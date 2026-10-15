"""Shared assembly-board pixel ROI for live and inspection paths."""
from copy import deepcopy
import json
from pathlib import Path

import cv2
import numpy as np

DEFAULT_ROOT = Path(__file__).resolve().parent.parent / 'recordings/assembly_board_roi'


def profile_mask(profile, image_shape=None):
    from .hand_cycle import validate_polygon
    width, height = profile['image_size']
    if any(type(v) is not int or v <= 0 for v in (width, height)):
        raise ValueError('Invalid ROI image size')
    if image_shape is not None and tuple(image_shape[:2]) != (height, width):
        raise ValueError('assembly_roi_resolution_mismatch: saved ROI must match captured RGB')
    polygon = validate_polygon(profile['polygon_px'])
    if (polygon < 0).any() or (polygon[:, 0] >= width).any() or (polygon[:, 1] >= height).any():
        raise ValueError('ROI outside image')
    mask = np.zeros((height, width), np.uint8)
    cv2.fillPoly(mask, [polygon], 1)
    return mask.astype(bool), polygon


def load_profiles(root):
    profiles = {}
    for view in ('V0', 'D1', 'D3'):
        paths = sorted((Path(root) / view).glob('*/assembly_roi.json'))
        if not paths:
            raise ValueError('Missing assembly ROI for ' + view)
        path = paths[-1]
        data = json.loads(path.read_text())
        if data.get('purpose') != 'ASSEMBLY_BOARD' or data.get('view_id', 'V0') != view:
            raise ValueError('Assembly ROI View mismatch: ' + str(path))
        profile_mask(data)
        profiles[view] = dict(data, view_id=view, source=str(path.resolve()))
    return profiles


def freeze_rois(config, *, default=False):
    """Freeze JSON profiles in the cycle archive; missing configured files fail closed."""
    config = deepcopy(config)
    root = config.get('assembly_roi_root', str(DEFAULT_ROOT) if default else None)
    if root is not None and 'assembly_roi_profiles' not in config:
        root = Path(root)
        if not root.is_absolute():
            root = Path(__file__).resolve().parent.parent / root
        config['assembly_roi_profiles'] = load_profiles(root)
        config['assembly_roi_root'] = str(root.resolve())
    return config


def mask_for_view(config, view, image_shape):
    profiles = config.get('assembly_roi_profiles')
    if profiles is None:
        return None
    if view not in profiles:
        raise ValueError('Missing assembly ROI for ' + view)
    return profile_mask(profiles[view], image_shape)[0]
