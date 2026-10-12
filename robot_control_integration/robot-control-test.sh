#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
command="${1:-help}"
if (($#)); then shift; fi
case "$command" in
  unit)
    mkdir -p logs/verification
    exec python3 -m pytest -q --junitxml=logs/verification/tests.xml "$@" ;;
  integration-test)
    exec python3 -m pytest -q tests/unit/test_control_session.py tests/unit/test_control_driver.py tests/unit/test_control_cli.py "$@" ;;
  replay)
    exec python3 -m scripts.integrated_replay "$@" ;;
  a-step)
    exec python3 -m scripts.check_a_d_onsite "$@" ;;
  preview|template|doctor|run)
    exec python3 -m scripts.robot_control_trial "$command" "$@" ;;
  camera)
    for arg in "$@"; do
      if [[ "$arg" == --enable-gripper-output* ]]; then
        echo '통합 camera 명령은 장치 출력 없는 후보 확인만 지원합니다.' >&2
        exit 2
      fi
    done
    exec python3 -m app.handover_gesture_camera --rgb-transport theora "$@" ;;
  help)
    echo 'unit | integration-test | replay | a-step | preview | template | camera | doctor | run'
    echo 'a-step: D 현장 기준 A 계산 대조. 기본 (11,11) 2층, 로봇·카메라 연결 없음.'
    echo '기본 preview/replay/unit은 장치 없음. run도 --execute 없으면 미리보기.' ;;
  *) echo "알 수 없는 명령: $command" >&2; exit 2 ;;
esac
