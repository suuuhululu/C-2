"""ROS live RGB-D diagnostic viewer; no Robot or Backend progression permission."""
import argparse
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from threading import Lock, Thread

import cv2
import numpy as np

from .rgbd_io import image_array, info_dict, save_capture, stamp
from .yolo_pipeline import load_segmentation_model

DEFAULT_INTEGRATED_WEIGHTS = (Path(__file__).resolve().parent.parent / 'models' /
                              'block_v1_six_runs_20261010' / 'blocks_yolo26s_best.pt')


def put_label(img, text, org, fontFace=cv2.FONT_HERSHEY_SIMPLEX, fontScale=.5,
              color=(255, 255, 255), thickness=1, lineType=cv2.LINE_AA):
    """Display-only text on a translucent dark box: readable on wood, board and blocks.
    Same positional signature as cv2.putText; draws in place and never changes image size."""
    (w, h), base = cv2.getTextSize(text, fontFace, fontScale, thickness)
    x, y = int(org[0]), int(org[1])
    x1, y1 = max(x - 4, 0), max(y - h - 4, 0)
    x2, y2 = min(x + w + 4, img.shape[1]), min(y + base + 4, img.shape[0])
    if x2 > x1 and y2 > y1:
        roi = img[y1:y2, x1:x2]
        roi[:] = (roi * .25 + np.array((24, 20, 16)) * .75).astype(np.uint8)
    cv2.putText(img, text, (x, y), fontFace, fontScale, color, thickness, lineType)


# ---------------------------------------------------------------------------
# Live-view HUD (display only). Draws on the display canvas, never on detection input.
# Rollback switches: HUD_LEGACY_BLOCK_LABELS=True restores draw_integrated's long per-block
# labels; pressing h cycles FULL -> COMPACT -> OFF while running.
# ---------------------------------------------------------------------------
HUD_FULL, HUD_COMPACT, HUD_OFF = 0, 1, 2
HUD_LEGACY_BLOCK_LABELS = False
HUD_SHOW_GRID_LAYER_H = False  # True: show GRID / LAYER / H(mm) columns in the HUD table
_HUD_FONT = cv2.FONT_HERSHEY_SIMPLEX
_HUD_PANEL = (58, 50, 44)
_HUD_WHITE, _HUD_GREY = (255, 255, 255), (205, 198, 190)
_HUD_GREEN, _HUD_AMBER, _HUD_RED, _HUD_CYAN = (132, 220, 61), (0, 179, 255), (82, 82, 255), (255, 229, 0)
_HUD_EDGE = (96, 88, 80)
_HUD_BADGE = {'yellow': ((0, 200, 255), (0, 0, 0)), 'red': ((40, 70, 230), (255, 255, 255)),
              'blue': ((230, 150, 40), (255, 255, 255))}
_HUD_STAGE = ('FROZEN', 'RECEIVING', 'RX OFF', 'MOVING', 'WAITING RGB', 'WAIT', 'STALE RGB')
_HUD_REASON = {'height_outside_layer_reference': 'RANGE', 'layer_reference_missing': 'NOREF',
               'color_missing_or_conflict': 'COLOR', 'instance_crosses_roi_boundary': 'ROI',
               'insufficient_depth': 'DEPTH', 'surface_height_conflict': 'SURF',
               'partial_or_invalid_footprint': 'FOOT', 'orientation_off_grid': 'ANGLE'}


def default_hud_mode(view):
    return HUD_FULL if view == 'V0' else HUD_COMPACT


def new_hud():
    return dict(lines=[], records=None, show_height=False)


def hud_add(hud, img, text, org, fontFace=0, fontScale=.5, color=(255, 255, 255), thickness=1,
            lineType=cv2.LINE_AA):
    """Collect one text line for render_hud. Same positional signature as put_label."""
    hud['lines'].append(dict(text=str(text), org=(int(org[0]), int(org[1])), scale=float(fontScale),
                             color=tuple(int(c) for c in color), th=int(thickness), h=int(img.shape[0])))


def _hud_tw(text, scale, th=1):
    return cv2.getTextSize(text, _HUD_FONT, scale, th)[0][0]


def _hud_box(img, x1, y1, x2, y2, alpha, color=_HUD_PANEL):
    x1, y1 = max(int(x1), 0), max(int(y1), 0)
    x2, y2 = min(int(x2), img.shape[1]), min(int(y2), img.shape[0])
    if x2 > x1 and y2 > y1:
        roi = img[y1:y2, x1:x2]
        roi[:] = (roi * (1 - alpha) + np.array(color) * alpha).astype(np.uint8)


def _hud_text(img, s, x, y, scale=.46, color=_HUD_WHITE, th=1):
    cv2.putText(img, s, (int(x), int(y)), _HUD_FONT, scale, color, th, cv2.LINE_AA)
    return int(x) + _hud_tw(s, scale, th)


def _hud_chip(img, s, x, y, color, scale=.42, filled=False):
    x2, y2 = x + _hud_tw(s, scale, 2) + 12, y + 22
    _hud_box(img, x, y, x2, y2, .72)
    if filled:
        _hud_box(img, x, y, x2, y2, .2, color)
    cv2.rectangle(img, (x, y), (x2, y2), color, 1, cv2.LINE_AA)
    cv2.putText(img, s, (x + 6, y + 15), _HUD_FONT, scale, color, 2, cv2.LINE_AA)
    return x2 + 4


def _hud_chip_row(img, chips, x, y, max_x):
    """Chips left to right, wrapping at max_x. Returns the y for whatever comes next."""
    cx = x
    for s, color, filled in chips:
        if cx + _hud_tw(s, .42, 2) + 16 > max_x and cx > x:
            cx, y = x, y + 26
        cx = _hud_chip(img, s, cx, y, color, filled=filled)
    return y + 26


def _hud_badge(img, no, cx, cy, fill, fg, r=8):
    label = str(no)
    if len(label) > 1:
        r += 3
    cv2.circle(img, (cx, cy), r + 1, (0, 0, 0), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r, fill, -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r, _HUD_WHITE, 1, cv2.LINE_AA)
    cv2.putText(img, label, (cx - _hud_tw(label, .42) // 2, cy + 4), _HUD_FONT, .42, fg, 1, cv2.LINE_AA)


def _hud_wrap(text, scale, width, th=1):
    lines, cur = [], ''
    for word in text.split(' '):
        trial = cur + ' ' + word if cur else word
        if cur and _hud_tw(trial, scale, th) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    lines.append(cur)
    out = []
    for line in lines:  # an over-long token (e.g. a reason code) is hard-split
        while len(line) > 1 and _hud_tw(line, scale, th) > width:
            k = len(line)
            while k > 1 and _hud_tw(line[:k], scale, th) > width:
                k -= 1
            out.append(line[:k])
            line = line[k:]
        out.append(line)
    return out


def _hud_color(color):
    if color[2] >= 200 and color[0] <= 80 and color[1] <= 80:
        return _HUD_RED
    if color[1] >= 200 and color[0] <= 120 and color[2] <= 120:
        return _HUD_GREEN
    if tuple(color) == (0, 180, 255):
        return _HUD_AMBER
    return _HUD_WHITE


def _hud_reason_abbr(reason):
    if reason is None:
        return ''
    reason = str(reason)
    if reason in _HUD_REASON:
        return _HUD_REASON[reason]
    if reason.startswith('board_baseline'):
        return 'BASE'
    return reason.split(',')[0].strip().upper().replace('_', ' ')[:6]


def _hud_block_order(records):
    """Stable numbering: top-to-bottom in 60px bands, left-to-right inside a band."""
    items = []
    for record in records:
        ys, xs = np.nonzero(record['mask'])
        if xs.size:
            items.append((record, (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))))
    items.sort(key=lambda item: (item[1][1] // 60, item[1][0]))
    return [(i + 1, record, box) for i, (record, box) in enumerate(items)]


def draw_block_badges(canvas, records):
    """Same tint/outline as draw_integrated; the long per-block label becomes a number badge."""
    ordered = _hud_block_order(records)
    for _, record, _ in ordered:
        mask = record['mask']
        tint = np.array((80, 220, 80) if record['reason'] is None else (0, 180, 255))
        canvas[mask] = (.7 * canvas[mask] + .3 * tint).astype(np.uint8)
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, contours, -1, tuple(map(int, tint)), 1)
    height, width = canvas.shape[:2]
    for no, record, (x0, y0, x1, y1) in ordered:
        fill, fg = _HUD_BADGE.get(str(record.get('color', '')).lower(), ((160, 160, 160), (0, 0, 0)))
        cx = max(14, min((x0 + x1) // 2, width - 14))
        cy = y0 - 12
        if cy < 14:
            cy = min(y1 + 12, height - 14)
        _hud_badge(canvas, no, cx, cy, fill, fg)
    return canvas


def _hud_cells(record, show_height):
    part = str(record.get('part_class', ''))
    size = part.split('_', 1)[1] if '_' in part else '-'
    color = str(record.get('color', '')).lower()
    if record.get('reason') == 'color_missing_or_conflict':
        color = 'color?'
    elif color in ('', 'unknown'):
        color = 'unknown'
    grid = record.get('grid')
    layer = record.get('layer')
    height = record.get('height_mm')
    stud = record.get('stud_layer')
    return dict(color=color, size=size,
                grid='(%d,%d)' % (grid[0], grid[1]) if grid is not None else '-',
                layer='L%d' % layer if layer is not None else '-',
                why='' if layer is not None else _hud_reason_abbr(record.get('reason')),
                height='%.1f' % height if show_height and height is not None else '-',
                stud=None if stud is None else ('s%d' % stud['layer'] if stud.get('layer') is not None else 's-'))


def _hud_parse(lines):
    height = lines[0]['h'] if lines else 0
    top, bottom = [], []
    for item in lines:
        (bottom if height >= 400 and height - item['org'][1] <= 70 else top).append(item)
    row1, row2, reasons, notes = [], [], [], []

    def add(row, chip):
        if chip[0] not in [c[0] for c in row]:
            row.append(chip)

    for item in top:
        text, color = item['text'], item['color']
        if text.startswith('RESULT FROZEN'):
            add(row1, ('FROZEN', _HUD_GREEN, True))
            notes.append(('r: new observation', _HUD_GREY))
        elif text.startswith('RECEIVING ON'):
            add(row1, ('RECEIVING', _HUD_CYAN, False))
        elif text.startswith('RECEIVING OFF'):
            add(row1, ('RX OFF', _HUD_WHITE, False))
        elif text.startswith('HSV -> YOLO'):
            add(row1, ('LOCAL ONLY', _HUD_AMBER, False))
        elif text.startswith('GEOMETRY:'):
            reasons.extend(r.strip() for r in text[len('GEOMETRY:'):].split(',') if r.strip())
        elif text.startswith('MEASUREMENT DISPLAY ONLY'):
            add(row2, ('MEASURE ONLY', _HUD_AMBER, False))
            notes.append(('NO CYCLE / ROBOT PERMISSION', _HUD_AMBER))
        elif text.startswith('STALE RGB'):
            add(row1, ('STALE RGB', _HUD_RED, True))
        elif text.startswith('MOVING / UNCONFIRMED'):
            add(row1, ('MOVING', _HUD_AMBER, True))
            notes.append(('receiving / inference OFF', _HUD_GREY))
        elif text.startswith('Waiting for ROS RGB'):
            add(row1, ('WAITING RGB', _HUD_AMBER, True))
        elif text.startswith('WAIT:'):
            add(row1, ('WAIT', _HUD_AMBER, True))
            notes.append((text[5:].strip(), _HUD_AMBER))
        elif ' | c: capture' in text:
            parts = [p.strip() for p in text.split(' | ')]
            add(row1, (parts[0].split(' ')[0], _HUD_CYAN, False))
            if 'LOCAL ONLY' in parts[0]:
                add(row1, ('LOCAL ONLY', _HUD_AMBER, False))
            notes.append((' | '.join(parts[1:]), _HUD_GREY))
        elif text.startswith('SYNC dt:'):
            notes.append((text, _HUD_GREY))
        else:
            notes.append((text, _hud_color(color)))
    row1.sort(key=lambda c: _HUD_STAGE.index(c[0]) if c[0] in _HUD_STAGE else len(_HUD_STAGE))
    if reasons:
        row2.insert(0, ('WARN x%d' % len(reasons), _HUD_AMBER, False))
    return dict(row1=row1, row2=row2, reasons=reasons, notes=notes), bottom


def _hud_layout_top(img, parsed, records, show_height, right):
    """Draws the FULL top-left content onto img and returns the y where it ends."""
    y = 14
    y = _hud_chip_row(img, parsed['row1'], 14, y, right - 4)
    if records:
        ordered = _hud_block_order(records)
        studs = any(r.get('stud_layer') is not None for _, r, _ in ordered)
        full = HUD_SHOW_GRID_LAYER_H
        cols = [('#', 16), ('COLOR', 36), ('SIZE', 96)]
        if full:
            cols += [('GRID', 134), ('LAYER', 198)]
        if studs:
            cols.append(('sL', 250 if full else 134))
        if full:
            cols.append(('H(mm)', 286 if studs else 250))
        y += 6
        for title, cx in cols:
            _hud_text(img, title, cx, y + 8, .36, _HUD_GREY)
        y += 30
        for no, record, _ in ordered:
            cells = _hud_cells(record, show_height)
            fill, fg = _HUD_BADGE.get(cells['color'], ((160, 160, 160), (0, 0, 0)))
            _hud_badge(img, no, 22, y - 4, fill, fg, r=7)
            _hud_text(img, cells['color'], 36, y)
            _hud_text(img, cells['size'], 96, y, color=_HUD_GREY if cells['size'] == '-' else _HUD_WHITE)
            if full:
                _hud_text(img, cells['grid'], 134, y, color=_HUD_GREY if cells['grid'] == '-' else _HUD_WHITE)
                end = _hud_text(img, cells['layer'], 198, y,
                                color=_HUD_GREEN if cells['layer'] != '-' else _HUD_GREY)
                if cells['why']:
                    _hud_text(img, cells['why'], end + 4, y, .32, _HUD_AMBER)
            if studs:
                _hud_text(img, cells['stud'] or '-', 250 if full else 134, y, color=_HUD_CYAN)
            if full:
                _hud_text(img, cells['height'], 286 if studs else 250, y,
                          color=_HUD_GREY if cells['height'] == '-' else _HUD_WHITE)
            y += 22
        y -= 4
    if parsed['row2']:
        y = _hud_chip_row(img, parsed['row2'], 14, y + 4, right - 4)
    for reason in parsed['reasons']:
        y += 2
        for piece in _hud_wrap(reason, .34, right - 30):
            _hud_text(img, piece, 24, y + 8, .34, _HUD_AMBER)
            y += 14
    for text, color in parsed['notes']:
        y += 2
        for piece in _hud_wrap(text, .36, right - 20):
            _hud_text(img, piece, 16, y + 10, .36, color)
            y += 15
    return y + 6


def _hud_draw_bottom(img, items):
    """Hand/view status as chips stacked up from the bottom-left (clear of the origin marker)."""
    height, max_x = img.shape[0], 392
    hand, view_row, step, reason_note, other = [], [], None, '', []
    view_keys = ''
    for item in items:
        text = item['text']
        if text.startswith('HAND '):
            parts = [p.strip() for p in text.split(' | ')]
            head = parts[0]
            hand.append((head, _HUD_GREEN if head.endswith('ABSENT') else
                         _HUD_RED if head.endswith('PRESENT') else _HUD_AMBER, False))
            for part in parts[1:]:
                if part.startswith('exit'):
                    try:
                        seconds = float(part.split()[1].rstrip('s'))
                    except (IndexError, ValueError):
                        seconds = 0.
                    hand.append(('exit %.2fs' % seconds, _HUD_GREEN if seconds > 3 else _HUD_AMBER, False))
                elif part.startswith('stable'):
                    ok = part.endswith('True')
                    hand.append(('stable' if ok else 'unstable', _HUD_GREEN if ok else _HUD_AMBER, False))
                else:
                    hand.append((part, _HUD_GREEN if part == 'READY' else _HUD_AMBER, False))
        elif ' | NOT STEP COMPLETE' in text:
            reason_note = text.split(' | NOT STEP COMPLETE')[0]
            step = ('NOT STEP COMPLETE', _HUD_AMBER, True)
        elif ' | m:move' in text:
            head, view_keys = text.split(' | ', 1)
            view = head.split(' ')[0]
            view_row.append((view + ' STOPPED', _HUD_GREEN, False) if 'STOPPED' in head
                            else (view + ' MOVING', _HUD_AMBER, True))
        else:
            other.append((text, _hud_color(item['color'])))
    y = height - 8
    if reason_note:
        for piece in reversed(_hud_wrap(reason_note, .36, max_x - 8)):
            put_label(img, piece, (8, y - 2), 0, .36, _HUD_GREY, 1)
            y -= 16
        y -= 2
    if step:
        y -= 24
        _hud_chip_row(img, [step], 8, y, max_x)
        y -= 4
    if hand:
        rows = int((_hud_chip_row(np.zeros((1, 1, 3), np.uint8), hand, 8, 0, max_x)) // 26)
        y -= 26 * rows
        _hud_chip_row(img, hand, 8, y, max_x)
    if view_row:
        y -= 26
        x = _hud_chip_row(img, view_row, 8, y, max_x)
        end = 8 + sum(_hud_tw(c[0], .42, 2) + 16 for c in view_row)
        put_label(img, view_keys, (end + 4, y + 16), 0, .36, _HUD_GREY, 1)
    for text, color in other:
        y -= 18
        put_label(img, text, (8, y), 0, .4, color, 1)


def render_hud(canvas, hud, mode=HUD_FULL):
    """Lay the collected lines out as compact panels/chips. Display canvas only."""
    lines = hud['lines']
    height, width = canvas.shape[:2]
    if height < 400:  # small status screens: keep each line where the code put it
        for item in lines:
            put_label(canvas, item['text'], item['org'], 0, item['scale'], item['color'], item['th'])
        return canvas
    if mode == HUD_OFF:
        return canvas
    parsed, bottom = _hud_parse(lines)
    records, show_height = hud['records'], hud['show_height']
    if parsed['row1'] or parsed['row2'] or parsed['notes'] or records:
        if mode == HUD_FULL:
            studs = bool(records) and any(r.get('stud_layer') is not None for r in records)
            right = 8 + ((336 if studs else 296) if HUD_SHOW_GRID_LAYER_H else 256)
            scratch = np.zeros((1, 1, 3), np.uint8)
            end = _hud_layout_top(scratch, parsed, records, show_height, right)
            _hud_box(canvas, 8, 8, right, end, .58)
            cv2.rectangle(canvas, (8, 8), (right, end), _HUD_EDGE, 1)
            _hud_layout_top(canvas, parsed, records, show_height, right)
        else:  # COMPACT: chips only
            chips = parsed['row1'] + parsed['row2']
            if records:
                chips.append(('BLOCKS %d' % len(records), _HUD_WHITE, False))
                for no, record, _ in (_hud_block_order(records) if HUD_SHOW_GRID_LAYER_H else []):
                    layer = record.get('layer')
                    chips.append(('%d:%s' % (no, 'L%d' % layer if layer is not None else '-'),
                                  _HUD_GREEN if layer is not None else _HUD_GREY, False))
            y = _hud_chip_row(canvas, chips, 8, 8, 460)
            for text, color in parsed['notes']:
                if color == _HUD_RED:
                    for piece in _hud_wrap(text, .4, 440):
                        put_label(canvas, piece, (10, y + 10), 0, .4, color, 1)
                        y += 16
    _hud_draw_bottom(canvas, bottom)
    return canvas


def resolve_live_weights(weights, integrated):
    # Keep RGB-only and legacy four-class diagnostics independent of this model.
    return DEFAULT_INTEGRATED_WEIGHTS if integrated and weights is None else weights


def load_view_rois(root):
    from .hand_cycle import validate_polygon
    result = {}
    for view in ('V0', 'D1', 'D3'):
        paths = sorted((Path(root) / view).glob('*/assembly_roi.json'))
        if not paths:
            raise ValueError('Missing assembly ROI for ' + view)
        path = paths[-1]
        data = json.loads(path.read_text())
        if data.get('purpose') != 'ASSEMBLY_BOARD' or data.get('view_id', 'V0') != view:
            raise ValueError('Assembly ROI View mismatch: ' + str(path))
        polygon = validate_polygon(data['polygon_px'])
        width, height = data['image_size']
        if type(width) is not int or type(height) is not int or min(width, height) <= 0:
            raise ValueError('Invalid ROI image size')
        if (polygon < 0).any() or (polygon[:, 0] >= width).any() or (polygon[:, 1] >= height).any():
            raise ValueError('ROI outside image')
        mask = np.zeros((height, width), np.uint8)
        cv2.fillPoly(mask, [polygon], 1)
        result[view] = (mask.astype(bool), polygon)
        print('ROI ' + view + ': ' + str(path))
    return result


def save_hand_roi(directory, rgb, rectangle, rgb_message):
    """Pixel ROI setup only. Unknown hand-quality thresholds stay unconfigured."""
    x, y, width, height = (int(v) for v in rectangle)
    if width <= 0 or height <= 0:
        return None
    if x < 0 or y < 0 or x + width > rgb.shape[1] or y + height > rgb.shape[0]:
        raise ValueError('ROI must fit the actual RGB image')
    from .rgbd_io import write_cycle_json
    import yaml
    settings = yaml.safe_load(Path(__file__).with_name('config.yaml').read_text())
    hand = settings['hand']
    # A newly selected ROI is not validated by another ROI's saved trial profile.
    hand.pop('board_polygon_v0', None)
    for key in ('confidence', 'min_valid_depth_fraction', 'stable_mean_difference',
                'stable_seconds', 'max_frame_gap_seconds'):
        hand[key] = None
    hand['board_roi_v0'] = [x, y, x + width, y + height]
    hand['board_image_size'] = [rgb.shape[1], rgb.shape[0]]
    hand['weights'] = str(DEFAULT_INTEGRATED_WEIGHTS.parent.parent /
                          'hand_yolo11n_added_20261012' / 'weights' / 'best.pt')
    directory = Path(directory) / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True, exist_ok=False)
    write_cycle_json(directory / 'hand_config.json', dict(hand=hand, roi_capture=dict(
        view_id='V0', topic='/camera/color/image_raw', stamp_ns=stamp(rgb_message),
        frame_id=rgb_message.header.frame_id, status='ROI_SELECTED_OTHER_SETTINGS_REQUIRED')))
    preview = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    cv2.rectangle(preview, (x, y), (x + width - 1, y + height - 1), (0, 255, 0), 2)
    if not cv2.imwrite(str(directory / 'roi_preview.png'), preview):
        raise OSError('failed to save ROI preview')
    return directory / 'hand_config.json'


class ViewSelection:
    """Shared view/stop input boundary; no Robot command or safety authorization."""
    def __init__(self, view, calibrations, *, stopped=False):
        self.calibrations = calibrations
        self.view = view
        self.stopped = stopped
        self.generation = 0
        if view not in calibrations:
            raise ValueError('unknown observation View')

    def update(self, view, *, stopped):
        # A future Controller adapter calls this same boundary with verified inputs.
        if view not in self.calibrations or type(stopped) is not bool:
            raise ValueError('known View and explicit stop state required')
        if view != self.view and self.stopped and stopped:
            raise ValueError('mark moving before changing observation View')
        changed = (view, stopped) != (self.view, self.stopped)
        self.view, self.stopped = view, stopped
        if changed:
            self.generation += 1
        return changed


def load_layer_reference(path=None):
    """Explicit JSON overrides defaults; config trial datum is flat-board zero."""
    if path is not None:
        return json.loads(Path(path).read_text())
    import yaml
    from .depth_grid import params_from_geometry
    config = yaml.safe_load(Path(__file__).with_name('config.yaml').read_text())['geometry']
    levels = config.get('top_heights_m')
    if levels is None:
        return {}
    return dict(top_heights_mm=[value * 1000. for value in levels],
                tolerance_mm=config['height_tolerance_m'] * 1000.,
                first_layer_min_mm=(config['first_layer_min_height_m'] * 1000.
                    if config.get('first_layer_min_height_m') is not None else None),
                first_layer_max_mm=(config['first_layer_max_height_m'] * 1000.
                    if config.get('first_layer_max_height_m') is not None else None),
                layer_upper_bounds_mm=([value * 1000. for value in config['layer_upper_bounds_m']]
                    if config.get('layer_upper_bounds_m') is not None else None),
                board_baseline_params=params_from_geometry(config, 1000.),
                board_bounds_mm=(np.asarray(config['board_bounds_m'], float) * 1000.).tolist(),
                height_reference_offset_mm=config['board_stud_height_m'] * 1000.,
                status=config['layer_reference_status'], depth_ranges_m=config.get('depth_ranges_m'),
                max_height_spread_mm=config['max_height_spread_m'] * 1000.,
                block_stud_height_mm=(config['block_stud_height_m'] * 1000.
                    if config['block_surface_height_basis'] == 'BODY_TOP_PLUS_STUD' else 0.),
                top_plane_stud_mm=(config['block_stud_height_m'] * 1000.
                    if config['block_surface_height_basis'] == 'TOP_PLANE_PLUS_STUD' else 0.),
                stud_layer_params=config.get('stud_layer'),
                stud_layer_stud_mm=config['block_stud_height_m'] * 1000.)


def load_view_calibrations(root):
    calibrations = {}
    for view in ('V0', 'D1', 'D3'):
        path = root / ('board_calibration_'+view) / view / 'run' / 'calibration.json'
        calibration = json.loads(path.read_text())
        if calibration['view_id'] != view or calibration['independently_validated'] is not True:
            raise ValueError('validated calibration View mismatch: '+str(path))
        calibrations[view] = (path, calibration)
    return calibrations


def load_live_hand(view, path):
    from .hand_cycle import live_hand_components
    if view != 'V0':
        return None, None, None
    try:
        import yaml
        default = path is None
        path = Path(__file__).with_name('config.yaml') if default else Path(path)
        settings = yaml.safe_load(path.read_text())['hand']
        if default and not Path(settings['weights']).is_absolute():
            settings['weights'] = str(Path(__file__).resolve().parent.parent / settings['weights'])
        detector, gate = live_hand_components(view, settings)
        return detector, gate, None
    except (ValueError, KeyError, OSError) as error:
        print('HAND UNKNOWN: '+str(error))
        return None, None, str(error)


def synchronized_packet(queues, max_delta_ns=50_000_000):
    """Newest queued RGB with matching aligned Depth; raw Depth is only needed to save."""
    if not queues['aligned']:
        return None
    for rgb in reversed(queues['rgb']):
        aligned = min(queues['aligned'], key=lambda m: abs(stamp(m)-stamp(rgb)))
        if stamp(rgb) <= 0 or abs(stamp(aligned)-stamp(rgb)) > max_delta_ns:
            continue
        messages = {'rgb': rgb, 'aligned': aligned}
        if queues['raw']:
            raw = min(queues['raw'], key=lambda m: abs(stamp(m)-stamp(rgb)))
            times = [stamp(rgb), stamp(aligned), stamp(raw)]
            if max(times)-min(times) <= max_delta_ns:
                messages['raw'] = raw
        return messages
    return None


class LiveFrameBuffer:
    """Short bounded callback buffer; inference reads one immutable snapshot."""
    def __init__(self):
        self.lock = Lock()
        self.frames = {key: deque(maxlen=10) for key in ('rgb', 'raw', 'aligned')}
        self.infos = {}

    def image(self, key, message):
        with self.lock:
            self.frames[key].append((message, time.monotonic()))

    def info(self, key, message):
        with self.lock:
            self.infos[key] = message

    def clear(self):
        with self.lock:
            for queue in self.frames.values():
                queue.clear()

    def snapshot(self):
        with self.lock:
            frames = {key: list(queue) for key, queue in self.frames.items()}
            infos = dict(self.infos)
        queues = {key: [msg for msg, _ in queue] for key, queue in frames.items()}
        received = {key: queue[-1][1] for key, queue in frames.items() if queue}
        arrivals = {(key, stamp(msg)): at for key, queue in frames.items() for msg, at in queue}
        return queues, infos, received, arrivals


def geometry_display_allowed(synchronized, has_info, stopped, view, hand_event,
                             *, diagnostic=False):
    """Display permission only; never grants hand/cycle/Robot authorization."""
    return bool(synchronized and has_info and stopped and
                (diagnostic or view != 'V0' or hand_event['observation_allowed']))


def sync_diagnostic(queues, received, now, packet_received):
    """Header delta and local arrival ages are separate clocks, in milliseconds."""
    delta = None
    if queues['rgb'] and queues['aligned']:
        latest = stamp(queues['rgb'][-1])
        if latest > 0:
            delta = min((abs(latest-stamp(m)) / 1e6 for m in queues['aligned']
                         if stamp(m) > 0), default=None)
    age = lambda key: None if key not in received else 1000*(now-received[key])
    return dict(delta_ms=delta, rgb_age_ms=age('rgb'), depth_age_ms=age('aligned'),
                packet_age_ms=None if not packet_received else 1000*(now-packet_received))


def sync_diagnostic_text(values):
    value = lambda key: 'missing' if values[key] is None else f'{values[key]:.0f}ms'
    return ('SYNC dt:'+value('delta_ms')+' (limit 50ms) RGB age:'+value('rgb_age_ms')+
            ' Depth age:'+value('depth_age_ms')+' pair age:'+value('packet_age_ms')+' (limit 250ms)')


def geometry_input_reasons(calibration, depth_received, has_info, synchronized,
                           stopped, view, hand_event, *, diagnostic=False):
    reasons = []
    if calibration is None:
        reasons.append('calibration_missing')
    if not depth_received:
        reasons.append('aligned_depth_not_received')
    elif not synchronized:
        reasons.append('rgb_depth_not_fresh_or_synchronized')
    if not has_info:
        reasons.append('aligned_camera_info_not_received')
    if not stopped:
        reasons.append('stop_not_confirmed')
    if view == 'V0' and not diagnostic and not hand_event['observation_allowed']:
        reasons.append('v0_hand_gate_not_ready')
    return reasons


def stopped_analysis_ready(view, stopped, synchronized, has_info, hand_event,
                           frame_stamp, minimum_stamp, *, completed=False):
    """One fresh stopped observation; diagnostics cannot bypass the V0 hand gate."""
    return bool(not completed and stopped and synchronized and has_info and
                frame_stamp > minimum_stamp and
                (view != 'V0' or hand_event['observation_allowed']))


def board_point(pixel, depth, info, calibration):
    """Measured clicked surface point in mm, not a block-anchor detection."""
    if not calibration['independently_validated']:
        raise ValueError('RGB calibration not independently validated')
    h, w = depth.shape
    if [w, h] != calibration['image_size'] or [w, h] != [info['width'], info['height']]:
        raise ValueError('calibration/image size mismatch')
    k = np.asarray(info['k'], float).reshape(3, 3)
    if not np.allclose(k, calibration['intrinsics']['camera_matrix']):
        raise ValueError('camera intrinsics differ from calibration')
    if info['distortion_model'] != 'plumb_bob' or np.any(np.asarray(info['d']) != 0):
        raise ValueError('only zero-distortion aligned Depth supported')
    u, v = pixel
    if not (0 <= u < w and 0 <= v < h) or depth[v, u] == 0:
        raise ValueError('clicked Depth missing')
    z = float(depth[v, u])  # RealSense ROS 16UC1 publishes millimeters.
    camera = np.array([(u-k[0, 2])*z/k[0, 0], (v-k[1, 2])*z/k[1, 1], z])
    pose = calibration['camera_pose']
    r = np.asarray(pose['R_camera_from_board'], float)
    t = np.asarray(pose['t_camera_from_board_mm'], float)
    if (r.shape != (3, 3) or t.shape != (3,) or not np.isfinite(r).all()
            or not np.isfinite(t).all() or not np.allclose(r.T @ r, np.eye(3), atol=1e-5)):
        raise ValueError('invalid calibration pose')
    board = (camera-t) @ r
    board[2] *= pose['height_normal_sign']
    return board


def live_overlay_test_payload(calibration, info, image_shape, reference, position, stage, frame_stamp):
    """Real calibration/RGB; synthetic placements only, never B Current/Observed."""
    from .contracts import validate_block
    height, width = image_shape[:2]
    if calibration['independently_validated'] is not True or calibration['image_size'] != [width, height]:
        raise ValueError('validated calibration/RGB size mismatch')
    k = np.asarray(info['k'], float).reshape(3, 3)
    if [info['width'], info['height']] != [width, height] or not np.allclose(k, calibration['intrinsics']['camera_matrix']):
        raise ValueError('live RGB intrinsics differ from calibration')
    if info['distortion_model'] != 'plumb_bob' or np.any(np.asarray(info['d']) != 0):
        raise ValueError('test projection requires calibrated zero-distortion RGB')
    pose = calibration['camera_pose']
    rotation = np.asarray(pose['R_camera_from_board'], float)
    if pose['height_normal_sign'] != 1:
        raise ValueError('test flat-board transform requires positive height normal')
    transform = np.eye(4)
    transform[:3,:3] = rotation
    transform[:3,3] = (np.asarray(pose['t_camera_from_board_mm']) -
                       rotation[:,2]*reference['height_reference_offset_mm']) / 1000.
    levels = np.asarray(reference['top_heights_mm'], float) / 1000.
    if len(levels) not in (4, 5):
        raise ValueError('test projection needs four or five explicitly configured layer heights')
    blocks = [dict(brick_type='2x2x1', color='yellow', x=position[0], y=position[1],
                   layer=layer, orientation_deg=0) for layer in (1,2,3)]
    for block in blocks:
        validate_block(block)
    before = dict(current_revision=0, blocks=blocks[:2])
    current = before if stage == 'OBSERVING' else dict(current_revision=1, blocks=blocks)
    state = dict(check_id='LOCAL-SYNTHETIC-TEST', display_stage=stage,
        comparison=None if stage == 'OBSERVING' else 'MATCH', previous_current=before,
        current=current, expected=blocks)
    projection = dict(camera_to_board=np.linalg.inv(transform).tolist(),
        rgb_intrinsics=dict(model='none',fx=float(k[0,0]),fy=float(k[1,1]),cx=float(k[0,2]),cy=float(k[1,2])),
        grid_origin_m=[0.,0.],stud_pitch_m=calibration['pitch_mm']/1000.,
        top_heights_m=levels.tolist(),stud_height_m=.004)
    return dict(state=state, projection=projection, projection_valid=True,
        height_reference='board_flat_surface', phase='COMPARISON',
        view_id=calibration['view_id'], frame_stamp_ns=frame_stamp)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--view', choices=('V0', 'D1', 'D3'), required=True)
    parser.add_argument('--comparison-overlay', type=Path,
                        help='Local comparison state + actual frame/projection JSON; not Observed')
    parser.add_argument('--overlay-mode', choices=('auto', 'target', 'changes'), default='auto')
    parser.add_argument('--live-overlay-test', action='store_true',
                        help='Actual ROS RGB + explicitly synthetic state; no YOLO/Robot/cycle')
    parser.add_argument('--overlay-test-position', nargs=2, type=int, default=[9, 13],
                        metavar=('X', 'Y'), help='Synthetic 2x2 anchor, not an observed coordinate')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--calibration', type=Path)
    parser.add_argument('--roi-root', type=Path,
                        help='Assembly ROI root with V0/D1/D3; loads latest saved selection per View')
    parser.add_argument('--manual-views', action='store_true',
                        help='Single window: m moving, v V0, d D1, f D3, s confirm stopped')
    parser.add_argument('--calibration-root', type=Path,
                        help='Recordings root containing board_calibration_V0/D1/D3')
    parser.add_argument('--weights', type=Path,
                        help='Integrated default: first-round blocks_yolo26s_best.pt; explicit override allowed')
    parser.add_argument('--confidence', type=float)
    parser.add_argument('--integrated', action='store_true',
                        help='HSV -> original RGB crop -> five-class YOLO -> Board diagnostics')
    parser.add_argument('--diagnostic-geometry', action='store_true',
                        help='Stopped local Depth/Grid display without hand gate; NOT cycle permission')
    parser.add_argument('--layer-reference', type=Path,
                        help='Optional JSON override: top_heights_mm, tolerance_mm, height_reference_offset_mm; defaults from config.yaml')
    parser.add_argument('--hand-config', type=Path,
                        help='V0 hand settings YAML/JSON (hand section); ignored at D1/D3')
    parser.add_argument('--hand-detect-only', action='store_true',
                        help='V0 ROS RGB hand boxes only; no ROI, exit gate, Robot or Backend output')
    parser.add_argument('--select-hand-roi', action='store_true',
                        help='V0 setup: r freezes RGB for rectangle selection; no inference or cycle')
    parser.add_argument('--opencv-separated', action='store_true',
                        help='Temporary HSV masks + geometry for separated blocks; no Backend output')
    parser.add_argument('--stopped-and-clear', action='store_true',
                        help='Manual diagnostic confirmation, NOT a Controller safety signal')
    args = parser.parse_args(argv)
    args.weights = resolve_live_weights(args.weights, args.integrated)
    if args.live_overlay_test and (not args.manual_views or not args.calibration_root or
            args.integrated or args.weights or args.hand_config or args.comparison_overlay):
        parser.error('--live-overlay-test requires --manual-views + --calibration-root; no inference/state-file modes')
    if args.comparison_overlay and not args.integrated:
        parser.error('--comparison-overlay requires --integrated')
    if args.diagnostic_geometry and not args.integrated:
        parser.error('--diagnostic-geometry requires --integrated')
    if args.roi_root and not args.integrated:
        parser.error('--roi-root requires --integrated')
    view_rois = load_view_rois(args.roi_root) if args.roi_root else None
    if args.select_hand_roi and (args.view != 'V0' or not args.stopped_and_clear or
            args.weights or args.integrated or args.manual_views or args.hand_detect_only or
            args.hand_config or args.opencv_separated or args.calibration or args.calibration_root):
        parser.error('--select-hand-roi needs V0 + --stopped-and-clear, without inference/geometry modes')
    if args.hand_detect_only and (args.view != 'V0' or not args.weights or
            args.integrated or args.opencv_separated or args.manual_views or
            args.hand_config or args.calibration or args.calibration_root or args.stopped_and_clear):
        parser.error('--hand-detect-only requires V0 + hand --weights, without geometry/cycle modes')
    if args.weights and (args.confidence is None or not 0 < args.confidence <= 1):
        parser.error('--weights requires explicit --confidence in (0,1]')
    if args.opencv_separated and (not args.calibration or not args.stopped_and_clear or args.weights):
        parser.error('--opencv-separated needs calibration + stopped-and-clear, without YOLO weights')
    if args.integrated and (not args.weights or args.opencv_separated):
        parser.error('--integrated requires --weights and excludes --opencv-separated')
    if args.layer_reference and not (args.integrated or args.live_overlay_test):
        parser.error('--layer-reference requires --integrated')
    if args.hand_config and not args.integrated:
        parser.error('--hand-config requires --integrated')
    if args.manual_views and (not (args.integrated or args.live_overlay_test) or not args.calibration_root or args.calibration):
        parser.error('--manual-views requires --integrated + --calibration-root, without --calibration')
    if args.calibration_root and not args.manual_views:
        parser.error('--calibration-root requires --manual-views')
    selection = None
    if args.manual_views:
        selection = ViewSelection(args.view, load_view_calibrations(args.calibration_root))
        args.calibration, calibration = selection.calibrations[args.view]
        # Always start blocked until explicit local confirmation; never inherit CLI stop.
        args.stopped_and_clear = False
    else:
        calibration = json.loads(args.calibration.read_text()) if args.calibration else None
    if calibration and calibration['view_id'] != args.view:
        parser.error('calibration View mismatch')
    from .integrated_view import LIVE_CLASSES, process_frame, draw_integrated
    if args.hand_detect_only:
        from .hand_cycle import load_hand_model
        model = load_hand_model(args.weights)
    else:
        model = load_segmentation_model(args.weights, allowed_classes=LIVE_CLASSES if args.integrated else None) if args.weights else None
    layer_reference = load_layer_reference(args.layer_reference) if args.integrated or args.live_overlay_test else {}
    test_stage = 'OBSERVING'
    if layer_reference:
        print('LAYER REFERENCE: ' + str(layer_reference.get('status', 'EXPLICIT_OVERRIDE_NOT_VALIDATED')))
    from .hand_cycle import live_hand_event
    hand_detector, hand_gate, hand_error = None, None, None
    if args.integrated and args.view == 'V0':
        hand_detector, hand_gate, hand_error = load_live_hand(args.view, args.hand_config)
    hand_stamp, hand_event = None, None
    import rclpy
    from rclpy.qos import qos_profile_sensor_data, QoSProfile, ReliabilityPolicy
    # All three image publishers were confirmed reliable; CameraInfo remains sensor-data QoS.
    image_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE)
    from sensor_msgs.msg import Image, CameraInfo
    rclpy.init()
    node = rclpy.create_node('perception_live_diagnostic')
    topics = {'rgb': '/camera/color/image_raw', 'raw': '/camera/depth/image_rect_raw',
              'aligned': '/camera/aligned_depth_to_color/image_raw',
              'rgb-info': '/camera/color/camera_info', 'raw-info': '/camera/depth/camera_info',
              'aligned-info': '/camera/aligned_depth_to_color/camera_info'}
    buffer = LiveFrameBuffer()
    queues, infos, received, arrivals = buffer.snapshot()
    subscriptions = []
    from rclpy.executors import SingleThreadedExecutor
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    receiver_thread = None
    last_sync_log = 0.
    clicked = []
    name = 'Perception LIVE - LOCAL DIAGNOSTIC'
    cv2.namedWindow(name, cv2.WINDOW_AUTOSIZE)
    if not args.opencv_separated and not args.hand_detect_only and not args.select_hand_roi:
        cv2.setMouseCallback(name, lambda event, x, y, flags, data:
                            clicked.__setitem__(slice(None), [(x, y)]) if event == cv2.EVENT_LBUTTONDOWN else None)
    last_rgb, receipt = None, time.monotonic()
    reference, measurement = None, None
    tracks, candidate_stamp = [], None
    packet, packet_received = None, 0.
    frozen_canvas = None
    frozen_hud = None
    hud_mode = default_hud_mode(args.view)
    hand_ready_stamp = None
    view_generation = selection.generation if selection else 0
    def stop_receiving():
        nonlocal receiver_thread, executor
        if receiver_thread is not None:
            executor.shutdown(timeout_sec=2.)
            receiver_thread.join(timeout=2.)
            if receiver_thread.is_alive():
                raise RuntimeError('ROS receiver did not stop; observation blocked')
            receiver_thread = None
        for subscription in subscriptions:
            node.destroy_subscription(subscription)
        subscriptions.clear()
        executor.remove_node(node)
        executor = SingleThreadedExecutor()
        executor.add_node(node)

    def start_receiving():
        nonlocal receiver_thread, buffer
        if receiver_thread is not None:
            return
        buffer = LiveFrameBuffer()  # No old View frames or CameraInfo.
        for key in ('rgb', 'raw', 'aligned'):
            subscriptions.append(node.create_subscription(Image, topics[key],
                lambda msg, k=key, b=buffer: b.image(k, msg),
                image_qos))
            subscriptions.append(node.create_subscription(CameraInfo, topics[key+'-info'],
                lambda msg, k=key, b=buffer: b.info(k, msg), qos_profile_sensor_data))
        receiver_thread = Thread(target=executor.spin, name='ros-rgbd-receiver', daemon=True)
        receiver_thread.start()

    try:
        if not args.integrated and not args.live_overlay_test:
            start_receiving()
        else:
            print('STOPPED OBSERVATION: no receiving while moving; one RGB-D pair, one analysis. '
                  'V0 hand monitoring stays continuous until ready; r requests a new observation.')
        if args.select_hand_roi:
            print('V0 HAND ROI SETUP: r = freeze RGB and select board rectangle; q = quit. No Robot/cycle permission.')
        elif args.hand_detect_only:
            print('HAND DETECTION ONLY: actual ROS RGB, CPU; q = quit. No saving, cycle gate or Robot permission.')
        elif args.opencv_separated:
            print('LIVE: automatic block masks and lower-left Board stud coordinates; NO clicking required. c = RGB-D; q = quit.')
        else:
            print('LIVE: click stud center; 1 = store lower stud; 2 = compare upper stud; c = RGB-D; q = quit.')
        print('Diagnostic only: XYZ calibration bias/Depth noise not accepted as validated placement.')
        if selection:
            print('MANUAL VIEW: m BEFORE moving; v=V0 d=D1 f=D3; s AFTER actual stop. No Robot commands.')
        while rclpy.ok():
            if selection and selection.generation != view_generation:
                stop_receiving()
                args.view, args.stopped_and_clear = selection.view, selection.stopped
                args.calibration, calibration = selection.calibrations[args.view]
                buffer.clear()
                packet, packet_received, last_rgb = None, 0., None
                frozen_canvas, hand_ready_stamp = None, None
                hud_mode = default_hud_mode(args.view)
                clicked.clear()
                reference, tracks, candidate_stamp = None, [], None
                hand_stamp, hand_event = None, None
                if hand_gate is not None:
                    hand_gate.reset_for_reobservation()
                    hand_detector.reset()
                if args.view == 'V0' and hand_detector is None:
                    hand_detector, hand_gate, hand_error = load_live_hand(args.view, args.hand_config)
                view_generation = selection.generation
                test_stage = 'OBSERVING'
                print(f'VIEW {args.view}: '+('STOPPED (manual)' if selection.stopped else 'MOVING/UNCONFIRMED'))
            measurement = None
            hud = new_hud()
            loop_started = time.monotonic()
            if args.integrated or args.live_overlay_test:
                if args.stopped_and_clear and frozen_canvas is None:
                    start_receiving()
                elif receiver_thread is not None:
                    stop_receiving()
            queues, infos, received, arrivals = buffer.snapshot()
            if args.integrated and frozen_canvas is not None:
                canvas = frozen_canvas.copy()
                hud['lines'] = list(frozen_hud['lines'])
                hud['records'], hud['show_height'] = frozen_hud['records'], frozen_hud['show_height']
            elif args.integrated and not args.stopped_and_clear:
                canvas = np.zeros((180, 1000, 3), np.uint8)
                hud_add(hud, canvas, 'MOVING / UNCONFIRMED: receiving and inference OFF',
                            (12, 40), 0, .6, (0, 180, 255), 2)
                messages = None
            elif not queues['rgb']:
                canvas = np.zeros((180, 800, 3), np.uint8)
                hud_add(hud, canvas, 'Waiting for ROS RGB...', (12, 40), 0, .7, (0, 180, 255), 2)
                messages = None
            else:
                matched = synchronized_packet(queues)
                if matched and (packet is None or stamp(matched['rgb']) != stamp(packet['rgb'])):
                    packet = matched
                    packet_received = min(arrivals[(key, stamp(matched[key]))]
                                          for key in ('rgb', 'aligned'))
                synchronized = packet is not None and time.monotonic()-packet_received < .25
                # Retain the matched image AND its overlays briefly, never overlay old masks on new RGB.
                rgb_msg = packet['rgb'] if synchronized else queues['rgb'][-1]
                if stamp(rgb_msg) != last_rgb:
                    receipt, last_rgb = time.monotonic(), stamp(rgb_msg)
                rgb = image_array(rgb_msg)
                canvas = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                messages = packet if synchronized else {'rgb': rgb_msg}
                fresh = time.monotonic()-receipt < 1.0
                if args.integrated:
                    usable_hand = fresh and synchronized and args.stopped_and_clear
                    if stamp(rgb_msg) != hand_stamp or not usable_hand:
                        hand_event = live_hand_event(args.view, hand_detector, hand_gate,
                            rgb, image_array(messages['aligned']) if usable_hand else None,
                            time.monotonic(), usable=usable_hand)
                        hand_stamp = stamp(rgb_msg)
                    if hand_error and args.view == 'V0':
                        hand_event['reason'] = hand_error
                    if args.view == 'V0':
                        if not hand_event['observation_allowed']:
                            hand_ready_stamp = None
                        elif hand_ready_stamp is None:
                            hand_ready_stamp = stamp(rgb_msg)
                    analysis_ready = stopped_analysis_ready(args.view, args.stopped_and_clear,
                        synchronized, 'aligned' in infos and 'rgb' in infos, hand_event,
                        stamp(rgb_msg), hand_ready_stamp if args.view == 'V0' and
                        hand_ready_stamp is not None else 0)
                    if not analysis_ready:
                        hud_add(hud, canvas, 'WAIT: V0 hand entry/exit and stability' if args.view == 'V0'
                                    else 'WAIT: fresh synchronized RGB-D and CameraInfo',
                                    (8, 70), 0, .5, (0, 180, 255), 1)
                if args.opencv_separated:
                    from .opencv_live import candidates, stabilize, draw
                    if fresh and synchronized and 'aligned' in infos:
                        if candidate_stamp != stamp(rgb_msg):
                            try:
                                records = candidates(rgb, image_array(messages['aligned']),
                                                     info_dict(infos['aligned']), calibration)
                                tracks = stabilize(records, tracks)
                            except (ValueError, KeyError) as error:
                                tracks = []
                                print('OpenCV UNKNOWN: ' + str(error))
                            candidate_stamp = stamp(rgb_msg)
                        canvas = draw(canvas, tracks)
                    else:
                        tracks, candidate_stamp = [], None
                        missing = ('aligned Depth not received' if not queues['aligned'] else
                                   'aligned CameraInfo not received' if 'aligned' not in infos else
                                   'no fresh timestamp-matched RGB/Depth')
                        hud_add(hud, canvas, 'UNKNOWN: ' + missing,
                                    (8, 70), 0, .5, (0, 0, 255), 1)
                    hud_add(hud, canvas, 'HSV TEST: separated only; no layer/Backend; thresholds temporary',
                                (8, 48), 0, .5, (0, 220, 255), 1)
                if args.integrated and fresh and analysis_ready:
                    stop_receiving()  # Freeze the selected RGB-D before slow inference.
                    try:
                        input_reasons = geometry_input_reasons(calibration, bool(queues['aligned']),
                            'aligned' in infos, synchronized, args.stopped_and_clear,
                            args.view, hand_event, diagnostic=args.diagnostic_geometry)
                        # Never infer on a rendered canvas: text and masks are presentation only.
                        has_geometry = geometry_display_allowed(synchronized, 'aligned' in infos,
                            args.stopped_and_clear, args.view, hand_event,
                            diagnostic=args.diagnostic_geometry)
                        records = process_frame(rgb, model, args.confidence,
                            image_array(messages['aligned']) if has_geometry else None,
                            info_dict(infos['aligned']) if has_geometry else None,
                            calibration if args.stopped_and_clear else None,
                            layer_reference.get('top_heights_mm'), layer_reference.get('tolerance_mm'),
                            roi_mask=view_rois[args.view][0] if view_rois else None,
                            height_reference_offset_mm=layer_reference.get('height_reference_offset_mm', 0.),
                            depth_range_m=(
                                [layer_reference['depth_ranges_m'][args.view][key]
                                 for key in ('min_depth_m', 'max_depth_m')]
                                if layer_reference.get('depth_ranges_m') else None),
                            max_height_spread_mm=layer_reference.get('max_height_spread_mm'),
                            block_stud_height_mm=layer_reference.get('block_stud_height_mm', 0.),
                            top_plane_stud_mm=layer_reference.get('top_plane_stud_mm', 0.),
                            first_layer_min_mm=layer_reference.get('first_layer_min_mm'),
                            first_layer_max_mm=layer_reference.get('first_layer_max_mm'),
                            layer_upper_bounds_mm=layer_reference.get('layer_upper_bounds_mm'),
                            board_baseline_params=layer_reference.get('board_baseline_params'),
                            board_bounds_mm=layer_reference.get('board_bounds_mm'),
                            stud_layer_params=layer_reference.get('stud_layer_params'),
                            stud_layer_stud_mm=layer_reference.get('stud_layer_stud_mm', 0.))
                        for record in records:
                            if record.get('reason') == 'calibration_or_synced_depth_missing':
                                record['reason'] = ', '.join(input_reasons)
                        canvas = (draw_integrated(canvas, records, show_height=args.diagnostic_geometry)
                                  if HUD_LEGACY_BLOCK_LABELS else draw_block_badges(canvas, records))
                        hud['records'], hud['show_height'] = records, args.diagnostic_geometry
                        if view_rois:
                            cv2.polylines(canvas, [view_rois[args.view][1]], True, (0, 255, 0), 2)
                        hud_add(hud, canvas, 'HSV -> YOLO -> DEPTH/GRID | trial geometry thresholds; LOCAL ONLY',
                                    (8, 48), 0, .5, (0, 220, 255), 1)
                        reasons = sorted(set(input_reasons) | {
                            r['reason'] for r in records if r.get('reason')})
                        if reasons:
                            hud_add(hud, canvas, 'GEOMETRY: '+', '.join(reasons),
                                        (8, 70), 0, .45, (0, 180, 255), 1)
                        if args.diagnostic_geometry:
                            hud_add(hud, canvas, 'MEASUREMENT DISPLAY ONLY - NO CYCLE / ROBOT PERMISSION',
                                        (8, 92), 0, .45, (0, 180, 255), 1)
                    except (ValueError, KeyError, cv2.error) as error:
                        hud_add(hud, canvas, 'UNKNOWN: '+str(error), (8, 70), 0, .5, (0, 0, 255), 1)
                    frozen_canvas = canvas.copy()
                    frozen_hud = dict(lines=list(hud['lines']), records=hud['records'],
                                      show_height=hud['show_height'])
                    print('OBSERVATION FINISHED: receiving OFF; result frozen. r=new observation.', flush=True)
                elif model and fresh and not args.integrated:
                    result = model.predict(canvas, conf=args.confidence, retina_masks=True,
                                           device='cpu', verbose=False)[0]
                    canvas = result.plot()
                line = f'{args.view} LOCAL ONLY | c: capture | q: quit | h: hud | '
                line += ('OpenCV SEPARATED TEST' if args.opencv_separated else
                         'HAND ROI SETUP | r:select board' if args.select_hand_roi else
                         'INTEGRATED CPU' if args.integrated else
                         'HAND BOXES ONLY - NO CYCLE PERMISSION' if args.hand_detect_only else
                         'YOLO CPU' if model else 'NO MODEL - no automatic block coordinates')
                hud_add(hud, canvas, line, (8, 24), 0, .5, (0, 220, 255), 1)
                if not fresh:
                    hud_add(hud, canvas, 'STALE RGB - no measurement/capture', (8, 48), 0, .6, (0, 0, 255), 2)
                elif clicked and calibration and args.stopped_and_clear and synchronized and 'aligned' in infos:
                    try:
                        point = board_point(clicked[0], image_array(messages['aligned']),
                                            info_dict(infos['aligned']), calibration)
                        measurement = point.copy()
                        text = 'CLICK surface XYZ mm: ' + ', '.join(f'{p:.2f}' for p in point)
                        text += ' | grid XY: ' + ', '.join(f'{p/calibration["pitch_mm"]:.2f}' for p in point[:2])
                    except (ValueError, KeyError) as error:
                        text = 'UNKNOWN: ' + str(error)
                    cv2.circle(canvas, clicked[0], 5, (0, 0, 255), 2)
                    hud_add(hud, canvas, text, (8, 70), 0, .5, (0, 220, 255), 1)
                elif args.select_hand_roi:
                    hud_add(hud, canvas, 'Press r, drag around entire assembly board, ENTER accept; q quit',
                                (8, 48), 0, .5, (0, 180, 255), 1)
                elif args.hand_detect_only:
                    hud_add(hud, canvas, 'All image hand boxes; NOT board entry/exit; NOT a safety interlock',
                                (8, 48), 0, .5, (0, 180, 255), 1)
                elif not args.opencv_separated and not args.integrated:
                    hud_add(hud, canvas, 'XYZ unavailable unless stopped + calibration + synced Depth',
                                (8, 48), 0, .5, (0, 180, 255), 1)
                if reference is not None:
                    hud_add(hud, canvas, 'Stored lower XYZ mm: ' + ', '.join(f'{p:.2f}' for p in reference),
                                (8, 95), 0, .5, (80, 255, 80), 1)
            if args.integrated:
                if hand_event is None:
                    hand_event = live_hand_event(args.view, hand_detector, hand_gate,
                        None, None, time.monotonic(), usable=False)
                label = (f"HAND {args.view}: {hand_event['presence']} | {hand_event['state']} | "
                         f"exit {hand_event['absent_seconds']:.2f}s (>3s) | stable {hand_event['stable']}")
                hud_add(hud, canvas, label, (8, canvas.shape[0]-32), 0, .5, (0, 220, 255), 1)
                hud_add(hud, canvas, str(hand_event['reason'])+' | NOT STEP COMPLETE',
                            (8, canvas.shape[0]-12), 0, .4, (0, 220, 255), 1)
            if selection:
                mode = 'STOPPED (manual)' if selection.stopped else 'MOVING/UNCONFIRMED - receiving/inference OFF'
                hud_add(hud, canvas, f'{selection.view} {mode} | m:move v:V0 d:D1 f:D3 s:stop',
                            (8,canvas.shape[0]-54),0,.5,(0,220,255),1)
            if args.integrated and frozen_canvas is None:
                now = time.monotonic()
                latest_queues, _, latest_received, _ = buffer.snapshot()
                sync_text = sync_diagnostic_text(sync_diagnostic(latest_queues, latest_received, now, packet_received))
                hud_add(hud, canvas, sync_text, (8, 114), 0, .42, (0, 220, 255), 1)
                if now-last_sync_log >= 2.:
                    print(sync_text+f' loop:{1000*(now-loop_started):.0f}ms', flush=True)
                    last_sync_log = now
            if args.integrated:
                hud_add(hud, canvas, 'RESULT FROZEN | receiving OFF | r:new observation' if frozen_canvas is not None
                            else 'RECEIVING ON: stopped observation' if receiver_thread is not None
                            else 'RECEIVING OFF', (8, 136), 0, .42, (0, 220, 255), 1)
            if args.live_overlay_test:
                from .visualization import render_comparison_overlay
                try:
                    if not messages or 'rgb' not in messages or 'rgb' not in infos:
                        raise ValueError('live RGB and RGB CameraInfo required')
                    if time.monotonic()-received.get('rgb', 0.) > 1.:
                        raise ValueError('live RGB stale')
                    payload = live_overlay_test_payload(calibration, info_dict(infos['rgb']),
                        image_array(messages['rgb']).shape, layer_reference, args.overlay_test_position,
                        test_stage, stamp(messages['rgb']))
                    overlay, report = render_comparison_overlay(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB),
                        payload, view=args.view, frame_stamp_ns=stamp(messages['rgb']),
                        stopped=args.stopped_and_clear, hand_clear=args.stopped_and_clear, mode='auto')
                    canvas = cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR)
                except (ValueError, KeyError) as error:
                    hud_add(hud, canvas, '3D TEST hidden: '+str(error), (8, 155),0,.45,(0,180,255),1)
                hud_add(hud, canvas, 'LIVE RGB + SYNTHETIC STATES / TRIAL HEIGHTS / NOT ASSEMBLY VERIFICATION',
                            (8, 178),0,.42,(0,180,255),1)
                hud_add(hud, canvas, 'b:before comparison | a:simulate confirmed | m:move | s:stopped | q:quit',
                            (8, 198),0,.42,(0,180,255),1)
            if args.comparison_overlay:
                from .visualization import render_comparison_overlay
                try:
                    payload = json.loads(args.comparison_overlay.read_text())
                    overlay, overlay_report = render_comparison_overlay(
                        cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB), payload, view=args.view,
                        frame_stamp_ns=stamp(messages['rgb']) if messages and 'rgb' in messages else None,
                        stopped=args.stopped_and_clear,
                        hand_clear=bool(hand_event and hand_event.get('observation_allowed'))
                            if args.view == 'V0' else args.stopped_and_clear,
                        mode=args.overlay_mode)
                    canvas = cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR)
                except (OSError, ValueError) as error:
                    hud_add(hud, canvas, '3D hidden: comparison input unavailable',
                                (8, 134), 0, .45, (0, 180, 255), 1)
            render_hud(canvas, hud, hud_mode)
            cv2.imshow(name, canvas)
            key = cv2.waitKey(1) & 255
            if key == ord('q') or cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord('h'):
                hud_mode = (hud_mode + 1) % 3
                continue
            if args.live_overlay_test and key in (ord('a'), ord('b')):
                if not args.stopped_and_clear:
                    print('Overlay test stage blocked: confirm actual stop first')
                else:
                    test_stage = 'CONFIRMED' if key == ord('a') else 'OBSERVING'
                continue
            if args.live_overlay_test and key == ord('c'):
                print('Overlay-only test: capture/Observed/Robot output disabled')
                continue
            if args.integrated and key == ord('r'):
                if not args.stopped_and_clear:
                    print('Re-observation blocked: actual stop confirmation required')
                    continue
                stop_receiving()
                frozen_canvas, hand_ready_stamp = None, None
                packet, packet_received, last_rgb = None, 0., None
                hand_stamp, hand_event = None, None
                if hand_gate is not None:
                    hand_gate.reset_for_reobservation()
                    hand_detector.reset()
                continue
            if selection and key in map(ord, 'mvdfs'):
                try:
                    if key == ord('m'):
                        selection.update(selection.view, stopped=False)
                    elif key == ord('s'):
                        selection.update(selection.view, stopped=True)
                    else:
                        if selection.stopped:
                            raise ValueError('Press m BEFORE moving; then select the destination View')
                        selection.update({ord('v'):'V0',ord('d'):'D1',ord('f'):'D3'}[key],stopped=False)
                except ValueError as error:
                    print('View switch blocked: '+str(error))
                continue
            if args.select_hand_roi and key == ord('r'):
                if not queues['rgb'] or time.monotonic() - receipt >= 1.:
                    print('ROI blocked: fresh RGB required')
                    continue
                rectangle = cv2.selectROI('V0 board ROI - ENTER accept, C cancel',
                    cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), showCrosshair=True, fromCenter=False)
                cv2.destroyWindow('V0 board ROI - ENTER accept, C cancel')
                path = save_hand_roi(args.output, rgb, rectangle, rgb_msg)
                print('ROI cancelled; nothing saved' if path is None else
                      'ROI saved: '+str(path)+' | other hand settings still required')
                continue
            if (args.hand_detect_only or args.select_hand_roi) and key in (ord('c'), ord('1'), ord('2')):
                print('Detection-only mode: capture and geometry comparison disabled')
                continue
            if not args.opencv_separated and key in (ord('1'), ord('2')):
                if measurement is None:
                    print('Comparison blocked: click a valid stud with synchronized Depth first')
                    continue
                if key == ord('1'):
                    reference = measurement.copy()
                    clicked.clear()  # Upper surface shifts in pixels; require a fresh click.
                    print('Lower stud saved, XYZ mm:', reference.tolist())
                elif reference is None:
                    print('Press 1 on the lower stud first')
                    continue
                else:
                    delta = measurement-reference
                    report = {'scope': 'LOCAL_COORDINATE_DIAGNOSTIC', 'view_id': args.view,
                              'calibration': str(args.calibration.resolve()),
                              'lower_xyz_mm': reference.tolist(), 'upper_xyz_mm': measurement.tolist(),
                              'delta_xyz_mm': delta.tolist(),
                              'delta_xy_stud': (delta[:2]/calibration['pitch_mm']).tolist(),
                              'judgement': 'NOT_AUTOMATIC_PASS',
                              'note': 'Same anchor must be clicked; no assumed layer or correction offset'}
                    print(json.dumps(report, ensure_ascii=False, indent=2))
                    args.output.mkdir(parents=True, exist_ok=True)
                    report_path = args.output / ('comparison_' + datetime.now(timezone.utc).strftime(
                        '%Y%m%dT%H%M%S%fZ') + '.json')
                    with report_path.open('x', encoding='utf-8') as stream:
                        json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
            if key == ord('c'):
                missing = [topics[k] for k in queues if not queues[k]]
                missing += [topics[k+'-info'] for k in queues if k not in infos]
                if not args.stopped_and_clear:
                    print('Capture blocked: --stopped-and-clear required')
                    continue
                if missing:
                    print('Capture blocked: missing topics: ' + ', '.join(missing))
                    continue
                capture_messages = synchronized_packet(queues)
                if not capture_messages or 'raw' not in capture_messages:
                    latest = {k: stamp(queue[-1]) for k, queue in queues.items()}
                    print('Capture blocked: RGB/raw/aligned timestamps not matched within 50ms; '
                          'latest timestamps ns: ' + str(latest))
                    continue
                if (not synchronized or time.monotonic()-receipt >= 1.0 or
                        stamp(capture_messages['rgb']) != stamp(packet['rgb'])):
                    print('Capture blocked: matched RGB-D is stale; no fresh matched packet in 0.25s')
                    continue
                capture_root = args.output / args.view if selection else args.output
                directory = capture_root / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                try:
                    save_capture(directory, capture_messages, infos, topics, args.view, 50.)
                except (ValueError, OSError) as error:
                    print('Capture failed: ' + str(error))
    finally:
        cv2.destroyAllWindows()
        stop_receiving()
        executor.shutdown(timeout_sec=2.)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
