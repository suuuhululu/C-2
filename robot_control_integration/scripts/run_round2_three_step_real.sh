#!/usr/bin/env bash
# 실제 로봇·그리퍼 명령. 기존 ROS 및 로봇 드라이버 환경에서 실행.
set -euo pipefail
C2_SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
C2_TRIAL_ROOT="${C2_TRIAL_ROOT:-$C2_SCRIPT_ROOT}"
C2_THREE_STEP_OUTPUT="${C2_THREE_STEP_OUTPUT:-$C2_TRIAL_ROOT/reports/round2_three_step_trial_20261014}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-20}"
cd "$C2_TRIAL_ROOT"
exec python3 robot_control_integration/scripts/round2_three_step_trial.py run \
  --execute --confirm-hand-clear --start-zone home \
  --output "$C2_THREE_STEP_OUTPUT/real_runs" "$@"
