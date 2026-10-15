"""Conservative Depth ray evidence of clear grid columns; never ROI-as-empty."""
import cv2
import numpy as np


def empty_column_evidence(depth, scale, intrinsics, camera_to_board, config, *, object_mask=None,
                          _minimum_layers=None):
    """Every valid sampled ray must reach beyond its allowed volume.

    Columns span all five layers, excluding the board/stud allowance at the base.
    Sparse zero Depth may be tolerated by an explicit quality threshold. Measured
    occluders, out-of-range values and clipped columns still leave unknown.
    This is calibrated geometry evidence, not a safety detector/ground-truth label.
    """
    from itertools import product
    from .depth_grid import deproject_pixels, validate_geometry
    if depth.ndim != 2 or depth.dtype != np.uint16:
        raise ValueError('original aligned uint16 Depth required')
    if object_mask is not None and (object_mask.shape != depth.shape or object_mask.dtype != bool):
        raise ValueError('object exclusion mask must match aligned Depth')
    transform = validate_geometry(scale, intrinsics, camera_to_board)
    minimum_fraction = config.get('empty_min_valid_fraction', 1.0)
    if not np.isfinite(minimum_fraction) or not 0 < minimum_fraction <= 1:
        raise ValueError('empty_min_valid_fraction must be in (0, 1]')
    model = intrinsics['model']
    if model not in ('none', 'brown_conrady'):
        raise ValueError('empty-column projection requires none/brown_conrady distortion')
    if config.get('layer_height_reference') != 'BOARD_FLAT_SURFACE_ZERO' or len(config['top_heights_m']) != 5:
        raise ValueError('explicit flat-board five-layer profile required')
    camera_from_board = np.linalg.inv(transform)
    rvec, _ = cv2.Rodrigues(camera_from_board[:3, :3])
    k = np.array([[intrinsics['fx'], 0., intrinsics['cx']],
                  [0., intrinsics['fy'], intrinsics['cy']], [0., 0., 1.]])
    distortion = np.zeros(5) if model == 'none' else np.asarray(intrinsics['coefficients'])
    pitch = config['stud_pitch_m']
    bottom = config['board_stud_height_m'] + config['height_tolerance_m']
    top = config['top_heights_m'][-1] + config['height_tolerance_m']
    if not 0 <= bottom < top:
        raise ValueError('invalid clear-column height bounds')
    regions = []
    rejected = dict(clipped=0, support=0, invalid_depth=0, missing_depth=0,
                    depth_out_of_range=0, blocked=0)
    for y in range(24):
        for x in range(24):
            first_layer = 1 if _minimum_layers is None else _minimum_layers.get((x, y), 6)
            if first_layer > 5:
                continue
            # A measured lower block is not empty. Test only the volume above its
            # permitted top, and still require Depth rays to clear that volume.
            column_bottom = (bottom if first_layer == 1 else
                             config['top_heights_m'][first_layer - 2] + config['height_tolerance_m'])
            low = np.array([(x - .5) * pitch, (y - .5) * pitch, column_bottom])
            high = np.array([(x + .5) * pitch, (y + .5) * pitch, top])
            corners = np.array(list(product(*zip(low, high))))
            camera = corners @ camera_from_board[:3, :3].T + camera_from_board[:3, 3]
            if np.any(camera[:, 2] <= 0):
                rejected['clipped'] += 1
                continue
            pixels, _ = cv2.projectPoints(corners, rvec, camera_from_board[:3, 3], k, distortion)
            pixels = pixels.reshape(-1, 2)
            if (not np.isfinite(pixels).all() or np.any(pixels < 0) or
                    np.any(pixels > [depth.shape[1] - 1, depth.shape[0] - 1])):
                rejected['clipped'] += 1
                continue
            left, upper = np.floor(pixels.min(0)).astype(int)
            right, lower = np.ceil(pixels.max(0)).astype(int)
            mask = np.zeros((lower - upper + 1, right - left + 1), np.uint8)
            hull = cv2.convexHull((pixels - [left, upper]).astype(np.float32))
            cv2.fillConvexPoly(mask, np.rint(hull).astype(np.int32), 1)
            vv, uu = np.nonzero(mask)
            u, v = uu + left, vv + upper
            # Ray parameter is camera optical Z, exactly the published Depth unit.
            if model == 'none' or not np.any(distortion):
                rays = np.column_stack(((u - intrinsics['cx']) / intrinsics['fx'],
                                        (v - intrinsics['cy']) / intrinsics['fy'], np.ones(len(u))))
            else:
                rays = deproject_pixels(u, v, np.ones(len(u)), intrinsics, depth.shape[1], depth.shape[0])
            directions = rays @ transform[:3, :3].T
            origin = transform[:3, 3]
            near, far = np.full(len(u), -np.inf), np.full(len(u), np.inf)
            for axis in range(3):
                parallel = np.abs(directions[:, axis]) < 1e-12
                divisor = np.where(parallel, 1., directions[:, axis])
                a, b = (low[axis] - origin[axis]) / divisor, (high[axis] - origin[axis]) / divisor
                axis_near, axis_far = np.minimum(a, b), np.maximum(a, b)
                axis_near[parallel], axis_far[parallel] = -np.inf, np.inf
                if not low[axis] <= origin[axis] <= high[axis]:
                    axis_far[parallel] = -np.inf
                near, far = np.maximum(near, axis_near), np.minimum(far, axis_far)
            intersects = (far >= np.maximum(near, 0)) & np.isfinite(far)
            if intersects.sum() < config['min_depth_pixels']:
                rejected['support'] += 1
                continue
            if object_mask is not None and np.any(object_mask[v[intersects], u[intersects]]):
                rejected['blocked'] += 1
                continue
            observed = depth[v[intersects], u[intersects]].astype(float) * scale
            valid = observed > 0
            out_of_range = valid & ((observed < config['min_depth_m']) |
                                    (observed > config['max_depth_m']))
            if (np.any(out_of_range) or valid.sum() < config['min_depth_pixels'] or
                    valid.mean() < minimum_fraction):
                rejected['invalid_depth'] += 1
                rejected['missing_depth'] += int(np.any(observed == 0))
                rejected['depth_out_of_range'] += int(np.any((observed > 0) & (
                    (observed < config['min_depth_m']) | (observed > config['max_depth_m']))))
                continue
            if np.any(observed[valid] < far[intersects][valid]):
                rejected['blocked'] += 1
                continue
            # Same observed clear volume proves each permitted layer, not hidden history.
            regions.extend(dict(x=x, y=y, width=1, height=1, layer=layer)
                           for layer in range(first_layer, 6))
    return dict(verified_regions=regions, verification_basis=(dict(
        kind='DEPTH_RAYS_CLEAR_FIVE_LAYER_COLUMN', calibration_id=config['calibration_id'],
        height_reference='BOARD_FLAT_SURFACE_ZERO', volume_bottom_m=bottom, volume_top_m=top,
        all_sampled_rays_required=minimum_fraction == 1.0,
        minimum_valid_fraction=minimum_fraction,
        minimum_valid_pixels=config['min_depth_pixels'],
        spatial_scope='CALIBRATED_BOARD_3D_COLUMNS_NOT_RGB_ROI',
        missing_depth_policy='ZERO_ONLY; ALL_NONZERO_RAYS_MUST_CLEAR') if regions else None),
        rejection_counts=rejected)


def empty_above_block_evidence(depth, scale, intrinsics, camera_to_board, config, *,
                               occupied_regions, object_mask=None):
    """Depth proof above measured footprints; never infer hidden lower layers.

    Only use this with the authority View's measured occupied regions. Unknown
    instance masks remain excluded. An occupied footprint alone proves no air.
    """
    from .contracts import region_cells
    minimum = {}
    for x, y, layer in region_cells(occupied_regions):
        minimum[x, y] = max(minimum.get((x, y), 1), layer + 1)
    evidence = empty_column_evidence(depth, scale, intrinsics, camera_to_board, config,
                                    object_mask=object_mask, _minimum_layers=minimum)
    if evidence['verification_basis'] is not None:
        evidence['verification_basis'].update(
            kind='DEPTH_RAYS_CLEAR_ABOVE_MEASURED_BLOCK', calibration_id=config['calibration_id'],
            height_reference='BOARD_FLAT_SURFACE_ZERO',
            lower_bound_basis='MEASURED_LAYER_NOMINAL_TOP_PLUS_EXISTING_TOLERANCE',
            column_minimum_layers=[dict(x=x, y=y, first_empty_layer=layer)
                                   for (x, y), layer in sorted(minimum.items()) if layer <= 5],
            volume_top_m=config['top_heights_m'][-1] + config['height_tolerance_m'])
    return evidence
