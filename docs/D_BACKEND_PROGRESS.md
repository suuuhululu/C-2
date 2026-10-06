# 수현 Day4 Backend·HMI 진행 기록

갱신: 2026-10-06. 합의한 **원격 개발 0~7단계**를 진행했다. 현재 실행은 명시적 FAKE 전용이며 실제 Robot Controller·Camera·팀 모듈 연결과 사람 조립 시연은 미완료다.

## 구현한 범위

| 단계 | 입력 → 출력과 책임 | 주요 파일 |
|---|---|---|
| 0 | 최신 계약·역할·24×24 HMI 시안과 원격 개발 범위 확인 | 이 기록과 단계별 로컬 STATUS |
| 1 | Design/Plan/Observed·HMI 입력 → 구조·필수값·지원값 검사. 전체 기하 검증은 세은 담당 | [contracts.py](../app/contracts.py), [hmi_contracts.py](../app/hmi_contracts.py), [공통 Schema](../interfaces/schemas/day4.schema.json), [HMI Schema](../interfaces/schemas/hmi.schema.json) |
| 2 | visible_blocks/verified_regions·check/seq → 가림 유지·빈 영역 반영·실제 Current/revision | [current.py](../app/current.py) |
| 3 | 채택 당시 고정 Current·Step 효과·Observed → Expected/Difference·Step/전체 Design 완료 | [completion.py](../app/completion.py) |
| 4 | 명령·Fake callback → 단일 Job/Step/실행·전달/조립 분리·STOP/재개 | [backend.py](../app/backend.py) |
| 5 | Backend 상태·주요 이벤트 → snapshot·Job별 JSONL | [snapshot.py](../app/snapshot.py), [jsonl_log.py](../app/jsonl_log.py) |
| 6 | snapshot → 반폭 고정 Qt 단일 창·24×24 도식. 버튼 → 식별이 붙은 Backend 명령 | [qt_hmi.py](../app/qt_hmi.py), [hmi_board.py](../app/hmi_board.py), [fake_demo.py](../app/fake_demo.py) |
| 7 | Fake KEEP/REVISE/UNCLEAR·Planner 결과 → 의도 확인·사람 정리·최신 기준 재계획 | [replan.py](../app/replan.py) |

공통 필드는 brick_type, color, x, y, layer, orientation_deg다. Day4는 PLACE·4/6점·노랑/파랑·24×24점·최대 4층이다. MOVE/REMOVE·DB·재고 수량 검사·자동 Robot 복구·Camera 재시작·앱 종료 후 복원은 구현하지 않았다. 다른 담당 알고리즘은 [day4 Fixture](../interfaces/fixtures/day4.json)와 [HMI Fixture](../interfaces/fixtures/hmi.json)로 연결했다.

## 검증과 한계

- 게시 준비 중 현재 로컬 저장소 전체 검사: `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` → **397 passed**, 종료 코드 0. 다른 작업의 팀 연결 소비 검사 17개를 포함한 수치다.
- 최신 main과 게시 대상 파일만 모은 별도 디렉터리에서 전체 검사: **380 passed**, 종료 코드 0. 같은 디렉터리에서 안내한 Qt 없는 Backend/로그/Replan 검사도 **63 passed**, 종료 코드 0. 순수 계약/Current/Expected 검사와 Fake Backend·로그·Replan·Qt offscreen 검사를 구분한다. Qt 검사는 실제 모니터·장치 시험이 아니다.
- 정상/가림 유지/확인한 빈 영역/실제 차이 채택/revision 변화/고정 Expected/중복·역순·닫힌 check/전달과 조립 완료 분리/STOP 확인/로그 실패/KEEP·REVISE·UNCLEAR/재계획 중 Current 변경을 검사했다.
- 이전 별도 Qt 실행에서 정상·KEEP·REVISE·불명확 후 명시 선택은 COMPLETE, HRI 실패는 HOLD로 종료했으며 Job JSONL과 화면을 확인했다. 이것은 고정 Fake 시나리오 결과다.
- lint/type check/CI는 이 개발 범위에 미구성이다. 새 도구를 설치하거나 검사 규칙을 완화하지 않았다. PyQt5는 현재 환경에 설치된 라이브러리를 사용했다.
- 실제 A/B/C 생산자 반환과 실패/지연 adapter, 실제 촬영·전달판 판별, Controller 슬롯 소모·물리 STOP/재개, 장치 L3/L4와 전체 사람 조립 시연은 미검증이다.

## 진행 중 조정한 내용

1. 닫힌 Step check의 늦은 EMPTY 대신 새 전달판 비움 check를 자동으로 연다.
2. STOP 재개에서 전달 재요청과 observe point 복귀를 구분하고 새 실행 ID를 사용한다. 정지·이전 실행 종료·블록 상태 확인 없이 진행하지 않는다.
3. 관측 화면은 동일 촬영의 값·식별을 표시한다. 관측 블록별 열은 목록 순서이며 물리 블록 대응을 추정하지 않는다.
4. 늦은 결과는 원래 요청의 Job/Plan/Step 로그에 연결한다. 로그 저장 실패는 다음 실행을 막되 STOP 요청은 허용한다.
5. READY가 와도 Current 재관측이 판단 불가이면 보관 후 보류한다. 실제 revision이 바뀌면 이전 결과를 닫고 최신 기준으로 요청한다.
6. UNCLEAR 안내 뒤 새 질문 UUID를 사용한다. 중복 응답·자동 재질문 반복·자동 KEEP으로 진행하지 않는다.
7. 새 후보 Design은 유효한 Plan과 함께 채택한다. 빈 Remaining만으로 최종 완료를 선언하지 않는다.

## 규모와 사람 검토

이 게시에는 승인받아 나누어 개발한 여러 단계가 누적돼 있다. Backend는 약 370줄로 권장 모듈 규모를 넘지만 단일 상태 Owner와 요청 식별을 유지한다. snapshot 생성과 Qt 창 구성도 권장 함수 길이를 넘는다. 줄 수만으로 계층을 늘리지 않고 독립 책임/검사 단위로 분리했다. 신규 DB·Factory/Manager·추상 계층은 없다. 누적 코드량과 여러 신규 파일은 AI 코드 정책의 사람 리뷰 대상이며, 자체 검사로 사람 리뷰를 대체하지 않는다.

## 게시와 다음 작업

GitHub 게시 기준은 최신 main `6fde225c0d8ae46d827174dec5e6a3379559605b`이다. 그 위에 수현 파일과 이 기록/실행 안내/STATUS 요약만 추가한다. 최신 팀 문서와 C 코드는 유지한다. 로컬 `work/suhyun-hmi-backend-robot-db`는 옛 독립 이력에서 만들어졌으므로 브랜치 전환·reset·rebase 없이 작업 파일과 기존 미커밋 변경을 보존한다. 원격에 같은 이름의 브랜치를 올리는 것은 로컬 이력 동기화나 main 병합을 뜻하지 않는다. 이후 로컬 이력 통합 방식은 별도 결정이 필요하다.

공용 STATUS의 다른 작업 내용, README/AGENTS/팀 문서의 기존 미커밋 변경, 발표 자료, 다른 담당 Fixture/검사는 이번 게시에 섞지 않는다. 로컬 상세 STATUS 이력은 보존하고 공용 원격 STATUS에는 이 문서 링크와 최신 결과를 추가한다.

다음은 [실행 안내와 Robot 단계별 계획](D_BACKEND_RUN_ROBOT_PLAN.md)의 Robot 0단계 검토다. 계약 항목을 다시 채워 달라고 요청하는 것이 아니라, 실제 driver가 확정 계약과 같은 결과를 내는지 및 어떤 정지/집기 증거를 제공하는지 확인한다.

## 2026-10-06 — 실제 A Planner 연결 검증

세은의 a_manual_execution.tar.gz를 읽고 원격 work/seeun-planning의 f9b841c8f090b0b25c30ab27459781ad2017fd9e에서 planning_trial을 수정 없이 가져왔다. Planner 소스 SHA-256이 첨부 실행 기록과 일치한다. C의 첨부 Mock Initial/Revised 응답을 받아 실제 A 함수를 D에 연결했다. Initial 성공 응답은 on_initial_design으로 받으며, design이 있는 planner 요청은 run_planning_request로 실행한다. C에 Current blocks 목록을 전달하는 helper와 성공 HRI 응답 연결도 준비했다. 실제 C/LLM/음성 함수는 호출하지 않았다.

빈 Current READY 15 Step, 부분 Current READY 11 Step, 색상 차이 NEEDS_CORRECTION, 5층 INVALID를 A 실제 함수로 재현해 D 채택/보류·Qt·JSONL을 확인했다. 네 관측 Step의 Current revision=4로 재계획하면 11 Step이며 base_current_revision=4다. 첨부 묶음 Current의 revision=1 사례와 구분한다. 이동된 Current를 유지하는 C Mock Revised v2와 실제 A의 11 Step을 채택해 FakeRobot·관측으로 전체 완료했고, 별도 정상 15 Step도 전체 완료했다. 전달 성공만으로 Step/Current를 완료하지 않는다. Revised에서 누적 공급 6개 이후 보충 대기·명시 보충·새 EMPTY를 유지했다.

첫 Plan 채택 전 사람 정리 재관측의 이전 미연결 제한을 해소했다. D 내부 check의 plan_id/step_id를 둘 다 null로 허용하고 가짜 Plan/Step을 발급하지 않는다. Vision 외부 callback 필드는 바꾸지 않았다. 이 문맥은 Current 채택만 가능하고 조립 Step 완료 증거가 될 수 없다. 단위·통합 검사를 추가했다. startup의 실제 빈 보드 관측 자동 연결은 이번 범위가 아니다.

최종 코드 변경 후 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` → **707 passed**, 종료 코드 0. A 독립 검사 **112 passed**, 새 실제 A/D 연결 검사 **24 passed**, 각각 종료 코드 0. Qt는 offscreen, Robot/Observed는 Fake이며 실제 장치 성공이 아니다. [실행 결과 JSON](../logs/a-backend-connection-guy8gbim/results.json)과 같은 폴더의 시나리오별 Job JSONL을 보존했다. logs는 로컬 산출물로 원격 clone에 없다. lint/type는 미구성이고 새 dependency를 설치하지 않았다.

[연결 안내](D_A_PLANNER_HANDOFF.md)에 호출법·범위·남은 작업을 갱신했다. 기존 3-Step FakeDemo는 별도 독립 시험용으로 유지한다. C 실제 호출의 다른 인자·Difference 변환·음성/질문·취소 Workflow, B 실제 callback·촬영, 실제 Robot driver/pose/STOP/재개는 남아 있다. 자동 복구·DB·MOVE/REMOVE·미검증 pose를 추가하지 않았다. 로컬 작업 브랜치와 기존 미커밋 변경을 보존하고 이번 PR에서 연결 코드와 검증 기록을 게시한다. main 병합은 하지 않는다.


이번 게시에는 A–D 통합이 사용하는 Fake Robot Controller·driver와 관련 검사도 포함한다. 별도 작업의 REAL 장치 시험·터미널 수동 입력 HMI·발표 자료·팀 공통 문서 변경은 포함하지 않는다. 707개는 로컬 전체 검사이며, 게시 파일과 최신 main을 합친 독립 검사 결과는 PR에 별도로 기록한다.


PR 게시 대상과 최신 main을 합친 독립 파일 트리에서 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` 실행: **884 passed**, 종료 코드 0. main의 C 검사도 포함하며, 별도 REAL 장치 시험·수동 입력 HMI 검사는 이번 게시 범위에서 제외한다. 실제 Camera/Robot 시험은 수행하지 않았다.

## 2026-10-06 — 누적 D 수정 PR 게시 준비

사용자가 지금까지의 수정사항을 PR로 요청했다. PR #9와 B PR #10이 병합된 최신 main `7c51549efb90e0b324a21351b7109dc473a7bda9`에 수현의 후속 수정만 적용한 독립 파일 트리를 검사했다. 로컬 지정 브랜치/HEAD/미커밋 파일과 기존 원격 브랜치를 유지하며, 최신 main에서 만든 별도 게시용 원격 브랜치 `work/suhyun-day4-integration-updates`에 후속 수정만 게시한다. GitHub 연결 API의 쓰기 권한 오류로 로그인된 웹 업로드를 사용한다. 로컬 파일이나 팀원 소스를 최신 main으로 일괄 덮어쓰지 않는다.

포함: Robot 한 블록·3-Step 수동 시험 진입점/설정, FAKE 단계 입력·STOP/재개, 현장 잘못 놓음 신고/좌표 표시, A–B–D 합성 callback·C 저장 응답 재계획, HMI 블록 비율, 관련 Consumer Schema·검사·실행 안내/진행 기록. 별도 history DB/컨테이너 작업·발표/제출 자료·미완료 공통 문서는 제외한다. A/B 원본과 main의 실제 C 코드는 동일 바이트를 유지한다.

게시 파일 트리에서 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` → **1045 passed**, 종료 코드 0. main의 C 독립 검사와 D 후속 검사를 포함하며 별도 history 검사는 포함하지 않는다. 앞선 로컬 852 passed/11 skipped는 파일 구성이 다른 당시 기록이다. 실제 Camera/Robot 연결 성공 또는 GitHub CI 결과가 아니다.

Robot 관련 검사는 이 호스트의 `source_path`/`measurements_path`가 가리키는 기존 자료 파일을 사용한다. 다른 PC/clone에서 해당 파일이 없으면 전체 Robot 시험 검사는 그대로 재현되지 않는다. 실제 시험 진입점은 원본/측정 SHA 확인과 명시 실행을 유지하며 경로·TCP·pose·속도를 이번 게시에서 변경하지 않았다. 장치 시험 기록은 사용자 보고와 모의 검사를 구분한다. C 저장 JSON 시험은 저장소에 보관한 Fixture 경로로 실행할 수 있다. 로그/PNG는 Git 제외인 로컬 산출물이다.

원격 PR은 사람 검토용 초안으로 준비하며 실제 STOP/재개·B production callback/Camera·C 함수/LLM/음성·전체 사람 조립 연결은 미검증이다. main 병합/실제 장치 실행은 하지 않는다.
