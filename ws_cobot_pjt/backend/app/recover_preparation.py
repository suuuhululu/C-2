"""정비용: HMI 종료 후 '모션 전 제어권 검사 거절' 한 건만 보존형 무효화.

Action/정지/제어권 명령은 호출하지 않는다. 일반 UNKNOWN 복구 도구가 아니다.
"""
import argparse
from copy import deepcopy
import fcntl
import json
import math
import time
from pathlib import Path

from .storage import Storage
from .monitor_contract import now


def validate_rejection(store, rid):
    record = store.preparation(rid)
    if not record or record['state'] != 'UNKNOWN':
        raise ValueError('UNKNOWN 요청 한 건만 지정하세요.')
    ref = record['measurement_record']
    raw = json.loads(store.read_asset(ref['id'], ref['sha256']))
    result = raw['result']
    goal = record['action_goal']
    if (raw['contract'] != 'prepare-workpiece-result/1' or goal['operation'] != 'MEASURE'
            or goal['source_mode'] != 'REAL' or result['outcome'] != 'FAILED'
            or result['error_code'] != 'NOT_READY'
            or result['message'] != '정지 래치 또는 로봇 제어권 미확인'
            or result['contact_indices'] != [] or result['geometry_ready'] is not False
            or result['snapshot_bound'] is not False or record.get('bind_goal')):
        raise ValueError('모션 전 제어권 검사 거절로 확인되지 않습니다. 자동 복구 금지.')
    if any(result.get(k) != v for k, v in goal.items() if k != 'schema_version'):
        raise ValueError('원본 Result와 Goal 참조 불일치')
    if any(e.get('stage') not in ('VALIDATING', 'ROBOT_CHECK', 'COMPLETE') for e in record['feedback']):
        raise ValueError('홈/측정 단계 진입 이력이 있습니다.')
    config = json.loads(store.read_asset(goal['input_profile_snapshot_id'], goal['input_profile_sha256']))
    return record, config


def observe_idle(config):
    """기존 조회 서비스만 사용. 사용자 정지 확인과 함께 사용하는 관측 근거."""
    import rclpy
    from dsr_msgs2.srv import GetRobotState, CheckMotion, GetCurrentPosj
    from c2_interfaces.msg import ProcessState
    from std_msgs.msg import String
    prefix = config['controller_prefix']
    rclpy.init(args=[])
    node = rclpy.create_node('hmi_preparation_recovery_readonly')
    process, authority = [], []
    node.create_subscription(ProcessState, '/c2/process_state', lambda m: process.append((time.monotonic(), m)), 1)
    node.create_subscription(String, prefix+'/control_authority', lambda m: authority.append((time.monotonic(), json.loads(m.data))), 1)
    clients = [(node.create_client(t, prefix+'/'+name), t) for t, name in (
        (GetRobotState, 'system/get_robot_state'), (CheckMotion, 'motion/check_motion'),
        (GetCurrentPosj, 'aux_control/get_current_posj'))]
    def read():
        values = []
        for client, typ in clients:
            if not client.wait_for_service(timeout_sec=2): raise ValueError('조회 서비스 없음')
            future = client.call_async(typ.Request())
            rclpy.spin_until_future_complete(node, future, timeout_sec=2)
            if not future.done() or not future.result().success: raise ValueError('조회 실패')
            values.append(future.result())
        state, motion, joints = values
        if state.robot_state != 1 or motion.status != 0: raise ValueError('STANDBY/IDLE 아님')
        pos = list(joints.pos)
        if len(pos) != 6 or not all(math.isfinite(v) for v in pos): raise ValueError('관절 미확인')
        return pos
    try:
        # ROS 참가자 발견을 기다리되, 오래된 관측을 허용하는 것으로 대체하지 않는다.
        discovery_deadline = time.monotonic()+5.
        while (not process or not authority) and time.monotonic() < discovery_deadline:
            rclpy.spin_once(node, timeout_sec=.1)
        if not process or not authority:
            raise ValueError('공정 상태/제어권 발견 제한시간 초과')
        first = read()
        end = time.monotonic()+max(.5, config['guards']['stop_stable_s'])
        samples = [first]
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=.05)
            pos = read()
            if any(abs(a-b) > config['guards']['movement_start_deg'] for a,b in zip(first,pos)):
                raise ValueError('관절 변동 확인: 복구 거절')
            samples.append(pos)
        if not process or time.monotonic()-process[-1][0] > .5: raise ValueError('공정 상태 미수신')
        p = process[-1][1]
        if p.source_mode != 'REAL' or p.status != 'IDLE' or p.run_id or p.stop_state != 'NONE':
            raise ValueError('공정 대기 상태 아님')
        if not authority or time.monotonic()-authority[-1][0] > .5: raise ValueError('제어권 미수신')
        a = authority[-1][1]
        if (a.get('schema_version') != 1 or a.get('source') != 'CONTROLLER_ACCESS_CONTROL'
                or not all(a.get(k) is True for k in ('active','connected','valid','has_control'))
                or not 0 <= a.get('monitoring_age_ms', -1) <= 500
                or not 0 <= time.time_ns()-a.get('published_at_unix_ns', 0) <= 500_000_000):
            raise ValueError('유효한 제어권 관측 아님')
        return dict(observed_at=now(), process_epoch=p.source_epoch, process_status=p.status,
                    robot_state=1, motion_status=0, joints_deg=samples, authority=a,
                    operator_confirmed_stopped=True)
    finally:
        node.destroy_node()
        rclpy.shutdown()


def recover(store, record, evidence):
    before = deepcopy(record)
    audit = store.put_json(dict(before=before, evidence=evidence, reason='모션 전 제어권 검사 거절 후 운영자 확인 복구'),
                           'preparation_recovery', 'recovery.json')
    record.update(state='INVALIDATED', binding_status='UNCONFIRMED', updated_at=now(),
                  recovery_record=dict(id=audit['id'], sha256=audit['sha256']),
                  message='이전 모션 전 거절 기록 보존·복구 완료. 새 요청으로 다시 준비하세요.')
    store.save_preparation(record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--operator-confirmed-stopped', action='store_true', required=True)
    args = parser.parse_args()
    root = Path(args.data_dir).resolve()
    if not (root/'monitor.sqlite3').is_file(): raise ValueError('기존 DB 경로 필요')
    with (root/'.server.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # 살아 있는 HMI와 원장 동시 수정 금지
        store = Storage(root)
        record, config = validate_rejection(store, args.request_id)
        evidence = observe_idle(config)
        print(json.dumps(recover(store, record, evidence), ensure_ascii=False))


if __name__ == '__main__': main()
