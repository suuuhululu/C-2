# Interface Specification 코드 대조 기록 · 2026-09-25

- 시험명: 최신 main 인터페이스 코드·문서 일치 점검
- 기준 커밋: `origin/main` `987a3b72b29e7224be62e6bdfa6ab40b744375aa` (PR #90 병합)
- 작업 브랜치: `codex/interface-spec-20260925`
- 시험 수준: 정적 코드 검토 / 문서 링크·형식 / 프런트 빌드 / 백엔드 pytest / ROS 2 빌드·모의시험
- 실기 실행: 미수행. 로봇과 두산 제어기를 기동하거나 모션을 호출하지 않음

## 확인한 코드 원본

- `backend/app/monitor.py`, `monitor_contract.py`, `monitor_service.py`, `preparation.py`, `ros_bridge.py`, `ros_preparation.py`
- `frontend/src/monitor/api.ts`
- `c2_interfaces`의 Action 3개, Service 1개, Message 2개 원본
- `c2_process/state_machine.py`, `c2_process/node.py`
- `c2_path/node.py`

## 코드와 문서의 불일치

| 항목 | 코드 확인 | 문서 상태 | 조치 |
| --- | --- | --- | --- |
| entry 활성 prepared 정상 단계 | `PRECHECK → ENTRY → ENGRAVE → RETURN_HOME → FINISH`; entry 비활성 호환 흐름은 두 콜백 생략 가능 | 주요 현재 문서가 `RETURN_HOME` 또는 조건을 누락 | 현재 가이드·README·공통 타입 주석 수정 |
| HOME 복귀 연결 | coordinator가 검사된 `prepared_return_home` 전달 | 공정 README가 미연결로 표시 | 정상 성공 경로 연결과 실패 후 자동 복귀 금지를 구분 |
| 준비 Action | HMI 서버·RosBridge·공정 ActionServer가 사용 | 공통 타입 README가 권장안/통합 전으로 표시 | 현재 연결 상태로 수정 |
| HMI API | HTTP·WS 라우트와 검증·제한 시간 구현 | 주요 API 이름만 안내 | `INTERFACE_SPECIFICATION.md`에 요청·상태·오류·시간·중복/정지 계약 작성 |

날짜가 붙은 과거 실기·검증 기록은 당시 실제 결과를 보존하기 위해 현재 흐름으로 덮어쓰지 않았다.

## 실행한 검사

| 검사 | 결과 | 비고 |
| --- | --- | --- |
| `git diff --check` | 통과 | 공백 오류 없음 |
| `python3 tools/check_repository.py` | 통과 | 텍스트·Python 구문·상대 링크 259개, ROS/실기 아님 |
| `python3 tools/test_git_hooks.py` | 통과 | 8개 |
| `python3 tools/issue_manager.py` | 통과 | 읽기 전용 설정 확인, 네트워크·변경 없음 |
| `python3 tools/test_issue_manager.py` | 통과 | 27개 |
| `pnpm --dir ws_cobot_pjt/frontend build` | 통과 | TypeScript·Vite 빌드 |
| 백엔드 핵심 pytest | 통과 | 기존 `backend/.venv` 사용, 모니터·준비·취소·복구·완료 표시 71개 통과 |
| 백엔드 ROS 계약 pytest | 통과 | Jazzy와 새 overlay source 후 10개 통과 |
| ROS 2 새 빌드 | 통과 | Jazzy + 기존 `dsr_msgs2` overlay, `c2_interfaces`·`c2_path`·`c2_process` 3개 패키지 |
| `c2_interfaces` colcon test | 통과 | 생성 타입 계약 18개 통과 |
| `c2_path` pytest | 통과 | 기존 백엔드 가상환경의 `scikit-image` 사용, 237개 통과 |
| `c2_process` 인터페이스·상태 흐름 pytest | 통과 | node·준비 Action·상태 관측·상태 머신·HOME 복귀 417개 통과, 2개 환경 의존 시험 건너뜀 |
| `c2_process` 전체 모의 pytest | 실패 있음 | 1,018개 중 951개 통과·2개 건너뜀·65개 실패. 양초 접촉 모의시험 계열이 `CONTACT_NOT_FOUND`로 집중 실패 |
| 원본 `colcon test` 일괄 실행 | 실패 있음 | 시스템 Python에 `python3-skimage` 미설치로 `c2_path` 수집 중단, `c2_process`는 pytest 등록이 없어 0개/종료 코드 5 |
| 실제 M0609 | 미수행 | 문서·정적 검토 범위 |

## 미확인 한계

- 실행 PC의 설치된 `c2_interfaces`와 `origin/main` 필드 일치 여부
- 실제 M0609에서 prepared `RETURN_HOME` 전체 이동과 정지·실패 시 단계 차단
- 실제 네트워크에서 HTTP·WebSocket·DDS 제한 시간과 복구 절차
- 반복 조각 품질과 운영자 검사 판정
- `c2_process` 양초 접촉 모의시험 65개의 `CONTACT_NOT_FOUND` 회귀 원인과 기대값 갱신 필요 여부
- ROS 패키지 시험 의존성(`python3-skimage`) 설치 및 `c2_process` pytest를 `colcon test`에 등록하는 패키징 보완

백엔드와 ROS 2가 로컬에서 실행 불가능한 것은 아니다. 최초 실패는 시스템 Python과 백엔드 가상환경을 구분하지 않은 실행에서 발생했다. 위 재검증으로 백엔드 핵심 기능, ROS 계약, ROS 빌드는 확인했으며, 남은 두 항목은 제품 실행 불가가 아니라 전체 시험 환경·모의시험 회귀로 별도 기록한다.
