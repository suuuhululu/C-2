"""Real wiring tests with injected capture, not physical ROS validation."""
import pytest
from perception_mvp.team_connection import connect_real_inspection


def test_real_binding_preserves_controller_and_capture_contract(tmp_path, monkeypatch):
    import perception_mvp.main as runtime
    import perception_mvp.ros_capture as ros
    import perception_mvp.team_connection as connection
    weights = tmp_path / 'model.pt'
    weights.write_bytes(b'test-only')
    state = [True]
    hooks = dict(confirm_view=lambda view: True, is_stopped=lambda view: True,
                 robot_pose=lambda view: {'view': view}, workflow_valid=lambda: state[0],
                 bundle_valid=lambda: True)
    def capture(manifest, view, active, **kwargs):
        assert manifest['check_id'] == 'actual-check' and view == 'D1'
        assert kwargs['robot_pose']('D1') == {'view': 'D1'}
        assert kwargs['calibration_id'] == 'cal'
        assert kwargs['output_root'] == tmp_path / 'captures'
        assert kwargs['workflow_valid'] is hooks['workflow_valid']
        assert kwargs['bundle_valid'] is hooks['bundle_valid']
        assert active()
        state[0] = False
        assert active() and kwargs['workflow_valid']() is False
        return {'directory': 'real-record'}
    def make(*args, **kwargs):
        assert args[2] is None  # ROS hand stream, not a synthetic iterator
        assert kwargs['is_stopped'] is hooks['is_stopped']
        assert args[3]({'check_id': 'actual-check'}, 'D1', lambda: True)['directory'] == 'real-record'
        return 'bound-observer'
    monkeypatch.setattr(ros, 'capture_inspection_view', capture)
    monkeypatch.setattr(runtime, 'make_inspection_observer', make)
    monkeypatch.setattr(connection, 'connect_inspection', lambda sink, **kw: kw)
    args = dict(gate=object(), hand_detector=object(), weights=weights,
                calibration={'calibration_id': 'cal', 'views': dict(V0={}, D1={}, D3={})},
                config={'calibration_id': 'cal'}, detector_confidence=.25,
                scene_id='real-board', output_root=tmp_path, **hooks)
    bound = connect_real_inspection(lambda result: None, **args)
    assert bound['observe'] == 'bound-observer' and bound['geometry_reference'] == 'cal'
    args['config'] = {'calibration_id': 'wrong'}
    with pytest.raises(ValueError, match='IDs'):
        connect_real_inspection(lambda result: None, **args)
    args['weights'] = tmp_path / 'missing.pt'
    with pytest.raises(ValueError, match='weights'):
        connect_real_inspection(lambda result: None, **args)
