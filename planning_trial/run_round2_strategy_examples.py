"""Generate complete A 0.5.2 review messages for D; no device/C/D execution."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from planning_trial.assembly_adapter import handle_whole_plan, handle_step_reassessment, handle_step_motion
from planning_trial.assembly_api_fixtures import whole_request, reassess_request, motion_request, frame_profile
from planning_trial.assembly_contract import VERSION, validate_message


def brick(x=6,y=6,layer=1):
    return dict(brick_type='2x2x1',color='yellow',x=x,y=y,layer=layer,orientation_deg=0)


def build_examples():
    seed=json.loads((Path(__file__).parent/'fixtures/round2_release_press.synthetic.json').read_text())
    neighbors=[brick(4,6),brick(8,6)]
    cases=[
        ('ordinary_robot',[],brick(),None,'NONE'),
        ('release_press',seed['current']['blocks'],brick(),'RELEASE_PRESS','NONE'),
        ('partial_support_manual',[brick(6,5),*neighbors,*[b | {'layer':2} for b in neighbors]],brick(layer=2),None,'MANUAL_ASSEMBLY'),
        ('robot_hold',[brick(4,6),brick(7,4),brick(5,6,2),brick(7,5,2)],brick(layer=3),None,'HOLD'),
        ('robot_press_and_hold',[brick(4,6),brick(5,6,2)],brick(layer=3),None,'PRESS_AND_HOLD'),
        ('release_press_with_hold',[*neighbors,*[brick(x,6,2) for x in (3,5,7,9)],*[b | {'layer':3} for b in neighbors]],brick(layer=3),'RELEASE_PRESS','HOLD'),
    ]
    examples=[]
    for name,blocks,target,strategy,assistance in cases:
        context=deepcopy(seed['assembly_context']);context['grip_axes']=['x']
        profile=frame_profile()
        if name=='partial_support_manual':
            profile['calculation_profiles']['tray']={
                'profile_id':'SYNTHETIC_TRAY_NOT_D_TEACHING',
                'tcp_pose_mm_zyz_deg':[200,0,60,0,180,0],'travel_tcp_z_mm':180}
        current=dict(current_revision=len(blocks),blocks=blocks)
        request=whole_request(dict(design_version=1,blocks=blocks+[target]),current,context,profile)
        whole=handle_whole_plan(request)
        re_req=reassess_request(request,whole);assessment=handle_step_reassessment(re_req)
        mo_req=motion_request(re_req,assessment,profile);motion=handle_step_motion(mo_req)
        action=assessment['action_proposal']
        assert action.get('assembly_strategy')==strategy and action['assistance_kind']==assistance
        assert motion['status']==('BLOCKED' if strategy else 'CANDIDATE'),motion
        if strategy: assert motion['errors'][0]['code']=='UNSUPPORTED_METHOD'
        messages=dict(whole_request=request,whole_result=whole,
            reassessment_request=re_req,reassessment_result=assessment,
            motion_request=mo_req,motion_result=motion)
        for message in messages.values():validate_message(message)
        examples.append(dict(case_id=name,expected_strategy=strategy,
            expected_assistance_kind=assistance,messages=messages))
    return dict(bundle_kind='A_052_FULL_MESSAGE_REVIEW_EXAMPLES',schema_version=VERSION,
        sample_kind='SYNTHETIC_REVIEW_NOT_FOR_EXECUTION',execution_allowed=False,
        note='Complete actual A API messages from review fixtures, not measured D profiles or C-approved live designs. B Current values here are synthetic.',
        examples=examples)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    data=build_examples();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print('Saved full messages:',len(data['examples']),args.output)


if __name__=='__main__':main()
