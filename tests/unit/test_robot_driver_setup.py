from types import SimpleNamespace
import pytest
from scripts.robot_driver_setup import apply_settings


def fake_calls(current=None, moving=False, failed=False):
    selected = dict(tcp='', tool='') if current is None else dict(current)
    mode = [1]
    calls = []
    def call(path, typename, **fields):
        calls.append((path, fields))
        if path == 'system/get_robot_system': return SimpleNamespace(robot_system=0)
        if path == 'system/get_robot_state': return SimpleNamespace(robot_state=1)
        if path == 'system/get_robot_mode': return SimpleNamespace(robot_mode=mode[0])
        if path == 'system/set_robot_mode':
            mode[0] = fields['robot_mode']
            return SimpleNamespace(success=True)
        if path == 'motion/check_motion': return SimpleNamespace(status=2 if moving else 0)
        kind = path.split('/')[0]
        if '/set_' in path:
            if failed: raise RuntimeError('SERVICE_FAILED: '+path)
            selected[kind] = fields['name']
            return SimpleNamespace(success=True)
        return SimpleNamespace(info=selected[kind])
    return call, calls


CONNECTION = dict(tcp='GripperDA_v4', tool='ToolWeight0')


def test_selects_existing_names_and_verifies_without_motion():
    call, calls = fake_calls()
    assert apply_settings(call, CONNECTION) == dict(CONNECTION, motion_commands=0)
    assert [(p, data) for p,data in calls if '/set_' in p] == [
        ('system/set_robot_mode',dict(robot_mode=0)),
        ('tool/set_current_tool',dict(name='ToolWeight0')),
        ('tcp/set_current_tcp',dict(name='GripperDA_v4')),
        ('system/set_robot_mode',dict(robot_mode=1))]
    assert all('move' not in p and 'create' not in p for p,_ in calls)


def test_already_selected_settings_are_only_read():
    call,calls = fake_calls(CONNECTION)
    apply_settings(call,CONNECTION)
    assert not any('/set_' in p for p,_ in calls)


def test_moving_robot_never_changes_tool_or_tcp():
    call,calls = fake_calls(moving=True)
    with pytest.raises(RuntimeError,match='STOPPED_STANDBY'):
        apply_settings(call,CONNECTION)
    assert not any('/set_' in p for p,_ in calls)


def test_unregistered_setting_failure_does_not_create_or_replace_values():
    call,calls = fake_calls(failed=True)
    with pytest.raises(RuntimeError,match='SERVICE_FAILED'):
        apply_settings(call,CONNECTION)
    assert not any('create' in p or 'set_current_tcp' in p for p,_ in calls)
    assert ('system/set_robot_mode',dict(robot_mode=1)) in calls
