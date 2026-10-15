"""Offline slot ROI candidates and RGB-D observation audit; no device interface."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT.parent / 'perception')]
from app.supply_stud.backend import observe
from app.supply_stud.depth_center import processing_frame
from scripts.capture_supply_depth_reference import surface_point, pose_gap
from supply_vision.virtual_board_grid import pose_matrix


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def identity(row):
    return f"{row['color']}_{row['brick_type']}_{row['slot']:02d}"


def affine_model(template_centers, observed_centers):
    source = np.c_[np.asarray(template_centers, float), np.ones(3)]
    if source.shape != (3, 3) or np.linalg.matrix_rank(source) != 3:
        raise ValueError('THREE_NONCOLLINEAR_ANCHORS_REQUIRED')
    return np.linalg.solve(source, np.asarray(observed_centers, float))


def roi_candidate(roi, matrix):
    x0, y0, x1, y1 = roi
    corners = np.array([[x0, y0, 1], [x1, y0, 1], [x0, y1, 1], [x1, y1, 1]]) @ matrix
    low, high = np.floor(corners.min(axis=0)), np.ceil(corners.max(axis=0))
    if np.any(low < 0) or np.any(high > [640, 480]) or np.any(high <= low):
        raise ValueError('MODEL_ROI_OUTSIDE_PROCESSING_IMAGE')
    return [*low.astype(int).tolist(), *high.astype(int).tolist()]


def valid_packet(info):
    times = info['stamps_ns']
    return (info['width'] == 1280 and info['height'] == 720
            and info['frame_id'] == 'camera_color_optical_frame'
            and info['depth_encoding'] == '16UC1'
            and len(times) == 3 and max(times)-min(times) <= 50_000_000
            and all(0 <= age <= 300 for age in info['ages_at_capture_ms']))


def row_grid(observations):
    # Fit visual spacing, never robot pickup coordinates. Median neighbours
    # keep a slightly displaced baseline block from tilting every other row.
    groups = {}
    for row, center in observations:
        groups.setdefault((row['color'], row['brick_type']), []).append((row['slot'], np.array(center)))
    if len(groups) != 5 or any(len(rows) < 3 for rows in groups.values()):
        raise ValueError('AT_LEAST_THREE_VISIBLE_CENTERS_PER_ROW_REQUIRED')
    steps = []
    for rows in groups.values():
        rows.sort(key=lambda item: item[0])
        steps.extend((b-a)/(j-i) for (i, a), (j, b) in zip(rows, rows[1:]))
    step = np.median(steps, axis=0)
    if step[0] >= 0 or np.linalg.norm(step) < 1:
        raise ValueError('RIGHT_TO_LEFT_GRID_REQUIRED')
    origins = {key: np.median([center-(slot-1)*step for slot, center in rows], axis=0)
               for key, rows in groups.items()}
    return step, origins


def validate_frozen_layout(layout, binding, slot_ids):
    if (layout.get('schema_version') != 'supply-rgbd-model-layout-candidate/1'
            or layout.get('model_binding') != binding
            or {identity(row) for row in layout['slots']} != set(slot_ids)
            or len(layout['slots']) != 25 or layout['image_size'] != [640, 480]):
        raise ValueError('FROZEN_MODEL_BINDING_MISMATCH')


def build(args):
    # Exclusive output creation preserves prior evidence even on a failed run.
    args.output.mkdir(parents=True, exist_ok=False)
    bundle, template = read(args.references), read(args.layout)
    capture = read(args.capture/'capture.json')
    before, after = capture['before'], capture['after']
    if (any(before[k] != bundle['connection'][k] or after[k] != before[k] for k in ('tcp', 'tool'))
            or any(v > .5 for v in pose_gap(before['posx'], bundle['observation_pose']))
            or any(v > .5 for v in pose_gap(before['posx'], after['posx']))):
        raise ValueError('CAPTURE_POSE_TCP_BINDING_MISMATCH')
    entries = {identity(s): s for s in template['slots']}
    if len(entries) != 25 or len(template['slots']) != 25 or template['image_size'] != [640, 480]:
        raise ValueError('CURRENT_UNIQUE_25_SLOT_TEMPLATE_REQUIRED')
    frames = sorted(args.capture.glob('frame-*.json'))
    if len(frames) < 3:
        raise ValueError('MODEL_FRAME_AND_HELD_OUT_FRAMES_REQUIRED')
    first_info = read(frames[0])
    if not valid_packet(first_info):
        raise ValueError('INVALID_MODEL_PACKET')
    first = processing_frame(cv2.imread(str(frames[0]).replace('.json', '.rgb.png')), [1280, 720])
    binding = dict(connection=bundle['connection'], observation_pose=bundle['observation_pose'],
        T_tcp_camera_mm=bundle['T_tcp_camera_mm'], camera={k: first_info[k] for k in ('k', 'd', 'distortion_model', 'width', 'height', 'frame_id')})
    if args.model_layout:
        layout = read(args.model_layout)
        validate_frozen_layout(layout, binding, entries)
        fit = layout['model_fit']
        matrix, step, anchors = np.array(fit['bootstrap_affine']), np.array(fit['step_uv']), fit['anchors']
        centers = [None]*fit['baseline_center_count']
        expected_centers = {identity(row): np.array(row['expected_center_uv']) for row in layout['slots']}
        for row in layout['slots']:
            roi_candidate(row['roi_xyxy'], np.array([[1, 0], [0, 1], [0, 0]]))
    else:
        source, observed, anchors = [], [], []
        for ref in bundle['references']:
            row = entries[ref['slot_id']]
            anchor_layout = deepcopy(template)
            anchor = next(s for s in anchor_layout['slots'] if identity(s) == ref['slot_id'])
            anchor['roi_xyxy'] = ref['roi_xyxy_processing']
            decision = observe(first, anchor_layout, row, first_info['stamps_ns'][0])
            if not decision['recognized']:
                raise ValueError('CURRENT_ANCHOR_NOT_RECOGNIZED:'+ref['slot_id'])
            x0, y0, x1, y1 = row['roi_xyxy']
            source.append([(x0+x1)/2, (y0+y1)/2])
            observed.append(decision['center_uv'])
            anchors.append(ref['slot_id'])
        matrix = affine_model(source, observed)
        layout = deepcopy(template)
        centers = []
        for row in layout['slots']:
            row['roi_xyxy'] = roi_candidate(row['roi_xyxy'], matrix)
            # Bootstrap margins repair mapped ROI clipping without crossing cells.
            row['roi_xyxy'] = [row['roi_xyxy'][0]-4, row['roi_xyxy'][1]-4,
                               row['roi_xyxy'][2]+4, row['roi_xyxy'][3]+4]
        for row in layout['slots']:
            decision = observe(first, layout, row, first_info['stamps_ns'][0])
            if decision['recognized']: centers.append((row, decision['center_uv']))
        step, origins = row_grid(centers)
        expected_centers = {}
        for row in layout['slots']:
            expected = origins[(row['color'], row['brick_type'])]+(row['slot']-1)*step
            expected_centers[identity(row)] = expected
            row['expected_center_uv'] = expected.tolist()
            x0, y0, x1, y1 = row['roi_xyxy']
            half = np.array([(x1-x0)/2, (y1-y0)/2])
            row['roi_xyxy'] = [*np.floor(expected-half).astype(int).tolist(),
                               *np.ceil(expected+half).astype(int).tolist()]
            roi_candidate(row['roi_xyxy'], np.array([[1, 0], [0, 1], [0, 0]]))
        layout.update(schema_version='supply-rgbd-model-layout-candidate/1',
                      config_id='round3_model_candidates_25',
                      calibration_id='SHARED_TRANSFORM_CANDIDATE_NOT_INDEPENDENTLY_VERIFIED',
                      layout_status='OBSERVATION_CANDIDATE_NOT_FOR_EXECUTION', execution_allowed=False)
        layout['template_source_evidence'] = layout.pop('source_evidence', {})
        layout['source_evidence'] = dict(capture_source=str(args.capture.resolve()),
            model_frame=frames[0].name, physical_center_ground_truth=False)
        layout['model_binding'] = binding
        layout['model_fit'] = dict(bootstrap_affine=matrix.tolist(), step_uv=step.tolist(),
            anchors=anchors, baseline_center_count=len(centers),
            capture_source=str(args.capture.resolve()), model_frame=frames[0].name)
    write(args.output/'layout.candidate.json', layout)
    transform = pose_matrix(before['posx']) @ np.asarray(bundle['T_tcp_camera_mm'])
    results, overlay = [], first.copy()
    measurements = read(args.geometry)['reported_dimensions']
    for row in layout['slots']:
        slot_id = identity(row)
        expected = expected_centers[slot_id]
        dims = [measurements[f'span_{n}_outer_length_mm'] for n in map(int, row['brick_type'].split('x')[:2])]
        samples = []
        for meta in frames[1:]:
            info = read(meta)
            sample = dict(frame=meta.name, recognized=False, surface_available=False)
            if not valid_packet(info) or any(info[k] != first_info[k] for k in ('k', 'd', 'distortion_model')):
                sample['reason'] = 'INVALID_OR_CHANGED_CAMERA_PACKET'
            else:
                prefix = str(meta)[:-5]
                image = processing_frame(cv2.imread(prefix+'.rgb.png'), [1280, 720])
                decision = observe(image, layout, row, info['stamps_ns'][0])
                sample.update(recognized=decision['recognized'], reason=decision['reason'])
                if decision['recognized']:
                    sample['center_uv'] = decision['center_uv']
                    sample['model_residual_px'] = float(np.linalg.norm(np.array(decision['center_uv'])-expected))
                    try:
                        point = surface_point(cv2.imread(prefix+'.depth-mm.png', -1), info, decision, [1280, 720])
                        sample.update(point, surface_available=True)
                        sample['surface_center_base_candidate_mm'] = (transform @ np.r_[point['surface_center_camera_mm'], 1])[:3].tolist()
                        sides = sorted(cv2.minAreaRect(np.array(decision['contour_uv'], np.float32))[1])
                        expected_sides = np.array(sorted(dims))*(info['k'][0]+info['k'][4])/(4*point['depth_mm'])
                        sample['outline_to_frontal_dimension_ratio'] = (np.array(sides)/expected_sides).tolist()
                    except ValueError as exc:
                        sample['reason'] = str(exc)
            samples.append(sample)
        recognized = [s for s in samples if s['recognized']]
        surfaces = [s for s in samples if s['surface_available']]
        reasons = []
        if len(recognized) != len(samples): reasons.append('VISION_OR_ROI_REVIEW')
        if any(s['recognized'] and not s['surface_available'] or s['reason'] == 'INVALID_OR_CHANGED_CAMERA_PACKET' for s in samples):
            reasons.append('DEPTH_OR_PACKET_REACQUIRE')
        if recognized and max(s['model_residual_px'] for s in recognized) > args.review_residual_px:
            reasons.append('MODEL_GEOMETRY_REVIEW_BEFORE_ADDITIONAL_TEACHING')
        if surfaces and max(s['patch_spread_mm'] for s in surfaces) > args.review_spread_mm:
            reasons.append('DEPTH_SURFACE_REVIEW')
        if any(not .7 <= ratio <= 1.3 for s in surfaces for ratio in s['outline_to_frontal_dimension_ratio']):
            reasons.append('OUTLINE_DIMENSION_OR_PERSPECTIVE_REVIEW')
        result = dict(slot_id=slot_id, roi_xyxy_processing=row['roi_xyxy'],
            expected_center_uv=expected.tolist(), model_anchor=slot_id in anchors,
            outer_dimensions_mm=dims, model_frame_excluded_from_audit=True,
            audit_frames=len(samples), recognized_frames=len(recognized), valid_depth_frames=len(surfaces),
            review_reasons=reasons, status='REVIEW_REQUIRED' if reasons else 'OBSERVATION_CONSISTENT_ONLY',
            pickup_pose_candidate=None, runtime_reference_accepted=False,
            independently_verified=False, execution_allowed=False, samples=samples)
        if surfaces:
            points = np.array([s['surface_center_base_candidate_mm'] for s in surfaces])
            result.update(surface_center_base_candidate_median_mm=np.median(points, axis=0).tolist(),
                observed_depth_range_mm=[min(s['depth_mm'] for s in surfaces), max(s['depth_mm'] for s in surfaces)],
                surface_point_range_xyz_mm=np.ptp(points, axis=0).tolist())
        results.append(result)
        x0, y0, x1, y1 = row['roi_xyxy']
        color = (0, 0, 255) if reasons else (0, 220, 0)
        cv2.rectangle(overlay, (x0, y0), (x1, y1), color, 1)
        cv2.putText(overlay, str(row['slot']), (x0, y0+12), cv2.FONT_HERSHEY_SIMPLEX, .4, color, 1)
    sources = [args.layout, args.references, args.geometry, args.capture/'capture.json', *frames,
               *sorted(args.capture.glob('frame-*.rgb.png')), *sorted(args.capture.glob('frame-*.depth-mm.png'))]
    if args.model_layout: sources.append(args.model_layout)
    report = dict(frozen_model_reused=args.model_layout is not None, schema_version='supply-rgbd-slot-model-audit/1',
        status='OFFLINE_CANDIDATES_ONLY_NOT_RUNTIME_PROFILE', physical_commands=0,
        model_basis='THREE_ANCHOR_BOOTSTRAP_THEN_ROBUST_VISUAL_ROW_GRID_FROM_FIRST_FRAME',
        visual_grid_step_uv=step.tolist(), baseline_center_count=len(centers),
        baseline_fitting_is_not_independent_accuracy_validation=True,
        model_frame=layout['model_fit']['model_frame'], model_capture=layout['model_fit']['capture_source'],
        audit_capture=str(args.capture.resolve()), audit_first_frame_excluded=frames[0].name,
        anchor_slots=anchors, affine_matrix=matrix.tolist(),
        review_thresholds_only=dict(residual_px=args.review_residual_px, patch_spread_mm=args.review_spread_mm),
        frontal_dimension_ratio_review_range=[.7, 1.3],
        dimension_check_limitation='Frontal approximation; perspective/side visibility may require ROI review, not re-teaching.',
        thresholds_are_execution_acceptance_limits=False, input_size=[1280, 720],
        processing='resize_640x360_pad_top_bottom_60', slots=results,
        observation_consistent_slots=[r['slot_id'] for r in results if not r['review_reasons']],
        additional_review_slots=[dict(slot_id=r['slot_id'], reasons=r['review_reasons']) for r in results if r['review_reasons']],
        manual_teaching_policy='Review ROI/model/depth first; only unresolved physical correspondence needs teaching.',
        source_sha256={str(p.resolve()): sha256(p.read_bytes()).hexdigest() for p in sources},
        assembly_xy_correction_enabled=False, runtime_config_changed=False,
        independent_displacements_tested=False, occupancy_or_empty_verified=False)
    write(args.output/'report.json', report)
    if not cv2.imwrite(str(args.output/'overlay.png'), overlay): raise RuntimeError('OVERLAY_WRITE_FAILED')
    print(json.dumps(dict(output=str(args.output), slots=len(results),
        observation_consistent=len(report['observation_consistent_slots']),
        review_required=len(report['additional_review_slots']), physical_commands=0), ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model-layout', type=Path, help='Reuse fixed candidate ROIs and centers; never refit from audit frames')
    parser.add_argument('--layout', type=Path, default=ROOT/'settings/supply_sequence_20261014/opencv_stud_layout.json')
    parser.add_argument('--references', type=Path, default=ROOT/'settings/round3_supply_rgbd_20261015/reference-bundle.candidate.json')
    parser.add_argument('--geometry', type=Path, default=ROOT.parent/'planning_trial/measurements/round2_geometry.operator_20261013.json')
    parser.add_argument('--review-residual-px', type=float, default=3.)
    parser.add_argument('--review-spread-mm', type=float, default=4.)
    args = parser.parse_args()
    if not all(np.isfinite(x) and x > 0 for x in (args.review_residual_px, args.review_spread_mm)):
        parser.error('review thresholds must be finite and positive')
    build(args)


if __name__ == '__main__':
    main()
