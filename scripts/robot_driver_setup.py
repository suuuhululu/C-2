"""기존 TCP/Tool을 선택한다. pose·도구 무게 생성·로봇 이동 명령은 없다."""
import argparse
import json
from pathlib import Path
import time


def apply_settings(call, connection):
    if call('system/get_robot_system', 'GetRobotSystem').robot_system != 0:
        raise RuntimeError('PHYSICAL_ROBOT_REQUIRED')
    if (call('system/get_robot_state', 'GetRobotState').robot_state != 1
            or call('motion/check_motion', 'CheckMotion').status != 0):
        raise RuntimeError('STOPPED_STANDBY_REQUIRED_FOR_TCP_TOOL_SETUP')
    original_mode = call('system/get_robot_mode', 'GetRobotMode').robot_mode
    if original_mode not in (0, 1):
        raise RuntimeError('UNKNOWN_ROBOT_MODE')
    changed_mode = False
    try:
        # The controller accepts TCP/Tool selection only in manual mode.
        for kind, typename in [('tool', 'Tool'), ('tcp', 'Tcp')]:
            expected = connection[kind]
            actual = call(f'{kind}/get_current_{kind}', f'GetCurrent{typename}').info
            if actual != expected:
                if original_mode == 1 and not changed_mode:
                    call('system/set_robot_mode', 'SetRobotMode', robot_mode=0)
                    changed_mode = True
                    if call('system/get_robot_mode', 'GetRobotMode').robot_mode != 0:
                        raise RuntimeError('MANUAL_MODE_UNCONFIRMED')
                call(f'{kind}/set_current_{kind}', f'SetCurrent{typename}', name=expected)
            actual = call(f'{kind}/get_current_{kind}', f'GetCurrent{typename}').info
            if actual != expected:
                raise RuntimeError(f'{kind.upper()}_SELECTION_UNCONFIRMED: expected={expected}, actual={actual}')
    finally:
        if changed_mode:
            call('system/set_robot_mode', 'SetRobotMode', robot_mode=original_mode)
            if call('system/get_robot_mode', 'GetRobotMode').robot_mode != original_mode:
                raise RuntimeError('ROBOT_MODE_RESTORE_UNCONFIRMED')
    return dict(tcp=connection['tcp'], tool=connection['tool'], motion_commands=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--wait-seconds', type=float, default=60)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config['mode'] != 'REAL':
        parser.error('explicit REAL config required')
    import rclpy
    from dsr_msgs2 import srv
    rclpy.init()
    node = rclpy.create_node('c2_roboton2_setup')
    prefix = '/' + config['connection']['robot_id'] + '/dsr_controller2/'
    deadline = time.monotonic() + args.wait_seconds

    def call(path, typename, **fields):
        client = node.create_client(getattr(srv, typename), prefix+path)
        try:
            if not client.wait_for_service(timeout_sec=max(0, deadline-time.monotonic())):
                raise TimeoutError('SERVICE_UNAVAILABLE: '+prefix+path)
            request = getattr(srv, typename).Request()
            for key, value in fields.items():
                setattr(request, key, value)
            future = client.call_async(request)
            rclpy.spin_until_future_complete(node, future, timeout_sec=5)
            if not future.done():
                raise TimeoutError('SERVICE_RESPONSE_TIMEOUT: '+path)
            response = future.result()
            if response is None or not response.success:
                raise RuntimeError('SERVICE_FAILED: '+path)
            return response
        finally:
            node.destroy_client(client)

    try:
        print('roboton2: 드라이버 준비 후 기존 TCP/Tool을 선택합니다.', flush=True)
        result = apply_settings(call, config['connection'])
        print(f"ROBOTON2_READY · TCP={result['tcp']} · Tool={result['tool']} · 이동 명령 0", flush=True)
    except Exception as error:
        print('ROBOTON2_SETUP_FAILED: '+str(error), flush=True)
        return 1
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
