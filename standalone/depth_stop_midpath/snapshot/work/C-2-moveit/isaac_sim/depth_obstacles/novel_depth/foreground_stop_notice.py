"""In-process qualified foreground notice; no point/risk product or commands.

Call immediately after the original evaluate_depth_frame, while its owned
arrays and capture frame are alive. The receiver must still check its current
SIM clock, accepted goal, binding and active UUID immediately before cancel.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import math

import numpy as np

from .geometry import _digest
from .qualification import camera_scope


_ORIGIN = object()


@dataclass(frozen=True, slots=True)
class ForegroundStopNotice:
    """Immutable local lease; JSON/deserialized dictionaries are not notices."""
    metadata_json: str
    metadata_sha256: str
    _mask_bytes: bytes
    _attestation: tuple

    @property
    def candidate_mask(self):
        shape = json.loads(self.metadata_json)['candidate_mask_shape']
        return np.frombuffer(self._mask_bytes, dtype=np.bool_).reshape(shape)


def verify_foreground_stop_notice(notice):
    """Check the small seal without rehashing a full mask on the cancel path.

    The producer hashed and copied the mask into immutable bytes. Attestation
    binds that exact bytes object and metadata, so receiving only checks their
    identity and the small metadata digest. This is a local ownership contract,
    not authentication against arbitrary code executing in this process.
    """
    if type(notice) is not ForegroundStopNotice:
        raise ValueError('FOREGROUND_STOP_TRUSTED_NOTICE_REQUIRED')
    origin, metadata, mask = notice._attestation
    if (origin is not _ORIGIN or metadata is not notice.metadata_json or
            mask is not notice._mask_bytes or
            sha256(metadata.encode()).hexdigest() != notice.metadata_sha256):
        raise ValueError('FOREGROUND_STOP_NOTICE_SEAL_MISMATCH')
    return json.loads(metadata)


def make_foreground_stop_notice(review, frame, known_geometry, *, completed_source_observation):
    """Preserve original classification/source; return None for non-foreground.

    No projection, PNG, disk export, display preparation or commands run here.
    The original evaluator already checked raw-depth and native source pins.
    These checks bind that result, qualification and frozen map to this frame.
    Stale notices retain their original age; the receiver rejects them.
    """
    if review.get('guard') or not review.get('detection'):
        return None
    detection = review['detection']
    expected = review['expected']
    if detection.get('guard') or detection.get('counts', {}).get('foreground', 0) == 0:
        return None
    qualification = expected.get('scoped_qualification')
    if (not qualification or expected['error_model']['status'] != 'SIM_SCOPED_NUMERICAL_MODEL' or
            detection.get('classification_scope') != 'SIM_NUMERICAL_TRIAL'):
        return None
    association = frame['source_association']
    if (frame['source_kind'] != 'SIM_DEPTH' or frame['clock_basis'] != 'SIM_TIME' or
            association['scope'] != 'ACTUAL_SOURCE_TICK' or
            association.get('physical_source_pair_verified') is not True or
            association.get('same_tick_verified') is not True or
            expected['status'] != 'ACTUAL_SOURCE_TICK' or
            expected['map_scope'] != 'PRE_OBSTACLE_APPROVED' or
            _digest(frame) != _digest(expected['frame_state']) or
            detection['source_association'] != association):
        raise ValueError('FOREGROUND_STOP_ORIGINAL_SOURCE_MISMATCH')
    # face_intervals retains the exact qualification ref/digest after the
    # original evaluator has pinned and checked session/camera/model scope.
    qref = qualification['qualification_ref']
    if (expected['error_model']['qualification_ref'] != qref or
            detection['qualification_ref'] != qref or
            detection['effective_pixel_convention']['status'] != 'SCOPED_SIM_TEST' or
            detection['map_digest'] != expected['map_digest'] or
            expected['map_digest'] != known_geometry['digest'] or
            detection['error_model_digest'] != expected['error_model_digest']):
        raise ValueError('FOREGROUND_STOP_QUALIFICATION_OR_MAP_MISMATCH')
    mask = detection['candidate_mask']
    shape = (frame['intrinsics']['height'], frame['intrinsics']['width'])
    if (not isinstance(mask, np.ndarray) or mask.dtype != np.bool_ or mask.shape != shape or
            int(mask.sum()) != detection['counts']['foreground'] or
            not np.array_equal(mask, detection['reason_masks']['foreground']) or
            np.any(mask & detection['uncertain_candidate_mask'])):
        raise ValueError('FOREGROUND_STOP_ORIGINAL_MASK_MISMATCH')
    clock = dict(completed_source_observation)
    wall_keys = [k for k in ('wall_monotonic_s', 'observed_wall_monotonic_s') if k in clock]
    if (any(clock[k] != frame[k] for k in ('session_id', 'clock_epoch', 'clock_basis')) or
            not wall_keys or not all(math.isfinite(clock[k]) for k in ['source_s'] + wall_keys) or
            len({clock[k] for k in wall_keys}) != 1 or
            not math.isfinite(frame['source_stamp_s']) or clock['source_s'] < frame['source_stamp_s']):
        raise ValueError('FOREGROUND_STOP_COMPLETION_CLOCK_MISMATCH')
    mask_bytes = mask.tobytes(order='C')
    age = clock['source_s'] - frame['source_stamp_s']
    metadata = dict(schema='qualified-foreground-conservative-stop-notice/1.0',
        scope='SIM_CONSERVATIVE_FOREGROUND_STOP_NOT_PATH_RISK',
        **{k: frame[k] for k in ('session_id', 'clock_epoch', 'clock_basis', 'frame_seq',
            'source_stamp_s', 'reference_time', 'renderer_frame_id', 'render_request_id',
            'optical_frame_id', 'calibration_id', 'depth_array_sha256', 'rgb_array_sha256')},
        source_frame_digest=_digest(frame), source_association_digest=_digest(association),
        calibration_digest=_digest(camera_scope(frame)), source_refs=frame['source_refs'],
        qualification_ref=qref, qualification_digest=qualification['qualification_digest'],
        map_digest=detection['map_digest'], model_manifest_sha256=known_geometry['metadata']['model_manifest_sha256'],
        error_model_digest=detection['error_model_digest'], counts=detection['counts'],
        candidate_mask_shape=list(shape), candidate_mask_sha256=sha256(mask_bytes).hexdigest(),
        completed_source_observation=clock, classification_age_SIM_s=age,
        fresh_at_notice=0 <= age <= .12, TTL_SIM_s=.12, qualified_foreground_observed=True,
        receiver_must_check_current_clock_and_active_UUID=True,
        point_error_m=None, risk_qualified=False, stop_intent=None, execution_allowed=False)
    encoded = json.dumps(metadata, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return ForegroundStopNotice(encoded, sha256(encoded.encode()).hexdigest(), mask_bytes,
        (_ORIGIN, encoded, mask_bytes))
