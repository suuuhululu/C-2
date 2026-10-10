#!/usr/bin/env bash
# Offline A calculation only. No ROS, Robot, Camera, LLM, D or Isaac commands.
set -euo pipefail
task_project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$task_project_root"
task_output_dir=${1:-planning_trial/assembly_api_results_user_05_01}
if [[ -e "$task_output_dir" || -e "$task_output_dir.execution.log" ]]; then
  echo "기존 결과가 있습니다. user_05_02처럼 새 출력 폴더를 지정하세요."
  exit 2
fi
mkdir -p -- "$(dirname -- "$task_output_dir")"
if python3 -m planning_trial.run_assembly_apis --actor user --output-dir "$task_output_dir" 2>&1 | tee "$task_output_dir.execution.log"; then
  echo "실행 종료 코드: 0"
else
  task_exit_code=$?
  echo "실행 종료 코드: $task_exit_code"
  exit "$task_exit_code"
fi
