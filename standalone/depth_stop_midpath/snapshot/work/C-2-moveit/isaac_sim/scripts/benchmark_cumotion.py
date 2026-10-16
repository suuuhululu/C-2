"""Offline cuMotion/OMPL comparison and independent native-time FCL checks.

Archived SIM state is calculation input only. Test obstacles are additive
benchmark overlays, never fresh Current observations or execution permission.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import yaml
from prepare_cumotion_model import read_cumotion_model, make_world, TCP, urdf_transforms
from cumotion_timing import retime_sdk_position_path, export_spline_points
from prepare_cpu_model import file_hash
from plan_only import BINDING, JOINTS, checked_pose, validate_trajectory, prepare_d_candidate


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def check_fixture(fixture, request):
    if (fixture["scope"] != "OFFLINE_BENCHMARK_OVERLAY_NOT_OBSERVED_CURRENT" or
            fixture["execution_allowed"] is not False or
            fixture["planning_request_digest"] != request["planning_request_digest"]):
        raise ValueError("Benchmark fixture gate/binding mismatch")
    ids = {obj["id"] for obj in request["planning_snapshot"]["world_objects"]}
    for obj in fixture["test_obstacles"]:
        if obj["role"] != "BENCHMARK_OBSTACLE" or not obj["id"].startswith("Benchmark_") or obj["id"] in ids:
            raise ValueError("Only additional unique benchmark obstacles allowed")
        ids.add(obj["id"])
        size = np.asarray(obj["size_m"], float)
        if size.shape != (3,) or not np.isfinite(size).all() or np.any(size <= 0) or obj["studs"] is not False:
            raise ValueError("Positive whole cuboid fixture required")
        checked_pose(obj["pose"])


def sample_memory(stop, samples):
    # Observed peak at 200 ms intervals is a lower bound, not an allocator peak.
    while not stop.is_set():
        try:
            lines = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory",
                "--format=csv,noheader,nounits"], text=True, timeout=3).splitlines()
            for line in lines:
                fields = line.split(",")
                if int(fields[0]) == os.getpid():
                    samples.append(dict(t_monotonic_s=time.perf_counter(), process_vram_mib=int(fields[1])))
        except (subprocess.SubprocessError, ValueError) as error:
            samples.append(dict(error=str(error)))
        stop.wait(.2)


def fcl_run(binary, request_path, folder, label, external=None, fixture_path=None):
    result_path = folder / (label + ".fcl.yaml")
    if result_path.exists():
        raise FileExistsError(result_path)
    args = [str(binary), str(Path(__file__).resolve().parents[2]), str(request_path.parent),
            str(request_path), str(result_path)]
    if external is not None or fixture_path is not None:
        args.append(str(external) if external is not None else "-")
    if fixture_path is not None:
        args.append(str(fixture_path))
    env = os.environ.copy()
    env.update(ROS_DOMAIN_ID="188", ROS_LOCALHOST_ONLY="1", ROS_AUTOMATIC_DISCOVERY_RANGE="LOCALHOST")
    begin = time.perf_counter()
    with (folder / (label + ".fcl.log")).open("x") as log:
        completed = subprocess.run(["/usr/bin/time", "-f", "%M", "-o", str(folder / (label + ".rss_kib"))] + args,
                                   env=env, stdout=log, stderr=subprocess.STDOUT, timeout=120)
    elapsed = time.perf_counter() - begin
    result = yaml.load(result_path.read_text(), Loader=yaml.CSafeLoader)
    entry = dict(exit_code=completed.returncode, process_wall_s=elapsed, result=str(result_path),
                 plan_success=result["plan_success"], error=result.get("error"),
                 performance=result.get("performance", {}), checks=result.get("post_timing_collision_checks", 0),
                 duration_s=result.get("planned_duration_s"),
                 direct_collision_count=result.get("direct_joint_path_collision_count"),
                 goal_held_only_collision=result.get("goal_held_only_collision"),
                 interpolation_limit_violation=result.get("interpolation_limit_violation"),
                 collision_pairs=result.get("collision_pairs", result.get("goal_collision_pairs", [])))
    entry["process_max_rss_mib"] = float((folder / (label + ".rss_kib")).read_text().splitlines()[-1]) / 1024
    if result["plan_success"]:
        trajectory = validate_trajectory(result["planned_trajectory"])
        positions = np.array([p["positions_rad"] for p in trajectory["points"]])
        entry["sampled_joint_path_length_rad"] = float(np.linalg.norm(np.diff(positions, axis=0), axis=1).sum())
    return entry, result


def benchmark(args, report):
    if not sys.flags.isolated or sys.prefix == sys.base_prefix:
        raise ValueError("Use isolated cuMotion venv python -I")
    request, manifest = read_cumotion_model(args.model, args.request)
    fixture = yaml.safe_load(args.fixture.read_text()) if args.fixture else None
    if fixture:
        check_fixture(fixture, request)
    report.update(binding=manifest["binding"], model_files=manifest["files"],
                  jerk_limits_rad_s3=manifest["jerk_limits"], jerk_is_temporary_calculation_only=True,
                  source_request=str(args.request), source_request_sha256=file_hash(args.request),
                  fcl_binary_sha256=file_hash(args.fcl_binary),
                  source_files={n: file_hash(Path(__file__).parent / n) for n in
                                ["benchmark_cumotion.py", "prepare_cumotion_model.py", "cumotion_geometry.py", "cumotion_timing.py"]},
                  fixture=fixture, model_checks=json.loads((args.model / "model_checks.json").read_text()))
    # OMPL is an independent comparison, never an automatic fallback.
    report["ompl_runs"] = []
    for i in range(args.repeats):
        entry, _ = fcl_run(args.fcl_binary, args.request, args.output, "ompl_" + str(i), fixture_path=args.fixture)
        report["ompl_runs"].append(entry)
        save(args.output / ("ompl_" + str(i) + ".summary.json"), entry)
    begin = time.perf_counter()
    import cumotion
    report["cumotion_import_wall_s"] = time.perf_counter() - begin
    if cumotion.__version__ != "1.1.0" or not Path(cumotion.__file__).resolve().is_relative_to(Path(sys.prefix)):
        raise ValueError("Selected isolated stable cuMotion1.1.0 required")
    begin = time.perf_counter()
    robot = cumotion.load_robot_from_file(args.model / "robot.xrdf", args.model / "robot.urdf")
    world, mapping = make_world(request, cumotion)
    if fixture:
        for obj in fixture["test_obstacles"]:
            obstacle = cumotion.create_obstacle(cumotion.Obstacle.Type.CUBOID)
            obstacle.set_attribute(cumotion.Obstacle.Attribute.SIDE_LENGTHS, np.asarray(obj["size_m"]))
            world.add_obstacle(obstacle, cumotion.Pose3(checked_pose(obj["pose"])))
    view = world.add_world_view()
    inspector = cumotion.create_robot_world_inspector(robot, view)
    q = np.array(request["planning_snapshot"]["q_rad"], float)
    if fixture and "start_override_rad" in fixture:
        q = np.asarray(fixture["start_override_rad"], float)
    original = ET.fromstring(request["model_bundle"]["robot_description"])
    bounds = [original.find(f"joint[@name='{n}']/limit") for n in JOINTS]
    if q.shape != (6,) or not np.isfinite(q).all() or any(
            not float(b.get("lower")) <= v <= float(b.get("upper")) for v, b in zip(q, bounds)):
        report["cumotion_rejection"] = "START_BOUNDS_VIOLATION_BEFORE_GPU_SOLVE"
        return
    actual = urdf_transforms(original, q, request["planning_snapshot"]["grip_rad"])[TCP]
    expected = checked_pose(request["planning_snapshot"]["tcp_pose"])
    if not np.allclose(actual, expected, atol=.0008, rtol=0):
        report["cumotion_rejection"] = "SNAPSHOT_FK_TCP_MISMATCH_BEFORE_GPU_SOLVE"
        return
    report.update(world_mapping=mapping, start_self_collision_pairs=inspector.frames_in_self_collision(q),
                  start_world_collision=inspector.in_collision_with_obstacle(q),
                  model_world_loading_wall_s=time.perf_counter() - begin)
    # Confirmed by an actual stable1.1.0 optimizer initialization failure in
    # baseline_probe01. Do not repeat that allocation or remove geometry.
    report["self_collision_sphere_count"] = inspector.num_self_collision_spheres()
    if inspector.num_self_collision_spheres() > 1024:
        report["cumotion_rejection"] = "VERIFIED_STABLE_1_1_0_SELF_COLLISION_KERNEL_LIMIT_1024"
        report["cumotion_runs"] = []
        return
    begin = time.perf_counter()
    config = cumotion.create_default_trajectory_optimizer_config(robot, TCP, view)
    explicit_config = {"trajopt/num_geometric_planning_attempts": 0, "ik/max_reattempts": 0}
    for name, value in explicit_config.items():
        if not config.set_param(name, value):
            raise ValueError("cuMotion rejected explicit no-fallback parameter: " + name)
    report["explicit_optimizer_config"] = explicit_config
    optimizer = cumotion.create_trajectory_optimizer(config)
    cuda = ctypes.CDLL("libcuda.so.1")
    if cuda.cuInit(0) != 0 or cuda.cuCtxSynchronize() != 0:
        raise RuntimeError("CUDA synchronization failed")
    report["gpu_optimizer_initialization_wall_s"] = time.perf_counter() - begin
    goal = checked_pose(request["goal"])
    initial_rotation = expected[:3, :3]
    # API uses one cone tolerance; MoveIt uses separate rotation-vector X/Y.
    # The enclosing cone is only a solver constraint. Exact shared holding
    # tolerances and terminal pose are still required by the FCL post-check.
    target = cumotion.TrajectoryOptimizer.TaskSpaceTarget(
        cumotion.TrajectoryOptimizer.TranslationConstraint.target(goal[:3, 3], .0008),
        cumotion.TrajectoryOptimizer.OrientationConstraint.terminal_target_and_path_axis(
            cumotion.Rotation3.from_matrix(goal[:3, :3]), np.array([0., 0., 1.]),
            initial_rotation[:, 2], .005, args.path_axis_tolerance))
    report["target_mode"] = "POSE_TARGET"
    if args.cspace_reference is not None:
        reference = yaml.load(args.cspace_reference.read_text(), Loader=yaml.CSafeLoader)
        prepare_d_candidate(reference, request, manifest["binding"])
        goal_q = reference["planned_trajectory"]["points"][-1]["positions_rad"]
        target = cumotion.TrajectoryOptimizer.CSpaceTarget(np.array(goal_q),
            cumotion.TrajectoryOptimizer.CSpaceTarget.TranslationPathConstraint.none(),
            cumotion.TrajectoryOptimizer.CSpaceTarget.OrientationPathConstraint.axis(
                np.array([0., 0., 1.]), initial_rotation[:, 2], args.path_axis_tolerance))
        report.update(target_mode="EXPLICIT_CPU_IK_GOAL_Q_WITH_CUMOTION_PATH_NOT_FALLBACK",
            goal_cspace_reference=str(args.cspace_reference),
            goal_cspace_reference_sha256=file_hash(args.cspace_reference), goal_q_rad=goal_q,
            cpu_goal_ik_cost_not_in_native_solve_measurement=True)
    report["path_orientation_mapping"] = "SDK_AXIS_CONE_PLUS_EXACT_SHARED_FCL_ROTATION_VECTOR_CHECK"
    report["path_axis_tolerance_rad"] = args.path_axis_tolerance
    report["timed_export_engine"] = args.timed_export_engine
    report["cumotion_runs"] = []
    save(args.output / "before_native_solve.json", report)
    for i, kind in enumerate(["COLD_FIRST_SOLVE", "WARM_UP"] + ["WARM_REPEAT"] * args.repeats):
        if cuda.cuCtxSynchronize() != 0:
            raise RuntimeError("CUDA synchronization failed before solve")
        begin = time.perf_counter()
        result = (optimizer.plan_to_cspace_target(q, target) if args.cspace_reference is not None else
                  optimizer.plan_to_task_space_target(q, target))
        if cuda.cuCtxSynchronize() != 0:
            raise RuntimeError("CUDA synchronization failed after solve")
        entry = dict(kind=kind, status=str(result.status()), solve_wall_s=time.perf_counter() - begin)
        report["cumotion_runs"].append(entry)
        if result.status() == cumotion.TrajectoryOptimizer.Results.Status.SUCCESS:
            begin = time.perf_counter()
            trajectory = result.trajectory()
            native_duration = trajectory.domain().span()
            entry.update(max_native_velocity=trajectory.max_velocity_magnitude().tolist(),
                max_native_acceleration=trajectory.max_acceleration_magnitude().tolist(),
                max_native_jerk=trajectory.max_jerk_magnitude().tolist())
            timing_metadata = None
            if args.timed_export_engine == "sdk-spline-retime":
                trajectory, timing_metadata = retime_sdk_position_path(trajectory,
                    [float(b.get("lower")) for b in bounds], [float(b.get("upper")) for b in bounds],
                    manifest["jerk_limits"], cumotion)
            domain = trajectory.domain()
            points = []
            # All exported derivatives come from the explicitly selected curve.
            # Native and spline-retimed results retain separate provenance.
            if timing_metadata is not None:
                points, export_metadata = export_spline_points(trajectory)
                timing_metadata.update(export_metadata)
            else:
                for t in np.linspace(domain.lower, domain.upper, int(np.ceil(domain.span() / .01)) + 1):
                    p, v, a, _ = trajectory.eval_all(float(t))
                    points.append(dict(positions_rad=p.tolist(), velocities_rad_s=v.tolist(),
                        accelerations_rad_s2=a.tolist(), time_from_start_s=float(t - domain.lower)))
            timed = validate_trajectory(dict(joint_names=JOINTS, points=points))
            entry.update(duration_s=domain.span(), points=len(points),
                export_max_interval_s=.01, native_timing_changed=timing_metadata is not None,
                native_duration_s=native_duration, timing_metadata=timing_metadata,
                export_wall_s=time.perf_counter() - begin,
                max_export_velocity=trajectory.max_velocity_magnitude().tolist(),
                max_export_acceleration=trajectory.max_acceleration_magnitude().tolist(),
                max_export_jerk=trajectory.max_jerk_magnitude().tolist())
            external = args.output / ("cumotion_" + str(i) + ".input.json")
            save(external, dict(scope="FILE_ONLY_EXTERNAL_CUMOTION_TIMED", execution_allowed=False,
                hardware_execution_allowed=False, binding=manifest["binding"], trajectory=timed,
                timing_engine=timing_metadata["engine"] if timing_metadata else "CUMOTION_NATIVE_NO_TOTG",
                native_timing_changed=timing_metadata is not None, timing_metadata=timing_metadata,
                cuMotion_model_files=manifest["files"]))
            entry["fcl"], checked = fcl_run(args.fcl_binary, args.request, args.output,
                                          "cumotion_" + str(i), external, args.fixture)
            if checked["plan_success"] and fixture is None:
                candidate = prepare_d_candidate(checked, request, manifest["binding"])
                save(args.output / ("cumotion_" + str(i) + ".d_receive_only.json"), candidate)
                entry["common_d_draft_validated"] = True
        save(args.output / ("cumotion_" + str(i) + ".summary.json"), entry)
    read_cumotion_model(args.model, args.request)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "request", "output", "fcl-binary"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--cspace-reference", type=Path,
                        help="Explicit separate CPU-IK endpoint experiment; not automatic fallback")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timed-export-engine", choices=["native", "sdk-spline-retime"], default="native",
                        help="Explicit retiming experiment; changes native timing/path, requires final FCL")
    parser.add_argument("--path-axis-tolerance", type=float, default=np.sqrt(2) * .25,
                        help="Explicit solver cone; shared FCL holding tolerances are unchanged")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("Use 1..10 independent comparison repeats")
    if not np.isfinite(args.path_axis_tolerance) or not .005 <= args.path_axis_tolerance <= np.sqrt(2) * .25:
        parser.error("Solver cone may only be tightened within .005..sqrt(2)*.25 rad")
    for name in ("model", "request", "output", "fcl_binary", "fixture", "cspace_reference"):
        if getattr(args, name) is not None:
            setattr(args, name, getattr(args, name).resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(scope="OFFLINE_NOMINAL_SIM_COMPARISON_NOT_FOR_EXECUTION", pid=os.getpid(),
                  execution_allowed=False, hardware_execution_allowed=False, auto_fallback=False,
                  real_initial_contact_verified=False, d_execution_verified=False,
                  vram_measurement="200MS_PROCESS_SAMPLES_OBSERVED_PEAK_LOWER_BOUND")
    stop, memory = threading.Event(), []
    sampler = threading.Thread(target=sample_memory, args=(stop, memory), daemon=True)
    sampler.start()
    begin = time.perf_counter()
    try:
        benchmark(args, report)
    except Exception as error:
        report["error"] = str(error)
    finally:
        stop.set()
        sampler.join(timeout=5)
        report.update(total_wall_s=time.perf_counter() - begin, memory_samples=memory,
                      max_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                      observed_peak_process_vram_mib=max([s.get("process_vram_mib", 0) for s in memory], default=0))
        save(args.output / "report.json", report)
    print(json.dumps({k: report.get(k) for k in ("error", "cumotion_rejection", "observed_peak_process_vram_mib", "max_rss_mib")}))
    return 1 if "error" in report else 0


if __name__ == "__main__":
    raise SystemExit(main())
