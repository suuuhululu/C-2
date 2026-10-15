"""One real observation cycle over a local JSON channel; B sends no robot command."""
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys


def run(request, incoming, outgoing):
    from .hand_cycle import HandCycle, HandDetector
    from .main import make_inspection_observer, read_json
    from .ros_capture import capture_inspection_view
    from .runtime_log import progress_sink

    sequence = 0
    identity = request['context']['check_id']

    def hook(name, *args):
        nonlocal sequence
        sequence += 1
        outgoing.write(json.dumps(dict(kind='HOOK', check_id=identity, sequence=sequence,
                                       name=name, args=args))+'\n')
        outgoing.flush()
        reply = json.loads(incoming.readline())
        if (reply.get('check_id'), reply.get('sequence')) != (identity, sequence):
            raise ValueError('INSPECTION_HOOK_BINDING_MISMATCH')
        if reply.get('error'):
            raise RuntimeError(reply['error'])
        return reply['value']

    with redirect_stdout(sys.stderr):
        settings = read_json(request['settings'])
        config = settings['geometry']
        calibration = read_json(request['calibration'])
        if config['calibration_id'] != calibration['calibration_id']:
            raise ValueError('INSPECTION_CALIBRATION_MISMATCH')
        hand = settings['hand']
        gate = HandCycle(hand['stable_seconds'], hand['max_frame_gap_seconds'])
        detector = HandDetector(hand['weights'], hand['confidence'], hand['board_roi_v0'],
            min_valid_depth_fraction=hand['min_valid_depth_fraction'],
            stable_mean_difference=hand['stable_mean_difference'],
            image_size=hand['board_image_size'], board_polygon=hand.get('board_polygon_v0'))
        valid = lambda: hook('valid') is True
        stopped = lambda view: hook('is_stopped', view) is True

        def capture(manifest, view, active):
            return capture_inspection_view(manifest, view, active,
                output_root=Path(request['output'])/'captures', scene_id=request['scene_id'],
                calibration_id=config['calibration_id'],
                robot_pose=lambda v: hook('robot_pose', v), is_stopped=stopped,
                **request.get('capture_settings',{}))

        # Existing process_saved computes measured occupied/empty regions from Depth.
        # No full-board regions are supplied by the controller or from the target.
        observer = make_inspection_observer(gate, detector, None, capture,
            request['weights'], calibration, config, config['min_confidence'],
            confirm_view=lambda view: hook('confirm_view', view), workflow_valid=valid,
            bundle_valid=valid, is_stopped=stopped, output_root=Path(request['output'])/'cycles')
        def report(message, view, details):
            outgoing.write(json.dumps(dict(kind='PROGRESS',check_id=identity,
                message=message,view=view,details=details),ensure_ascii=False)+'\n')
            outgoing.flush()
        with progress_sink(report):
            observed, diagnostics = observer(request['context'], valid)
    return dict(kind='RESULT', check_id=identity, observed=observed, diagnostics=diagnostics)


def main():
    output = sys.stdout
    request = json.loads(sys.stdin.readline())
    try:
        result = run(request, sys.stdin, output)
    except Exception as error:
        result = dict(kind='ERROR', check_id=request['context']['check_id'], reason=str(error))
    output.write(json.dumps(result, ensure_ascii=False, allow_nan=False)+'\n')
    output.flush()
    return 0 if result['kind'] == 'RESULT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
