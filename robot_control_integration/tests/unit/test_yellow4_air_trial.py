from copy import deepcopy
import json
import subprocess
import sys
import numpy as np
import pytest
from app.yellow4_air_trial import prepare_air,route,execute
from app.yellow4_observation import prepare
from app.edge_first_seating import pose_matrix
from scripts.yellow4_air_trial import TrialWindow
from test_yellow4_observation import SETTINGS,ROOT,bundle,measurement
AIR=json.loads((ROOT/'robot_control_integration/settings/yellow4_challenge_20261014/air_trial.json').read_text())


def measured():
    b=bundle();m=measurement(b);m['operations']['removal']=None
    return prepare(ROOT,SETTINGS,m)


def test_missing_fields_preview_reuses_routes_rates_without_fake_poses():
    b=bundle();original=deepcopy(b);p=prepare_air(b,AIR)
    assert not p['execution_ready'] and p['physical_commands']==0
    assert p['rates']['transit']==120 and p['rates']['vertical']==12
    assert p['grasp_mode']=='STANDARD' and p['intended_pad_bottom_height_mm']==5
    assert 'air_geometry' not in p and b==original


def test_air_translation_preserves_grasp_axis_block_and_tcp_together():
    b=measured();original=deepcopy(b);p=prepare_air(b,AIR)
    shift=np.array(p['air_translation_xyz_mm']);air=p['air_geometry'];ground=p['ground_geometry']
    for a,g in zip(air['waypoints'],ground['waypoints']):
        for key in ('tcp_mm_zyz_deg','block_mm_zyz_deg'):
            assert np.array(a[key][:3])-g[key][:3]==pytest.approx(shift)
            assert pose_matrix(a[key])[:3,:3]==pytest.approx(pose_matrix(g[key])[:3,:3],abs=1e-9)
        assert np.array(a['block_corners_mm'])-g['block_corners_mm']==pytest.approx(np.tile(shift,(8,1)))
    assert np.array(air['contact_line_points_mm'])-ground['contact_line_points_mm']==pytest.approx(np.tile(shift,(2,1)))
    assert air['tcp_to_block_pose_mm_zyz_deg']==ground['tcp_to_block_pose_mm_zyz_deg']
    assert p['minimum_block_clearance_mm']>AIR['minimum_block_clearance_mm']
    assert p['execution_ready'] and not p['collision_free_verified'] and b==original


def test_missing_removal_does_not_block_assembly():
    b=measured();assert prepare_air(b,AIR,'assembly')['execution_ready']
    assert not prepare_air(b,AIR,'removal')['execution_ready']


def test_removal_popup_geometry_keeps_selected_operation():
    b=bundle();b=prepare(ROOT,SETTINGS,measurement(b));p=prepare_air(b,AIR,'removal')
    assert p['air_config']['operation']=='removal'
    assert p['air_geometry']['operation']=='removal'


@pytest.mark.parametrize('zone',['home','supply','assembly'])
def test_routes_end_at_air_reference_and_replace_third_waypoint(zone):
    p=prepare_air(measured(),AIR);segments=route(p,[100,50,200,0,180,0],zone);labels=[l for l,_ in segments]
    assert 'PLACE_BOARD' not in labels
    if zone!='assembly':assert [l for l in labels if l in ('SUPPLY_TRANSIT','BODY_BYPASS','ASSEMBLY_OBSERVATION')]==['SUPPLY_TRANSIT','BODY_BYPASS','ASSEMBLY_OBSERVATION']
    assert segments[-1]==('AIR_RETURN_REFERENCE',p['air_geometry']['seated_reference_tcp_mm_zyz_deg'])
    assert min(t[2] for l,t in segments if not l.startswith('PIVOT'))>=p['transport_height_mm']-.01
    if zone=='home':assert 'SUPPLY_OBSERVATION' in labels


@pytest.mark.parametrize('change',[{'air_tcp_z_mm':0},{'air_tcp_z_mm':40},{'rates':{'vertical':0}},{'position_tolerance_mm':-1}])
def test_invalid_or_low_air_geometry_cannot_execute(change):
    s=deepcopy(AIR);s.update(change)
    with pytest.raises(ValueError):prepare_air(measured(),s)


class Fake:
    mode='FAKE'
    def __init__(self):
        self.s=dict(posx=[100.,50.,200.,0.,180.,0.],posj=[0,0,90,0,90,0],velx=[0.]*6,motion_status=0,
            query_duration_s=.1,tcp='GripperDA_v4',tool='ToolWeight0',robot_state=1,robot_mode=0,drl_state=3,
            gripper_status=2,gripper_width_mm=35.,wrench=[0.]*6)
        self.moves=[];self.calls=[];self.stops=0;self.fail=False;self.stale=0
    def sample(self):
        s=deepcopy(self.s)
        if self.stale:self.stale-=1;s['query_duration_s']=.8
        return s
    def check_pose(self,p):return list(p)
    def call(self,path,kind,**kwargs):
        assert path=='system/set_robot_mode';self.calls.append(path);self.s['robot_mode']=kwargs['robot_mode']
    def move_line_async(self,p,v,a):
        self.moves.append((list(p),list(v),list(a)))
        if self.fail:raise TimeoutError('ACK_UNKNOWN')
        self.s['posx']=list(p)
    def stop(self):self.stops+=1
    def motion_feedback(self):return self.sample()


def test_fake_exec_records_actual_so3_width_force_and_return_without_grip():
    d=Fake();p=prepare_air(measured(),AIR);events=[]
    r=execute(d,p,'supply',lambda e,x:events.append((e,x)),sleep=lambda _:None)
    assert d.moves and d.stops==0 and r['gripper_commands']==0 and not r['assembly_completion']
    assert not r['contact_axis_maintained_physically_verified']
    assert d.s['posx']==p['air_geometry']['seated_reference_tcp_mm_zyz_deg']
    samples=[x for e,x in events if e=='MOTION_SAMPLE']
    assert all(x['position_error_mm']==0 and x['so3_error_deg']<1e-10 for x in samples)
    assert all('wrench' in x['sample'] and 'gripper_width_drift_mm' in x for x in samples)
    assert all(x['velocity'][0]==12 for e,x in events if e=='MOVE_REQUEST' and x['label'].startswith('PIVOT'))


def test_stale_stopped_reads_refresh_without_repeating_motion():
    d=Fake();d.stale=2;events=[]
    r=execute(d,prepare_air(measured(),AIR),'assembly',lambda e,x:events.append(e),sleep=lambda _:None)
    assert events.count('FEEDBACK_REFRESH_WAIT')==2 and r['move_line_requests']==len(d.moves) and r['physical_commands']==0


def test_unknown_ack_stops_once_without_resend_or_gripper_commands():
    d=Fake();d.fail=True
    with pytest.raises(TimeoutError,match='ACK_UNKNOWN'):execute(d,prepare_air(measured(),AIR),'assembly',lambda *_:None,sleep=lambda _:None)
    assert len(d.moves)==1 and d.stops==1


def test_closed_popup_does_not_prevent_stop_ack_pump():
    d=Fake();d.fail=True;old=lambda:None;d.ui_pump=old;seen=[]
    d.stop_ui_pump=lambda:seen.append('spin_only')
    def stop():d.ui_pump();d.stops+=1
    d.stop=stop
    with pytest.raises(TimeoutError):execute(d,prepare_air(measured(),AIR),'assembly',lambda *_:None,sleep=lambda _:None)
    assert seen==['spin_only'] and d.stops==1 and d.ui_pump is old


def test_failed_motion_journal_still_requests_stop():
    d=Fake()
    def record(event,data):
        if event in ('MOTION_SAMPLE','ABORT'):raise OSError('JOURNAL_WRITE_FAILED')
    with pytest.raises(OSError,match='JOURNAL_WRITE_FAILED') as error:
        execute(d,prepare_air(measured(),AIR),'assembly',record,sleep=lambda _:None)
    assert len(d.moves)==1 and d.stops==1
    assert any('ABORT_LOGGING_FAILED' in note for note in error.value.__notes__)


def test_force_and_tool_faults_prevent_first_command():
    p=prepare_air(measured(),AIR)
    for field,value in [('wrench',[46.,0,0,0,0,0]),('tcp','wrong')]:
        d=Fake();d.s[field]=value
        with pytest.raises(RuntimeError):execute(d,p,'assembly',lambda *_:None,sleep=lambda _:None)
        assert not d.moves and not d.calls and d.stops==0


def test_cli_missing_measurements_is_actionable_preview_without_ros(tmp_path):
    c=subprocess.run([sys.executable,str(ROOT/'robot_control_integration/scripts/yellow4_air_trial.py'),'--output',str(tmp_path)],capture_output=True,text=True)
    assert c.returncode==0,c.stderr
    p=json.loads((tmp_path/'preview.json').read_text());assert not p['execution_ready'] and p['physical_commands']==0 and p['intended_pad_bottom_height_mm']==5


def test_popup_keeps_feedback_pumping_and_saves_original_capture_time(monkeypatch,tmp_path):
    from types import SimpleNamespace
    import cv2
    calls=[]
    for name in ('namedWindow','resizeWindow','imshow','destroyWindow'):
        monkeypatch.setattr(cv2,name,lambda *args:None)
    monkeypatch.setattr(cv2,'getWindowProperty',lambda *args:1)
    monkeypatch.setattr(cv2,'waitKey',lambda *args:-1)
    observer=SimpleNamespace(ros=SimpleNamespace(spin_once=lambda *a,**kw:calls.append('spin')),node=None,
        frame=np.zeros((480,640,3),np.uint8),rgb_time=None,info=None)
    b=measured();p=prepare_air(b,AIR);w=TrialWindow(observer,b,p)
    try:
        w.feedback('START',dict(sample=Fake().sample()));w.pump()
        assert calls==['spin'] and w.pending is not None
        w.pending.result()
        path=w.save_evidence(tmp_path/'capture',observer.frame,w.sample,None,1234,5678)
        record=json.loads((path/'capture.json').read_text())
        assert record['timing']['unix_s']==5678 and record['timing']['rgb_stamp_ns']==1234
        assert not record['pose_image_registration_verified'] and not record['block_pose_measured']
        assert record['observation']['path_source']=='AIR_TRANSLATION_OF_INPUT_GEOMETRY_NOT_PHYSICAL_CONTACT'
        monkeypatch.setattr(cv2,'waitKey',lambda *args:27);w.last_draw=0
        with pytest.raises(KeyboardInterrupt,match='OPERATOR_STOP'):w.pump()
    finally:w.close()


def test_shared_motion_observer_keeps_ros_alive_for_operator_stop(monkeypatch):
    from types import SimpleNamespace
    from scripts.yellow4_observe import ReadOnlyRos
    initialized=[]
    node=SimpleNamespace(create_client=lambda *a:None,create_subscription=lambda *a:None,destroy_node=lambda:None)
    monkeypatch.setitem(sys.modules,'rclpy',SimpleNamespace(init=lambda **kw:initialized.append(kw),create_node=lambda name:node,ok=lambda:True,shutdown=lambda:None))
    monkeypatch.setitem(sys.modules,'rclpy.signals',SimpleNamespace(SignalHandlerOptions=SimpleNamespace(NO='NO')))
    monkeypatch.setitem(sys.modules,'rclpy.qos',SimpleNamespace(qos_profile_sensor_data=None))
    monkeypatch.setitem(sys.modules,'dsr_msgs2',SimpleNamespace(srv=SimpleNamespace(**{t:object for _,_,t,_ in ReadOnlyRos.SERVICES})))
    monkeypatch.setitem(sys.modules,'sensor_msgs.msg',SimpleNamespace(Image=object,CameraInfo=object))
    b=bundle();b['camera_info_topic']='/camera/color/camera_info'
    reader=ReadOnlyRos(b,node_name='air_trial_test',disable_signal_handlers=True);reader.close()
    assert initialized==[dict(args=[],signal_handler_options='NO')]
