"""Create a nominal 1..5 SIM scene, without playback, ROS or robot commands.

The seed is a test layout, not a saved post-grasp observation. Existing teaching
and six-slot geometry remain untouched; only occupied supply bodies are filtered.
"""
import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path
import json

import numpy as np
from scipy.spatial.transform import Rotation

from plan_only import checked_pose, digest, vector
from sim_utils import matrix_pose, pose_matrix, rigid, save
from taught_moveit import GROUPS
from planning_trial.assembly_adapter import handle_step_motion
from planning_trial.planner import block_key

ROOT = Path(__file__).resolve().parents[1]
SEED_SCHEMA = 'sim-scene-seed-draft/0.1.0'
BASE_PRIM = '/World/Robot/Geometry/world/base_link'
TCP_PRIM = BASE_PRIM+'/link_1/link_2/link_3/link_4/link_5/link_6/GripperDA_v4_tcp'


def scene_seed(model, motion_request):
    motion = handle_step_motion(deepcopy(motion_request))
    if motion['status'] != 'CANDIDATE' or motion['execution_allowed'] is not False:
        raise ValueError('Shared-A calculation candidate required')
    if model['current'] != motion_request['latest_current']:
        raise ValueError('Scene model and latest Current differ')
    if Counter(block_key(b['block']) for b in model['current_models']) != Counter(
            map(block_key, model['current']['blocks'])):
        raise ValueError('Scene needs every Current block exactly once')
    slot = motion_request['reserved_supply_slot']
    if type(slot['slot_index']) is not int or not 1 <= slot['slot_index'] <= 5:
        raise ValueError('Reservation must use supply slot 1..5')
    objects = []

    def body(name, role, centre, size, yaw=0, block=None, index=None):
        vector(centre, 3)
        if any(v <= 0 for v in vector(size, 3)):
            raise ValueError('Positive body dimensions required')
        pose = dict(frame_id='base_link', xyz_m=list(centre),
                    quaternion_xyzw=Rotation.from_euler('z', yaw).as_quat().tolist())
        checked_pose(pose)
        row = dict(id=name, role=role, pose=pose, size_m=list(size), studs=block is not None,
                   coordinate_kind='SIM_BODY_CENTRE', geometry_evidence_ref='SIM_NOMINAL_LAYOUT',
                   prim_path='/World/Environment/'+name)
        if block is not None:
            nx, ny, _ = map(int, block['brick_type'].split('x'))
            if not np.allclose(size, [nx*.016, ny*.016, .019], atol=1e-9, rtol=0):
                raise ValueError('Full block dimensions required')
            row['block'] = deepcopy(block)
        if index is not None:
            row['slot_index'] = index
        objects.append(row)

    boards = model.get('board_models')
    if boards is not None:
        if len(boards)!=2 or {b['role'] for b in boards}!={'SUPPLY_BOARD','ASSEMBLY_BOARD'}:
            raise ValueError('Exactly two explicit nominal board models required')
        for row in boards:
            body(row['id'], row['role'], row['centre_m'], row['size_m'], row['yaw_rad'])
    for name, role, points, padding in (() if boards is not None else (
            ('SupplyBoard', 'SUPPLY_BOARD', model['supply']['outline_m'], 0),
            ('AssemblyBoard', 'ASSEMBLY_BOARD', model['assembly_grid_lines_m'], .016))):
        points = np.asarray(points).reshape(-1, 3)
        lo, hi = points.min(0), points.max(0)
        body(name, role, ((lo[:2]+hi[:2])/2).tolist()+[float(lo[2]-.002)],
             (hi[:2]-lo[:2]+padding).tolist()+[.004])
    for i, row in enumerate(model['current_models']):
        body('Current_'+str(i), 'CURRENT_BLOCK', row['centre_m'], row['size_m'], row['yaw_rad'], row['block'])
    slots = [s for s in model['supply']['slots'] if (s['color'], s['brick_type']) in GROUPS and 1 <= s['slot_index'] <= 5]
    expected = {f'{color}_{kind}_{i:02d}' for color, kind in GROUPS for i in range(1, 6)}
    if len(slots) != 25 or {s['slot_id'] for s in slots} != expected:
        raise ValueError('Explicit nominal bodies for all five groups, slots 1..5 required')
    for row in slots:
        block = dict(color=row['color'], brick_type=row['brick_type'])
        if row['slot_id'] == slot['slot_id']:
            block = deepcopy(motion_request['selected_step']['after'])
        body(row['slot_id'], 'SUPPLY_BLOCK', row['centre_m'], row['size_m'], row['yaw_rad'], block, row['slot_index'])
    for row in model.get('obstacle_models', []):
        body(row['id'], 'OTHER_OBSTACLE', row['centre_m'], row['size_m'], row['yaw_rad'])
    if 'tray_model' in model:
        row = model['tray_model']
        body('HandoverTray', 'OTHER_OBSTACLE', row['centre_m'], row['size_m'], row['yaw_rad'])
    if slot['slot_id'] not in expected:
        raise ValueError('Reserved supply identity differs from nominal inventory')
    if len({o['id'] for o in objects}) != len(objects):
        raise ValueError('Scene object identities must be unique')
    return dict(schema_version=SEED_SCHEMA, source_kind='SIM_NOMINAL_SCENE_SEED',
        execution_allowed=False, production_B_confirmed=False, post_grasp_observed=False,
        current=deepcopy(model['current']), a_context=deepcopy(motion['context']),
        reservation_binding=deepcopy(motion['reservation_binding']), motion_input_digest=digest(motion_request),
        world_objects=objects, geometry_scope='SIM_NOMINAL_GEOMETRY', model_scope='SIM_NOMINAL_MODEL',
        final_approach_policy=json.loads((ROOT/'config/precontact.plan_only.json').read_text()),
        supply_policy=dict(slot_count=5, unavailable_slots=[6], always_replenished=True),
        omitted_legacy_slots=model.get('omitted_legacy_slots',[s['slot_id'] for s in model['supply']['slots'] if s['slot_id'] not in expected]),
        nominal_physics=dict(block_mass_kg=.02, friction=.6, measured=False),
        robot_base_prim=BASE_PRIM, robot_tcp_prim=TCP_PRIM,
        **{k:deepcopy(model[k]) for k in ('coordinate_provenance','d_gripper_reference','nominal_geometry_evidence') if k in model})


def write_usd_scene(seed, output, robot_stage):
    """USD authoring only. Import pxr from the installed Isaac USD runtime."""
    from pxr import Usd, UsdGeom, UsdPhysics, UsdShade, UsdLux, Gf
    output, robot_stage = Path(output), Path(robot_stage).resolve(strict=True)
    if output.exists():
        raise ValueError('Scene output must be new')
    stage = Usd.Stage.CreateNew(str(output))
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    world = UsdGeom.Xform.Define(stage, '/World')
    stage.SetDefaultPrim(world.GetPrim())
    world.GetPrim().GetReferences().AddReference(str(robot_stage), '/World')
    base = stage.GetPrimAtPath(seed['robot_base_prim'])
    if not base or not stage.GetPrimAtPath(seed['robot_tcp_prim']):
        raise ValueError('Referenced SIM robot lacks base/TCP')
    world_base = rigid(np.asarray(UsdGeom.Xformable(base).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T)
    alignment = dict(world_frame_id='world', base_frame_id='base_link', T_world_base=world_base.tolist(),
                     evidence_ref='USD_BASE_PRIM:'+seed['robot_base_prim'])
    material = UsdShade.Material.Define(stage, '/World/NominalContactMaterial')
    physics = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics.CreateStaticFrictionAttr(.6); physics.CreateDynamicFrictionAttr(.6); physics.CreateRestitutionAttr(0)
    for row in seed['world_objects']:
        transform = world_base @ checked_pose(row['pose'])
        xform = UsdGeom.Xform.Define(stage, row['prim_path'])
        xform.AddTransformOp().Set(Gf.Matrix4d(transform.T.tolist()))
        parts = [('Body', [0,0,0], row['size_m'])]
        if row['studs']:
            nx, ny, _ = map(int, row['block']['brick_type'].split('x'))
            parts += [(f'Stud_{i}_{j}', [(i-(nx-1)/2)*.016, (j-(ny-1)/2)*.016, .01175], [.01,.01,.0045])
                      for i in range(nx) for j in range(ny)]
        color = {'yellow':(1,.8,.1), 'blue':(.1,.3,.9), 'red':(.9,.04,.04)}.get(row.get('block', {}).get('color'), (.4,.45,.4))
        for name, position, size in parts:
            cube = UsdGeom.Cube.Define(stage, row['prim_path']+'/'+name)
            cube.CreateSizeAttr(1)
            cube.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(*position))
            cube.AddScaleOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(*size))
            cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
            UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
            UsdShade.MaterialBindingAPI.Apply(cube.GetPrim()).Bind(material, materialPurpose='physics')
        if row['role'] == 'SUPPLY_BLOCK':
            UsdPhysics.RigidBodyAPI.Apply(xform.GetPrim())
            UsdPhysics.MassAPI.Apply(xform.GetPrim()).CreateMassAttr(.02)
    physics_scene = UsdPhysics.Scene.Define(stage, '/World/PhysicsScene')
    physics_scene.CreateGravityDirectionAttr(Gf.Vec3f(0,0,-1)); physics_scene.CreateGravityMagnitudeAttr(9.81)
    UsdLux.DomeLight.Define(stage, '/World/Light').CreateIntensityAttr(1000)
    stage.GetRootLayer().customLayerData = dict(scope='SIM_NOMINAL_SCENE_SEED_NOT_POST_GRASP', seed_digest=digest(seed))
    stage.GetRootLayer().Save()
    return alignment


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('model', 'motion-request', 'output-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--robot-stage', type=Path, default=ROOT/'assets/aligned_robot.sim.usda')
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError('Scene directory must be new')
    seed = scene_seed(json.loads(args.model.read_text()), json.loads(args.motion_request.read_text()))
    args.output_dir.mkdir(parents=True)
    alignment = write_usd_scene(seed, args.output_dir/'scene.usda', args.robot_stage)
    save(args.output_dir/'scene.seed.json', seed)
    save(args.output_dir/'frame_alignment.seed.json', alignment)
    print('NOMINAL_SIM_SCENE_CREATED_NO_PLAYBACK:', args.output_dir)
