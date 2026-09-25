> 최신 후속 수정: [REAL HMI 통합 연결 수정](../docs/HMI_REAL_INTEGRATION_FIXES_20260922.md). 정적 실행 설정 사전 검사·측정 확인값 초기화·REAL 경로 서버 기동 및 현재 공통 Result 단절을 설명합니다. 아래 과거 검사 시점·별도 기동 설명보다 우선합니다.

# 새김 시스템 모니터 서버

REAL 실행 프로파일 검사는 HMI 기동이나 **사전 검사·양초 측정 요청**을 막지 않는다.
`--execution-profile`을 생략하거나 지정 파일이 없거나 JSON 형식이 잘못돼도 화면은 기동한다.
측정 성공 원본으로 REAL 미리보기 전용 스냅샷을 만들어 BIND 없이 경로를 생성한다.
이 경로는 test_only이며 실제 공정 실행은 차단된다. 측정 설정 `--preparation-config`는 계속 필요하다.
실행 설정은 최종 공정 실행 전에 연결해야 하며, `execution_context.entry_planning`의
실측 윗면 상대 상공 여유·표본 간격·관절/간격 기준·모션 프로파일 참조까지 사전 검사를 통과해야 한다.
검사는 준비 JSON이나 실행 프로파일을 수정하지 않는다. 양초 중심·반지름·윗면·바닥은
측정 결과로 새 불변 스냅샷에 기록하고, entry 정책만 실행 프로파일에서 그 스냅샷으로 복사한다.
설정 파일을 수정·선택한 뒤에는 HMI를 재시작한다.
잘못 지정한 실행 파일을 해제하려면 `unset C2_EXECUTION_PROFILE` 후 실행한다.

최신 작업: [이미지 한 장 HMI 부분통합](../docs/HMI_PARTIAL_INTEGRATION.md). 운영 화면에서 ZIP 교환을 제거하고 기본 실행을 실제 PNG/JPEG 계산 → 기존 준비/공정 흐름으로 연결했다. 이미지 의존성은 `requirements-image.lock.txt`를 사용한다. 아래 과거 파일 통합 메뉴 안내는 이전 구현 기록이다.

최신 REAL 흐름은 [인터페이스 안내](../docs/INTERFACE_GUIDE.md)를 따른다. `--mode REAL --preparation-config ...`는 현장 설정을 명시 선택하며 실행 프로파일이 없으면 측정·미리보기까지만 허용한다. BIND·REAL 실행 후보·prepared `PRECHECK → ENTRY → ENGRAVE → RETURN_HOME → FINISH`에는 유효한 `--execution-profile`이 추가로 필요하다. 정상 성공 경로의 검사된 HOME 복귀와 실패·정지 미확인 뒤 자동 복귀 금지를 구분한다. 아래의 과거 REAL 기동 거절·SIM 전용 표기는 이전 구현 기록이다.

최신: [main 8a68790 통합 준비](../docs/HMI_INTEGRATION_20260921.md). `C2_ROS_PREPARATION_SIM=1`로 기존 ROS 준비 요청의 MEASURE→원본 저장→동적 `/2`→BIND를 연결한다. REAL/조각 차단은 유지한다. 아래 미연결 표기는 이전 기록이다.

2026-09-21 후속: [HMI 선행 수정](../docs/HMI_PREWORK_20260921.md). 준비 HTTP의 수동 확인 3개/confirmed_at 제거, 재연결 후 이전 준비 무효화, PrepareWorkpiece raw 클라이언트·원본 변환을 추가했다. 준비 HTTP의 ROS 활성화와 실제 원본/BIND/동적 profile 연결은 아직 대기이며 REAL 제한을 유지한다.

2026-09-21: [준비·양초 측정 HMI](../docs/HMI_PREPARATION.md)를 MOCK으로 연결했다.
준비·측정 기록과 설정 ID/해시를 보존하고, 새 MOCK 실행에는 준비 성공 및 같은 설정의 경로가 필요하다.
ROS 준비 Action은 아직 미연결이며 기존 ROS 경로 시험·REAL 실행 차단은 유지한다.

2026-09-21: [작업 영역 기준](../docs/HMI_WORK_AREA.md)의 HMI 표시용 정책 스냅샷을 추가했다.
`config/work_area.json`을 관리 자산으로 저장하고 HTTP/WS snapshot의 `work_area_policy`로 전달한다.
ROS 입력 프로파일을 덮어쓰지 않으며 MOCK만 합의 제외 길이를 적용한다.

2026-09-21: [경로 생성 취소·중단 확인](../docs/HMI_GENERATION_CANCEL.md)을 지원한다. 기존 GeneratePath v2의 표준 취소를 사용하며 공통 ROS 타입 변경은 없다.

2026-09-21: 공통 SIM 스냅샷 등록·선택, 입력 ZIP 내보내기, 결과 ZIP 검증·등록을 추가했다.
화면의 **파일 통합 시험**을 사용한다. 전달 규격·API·공통 스키마의 미정 범위는
[HMI 파일 통합 안내](../docs/HMI_FILE_INTEGRATION.md)를 따른다. 가져온 경로의 HMI 실행은 차단한다.

2026-09-20: PR #38의 `c2_path` 계약에 맞춰 실제 이미지 경로 생성·관리 파일 로더·미리보기를 연결했다.
한 PC에서 `python3 ws_cobot_pjt/run_monitor.py --transport ros`로 실행한다.
Jazzy/공통 타입/계산 의존성 준비와 검증 범위는 [HMI 경로 통합 안내](../docs/HMI_PATH_INTEGRATION.md)를 따른다.
현재 ROS 연결은 SIMULATION/test_only이며 공정 실행은 차단한다.

2026-09-19 고정 드릴 반영: 통신 schema_version=2, engraving_drill/c2_base, 준비→보정 확인→접근·조각·이탈→완료를 모의 실행한다. 그리퍼 열기·집기·청소·반납은 없다. SQLite 테이블 버전은 1을 유지하며 과거 기록은 보존하고 이전 계약 경로의 새 실행은 거절한다. [변경·배포](../docs/C2_FIXED_DRILL_20260919.md).

2026-09-18. 운영자 HMI 전용 FastAPI + SQLite + 모의 게이트웨이. 고객 주문·대기열은 사용하지 않는다. 상세 DB·통신·검증 범위는 [모니터 구현 안내](../docs/HMI_MONITOR_IMPLEMENTATION.md)를 따른다.

## 실행

Python 3.12, Node.js 22 이상이 필요하다. 새 PC는 아래와 [화면 설치](../frontend/README.md)를 먼저 수행한다.

```bash
cd ws_cobot_pjt/backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
```

저장소 루트에서 화면과 서버를 함께 실행한다.

```bash
python3 ws_cobot_pjt/run_monitor.py
```

- 화면: http://127.0.0.1:5174/operator
- API·API 문서: http://127.0.0.1:8010/docs
- 기본은 SIMULATION / MOCK. `--transport ros`는 실제 이미지 경로 노드를 함께 기동한다. 실제 로봇·이전 서버는 기동하지 않는다.
- 접근 키는 없다. 루프백 주소의 한 운영자용 모의 개발 화면이다. 외부 공개·다중 사용자 인증은 구현 범위 밖이다.
- 종료: 실행 터미널에서 Ctrl+C. 데이터는 유지된다.

서버만 실행하려면:

```bash
cd ws_cobot_pjt/backend
C2_MONITOR_MODE=SIMULATION C2_MONITOR_TRANSPORT=mock \
  .venv/bin/python -m uvicorn app.monitor:app --host 127.0.0.1 --port 8010
```

화면을 빌드해 두면 같은 서버의 http://127.0.0.1:8010/operator 에서도 사용 가능하다. `--workers`는 1만 지원하며 같은 DB의 중복 서버는 파일 잠금으로 거절한다.

## DB와 환경

- 새 DB: 기본 MOCK은 `monitor_data/monitor.sqlite3`, ROS 실행기는 `monitor_data/ros_path/monitor.sqlite3`. 최초 기동 때 스키마 v1과 해당 모드의 불변 설정 스냅샷을 만든다.
- 관리 파일: `monitor_data/assets/<UUID>.bin`. 원본·SVG·경로·진단·미리보기는 UUID 및 SHA-256으로 참조한다.
- 이전 `data/saegim.sqlite3`는 열거나 마이그레이션하지 않는다.
- `C2_MONITOR_DATA`로 새 저장 디렉토리를 지정할 수 있다. 기본 `monitor_data`는 Git 제외다.
- `C2_MONITOR_MODE=REAL`은 기동 거절. ROS 환경을 준비한 뒤 통합 실행기의 `--transport ros`를 사용한다.
- 백업은 서버를 정상 종료한 다음 `monitor_data` 전체를 복사한다. 자동 삭제·보관 만료는 구현하지 않았다.

## 시험

```bash
cd ws_cobot_pjt/backend
env -u PYTHONPATH PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .venv/bin/python -m pytest -q tests/test_monitor.py
```

위 MOCK 시험은 임시 DB를 사용하며 ROS나 로봇에 연결하지 않는다. 실제 변환은 `c2_path`가 담당한다.
추가 의존성은 `requirements-ros.txt`, 파일 검증은 `tests/test_path_artifacts.py`, 실제 ROS/HTTP 통합은
`tests/test_ros_path_integration.py`다. 활성화·실행 명령은 [통합 안내](../docs/HMI_PATH_INTEGRATION.md#재현-시험)를 따른다.

## ROS 게이트웨이 연결 상태

`app/ros_bridge.py`에 Jazzy `monitor_gateway_node` 클라이언트를 구현했다. `/c2/generate_path`, `/c2/execute_process`, `/c2/stop_process`와 상태·이벤트 두 Topic을 사용한다. 임의 `.msg/.action/.srv`를 새로 정의하지 않는다.

2026-09-19 [c2_interfaces v2](../ws_cobot1/src/c2_interfaces/README.md)의 실제 타입·빌드 설정을 추가했다. 해당 안내대로 빌드·source하면 import할 수 있다. 게이트웨이는 HTTP의 RFC3339 확인 시각을 ROS Time으로 변환하고, 수신 시각은 UTC 문자열로 되돌린다. 신호 품질이 VALID가 아닌 수치 데이터는 null로 전달한다. 기존 DB 스키마와 MOCK 실행 방식은 유지한다.

생성 타입 경계 시험은 빌드 후 저장소 루트에서 실행한다. ROS 환경이 없는 일반 모의 시험에서는 이 시험 파일만 skip된다.

```bash
source /opt/ros/jazzy/setup.bash
source ws_cobot_pjt/ws_cobot1/install/local_setup.bash
cd ws_cobot_pjt/backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_ros_contract.py
```

PR #38의 ID→파일·미리보기 계약은 `app/artifact_loader.py`로 연결했다. 실제 `c2_path`와 HMI HTTP 경로 생성·조회 시험을 수행했다.
공정 노드와의 실행·실기 통합은 별도다. MOCK 경로를 ROS 상대에게 보내거나 test_only 경로로 공정을 시작하지 않는다.

이전 고객 웹앱·서버 초안은 개발 PC에 별도로 보존했다. 이 게시본에는 새 모니터를 실행하는 코드만 포함한다.

REAL 실기 시험 연결 및 배포 실행 설정은 [9/22 HMI 계약](../docs/HMI_REAL_EXECUTION_20260922.md)을 따른다. 운영자는 이미지만 업로드하며 JSON/ZIP 교환 단계는 없다.

랜선 없는 실제 HMI·경로·공정 ROS 통합은 [가상 장치 실행 안내](../docs/VIRTUAL_CELL_20260922.md)를 따른다. SIMULATION 전용이며 실물 드라이버는 실행하지 않는다.

HMI는 실행 중 받은 ProcessState의 최종 실패 사유를 즉시 표시한다. Action 최종 응답을 기다리는 동안은 `execution_pending`으로 새 작업을 차단하며, 이전 응답은 해당 실행 기록만 갱신한다. UNKNOWN과 미확인 정지는 상태 토픽의 성공만으로 해제하지 않는다. 공정이 준비 스냅샷 연결을 거절하면 HMI의 준비 상태도 무효화하여 재준비 필요 사유를 표시한다. 서버 재시작으로 결과가 미확인된 준비는 저장된 진행 단계만으로 자동 해제하지 않는다.
