"""Explicit educational supply approval; offline binding, never a device API."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

EXCEPTIONS = {'yellow_2x2x1_01', 'yellow_2x2x1_02', 'yellow_2x2x1_03',
              'yellow_2x3x1_03', 'red_1x2x1_01'}


def read(path):
    return json.loads(Path(path).read_text())


def load(path):
    path = Path(path).resolve()
    registry = read(path)
    expected = {f'{c}_{k}_{i:02d}' for c, k in
                [('yellow','2x2x1'), ('yellow','2x3x1'), ('blue','2x2x1'),
                 ('blue','2x3x1'), ('red','1x2x1')] for i in range(1,6)}
    if (registry.get('schema_version') != 'educational-supply-execution/1'
            or registry.get('operator_conditional_execution_approved') is not True
            or registry.get('assembly_xy_correction_enabled') is not False
            or registry.get('all_slots_physically_verified') is not False
            or len(registry.get('slots', [])) != 25
            or {r['slot_id'] for r in registry['slots']} != expected):
        raise ValueError('EDUCATIONAL_SUPPLY_APPROVAL_REQUIRED')
    for source, digest in registry['source_sha256'].items():
        source_path = Path(source)
        if registry.get('source_path_basis') == 'BUNDLE_RELATIVE':
            if source_path.is_absolute() or not (path.parent/source_path).resolve().is_relative_to(path.parent):
                raise ValueError('SUPPLY_SOURCE_MUST_STAY_IN_BUNDLE:'+source)
        source_path = source_path if source_path.is_absolute() else path.parent/source_path
        if sha256(source_path.read_bytes()).hexdigest() != digest:
            raise ValueError('SUPPLY_EXECUTION_SOURCE_CHANGED:'+source)
    for relative, digest in registry['artifacts_sha256'].items():
        artifact = (path.parent/relative).resolve()
        if not artifact.is_relative_to(path.parent) or sha256(artifact.read_bytes()).hexdigest() != digest:
            raise ValueError('SUPPLY_EXECUTION_ARTIFACT_CHANGED:'+relative)
    for row in registry['slots']:
        mode = 'TEACHING_ONLY' if row['slot_id'] in EXCEPTIONS else 'RGBD_XY'
        if (row.get('execution_mode') != mode or row.get('execution_approved') is not True
                or row.get('automatic_depth_failure_fallback_enabled') is not False):
            raise ValueError('SUPPLY_SLOT_MODE_NOT_APPROVED:'+row['slot_id'])
    return registry


def bind(config, path):
    """Bind one native row. Preserve Z, attitude, jaw settings and motion parameters."""
    path = Path(path).resolve(); registry = load(path); cfg = deepcopy(config)
    if len(cfg.get('blocks', [])) != 1:
        raise ValueError('SUPPLY_SINGLE_ROW_REQUIRED')
    row = cfg['blocks'][0]
    sid = f"{row['color']}_{row['brick_type']}_{row['slot']:02d}"
    matches = [r for r in registry['slots'] if r['slot_id'] == sid]
    if len(matches) != 1: raise ValueError('SUPPLY_SLOT_NOT_APPROVED:'+sid)
    entry = matches[0]
    if (registry['connection'] != {k: cfg['connection'][k] for k in ('robot_id','tcp','tool')}
            or registry['observation_pose'] != cfg['observation_pose']):
        raise ValueError('SUPPLY_EXECUTION_SETUP_MISMATCH')
    original = deepcopy(row)
    if entry['execution_mode'] == 'TEACHING_ONLY' and row['pickup_pose'] != entry['pickup_pose']:
        raise ValueError('USE_REGISTERED_EXACT_TEACHING_POSE:'+sid)
    if entry['reference_basis'] == 'PAIRED_MEASURED_AND_SINGLE_GRASP_TESTED':
        from app.assembly_motion import pose_error
        if max(pose_error(row['pickup_pose'], entry['pickup_pose'])[1:]) > .1 or abs(row['pickup_pose'][2]-entry['pickup_pose'][2]) > .1:
            raise ValueError('PAIRED_SUPPLY_HEIGHT_ATTITUDE_MISMATCH_USE_MATCHED_SCENARIO:'+sid)
        row['pickup_pose'][:2] = entry['pickup_pose'][:2]
    row.pop('center_mapping', None)
    cfg['assembly_xy_correction_enabled'] = False
    cfg['vision_xy_alignment'] = False
    cfg['vision']['layout'] = str(path.parent/'layout.json')
    cfg['vision']['center_basis'] = 'STUD_ARRAY'
    cfg['vision']['backend'] = 'opencv_studs'
    cfg['vision'].pop('depth_center_profile', None)
    cfg['educational_supply_binding'] = dict(registry=str(path),
        registry_sha256=sha256(path.read_bytes()).hexdigest(), slot_id=sid,
        execution_mode=entry['execution_mode'], original_row=original,
        reference_basis=entry['reference_basis'])
    if entry['execution_mode'] == 'RGBD_XY':
        cfg['vision']['depth_center_profile'] = str(path.parent/entry['depth_profile'])
    return cfg


def bound_depth_profile(path, profile, config):
    """Authenticate a static per-slot profile before adapting its row identity."""
    binding = config.get('educational_supply_binding', {})
    registry_path = Path(binding.get('registry', ''))
    registry = load(registry_path)
    if sha256(registry_path.read_bytes()).hexdigest() != binding.get('registry_sha256'):
        raise ValueError('SUPPLY_EXECUTION_REGISTRY_CHANGED')
    entries = [r for r in registry['slots'] if r['slot_id'] == binding.get('slot_id')]
    if len(entries) != 1 or entries[0]['execution_mode'] != 'RGBD_XY':
        raise ValueError('SUPPLY_RGBD_SLOT_APPROVAL_REQUIRED')
    entry = entries[0]
    if (Path(path).resolve() != (registry_path.parent/entry['depth_profile']).resolve()
            or config.get('assembly_xy_correction_enabled') is not False
            or binding != bind(dict(config, blocks=[deepcopy(binding['original_row'])]), registry_path)['educational_supply_binding']):
        raise ValueError('SUPPLY_EXECUTION_BINDING_MISMATCH')
    expected = bind(dict(config, blocks=[deepcopy(binding['original_row'])]), registry_path)
    if config['blocks'] != expected['blocks']:
        raise ValueError('SUPPLY_EXECUTION_ROW_CHANGED')
    result = deepcopy(profile)
    result['references'][0]['pickup_pose'] = config['blocks'][0]['pickup_pose'].copy()
    return result
