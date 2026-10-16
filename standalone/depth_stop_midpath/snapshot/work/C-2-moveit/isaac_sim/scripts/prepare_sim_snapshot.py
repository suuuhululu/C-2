"""Read saved SIM scene/state files; never start Isaac, ROS or a calculator.

This internal draft is not a common A/D schema. Contract fixtures retain their
own source kind and are not FK-valid solver inputs or evidence of a SIM run.
"""
import argparse
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path

from sim_utils import save

SIM_KIND = 'SIM_TEST_STATE'
SIM_SCHEMA = 'sim-plan-only-input-draft/0.1.0'
SCENE_FIELDS = ('current', 'world_objects', 'final_approach_policy')
STATE_FIELDS = ('a_context', 'reservation_binding', 'q_rad', 'grip_rad', 'tcp_pose',
                'attachment_tcp_to_block', 'holding_confirmed', 'stopped_verified',
                'active_command_count', 'pending_command_count')


def prepare_sim_snapshot(scene_path, state_path):
    """Copy explicit saved values without inventing Current, joints or geometry."""
    documents, files = {}, {}
    for name, path, fields in (('scene', scene_path, SCENE_FIELDS), ('state', state_path, STATE_FIELDS)):
        path = Path(path).resolve(strict=True)
        raw = path.read_bytes()
        value = json.loads(raw)
        required = {*fields, 'schema_version', 'source_kind', 'capture_id', 'captured_at',
                    'execution_allowed', 'production_B_confirmed'}
        if not isinstance(value, dict) or not required <= value.keys():
            raise ValueError('Incomplete saved SIM '+name)
        if (value['schema_version'] != SIM_SCHEMA or
                value['source_kind'] not in ('SIM_CONTRACT_FIXTURE', 'ISAAC_SIM_SAVED_STATE') or
                not isinstance(value['capture_id'], str) or not value['capture_id'] or
                not isinstance(value['captured_at'], str) or
                value['production_B_confirmed'] is not False or value['execution_allowed'] is not False):
            raise ValueError('Explicit non-production, non-executable SIM source required')
        if any(value.get(g, False) is not False for g in (
                'execute', 'sim_execution_authorized', 'hardware_execution_allowed', 'a_execution_allowed')):
            raise ValueError('Saved SIM execution gate must remain false')
        if datetime.fromisoformat(value['captured_at']).tzinfo is None:
            raise ValueError('SIM capture timestamp must include timezone')
        documents[name] = value
        files[name] = dict(path=str(path), sha256=sha256(raw).hexdigest())
    scene, state = documents['scene'], documents['state']
    if any(scene[k] != state[k] for k in ('source_kind', 'capture_id', 'captured_at')):
        raise ValueError('SIM scene/state capture mismatch')
    if (scene.get('geometry_scope') != 'SIM_NOMINAL_GEOMETRY' or
            scene.get('model_scope') != 'SIM_NOMINAL_MODEL' or
            state.get('attachment_scope') != 'SIM_NOMINAL_ATTACHMENT'):
        raise ValueError('SIM nominal geometry/model/attachment labels required')
    provenance = dict(schema_version=SIM_SCHEMA, source_kind=scene['source_kind'],
        capture_id=scene['capture_id'], captured_at=scene['captured_at'], files=files,
        geometry_scope=scene['geometry_scope'], model_scope=scene['model_scope'],
        attachment_scope=state['attachment_scope'])
    return dict(**{k: deepcopy(scene[k]) for k in SCENE_FIELDS},
        **{k: deepcopy(state[k]) for k in STATE_FIELDS}, confirmation_kind=SIM_KIND,
        confirmed_by='SIM_FILE_SNAPSHOT', confirmed_at=scene['captured_at'],
        evidence_ref=Path(files['state']['path']).as_uri(), production_B_confirmed=False,
        geometry_scope=scene['geometry_scope'], geometry_evidence_ref=Path(files['scene']['path']).as_uri(),
        execution_allowed=False, simulation_provenance=provenance)


def validate_sim_snapshot(snapshot):
    """Bind preparation/consumption to the exact saved capture, including labels."""
    provenance = snapshot.get('simulation_provenance')
    files = provenance.get('files') if isinstance(provenance, dict) else None
    if not isinstance(files, dict) or set(files) != {'scene', 'state'}:
        raise ValueError('Explicit saved SIM provenance required')
    if any(not isinstance(files[k], dict) or set(files[k]) != {'path', 'sha256'} or
           any(not isinstance(v, str) or not v for v in files[k].values()) for k in files):
        raise ValueError('SIM source file path and SHA-256 required')
    expected = prepare_sim_snapshot(files['scene']['path'], files['state']['path'])
    if snapshot != expected:
        raise ValueError('SIM snapshot or source files differ from saved capture')
    return dict(production_B_confirmed=False, simulation_provenance=deepcopy(provenance))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('SIM snapshot output must be new; previous evidence is preserved')
    save(args.output, prepare_sim_snapshot(args.scene, args.state))
    print('SIM_SNAPSHOT_PREPARED_NO_PROCESS_RUN:', args.output)
