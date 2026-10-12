"""Select supply-board pixel ROI from actual ROS RGB; no robot commands."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import time

import cv2
import numpy as np

from .rgbd_io import image_array, stamp, write_cycle_json
from .hand_cycle import validate_polygon


def save_roi(root, rgb, points, message, *, board='supply', view='V0'):
    polygon = validate_polygon(points)
    height, width = rgb.shape[:2]
    if (polygon < 0).any() or (polygon[:, 0] >= width).any() or (polygon[:, 1] >= height).any():
        raise ValueError('Corners must be inside RGB')
    if view not in ('V0', 'D1', 'D3'):
        raise ValueError('Unknown assembly View')
    folder = Path(root) / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True, exist_ok=False)
    if board not in ('supply', 'assembly'):
        raise ValueError('Unknown board')
    write_cycle_json(folder / (board + '_roi.json'), dict(
        purpose='SUPPLY_BOARD' if board == 'supply' else 'ASSEMBLY_BOARD', polygon_px=polygon.tolist(), image_size=[width, height],
        topic='/camera/color/image_raw', stamp_ns=stamp(message),
        frame_id=message.header.frame_id, view_id=view if board == 'assembly' else 'SUPPLY',
        status='PIXEL_ROI_ONLY_NOT_ROBOT_CALIBRATION'))
    if board == 'assembly' and view == 'V0':
        import yaml
        from .live_view import DEFAULT_INTEGRATED_WEIGHTS
        hand = yaml.safe_load(Path(__file__).with_name('config.yaml').read_text())['hand']
        hand.update(board_roi_v0=[int(polygon[:, 0].min()), int(polygon[:, 1].min()),
                                 int(polygon[:, 0].max())+1, int(polygon[:, 1].max())+1],
                    board_polygon_v0=polygon.tolist(), board_image_size=[width, height],
                    weights=str(DEFAULT_INTEGRATED_WEIGHTS.parent.parent /
                                'hand_yolo11n_added_20261012' / 'weights' / 'best.pt'))
        write_cycle_json(folder / 'hand_config.json', dict(hand=hand,
                         status='ROI_SELECTED_OTHER_SETTINGS_REQUIRED'))
    preview = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    cv2.polylines(preview, [polygon], True, (0, 255, 0), 2)
    for name, data in [('rgb.png', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)),
                       ('roi_preview.png', preview)]:
        if not cv2.imwrite(str(folder / name), data):
            raise OSError('Failed to save ' + name)
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--board', choices=('supply', 'assembly'), default='supply')
    parser.add_argument('--view', choices=('V0', 'D1', 'D3'), default='V0',
                        help='Assembly ROI context; hand settings are saved only for V0')
    args = parser.parse_args()
    import rclpy
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import Image
    rclpy.init()
    node = rclpy.create_node('supply_roi_setup')
    latest = []
    def receive(message):
        latest[:] = [image_array(message), message, time.monotonic()]
    subscription = node.create_subscription(Image, '/camera/color/image_raw', receive,
        QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE))
    window = args.board.title() + ' ROI | r freeze | click corners | u undo | ENTER save | q quit'
    frozen = None
    points = []
    def click(event, x, y, flags, parameter):
        if event == cv2.EVENT_LBUTTONDOWN and frozen is not None:
            points.append([x, y])
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(window, click)
    print('Robot must actually be stopped at ' + (args.view if args.board == 'assembly' else 'Supply') +
          '. r: freeze; click corners in order; Enter: save.')
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.01)
            packet = frozen if frozen is not None else latest
            canvas = (cv2.cvtColor(packet[0], cv2.COLOR_RGB2BGR) if packet else
                      np.zeros((480, 640, 3), dtype=np.uint8))
            if points:
                cv2.polylines(canvas, [np.asarray(points, dtype=np.int32)], len(points) >= 3, (0, 255, 0), 2)
            cv2.putText(canvas, 'FROZEN: click corners, Enter save' if frozen else 'LIVE: r freezes RGB',
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 255, 255), 2)
            cv2.imshow(window, canvas)
            key = cv2.waitKey(1) & 0xff
            if key == ord('q'):
                break
            if key == ord('r'):
                if latest and time.monotonic() - latest[2] < 1:
                    frozen = [latest[0].copy(), latest[1], latest[2]]
                    points.clear()
                else:
                    print('Fresh RGB required; check camera topic')
            elif key == ord('u') and points:
                points.pop()
            elif key in (10, 13) and frozen is not None:
                try:
                    folder = save_roi(args.output, frozen[0], points, frozen[1],
                                      board=args.board, view=args.view)
                except ValueError as error:
                    print(error)
                    continue
                print('Saved: ' + str(folder))
                break
    finally:
        node.destroy_node()
        rclpy.shutdown()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
