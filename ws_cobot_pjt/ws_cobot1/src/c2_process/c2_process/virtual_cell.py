"""세은 공정 노드에 연결하는 가상 장치. 실제 드라이버를 생성하지 않는다."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from .node import (create_ros_node, make_asset_bundle_loader, make_hmi_asset_resolver,
                   build_execution_settings, InputsUnavailable, PreconditionEvidence, RunJournal)
from .robot_adapter import MockRobotAdapter
from .preparation_action import AssetResolver, make_simulation_runner_factory


def simulation_settings():
    """가상 장치 전용 설정. 실물의 속도·깊이·관절 한계를 보증하지 않는다."""
    return dict(contract='c2-virtual-device/1', source_mode='SIMULATION', test_only=True,
        real_execution_allowed=False, provenance='SYNTHETIC_VIRTUAL_DEVICE',
        motion_profiles={name:dict(id=name,vel_mm_s=5.,acc_mm_s2=10.,pos_tol_mm=.15,completion_timeout_s=90.)
                         for name in ('candle_approach','candle_cut','candle_travel','candle_retract')},
        tool_profile=dict(tool_id='engraving_drill',contact_mode='fixed_depth',tool_axis='-y',
                          depth_m=.0003,clearance_m=.002),
        stop_profile=dict(mode=1,confirmation_timeout_s=2.),
        joint_limits_deg=[[-355,355],[-90,90],[-130,130],[-355,355],[-130,130],[-345,345]],
        j6_margin_deg=0.,tool_offset_m=[0.,-.1,0.])


def make_settings_resolver(adapter):
    def resolve(snapshot, goal, snapshot_id):
        cfg=snapshot.get('virtual_device')
        if (type(adapter) is not MockRobotAdapter or goal.get('source_mode')!='SIMULATION'
                or snapshot.get('source_mode')!='SIMULATION' or cfg!=simulation_settings()):
            raise InputsUnavailable('가상 장치는 등록된 SIMULATION 전용 설정만 받습니다.', 'PROFILE_MISMATCH')
        surface=snapshot['surface']
        origin=surface['axis_origin_m']
        workcell=dict(axis_xy_m=origin[:2],radius_m=surface['radius_mm']/1000,
                      top_z_m=origin[2]+surface['height_mm']/1000)
        evidence=PreconditionEvidence(runtime_mode='SIMULATION',robot_state=adapter.observe(),
            control_authority_confirmed=True,stop_latched=adapter.stopped,
            profile_snapshot_id=snapshot_id,max_robot_state_age_s=2.)
        return build_execution_settings(goal,evidence=evidence,adapter=adapter,workcell=workcell,
            calibration_record=None,calibration_snapshot_id=snapshot_id,calibration_profiles=None,
            motion_profiles=cfg['motion_profiles'],tool_profile=cfg['tool_profile'],stop_profile=cfg['stop_profile'],
            tip_tolerance_m=None,joint_limits_deg=cfg['joint_limits_deg'],j6_margin_deg=cfg['j6_margin_deg'],
            require_tool_verification=False,tool_offset_m=cfg['tool_offset_m'])
    return resolve


class VirtualRunJournal(RunJournal):
    """실행 경계에서 모의 호출을 저장한다. 중복 요청은 별도 실행으로 기록하지 않는다."""
    def __init__(self, path, adapter, scenario):
        super().__init__(path)
        self.adapter, self.scenario = adapter, scenario
        self.active = {}

    def reserve(self, request_id, identity):
        previous = super().reserve(request_id, identity)
        if previous is None:
            self.active[request_id] = (identity, len(self.adapter.calls))
        return previous

    def finish(self, request_id, result):
        super().finish(request_id, result)
        identity, start = self.active.pop(request_id)
        payload = dict(source='SYNTHETIC_VIRTUAL_DEVICE', scenario=self.scenario,
            request_id=request_id, run_id=identity[0], path_id=identity[2],
            path_version=identity[3], path_sha256=identity[4],
            outcome=result.outcome, error_code=result.error_code,
            observed_state=result.observed_state,
            calls=self.adapter.calls[start:])
        # 경로명은 요청 문자열 대신 해시로 만들어 외부 입력을 파일 경로로 사용하지 않는다.
        import hashlib
        name = hashlib.sha256(identity[0].encode()).hexdigest()
        destination = self.path.parent / ('motion-' + name + '.json')
        temporary = destination.with_suffix('.tmp')
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        temporary.replace(destination)


def main(args=None):
    parser=argparse.ArgumentParser(description='가상 로봇 + 실제 c2_process 노드 (실물 미연결)')
    parser.add_argument('--backend-url',default='http://127.0.0.1:8020')
    parser.add_argument('--data-dir',required=True)
    parser.add_argument('--scenario',choices=['normal','ik_failure','motion_failure'],default='normal')
    parser.add_argument('--move-time',type=float,default=.06)
    options=parser.parse_args(args)
    if os.getenv('C2_VIRTUAL_CELL')!='1' or os.getenv('ROS_DOMAIN_ID')!='174':
        parser.error('전용 실행기(C2_VIRTUAL_CELL=1, ROS_DOMAIN_ID=174)를 사용하세요.')
    if not 0<=options.move_time<=10: parser.error('move-time은 0~10초')
    data=Path(options.data_dir).resolve();data.mkdir(parents=True,exist_ok=True)
    adapter=MockRobotAdapter(move_time_s=options.move_time)
    if options.scenario=='ik_failure':adapter.ik_fail_at_call=1
    if options.scenario=='motion_failure':adapter.fail_at='move'
    loader=make_asset_bundle_loader(make_hmi_asset_resolver(options.backend_url),make_settings_resolver(adapter))
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    rclpy.init(args=[])
    node=create_ros_node(load_inputs=loader,runtime_mode='SIMULATION',preparation_required=True,
        journal=VirtualRunJournal(data/'execution.sqlite3',adapter,options.scenario),
        preparation_resolver=AssetResolver(options.backend_url),preparation_journal_path=data/'preparation.sqlite3',
        preparation_runner_factory=make_simulation_runner_factory(status_adapter=adapter))
    # 실제 ROS 상태 토픽은 실제 공정 노드가 발행. 내용만 가상 장치 관측값이다.
    observer=node.create_timer(.1,lambda:node.observations.capture(adapter.observe(),adapter.tool_offset_m,2.))
    node.message='가상 장치 연결 · 실제 로봇 미연결'
    last_call_count = 0
    def report_device():
        nonlocal last_call_count
        if len(adapter.calls) != last_call_count:
            last_call_count = len(adapter.calls)
            node.get_logger().info(f'가상 호출 {last_call_count}회 / 마지막 {adapter.calls[-1]["fn"]} / TCP {adapter.pose[:3]}')
    report_timer=node.create_timer(1.,report_device)
    executor=MultiThreadedExecutor(num_threads=4);executor.add_node(node)
    node.get_logger().warn('VIRTUAL DEVICE: 실제 드라이버 없음 / 모의 IK·접촉 / scenario='+options.scenario)
    try:executor.spin()
    except KeyboardInterrupt:pass
    finally:
        executor.shutdown()
        (data/'virtual-motion-log.json').write_text(json.dumps(dict(source='SYNTHETIC_VIRTUAL_DEVICE',
            scenario=options.scenario,calls=adapter.calls),ensure_ascii=False,indent=2))
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()

if __name__=='__main__':main()
