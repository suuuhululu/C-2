"""Explicit known SIM background added before baseline, mapping and planning."""
import copy
import numpy as np
from sim_utils import pose_matrix,matrix_pose,save


def reference_plate(objects):
    byid={obj['id']:obj for obj in objects}
    supply=np.asarray(byid['SupplyBoard']['pose']['xyz_m'])
    assembly=np.asarray(byid['AssemblyBoard']['pose']['xyz_m'])
    # Small known support at the middle transport arc; no broad background plane.
    center=[float((supply[0]+assembly[0])/2),float(max(supply[1],assembly[1])+.32),.028]
    return dict(id='MidpathReferencePlate',role='OTHER_OBSTACLE',pose=dict(frame_id='base_link',xyz_m=center,quaternion_xyzw=[0,0,0,1]),size_m=[.045,.045,.004],studs=False,prim_path='/World/Environment/MidpathReferencePlate',coordinate_kind='SIM_BODY_CENTRE',geometry_evidence_ref='EXPLICIT_SMALL_SUPPORT_BEFORE_BASELINE')


def style_scene(stage,seed,baseline,out):
    """Apply the user's scene edits before any native capture or known-map freeze."""
    from pxr import UsdGeom,Gf
    removed=[obj for obj in seed['world_objects'] if obj['id']=='HandoverTray']
    if len(removed)!=1 or removed[0]['prim_path']!='/World/Environment/HandoverTray':raise ValueError('EXACT_UNUSED_HANDOVER_TRAY_REQUIRED')
    if sum(obj['id']=='HandoverTray' for obj in baseline['planning_snapshot']['world_objects'])!=1:raise ValueError('HANDOVER_TRAY_BASELINE_MISMATCH')
    if not stage.RemovePrim(removed[0]['prim_path']):raise ValueError('HANDOVER_TRAY_USD_REMOVAL_FAILED')
    seed['world_objects']=[obj for obj in seed['world_objects'] if obj['id']!='HandoverTray']
    updated=copy.deepcopy(baseline)
    updated['planning_snapshot']['world_objects']=[obj for obj in updated['planning_snapshot']['world_objects'] if obj['id']!='HandoverTray']
    for name in ('SupplyBoard','AssemblyBoard'):
        body=UsdGeom.Cube(stage.GetPrimAtPath('/World/Environment/'+name+'/Body'))
        if not body:raise ValueError('BOARD_BODY_REQUIRED:'+name)
        body.CreateDisplayColorAttr([Gf.Vec3f(.08,.55,.16)])
    save(out/'scene_style.json',dict(removed_static_ids=['HandoverTray'],green_board_ids=['SupplyBoard','AssemblyBoard'],board_display_color=[.08,.55,.16],known_background='SMALL_SUPPORT_ONLY',obstacle_support_footprint='EXACT_OBSTACLE_XY',detector_algorithm_changed=False))
    return updated


def baseline_with_reference_plate(baseline,plate):
    """Register the explicitly authored plate; preserve strict original world checks."""
    if plate['id']!='MidpathReferencePlate' or plate['role']!='OTHER_OBSTACLE' or plate['prim_path']!='/World/Environment/MidpathReferencePlate':raise ValueError('EXPLICIT_REFERENCE_PLATE_REQUIRED')
    if any(obj['id']==plate['id'] for obj in baseline['planning_snapshot']['world_objects']):raise ValueError('DUPLICATE_BASELINE_REFERENCE_PLATE')
    updated=copy.deepcopy(baseline)
    updated['planning_snapshot']['world_objects'].append(copy.deepcopy(plate))
    return updated


def add_reference_plate(stage,seed,base,out):
    from pxr import UsdGeom,UsdPhysics,Gf
    if any(obj['id']=='MidpathReferencePlate' for obj in seed['world_objects']):raise ValueError('DUPLICATE_REFERENCE_PLATE')
    plate=reference_plate(seed['world_objects']);world=np.asarray(base)@pose_matrix(plate['pose'])
    plate['world_pose']=matrix_pose(world);plate['world_pose']['frame_id']='world'
    root=UsdGeom.Xform.Define(stage,plate['prim_path']);root.AddTransformOp().Set(Gf.Matrix4d(world.T))
    body=UsdGeom.Cube.Define(stage,plate['prim_path']+'/Body');body.CreateSizeAttr(1.)
    body.AddScaleOp(precision=UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(*plate['size_m']));body.CreateDisplayColorAttr([Gf.Vec3f(.7,.25,.12)])
    UsdPhysics.CollisionAPI.Apply(body.GetPrim())
    seed['world_objects'].append(copy.deepcopy(plate))
    save(out/'reference_plate_setup.json',dict(scope='EXPLICIT_KNOWN_STATIC_BACKGROUND_BEFORE_BASELINE_AND_UNKNOWN_ACTOR',object=plate,obstacle_created=False,known_before_baseline=True,detector_algorithm_changed=False))
    return plate
