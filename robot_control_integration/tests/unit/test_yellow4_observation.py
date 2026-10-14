from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import numpy as np
import pytest
from app.yellow4_observation import prepare,analyze,save_capture
from app.edge_first_seating import pose_matrix
from scripts.yellow4_observe import ReadOnlyRos

ROOT=Path(__file__).resolve().parents[3]
SETTINGS=json.loads((ROOT/'robot_control_integration/settings/yellow4_challenge_20261014/observation.json').read_text())


def bundle():return prepare(ROOT,SETTINGS)


def test_standard5_sources_and_layer_translation_remain_distinct():
    b=bundle()
    assert b['target']['x']==17 and b['supply_row']['slot']==1
    assert b['baseline_supply_tcp'][2]==pytest.approx(52.078731536865234)
    assert b['selected_pickup_tcp_candidate']==b['baseline_supply_tcp']
    assert b['grasp_mode']=='STANDARD' and b['intended_pad_bottom_height_mm']==5
    assert b['selected_seated_tcp_candidate']==b['baseline_seated_tcp']
    assert b['layer_reference']['grid_delta_xyz_mm'][0]>90
    assert b['dimensions']['span_2_outer_length_mm']==31.8
    assert b['board_transform_status']=='PROVISIONAL_NOT_FOR_MOTION'
    assert b['geometry_config'] is None and not b['raised_profile_has_measured_poses']
    assert not b['field_verified'] and b['physical_commands']==0
    for value in b['sources'].values():
        from hashlib import sha256
        assert sha256(Path(value['path']).read_bytes()).hexdigest()==value['sha256']


def test_missing_detection_and_resolution_mismatch_record_coordinate_fallback():
    b=bundle();image=np.zeros((480,640,3),np.uint8)
    _,r=analyze(image,b,'supply')
    assert r['supply_decision']['vision_attempted'] and not r['supply_decision']['recognized']
    assert r['coordinate_fallback_tcp']==b['baseline_supply_tcp']
    assert not r['supply_decision']['center_assist_applied']
    _,r=analyze(np.zeros((720,1280,3),np.uint8),b,'supply')
    assert r['supply_decision']['reason']=='LAYOUT_IMAGE_SIZE_MISMATCH_SELECT_B_ROI'
    assert r['coordinate_fallback_tcp']==b['baseline_supply_tcp']


def test_recognized_center_mapping_requires_verified_mapping_and_matching_view(monkeypatch):
    import app.yellow4_observation as module
    b=bundle();original=deepcopy(b)
    monkeypatch.setattr(module,'supply_observe',lambda *a:dict(slot_id='yellow_2x2x1_01',vision_attempted=True,
        recognized=True,center_available=True,center_uv=[103,104],center_basis='STUD_ARRAY',reason=None))
    _,r=analyze(np.zeros((480,640,3),np.uint8),b,'supply')
    assert r['supply_decision']['recognized'] and not r['supply_decision']['center_assist_applied']
    b['supply_row']['center_mapping']=dict(independently_verified=True,center_basis='STUD_ARRAY',
        base_xy_mm_per_pixel=[[.1,0],[0,.1]],reference_center_uv=[100,100],max_shift_mm=3)
    _,unknown=analyze(np.zeros((480,640,3),np.uint8),b,'supply')
    assert unknown['supply_decision']['fallback_reason']=='MAPPING_OBSERVATION_POSE_NOT_CONFIRMED'
    sample=dict(posx=b['supply_observation_pose'],motion_status=0,tcp=b['connection']['tcp'],tool=b['connection']['tool'])
    _,mapped=analyze(np.zeros((480,640,3),np.uint8),b,'supply',sample=sample)
    assert mapped['supply_decision']['center_assist_applied']
    assert mapped['coordinate_fallback_tcp'][:2]==pytest.approx(np.array(b['baseline_supply_tcp'][:2])+[.3,.4])
    assert original['supply_row']['pickup_pose']==b['supply_row']['pickup_pose']


def test_current_roi_changes_only_local_diagnostics():
    b=bundle();before=deepcopy(b)
    _,r=analyze(np.zeros((720,1280,3),np.uint8),b,'supply',roi=[400,30,600,160])
    assert r['roi_source']=='OPERATOR_CURRENT_FRAME_NOT_SAVED_LAYOUT'
    assert r['supply_decision']['reason']!='LAYOUT_IMAGE_SIZE_MISMATCH_SELECT_B_ROI'
    assert b==before


def test_assembly_grid_is_yaw_diagnostic_and_wrong_tool_cannot_project():
    b=bundle();image=np.zeros((480,640,3),np.uint8)
    info=dict(width=640,height=480,frame_id='camera_color_optical_frame',distortion_model='plumb_bob',k=[600,0,320,0,600,240,0,0,1],d=[0.]*5)
    sample=dict(posx=[472,85,194,102,-176,104],tcp=b['connection']['tcp'],tool=b['connection']['tool'])
    _,r=analyze(image,b,'assembly',sample=sample,info=info,edge=[[290,360],[340,361]],axis=[[20,20],[60,20]])
    assert r['relative_angle_deg'] is not None and not r['roll_pitch_observed']
    assert not r['pixel_axis_is_measured_3d_axis'] and not r['grid_reference']['projection_independently_verified']
    sample['tcp']='WRONG';_,r=analyze(image,b,'assembly',sample=sample,info=info)
    assert r['reason']=='CURRENT_TCP_TOOL_MISMATCH_OR_UNKNOWN'
    _,r=analyze(image,b,'assembly')
    assert r['reason']=='CURRENT_TCP_AND_CAMERA_INFO_REQUIRED'


def measurement(b):
    # Synthetic contract data for tests only; not saved as field evidence.
    g=json.loads((ROOT/'robot_control_integration/fixtures/yellow4_pivot_preview.json').read_text())
    for value in g['operations'].values():value['contact_line']['frame']='BASE'
    g['target_studs']['frame']='BASE'
    return dict(source_kind='OPERATOR_FIELD_MEASUREMENT',evidence_ref='TEST_ONLY_NOT_REAL',frame='BASE',
        target=b['target'],slot=1,tcp=b['connection']['tcp'],tool=b['connection']['tool'],grasp_id='test-only',
        grasp_mode='STANDARD',pad_bottom_from_block_bottom_mm=5,tcp_pose_mm_zyz_deg=[0,0,30,0,180,0],block_pose_mm_zyz_deg=[0,0,0,0,0,0],
        block_geometry=g['block_geometry'],target_studs=g['target_studs'],operations=g['operations'],board_fixation_confirmed=True)


def test_explicit_paired_measurement_derives_rigid_relation_without_contact_success():
    b=bundle();m=measurement(b);original=deepcopy(m);r=prepare(ROOT,SETTINGS,m)
    assert pose_matrix(m['tcp_pose_mm_zyz_deg'])@pose_matrix(r['tcp_to_block_pose_mm_zyz_deg'])==pytest.approx(pose_matrix(m['block_pose_mm_zyz_deg']),abs=1e-9)
    assert r['missing_measurements']==[] and not r['field_verified'] and not r['execution_allowed']
    assert m==original


@pytest.mark.parametrize('field,value',[('slot',2),('tool','wrong'),('source_kind','SYNTHETIC'),('pad_bottom_from_block_bottom_mm',15),('evidence_ref',None),('frame','CAMERA')])
def test_unbound_or_unmeasured_input_is_not_promoted(field,value):
    b=bundle();m=measurement(b);m[field]=value
    with pytest.raises(ValueError):prepare(ROOT,SETTINGS,m)


def test_capture_preserves_raw_evidence_and_cannot_mark_height_from_role(tmp_path):
    b=bundle();image=np.zeros((480,640,3),np.uint8);sample=dict(posx=[1,2,3,0,180,0],velx=[0]*6,motion_status=0)
    canvas,r=analyze(image,b,'supply');out=save_capture(tmp_path/'capture',image,canvas,b,r,sample=sample,role='SUPPLY_GRASP_CANDIDATE')
    record=json.loads((out/'capture.json').read_text())
    assert record['sample']==sample and record['robot_stopped_at_capture'] is True
    assert not record['actual_pad_bottom_height_verified'] and not record['block_pose_measured']
    assert not record['pose_image_registration_verified'] and record['physical_commands']==0
    with pytest.raises(FileExistsError):save_capture(out,image,canvas,b,r)


def test_live_reader_constructs_and_sends_only_queries(monkeypatch):
    allowed={'aux_control/get_current_posj','motion/fkin','aux_control/get_current_velx','motion/check_motion',
        'aux_control/get_tool_force','tcp/get_current_tcp','tool/get_current_tool'}
    calls=[];types={t:SimpleNamespace(Request=lambda:SimpleNamespace()) for _,_,t,_ in ReadOnlyRos.SERVICES}
    class Client:
        def __init__(self,path):self.path=path
        def service_is_ready(self):return True
        def call_async(self,request):
            assert self.path in allowed;calls.append((self.path,request))
            key=next(k for k,p,_,_ in ReadOnlyRos.SERVICES if p==self.path)
            value={'posj':[0]*6,'posx':[1,2,3,0,180,0],'velx':[0]*6,'motion_status':0,'wrench':[0]*6,'tcp':'GripperDA_v4','tool':'ToolWeight0'}[key]
            attr=next(a for k,_,_,a in ReadOnlyRos.SERVICES if k==key)
            response=SimpleNamespace(success=True,**{attr:value})
            return SimpleNamespace(done=lambda:True,result=lambda:response)
    class Node:
        def create_client(self,typename,path):
            relative=path.split('/dsr_controller2/')[1];assert relative in allowed;return Client(relative)
        def create_subscription(self,*args):return None
        def destroy_node(self):pass
    shutdown=[]
    monkeypatch.setitem(sys.modules,'rclpy',SimpleNamespace(init=lambda **kw:None,create_node=lambda name:Node(),spin_once=lambda *a,**k:None,ok=lambda:True,shutdown=lambda:shutdown.append(True)))
    monkeypatch.setitem(sys.modules,'rclpy.qos',SimpleNamespace(qos_profile_sensor_data=None))
    monkeypatch.setitem(sys.modules,'dsr_msgs2',SimpleNamespace(srv=SimpleNamespace(**types)))
    monkeypatch.setitem(sys.modules,'sensor_msgs',SimpleNamespace())
    monkeypatch.setitem(sys.modules,'sensor_msgs.msg',SimpleNamespace(Image=object,CameraInfo=object))
    b=bundle();b['camera_info_topic']='/camera/color/camera_info';reader=ReadOnlyRos(b)
    for _ in range(22):reader.poll()
    reader.close()
    assert {p for p,_ in calls}==allowed
    assert next(req for p,req in calls if p=='motion/fkin').pos==[0.]*6
    assert reader.sample['tcp']=='GripperDA_v4'
    assert shutdown==[True]
    reader.ros.ok=lambda:False;reader.close()
    assert shutdown==[True]


def test_human_replacement15_is_explicit_and_not_default():
    settings=deepcopy(SETTINGS);settings['grasp_mode']='HUMAN_REPLACEMENT'
    b=prepare(ROOT,settings)
    assert b['intended_pad_bottom_height_mm']==15
    assert b['selected_pickup_tcp_candidate'][2]-b['baseline_supply_tcp'][2]==10
    assert b['selected_seated_tcp_candidate'][2]-b['baseline_seated_tcp'][2]==10
    assert not b['raised_profile_has_measured_poses'] and not b['field_verified']
    m=measurement(bundle())
    with pytest.raises(ValueError,match='HEIGHT_MODE'):prepare(ROOT,settings,m)


def test_missing_removal_axis_does_not_discard_known_assembly_input():
    b=bundle();m=measurement(b);m['operations']['removal']=None
    r=prepare(ROOT,SETTINGS,m)
    assert r['geometry_config']['operation']=='assembly'
    assert r['missing_measurements']==['removal_contact_axis']
    m['block_geometry']=None;r=prepare(ROOT,SETTINGS,m)
    assert r['tcp_to_block_pose_mm_zyz_deg'] is not None and r['geometry_config'] is None
    assert 'block_geometry' in r['missing_measurements']
