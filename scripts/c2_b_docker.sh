#!/usr/bin/env bash
# ROS subscriptions only: existing host camera is reused; USB is not mounted.
set -euo pipefail
checkout_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
image_name="${C2_B_IMAGE:-c2-b-vision:pr48-20261014}"
docker image inspect "$image_name" >/dev/null
mkdir -p "$checkout_root/logs"
run_args=(run --rm --init --network host --shm-size 512m --user "$(id -u):$(id -g)"
  -e ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-20}" -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 -e QT_QPA_PLATFORM=${QT_QPA_PLATFORM:-xcb} -e YOLO_CONFIG_DIR=/tmp
  -e C2_B_CPU_THREADS=2 -e OMP_NUM_THREADS=2 -e MKL_NUM_THREADS=2
  --mount "type=bind,src=$checkout_root,dst=/workspace,readonly"
  --mount "type=bind,src=$checkout_root/logs,dst=/workspace/logs")
# Reuse the host DDS interface selection; a container default may miss localhost-only peers.
if [[ -n "${CYCLONEDDS_URI:-}" ]]; then
  if [[ "$CYCLONEDDS_URI" == file://* ]]; then
    cyclone_config="${CYCLONEDDS_URI#file://}"
    [[ -f "$cyclone_config" && -r "$cyclone_config" ]] || {
      echo 'CYCLONEDDS_URI configuration file is missing or unreadable.' >&2; exit 2;
    }
    run_args+=(--mount "type=bind,src=$cyclone_config,dst=/tmp/c2-cyclonedds.xml,readonly"
      -e CYCLONEDDS_URI=file:///tmp/c2-cyclonedds.xml)
  else
    run_args+=(-e CYCLONEDDS_URI)
  fi
fi
if [[ "${1:-}" == --gui ]]; then
  shift
  [[ -n "${DISPLAY:-}" && -f "${XAUTHORITY:-}" ]] || {
    echo 'DISPLAY와 현재 로그인 세션의 XAUTHORITY 파일이 필요합니다.' >&2; exit 2;
  }
  run_args+=(--hostname "$(hostname)" -e DISPLAY -e XAUTHORITY=/tmp/c2-xauth
    -e QT_X11_NO_MITSHM=1
    --mount type=bind,src=/tmp/.X11-unix,dst=/tmp/.X11-unix,readonly
    --mount "type=bind,src=$XAUTHORITY,dst=/tmp/c2-xauth,readonly")
fi
if [[ -t 0 ]]; then run_args+=(-it); else run_args+=(-i); fi
exec docker "${run_args[@]}" "$image_name" "$@"
