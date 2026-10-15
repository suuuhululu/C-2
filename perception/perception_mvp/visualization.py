"""Color calibration aid only: no instance labels, brick type, layer or Observed."""
import json
from pathlib import Path
from copy import deepcopy

import cv2
import numpy as np

from .rgbd_io import load_frame
from .contracts import validate_block, placement_key, footprint
from .depth_grid import validate_geometry


def freeze_overlay_states(current_blocks, expected_blocks, version_context, *, assembly_anchor=None):
    """Copy Backend-owned state once per bundle; None is not an empty board.

    version_context is opaque D metadata, not a new common JSON contract.
    With assembly_anchor, expected_blocks must be ORIGINAL design coordinates.
    Without it, Backend Expected is already in board coordinates. Current always
    contains actual board placements and is never translated a second time.
    """
    for blocks in (current_blocks, expected_blocks):
        if blocks is not None:
            for block in blocks:
                validate_block(block)
    if assembly_anchor is not None and expected_blocks is not None:
        expected_blocks = assembly_anchor.translate_design(expected_blocks)
    return deepcopy({"current": current_blocks, "expected": expected_blocks,
                     "version_context": version_context})


def render_state_overlay(rgb, snapshot, projection, *, stopped, projection_valid,
                         hidden_reason=None, alpha=.08, labels=None):
    """Invalid projection hides guidance rather than drawing invented geometry."""
    try:
        return _render_state_overlay(rgb, snapshot, projection, stopped=stopped,
            projection_valid=projection_valid, hidden_reason=hidden_reason, alpha=alpha, labels=labels)
    except (ValueError, KeyError, TypeError, np.linalg.LinAlgError, cv2.error) as error:
        if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or not rgb.size:
            raise
        output = rgb.copy()
        cv2.putText(output, "Overlay hidden: invalid projection/state", (8,22),
                    cv2.FONT_HERSHEY_SIMPLEX, .5, (255,80,80), 1)
        return output, {"overlay_visible": False, "reason": str(error), "guidance_only": True}


def _render_state_overlay(rgb, snapshot, projection, *, stopped, projection_valid,
                          hidden_reason=None, alpha=.08, labels=None):
    """Return live RGB guidance + separate display diagnostics, never Observed.

    projection: actual camera_to_board, RGB intrinsics, measured grid_origin_m
    (stud-0 center), stud_pitch_m and four or five measured top_heights_m. Caller verifies
    View/pose/calibration freshness; aligned-depth intrinsics must NOT substitute
    for RGB intrinsics. Footprints are stud-cell guidance, not brick dimensions.
    Volumes span consecutive measured layer levels (first layer starts at zero).
    Optional stud_height_m adds schematic studs; it is never inferred from RGB.
    """
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or not rgb.size:
        raise ValueError("actual nonempty uint8 RGB required")
    if type(stopped) is not bool or type(projection_valid) is not bool or not 0 < alpha < 1:
        raise ValueError("explicit stop/projection flags and opacity required")
    output = rgb.copy()
    reason = hidden_reason
    if not stopped:
        reason = "camera_moving"
    elif not projection_valid or projection is None:
        reason = reason or "projection_unverified"
    elif snapshot is None or snapshot["current"] is None or snapshot["expected"] is None:
        reason = "backend_state_missing"
    if reason:
        cv2.putText(output, "Overlay hidden: " + str(reason), (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 80, 80), 1)
        return output, {"overlay_visible": False, "reason": reason, "guidance_only": True}
    intr = projection["rgb_intrinsics"]
    transform = validate_geometry(1., intr, projection["camera_to_board"])
    if intr["model"] not in ("none", "brown_conrady"):
        raise ValueError("RGB projection needs none or Brown-Conrady distortion")
    origin = np.asarray(projection["grid_origin_m"], float)
    heights = np.asarray(projection["top_heights_m"], float)
    pitch = projection["stud_pitch_m"]
    if (origin.shape != (2,) or heights.shape not in ((4,), (5,)) or
            not np.isfinite(origin).all() or not np.isfinite(heights).all() or
            heights[0] <= 0 or np.any(np.diff(heights) <= 0) or
            not np.isfinite(pitch) or pitch <= 0):
        raise ValueError("measured grid origin/pitch and layer heights required")
    stud_height = float(projection.get("stud_height_m", 0.))
    if (not np.isfinite(stud_height) or stud_height < 0 or
            stud_height >= np.min(np.diff(np.r_[0., heights]))):
        raise ValueError("stud height must fit every measured layer interval")
    camera_from_board = np.linalg.inv(transform)
    matrix = np.array([[intr["fx"], 0, intr["cx"]], [0, intr["fy"], intr["cy"]], [0, 0, 1.]])
    distortion = np.zeros(5) if intr["model"] == "none" else np.asarray(intr["coefficients"])
    current_keys = {placement_key(b) for b in snapshot["current"]}
    skipped, faces = [], []
    block_rgb = {'yellow': (255, 220, 0), 'blue': (30, 100, 255), 'red': (255, 45, 45)}
    for name, edge_color in (("current", (255, 100, 220)), ("expected", (80, 255, 100))):
        for block in snapshot[name]:
            validate_block(block)
            color = block_rgb[block['color']]
            # Shared placements retain Current's colour instead of being tinted twice.
            if name == "expected" and placement_key(block) in current_keys:
                continue
            cells = footprint(block)
            x0, x1 = min(c[0] for c in cells) - .5, max(c[0] for c in cells) + .5
            y0, y1 = min(c[1] for c in cells) - .5, max(c[1] for c in cells) + .5
            level = block["layer"] - 1
            if level >= len(heights):
                raise ValueError("missing measured height for requested overlay layer")
            bottom = 0. if level == 0 else heights[level - 1] - stud_height
            top = heights[level] - stud_height
            corners = [(origin[0] + x * pitch, origin[1] + y * pitch)
                       for x,y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
            surfaces = _block_surfaces(corners, bottom, top, cells,
                                       origin, pitch, stud_height)
            projected = []
            behind_camera = False
            for surface, shade in surfaces:
                camera = (camera_from_board @ np.c_[surface, np.ones(len(surface))].T).T[:, :3]
                if np.any(camera[:, 2] <= 0):
                    projected = []
                    behind_camera = True
                    break
                normal = np.cross(camera[1]-camera[0], camera[2]-camera[0])
                if np.dot(normal, camera.mean(axis=0)) >= 0:
                    continue
                pixels, _ = cv2.projectPoints(camera, np.zeros(3), np.zeros(3), matrix, distortion)
                pixels = pixels.reshape(-1, 2)
                if not np.isfinite(pixels).all() or np.max(np.abs(pixels)) > 1e7:
                    raise ValueError("invalid projected pixels")
                projected.append((float(camera[:,2].mean()), np.rint(pixels).astype(np.int32), shade))
            if behind_camera:
                skipped.append({"state": name, "reason": "behind_camera"})
                continue
            faces.extend((depth, polygon, tuple(int(c*shade) for c in color),
                          edge_color, 1) for depth,polygon,shade in projected)
    # Painter ordering preserves perspective; transparent guidance is intentionally
    # see-through and does not assert real-image occlusion or observed occupancy.
    for _, polygon, fill, edge, thickness in sorted(faces, key=lambda face: -face[0]):
        x,y,w,h = cv2.boundingRect(polygon)
        x0,y0 = max(0,x), max(0,y)
        x1,y1 = min(output.shape[1],x+w), min(output.shape[0],y+h)
        if x0 >= x1 or y0 >= y1:
            continue
        region = output[y0:y1,x0:x1]
        tinted = region.copy()
        cv2.fillConvexPoly(tinted, polygon - [x0,y0], fill)
        region[:] = cv2.addWeighted(tinted, alpha, region, 1 - alpha, 0)
        cv2.polylines(output, [polygon], True, edge, thickness)
    labels = labels or ('Current (confirmed)', 'Expected (THIS check)')
    for index, (label, color) in enumerate(zip(labels, ((255,100,220), (80,255,100)))):
        cv2.putText(output, label, (8, 22 + index * 20), cv2.FONT_HERSHEY_SIMPLEX, .45, color, 1)
    cv2.putText(output, 'Faces: block color | Edges: comparison state', (8, 62),
                cv2.FONT_HERSHEY_SIMPLEX, .4, (180,180,180), 1)
    return output, {"overlay_visible": True, "reason": None, "guidance_only": True,
                    "skipped": skipped, "render_mode": "3d_volume",
                    "rendered_faces": len(faces),
                    "version_context": deepcopy(snapshot["version_context"])}


def render_comparison_overlay(rgb, payload, *, view, frame_stamp_ns, stopped,
                              hand_clear, mode='auto'):
    """Local display input with explicit frame/check context, never Robot permission.

    payload contains state from comparison_display_state(), projection, view_id,
    frame_stamp_ns and phase. Producer must supply the ACTUAL comparison frame.
    """
    try:
        state = payload['state']
        reason = None
        if payload['phase'] != 'COMPARISON' or not state['check_id']:
            reason = 'not_comparison_phase'
        elif payload['view_id'] != view or payload['frame_stamp_ns'] != frame_stamp_ns:
            reason = 'comparison_frame_mismatch'
        elif not hand_clear:
            reason = 'hand_or_safety_unconfirmed'
        elif payload.get('height_reference') != 'board_flat_surface':
            reason = 'board_flat_height_reference_unconfirmed'
        if reason:
            return render_state_overlay(rgb, None, None, stopped=stopped,
                                        projection_valid=False, hidden_reason=reason)
        if mode == 'auto':
            stage = state.get('display_stage')
            if stage == 'CONFIRMED' and state.get('comparison') in ('MATCH', 'MISMATCH'):
                mode = 'changes'
            elif stage in ('OBSERVING', 'UNOBSERVABLE'):
                mode = 'target'
            else:
                raise ValueError('automatic overlay stage unavailable')
        if mode == 'changes':
            before = state['previous_current']
            snapshot = freeze_overlay_states(None if before is None else before['blocks'],
                None if state['current'] is None else state['current']['blocks'], state)
            labels = ('Previous confirmed Current', 'Current after comparison')
        elif mode == 'target':
            snapshot = freeze_overlay_states(None if state['current'] is None else state['current']['blocks'],
                                              state['expected'], state)
            labels = ('Current (confirmed)', 'Expected (THIS check)')
        else:
            raise ValueError('unknown overlay mode')
        output, report = render_state_overlay(rgb, snapshot, payload.get('projection'), stopped=stopped,
            projection_valid=payload.get('projection_valid') is True,
            hidden_reason=reason, labels=labels)
        if report['overlay_visible'] and state.get('comparison') in ('MISMATCH', 'UNOBSERVABLE'):
            text = 'WARNING: '+state['comparison']
            difference = state.get('difference') or {}
            for missing in difference.get('missing', []):
                actual = next((b for b in difference.get('unexpected', []) if
                    all(b[k] == missing[k] for k in ('x','y','layer','brick_type','orientation_deg')) and
                    b['color'] != missing['color']), None)
                if actual:
                    text += f" | ({missing['x']},{missing['y']}) L{missing['layer']}: expected {missing['color']} / actual {actual['color']}"
                    break
            cv2.putText(output, text, (8, 85), cv2.FONT_HERSHEY_SIMPLEX, .5, (255,40,40), 1)
            report['comparison_warning'] = text
        return output, report
    except (KeyError, TypeError, ValueError) as error:
        return render_state_overlay(rgb, None, None, stopped=stopped, projection_valid=False,
                                    hidden_reason='comparison_input_invalid: '+str(error))


def projected_color_test(rgb, block, projection):
    """Local RGB color probe only. Does not verify identity, Grid, layer or assembly.

    Interior footprint (65%), >=20% colored coverage and >=70% dominant colored
    vote are explicit TRIAL values, not accepted deployment accuracy criteria.
    """
    from .opencv_live import color_mask
    validate_block(block)
    cells = footprint(block)
    xs, ys = [c[0] for c in cells], [c[1] for c in cells]
    center = np.array([(min(xs)+max(xs))/2, (min(ys)+max(ys))/2])
    half = np.array([max(xs)-min(xs)+1, max(ys)-min(ys)+1])*.5*.65
    origin, pitch = np.asarray(projection['grid_origin_m']), projection['stud_pitch_m']
    xy = np.array([center+half*[a,b] for a,b in [(-1,-1),(1,-1),(1,1),(-1,1)]])*pitch+origin
    z = projection['top_heights_m'][block['layer']-1]-projection.get('stud_height_m',0.)
    points = np.c_[xy, np.full(4,z), np.ones(4)]
    camera = (np.linalg.inv(projection['camera_to_board'])@points.T).T[:,:3]
    if np.any(camera[:,2] <= 0):
        return dict(status='UNKNOWN',actual=None,reason='behind_camera')
    intr = projection['rgb_intrinsics']
    k = np.array([[intr['fx'],0,intr['cx']],[0,intr['fy'],intr['cy']],[0,0,1.]])
    distortion = np.zeros(5) if intr['model']=='none' else np.asarray(intr['coefficients'])
    pixels = cv2.projectPoints(camera,np.zeros(3),np.zeros(3),k,distortion)[0].reshape(-1,2)
    if not np.isfinite(pixels).all() or np.any(pixels < 0) or np.any(pixels >= [rgb.shape[1],rgb.shape[0]]):
        return dict(status='UNKNOWN',actual=None,reason='projected_region_outside_image')
    region = np.zeros(rgb.shape[:2],np.uint8)
    cv2.fillConvexPoly(region,np.rint(pixels).astype(np.int32),1)
    hsv = cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    counts = {color:int(np.count_nonzero(color_mask(hsv,color)&region.astype(bool)))
              for color in ('yellow','blue','red')}
    total = sum(counts.values())
    coverage = total/max(1,int(region.sum()))
    dominant = max(counts,key=counts.get)
    confidence = counts[dominant]/max(1,total)
    actual = dominant if coverage >= .2 and confidence >= .7 else None
    return dict(status='UNKNOWN' if actual is None else 'MATCH' if actual==block['color'] else 'MISMATCH',
                actual=actual,expected=block['color'],counts=counts,
                coverage=coverage,dominant_fraction=confidence,trial_only=True)


def _block_surfaces(corners, bottom, top, cells, origin, pitch, stud_height):
    """Guidance volume only; optional stud radius is schematic, not metrology."""
    lower = np.array([[x,y,bottom] for x,y in corners])
    upper = np.array([[x,y,top] for x,y in corners])
    surfaces = [(upper, 1.)]
    for i in range(4):
        j = (i+1) % 4
        surfaces.append((np.array([lower[i],lower[j],upper[j],upper[i]]), .75))
    if stud_height:
        angles = np.linspace(0., 2*np.pi, 16, endpoint=False)
        ring = np.column_stack((np.cos(angles), np.sin(angles))) * pitch*.28
        for x,y,_ in sorted(cells):
            xy = ring + origin + np.array([x,y])*pitch
            base = np.c_[xy, np.full(16, top)]
            cap = np.c_[xy, np.full(16, top+stud_height)]
            surfaces.append((cap, 1.))
            for i in range(16):
                j = (i+1) % 16
                surfaces.append((np.array([base[i],base[j],cap[j],cap[i]]), .85))
    return surfaces


def aligned_change_mask(previous_rgb, current_rgb, current_to_previous, *,
                        previous_view, current_view, alignment_verified, threshold):
    """Measured same-View homography only; changes are NOT completion/coverage proof."""
    if previous_view != current_view or alignment_verified is not True:
        raise ValueError("verified same-View alignment required")
    if (previous_rgb.dtype != np.uint8 or current_rgb.dtype != np.uint8 or
            previous_rgb.shape != current_rgb.shape or previous_rgb.ndim != 3 or
            previous_rgb.shape[2] != 3 or not previous_rgb.size):
        raise ValueError("matching actual RGB images required")
    matrix = np.asarray(current_to_previous, float)
    if (matrix.shape != (3,3) or not np.isfinite(matrix).all() or
            abs(np.linalg.det(matrix)) < 1e-12 or not np.isfinite(threshold) or not 0 < threshold <= 255):
        raise ValueError("actual nonsingular alignment and measured pixel threshold required")
    height, width = previous_rgb.shape[:2]
    aligned = cv2.warpPerspective(current_rgb, matrix, (width,height))
    valid = cv2.warpPerspective(np.ones((height,width), np.uint8), matrix, (width,height),
                               flags=cv2.INTER_NEAREST) > 0
    difference = cv2.absdiff(cv2.cvtColor(previous_rgb, cv2.COLOR_RGB2GRAY),
                            cv2.cvtColor(aligned, cv2.COLOR_RGB2GRAY))
    return (valid & (difference > threshold)), valid


def render_observation(rgb, detections, candidates):
    """Actual model masks and actual Depth/Grid outcomes; no placeholder layer/confidence."""
    if len(detections) != len(candidates):
        raise ValueError("detections and measured candidates must correspond")
    output = rgb.copy()
    for (mask, name, confidence), candidate in zip(detections, candidates):
        color = (255, 255, 0) if name.startswith("yellow_") else (0, 128, 255)
        output[mask] = ((output[mask].astype(np.uint16) + np.array(color, np.uint16)) // 2).astype(np.uint8)
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(output, contours, -1, color, 2)
        status = candidate["status"]
        if status == "CANDIDATE":
            details = f"center={candidate['grid_center_stud']} layer={candidate['measured_layer_index'] + 1}"
        else:
            details = candidate["reason"]
        ys, xs = np.nonzero(mask)
        if xs.size:
            cv2.putText(output, f"{name} YOLO={confidence:.2f} {status} {details}",
                        (int(xs.min()), max(18, int(ys.min()) - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, .45, color, 1)
    return output


def color_masks(rgb, settings):
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or not rgb.size:
        raise ValueError("nonempty uint8 RGB image required")
    if settings["threshold_status"] not in ("temporary_test", "validated"):
        raise ValueError("explicit threshold status required")
    ranges = settings["hsv_ranges"]
    if set(ranges) != {"yellow", "blue"}:
        raise ValueError("yellow and blue HSV ranges required")
    bounds = {}
    for color, limits in ranges.items():
        if set(limits) != {"lower", "upper"}:
            raise ValueError("each HSV range requires lower and upper")
        lower, upper = limits["lower"], limits["upper"]
        if (len(lower) != 3 or len(upper) != 3 or
                any(type(v) is not int for v in lower + upper)):
            raise ValueError("HSV limits require three integers")
        if any(not 0 <= lo <= hi <= maximum
               for lo, hi, maximum in zip(lower, upper, (179, 255, 255))):
            raise ValueError("invalid OpenCV HSV limits")
        bounds[color] = (np.array(lower, np.uint8), np.array(upper, np.uint8))
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    return {color: cv2.inRange(hsv, lower, upper) for color, (lower, upper) in bounds.items()}


def save_color_review(recording, settings, output):
    """Compare unfiltered masks with original RGB; never modify recording arrays."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    rgb, _, _, metadata = load_frame(recording)
    masks = color_masks(rgb, settings)
    overlay = rgb.copy()
    for color, display_color in (("yellow", (255, 255, 0)), ("blue", (0, 0, 255))):
        selected = masks[color] > 0
        overlay[selected] = ((rgb[selected].astype(np.uint16) +
                              np.array(display_color, np.uint16)) // 2).astype(np.uint8)
    mask_panels = [cv2.cvtColor(masks[color], cv2.COLOR_GRAY2RGB) for color in ("yellow", "blue")]
    panels = [rgb, *mask_panels, overlay]
    comparison = np.concatenate(panels, axis=1)
    for index, label in enumerate(("Original RGB", "Yellow mask", "Blue mask", "Overlay")):
        cv2.putText(comparison, label, (index * rgb.shape[1] + 5, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 0, 0), 1)
    report = {"purpose": "color_review_only", "scene_id": metadata["scene_id"],
              "view_id": metadata["view_id"], "captured_at": metadata["captured_at"],
              "mode": metadata["mode"], "settings": settings,
              "candidate_pixels": {color: int(np.count_nonzero(mask)) for color, mask in masks.items()},
              "overlap_pixels": int(np.count_nonzero((masks["yellow"] > 0) & (masks["blue"] > 0))),
              "limitations": ["not_instance_masks", "no_brick_type_or_layer",
                              "not_verified_regions", "human_label_review_required"]}
    encoded = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)
    output.mkdir(parents=True, exist_ok=False)
    images = {"original.png": cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
              "comparison.png": cv2.cvtColor(comparison, cv2.COLOR_RGB2BGR),
              **{f"{color}_mask.png": mask for color, mask in masks.items()}}
    for name, image in images.items():
        if not cv2.imwrite(str(output / name), image):
            raise OSError(f"failed to write {output / name}")
    (output / "color_review.json").write_text(encoded, encoding="utf-8")
    return report
