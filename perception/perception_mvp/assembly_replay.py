"""Actual saved ROS RGB-D diagnostic replay, never a D inspection/ground truth."""
import argparse
from pathlib import Path
import json

import cv2
import numpy as np

from .integrated_view import LIVE_CLASSES, process_frame, draw_integrated
from .live_view import load_view_calibrations, load_layer_reference
from .yolo_pipeline import load_segmentation_model
from .rgbd_io import write_cycle_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording', type=Path, action='append', required=True)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--calibration-root', type=Path, required=True)
    parser.add_argument('--confidence', type=float, default=.25)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    calibrations = load_view_calibrations(args.calibration_root)
    reference = load_layer_reference()
    model = load_segmentation_model(args.weights, allowed_classes=LIVE_CLASSES)
    args.output.mkdir(parents=True, exist_ok=False)
    summaries = []
    for index, directory in enumerate(args.recording):
        row = dict(source=str(directory.resolve()), scope='ACTUAL_SAVED_RGBD_DIAGNOSTIC_NOT_D_RESULT')
        try:
            meta = json.loads((directory / 'metadata.json').read_text())
            rgb = np.load(directory / 'rgb.npy', allow_pickle=False)
            depth = np.load(directory / 'depth_aligned.npy', allow_pickle=False)
            view = meta['view_id']
            limits = reference['depth_ranges_m'][view]
            records = process_frame(rgb, model, args.confidence, depth, meta['camera_info']['aligned'],
                calibrations[view][1], reference['top_heights_mm'], reference['tolerance_mm'],
                height_reference_offset_mm=reference['height_reference_offset_mm'],
                depth_range_m=(limits['min_depth_m'], limits['max_depth_m']),
                max_height_spread_mm=reference['max_height_spread_mm'],
                block_stud_height_mm=reference['block_stud_height_mm'],
                top_plane_stud_mm=reference.get('top_plane_stud_mm', 0.))
            row.update(view=view, captured_at=meta['captured_at'],
                records=[{key: value for key, value in record.items() if key != 'mask'} for record in records])
            canvas = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            draw_integrated(canvas, records, show_height=True)
            if not cv2.imwrite(str(args.output / f'{index:02d}_{view}.png'), canvas):
                raise OSError('replay preview write failed')
        except Exception as error:
            row['error'] = f'{type(error).__name__}: {error}'
        summaries.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    write_cycle_json(args.output / 'report.json', dict(scope='DIAGNOSTIC_REPLAY_NOT_VALIDATION',
        weights=str(args.weights.resolve()), confidence=args.confidence,
        layer_settings=reference, frames=summaries,
        limitations=['historical robot pose not supplied', 'no ground-truth scoring',
                     'no verified_regions or D result', 'calibration pose repeatability not verified']))
    if any('error' in row for row in summaries):
        raise RuntimeError('one or more saved-frame replays failed; see report.json')


if __name__ == '__main__':
    main()
