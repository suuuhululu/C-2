# 준비 Action 권장 타입 검증 · 2026-09-21

## 기준·범위

- 기준/결과: `codex/hmi-preparation-flow`, HEAD 및 fetch 후 origin/main `829db40418adde65236fe856fca2c23e24f13f00`. 결과는 미커밋 작업 파일이다.
- 변경: PrepareWorkpiece.action 추가, CMake 생성 목록·타입 시험·README·권장 명세·수현/세은 작업 문서 갱신. 기존 사용자 변경 보존. 기존 GeneratePath/ExecuteProcess/StopProcess/ProcessState/ProcessEvent 정의는 변경하지 않음.
- 환경: 편집 PC `/opt/ros/jazzy`, Python 3.12. 독립 빌드 루트 `/tmp/c2-prepare-action-YSkrqA`; 기존 ws_cobot1/ws_dsr build/install/log를 사용하거나 덮어쓰지 않음.

## 재현 명령

저장소 루트에서 실행했다. 임시 경로는 이번 시험 경로이며 다음 실행은 새 임시 디렉토리를 사용한다.

```bash
source /opt/ros/jazzy/setup.bash
colcon --log-base /tmp/c2-prepare-action-YSkrqA/log build \
  --base-paths ws_cobot_pjt/ws_cobot1/src/c2_interfaces \
  --packages-select c2_interfaces \
  --build-base /tmp/c2-prepare-action-YSkrqA/build \
  --install-base /tmp/c2-prepare-action-YSkrqA/install
source /tmp/c2-prepare-action-YSkrqA/install/local_setup.bash
colcon --log-base /tmp/c2-prepare-action-YSkrqA/test-log test \
  --base-paths ws_cobot_pjt/ws_cobot1/src/c2_interfaces \
  --packages-select c2_interfaces \
  --build-base /tmp/c2-prepare-action-YSkrqA/build \
  --install-base /tmp/c2-prepare-action-YSkrqA/install
colcon test-result --test-result-base /tmp/c2-prepare-action-YSkrqA/build --verbose
python3 tools/check_repository.py
git diff --check
```

## 판정 범위

- 결과: pytest 18개 통과. colcon 집계는 CTest wrapper 포함 19 tests, 오류/실패/건너뜀 0.
- `check_repository.py`: 173개 파일 텍스트/Python 구문/문서 링크 통과. `git diff --check`: 통과.

Jazzy 타입 생성 빌드 성공. 시험은 생성 타입의 직렬화/역직렬화, MEASURE/BIND Goal·Result·Feedback, 안전하지 않은 기본 성공 방지, 접촉 9점·기하·UTC/monotonic 시각 보존, 수동 확인 Goal 필드 부재 및 기존 타입 회귀를 다룬다. 테스트의 임의 수치/ID는 직렬화 픽스처이며 실제 Goal 검증 통과·실기 승인값이 아니다.

서버 필드 검증, ActionClient/ActionServer 연결, 파일 resolver, 해시 검증, snapshot 등록/취소 경쟁, 실제 홈/측정/관절 검사·그리퍼 명령 부재는 **미검증**이다. 다음 단계에서 송수신 구현 후 권장 명세 7절의 ROS SIM 시나리오를 검증해야 한다. 로봇 노드·모션을 실행하지 않았고 REAL/test_only 제한을 바꾸지 않았다. commit/push/PR/병합하지 않음.
