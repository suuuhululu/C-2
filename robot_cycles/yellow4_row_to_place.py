#!/usr/bin/env python3
"""Transfer yellow 4-stud blocks 1..6; offline plan unless --execute/--check."""
import argparse
import math
import time
HOME = [0., 0., 90., 0., 90., 0.]

PICK = [-323.991, 215.923, -3.178, 24.268, 178.39, 26.818]

PICK_J = [-213.031, 11.384, 109.717, -1.523, 59.769, -210.065]

PLACE = [417.561, -184.622, 19.712, 58.132, -176.4, -121.902]

PLACE_J = [-21.602, 18.152, 96.818, -3.793, 65.697, -200.404]

def above(pose, lift):
    result = list(pose)
    result[2] += lift
    return result

class Robot:
    def __init__(self, args):
        import rclpy
        from dsr_msgs2 import srv
        self.ros, self.srv, self.args = rclpy, srv, args
        rclpy.init(args=[])
        self.node = rclpy.create_node('yellow4_single_cycle')
        self.prefix = f'/{args.robot_id}/dsr_controller2/'
        self.clients = {}
        # Pre-create the stop client, so interruption does not require discovery.
        self.client('motion/move_stop', 'MoveStop')

    def client(self, path, typename):
        if path not in self.clients:
            self.clients[path] = self.node.create_client(getattr(self.srv, typename), self.prefix + path)
        return self.clients[path]

    def call(self, path, typename, timeout=10., **fields):
        client = self.client(path, typename)
        if not client.wait_for_service(timeout_sec=3.):
            raise RuntimeError(f'서비스를 찾을 수 없습니다: {self.prefix}{path}')
        request = getattr(self.srv, typename).Request()
        for key, value in fields.items():
            setattr(request, key, value)
        future = client.call_async(request)
        self.ros.spin_until_future_complete(self.node, future, timeout_sec=timeout)
        if not future.done():
            raise TimeoutError(f'응답 시간 초과: {path}; 이동 완료 여부를 확인하세요')
        response = future.result()
        if response is None or not response.success:
            raise RuntimeError(f'요청 실패: {path}: {response}')
        return response

    def preflight(self):
        for path, typename, expected in [
            ('tcp/get_current_tcp', 'GetCurrentTcp', self.args.tcp),
            ('tool/get_current_tool', 'GetCurrentTool', self.args.tool),
        ]:
            actual = self.call(path, typename).info
            if actual != expected:
                raise RuntimeError(f'{path}: 현재 {actual!r}, 필요 {expected!r}. 로봇에서 먼저 선택하세요.')
        state = self.call('system/get_robot_state', 'GetRobotState').robot_state
        if state != 1:
            raise RuntimeError(f'로봇이 대기 상태가 아닙니다: state={state}')
        joints = {}
        for name, reference_j, pose in [('pick', PICK_J, PICK), ('place', PLACE_J, PLACE)]:
            sol = self.call('aux_control/get_solution_space', 'GetSolutionSpace', pos=reference_j).sol_space
            # Check both taught and approach poses on the taught configuration branch.
            for suffix, target in [('target', pose), ('above', above(pose, self.args.lift))]:
                q = list(self.call('motion/ikin', 'Ikin', pos=target, sol_space=sol, ref=0).conv_posj)
                if not all(math.isfinite(v) for v in q):
                    raise RuntimeError(f'유효하지 않은 역기구학 결과: {name}_{suffix}')
                joints[f'{name}_{suffix}'] = q
            print(f'{name}: solution={sol}, 접근 관절각={joints[name + "_above"]}', flush=True)
        return joints

    def movej(self, q):
        self.call('motion/move_joint', 'MoveJoint', timeout=300., pos=list(q),
                  vel=self.args.joint_speed, acc=self.args.joint_acc,
                  time=0., radius=0., mode=0, blend_type=0, sync_type=0)

    def movel(self, pose):
        self.call('motion/move_line', 'MoveLine', timeout=300., pos=list(pose),
                  vel=[self.args.linear_speed, 10.], acc=[self.args.linear_acc, 20.],
                  time=0., radius=0., ref=0, mode=0, blend_type=0, sync_type=0)

    def stop(self):
        try:
            self.call('motion/move_stop', 'MoveStop', timeout=5., stop_mode=1)
        except Exception as exc:
            print(f'정지 요청 결과를 확인할 수 없습니다: {exc}. 티치펜던트에서 확인하세요.', flush=True)

    def close(self):
        self.node.destroy_node()
        if self.ros.ok():
            self.ros.shutdown()

class Gripper:
    """Physical RG2 Modbus only: no simulated/skip fallback."""
    def __init__(self, args):
        from pymodbus.client import ModbusTcpClient
        self.args = args
        self.client = ModbusTcpClient(args.gripper_ip, port=502, timeout=2.)
        if not self.client.connect():
            self.client.close()
            raise ConnectionError('그리퍼 연결 실패; 로봇 이동을 시작하지 않습니다')
        try:
            self.read(268)  # Verify communication before any motion.
        except BaseException:
            self.client.close()
            raise

    def read(self, address):
        result = self.client.read_holding_registers(address=address, count=1, slave=65)
        if result.isError():
            raise ConnectionError(f'그리퍼 읽기 실패: {result}')
        return result.registers[0]

    def move(self, width_mm, require_grip=False):
        status = self.read(268)
        if status & 0b1111100:
            raise RuntimeError(f'그리퍼 안전 스위치 상태 확인 필요: {status}')
        if status & 1:
            raise RuntimeError('그리퍼가 이미 움직이는 중입니다')
        result = self.client.write_registers(address=0,
                 values=[round(self.args.force * 10), round(width_mm * 10), 16], slave=65)
        if result.isError():
            raise ConnectionError(f'그리퍼 쓰기 실패: {result}')
        time.sleep(0.5)
        deadline = time.monotonic() + 8.
        while time.monotonic() < deadline:
            status = self.read(268)
            if status & 0b1111100:
                raise RuntimeError(f'그리퍼 안전 스위치 활성: {status}')
            if not status & 1:
                if require_grip and not status & 2:
                    time.sleep(0.1)
                    continue
                actual_width = self.read(267) / 10.
                if not require_grip and abs(actual_width - width_mm) > 3.:
                    raise RuntimeError(f'그리퍼 열림 부족: 요청 {width_mm}, 현재 {actual_width} mm')
                return
            time.sleep(0.1)
        raise TimeoutError('그리퍼 동작 시간 초과')

    def close(self):
        self.client.close()

START = [-323.991, 215.923, -3.178, 24.268, 178.39, 26.818]
END = [-645.111, 216.103, -12.736, 83.522, 176.955, 85.94]


def orientations(start, end, fractions):
    from scipy.spatial.transform import Rotation, Slerp
    rotations = Rotation.from_euler('ZYZ', [start[3:], end[3:]], degrees=True)
    return Slerp([0., 1.], rotations)(fractions).as_euler('ZYZ', degrees=True)


def picks():
    abc = orientations(START, END, [i / 5 for i in range(6)])
    poses = [[START[j] + (END[j] - START[j]) * i / 5 for j in range(3)] + list(abc[i]) for i in range(6)]
    poses[0], poses[-1] = START.copy(), END.copy()
    return poses


def route(start, end, height, bypass_y):
    """Constant Base Z transfer, with a lateral bypass of the robot base."""
    waypoints = [[-150., bypass_y, height], [150., bypass_y, height]]
    if end[0] < start[0]:
        waypoints.reverse()
    xyz = [[start[0], start[1], height], *waypoints, [end[0], end[1], height]]
    lengths = [math.dist(xyz[i], xyz[i+1]) for i in range(3)]
    total = sum(lengths)
    fractions = [0., lengths[0]/total, sum(lengths[:2])/total, 1.]
    abc = orientations(start, end, fractions)
    result = [xyz[i] + list(abc[i]) for i in range(4)]
    result[0][3:], result[-1][3:] = start[3:], end[3:]
    return result


def plan(args):
    ps = picks()
    commands = [('joint', '시작 홈', HOME, None)]
    for i in range(args.start_block - 1, 6):
        p = ps[i]
        staging = p.copy()
        staging[0] = max(p[0], args.supply_staging_x)
        high = route(staging, PLACE, args.transit_z, args.bypass_y)
        if i == args.start_block - 1:
            commands += [('grip_open', '60 mm 열기', None, i+1),
                         ('initial_approach', '첫 픽업 높은 접근점', high[0], i+1)]
        else:
            backward = route(PLACE, staging, args.transit_z, args.bypass_y)
            commands += [('line_transit', '빈 그리퍼 높은 복귀 경로', pose, i+1) for pose in backward[1:]]
        commands += [
            ('line_transit', '픽업 30 mm 위 접근 (먼 블록은 대각 접근)', above(p, args.lift), i+1),
            ('line_local', '픽업 위치로 하강', p, i+1),
            ('grip_close', '집기 및 감지 대기', None, i+1),
            ('line_local', '픽업 후 30 mm 상승', above(p, args.lift), i+1),
            ('line_transit', '높은 이송 경유점 접근 (먼 블록은 안쪽으로 상승)', high[0], i+1),
        ]
        commands += [('line_transit', '높은 경유 경로로 이송', pose, i+1) for pose in high[1:]]
        commands += [
            ('line_transit', '놓기 30 mm 위까지 수직 접근', above(PLACE, args.lift), i+1),
            ('line_local', '지정 놓기 위치로 하강', PLACE, i+1),
            ('grip_open', '60 mm 열어 블록 놓기', None, i+1),
            ('line_local', '놓은 뒤 30 mm 후퇴', above(PLACE, args.lift), i+1),
            ('line_transit', '높은 위치까지 수직 상승', high[-1], i+1),
        ]
        if i < 5:
            commands.append(('clear_place', '놓기 공간 비우기 확인', None, i+1))
    commands.append(('joint', '마지막 홈 복귀', HOME, None))
    return commands


class RowRobot(Robot):
    def verify_setup(self):
        for path, typename, expected in [('tcp/get_current_tcp','GetCurrentTcp',self.args.tcp),
                                          ('tool/get_current_tool','GetCurrentTool',self.args.tool)]:
            actual = self.call(path, typename).info
            if actual != expected:
                raise RuntimeError(f'{path}: 현재 {actual!r}, 필요 {expected!r}')
        state = self.call('system/get_robot_state','GetRobotState').robot_state
        if state != 1:
            raise RuntimeError(f'로봇 대기 상태 필요: state={state}')
        sols = [self.call('aux_control/get_solution_space','GetSolutionSpace',pos=q).sol_space
                for q in (PICK_J, PLACE_J)]
        if sols[0] != sols[1]:
            raise RuntimeError(f'픽업/놓기 자세의 기구학 해가 다릅니다: {sols}. 연속 직선 경로 재설계 필요')
        return sols[0]

    def ik(self, pose, sol):
        q = list(self.call('motion/ikin','Ikin',pos=[float(v) for v in pose],sol_space=sol,ref=0).conv_posj)
        if not all(math.isfinite(v) for v in q):
            raise RuntimeError('역기구학 결과가 유효하지 않습니다')
        # Ikin service can return success=True even for a bad result; cross-check XYZ.
        fk = list(self.call('motion/fkin','Fkin',pos=q,ref=0).conv_posx)
        if math.dist(fk[:3],pose[:3]) > 2.:
            raise RuntimeError(f'도달 불가 접근점: {pose}; FK 오차={math.dist(fk[:3],pose[:3]):.2f} mm')
        from scipy.spatial.transform import Rotation
        error = (Rotation.from_euler('ZYZ',fk[3:],degrees=True).inv() *
                 Rotation.from_euler('ZYZ',pose[3:],degrees=True)).magnitude()
        if math.degrees(error) > 1.:
            raise RuntimeError('역기구학 자세 검증 실패')
        return q

    def check_plan(self, commands, sol):
        initial = None
        previous = None
        cache = set()
        for kind,label,target,block in commands:
            if not kind.startswith('line') and kind != 'initial_approach':
                if kind == 'joint':
                    previous = None
                continue
            samples = [target]
            if previous is not None:
                # Sample both position and orientation along each intended linear segment.
                n = max(1,math.ceil(math.dist(previous[:3],target[:3])/50.))
                abc = orientations(previous,target,[k/n for k in range(1,n+1)])
                samples = [[previous[j]+(target[j]-previous[j])*k/n for j in range(3)] + list(abc[k-1])
                           for k in range(1,n+1)]
            for pose in samples:
                key = tuple(round(float(v),4) for v in pose)
                if key not in cache:
                    q = self.ik(pose,sol)
                    cache.add(key)
                    if kind == 'initial_approach' and initial is None:
                        initial = q
            previous = target
        print(f'경로의 {len(cache)}개 표본점 IK/FK 확인 완료. 충돌 검증은 포함하지 않습니다.',flush=True)
        return initial

    def line(self, pose, speed):
        self.call('motion/move_line','MoveLine',timeout=300.,pos=[float(v) for v in pose],
                  vel=[speed,10.],acc=[self.args.linear_acc,20.],time=0.,radius=0.,
                  ref=0,mode=0,blend_type=0,sync_type=0)


def execute(commands, robot, gripper, initial):
    for kind,label,target,block in commands:
        print(f'[{block if block else "HOME"}] {label}',flush=True)
        if kind == 'joint':
            robot.movej(target)
        elif kind == 'initial_approach':
            robot.movej(initial)
        elif kind == 'line_local':
            robot.line(target,robot.args.local_speed)
        elif kind == 'line_transit':
            robot.line(target,robot.args.transit_speed)
        elif kind == 'grip_close':
            gripper.move(robot.args.close_width,require_grip=True)
        elif kind == 'grip_open':
            gripper.move(robot.args.open_width)
        elif kind == 'clear_place':
            # Same drop target cannot be assumed empty after every release.
            if input('놓인 블록을 치우고 작업 영역에서 손을 뺀 뒤 Enter. 중단은 q: ').strip().lower() == 'q':
                raise KeyboardInterrupt
        else:
            raise ValueError(kind)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute',action='store_true')
    mode.add_argument('--check',action='store_true',help='통신과 경로 표본 IK 확인만 수행')
    parser.add_argument('--robot-id',default='dsr01')
    parser.add_argument('--tcp',default='GripperDA_v4')
    parser.add_argument('--tool',default='ToolWeight0')
    parser.add_argument('--gripper-ip',default='192.168.1.1')
    parser.add_argument('--transit-z',type=float,default=200.,help='Base 절대 Z, mm')
    parser.add_argument('--supply-staging-x',type=float,default=-450.,help='먼 블록은 30mm 상승 후 이 X까지 안쪽으로 접근하며 추가 상승')
    parser.add_argument('--bypass-y',type=float,default=400.,help='높은 경유점의 Base Y, mm')
    parser.add_argument('--obstacle-top-z',type=float,default=92.,help='장애물 최고 Base Z; 기본92는 바닥 Base Z=0 및 23mm 4층을 가정')
    parser.add_argument('--lift',type=float,default=30.)
    parser.add_argument('--joint-speed',type=float,default=20.)
    parser.add_argument('--joint-acc',type=float,default=20.)
    parser.add_argument('--local-speed',type=float,default=40.)
    parser.add_argument('--transit-speed',type=float,default=80.)
    parser.add_argument('--linear-acc',type=float,default=60.)
    parser.add_argument('--open-width',type=float,default=60.)
    parser.add_argument('--close-width',type=float,default=2.)
    parser.add_argument('--force',type=float,default=40.)
    parser.add_argument('--start-block',type=int,choices=range(1,7),default=1,
                        help='이미 옮긴 블록이 있으면 다음 번호로 시작')
    args = parser.parse_args()
    nums = [args.transit_z,args.bypass_y,args.lift,args.joint_speed,args.joint_acc,
            args.local_speed,args.transit_speed,args.linear_acc,args.open_width,args.close_width,args.force]
    if not math.isfinite(args.supply_staging_x) or not all(math.isfinite(v) for v in nums) or args.lift < 30 or not 0 <= args.close_width < args.open_width <=110 or not 0 < args.force <=40 or min(nums[3:8]) <= 0:
        parser.error('유효한 좌표·양수 속도·RG2 폭/힘을 지정하세요')
    if args.transit_z <= max(p[2]+args.lift for p in picks()+[PLACE]):
        parser.error('이송 Z는 모든 접근점보다 높아야 합니다')
    if args.obstacle_top_z is not None:
        if not math.isfinite(args.obstacle_top_z) or args.transit_z < args.obstacle_top_z + 73.:
            parser.error('이송 Z는 장애물 최고 Base Z +73 mm 이상으로 설정하세요 (블록23+초기여유50)')
    if args.execute and args.obstacle_top_z is None:
        parser.error('--obstacle-top-z로 장애물 최고점의 Base Z를 입력하세요; 높이 가정만으로 실행하지 않습니다')
    commands = plan(args)
    for kind,label,target,block in commands:
        print(f'[{block or "HOME"}] {label}' + (f': {[round(float(v),3) for v in target]}' if target else ''))
    print(f'이송 Base Z={args.transit_z}, 경유 Y={args.bypass_y}, 속도: 관절 {args.joint_speed}도/s, 접근 {args.local_speed}, 이송 {args.transit_speed}mm/s')
    if not (args.execute or args.check):
        print('계획만 출력했습니다. 중간 블록 좌표/자세 및 높은 경로는 실기 검증 전입니다.')
        return 0
    robot = gripper = None
    started = False
    try:
        robot = RowRobot(args)
        sol = robot.verify_setup()
        initial = robot.check_plan(commands,sol)
        gripper = Gripper(args)
        if args.check:
            print('조회 완료. 로봇/그리퍼 이동 명령은 보내지 않았습니다.')
            return 0
        robot.call('system/set_robot_mode','SetRobotMode',robot_mode=1)
        started = True
        execute(commands,robot,gripper,initial)
        print('노랑 4점 공급 라인 이송 완료')
        return 0
    except (Exception,KeyboardInterrupt) as exc:
        print(f'중단: {exc or "사용자 중단"}',flush=True)
        if started and robot is not None:
            robot.stop()
        return 1
    finally:
        if gripper is not None: gripper.close()
        if robot is not None: robot.close()


if __name__ == '__main__':
    raise SystemExit(main())
