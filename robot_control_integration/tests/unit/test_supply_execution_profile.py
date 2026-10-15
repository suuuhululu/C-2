"""Approval and row binding checks without ROS or device connections."""
from copy import deepcopy
from hashlib import sha256
import json
import pytest
from app.supply_stud.execution_profile import bind, load, EXCEPTIONS


@pytest.fixture
def registry(tmp_path):
    entries=[]
    for color,kind in [('yellow','2x2x1'),('yellow','2x3x1'),('blue','2x2x1'),('blue','2x3x1'),('red','1x2x1')]:
        for slot in range(1,6):
            sid=f'{color}_{kind}_{slot:02d}'
            entries.append(dict(slot_id=sid,execution_mode='TEACHING_ONLY' if sid in EXCEPTIONS else 'RGBD_XY',
                execution_approved=True,automatic_depth_failure_fallback_enabled=False,
                reference_basis='OBSERVED_MODEL_BASELINE_NOT_PAIRED_GROUND_TRUTH',
                pickup_pose=([-410.,102.,49.,1.,179.,2.] if sid in EXCEPTIONS else [-400.,100.,50.,0.,180.,0.]),depth_profile='depth.json'))
    value=dict(schema_version='educational-supply-execution/1',operator_conditional_execution_approved=True,
        assembly_xy_correction_enabled=False,all_slots_physically_verified=False,slots=entries,
        source_sha256={},artifacts_sha256={},connection=dict(robot_id='dsr01',tcp='GripperDA_v4',tool='ToolWeight0'),
        observation_pose=[-440.,-38.,374.,8.,178.,8.])
    path=tmp_path/'profile.json';path.write_text(json.dumps(value));return path,value


def config(value, slot=5):
    return dict(connection=value['connection'], observation_pose=value['observation_pose'],
        blocks=[dict(color='yellow',brick_type='2x2x1',slot=slot,span=2,close_mm=35.,
            pickup_pose=[-410.,102.,49.,1.,179.,2.],center_mapping={'old':'mapping'})],
        vision={},velocity=12.,gripper_force_n=40.)


@pytest.mark.parametrize('slot,mode',[(1,'TEACHING_ONLY'),(2,'TEACHING_ONLY'),(3,'TEACHING_ONLY'),(4,'RGBD_XY'),(5,'RGBD_XY')])
def test_explicit_modes_preserve_height_attitude_motion_and_jaws(registry,slot,mode):
    path,value=registry; cfg=config(value,slot); original=deepcopy(cfg)
    result=bind(cfg,path)
    assert result['educational_supply_binding']['execution_mode']==mode
    assert result['blocks'][0]['pickup_pose']==original['blocks'][0]['pickup_pose']
    assert result['blocks'][0]['close_mm']==35. and result['velocity']==12. and result['gripper_force_n']==40.
    assert result['assembly_xy_correction_enabled'] is False
    assert bool(result['vision'].get('depth_center_profile'))==(mode=='RGBD_XY')
    assert 'center_mapping' not in result['blocks'][0]
    assert cfg==original


@pytest.mark.parametrize('change', ['approval','mode','duplicates','verified','source'])
def test_reject_changed_or_unapproved_registry(registry,change,tmp_path):
    path,value=registry
    if change=='approval':value['operator_conditional_execution_approved']=False
    if change=='mode':value['slots'][0]['execution_mode']='RGBD_XY'
    if change=='duplicates':value['slots'][-1]=deepcopy(value['slots'][0])
    if change=='verified':value['all_slots_physically_verified']=True
    if change=='source':
        source=tmp_path/'source.json';source.write_text('changed');value['source_sha256'][str(source)]=sha256(b'original').hexdigest()
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError): load(path)


def test_paired_reference_rejects_changed_height(registry):
    path,value=registry;value['slots'][4]['reference_basis']='PAIRED_MEASURED_AND_SINGLE_GRASP_TESTED'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='HEIGHT_ATTITUDE_MISMATCH'):bind(config(value),path)


def test_teaching_exception_rejects_old_or_interpolated_pose(registry):
    path,value=registry;cfg=config(value,2);cfg['blocks'][0]['pickup_pose'][0]+=1.
    with pytest.raises(ValueError,match='EXACT_TEACHING_POSE'):bind(cfg,path)


def test_relative_evidence_survives_bundle_relocation(registry,tmp_path):
    import shutil
    path,value=registry
    evidence=path.parent/'evidence.json';evidence.write_text('immutable measurement')
    value['source_path_basis']='BUNDLE_RELATIVE'
    value['source_sha256']={'evidence.json':sha256(evidence.read_bytes()).hexdigest()}
    path.write_text(json.dumps(value))
    target=tmp_path/'moved bundle';target.mkdir()
    shutil.copyfile(path,target/'profile.json');shutil.copyfile(evidence,target/'evidence.json')
    evidence.unlink()
    assert load(target/'profile.json')['source_path_basis']=='BUNDLE_RELATIVE'
    (target/'evidence.json').write_text('changed')
    with pytest.raises(ValueError,match='SOURCE_CHANGED'):load(target/'profile.json')


@pytest.mark.parametrize('source',['../outside.json','/tmp/outside.json'])
def test_portable_evidence_cannot_escape_bundle(registry,source):
    path,value=registry;value['source_path_basis']='BUNDLE_RELATIVE'
    value['source_sha256']={source:'not-read'}
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='MUST_STAY_IN_BUNDLE'):load(path)
