#!/usr/bin/env bash
# Default is an offline preview. initial/hmi are explicit operator run stages.
set -eo pipefail
c2_b3_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# Support the delivered runtime/ layout and a normal sibling Git checkout.
c2_b3_original="${C2_ROUND3_BASE_ROOT:-$c2_b3_root/../../C-2-round3}"
if [[ ! -d "$c2_b3_original/.venv" && -z "${C2_ROUND3_BASE_ROOT:-}" ]]; then
  c2_b3_original="$c2_b3_root/../C-2-round3"
fi
c2_b3_original="$(cd -- "$c2_b3_original" && pwd)"
c2_b3_python="${C2_B3_PYTHON:-$c2_b3_original/.venv/bin/python3}"
c2_b3_profile="$c2_b3_root/robot_control_integration/settings/round3_b_three_step_20261015"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
case "${1:-preview}" in
  initial|hmi)
    source "${C2_ROUND3_ENV:-$c2_b3_original/.env.round3-local.bash}"
    if [[ "${1:-preview}" == hmi ]]; then
      source "${C2_B3_SERVICE_ENV:-$c2_b3_original/.env.sixpart-local.bash}"
    fi
    # The source environment supplies installed ROS overlays; select this code copy.
    export C2_PROJECT_ROOT="$c2_b3_root"
    export C2_ROBOT_ROOT="$c2_b3_root/robot_control_integration"
    export PYTHONPATH="$c2_b3_root:$c2_b3_root/perception:${PYTHONPATH//"$c2_b3_original"/"$c2_b3_root"}"
    ;;
esac
cd "$c2_b3_root"
case "${1:-preview}" in
  preview)
    "$c2_b3_python" -m app.round3_initial_inspection preview
    cd "$c2_b3_root/robot_control_integration"
    exec "$c2_b3_python" -m scripts.round2_three_step_trial preview \
      --scenario "$c2_b3_profile/scenario.json" --execution-profile "$c2_b3_profile/profile.json"
    ;;
  initial)
    exec "$c2_b3_python" -u -m app.round3_initial_inspection run \
      --execute --confirm-route-reviewed --confirm-empty-gripper --confirm-hand-clear
    ;;
  hmi)
    [[ $# == 2 && -d "$2" ]] || { echo 'hmi requires the fresh successful INITIAL cycle directory.' >&2; exit 2; }
    "$c2_b3_python" - "$c2_b3_profile/scenario.json" <<'PY'
import json, sys
from pathlib import Path
s=json.loads(Path(sys.argv[1]).read_text())
p=Path('logs/real-b-three-step/design.candidate.json')
p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps(dict(design_version=1,blocks=[r['block'] for r in s['preplaced']]+[r['target'] for r in s['steps']]),indent=2)+'\n')
PY
    exec "$c2_b3_python" -m app.mvp_real_trial --robot-root "$C2_ROBOT_ROOT" \
      --log-directory "$c2_b3_root/logs/real-b-three-step/jobs" \
      --round3-b-three-step --initial-observation "$2" \
      --fixed-trial-scenario "$c2_b3_profile/scenario.json" \
      --execution-profile "$c2_b3_profile/profile.json" \
      --design "$c2_b3_root/logs/real-b-three-step/design.candidate.json" --execute
    ;;
  *) echo 'Usage: bash scripts/round3_b_three_step.bash {preview|initial|hmi INITIAL_CYCLE_DIR}' >&2; exit 2 ;;
esac
