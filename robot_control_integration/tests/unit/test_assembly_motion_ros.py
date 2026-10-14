"""실제 adapter 메서드에 가짜 transport만 연결한다. 생성자/ROS 노드/장치 연결은 없다."""

from types import SimpleNamespace

import pytest

from app.assembly_motion_ros import AssemblyMotionRos, response_vector
from test_assembly_motion import configuration


def driver():
    item = AssemblyMotionRos.__new__(AssemblyMotionRos)
    item.config = configuration()
    item.calls = []
    def call(path, kind, **fields):
        item.calls.append((path, kind, fields))
        outputs = dict(pos=[0.]*6, conv_posx=item.config["start_posx"], vel=[0.]*6, status=0,
                       robot_state=1, robot_mode=1, drl_state=3, tool_force=[0.]*6,
                       info=item.config["connection"]["tcp"] if path.startswith("tcp") else item.config["connection"]["tool"],
                       sol_space=0, conv_posj=[0.]*6)
        return SimpleNamespace(**outputs)
    item.call = call
    item._register = lambda address: 2 if address == 268 else 320
    registers = [0] * 18
    registers[9], registers[10], registers[17] = 320, 2, 320
    item.gripper = SimpleNamespace(read_holding_registers=lambda **kw:
        SimpleNamespace(isError=lambda: False, registers=registers))
    return item


def test_ros_numpy_arrays_are_normalized_before_checks_requests_and_logging():
    import numpy as np
    item = driver()
    original = item.call
    def call(path, kind, **fields):
        response = original(path, kind, **fields)
        for field in ("pos", "conv_posx", "vel", "tool_force", "conv_posj"):
            setattr(response, field, np.asarray(getattr(response, field), dtype=np.float64))
        if "pos" in fields:
            assert all(type(v) is float for v in fields["pos"])
        return response
    item.call = call
    sample = item.sample()
    for field in ("posx", "velx", "wrench"):
        assert all(type(v) is float for v in sample[field])
    assert item.check_pose([float(v) for v in item.config["start_posx"]]) == item.config["start_posx"]


@pytest.mark.parametrize("values", [[0.]*5, [0.]*7, [True]*6, ["0"]*6,
                                    [float("nan")]*6, [float("inf")]*6])
def test_ros_vector_still_rejects_invalid_responses(values):
    with pytest.raises(ValueError):
        response_vector(values, "response")


def test_motion_feedback_uses_actual_joint_fk_and_tool_velocity_not_target_posx():
    item = driver()
    result = item.sample()
    paths = [path for path, _, _ in item.calls]
    assert paths[:4] == ["aux_control/get_current_posj", "motion/fkin", "aux_control/get_current_velx", "motion/check_motion"]
    assert "aux_control/get_current_posx" not in paths and "aux_control/get_current_velj" not in paths
    assert result["posx"] == item.config["start_posx"] and result["gripper_status"] == 2
    assert result["gripper_width_mm"] == 32 and result["query_duration_s"] >= 0
    assert result["posj"] == [0.]*6
    assert result["query_finished_monotonic_s"] >= result["query_started_monotonic_s"]


def test_wrench_uses_controller_aux_control_service_with_ref_zero():
    item = driver()
    original = item.call
    def call(path, kind, **fields):
        if kind == "GetToolForce" and path != "aux_control/get_tool_force":
            raise TimeoutError("SERVICE_UNAVAILABLE")
        return original(path, kind, **fields)
    item.call = call
    assert item.sample()["wrench"] == [0.] * 6
    assert ("aux_control/get_tool_force", "GetToolForce", {"ref": 0}) in item.calls


def test_move_and_stop_requests_have_reviewed_base_absolute_async_fields_and_no_grip_write():
    item = driver()
    pose = [float(v) for v in item.config["waypoints"][0]]
    item.move_line_async(pose, [1., 1.], [1., 1.])
    item.stop()
    assert item.calls == [
        ("motion/move_line", "MoveLine", dict(pos=pose, vel=[1., 1.], acc=[1., 1.],
              time=0., radius=0., ref=0, mode=0, blend_type=0, sync_type=1)),
        ("motion/move_stop", "MoveStop", dict(stop_mode=1))]


def test_ik_fk_uses_current_solution_branch_and_never_dispatches():
    item = driver()
    assert item.check_pose(item.config["start_posx"]) == item.config["start_posx"]
    assert [path for path, _, _ in item.calls] == ["aux_control/get_current_posj",
        "aux_control/get_solution_space", "motion/ikin", "motion/fkin"]


def test_invalid_ik_solution_branch_is_not_forwarded():
    item = driver()
    original = item.call
    item.call = lambda path, kind, **fields: SimpleNamespace(sol_space=-1) if kind == "GetSolutionSpace" else original(path, kind, **fields)
    with pytest.raises(ValueError, match="solution space"):
        item.check_pose(item.config["start_posx"])
    assert not any(path == "motion/ikin" for path, _, _ in item.calls)


@pytest.mark.parametrize("case", ["missing", "timeout", "response_none", "success_false"])
def test_service_failures_remain_failures(case):
    item = AssemblyMotionRos.__new__(AssemblyMotionRos)
    item.config = configuration()
    future = SimpleNamespace(done=lambda: case != "timeout", result=lambda:
        None if case == "response_none" else SimpleNamespace(success=case != "success_false"))
    client = SimpleNamespace(wait_for_service=lambda **kwargs: case != "missing",
                             call_async=lambda request: future)
    item.client = lambda *args: client
    item.srv = SimpleNamespace(Test=SimpleNamespace(Request=SimpleNamespace))
    item.ros = SimpleNamespace(spin_until_future_complete=lambda *args, **kwargs: None)
    item.node = object()
    with pytest.raises((RuntimeError, TimeoutError)):
        item.call("test/read", "Test")


def test_force_ack_uses_stop_window_without_resending_or_changing_read_deadline():
    item=AssemblyMotionRos.__new__(AssemblyMotionRos)
    item.config={'timing':{'service_timeout_s':.5,'stop_timeout_s':3.}}
    requests=[];timeouts=[];ready=False
    future=SimpleNamespace(done=lambda:ready,result=lambda:SimpleNamespace(success=True))
    client=SimpleNamespace(wait_for_service=lambda **kw:True,
        call_async=lambda request:(requests.append(request) or future))
    item.client=lambda *a:client;item.node=object()
    item.srv=SimpleNamespace(Test=SimpleNamespace(Request=SimpleNamespace))
    def spin(*a,**kw):
        nonlocal ready
        timeouts.append(kw['timeout_sec']);ready=kw['timeout_sec']>=3.
    item.ros=SimpleNamespace(spin_until_future_complete=spin)
    with pytest.raises(TimeoutError):item.call('aux_control/test','Test')
    assert item.call('force/test','Test').success
    assert timeouts==[.5,3.] and len(requests)==2


def test_modbus_path_exposes_read_only_register_access():
    item = AssemblyMotionRos.__new__(AssemblyMotionRos)
    calls = []
    def read(**fields):
        calls.append(fields)
        return SimpleNamespace(isError=lambda: False, registers=[2])
    item.gripper = SimpleNamespace(read_holding_registers=read)
    assert item._register(268) == 2
    assert calls == [dict(address=268, count=1, slave=65)]


@pytest.mark.parametrize('offset_register,offset_mm', [(43, 4.3), (65526, -1.)])
def test_gripper_sample_preserves_raw_width_and_reads_offset_aware_width(offset_register, offset_mm):
    item = driver()
    reads = []
    values = {268: 2, 267: 406, 258: offset_register, 275: 320}
    def read(**fields):
        reads.append(fields)
        return SimpleNamespace(isError=lambda: False,
            registers=[values.get(address, 0) for address in range(258, 276)])
    item.gripper = SimpleNamespace(read_holding_registers=read)
    result = item.sample()
    assert reads == [dict(address=258, count=18, slave=65)]
    assert result['gripper_width_mm'] == 40.6
    assert result['gripper_width_with_offset_mm'] == 32.
    assert result['gripper_fingertip_offset_mm'] == offset_mm


def test_feedback_block_timeout_is_not_replaced_by_raw_width():
    item = driver()
    reads = []
    def read(**fields):
        reads.append(fields)
        raise TimeoutError('FEEDBACK_BLOCK_READ_TIMEOUT')
    item.gripper = SimpleNamespace(read_holding_registers=read)
    with pytest.raises(TimeoutError, match='FEEDBACK_BLOCK_READ_TIMEOUT'):
        item.sample()
    assert reads == [dict(address=258, count=18, slave=65)]


@pytest.mark.parametrize('register_count,is_error', [(17, False), (19, False), (18, True)])
def test_incomplete_or_error_feedback_block_remains_a_read_failure(register_count, is_error):
    item = driver()
    item.gripper = SimpleNamespace(read_holding_registers=lambda **kw:
        SimpleNamespace(isError=lambda: is_error, registers=[0]*register_count))
    with pytest.raises(ConnectionError, match='GRIPPER_READ_FAILED: 258..275'):
        item.sample()


def test_contact_force_requests_match_installed_ros_schema_without_gripper_or_mode_writes():
    item=driver();item.enable_compliance([3000.]*3+[200.]*3,.2)
    item.set_downward_force(6.,.2);item.release_force(0.);item.release_compliance()
    assert item.calls==[
        ('force/task_compliance_ctrl','TaskComplianceCtrl',dict(stx=[3000.]*3+[200.]*3,ref=0,time=.2)),
        ('force/set_desired_force','SetDesiredForce',dict(fd=[0.,0.,-6.,0.,0.,0.],dir=[0,0,1,0,0,0],ref=0,time=.2,mod=1)),
        ('force/release_force','ReleaseForce',dict(time=0.)),
        ('force/release_compliance_ctrl','ReleaseComplianceCtrl',{})]


def test_contact_capability_check_creates_clients_but_never_dispatches_requests():
    item=driver();paths=[];item.prefix='/dsr01/dsr_controller2/'
    item.client=lambda path,kind:(paths.append(path) or SimpleNamespace(wait_for_service=lambda **k:True))
    assert len(item.check_contact_services())==6 and item.calls==[]
    item.client=lambda path,kind:SimpleNamespace(wait_for_service=lambda **k:False)
    with pytest.raises(TimeoutError,match='SERVICE_UNAVAILABLE'):item.check_contact_services()


def test_local_ik_equivalent_wrist_wrap_is_rejected_before_motion():
    item=driver();original=item.call
    def call(path,kind,**fields):
        out=original(path,kind,**fields)
        if path=='motion/ikin':out.conv_posj=[0.,0.,0.,360.,0.,0.]
        return out
    item.call=call
    with pytest.raises(RuntimeError,match='LOCAL_IK_JOINT_JUMP'):
        item.check_pose(item.config['start_posx'],max_joint_delta_deg=10)
    assert all(path not in ('motion/move_line','motion/fkin') for path,kind,fields in item.calls)


def test_pressure_stages_use_absolute_controller_mode():
    item=driver()
    item.set_downward_force(25.,.2,relative=False)
    item.set_downward_force(30.,.2,relative=False)
    assert [fields['mod'] for _,_,fields in item.calls]==[0,0]
    assert [fields['fd'][2] for _,_,fields in item.calls]==[-25.,-30.]
    assert all(fields['dir']==[0,0,1,0,0,0] for _,_,fields in item.calls)


def test_stopped_slow_query_is_replaced_by_new_read_without_faking_timing(monkeypatch):
    from copy import deepcopy
    item=driver();original=item.sample();late=deepcopy(original);late['query_duration_s']=.7
    fresh=deepcopy(original);fresh['query_duration_s']=.12;fresh['posx'][2]+=.1
    reads=[late,fresh];events=[]
    item._sample_once=lambda:reads.pop(0)
    item.config['timing']['stopped_sample_retry_window_s']=5.
    item.feedback_record=lambda event,data:events.append((event,data))
    monkeypatch.setattr('app.assembly_motion_ros.time.sleep',lambda _:None)
    result=item.sample()
    assert result is fresh and result['query_duration_s']==.12
    assert late['query_duration_s']==.7 and events[0][1]['sample'] is late
    assert not reads and events[0][0]=='FEEDBACK_REFRESH_WAIT'


@pytest.mark.parametrize('case',['moving','force','equipment'])
def test_stale_query_never_waits_through_motion_force_or_equipment_fault(case):
    item=driver();late=item.sample();late['query_duration_s']=.7
    if case=='moving':late['motion_status']=1
    if case=='force':late['wrench'][2]=35.
    if case=='equipment':late['tcp']='WRONG_TCP'
    item.config['timing']['stopped_sample_retry_window_s']=5.
    calls=[]
    def read():calls.append(1);return late
    item._sample_once=read
    assert item.sample() is late and calls==[1]


def test_target_only_stopped_requery_accepts_velocity_jitter_and_60n_residual_then_uses_fresh_read(monkeypatch):
    from copy import deepcopy
    item=driver();late=item.sample();late.update(query_duration_s=.7,velx=[.002]*6,wrench=[0.,0.,60.,0.,0.,0.])
    fresh=deepcopy(late);fresh['query_duration_s']=.12
    reads=[late,fresh];events=[]
    item.config.update(target_only_motion=True,stale_retry_force_stop_n=None)
    item.config['timing']['stopped_sample_retry_window_s']=5.
    item._sample_once=lambda:reads.pop(0)
    item.feedback_record=lambda event,data:events.append((event,data))
    monkeypatch.setattr('app.assembly_motion_ros.time.sleep',lambda _:None)
    assert item.sample() is fresh and not reads
    assert events[0][0]=='FEEDBACK_REFRESH_WAIT' and late['query_duration_s']==.7


@pytest.mark.parametrize('case',['moving','equipment'])
def test_target_only_stale_requery_still_does_not_wait_through_motion_or_equipment_fault(case):
    item=driver();late=item.sample();late.update(query_duration_s=.7,velx=[.002]*6,wrench=[0.,0.,60.,0.,0.,0.])
    if case=='moving':late['motion_status']=2
    else:late['tcp']='WRONG_TCP'
    item.config.update(target_only_motion=True,stale_retry_force_stop_n=None)
    item.config['timing']['stopped_sample_retry_window_s']=5.
    calls=[];item._sample_once=lambda:(calls.append(1) or late)
    assert item.sample() is late and calls==[1]
