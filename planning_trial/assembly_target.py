"""Nominal TCP candidates from Suhyun's seated 2x2 calibration; never execute motion.

One calculation for all input sources. Grid-label mapping is not a 3-D rotation.
Non-reference sizes/layers/axes are explicitly nominal geometric extensions.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path

from planning_trial.planner import validate_brick, validate_current, occupied_cells, block_key, check_placement, check_support, validate_step
from planning_trial.assembly_geometry import validate_context, grip_options
from planning_trial.measurement_geometry import GEOMETRY_FILE, ABS_REFERENCE_FILE, load_geometry, load_material_reference

ROOT = Path(__file__).resolve().parent
HANDOFF = ROOT/'handoffs/assembly_trial_20261008_received/isaac_sim_assembly_20261008'


def quaternion_xyzw_from_zyz(abc):
    if len(abc) != 3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in abc):
        raise ValueError('Finite ZYZ degree triple required')
    a,b,c = [math.radians(v)/2 for v in abc]
    return [-math.sin(b)*math.sin(a-c), math.sin(b)*math.cos(a-c),
            math.cos(b)*math.sin(a+c), math.cos(b)*math.cos(a+c)]


def load_assembly_target_profile(handoff_dir=HANDOFF):
    directory=Path(handoff_dir)
    files=('data/points.json','data/position_analysis.json','data/sequence_plan.json')
    raw={name:(directory/name).read_bytes() for name in files}
    points=json.loads(raw[files[0]])
    fit=json.loads(raw[files[1]])
    centre=next(p for p in points['points'] if p['grid']==[11,11])
    hashes={name:sha256(value).hexdigest() for name,value in raw.items()}
    measured=load_geometry()
    hashes['measurements/'+GEOMETRY_FILE.name]=sha256(GEOMETRY_FILE.read_bytes()).hexdigest()
    hashes['measurements/'+ABS_REFERENCE_FILE.name]=sha256(ABS_REFERENCE_FILE.read_bytes()).hexdigest()
    p={
        'profile_id':'seated-tcp-'+sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()[:16],
        'source_sha256':hashes,'coefficient_xyz_mm':{k:fit[k] for k in ('origin','x_coefficient','y_coefficient','xy_coefficient')},
        'grid_mapping':{'planner_to_trial_xy':[[0,1],[1,0]],'offset_trial_xy':[0,0],
                        'status':'USER_CONFIRMED_COMMON_ORIGIN_AXIS_SWAP',
                        'confirmation_source':'USER_CHAT_20261008_SAME_PHYSICAL_CORNER_STUD',
                        'meaning':'GRID_LABEL_TRANSFORM_NOT_3D_ROTATION'},
        'reference':{'brick_type':'2x2x1','color':'blue','layer':1,'grip_axis_planner':'x',
                     'pad_bottom_above_block_bottom_mm':5,'tcp_setting_name':centre['sample']['tcp'],
                     'tcp_zyz_deg':centre['sample']['posx'][3:]},
        'geometry':{k:measured[k] for k in ('body_height_mm','stud_height_mm','precontact_block_bottom_clearance_mm')},
        'geometry_source':'USER_BODY19_STUD4_5_PITCH16_20261008_NOT_SOCKET_CALIBRATION',
        'material_metadata':{**measured['material'], 'reference_properties':load_material_reference()},
        'extensions':{'allow_nominal_sizes_layers_and_grip_rotation':True,
                      'assumption':'TCP_XY_AT_COMMON_BLOCK_CENTRE_AND_SAME_5MM_GRASP; UNVERIFIED_RIGID_GRASP_TRANSFORM'},
        'centre_residual_norm_mm':fit['center_residual_norm_mm'],
        'recorded_transfer_height_candidate_mm':json.loads(raw[files[2]])['clearance_z_mm'],
        'execution_allowed':False,
    }
    p['profile_id']=profile_fingerprint(p)
    validate_profile(p)
    return p


def profile_fingerprint(p):
    content={k:p[k] for k in ('source_sha256','coefficient_xyz_mm','grid_mapping','reference','geometry','extensions','recorded_transfer_height_candidate_mm')}
    return 'seated-tcp-'+sha256(json.dumps(content,sort_keys=True).encode()).hexdigest()[:16]


def validate_profile(p):
    for coeff in p['coefficient_xyz_mm'].values():
        if (not isinstance(coeff,list) or len(coeff)!=3 or
            any(type(v) not in (int,float) or not math.isfinite(v) for v in coeff)):
            raise ValueError('Finite 3-D calibration coefficients required')
    m=p['grid_mapping']['planner_to_trial_xy'];off=p['grid_mapping']['offset_trial_xy']
    if (not isinstance(m,list) or len(m)!=2 or any(not isinstance(r,list) or len(r)!=2 for r in m) or
        any(type(v) is not int for r in m for v in r) or len(off)!=2 or any(type(v) is not int for v in off)):
        raise ValueError('Explicit integer grid label map required')
    if abs(m[0][0]*m[1][1]-m[0][1]*m[1][0])!=1:
        raise ValueError('Grid labels must be a nondegenerate signed permutation')
    if any(sum(abs(v) for v in r)!=1 for r in m):
        raise ValueError('Only grid axis permutation/reflection supported')
    if p['reference']['pad_bottom_above_block_bottom_mm']!=5:
        raise ValueError('This calibration is for the taught 5mm grasp')
    quaternion_xyzw_from_zyz(p['reference']['tcp_zyz_deg'])
    for key,value in p['geometry'].items():
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
            raise ValueError('Explicit positive nominal geometry required: '+key)
    if type(p['recorded_transfer_height_candidate_mm']) not in (int,float) or not math.isfinite(p['recorded_transfer_height_candidate_mm']):
        raise ValueError('Finite recorded transfer-height candidate required')


def trial_nominal_tcp(x,y,*,profile=None):
    """Exact supplied bilinear nominal at the taught 2x2 minimal-stud index."""
    p=load_assembly_target_profile() if profile is None else profile
    validate_profile(p)
    if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=22 for v in (x,y)):
        raise ValueError('Reference/virtual 2x2 anchor must be in [0,22]')
    c=p['coefficient_xyz_mm']
    return [c['origin'][j]+x*c['x_coefficient'][j]+y*c['y_coefficient'][j]+x*y*c['xy_coefficient'][j] for j in range(3)]


def _pose(xyz,abc):
    return {'frame_id':'robot_base','xyz_mm_zyz_deg':list(xyz)+list(abc),
            'position_m':[v/1000 for v in xyz],'quaternion_xyzw':quaternion_xyzw_from_zyz(abc)}


def calculate_step_tcp(step,*,profile=None,grip_axis=None):
    """A selected PLACE -> seated/20mm bottom-gap TCP candidates and provenance."""
    p=load_assembly_target_profile() if profile is None else profile
    validate_profile(p)
    if (not isinstance(step,dict) or set(step)!={'step_id','operation','before','after','prerequisites','requires_delivery'} or
        step.get('operation')!='PLACE' or step.get('before') is not None or step.get('requires_delivery') is not True):
        raise ValueError('Existing PLACE Step required')
    if (not isinstance(step['prerequisites'],list) or any(not isinstance(v,str) or not v.strip() for v in step['prerequisites']) or
        len(set(step['prerequisites']))!=len(step['prerequisites'])):
        raise ValueError('Explicit unique prerequisite IDs required')
    if not isinstance(step.get('step_id'),str) or not step['step_id'].strip():
        raise ValueError('Step ID required')
    b=validate_brick(step['after'],0)
    from planning_trial.planner import BRICK_SIZES
    width,depth=BRICK_SIZES[b['brick_type']]
    if b['orientation_deg']==90:width,depth=depth,width
    required_axis='x' if width==2 else 'y'
    axis=grip_axis or required_axis
    if axis not in ('x','y') or (b['brick_type']!='2x2x1' and axis!=required_axis):
        raise ValueError('Grip must span 2 studs: small end faces for red1x2, long side faces for2x3')
    extended=b['brick_type']!='2x2x1' or b['layer']!=1 or axis!=p['reference']['grip_axis_planner']
    if extended and not p['extensions']['allow_nominal_sizes_layers_and_grip_rotation']:
        return {'status':'INPUTS_REQUIRED','step_id':step['step_id'],'execution_allowed':False,
                'errors':[{'reason':'Only taught blue 2x2 layer1/reference grip calibrated','block':b}]}
    # The calibration's x/y already includes the 2x2 centre/grasp relation.
    # Compare centres of the requested footprint and a virtual 2x2 footprint.
    equivalent=[b['x']+(width-2)/2,b['y']+(depth-2)/2]
    m=p['grid_mapping']['planner_to_trial_xy'];off=p['grid_mapping']['offset_trial_xy']
    centre=[b['x']+(width-1)/2,b['y']+(depth-1)/2]
    trial=[sum(m[j][k]*centre[k] for k in range(2))+off[j]-.5 for j in range(2)]
    xyz=trial_nominal_tcp(*trial,profile=p)
    xyz[2]+=(b['layer']-1)*p['geometry']['body_height_mm']
    abc=list(p['reference']['tcp_zyz_deg'])
    if axis!=p['reference']['grip_axis_planner']:abc[0]+=90 # world Base +Z left-multiplication, not Euler ZYX.
    gap=p['geometry']['stud_height_mm']+p['geometry']['precontact_block_bottom_clearance_mm']
    pre=list(xyz);pre[2]+=gap
    trial_corrected=list(xyz);trial_corrected[2]-=2
    limits=['GRID_LABEL_MAPPING_USER_CONFIRMED_NOT_PHYSICAL_PATH_VALIDATION',
            'NO_IK_OR_FULL_TOOL_PATH_VALIDATION','REFERENCE_SEATED_TCP_ALREADY_INCLUDES_GRASP_AND_CENTRE',
            'COLOUR_TRANSFER_NOT_INDEPENDENTLY_TESTED' if b['color']!='blue' else 'BLUE_REFERENCE_COLOUR']
    if extended:limits.append('NOMINAL_SIZE_LAYER_ROTATION_EXTENSION_NOT_PHYSICALLY_CALIBRATED')
    return {'schema_version':'assembly-target-coordinate-candidate/0.1','status':'COORDINATE_CANDIDATE',
            'execution_allowed':False,'profile_id':profile_fingerprint(p),'step_id':step['step_id'],'block':b,
            'grid_alignment_status':p['grid_mapping']['status'],
            'grip_axis_planner':axis,'equivalent_reference_2x2_anchor_planner':equivalent,
            'trial_grid_reference_2x2_anchor':trial,
            'scope':'NOMINAL_GEOMETRIC_EXTENSION' if extended else 'TAUGHT_2X2_LAYER1_INTERPOLATION',
            'nominal_seated_tcp':_pose(xyz,abc),'pre_contact_tcp':_pose(pre,abc),
            'D_contact_minus2mm_trial_candidate':_pose(trial_corrected,abc),
            'precontact_tcp_lift_from_nominal_seated_mm':gap,
            'precontact_gap_reference':'HELD_BLOCK_BOTTOM_TO_LOWER_STUD_TIP_20MM',
            'pad_bottom_above_block_bottom_mm':5,'raw_reference_centre_residual_mm':p['centre_residual_norm_mm'],
            'limits':limits,'motion_generated':False}


def calculate_step_waypoints(step,current,pick,assembly_context,*,profile=None,grip_axis=None,plan=None):
    """Local grip + overhead waypoints. No claim of full-robot swept collision/IK."""
    p=load_assembly_target_profile() if profile is None else profile
    target=calculate_step_tcp(step,profile=p,grip_axis=grip_axis)
    blocks,revision=validate_current(current)
    if target['status']!='COORDINATE_CANDIDATE':return target
    if plan is None and step['prerequisites']:
        return {'status':'BLOCKED','waypoints':[],'base_current_revision':revision,'execution_allowed':False,
                'errors':[{'reason':'Plan required to resolve prerequisite placements','block':target['block']}]}
    if plan is not None:
        if (not isinstance(plan,dict) or set(plan)!={'plan_id','design_version','base_current_revision','steps'} or
            type(plan['base_current_revision']) is not int or not 0<=plan['base_current_revision']<=revision):
            raise ValueError('Plan and Current baseline references required')
        seen={}
        for index,item in enumerate(plan['steps']):seen[item['step_id']]=validate_step(item,index,seen)
        if step not in plan['steps']:raise ValueError('Selected Step must equal original Plan Step')
        present={block_key(b) for b in blocks}
        if any(block_key(seen[sid]) not in present for sid in step['prerequisites']):
            return {'status':'WAIT_PREREQUISITES','waypoints':[],'base_current_revision':revision,'execution_allowed':False,
                    'errors':[{'reason':'Prerequisite placements not confirmed in Current','block':target['block']}]}
    if any(block_key(b)==block_key(target['block']) for b in blocks):
        return {'status':'ALREADY_ASSEMBLED','waypoints':[],'base_current_revision':revision,'execution_allowed':False}
    validate_context(assembly_context)
    if (assembly_context['geometry']['grip_bottom_offset_mm']!=5 or
        pick['grasp']['pad_bottom_above_block_bottom_mm']!=5):
        raise ValueError('Pickup, target calibration and local grip model must all use 5mm depth')
    if pick['brick_type']!=target['block']['brick_type'] or pick['color']!=target['block']['color']:
        raise ValueError('D-selected supply part must match selected Step')
    occupied={c for b in blocks for c in occupied_cells(b)}
    for b in blocks:
        check_support(b,occupied,'Current','NEEDS_CORRECTION')
    try:
        check_placement(target['block'],occupied,'selected Step')
    except ValueError as exc:
        return {'status':'BLOCKED','waypoints':[],'base_current_revision':revision,'execution_allowed':False,
                'errors':[{'reason':str(exc),'block':getattr(exc,'block',target['block'])}]}
    choices=grip_options(target['block'],blocks,assembly_context)
    if not any(o['grip_axis']==target['grip_axis_planner'] for o in choices):
        return {'status':'BLOCKED','waypoints':[],'base_current_revision':revision,'execution_allowed':False,
                'errors':[{'reason':'Selected long-side grip corridor blocked in local 5mm model','block':target['block']}]}
    pickup=pick['pickup_tcp_pose']
    if pickup['frame_id']!='robot_base' or pickup['position_unit']!='mm' or pickup['orientation_convention']!='ZYZ':
        raise ValueError('Pickup and target must use the same native Base/TCP pose convention')
    start=pickup['xyz_abc']
    if len(start)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in start):
        raise ValueError('Finite pickup pose required')
    pre=target['pre_contact_tcp']['xyz_mm_zyz_deg']
    max_layer=max([0]+[b['layer'] for b in blocks])
    floor_z_max=max(trial_nominal_tcp(x,y,profile=p)[2] for x in (0,22) for y in (0,22))
    # Same grasp height cancels when comparing carried bottom against structure top.
    overhead=floor_z_max+max_layer*p['geometry']['body_height_mm']+p['geometry']['stud_height_mm']+20
    # Keep the recorded transfer height as a candidate minimum, raising for taller Current.
    recorded=p['recorded_transfer_height_candidate_mm']
    travel=max(recorded,overhead,pre[2],start[2]+20)
    lift=start[:];lift[2]=travel
    above=pre[:];above[2]=travel
    return {'schema_version':'assembly-waypoint-candidate/0.1','status':'WAYPOINT_CANDIDATE','execution_allowed':False,
            'step_id':step['step_id'],'motion_current_revision':revision,'profile_id':target['profile_id'],
            'pad_bottom_above_block_bottom_mm':5,'travel_tcp_z_mm':travel,
            'nominal_structure_envelope_tcp_z_mm':overhead,
            'waypoints':[{'label':label,'pose':_pose(pose[:3],pose[3:])} for label,pose in
                         [('LIFT_HOLDING',lift),('TRANSIT_ABOVE_TARGET',above),('PRE_CONTACT_HOLDING',pre)]],
            'terminal_gripper_policy':'HOLD_NO_AUTOMATIC_OPEN','assembly_completed':False,
            'local_grip_corridor_checked':True,'full_robot_collision_checked':False,'ik_checked':False,
            'speed_profile':None,'grid_alignment_status':p['grid_mapping']['status'],
            'limits':['GRASP_RIGID_TRANSFORM_AND_ISAAC_WORLD_BASE_ALIGNMENT_UNVERIFIED',
                                          'OVERHEAD_RULE_NOT_FULL_ROBOT_COLLISION_PROOF',
                                          'NO_RELEASE_RETURN_FORCE_OR_ROBOT_COMMAND'],
            'target':target}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output-dir',type=Path,required=True);args=ap.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=False)
    p=load_assembly_target_profile()
    # User confirmed the common physical origin; Planner and trial axis labels swap.
    samples=[('reference_10_20',20,10,1,'2x2x1',0),('reference_17_1',1,17,1,'2x2x1',0),
             ('reference_0_16',16,0,1,'2x2x1',0),('reference_14_20',20,14,1,'2x2x1',0),
             ('nominal_2x3_layer2',5,5,2,'2x3x1',0),('nominal_2x3_rotated',5,5,2,'2x3x1',90)]
    results=[];inputs=[]
    for name,x,y,layer,kind,angle in samples:
        step={'step_id':name,'operation':'PLACE','before':None,'after':{'brick_type':kind,'color':'blue','x':x,'y':y,'layer':layer,'orientation_deg':angle},'prerequisites':[],'requires_delivery':True}
        result=calculate_step_tcp(step,profile=p);inputs.append(step);results.append(result)
        print(name,'trial=',result.get('trial_grid_reference_2x2_anchor'),'nominal=',result['nominal_seated_tcp']['xyz_mm_zyz_deg'][:3],'pre-contact=',result['pre_contact_tcp']['xyz_mm_zyz_deg'][:3],'scope=',result['scope'])
    for name,obj in [('profile.json',p),('steps.json',inputs),('tcp_candidates.json',results)]:
        (args.output_dir/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    from planning_trial.supply_pick import calculate_supply_pick
    context=json.loads((ROOT/'sample_user_rules_5mm_measured_rev2_inputs.json').read_text())['assembly_context']
    route_inputs=[];routes=[]
    first=inputs[0]
    scenarios=[('empty',first,{'current_revision':0,'blocks':[]},1),
               ('next_layer',dict(first,step_id='NEXT_LAYER',after=dict(first['after'],layer=2)),
                {'current_revision':1,'blocks':[first['after']]},2),
               ('tall_current',first,{'current_revision':4,'blocks':[dict(first['after'],x=10,y=10,layer=i) for i in range(1,5)]},3)]
    for label,selected,current,slot in scenarios:
        pick=calculate_supply_pick('2x2x1','blue',slot)
        route_inputs.append({'case':label,'step':selected,'current':current,'pickup':pick,'assembly_context':context})
        routes.append({'case':label,'result':calculate_step_waypoints(selected,current,pick,context,profile=p)})
    (args.output_dir/'waypoint_inputs.json').write_text(json.dumps(route_inputs,ensure_ascii=False,indent=2)+'\n')
    (args.output_dir/'waypoint_candidates.json').write_text(json.dumps(routes,ensure_ascii=False,indent=2)+'\n')
    # Static markers only. Base==World is a display convention, not scene calibration.
    usd=['#usda 1.0','(','    defaultPrim = "AReview"','    metersPerUnit = 1','    upAxis = "Z"',')','def Xform "AReview"','{']
    for index,result in enumerate(results):
        for label,key,colour in [('Nominal','nominal_seated_tcp',(0.2,0.4,1)),('PreContact','pre_contact_tcp',(0.2,1,0.4)),('DMinus2','D_contact_minus2mm_trial_candidate',(1,0.3,0.2))]:
            pose=result[key];x,y,z,w=pose['quaternion_xyzw']
            usd += [f'    def Sphere "{label}_{index}"','    {','        double radius = 0.003',
                    f'        double3 xformOp:translate = {tuple(pose["position_m"])}',
                    f'        quatd xformOp:orient = {(w,x,y,z)}',
                    '        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:orient"]',
                    f'        color3f[] primvars:displayColor = [{colour}]','    }']
    for index,item in enumerate(routes):
        points=[tuple(w['pose']['position_m']) for w in item['result'].get('waypoints',[])]
        if points:
            usd += [f'    def BasisCurves "Route_{index}"','    {','        uniform token type = "linear"','        uniform token wrap = "nonperiodic"',
                    f'        int[] curveVertexCounts = [{len(points)}]',f'        point3f[] points = {points}',
                    '        float[] widths = [0.001] (interpolation = "constant")','        color3f[] primvars:displayColor = [(1, 0.8, 0.2)]','    }']
    usd.append('}');(args.output_dir/'tcp_review_markers.usda').write_text('\n'.join(usd)+'\n')
    rows=['# 조립판 TCP 변환·대기 위치 후보','','Base XYZ mm. 사용자 확인: 같은 구석 stud 원점, trial_x=Planner_y / trial_y=Planner_x. 실물 경로 검증과 Isaac World/Base 정합은 별도이다.',
          '| 사례 | Planner x,y,layer | trial 기준점 | nominal TCP XYZ | 대기 TCP XYZ | 범위 |',
          '|---|---|---|---|---|---|']
    for result in results:
        b=result['block'];fmt=lambda values:', '.join(f'{v:.3f}' for v in values)
        rows.append(f"| {result['step_id']} | {b['x']},{b['y']},{b['layer']} | {result['trial_grid_reference_2x2_anchor']} | {fmt(result['nominal_seated_tcp']['xyz_mm_zyz_deg'][:3])} | {fmt(result['pre_contact_tcp']['xyz_mm_zyz_deg'][:3])} | {result['scope']} |")
    rows += ['',f"nominal 대비 +{p['geometry']['stud_height_mm']+p['geometry']['precontact_block_bottom_clearance_mm']}mm = stud 높이 + 밑면 대기 간격. −2mm는 D Contact 시험 후보에만 별도 적용.",
             'marker는 Base=World의 표시용 파일이며 robot/board/stud/socket 물리 모델이 없다.',
             '이동 후보: 집은 채 상승→상공 이동→pre-contact 정지. 실제 IK/팔 전체 충돌/정지는 미검증.']
    (args.output_dir/'tcp_candidates.md').write_text('\n'.join(rows)+'\n')
    print('Saved:',args.output_dir.resolve(),'| review candidates only, no robot/Isaac execution')


if __name__=='__main__':main()
