#!/bin/bash
set -eo pipefail
TASK_PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
python3 "$TASK_PACKAGE_DIR/tools/verify_bundle.py"
python3 "$TASK_PACKAGE_DIR/tools/portable_runtime.py" "$@"
python3 "$TASK_PACKAGE_DIR/tools/install_python.py"
"$TASK_PACKAGE_DIR/start.sh" --check
