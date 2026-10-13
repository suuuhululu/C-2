"""Evaluate saved original RGB with top-face segmentation; TEST replay, no ROS or Robot execution."""
import argparse
import json
from pathlib import Path

import cv2

from .main import load_model, process, resolve_weights, validate_config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--request', required=True)
    parser.add_argument('--weights', help='override config "weights"')
    parser.add_argument('--frame-stamp-ns', required=True, type=int)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    if output.exists():
        parser.error('output already exists')
    config = json.loads(Path(args.config).read_text())
    request = json.loads(Path(args.request).read_text())
    if request.get('mode') != 'TEST':
        parser.error('saved image replay requires explicit mode=TEST')
    validate_config(config, request)
    frame = cv2.imread(args.image)
    if frame is None:
        raise ValueError('cannot read saved RGB')
    model = load_model(resolve_weights(config, args.config, args.weights))
    result = process(frame, model, config, request, args.frame_stamp_ns)
    result.update(mode='TEST', source='SAVED_RGB_REPLAY', image=str(Path(args.image).resolve()))
    with output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(result['status'], output)


if __name__ == '__main__':
    main()
