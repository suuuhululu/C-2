"""확정 Design/B Current와 D 설정으로 세 A 요청을 구성한다. 장치 호출 없음."""
from copy import deepcopy
from uuid import uuid4

from planning_trial.assembly_api_fixtures import whole_request, reassess_request, motion_request


def whole_input(design, current, settings, job_id, generation, epoch):
    # 예시의 envelope만 재사용한다. 계산 설정·프로필·실제 식별은 호출자가 공급한다.
    request = whole_request(design, current, settings['assembly_context'], settings['frame_profile'])
    request['context'].update(job_id=job_id, request_id=str(uuid4()), workflow_generation=generation,
                              source_epoch=epoch, world_state_revision=current['current_revision'])
    request['policy'].update(finish_layers=settings['assembly_context']['finish_layers'],
        hold_gripper_nonintrusion_assumption=settings['assembly_context']['hold_gripper_nonintrusion_assumption'])
    return request


def assessment_input(whole, result, current, index, frame):
    request = reassess_request(whole, result, current, index)
    request['context'].update(request_id=str(uuid4()), frame_profile_id=frame['profile_id'],
                              frame_profile_version=frame['profile_version'])
    request['frame_profile'] = deepcopy(frame)
    # B Current가 달라져도 Plan의 예상 prefix를 실제값으로 덮어쓰지 않는다.
    expected = result['shared_planning_bundle']['expected_steps'][index]['before_blocks']
    request['expected_current_before_step'] = dict(current_revision=current['current_revision'],
                                                  blocks=deepcopy(expected))
    return request


def motion_input(assessment, result, frame, slot, robot_state):
    request = motion_request(assessment, result, profile=frame)
    request['context']['request_id'] = str(uuid4())
    request['reserved_supply_slot'] = deepcopy(slot)
    request['robot_state'] = deepcopy(robot_state)
    return request
