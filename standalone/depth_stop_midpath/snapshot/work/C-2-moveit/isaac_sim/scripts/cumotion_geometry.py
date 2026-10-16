"""Calculation-only conservative geometry; no robot, ROS or simulator imports."""
import itertools
import struct

import numpy as np
from scipy.ndimage import binary_fill_holes, distance_transform_edt
from scipy.spatial import cKDTree


def read_closed_stl(path):
    data = path.read_bytes()
    if len(data) < 84:
        raise ValueError("Binary STL header missing")
    count = struct.unpack_from("<I", data, 80)[0]
    if not count or len(data) != 84 + 50 * count:
        raise ValueError("Only complete binary STL collision meshes are supported")
    dtype = np.dtype([("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")])
    raw = np.frombuffer(data, dtype=dtype, count=count, offset=84)["vertices"].reshape(-1, 3)
    if not np.isfinite(raw).all():
        raise ValueError("Nonfinite collision mesh")
    vertices, indices = np.unique(raw, axis=0, return_inverse=True)
    triangles = indices.reshape(-1, 3).astype(np.int32)
    edges = np.sort(np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]],
                                    triangles[:, [2, 0]]]), axis=1)
    _, multiplicity = np.unique(edges, axis=0, return_counts=True)
    if not np.all(multiplicity == 2):
        raise ValueError("Closed two-manifold collision mesh required")
    return vertices.astype(float), triangles


def voxel_envelope(vertices, triangles, pitch):
    """Cover every triangle AABB, then fill cells unreachable from outside.

    Marking the whole triangle AABB deliberately overestimates its surface.
    For a closed mesh, every interior cell is either marked or disconnected
    from the exterior. No physical mesh dimension is reduced.
    """
    if not np.isfinite(pitch) or pitch <= 0:
        raise ValueError("Positive finite voxel pitch required")
    origin = vertices.min(axis=0) - 2 * pitch
    shape = np.ceil(np.ptp(vertices, axis=0) / pitch).astype(int) + 5
    if np.prod(shape) > 2000000:
        raise ValueError("Model grid exceeds the bounded preparation budget")
    boundary = np.zeros(tuple(shape), dtype=bool)
    pending = list(vertices[triangles])
    while pending:
        triangle = pending.pop()
        # A long diagonal face's whole AABB can fill large empty regions.
        # Subdivision retains full coverage while bounding this overestimate.
        if np.ptp(triangle, axis=0).max() > pitch:
            pairs = [(0, 1), (1, 2), (2, 0)]
            a, b = max(pairs, key=lambda pair: np.linalg.norm(triangle[pair[0]] - triangle[pair[1]]))
            midpoint = (triangle[a] + triangle[b]) / 2
            first, second = triangle.copy(), triangle.copy()
            first[a], second[b] = midpoint, midpoint
            pending.extend([first, second])
            continue
        low = np.floor((triangle.min(axis=0) - origin - 1e-12) / pitch).astype(int)
        high = np.floor((triangle.max(axis=0) - origin + 1e-12) / pitch).astype(int) + 1
        boundary[tuple(slice(int(a), int(b)) for a, b in zip(low, high))] = True
    # Default connectivity is the same six-neighbour exterior flood fill.
    solid = binary_fill_holes(boundary)
    centres = origin + (np.argwhere(solid) + .5) * pitch
    return centres, float(np.sqrt(3) * pitch / 2), tuple(int(n) for n in shape)


def mesh_spheres(vertices, triangles, pitch, cumotion, margin=None):
    """Use native sphere placement, then cover whole occupied voxel cells.

    Native approximation alone is not accepted as proof of full mesh coverage.
    Increasing a sphere's radius to distance(cell centre)+cell circumradius
    covers that cell including its interior and all eight corners.
    """
    margin = 4 * pitch if margin is None else margin
    if not np.isfinite(margin) or margin < 0:
        raise ValueError("Nonnegative finite conservative sphere margin required")
    native = cumotion.generate_collision_spheres(vertices, triangles, max_overshoot=min(.001, pitch / 4),
                                                max_num_spheres=128, surface_point_density=300000,
                                                min_triangle_area=1e-12)
    if not native:
        raise ValueError("NVIDIA sphere generator returned empty collision geometry")
    positions = np.array([s.center for s in native], dtype=float)
    radii = np.array([s.radius for s in native], dtype=float)
    if not np.isfinite(positions).all() or not np.isfinite(radii).all() or np.any(radii <= 0):
        raise ValueError("Invalid native spheres")
    cells, cell_radius, shape = voxel_envelope(vertices, triangles, pitch)
    cell_tree = cKDTree(cells)
    witness = np.full(len(cells), -1, dtype=int)
    selected_positions, selected_radii = [], []
    def add_sphere(position, radius):
        neighbours = cell_tree.query_ball_point(position, max(0., radius - cell_radius))
        indices = np.array([i for i in neighbours if witness[i] < 0], dtype=int)
        if not len(indices):
            return
        witness[indices] = len(selected_radii)
        selected_positions.append(position)
        selected_radii.append(radius)
    # Native spheres are only seeds; they must cover whole cells to count.
    for position, radius in zip(positions, radii):
        add_sphere(position, radius + cell_radius + 1e-9)
    native_count = len(selected_radii)
    # Place additional large interior spheres rather than one per voxel.
    # The exterior-distance field keeps their radii local to the mesh shape.
    grid_indices = np.rint((cells - cells.min(axis=0)) / pitch).astype(int) + 1
    solid = np.zeros(tuple(grid_indices.max(axis=0) + 2), dtype=bool)
    solid[tuple(grid_indices.T)] = True
    distances = distance_transform_edt(solid)[tuple(grid_indices.T)] * pitch
    for i in np.argsort(-distances, kind="stable"):
        if witness[i] < 0:
            add_sphere(cells[i], distances[i] + cell_radius + margin + 1e-9)
    positions, expanded = np.array(selected_positions), np.array(selected_radii)
    if np.any(witness < 0):
        raise ValueError("Uncovered occupied voxel")
    # Independently verify one full-cell witness for every occupied cell.
    worst = float(np.max(np.linalg.norm(cells - positions[witness], axis=1) +
                         cell_radius - expanded[witness]))
    if worst > 1e-9:
        raise ValueError("Spheres fail to cover a full occupied cell")
    spheres = [dict(center=p.tolist(), radius=float(r)) for p, r in zip(positions, expanded)]
    return spheres, dict(pitch_m=pitch, grid_shape=shape, occupied_cells=len(cells),
                         sphere_count=len(spheres), full_cell_max_uncovered_m=worst,
                         supplemental_field_sphere_count=len(spheres) - native_count,
                         native_seed_sphere_count=native_count,
                         supplemental_radius_margin_m=margin,
                         max_native_radius_expansion_m=cell_radius + 1e-9,
                         closed_mesh_verified=True, conservative_voxel_cover_verified=True)


def box_cells(size, transform, pitch=.004):
    """Partition an entire solid box into cells bounded by circumspheres."""
    size = np.asarray(size, dtype=float)
    if size.shape != (3,) or not np.isfinite(size).all() or np.any(size <= 0):
        raise ValueError("Full positive box dimensions required")
    pitch = np.asarray(pitch, dtype=float)
    if pitch.shape not in ((), (3,)) or not np.isfinite(pitch).all() or np.any(pitch <= 0):
        raise ValueError("Positive scalar or XYZ cell pitch required")
    counts = np.ceil(size / pitch).astype(int)
    if np.prod(counts) > 10000:
        raise ValueError("Attachment sphere budget exceeded")
    cell = size / counts
    axes = [(np.arange(int(n)) + .5) * d - s / 2 for n, d, s in zip(counts, cell, size)]
    result = []
    for point in itertools.product(*axes):
        pose = transform.copy()
        pose[:3, 3] = transform[:3, :3] @ np.array(point) + transform[:3, 3]
        result.append(dict(size=cell.copy(), transform=pose))
    return result


def cell_spheres(cells):
    return [dict(center=c["transform"][:3, 3].tolist(), radius=float(np.linalg.norm(c["size"] / 2)) + 1e-9)
            for c in cells]


def box_spheres(size, transform, pitch=.004):
    return cell_spheres(box_cells(size, transform, pitch))


def split_box_cell(cell, axis):
    """Two exact half boxes preserve all of the original solid volume."""
    children = []
    for sign in (-1, 1):
        size, transform = cell["size"].copy(), cell["transform"].copy()
        size[axis] /= 2
        transform[:3, 3] += sign * size[axis] / 2 * transform[:3, axis]
        children.append(dict(size=size, transform=transform))
    return children


def object_boxes(obj, transform, padding=0):
    """Same body/stud boxes and offsets as moveit_step.cpp, in metres."""
    if "mesh_vertices_m" in obj or "mesh_triangles" in obj:
        raise ValueError("Mesh world inputs require a separate reviewed conversion")
    boxes = [(np.asarray(obj["size_m"], float) + 2 * padding, transform.copy())]
    if obj["studs"]:
        nx, ny = [int(round(s / .016)) for s in obj["size_m"][:2]]
        for x in range(nx):
            for y in range(ny):
                local = np.eye(4)
                local[:3, 3] = [(x - (nx - 1) / 2) * .016,
                               (y - (ny - 1) / 2) * .016, .01175]
                boxes.append((np.array([.01, .01, .0045]) + 2 * padding, transform @ local))
    return boxes


def cloud_node(link, points, cell_radius, source):
    """Enclose every complete cell in a partition, including its interior."""
    points = np.asarray(points, float)
    if points.ndim != 2 or points.shape[1] != 3 or not len(points) or not np.isfinite(points).all():
        raise ValueError("Finite nonempty XYZ cell centres required")
    if not np.isfinite(cell_radius) or cell_radius <= 0:
        raise ValueError("Positive full-cell circumradius required")
    centre = (points.min(axis=0) + points.max(axis=0)) / 2
    radius = float(np.max(np.linalg.norm(points - centre, axis=1))) + cell_radius + 1e-9
    return dict(link=link, points=points, cell_radius=cell_radius, source=source,
                center=centre, radius=radius)


def split_cloud(node):
    """Partition without removing, shrinking or duplicating any cell."""
    points = node["points"]
    if len(points) < 2:
        raise ValueError("Cannot subdivide a single full covered cell")
    axis = int(np.argmax(np.ptp(points, axis=0)))
    ordered = points[np.argsort(points[:, axis], kind="stable")]
    return [cloud_node(node["link"], p, node["cell_radius"], node["source"])
            for p in (ordered[:len(points)//2], ordered[len(points)//2:])]


def sphere_contacts(names, centres, radii, world_boxes, ignore):
    """Exact sphere/sphere and oriented cuboid signed overlap, in metres.

    This chooses where to refine the conservative cover. Acceptance still
    requires the independent NVIDIA inspector and original-mesh FCL checks.
    """
    bad, contacts = set(), []
    for identifier, size, transform in world_boxes:
        local = (centres - transform[:3, 3]) @ transform[:3, :3]
        delta = np.abs(local) - np.asarray(size) / 2
        signed = (np.linalg.norm(np.maximum(delta, 0), axis=1) +
                  np.minimum(np.max(delta, axis=1), 0) - radii)
        for i in np.where(signed < -1e-10)[0]:
            bad.add(int(i)); contacts.append((names[i], identifier, float(signed[i])))
    tree = cKDTree(centres)
    for i in range(len(centres)):
        for j in tree.query_ball_point(centres[i], radii[i] + radii.max()):
            if j <= i or names[i] == names[j] or frozenset((names[i], names[j])) in ignore:
                continue
            signed = np.linalg.norm(centres[i] - centres[j]) - radii[i] - radii[j]
            if signed < -1e-10:
                bad.update((i, j)); contacts.append((names[i], names[j], float(signed)))
    return bad, contacts
