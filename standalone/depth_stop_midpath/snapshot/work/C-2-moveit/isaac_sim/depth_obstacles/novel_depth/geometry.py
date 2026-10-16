"""Pinned visual surfaces for CPU Depth comparison; no scene enumeration."""
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import struct
from types import MappingProxyType
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial.transform import Rotation

from prepare_cpu_model import read_model_bundle
from held_geometry_inputs import nominal_definition
from cumotion_geometry import object_boxes


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _pin(ref):
    raw = Path(ref['path']).read_bytes()
    if sha256(raw).hexdigest() != ref['sha256']:
        raise ValueError('SOURCE_CHANGED:' + ref['path'])
    return deepcopy(ref)


def _immutable(value):
    if isinstance(value, np.ndarray):
        # A bytes backing store also prevents setflags(write=True) by a caller.
        return np.frombuffer(value.tobytes(), dtype=value.dtype).reshape(value.shape)
    if isinstance(value, Mapping):
        return MappingProxyType({k: _immutable(v) for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_immutable(v) for v in value)
    return value


def _rigid(value):
    t = np.asarray(value, dtype=float)
    if (t.shape != (4, 4) or not np.isfinite(t).all() or
            not np.array_equal(t[3], [0., 0., 0., 1.]) or
            not np.allclose(t[:3, :3].T @ t[:3, :3], np.eye(3), atol=1e-8, rtol=0) or
            not np.isclose(np.linalg.det(t[:3, :3]), 1., atol=1e-8, rtol=0)):
        raise ValueError('FINITE_RIGID_TRANSFORM_REQUIRED')
    return t


def _origin(item):
    t = np.eye(4)
    if item is not None:
        t[:3, :3] = Rotation.from_euler('xyz', np.array(item.get('rpy', '0 0 0').split(), float)).as_matrix()
        t[:3, 3] = np.array(item.get('xyz', '0 0 0').split(), float)
    return _rigid(t)


def _pose(item):
    if item['frame_id'] != 'base_link':
        raise ValueError('STATIC_BASE_LINK_POSE_REQUIRED')
    t = np.eye(4)
    t[:3, :3] = Rotation.from_quat(item['quaternion_xyzw']).as_matrix()
    t[:3, 3] = item['xyz_m']
    return _rigid(t)


def _box_triangles(size):
    size = np.asarray(size, float)
    if size.shape != (3,) or not np.isfinite(size).all() or np.any(size <= 0):
        raise ValueError('FINITE_POSITIVE_BOX_REQUIRED')
    vertices = np.array([[x, y, z] for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)]) * size
    faces = [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
             [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]]
    return vertices[faces]


def _transform(triangles, transform):
    return triangles @ transform[:3, :3].T + transform[:3, 3]


def _visual_triangles(mesh):
    uri = urlparse(mesh.get('filename'))
    if uri.scheme != 'file' or uri.netloc:
        raise ValueError('LOCAL_VISUAL_STL_REQUIRED')
    path = Path(unquote(uri.path))
    raw = path.read_bytes()
    if len(raw) < 84:
        raise ValueError('BINARY_VISUAL_STL_REQUIRED')
    count = struct.unpack_from('<I', raw, 80)[0]
    if count == 0 or len(raw) != 84 + 50 * count:
        raise ValueError('COMPLETE_BINARY_VISUAL_STL_REQUIRED')
    dtype = np.dtype([('normal', '<f4', (3,)), ('vertices', '<f4', (3, 3)), ('attribute', '<u2')])
    scale = np.array(mesh.get('scale', '1 1 1').split(), float)
    if scale.shape != (3,) or not np.isfinite(scale).all() or np.any(scale <= 0):
        raise ValueError('VISUAL_SCALE_REQUIRED')
    triangles = np.frombuffer(raw, dtype=dtype, count=count, offset=84)['vertices'].astype(float) * scale
    if not np.isfinite(triangles).all():
        raise ValueError('NONFINITE_VISUAL_MESH')
    return triangles, dict(path=str(path), sha256=sha256(raw).hexdigest(), scale=scale.tolist())


def freeze_known_geometry(static_snapshot, model_bundle, held_definition, approved_static_ids, source_refs):
    """Freeze an explicitly approved pre-obstacle subset, never a live USD stage.

    static_snapshot: session_id, clock_epoch, freeze_source_time, map_scope,
    T_world_base, world_objects. map_scope is PRE_OBSTACLE_APPROVED,
    ARCHIVED_SUBSET_REPLAY_ONLY or FIXTURE. Caller owns that provenance decision.
    source_refs is a nonempty sequence of pinned {path,sha256} records.
    Returned arrays and nested metadata are immutable. No collision padding.
    """
    s = deepcopy(static_snapshot)
    if s['map_scope'] not in ('PRE_OBSTACLE_APPROVED', 'ARCHIVED_SUBSET_REPLAY_ONLY', 'FIXTURE'):
        raise ValueError('EXPLICIT_PRE_OBSTACLE_MAP_SCOPE_REQUIRED')
    if (not s['session_id'] or type(s['clock_epoch']) is not int or s['clock_epoch'] < 0 or
            not np.isfinite(s['freeze_source_time'])):
        raise ValueError('MAP_SOURCE_IDENTITY_REQUIRED')
    if not source_refs:
        raise ValueError('PINNED_MAP_SOURCES_REQUIRED')
    refs = [_pin(r) for r in source_refs]
    bundle = read_model_bundle(model_bundle['bundle_path'] if isinstance(model_bundle, Mapping) else model_bundle)
    if isinstance(model_bundle, Mapping) and bundle != model_bundle:
        raise ValueError('MODEL_BUNDLE_CHANGED')
    manifest_raw = (Path(bundle['bundle_path'])/'MODEL_MANIFEST.json').read_bytes()
    if sha256(manifest_raw).hexdigest() != bundle['manifest_sha256']:
        raise ValueError('MODEL_MANIFEST_CHANGED_DURING_FREEZE')
    mesh_pins = json.loads(manifest_raw)['meshes']
    definition = nominal_definition(held_definition['geometry'], bundle)
    if definition != held_definition:
        raise ValueError('HELD_DEFINITION_CHANGED')
    ids = tuple(approved_static_ids)
    objects = {o['id']: o for o in s['world_objects']}
    if len(objects) != len(s['world_objects']) or len(set(ids)) != len(ids) or any(i not in objects for i in ids):
        raise ValueError('UNIQUE_APPROVED_STATIC_IDS_REQUIRED')
    if definition['geometry']['id'] in ids:
        raise ValueError('HELD_BLOCK_MUST_NOT_BE_STATIC')
    world_base = _rigid(s['T_world_base'])
    static = []
    for name in ids:
        obj = objects[name]
        for size, local in object_boxes(obj, _pose(obj['pose']), padding=0.):
            static.append(_transform(_box_triangles(size), world_base @ local))
    robot = ET.fromstring(bundle['robot_description'])
    visuals = []
    for link in robot.findall('link'):
        for index, visual in enumerate(link.findall('visual')):
            mesh = visual.find('geometry/mesh')
            if mesh is None:
                raise ValueError('UNSUPPORTED_ROBOT_VISUAL_GEOMETRY')
            triangles, pin = _visual_triangles(mesh)
            if mesh_pins[pin['path']] != pin['sha256']:
                raise ValueError('VISUAL_CHANGED_DURING_FREEZE')
            visuals.append(dict(link=link.get('name'), index=index, triangles=_transform(triangles, _origin(visual.find('origin'))), mesh=pin))
    if not visuals:
        raise ValueError('ROBOT_VISUAL_SURFACES_REQUIRED')
    held = [_transform(_box_triangles(size), local) for size, local in object_boxes(definition['geometry'], np.eye(4), padding=0.)]
    metadata = dict(session_id=s['session_id'], clock_epoch=s['clock_epoch'], freeze_source_time=s['freeze_source_time'],
        map_scope=s['map_scope'], approved_static_ids=list(ids), model_manifest_sha256=bundle['manifest_sha256'],
        static_objects=[objects[i] for i in ids], T_world_base=world_base.tolist(), held_definition=definition,
        visual_inventory=[dict(link=v['link'], index=v['index'], triangle_count=len(v['triangles']), mesh=v['mesh']) for v in visuals], source_refs=refs)
    return _immutable(dict(metadata=metadata, digest=_digest(metadata), robot_description=bundle['robot_description'],
        static_world_triangles=np.concatenate(static) if static else np.empty((0, 3, 3)),
        robot_visuals=visuals, held_block_triangles=np.concatenate(held), coverage='APPROVED_SURFACES_ONLY_NOT_COMPLETE_WORLD'))
