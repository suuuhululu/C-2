#!/usr/bin/env bash
# Opening the HMI sends no robot command. START is an explicit operator action.
set -eo pipefail
c2_service_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# Support the delivered runtime/ layout and a normal sibling Git checkout.
c2_service_original="${C2_ROUND3_BASE_ROOT:-$c2_service_root/../../C-2-round3}"
if [[ ! -d "$c2_service_original/.venv" && -z "${C2_ROUND3_BASE_ROOT:-}" ]]; then
  c2_service_original="$c2_service_root/../C-2-round3"
fi
c2_service_original="$(cd -- "$c2_service_original" && pwd)"
c2_service_python="$c2_service_original/.venv/bin/python3"
c2_service_action="${1:-preview}"
if [[ "$c2_service_action" == hmi || "$c2_service_action" == web ]]; then
  source "${C2_ROUND3_ENV:-$c2_service_original/.env.round3-local.bash}"
  source "${C2_SERVICE_ENV:-$c2_service_original/.env.sixpart-local.bash}"
  if [[ "$c2_service_action" == hmi && -f "${C2_SERVICE_LOCAL_ENV:-$c2_service_root/.env.round3-service-local.bash}" ]]; then
    source "${C2_SERVICE_LOCAL_ENV:-$c2_service_root/.env.round3-service-local.bash}"
  fi
  export C2_PROJECT_ROOT="$c2_service_root" C2_ROBOT_ROOT="$c2_service_root/robot_control_integration"
  export PYTHONPATH="$c2_service_root:$c2_service_root/perception:${PYTHONPATH//"$c2_service_original"/"$c2_service_root"}"
  export C_DESIGN_USE_LLM=1
  export OPENAI_MODEL="${OPENAI_MODEL:-gpt-6.1-sol}"
  export OPENAI_AUX_MODEL="${OPENAI_AUX_MODEL:-$OPENAI_MODEL}"
  export OPENAI_JUDGE_MODEL="${OPENAI_JUDGE_MODEL:-$OPENAI_MODEL}"
  if [[ "$c2_service_action" == hmi && -z "${OPENAI_LLM_API_KEY:-}" && -t 0 ]]; then
    read -r -s -p 'C 설계 API 키 (화면·로그에 저장하지 않음): ' OPENAI_LLM_API_KEY
    echo
    export OPENAI_LLM_API_KEY
  fi
fi
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
cd "$c2_service_root"
case "$c2_service_action" in
  hmi) exec "$c2_service_python" -m app.round3_service hmi ;;
  web) exec "$c2_service_python" -m history.web --port 8767 ;;
  preview) exec "$c2_service_python" -m app.round3_service preview ;;
  *) echo 'Usage: bash scripts/round3_service.bash {preview|hmi|web}' >&2; exit 2 ;;
esac
