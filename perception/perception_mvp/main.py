"""Real capture and recorded RGB-D inference; no synthetic fixtures or robot control."""
import argparse
import json
from copy import deepcopy
from pathlib import Path

import yaml

from .rgbd_io import capture, load_frame, stream_v0
from .rgbd_io import begin_cycle_archive, save_cycle_view, write_cycle_json
from .yolo_pipeline import infer_masks, check_labels, train_or_evaluate
from .depth_grid import process_saved_bundle
from .backend_adapter import deliver_observed
from .contracts import validate_block
from .contracts import candidate_to_block
from .depth_grid import process_saved
from .runtime_log import progress
from .backend_adapter import build_observed
from .view_roles import AUTHORITY_VIEW, build_role_view, finalize

DEFAULT_CYCLE_OUTPUT = Path(__file__).resolve().parent.parent / "recordings" / "observation_cycles"


def validate_cycle_target(context):
    kind = context.get('check_kind', 'STEP')  # Existing ASSEMBLY callers remain STEP.
    if kind == 'STEP':
        validate_block(context['target_after'])
    elif kind not in ('INITIAL', 'FINAL') or context.get('target_after') is not None:
        raise ValueError('INITIAL/FINAL require explicit kind and null target_after')
    return kind


def make_inspection_observer(gate, hand_detector, hand_stream, capture_view,
                             weights, calibration, config, detector_confidence, *,
                             confirm_view, workflow_valid, bundle_valid,
                             frame_sink=None, view_sink=None, output_root=None,
                             start_condition=None, is_stopped=None):
    """B observe(context, is_active) callable for connect_inspection.

    capture_view(manifest, view, is_active) must supply actual saved RGB-D and
    occupancy evidence. Controller/Camera hooks are required, never simulated here.
    D owns completion gestures: the default is STOPPED_CLEAR for all check kinds.
    Explicit HUMAN_ASSEMBLY remains available for standalone hand-driven callers.
    hand_stream=None selects ROS V0 hand reception and requires is_stopped(view).
    """
    def observe(context, is_active):
        manifest = deepcopy(context)
        # D requests inspection after the gesture or completed robot operation.
        # Another mandatory hand entry would block this already completed step.
        condition = (start_condition(deepcopy(context)) if start_condition is not None else
                     'STOPPED_CLEAR')
        if condition not in ('HUMAN_ASSEMBLY', 'STOPPED_CLEAR'):
            raise ValueError('explicit HUMAN_ASSEMBLY or STOPPED_CLEAR start condition required')
        manifest['start_condition'] = condition
        current = manifest.get('current')
        manifest.update(mode='REAL', view_order=['V0', 'D1', 'D3'],
                        previous_accepted_blocks=deepcopy(current['blocks']) if current is not None else [],
                        target_after=manifest.get('target_after'))
        valid = lambda: is_active() is True and workflow_valid() is True
        stream_factory = hand_stream
        if stream_factory is None:
            if not callable(is_stopped):
                raise ValueError('ROS hand reception requires actual is_stopped(View) hook')
            from .ros_capture import stream_ros_hand
            stream_factory = lambda: stream_ros_hand(is_active, is_stopped,
                context=manifest, workflow_valid=workflow_valid)
        return run_observation_cycle(gate, hand_detector, stream_factory,
            lambda view: capture_view(deepcopy(manifest), view, is_active), manifest,
            weights, calibration, config, detector_confidence, callback=lambda value: None,
            confirm_view=confirm_view, workflow_valid=valid, bundle_valid=bundle_valid,
            frame_sink=frame_sink, view_sink=view_sink, output_root=output_root)
    return observe


def read_json(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text) if path.suffix in (".yaml", ".yml") else json.loads(text)


def run_observation_cycle(gate, hand_detector, hand_stream, capture_view, manifest,
                         weights, calibration, config, detector_confidence, *,
                         callback, confirm_view, workflow_valid, bundle_valid,
                         frame_sink=None, view_sink=None, output_root=None):
    """One normal ASSEMBLY cycle, including actual stopped-V0 hand waiting.

    hand_stream is a factory opened after V0 stop confirmation. Controller hooks
    remain responsible for safety and motion; this function sends no Robot command.
    Runtime inputs/context are frozen before waiting and not rebound to a new check.
    """
    from .hand_cycle import wait_for_hand_ready
    context = deepcopy(manifest)
    if context.get("mode") != "REAL" or context.get("view_order") != ["V0", "D1", "D3"]:
        raise ValueError("explicit REAL V0 -> D1 -> D3 cycle required")
    check, seq = context.get("check_id"), context.get("observation_seq")
    if not isinstance(check, str) or not check or type(seq) is not int or seq < 0:
        raise ValueError("Backend check and bundle-start sequence required")
    validate_cycle_target(context)
    calibration, config = deepcopy(calibration), deepcopy(config)

    def valid():
        return workflow_valid() is True and bundle_valid() is True

    try:
        progress(context, '이동 요청·도착 대기', view='V0')
        if not valid() or confirm_view("V0") is not True or not valid():
            raise RuntimeError("safe stopped V0 and active context required")
        progress(context, '정지 확인', view='V0')
        condition = context.get('start_condition', 'HUMAN_ASSEMBLY' if
                                context.get('check_kind', 'STEP') == 'STEP' else 'STOPPED_CLEAR')
        if condition not in ('HUMAN_ASSEMBLY', 'STOPPED_CLEAR'):
            raise ValueError('unknown observation start condition')
        if condition == 'HUMAN_ASSEMBLY':
            gate.reset_for_reobservation()
        else:
            gate.reset_for_reobservation(require_entry=False)
        hand_detector.reset()
        progress(context, '손 조건·영상 안정 확인 대기', view='V0', start_condition=condition)
        last_hand_state = [None]
        def hand_status(rgb, depth, event, quality):
            state = (event.get('state'), event.get('reason'), event.get('observation_allowed'))
            if state != last_hand_state[0]:
                last_hand_state[0] = state
                progress(context, '손 조건·안정 상태', view='V0', state=state[0],
                         reason=state[1], ready=state[2])
            if frame_sink is not None:
                frame_sink(rgb, depth, event, quality)
        wait_for_hand_ready(hand_stream(), hand_detector, gate, valid, frame_sink=hand_status)
        progress(context, '손 조건·영상 안정 확인 완료', view='V0')
        if not valid():
            raise RuntimeError("observation request cancelled after hand waiting")
        return observe_cycle(gate, capture_view, context, weights, calibration, config,
            detector_confidence, callback=callback, confirm_view=confirm_view,
            bundle_valid=valid, view_sink=view_sink, output_root=output_root)
    except Exception as error:
        progress(context, '관측 시작 실패·중단', view=getattr(error, 'view', None), reason=str(error))
        gate.state = "HOLD"
        raise


def observe_cycle(gate, capture_view, manifest, weights, calibration, config,
                  detector_confidence, *, callback, confirm_view, bundle_valid,
                  view_sink=None, output_root=None):
    """One normal or recheck bundle. Hooks are internal, not D transport DTOs.

    confirm_view waits for actual Controller stop/safety and image stability.
    capture_view captures ONE View; processing finishes before requesting the next.
    bundle_valid checks active context, scene continuity, STOP and interruption,
    including the agreed non-V0 policy. It is not replaced by stale V0 hand data.
    No movement commands, return-to-V0 step or next-Step decision is made here.
    """
    context, calibration, config = deepcopy(manifest), deepcopy(calibration), deepcopy(config)
    order = context["view_order"]
    if order != ["V0", "D1", "D3"]:
        raise ValueError("observation order must be V0 -> D1 -> D3")
    if context["mode"] != "REAL":
        raise ValueError("explicit REAL cycle required")
    check, seq = context["check_id"], context["observation_seq"]
    if not isinstance(check, str) or not check or type(seq) is not int or seq < 0:
        raise ValueError("Backend check and bundle-start sequence required")
    kind = validate_cycle_target(context)
    views, measurements, scenes = [], [], set()
    role_notes, role_gating = {}, []
    def require_valid():
        if bundle_valid() is not True:
            raise RuntimeError("bundle interrupted or continuity/safety unverified")
    archive = None
    try:
        gate.begin_observation()
        require_valid()
        archive = begin_cycle_archive(DEFAULT_CYCLE_OUTPUT if output_root is None else output_root,
            context, calibration, config, weights, detector_confidence)
        for view_id in order:
            require_valid()
            progress(context, '이동 요청·도착 대기', view=view_id)
            if confirm_view(view_id) is not True:
                raise RuntimeError("actual stop, safety and image stability required")
            require_valid()
            progress(context, '정지 확인', view=view_id)
            progress(context, '관측 중·RGB-D 수신 시작', view=view_id)
            record = capture_view(view_id)
            rgb, raw, aligned, meta = load_frame(record["directory"])
            progress(context, 'RGB-D 수신 완료', view=view_id)
            if (meta["mode"] != "REAL" or meta["view_id"] != view_id or
                    (meta.get("check_id"), meta.get("observation_seq")) != (check, seq) or
                    meta.get("calibration_id") != calibration["calibration_id"]):
                raise ValueError("captured View/context/calibration mismatch")
            scenes.add(meta["scene_id"])
            if len(scenes) != 1:
                raise ValueError("scene changed within bundle")
            regions = record.get("verified_regions", [])
            if regions and not record.get("verification_basis"):
                raise ValueError("verified regions require actual occupancy evidence")
            require_valid()
            if view_id == 'V0':
                gate.freeze_capture()
            view_directory = save_cycle_view(archive, view_id, rgb, raw, aligned,
                                            meta, record["directory"])
            write_cycle_json(view_directory / "capture_evidence.json", dict(
                verified_regions=regions, verification_basis=record.get("verification_basis")))
            progress(context, '분석 시작', view=view_id)
            detections = infer_masks(rgb, weights, detector_confidence)
            result = process_saved(record["directory"], detections, calibration, config)
            # Which measured evidence a View may contribute is decided by its role (view_roles).
            write_cycle_json(view_directory / 'measured_occupancy_evidence.json', dict(
                verified_regions=result.get('verified_regions', []),
                verification_basis=result.get('verification_basis')))
            vote_candidates = deepcopy(result['candidates'])
            for candidate in vote_candidates:
                if candidate['status'] == 'CANDIDATE':
                    candidate['block'] = candidate_to_block(candidate, config['center_to_anchor_offsets_stud'])
            unknown = any(c["status"] == "UNKNOWN" for c in result["candidates"])
            progress(context, '분석 완료·일부 후보 미확인' if unknown else '분석 완료', view=view_id,
                     detected=len(result['candidates']),
                     reasons=[c.get('reason') for c in result['candidates'] if c['status'] == 'UNKNOWN'])
            # V0 owns layers and occupied footprints; D1/D3 are auxiliary (view_roles). An UNKNOWN
            # candidate only drops itself, so one failed D1/D3 candidate no longer voids its View.
            view, notes, gating = build_role_view(
                dict(check_id=check, observation_seq=seq, calibration_id=calibration["calibration_id"]),
                dict(result, view_id=view_id), regions,
                lambda c: candidate_to_block(c, config["center_to_anchor_offsets_stud"]))
            role_notes[view_id] = notes
            role_gating += gating
            views.append(view)
            views[-1]['measured_candidates'] = vote_candidates if view_id == AUTHORITY_VIEW else []
            measurements.append(result)
            require_valid()
            partial, details = build_observed(check, seq, views,
                context["previous_accepted_blocks"], context.get("target_after"),
                scene_stable=True, check_kind=kind, vote_policy=config.get('class_vote_policy'))
            write_cycle_json(view_directory / "measurement.json", result)
            write_cycle_json(view_directory / "view_result.json", views[-1])
            write_cycle_json(view_directory / "partial_observed.json", partial)
            write_cycle_json(view_directory / "diagnostics.json", details)
            if view_sink is not None:
                view_sink(view_id, rgb, detections, deepcopy(result), partial, details)
            if view_id == "V0":
                gate.finish_observation()  # Finish while live V0 evidence is still available.
        require_valid()
        observed, diagnostics = build_observed(check, seq, views,
            context["previous_accepted_blocks"], context.get("target_after"),
            scene_stable=True, check_kind=kind, vote_policy=config.get('class_vote_policy'))
        diagnostics["source_measurements"] = measurements
        finalize(diagnostics, role_notes, role_gating)
        require_valid()
        write_cycle_json(archive / "observed.json", observed)
        write_cycle_json(archive / "diagnostics.json", diagnostics)
        require_valid()
        deliver_observed(observed, callback)
        write_cycle_json(archive / "submission.json", dict(status="CALLBACK_RETURNED",
            check_id=check, observation_seq=seq, backend_acceptance="NOT_CONFIRMED_BY_B"))
    except Exception as error:
        progress(context, '관측 실패·중단', view=getattr(error, 'view', None), reason=str(error))
        gate.state = "HOLD"
        if archive is not None:
            write_cycle_json(archive / "failure.json", dict(check_id=check,
                observation_seq=seq, status="HOLD", reason=str(error)))
        raise
    return observed, diagnostics


def inspect_cycle(session, gate, capture_view, manifest, weights, calibration, config,
                  detector_confidence, *, confirm_view, bundle_valid, view_sink=None, output_root=None):
    """Actual capture pipeline -> B Current/Expected inspection, no D wire changes.

    Caller supplies D-selected plan_id/step_id/check_id and confirmed geometry
    reference in this INTERNAL manifest. All state calls must be serialized.
    Returns a new internal result; do not feed it into legacy submit_observation.
    """
    context = deepcopy(manifest)
    check, plan, step = context["check_id"], context["plan_id"], context["step_id"]
    profile = context["geometry_reference"]
    selected = session.start(check, plan, step, geometry_reference=profile)
    context["previous_accepted_blocks"] = selected["current"]["blocks"]
    context["target_after"] = selected["target_after"]
    def valid():
        return bundle_valid() is True and session.is_active(check, plan, step)
    try:
        observed, diagnostics = observe_cycle(gate, capture_view, context, weights,
            calibration, config, detector_confidence, callback=lambda value: None,
            confirm_view=confirm_view, bundle_valid=valid, view_sink=view_sink, output_root=output_root)
        if valid() is not True:
            raise RuntimeError("inspection cancelled before Current commit")
        result = session.finish(observed, plan_id=plan, step_id=step,
                                geometry_reference=profile, issues=diagnostics["issues"])
        result["observation_evidence"] = diagnostics
        return result
    except Exception:
        session.cancel(check)
        raise


def watch_hand(settings, check_id, output):
    from .hand_cycle import HandCycle, HandDetector, monitor_hand
    if not isinstance(check_id, str) or not check_id:
        raise ValueError("Backend check_id required")
    camera, hand = settings["camera"], settings["hand"]
    missing = [f"{name}.{key}" for name, values in (("camera", camera), ("hand", hand))
               for key, value in values.items() if value is None]
    if missing:
        raise ValueError("real settings not provided: " + ", ".join(missing))
    if hand["exit_seconds"] != 3.0:
        raise ValueError("user condition requires strictly more than 3 seconds")
    detector = HandDetector(hand["weights"], hand["confidence"], hand["board_roi_v0"],
        min_valid_depth_fraction=hand["min_valid_depth_fraction"],
        stable_mean_difference=hand["stable_mean_difference"],
        image_size=hand.get("board_image_size"), board_polygon=hand.get("board_polygon_v0"))
    gate = HandCycle(hand["stable_seconds"], hand["max_frame_gap_seconds"])
    stream = stream_v0(camera["serial"], camera["width"], camera["height"], camera["fps"], camera["timeout_ms"])
    monitor_hand(stream, detector, gate, output, {"check_id": check_id})


def infer_bundle(manifest, weights, calibration, config, detector_confidence, *, callback=None,
                 preview_sink=None):
    """Local manifest is not a Backend DTO. Coverage requires independent evidence.

    Paths in a CLI manifest are resolved relative to the manifest file. Missing
    coverage stays unverified, even when YOLO detects no blocks.
    """
    check = manifest["check_id"]
    seq = manifest["observation_seq"]
    if not isinstance(check, str) or not check or type(seq) is not int or seq < 0:
        raise ValueError("Backend check and nonnegative bundle-start sequence required")
    if manifest["mode"] != "REAL":
        raise ValueError("runtime requires explicit REAL recordings")
    validate_block(manifest["target_after"])
    if type(manifest["scene_stable"]) is not bool:
        raise ValueError("scene_stable requires external boolean evidence")
    records = manifest["recordings"]
    if not isinstance(records, list) or not records:
        raise ValueError("at least one actual recording required")
    loaded = []
    view_ids = set()
    scenes = set()
    for record in records:
        rgb, _, _, meta = load_frame(record["directory"])
        if meta["mode"] != "REAL":
            raise ValueError("TEST frame cannot enter REAL runtime")
        if (meta.get("check_id"), meta.get("observation_seq")) != (check, seq):
            raise ValueError("capture check/sequence differs from manifest")
        if meta.get("calibration_id") != calibration["calibration_id"]:
            raise ValueError("capture calibration differs from requested calibration")
        if meta["view_id"] in view_ids:
            raise ValueError("duplicate View in one observation bundle")
        view_ids.add(meta["view_id"])
        scenes.add(meta["scene_id"])
        regions = record.get("verified_regions", [])
        if regions and not record.get("verification_basis"):
            raise ValueError("verified regions require independent verification_basis")
        loaded.append((record, rgb, meta, regions))
    if len(scenes) != 1:
        raise ValueError("bundle must contain one static scene")
    processed = []
    for record, rgb, _, regions in loaded:
        detections = infer_masks(rgb, weights, detector_confidence)
        processed.append({"directory": record["directory"], "detections": detections,
                          "verified_regions": regions})
    observed, diagnostics = process_saved_bundle(processed, calibration, config, check, seq,
        manifest["previous_accepted_blocks"], manifest["target_after"],
        scene_stable=manifest["scene_stable"])
    diagnostics["capture_context"] = [
        {"view_id": meta["view_id"], "captured_at": meta["captured_at"],
         "verification_basis": record.get("verification_basis"),
         "coverage_status": "externally_verified" if regions else "unverified"}
        for record, _, meta, regions in loaded]
    if preview_sink is not None:
        for (_, rgb, meta, _), record, measurements in zip(
                loaded, processed, diagnostics["source_measurements"]):
            preview_sink(meta["view_id"], rgb, record["detections"], measurements["candidates"])
    if callback is not None:
        deliver_observed(observed, callback)
    return observed, diagnostics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    camera = commands.add_parser("capture", help="Capture at externally confirmed stopped View")
    camera.add_argument("directory", type=Path)
    for key in ("serial", "scene-id", "view-id", "robot-pose", "calibration-id", "check-id"):
        camera.add_argument("--" + key, required=True)
    camera.add_argument("--mode", choices=["REAL"], required=True)
    camera.add_argument("--stopped-and-clear", action="store_true", required=True,
                        help="External confirmation only; not automatic hand/robot detection")
    for key in ("width", "height", "fps", "timeout-ms", "observation-seq"):
        camera.add_argument("--" + key, type=int, required=True)
    inference = commands.add_parser("infer", help="Infer actual recorded RGB-D bundle")
    for key in ("manifest", "weights", "calibration", "config", "output"):
        inference.add_argument("--" + key, type=Path, required=True)
    inference.add_argument("--detector-confidence", type=float, required=True)
    colors = commands.add_parser("color-check", help="Review HSV masks; not instance inference")
    colors.add_argument("recording", type=Path)
    colors.add_argument("--settings", type=Path, required=True)
    colors.add_argument("--output", type=Path, required=True)
    labels = commands.add_parser("check-labels", help="Check actual polygons and scene split")
    for command in (labels, commands.add_parser("train"), commands.add_parser("evaluate")):
        command.add_argument("--dataset", type=Path, required=True)
        command.add_argument("--scene-manifest", type=Path, required=True)
        if command is not labels:
            command.add_argument("--weights", type=Path, required=True)
            command.add_argument("--device", default="cpu", help="Default CPU on this PC")
            command.add_argument("--imgsz", type=int, required=True)
            command.add_argument("--output", type=Path, required=True)
            if command.prog.endswith(" train"):
                command.add_argument("--epochs", type=int, required=True)
                command.add_argument("--batch", type=int, required=True)
    monitor = commands.add_parser("watch-hand", help="Live V0 cycle monitoring; never commands Robot")
    monitor.add_argument("--config", type=Path, required=True)
    monitor.add_argument("--check-id", required=True)
    monitor.add_argument("--output", type=Path, required=True)
    monitor.add_argument("--at-stopped-v0", action="store_true", required=True)
    args = parser.parse_args(argv)
    if args.command == "watch-hand":
        watch_hand(read_json(args.config), args.check_id, args.output)
        return
    if args.command == "check-labels":
        print(json.dumps(check_labels(args.dataset, args.scene_manifest), ensure_ascii=False))
        return
    if args.command in ("train", "evaluate"):
        train_or_evaluate(args.command, args.dataset, args.scene_manifest, args.weights,
            device=args.device, imgsz=args.imgsz, output=args.output,
            epochs=getattr(args, "epochs", None), batch=getattr(args, "batch", None))
        return
    if args.command == "color-check":
        from .visualization import save_color_review
        save_color_review(args.recording, read_json(args.settings), args.output)
        print(f"Color review: {args.output / 'comparison.png'}")
        return
    if args.command == "capture":
        capture(args.directory, args.serial, args.scene_id, args.view_id,
                read_json(args.robot_pose), args.width, args.height, args.fps, args.timeout_ms,
                observation_context={"check_id": args.check_id,
                    "observation_seq": args.observation_seq, "calibration_id": args.calibration_id})
        return
    if args.output.exists():
        raise FileExistsError(args.output)
    manifest = read_json(args.manifest)
    for record in manifest["recordings"]:
        directory = Path(record["directory"])
        if not directory.is_absolute():
            record["directory"] = args.manifest.resolve().parent / directory
    settings = read_json(args.config)
    config = settings["geometry"] if "geometry" in settings else settings
    previews = {}
    def collect_preview(view_id, rgb, detections, candidates):
        from .visualization import render_observation
        previews[view_id] = render_observation(rgb, detections, candidates)
    observed, diagnostics = infer_bundle(manifest, args.weights, read_json(args.calibration),
                                         config, args.detector_confidence, preview_sink=collect_preview)
    encoded = [json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)
               for value in (observed, diagnostics)]
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in zip(("observed.json", "diagnostics.json"), encoded):
        (args.output / name).write_text(value, encoding="utf-8")
    import cv2
    for view_id, rgb in previews.items():
        image_path = args.output / f"{view_id}_inference.png"
        if not cv2.imwrite(str(image_path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)):
            raise OSError(f"failed to save actual inference preview: {image_path}")
    print(f"Observed: {args.output / 'observed.json'}")
    print(f"Diagnostics: {args.output / 'diagnostics.json'}")


def reobserve_once(gate, capture_view, weights, calibration, config, detector_confidence,
                  *, previous_check_id, current_view, hold_kind, reason, close_check,
                  return_to_v0, confirm_view, workflow_valid, bundle_valid,
                  reset_hand_detector, wait_for_hand, request_context, callback,
                  notice, view_sink=None, output_root=None):
    """Internal callables; no new transport schema or automatic retry.

    close_check(id) confirms Backend closed the old request and holds delivery.
    return_to_v0() delegates safe validated-path motion and reports success.
    workflow_valid() checks STOP/fault/other holds throughout correction waiting;
    bundle_valid() checks the NEW active check and continuity during observation.
    wait_for_hand(gate) consumes live stopped-V0 frames, never sets READY manually.
    request_context() obtains a new Backend check and latest Current/Expected only
    after that gate is ready. It may reflect replan; do not force the old Step.
    notice(dict) is proposed internal HMI metadata, not an Observed extension.
    Actual D/HMI adapter implementations and device safety remain external.
    """
    gate.state = "HOLD"
    if current_view not in ("V0", "D1", "D3"):
        raise ValueError("current View must be V0, D1 or D3")
    if hold_kind not in ("ACTUAL_PLACEMENT", "OBSERVATION_CONDITIONS"):
        raise ValueError("STOP/robot error/place occupancy are not correction requests")
    if not isinstance(previous_check_id, str) or not previous_check_id:
        raise ValueError("previous Backend check_id required")
    if not isinstance(reason, str) or not reason:
        raise ValueError("Backend hold reason required")

    def require_workflow():
        if workflow_valid() is not True:
            raise RuntimeError("correction blocked by STOP, fault or other hold")

    def announce(state, allowed=False):
        notice({"state": state, "hold_kind": hold_kind, "reason": reason,
                "previous_check_id": previous_check_id,
                "human_correction_allowed": allowed})

    try:
        require_workflow()
        if close_check(previous_check_id) is not True:
            raise RuntimeError("Backend old check closure/delivery hold not confirmed")
        announce("WAIT_SAFE_V0")
        require_workflow()
        if current_view != "V0":
            if return_to_v0() is not True:
                raise RuntimeError("Controller return-to-V0 failed or interrupted")
        require_workflow()
        if confirm_view("V0") is not True:
            raise RuntimeError("safe stopped stable V0 not confirmed")
        require_workflow()
        gate.reset_for_reobservation()
        reset_hand_detector()
        announce("WAIT_HUMAN_CORRECTION", allowed=True)
        if wait_for_hand(gate) is not True or gate.state != "READY":
            raise RuntimeError("new hand entry, exit >3 seconds and stability required")
        require_workflow()
        context = request_context()
        require_workflow()
        if (not isinstance(context, dict) or not context.get("check_id") or
                context["check_id"] == previous_check_id):
            raise ValueError("Backend must issue a new check_id for reobservation")
        announce("REOBSERVING")
        observed, diagnostics = observe_cycle(
            gate, capture_view, context, weights, calibration, config,
            detector_confidence, callback=callback, confirm_view=confirm_view,
            bundle_valid=lambda: workflow_valid() is True and bundle_valid() is True,
            view_sink=view_sink, output_root=output_root)
        # OK means readable, never completion; only Backend can release delivery.
        announce("WAIT_BACKEND_REVALIDATION")
        return observed, diagnostics
    except Exception as error:
        gate.state = "HOLD"
        notice({"state": "HOLD", "hold_kind": hold_kind,
                "reason": str(error), "hold_reason": reason,
                "previous_check_id": previous_check_id,
                "human_correction_allowed": False})
        raise


if __name__ == "__main__":
    main()
