#!/usr/bin/env bash
# 장치 연결 없는 회귀 검사, 설정 preview, 합성 세 사이클 replay.
set -euo pipefail
C2_SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
C2_TRIAL_ROOT="${C2_TRIAL_ROOT:-$C2_SCRIPT_ROOT}"
C2_THREE_STEP_OUTPUT="${C2_THREE_STEP_OUTPUT:-$C2_TRIAL_ROOT/reports/round2_three_step_trial_20261014}"
mkdir -p "$C2_THREE_STEP_OUTPUT"
cd "$C2_TRIAL_ROOT"
python3 scripts/test_robot_trial_offline.py -p no:cacheprovider \
  --junitxml="$C2_THREE_STEP_OUTPUT/three_step_native_tests.xml"
python3 robot_control_integration/scripts/round2_three_step_trial.py preview \
  --start-zone home --output "$C2_THREE_STEP_OUTPUT/preview" \
  > "$C2_THREE_STEP_OUTPUT/preview_stdout.json"
python3 robot_control_integration/scripts/round2_three_step_trial.py replay \
  --start-zone home --output "$C2_THREE_STEP_OUTPUT/replay" \
  > "$C2_THREE_STEP_OUTPUT/replay_stdout.log"
printf '세 단계 오프라인 검사 완료. 결과: %s\n' "$C2_THREE_STEP_OUTPUT"
