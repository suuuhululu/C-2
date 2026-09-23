# REAL 측정 수정 수신 후 통합·실행 준비 · 2026-09-23

이 문서는 담당자의 측정 수정 커밋 SHA가 도착한 뒤 같은 코드로 정적 검사,
PR 병합, 실기 PC 재빌드까지 이어가기 위한 체크리스트다. 현재 기준은
`origin/main` `b9eb003`, 준비 브랜치는 `codex/real-contract-fix`다.

## 병합 전 필수 입력

- 담당자 브랜치와 커밋 SHA
- 해당 커밋의 변경 파일 목록
- 외력 영점/보정이 ROS 측정 실행 동안 유지되는 근거와 시험
- 측정 설정 전체 변경분. 중심·반지름·탐색 길이·후퇴 여유 일부만 떼어 적용하지 않는다.
- 8/8 결과 JSON, 결과 발행 성공, `stop_confirmed=true`, HOME 복귀 결과

현재 배포 실행 후보는
`ws_cobot_pjt/ws_cobot1/src/c2_process/config/real_execution_profile_20260923.json`이다.
7점 승인값은 후보 표면일 뿐이며 `BIND_SNAPSHOT`에서 새 8점 실측 기하로
대체돼야 한다. 측정 설정은 담당자 커밋 전까지 main 원본을 유지한다.

## 담당자 SHA 수신 직후

```bash
cd /home/rokey/cobot1/.worktrees/real-contract-fix
git fetch origin --prune
git show --stat --oneline <담당자_커밋_SHA>
git diff origin/main...<담당자_커밋_SHA> -- \
  ws_cobot_pjt/ws_cobot1/src/c2_process
```

다른 팀원의 파일이나 생성 산출물이 섞였으면 cherry-pick하지 않고 담당자에게
커밋 분리를 요청한다. 깨끗한 커밋이면 준비 브랜치에 반영하고 충돌을 검토한다.

```bash
git cherry-pick <담당자_커밋_SHA>
```

## 병합 전 정적 검사

```bash
cd /home/rokey/cobot1/.worktrees/real-contract-fix/ws_cobot_pjt/backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_real_config_alignment.py tests/test_real_preparation_hmi.py

cd /home/rokey/cobot1/.worktrees/real-contract-fix/ws_cobot_pjt/ws_cobot1/src/c2_process
PYTHONPATH=.:test PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  ../../../backend/.venv/bin/python -m pytest -q test/ -p no:cacheprovider

cd /home/rokey/cobot1/.worktrees/real-contract-fix/ws_cobot_pjt/ws_cobot1/src/c2_path
PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  ../../../backend/.venv/bin/python -m pytest -q test/ -p no:cacheprovider

cd /home/rokey/cobot1/.worktrees/real-contract-fix
python3 tools/check_repository.py
python3 tools/test_git_hooks.py
python3 tools/issue_manager.py
python3 tools/test_issue_manager.py
git diff --check
```

```bash
cd /home/rokey/cobot1/.worktrees/real-contract-fix/ws_cobot_pjt/ws_cobot1
source /opt/ros/jazzy/setup.bash
source /home/rokey/ws_cobot_pjt/ws_dsr/install/setup.bash
colcon build --symlink-install --packages-select c2_interfaces c2_path c2_process
```

검사 결과와 미검증 실기 항목을 PR에 기록하고 동료 검토 후 main에 병합한다.
main 직접 push와 자동 병합은 하지 않는다.

## 병합 뒤 실기 PC 배포

실기 checkout에 추적 변경이 없는지 먼저 확인한다. `<병합_SHA>`는 PR이 main에
병합된 실제 커밋으로 바꾼다.

```bash
cd /home/rokey/cobot1-real-test
git status --short --branch
git fetch origin --prune
git switch --detach <병합_SHA>

cd ws_cobot_pjt/ws_cobot1
source /opt/ros/jazzy/setup.bash
source /home/rokey/ws_cobot_pjt/ws_dsr/install/setup.bash
colcon build --symlink-install --packages-select c2_interfaces c2_path c2_process
source install/local_setup.bash
```

모든 실행 터미널에서 다음 환경을 동일하게 사용한다.

```bash
cd /home/rokey/cobot1-real-test
source /opt/ros/jazzy/setup.bash
source /home/rokey/ws_cobot_pjt/ws_dsr/install/setup.bash
source ws_cobot_pjt/ws_cobot1/install/local_setup.bash

export ROS_DOMAIN_ID=20
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export ROS_STATIC_PEERS=''
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset ROS_LOCALHOST_ONLY

export C2_MONITOR_DATA=/tmp/c2-real-engraving
export C2_PREPARATION_CONFIG=/home/rokey/cobot1-real-test/ws_cobot_pjt/ws_cobot1/src/c2_process/config/workpiece_real_trial_0921.json
export C2_EXECUTION_PROFILE=/home/rokey/cobot1-real-test/ws_cobot_pjt/ws_cobot1/src/c2_process/config/real_execution_profile_20260923.json
mkdir -p "$C2_MONITOR_DATA"
```

터미널 1에서 HMI를 실행한다.

```bash
cd /home/rokey/cobot1-real-test
python3 ws_cobot_pjt/run_monitor.py \
  --transport ros \
  --mode REAL \
  --ros-domain-id "$ROS_DOMAIN_ID" \
  --preparation-config "$C2_PREPARATION_CONFIG" \
  --execution-profile "$C2_EXECUTION_PROFILE"
```

터미널 2에서 REAL 공정 노드를 실행한다.

```bash
cd /home/rokey/cobot1-real-test
ros2 run c2_process real_process_node \
  --preparation-backend-url http://127.0.0.1:8010 \
  --preparation-journal-path "$C2_MONITOR_DATA/preparation.sqlite3" \
  --execution-journal-path "$C2_MONITOR_DATA/execution.sqlite3" \
  --controller-prefix /dsr01/dsr_controller2
```

## 실기 진행 게이트

1. 중복 HMI/공정 노드가 없는지 확인한다.
2. TCP `GripperDA_v1`, load `ToolWeight_1`, 정지 상태, 제어권을 읽기 전용으로 확인한다.
3. 담당자 수정이 외력 오프셋을 측정 실행 동안 어떻게 처리하는지 로그로 확인한다.
4. 먼저 8/8 측정과 결과 JSON 발행, 정지 확인, HOME 복귀까지만 수행한다.
5. 성공 결과를 `BIND_SNAPSHOT`하고 같은 스냅샷으로 경로·미리보기를 새로 만든다.
6. 읽기 전용 ENTRY 검사 후 감독하 `ENTRY_ONLY`, 짧은 곡면 조각, 전체 조각 순으로 진행한다.

`FORCE_LIMIT`, `STOP_UNCONFIRMED`, 제어권 상실, 통신 불명은 자동 재시도하지 않는다.
철사 고정 상태에서 그리퍼를 열지 않는다.
