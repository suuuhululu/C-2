#!/usr/bin/env bash
# Default preview creates a frozen random plan; run never rerolls it.
set -eo pipefail
c2_stack_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# Support the delivered runtime/ layout and a normal sibling Git checkout.
c2_stack_original="${C2_ROUND3_BASE_ROOT:-$c2_stack_root/../../C-2-round3}"
if [[ ! -d "$c2_stack_original/.venv" && -z "${C2_ROUND3_BASE_ROOT:-}" ]]; then
  c2_stack_original="$c2_stack_root/../C-2-round3"
fi
c2_stack_original="$(cd -- "$c2_stack_original" && pwd)"
c2_stack_python="$c2_stack_original/.venv/bin/python3"
c2_stack_command="${1:-preview}"
if [[ $# -gt 0 ]]; then shift; fi
if [[ "$c2_stack_command" == run || "$c2_stack_command" == hmi ]]; then
  source "$c2_stack_original/.env.round3-local.bash"
  export C2_PROJECT_ROOT="$c2_stack_root"
  export C2_ROBOT_ROOT="$c2_stack_root/robot_control_integration"
  export PYTHONPATH="$c2_stack_root:$c2_stack_root/perception:${PYTHONPATH//"$c2_stack_original"/"$c2_stack_root"}"
fi
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
cd "$c2_stack_root"
exec "$c2_stack_python" -m app.round3_stack_five "$c2_stack_command" "$@"
