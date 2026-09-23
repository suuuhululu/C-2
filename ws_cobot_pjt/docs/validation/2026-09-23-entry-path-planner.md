# 통합·실기 검증 기록 · 실행 전 entry 계획

- 시험명 / 작성자 / 확인자 / 날짜: HOME→entry→첫 APPROACH 내부 계획 회귀검사 / Codex / 팀장 확인 대기 / 2026-09-23
- Issue / PR / 시험한 커밋: PR 생성 전 작업 브랜치 `codex/entry-path-planner`, 기준 `48a4756`
- 시험 수준: 구문 / 모의 응답
- 실제 실행 PC·ROS·패키지·제어기·그리퍼 버전: 일반 Python 환경, ROS·제어기·로봇 미사용
- 공작물·지그·TCP·하중·좌표계 등 적용 조건: 합성 원통·Mock 어댑터, `c2_base`, m·quaternion xyzw
- 현장 절차에 따른 실행 전 확인: 실제 장비 시험이 아니므로 미수행

| 시나리오 | 기대 결과 | 실제 결과 | 통과·실패·미수행 | 증거 |
| --- | --- | --- | --- | --- |
| 상대 높이 후보 선정 | IK 한계·특이점 실패 후보를 제외하고 통과 후보 확정, 모션 없음 | 모의 330/320 후보 거절·310 상당 상대 후보 선택, move 0회 | 통과 | `test_entry_planner.py` |
| 후보 전부 실패 | `ENTRY_PATH_UNAVAILABLE`, 모션 없음 | 기대와 일치 | 통과 | `test_all_candidates_fail_closed_without_motion` |
| 계획 해시 변경 | 실행 전 `PROFILE_MISMATCH` | 기대와 일치 | 통과 | `test_checked_plan_executes_once_and_mutation_is_rejected` |
| 공정 호출 순서 | PRECHECK→ENTRY→ENGRAVE, ENTRY 실패 시 조각 차단 | 기대와 일치 | 통과 | 신규 state machine·node 시험 |
| 기존 공정 계약 | 준비·정지·중복·깊이·관절 검사 회귀 없음 | 423 passed, 1 skipped | 통과 | 아래 pytest 명령 |
| 전체 c2_process(외부 backend 의존 시험 제외) | 기존 공정 모듈 전체 회귀 없음 | 911 passed, 5 skipped | 통과 | 아래 pytest 명령 |
| 실제 IK·entry 이동·조각 | 별도 감독 승인 뒤 수행 | 수행하지 않음 | 미수행 | 없음 |

- 실행 명령과 결과:
  - `python3 -m py_compile ...`: 통과
  - `python3 -m pytest -q test_entry_planner.py test_state_machine.py test_execution_plan.py test_node.py`: `423 passed, 1 skipped`
  - `python3 -m pytest -q ws_cobot_pjt/ws_cobot1/src/c2_process/test --ignore=.../test_measurement_execution_offset.py`: `911 passed, 5 skipped`
  - 전체 디렉터리 수집은 backend 고정 의존성 `pydantic==2.13.5`가 현재 Python 환경에 없어 `test_measurement_execution_offset.py` import에서 중단. 코드 실패로 기록하지 않으며 해당 결합 시험은 의존성 설치 환경에서 재수행 필요
  - `python3 tools/check_repository.py`: 238개 파일 텍스트·구문·상대 링크 통과
  - `python3 tools/test_git_hooks.py`: 8건 통과
  - `python3 tools/issue_manager.py && python3 tools/test_issue_manager.py && git diff --check`: 설정 정상·27건 통과·diff 오류 없음
- 반복 횟수 / 성공·실패 횟수 / 시간 측정 방법: 관련 pytest 재검증 2회와 전체 공정 pytest 1회, 코드 실패 0
- 실패 원인과 후속 Issue: 없음. 다만 REAL 정책값·전체 메시 충돌·실제 제어기 IK·감독하 모션은 후속 검증 필요
- 미확인 한계: 단순 원통과 도구 끝↔TCP 선분 간격만 검사하며 전체 그리퍼 메시 충돌을 증명하지 않음
- 시연에 사용할 커밋·영상·발표 자료 연결: PR 생성 후 커밋·PR 번호 추가 필요
