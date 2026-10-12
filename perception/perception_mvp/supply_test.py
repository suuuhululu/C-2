"""Stored actual supply RGB/ROI diagnostic; no robot coordinates or progression."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import cv2
import numpy as np

from .opencv_live import color_mask, HSV_RANGES
from .rgbd_io import write_cycle_json
from .yolo_pipeline import infer_masks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roi', type=Path, required=True)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--confidence', type=float, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    settings = json.loads(args.roi.read_text())
    source = args.roi.parent / 'rgb.png'
    bgr = cv2.imread(str(source))
    if bgr is None:
        raise ValueError('Actual saved RGB required')
    if settings['purpose'] != 'SUPPLY_BOARD' or settings['image_size'] != [bgr.shape[1], bgr.shape[0]]:
        raise ValueError('Supply ROI and RGB resolution must match')
    polygon = np.asarray(settings['polygon_px'], dtype=np.int32)
    roi = np.zeros(bgr.shape[:2], np.uint8)
    cv2.fillPoly(roi, [polygon], 255)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    candidates = np.zeros_like(roi)
    for color in HSV_RANGES:
        candidates |= color_mask(hsv, color)
    candidates &= roi
    pixels = cv2.findNonZero(candidates)
    if pixels is None:
        raise ValueError('No HSV candidates in ROI; not an EMPTY verdict')
    x, y, w, h = cv2.boundingRect(pixels)
    # Preserve original RGB within the candidate bounding crop; do not erase reflections.
    x0, y0 = max(0, x-16), max(0, y-16)
    x1, y1 = min(bgr.shape[1], x+w+16), min(bgr.shape[0], y+h+16)
    rgb = cv2.cvtColor(bgr[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)
    detections = infer_masks(rgb, args.weights, args.confidence, device='cpu')
    preview = bgr.copy()
    entries = []
    for mask, name, confidence in detections:
        full = np.zeros_like(roi, dtype=bool)
        full[y0:y1, x0:x1] = mask
        if not np.any(full & (roi > 0)):
            continue
        ys, xs = np.nonzero(full)
        color = {'yellow': (0, 255, 255), 'blue': (255, 100, 0), 'red': (0, 0, 255)}[name.split('_')[0]]
        preview[full] = (preview[full]*.7 + np.asarray(color)*.3).astype(np.uint8)
        cv2.putText(preview, name, (int(xs.min()), int(ys.min())),
                    cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1)
        entries.append(dict(class_name=name, confidence=confidence,
                            crosses_roi=bool(np.any(full & (roi == 0)))))
    cv2.polylines(preview, [polygon], True, (0, 255, 0), 2)
    folder = args.output / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True, exist_ok=False)
    report = dict(source=str(source.resolve()), roi=str(args.roi.resolve()),
                  weights=str(args.weights.resolve()), confidence=args.confidence,
                  status='LOCAL_DIAGNOSTIC_NOT_GROUND_TRUTH',
                  counts=dict(Counter(entry['class_name'] for entry in entries)), detections=entries)
    write_cycle_json(folder / 'detections.json', report)
    if not cv2.imwrite(str(folder / 'preview.png'), preview):
        raise OSError('Preview save failed')
    print(json.dumps(dict(output=str(folder), counts=report['counts']), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
