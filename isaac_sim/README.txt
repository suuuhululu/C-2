Isaac SIM local port — 2026-10-10

Scope
  This folder consolidates the existing SIM implementation. It does not connect
  a physical robot. The authoritative A implementation is ../planning_trial.
  C/D application code and the existing C→A check scripts were preserved.
  assembly-ad-calculation-draft/0.5 remains DRAFT_NOT_FROZEN.

Layout
  scripts/                 SIM host, MoveIt orchestration, FCL guard, tests
  config/                  chair/red inputs and nominal SIM profiles
  fixtures/                frozen request/model inputs and original A snapshot
  assets/original_robot/   original URDF/meshes used by the independent FCL guard
  assets/isaac_robot/      imported Isaac robot; USD references are relative
  ros_ws/src/              canonical M0609+RG2 model and MoveIt executables
  review/                  local port manifest and verification summary

Requirements
  Tested here: Linux, Python 3.12, ROS 2 Jazzy, installed Isaac Sim 6.1 rc.26,
  MoveIt 2.12.4. No Isaac reinstall or version migration was performed.
  ROS/MoveIt/colcon and the Isaac ROS 2 control extension must be installed.
  Runtime Python packages are listed in requirements.txt. If they are absent,
  install into this folder's ignored python_deps/ using a Python 3.12 interpreter:
    python3 -m pip install --target python_deps -r requirements.txt
  Do not copy another PC's build/install/ or site-packages into GitHub.

Build and run (from this folder)
  export ISAAC_SIM_ROOT=<your installed Isaac Sim folder>
  export ROS_SETUP_PATH=/opt/ros/jazzy/setup.bash
  bash BUILD.sh
  bash RUN_SIM.sh --scenario red --auto-start
  bash RUN_SIM.sh --scenario chair --auto-start --auto-human
  Close one SIM session before starting another. Domain 77 is the default;
  ROS_DOMAIN_ID can select a separate local domain. SIM_PYTHON may select a
  Python 3.12 interpreter with rclpy and the requirements available.
  --auto-human supplies MOCK responses, not observations or actual human help.
  The red scenario is one red block; chair is the saved 12-block design.
  prepare_config.py generates config/robot.urdf with local mesh URIs at build
  time. This generated file and build/install/log are ignored, not portable inputs.

CPU checks (from repository root)
  PYTHONPATH=isaac_sim/python_deps python3 -m pytest -q
  PYTHONPATH=isaac_sim/python_deps python3 isaac_sim/scripts/prepare_scenario.py \
    --run-dir <new output folder> \
    --whole-request isaac_sim/config/whole.chair.regression.request.json
  Existing C check scripts take a separate team checkout as their argument.
  This A branch contains the earlier C skeleton, not the required public C/D
  implementations. Local C connection verification used pinned team commit
  101d9d85efe8bdf7cf82bef2a199f4919e1e6c84 without merging its application code.

Runtime evidence
  runs/, runtime_reports/, runtime_logs/ are retained locally and ignored.
  check_chair.py, check_red_run.py and check_handover_lift.py audit saved runs.
  Old full-chair tests belong to their original source version, not this port.
  This port passed CPU checks, C/A/D fixture checks, local ROS build, FCL
  equivalence checks and USD resolution after relocation. Animation was not
  replayed in this task. Tray-open-at-wait behavior remains unverified in SIM.

Boundaries
  Metres/Base/Z-up; no extra division by 1000 of wire poses. Supply display
  height remains the 37.73 mm estimate. Fingertip Offset 40 mm is a gripper
  setting, not pad spacing or TCP Z. Real frame/TCP calibration is unverified.
  The 100 mm source lift is a SIM adapter policy; original A tray travel TCP
  Z=400 mm remains in raw inputs. Source_reference strings and asset provenance
  can retain historical absolute paths: they are records, never opened by the
  runtime. Frozen original inputs were not rewritten to hide their provenance.
  Transport uses contact grasp and MoveIt with Current/attached collision objects.
  Completion uses mock placement/Current update. It is not physical stud fitting,
  force control, a gravity-drop test, real human help or B observation.
  ROBOT_RELEASE_PRESS is not supported by the integrated motion API.
  Model licences remain beside both original and canonical meshes.

Publication
  These checks were completed before publication. The branch history records
  publication; local verification does not imply a new Isaac replay.
