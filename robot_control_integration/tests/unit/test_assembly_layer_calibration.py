"""Measured layer separation, board convention and independent validation."""
import json
import pytest
from app.assembly_layer_calibration import seated_record,fit_layers,layer_pose
from app.assembly_contact_fake import ContactFake,fake_config
from scripts.assembly_contact_trial import TEMPLATE
from scripts.assembly_layer_calibration import main


def record(x,y,layer=1,role='fit',grasp='a'):
    c=fake_config(json.loads(TEMPLATE.read_text()));sample=ContactFake(c).sample()
    sample['posx']=[300+16*x,20+16*y,10+17.3*layer+.02*x-.01*y,30.,180.,30.]
    target=dict(brick_type='2x3x1',color='yellow',x=x,y=y,layer=layer,orientation_deg=0)
    return seated_record(target,sample,c,setup_id='fixture',grasp_id=grasp,role=role,confirmed=True)


def test_exact_point_available_per_layer_without_invented_stack_height():
    rows=[record(7,7,layer=k) for k in range(1,6)]
    report=fit_layers(rows)
    assert report['measured_layers']==[1,2,3,4,5] and not report['fitted_layers']
    assert not report['automatic_layer_height']
    for model,r in zip(report['models'],rows):
        p=layer_pose(model,r['target'])
        assert p['posx']==r['sample']['posx'] and not p['executable']
    with pytest.raises(ValueError,match='BLOCK_OR_LAYER'):
        layer_pose(report['models'][0],rows[1]['target'])


def test_explicit_layer_z_update_preserves_raw_records_and_other_layers():
    old=record(11,11,layer=5);new=record(11,9,layer=5);other=record(11,11,layer=4)
    new['sample']['posx'][2]=new['floor_z_mm']=old['sample']['posx'][2]-.5
    new['adopt_as_layer_z']=True
    rows=[old,new,other];original=json.dumps(rows)
    models=fit_layers(rows)['models']
    updated=layer_pose(models[0],old['target'])
    assert updated['floor_z_mm']==new['floor_z_mm']
    assert updated['posx'][:2]==old['sample']['posx'][:2]
    assert updated['status']=='LAYER_Z_UPDATED_POSE_CANDIDATE'
    assert updated['seated_z_reference']['record_id']==new['record_id']
    assert layer_pose(models[0],new['target'])['status']=='EXACT_TAUGHT_LAYER_POINT'
    assert layer_pose(models[1],other['target'])['posx']==other['sample']['posx']
    assert json.dumps(rows)==original


def test_affine_plane_uses_only_same_layer_and_grasp_and_reports_independent_error():
    rows=[record(0,0),record(22,0),record(0,21),record(7,7,role='check'),record(0,0,layer=2),record(0,0,grasp='b')]
    rows[3]['sample']['posx'][0]+=.4
    report=fit_layers(rows);assert len(report['models'])==3
    model=report['models'][0]
    assert len(model['fit_record_ids'])==3 and len(model['check_record_ids'])==1
    assert model['independent_checks'][0]['xyz_error_mm'][0]==pytest.approx(.4)
    target={**rows[0]['target'],'x':5,'y':8}
    assert layer_pose(model,target)['posx'][:3]==pytest.approx([380,148,27.32])
    assert model['fit_orientation_deviation_deg']==pytest.approx([0,0,0],abs=1e-10)
    assert not model['executable']


def test_collinear_points_do_not_generate_board_model():
    model=fit_layers([record(0,0),record(1,0),record(2,0)])['models'][0]
    assert 'xyz_coefficients' not in model
    with pytest.raises(ValueError,match='NOT_TAUGHT'):
        layer_pose(model,{**record(0,0)['target'],'x':1,'y':1})


def test_explicitly_excluded_transient_is_preserved_but_not_fitted():
    transient=record(7,7);transient['sample']['posx'][2]+=10
    transient['model_excluded']=True
    rows=[record(0,0),record(22,0),record(0,21),transient];original=json.dumps(rows)
    report=fit_layers(rows);model=report['models'][0]
    assert report['excluded_record_ids']==[transient['record_id']]
    assert transient['record_id'] not in model['fit_record_ids']
    assert layer_pose(model,transient['target'])['posx'][2]==pytest.approx(27.37)
    assert json.dumps(rows)==original


def test_six_point_minimum_stud_bounds_and_manual_confirmation():
    with pytest.raises(ValueError,match='outside board'):record(22,22)
    r=record(22,21);c=fake_config(json.loads(TEMPLATE.read_text()))
    with pytest.raises(ValueError,match='CONFIRMATION'):
        seated_record(r['target'],r['sample'],c,setup_id='s',grasp_id='g',role='fit')
    r['coordinate_convention']='LEGACY_TRIAL_XY'
    with pytest.raises(ValueError,match='LEGACY'):fit_layers([r])


def test_layer_capture_cli_is_readonly_and_preserves_repeated_measurements(tmp_path,monkeypatch):
    monkeypatch.setenv('ROS_DOMAIN_ID','20');devices=[]
    def factory(c):
        d=ContactFake(fake_config(c));d.robot_system=lambda:0;devices.append(d);return d
    path=tmp_path/'layers.json'
    args=['capture','--brick','4','--color','yellow','--layer','5','--xy','11','11',
        '--setup-id','setup','--grasp-id','g','--confirm-seated','--records',str(path)]
    assert main(args,driver_factory=factory)==0 and main(args,driver_factory=factory)==0
    assert len(json.loads(path.read_text()))==2
    assert all(r['target']['layer']==5 for r in json.loads(path.read_text()))
    assert all(d.closed and not d.calls for d in devices)
    assert main(['fit','--records',str(path),'--out',str(tmp_path/'models.json')])==0
