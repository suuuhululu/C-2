# HMI 선행 수정 · 관측 캐시 연결 전

> 이전 선행 작업 기록이다. 최신 main 반영과 ROS SIM 연결은 [최종 HMI 통합 준비](HMI_INTEGRATION_20260921.md)를 우선한다. 아래 ROS 미연결 항목은 당시 상태다.

## 기준과 범위

2026-09-21. 원격 main `2e94e5d`(PR #51 포함)를 fetch 후 확인했다. 현재 작업 브랜치는 `codex/hmi-preparation-flow`, HEAD `8c8fb5c`다. 기존 미커밋 HMI 작업을 보존하며 이어서 수정했다. HEAD..origin/main에 backend/frontend 변경은 없었고, 원격 제어 코드와 PrepareWorkpiece 타입을 별도로 대조했다. main 전체를 현재 작업 파일에 병합한 것은 아니다.

이번 작업은 HMI 프런트/백엔드·시험·문서만 대상으로 한다. 제어 노드의 관측 수집/캐시·모션 코드는 수정하지 않았다. 기존 `.action`·`.msg`·`.srv`의 이름/필드는 변경하지 않았다. 준비 Action 생성 파일은 이전 작업 산출물이며 이번에는 소비자 연결 코드를 추가했다.

## 구현한 것

- 준비 입력에서 `operator_confirmed_drill_fixed`, `operator_confirmed_gripper_closed`, `operator_confirmed_drill_off`, 이 용도의 `confirmed_at`을 제거. HTTP 준비 입력은 `request_id`, `input_profile_snapshot_id`, `input_profile_sha256`, `height_m`이다. 과거 기록은 원본 유지. 구형 입력은 422로 거절한다.
- 측정 전 수동 OFF, 그리퍼 개폐 금지, 종료/취소 후 수동 OFF 안내. 모의 진행에 홈 확인→홈 이동→재검사→접촉→정상 후퇴 표시를 추가. 실제 모션 구현이 아니다.
- 드릴 ON 체크는 화면 실행 버튼에만 적용. 경로/설정/준비/공정 세션/실행 상태/화면 변경, 연결 상실, 요청·취소·정지·초기화에서 재사용을 차단한다. 새 실행 요청 시 소비하고 불확실 응답의 동일 요청 재조회와 구분한다. HTTP/ExecuteProcess에 ON 필드 없음. 직접 API 요청에서 ON을 보증하는 기능도 아님.
- 준비 Action 결과와 별도의 상시 관측 패널: 공정 단계, 관절 rad, 제어기 TCP m/좌표계, 로봇·그리퍼 품질, 출처, 정지 상태, 실제 관측 시각 표시. 정상 heartbeat만으로 값이 최신이 되지 않는다. 품질이 VALID가 아니거나 표시 상한 2초 초과/시각 누락/미래 시각이면 수치 사용을 차단한다. 이 2초는 화면 보호 상한이며 제어 안전 판정이나 관측 주기 계약 변경이 아니다.
- 준비 접수 응답 미확인은 같은 ID를 우선 GET 조회. 재연결·제어 세션 변경 시 기존 성공 준비의 재사용을 백엔드에서도 차단. 부분/실패 기하의 기본 0을 실제 기하로 표시하지 않는다.
- `RosBridge.prepare_raw()`로 기존 PrepareWorkpiece MEASURE/BIND 요청·Feedback·Result 전송 경계 추가. 표준 CancelGoal 사용. 요청 식별자·설정 참조 대조와 BIND 완료 근거 검사. 원본 Time `{sec,nanosec}`·Pose·배열을 보존해 향후 저장 원본의 BIND 대조가 가능하다. PrepareWorkpiece 미설치 시 기존 ROS 경로 시험은 유지하며 준비 요청만 거절한다.

## 아직 연결하지 않은 것

**ROS 준비 버튼은 계속 비활성, REAL 기동/실행은 계속 차단한다.** 위 클라이언트 메서드를 추가한 것이 HMI HTTP → MEASURE → 원본 저장 → BIND → 동적 경로 생성의 완전 통합을 뜻하지 않는다.

후속 작업은 다음과 같다.

1. 세은/시율: 실제 관측을 기존 공정 캐시에 지속 공급하고 준비 단계/오류를 ProcessState에 반영. 측정 중 취소·정지·관측 동시 동작 검증.
2. HMI: 배포할 `prepare-workpiece-config/1`의 승인된 SIM/REAL 원본 등록 경로, Result→화면 표시 변환, `prepare-workpiece-result/1` 원본 저장, BIND 원장 연결. 현재 MOCK 설정/원본을 그대로 ROS BIND 입력으로 보내지 않음.
3. 홍동/HMI: 동적 실측 profile 버전과 소비 계약을 확인하고 같은 ID/해시로 경로 생성. 기존 고정 test_only 프로파일을 임의 변경하지 않음.
4. 위 계약으로 격리 ROS SIM 통합 시험 후 준비 버튼 활성화 검토. REAL은 현장 관측·오프셋·정지·관절/모션 검증 별도.

## 적용 방법

프런트 `tsc -b` 및 `vite build` 후 백엔드를 재시작한다. 기존 데이터는 보존하며 구형 프런트는 새 HTTP 준비 입력과 맞지 않으므로 함께 갱신한다. 실제 운영 중인 서버를 이번 작업에서 재시작하지 않았다. 화면 검증은 임시 DB의 별도 MOCK 서버로 수행한다.

## 검증

- 관련 backend 7개 시험 파일: **91 passed**, Starlette의 기존 deprecation warning 1건. `test_preparation`, `test_monitor`, `test_preparation_bridge`, `test_ros_contract`, `test_generation_cancel`, `test_work_area`, `test_path_artifacts`.
- frontend Node 시험 4개 파일 통과. TypeScript 및 Vite production build 통과.
- Jazzy c2_interfaces 독립 타입 빌드 성공(`/tmp/c2-hmi-type-SzJOH4`). 생성된 준비 Result의 Time·Pose·배열 원본 변환까지 검사. 모의 자료만 사용, 로봇/공정 서버를 실행하지 않음.
- 임시 DB의 MOCK 브라우저 시험: 준비 요청/진행/8점 최종 결과, 경로 생성, ON 미체크 시 실행 차단/체크 후 활성화, 화면 전환 후 ON 해제/실행 재차단, 새로고침 초기화 확인. 실제 조각 요청·드릴/로봇 제어는 하지 않음. 시험 서버와 탭 종료.
- `check_repository.py` 205개 파일, `git diff --check` 통과.
- 확장 전체 backend 실행에서는 파일 교환 `result.json` 필드 불일치 3건과 구형 별도 앱 SVG 엔진 부재 관련 10건이 남았다. 해당 파일/엔진은 이번 수정 대상이 아니며 변경하지 않았다. 최초 실행의 추가 준비 타입 변환 오류는 수정하고 위 91개 시험으로 재검증했다. 전체 시험 통과로 보고하지 않는다. 실제 ROS 서버 통합 시험 4건은 환경 조건으로 skip되었으며 실기와 무관하다.

재현: Jazzy와 위 임시 install의 `local_setup.bash`를 source한 backend에서 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_preparation.py tests/test_monitor.py tests/test_preparation_bridge.py tests/test_ros_contract.py tests/test_generation_cancel.py tests/test_work_area.py tests/test_path_artifacts.py -q`.
샌드박스의 로컬 스레드 통신 대기로 FastAPI TestClient 시험은 제한 밖에서 수행했다. 저장소 기본 DB는 사용하지 않았다.

결과는 미커밋 작업 파일이며 commit/push/PR/병합하지 않았다. 실제 관측 공급·ROS 준비 HTTP 활성화·동적 스냅샷 통합·실기 검증은 위 후속 작업으로 남는다.
