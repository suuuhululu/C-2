# 9/21 HMI 통합 준비 기록

> **보관 기록:** 이 문서의 REAL 전체 차단 표기는 9/21 SIM 작업 당시 상태다. 2026-09-23 `main`은 REAL 실측 미리보기와 조건부 BIND·경로 후보·별도 실행 요청을 포함한다. [현재 흐름](INTERFACE_GUIDE.md)과 [실행 안내](../backend/README.md)를 우선한다.

## 기준과 보존

2026-09-21. `codex/hmi-preparation-flow`를 `8c8fb5c`에서 최신 `origin/main` **`8a68790`**으로 fast-forward했다.
PR #51 준비 Action, #52 상시 관측 공급, #53 준비 상태·관측 수명 연결을 소스로 확인했다.
기존 staged/unstaged/untracked 작업은 stash 후 복원했다. 중복 Action은 main과 동일하며, 중복 설명 문서는 main의 오타 수정본을 유지했다.
백업 stash `hmi-before-main-8a68790-20260921`은 삭제하지 않았다. 새 commit/push/PR은 만들지 않았다.

## 이번 수정

- 기존 HTTP 준비 요청을 선택적으로 ROS SIM에 연결: MEASURE Goal 발급/발송 전 원장 저장 → typed Result 수신 → 원본 파일 저장 → 동적 `/2` profile 생성 → 새 request ID의 BIND → 성공 원장 저장 → 경로 생성용 profile 공개.
- `prepare-workpiece-result/1`의 ROS Time `{sec,nanosec}`·Pose·접촉 배열을 원본 그대로 보존한다. 화면 변환 데이터와 BIND 원본을 분리한다.
- 입력은 저장소의 `workpiece_simulation.json`과 c2_path의 기존 시험 profile 식별자를 참조한다. REAL 설정을 추정하지 않는다. 원본 `/1`은 유지하고 측정한 기하·작업 범위는 `/2`에만 넣는다. c2_path의 실제 `validate_profile`로 검증한다.
- BIND 실패·취소·시간 초과·늦은 성공·재연결·재시작 시 등록을 재사용하지 않는다. 준비 취소는 표준 Action CancelGoal이다. StopProcess에 준비 ID를 넣지 않는다.
- Action 완료 개수와 최종 9접촉(윗면 1 + 옆면 8) 원본을 구분한다. 개수만으로 개별 점을 초록색으로 채우지 않는다. 등록 성공과 측정 성공도 구분한다.
- 기존 드릴 ON 화면 전용 확인/초기화, 관측 품질·시각 표시를 유지한다. 새 main에 맞춰 첫 REAL Goal 전 UNKNOWN은 관측 설정 미연결일 수 있음을 안내한다.

수정 위치: backend `preparation.py`, `ros_preparation.py`, `storage.py`; frontend 준비 패널/진행 표시/관측 패널; 관련 시험·문서.
기존 `.action`·`.msg`·`.srv`, Topic, HTTP 요청 필드를 추가/변경하지 않았다. 제어/측정 모듈과 장치 명령은 수정하지 않았다.

## SIM 연결 방법

동일한 main의 `c2_interfaces`, `c2_process`, `c2_path`를 Jazzy에서 빌드·source한다.
기존 ROS 모니터 기동에 `C2_ROS_PREPARATION_SIM=1`을 추가한다. 미설정이면 기존 ROS 경로 시험 모드를 유지하고 준비 버튼은 비활성이다.

```bash
# 기존 backend ROS 기동 명령 앞에 두 환경 변수를 적용
export C2_MONITOR_TRANSPORT=ros
export C2_ROS_PREPARATION_SIM=1
```

공정 SIM 노드는 기존 `preparation_backend_url`을 이 HMI 주소로, `preparation_journal_path`를 영속 원장 경로로 지정해야 한다.
HMI가 등록한 설정·측정 원본·프로파일은 기존 `/api/operator/assets/{id}/content`로 읽는다.
Action 서버가 준비되지 않으면 요청을 거절한다. HMI는 서버나 로봇을 자동 기동하지 않는다.
프런트 빌드 후 백엔드를 재기동해야 한다. 이번 작업에서 운영 서버나 기존 DB는 재시작/초기화하지 않았다.

## 새 main 해석과 제한

- `/c2/process_state`의 단일 발행자는 세은 공정 노드다. 시율 모듈은 내부 캐시에 관측값을 공급한다. 측정 결과는 별도 Action Result다.
- PR #53 관측기는 첫 유효한 REAL MEASURE의 설정 검증 뒤 시작하고 요청 종료 이후에도 유지된다. 기동 직후부터 실측값이 나온다는 뜻은 아니다.
- 세부 준비 단계는 Action Feedback, ProcessState.phase는 기존 PRECHECK다. 상태 IDLE 복귀만으로 준비 성공을 판정하지 않는다.
- 게이트웨이는 SIMULATION 전용이다. **REAL 준비/조각은 활성화하지 않았다.** 제어의 ESTIMATED 결과는 BIND가 거절하며 이를 HMI에서 절대 기하로 승격하지 않는다.
- HMI 체크박스를 실제 센서 근거로 대체하지 않는다. 장착·OFF 관측 경로와 현장 승인값은 제어/측정 담당 확인이 필요하다.

## 검증과 남은 일

- 관련 backend 8개 파일 **102 passed**: 기존 준비·모니터·클라이언트·생성 취소·작업 범위·경로 자산·생성 타입 및 신규 ROS 준비 연결/취소/시간 초과 시험. Starlette 기존 경고 1건.
- 마지막 늦은 Feedback 격리 보강 후 준비 관련 2개 파일을 다시 실행해 **39 passed**. 이전 Goal의 진행이 새 준비를 덮지 않는 사례 포함.
- 신규 시험은 main handler의 실제 SIM 측정 함수와 HMI 저장/BIND를 연결한다. 별도 domain 173 + LOCALHOST에서 실제 RosBridge와 공정 ActionServer의 MEASURE/BIND 왕복도 통과했다. 로봇/드라이버는 실행하지 않았다.
- frontend Node 시험 4개 파일, TypeScript, Vite production build 통과.
- 최초 회귀 시험의 3개 setup 오류는 동시 Vite 빌드가 dist/assets를 재생성하는 구간과 겹친 것이다. 빌드 완료 후 재실행해 통과했다.
- 저장소 텍스트/Python 구문/문서 링크 검사 226개 파일 및 `git diff --check` 통과. 전체 레거시 backend 시험 통과를 뜻하지 않는다.
- 이 시험의 자산 resolver는 저장소 바이트를 직접 읽는 시험 대역이다. 배포 HTTP 조회/브라우저부터 끝까지의 ROS 통합이나 실기 검증을 대신하지 않는다.

재현: Jazzy와 같은 c2_interfaces 설치본을 source한 backend에서 `ROS_DOMAIN_ID=173 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST C2_RUN_HMI_PREPARE_ROS=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_ros_preparation_flow.py -q`.
로컬 스레드 통신 제약으로 pytest는 샌드박스 밖에서 임시 DB를 사용했다.

남은 통합: 배포 환경의 HTTP 자산 조회, HMI → 준비 → 경로 생성·미리보기 전체 시나리오, 실제 관측 중 취소/정지 지연, REAL 기하 승인·현장 검증.
SIM 통과는 실기 가공 승인이나 REAL/test_only 제한 해제를 의미하지 않는다.
