# 수현 Day4 Backend·HMI 진행 기록

> 2026-10-07 적용: 현재 제품 목표는 [최종 MVP](10_FINAL_MVP.md)입니다. 아래는 전달형 Day4 Backend/Qt·Robot 연결의 단계별 구현·시험 기록입니다. 최종 커스텀 의자 대화/확정·직접 결착·지지·세 단계 종료·사용자별 DB/웹의 구현 진도로 환산하지 않습니다. 새로운 현재 상태와 필요 이행은 최종 MVP와 STATUS 상단을 확인합니다.

갱신: 2026-10-06. 합의한 **원격 개발 0~7단계**를 진행했다. 현재 실행은 명시적 FAKE 전용이며 실제 Robot Controller·Camera·팀 모듈 연결과 사람 조립 시연은 미완료다.

별도 Robot 개발은 사용자 **6단계까지 승인** 후 5단계 조회와 6단계 첫 실행까지 진행했다. 첫 실행은 HOME의 ROS float64 변환에서 abort됐고 입력 타입을 수정한 뒤 조회/직렬화만 재검증했다. 단일 전달/복귀 재실행은 미수행이다. 현재 Qt 예제는 Fake Controller/driver에 연결돼 있으며 실제 한 블록 시험 실행부는 HMI와 별개다. 아래 이전 기록은 그 시점의 상태이며 최신 결과는 STATUS를 따른다.

2026-10-06 Robot 6단계 첫 실패 보완: 원본 CLI의 argparse float와 JSON int 차이로 `vel=20`의 C 변환이 중단됐다. 유효 수치를 float로 정규화하고, 원본 이동 호출을 실제 ROS Request로 직렬화하는 송신 없는 사전 검사를 추가했다. 순수 관련 검사 **105 passed**, 전체 **511 passed**, 실제 `--check` **37점 IK/FK·15개 이동 메시지 변환 성공**, 각각 종료 0. 최초 실행 로그와 사용자 설정을 보존했다. 실제 재집기/복귀/STOP 시험을 대신 수행하지 않았다. 다음은 사용자의 한 블록 재실행과 현장 결과 확인이며 상세는 [STATUS](STATUS.md)다.

2026-10-06 Robot 5단계 추가: [robot_trial.py](../app/robot_trial.py), [가변 실제 시험 설정](../interfaces/robot_trial.json), [독립 검사](../tests/unit/test_robot_trial.py)를 추가했다. 원본 해시·기존 경로/속도 보존, 2번 슬롯 한 번만 선택, 상승 후 grip 확인/소모 기록·놓기/복귀·실패 보류·자동 재시도 없음·명시 실행 모드를 검사했다. 사용자 제공 observe posj/posx와 확인한 HOME→observe 경로를 설정에 저장했다. 실기 원본/기존 Fake 구현은 수정하지 않았다. 실제 M0609/RG2 읽기와 원본 경로 37점 IK/FK 조회 성공(종료 0), **이동/개폐 없음**. 6단계 실제 전달·7단계 STOP/재개·Camera/실제 HMI binding은 미수행이다. 상세 검사/파일 범위는 [STATUS](STATUS.md), 실행법은 [안내](D_BACKEND_RUN_ROBOT_PLAN.md)에 기록한다.

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

- Robot 4단계 후 현재 전체 재실행: **485 passed**, 종료 코드 0. Qt 없는 Controller/Backend 연결 **79 passed**(Controller 60개·연결 19개), Qt offscreen **20 passed**, 각각 종료 코드 0. 정상 3 Step·세 STOP/재개 경로·보충·실패/timeout·모순된 준비 증거·오류 후 정리/새 Job·로그 실패 시 다음 이동 차단·외부 파일 설정/Fixture를 확인했다. 기존 Backend/HRI/Replan 검사와 팀 연결 소비 검사 17개도 전체에 포함된다.
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

2026-10-06 추가: 사용자의 Robot 1단계까지 승인에 따라 [기존 제어 점검과 Controller 경계 설계](D_ROBOT_CONTROLLER_DESIGN.md)를 작성했다. 기존 goal/result·STOP/재개 경계를 유지하고 원본/과거 실기 설정을 보존했다. 신규 Controller 코드는 없으며, 다음은 [실행 안내와 Robot 단계별 계획](D_BACKEND_RUN_ROBOT_PLAN.md)의 2단계 Fake 정상 전달·슬롯 구현이다. 실제 driver가 확정 계약과 같은 결과/정지/집기 증거를 제공하는지 확인하는 작업이며 팀원에게 계약 항목을 다시 작성하라는 요청이 아니다. 이 추가 기록은 로컬 작업이며 직전 게시 커밋 55e33cc에 자동 포함되지 않는다.

추가 설계 요구: observe point·pose/동작 값·공급 설정·팀 모듈 연결·Day4 이후 지원 범위를 변경 가능한 설정으로 분리한다. 새 Controller는 검증한 설정을 주입받고 활성 Job에서 고정하며, 변경 값은 검사 후 다음 Job에 적용한다. 기존 전체 코드가 이미 가변화됐다는 의미는 아니다. 2단계 Fake 설정 주입, 4단계 Backend/HMI/설정 로그 연결, 5단계 실제 driver 설정으로 나누어 검증한다.

2026-10-06 Robot 2단계 추가: 사용자 승인으로 [Controller](../app/robot_controller.py), [Fake driver](../app/fake_robot_driver.py), [외부 설정 Fixture](../interfaces/fixtures/robot.json), [독립 검사](../tests/unit/test_robot_controller.py)를 구현했다. 단일 실행·정상 집기/놓기/관측 위치 복귀·집기 확인 때만 슬롯 1회 소모·네 열 독립 순서·6번 이후 해당 열 보충 대기/명시 보충·중복/역순/늦은 확인 차단을 검사했다. 설정 파일 경로·Fake 위치 이름·슬롯 수를 주입하고 생성 시 복사본을 고정한다. 새 dependency·ROS/실제 pose 없음. 독립 **41 passed**, Qt offscreen을 포함한 로컬 전체 **438 passed**, 각각 종료 코드 0. 직전 게시 때의 397/380 결과와 구분한다.

새 Controller는 아직 기존 Qt/Backend 예제에 연결하지 않았다. STOP/재개·실행 실패/timeout은 다음 승인 단위인 Robot 3단계, Backend/HMI/로그/설정 식별 연결은 4단계다. 실제 Camera/Robot/팀 생산자 연결은 미검증이다. 이 추가 코드는 로컬 작업이며 GitHub에 추가 게시하지 않았다. 3단계 Fake 검사는 현재 계약으로 가능하며 실제 연결 때 필요한 제공물은 위 설계의 검증된 장치 설정/API와 홍동의 실제 callback이다.

2026-10-06 Robot 3·4단계 추가: [Controller](../app/robot_controller.py)의 실패/STOP/재개를 독립 검증한 뒤 Backend의 기존 deliver/stop/resume·snapshot·JSONL·Qt 버튼에 연결했다. 집기 callback 누락 때의 정지 증거 채택, 다음 Step의 미집기 상태 구분, 복귀만 요청의 반복 STOP/재개, 오류 후 중복 STOP 차단을 조정했다. 새 goal/result·HMI Schema 필드는 없다. [연결 검사](../tests/unit/test_robot_backend.py)를 추가하고 기존 Controller/Qt 검사를 보완했다. 공급 보충 뒤 새 EMPTY 전 다음 집기는 없고, 장치 정리 확인만으로 Current/슬롯을 지우지 않는다. 새 START에서 초기 배치 확인·새 Job·슬롯/설정을 채택하며 이전 Job 로그를 보존한다. `--robot-config/--fixture/--delay-ms` 실행법은 [안내](D_BACKEND_RUN_ROBOT_PLAN.md)에 있다.

3·4단계 누적 변경은 기존 파일 11개와 신규 연결 검사 1개다. 실행 코드 약 350줄 변화와 검사 약 530줄 보완 및 직접 관련 문서가 포함돼 규모 검토 신호를 넘는다. 두 승인 단위로 순차 구현/검증했고 신규 클래스/계층/의존성은 없다. Backend는 436줄로 400줄 검토 신호를 넘지만 단일 상태 Owner를 유지한 연결 변경이며 줄 수만으로 분할하지 않았다. 추가 사람 리뷰는 아직 없다. 실제 driver 준비·안전·Camera/Robot·실제 팀 생산자 연결은 다음 별도 승인 범위이며 이번 추가 GitHub 게시는 없다.


## 2026-10-06 — A 결과 Consumer 연결 준비

사용자 승인으로 세은의 실제 실행 검증 커밋을 기다리는 동안 D 수신부를 `status / plan / errors`로 통일했다. PREPARING/REPLANNING에서 같은 Consumer를 사용하고 활성 request_id·버전·revision 채택 gate를 유지한다. 오류 배치와 null을 원본 진단으로 보존하며 Qt 기존 안내와 PLAN_RESULT JSONL에 전체 사유를 연결했다. FakeDemo·재계획 Fixture 및 테스트도 새 envelope로 맞췄다. 새 dependency·실제 A 호출·장치 동작·GitHub 게시 없음.

최종 코드 변경 후 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests/unit -q`: **550 passed**, 종료 코드 0. Schema/Fixture·Consumer·Backend·Qt offscreen·FakeRobot·JSONL을 포함한 단위 검사이며 실제 A/C/Vision/Robot 통합 성공이 아니다. 이번 신규 Planner 결과 검사 24개와 Qt 다중 오류 표시 검사 1개를 포함한다. 기존 lint/type 설정 파일은 확인 범위에서 없으며 새 도구를 설치하지 않았다.

상세 계약·예시·제한은 [A 연결 준비](D_A_PLANNER_HANDOFF.md)에 있다. 남은 일은 세은 새 커밋 확보와 실제 함수 호출, C의 Initial Design 입력 연결, 첫 Plan 채택 전 정리 후 재관측 연결이다. 최초 NEEDS_CORRECTION은 표시·전달 보류까지만 가능하고 정리 후 재관측은 명시적으로 미연결 처리한다. 기존 채택 Plan이 있는 재계획 정리 경로는 검증했다. 수현 브랜치와 기존 미커밋 변경을 보존했으며 commit/push하지 않았다.


## 2026-10-06 — 실제 A Planner 연결 검증

세은의 a_manual_execution.tar.gz를 읽고 원격 work/seeun-planning의 f9b841c8f090b0b25c30ab27459781ad2017fd9e에서 planning_trial을 수정 없이 가져왔다. Planner 소스 SHA-256이 첨부 실행 기록과 일치한다. C의 첨부 Mock Initial/Revised 응답을 받아 실제 A 함수를 D에 연결했다. Initial 성공 응답은 on_initial_design으로 받으며, design이 있는 planner 요청은 run_planning_request로 실행한다. C에 Current blocks 목록을 전달하는 helper와 성공 HRI 응답 연결도 준비했다. 실제 C/LLM/음성 함수는 호출하지 않았다.

빈 Current READY 15 Step, 부분 Current READY 11 Step, 색상 차이 NEEDS_CORRECTION, 5층 INVALID를 A 실제 함수로 재현해 D 채택/보류·Qt·JSONL을 확인했다. 네 관측 Step의 Current revision=4로 재계획하면 11 Step이며 base_current_revision=4다. 첨부 묶음 Current의 revision=1 사례와 구분한다. 이동된 Current를 유지하는 C Mock Revised v2와 실제 A의 11 Step을 채택해 FakeRobot·관측으로 전체 완료했고, 별도 정상 15 Step도 전체 완료했다. 전달 성공만으로 Step/Current를 완료하지 않는다. Revised에서 누적 공급 6개 이후 보충 대기·명시 보충·새 EMPTY를 유지했다.

첫 Plan 채택 전 사람 정리 재관측의 이전 미연결 제한을 해소했다. D 내부 check의 plan_id/step_id를 둘 다 null로 허용하고 가짜 Plan/Step을 발급하지 않는다. Vision 외부 callback 필드는 바꾸지 않았다. 이 문맥은 Current 채택만 가능하고 조립 Step 완료 증거가 될 수 없다. 단위·통합 검사를 추가했다. startup의 실제 빈 보드 관측 자동 연결은 이번 범위가 아니다.

최종 코드 변경 후 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` → **707 passed**, 종료 코드 0. A 독립 검사 **112 passed**, 새 실제 A/D 연결 검사 **24 passed**, 각각 종료 코드 0. Qt는 offscreen, Robot/Observed는 Fake이며 실제 장치 성공이 아니다. 실행 결과 JSON (`logs/a-backend-connection-guy8gbim/results.json`, 로컬 산출물)과 같은 폴더의 시나리오별 Job JSONL을 보존했다. logs는 로컬 산출물로 원격 clone에 없다. lint/type는 미구성이고 새 dependency를 설치하지 않았다.

[연결 안내](D_A_PLANNER_HANDOFF.md)에 호출법·범위·남은 작업을 갱신했다. 기존 3-Step FakeDemo는 별도 독립 시험용으로 유지한다. C 실제 호출의 다른 인자·Difference 변환·음성/질문·취소 Workflow, B 실제 callback·촬영, 실제 Robot driver/pose/STOP/재개는 남아 있다. 자동 복구·DB·MOVE/REMOVE·미검증 pose를 추가하지 않았다. 지정 수현 브랜치·기존 미커밋 변경을 보존하고 commit/push/PR/merge하지 않았다.

## 2026-10-06 — HMI 블록 비율 수정

사용자의 납작한 블록 표시 피드백에 따라 [hmi_board.py](../app/hmi_board.py)의 표시 투영만 수정했다. 기존 가로 투영 한 칸 길이 약 1.109·층 높이 0.65 대신 세 축을 같은 축척으로 투영하고, 기본 brick의 가로20/몸체 높이24 LDU 비율(1.2)을 적용했다. 돌기 지름12/높이4 LDU도 반영했다. 근거는 [LDraw 파일 규격](https://ldraw.org/article/218.html)의 모델 치수이며 실물 측정·Robot 보정값으로 사용하지 않는다.

`BoardView(isometric=True, brick_height_per_stud=24/20)`의 높이 비율은 표시용 인자로 조절할 수 있다. 층·좌표·Design/Current는 변경하지 않는다. 전체판과 확대가 같은 투영을 사용하고, 몸체 바닥의 모든 모서리와 최상층 돌기 높이까지 확대 범위에 넣어 4층 가장자리 잘림을 방지했다. 위에서 보는 현재 목표/전달 블록은 몸체 높이가 보이지 않는 시점을 유지하고 돌기 지름 비율만 맞췄다.

기존 Qt 검사에 비율/표시 설정 2개·가장자리/창 크기/4층/원본 유지 4개를 추가했다. 관련 Qt+C 저장 응답 A/D 검사 **40 passed**, 전체 **852 passed, 11 skipped**, 종료 코드 0. skip은 기존 별도 history PostgreSQL 통합 검사의 `HISTORY_TEST_DSN` 미설정이며 이번 HMI 검사는 모두 실행했다. 새 dependency/class/framework/장치 명령은 없고 공통 계약/Backend/Robot 설정/다른 미커밋 변경은 보존한다. lint/type 설정은 미구성이다.

수정 전 전체 목표 (`logs/hmi-brick-proportion/board-before.png`, 로컬 산출물), 수정 후 (`logs/hmi-brick-proportion/board-after.png`, 로컬 산출물), Revised 표시 (`logs/hmi-brick-proportion/revised-after.png`, 로컬 산출물)와 전체 창 PNG/JUnit을 logs에 저장하고 시각 확인했다. Qt offscreen 표시 검증이며 실제 Camera/Robot/치수 측정 시험이 아니다. 실행 중인 창에는 새 코드가 자동 반영되지 않으므로 FAKE 창을 닫고 기존 실행 명령으로 다시 열어 확인한다. GitHub 게시/PR/merge 없음.

## 2026-10-06 — 누적 D 수정 PR 게시 준비

사용자가 지금까지의 수정사항을 PR로 요청했다. PR #9와 B PR #10이 병합된 최신 main `7c51549efb90e0b324a21351b7109dc473a7bda9`에 수현의 후속 수정만 적용한 독립 파일 트리를 검사했다. 로컬 지정 브랜치/HEAD/미커밋 파일과 기존 원격 브랜치를 유지하며, 최신 main에서 만든 별도 게시용 원격 브랜치 `work/suhyun-day4-integration-updates`에 후속 수정만 게시한다. GitHub 연결 API의 쓰기 권한 오류로 로그인된 웹 업로드를 사용한다. 로컬 파일이나 팀원 소스를 최신 main으로 일괄 덮어쓰지 않는다.

포함: Robot 한 블록·3-Step 수동 시험 진입점/설정, FAKE 단계 입력·STOP/재개, 현장 잘못 놓음 신고/좌표 표시, A–B–D 합성 callback·C 저장 응답 재계획, HMI 블록 비율, 관련 Consumer Schema·검사·실행 안내/진행 기록. 별도 history DB/컨테이너 작업·발표/제출 자료·미완료 공통 문서는 제외한다. A/B 원본과 main의 실제 C 코드는 동일 바이트를 유지한다.

게시 파일 트리에서 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` → **1045 passed**, 종료 코드 0. main의 C 독립 검사와 D 후속 검사를 포함하며 별도 history 검사는 포함하지 않는다. 앞선 로컬 852 passed/11 skipped는 파일 구성이 다른 당시 기록이다. 실제 Camera/Robot 연결 성공 또는 GitHub CI 결과가 아니다.

Robot 관련 검사는 이 호스트의 `source_path`/`measurements_path`가 가리키는 기존 자료 파일을 사용한다. 다른 PC/clone에서 해당 파일이 없으면 전체 Robot 시험 검사는 그대로 재현되지 않는다. 실제 시험 진입점은 원본/측정 SHA 확인과 명시 실행을 유지하며 경로·TCP·pose·속도를 이번 게시에서 변경하지 않았다. 장치 시험 기록은 사용자 보고와 모의 검사를 구분한다. C 저장 JSON 시험은 저장소에 보관한 Fixture 경로로 실행할 수 있다. 로그/PNG는 Git 제외인 로컬 산출물이다.

원격 PR은 사람 검토용 초안으로 준비하며 실제 STOP/재개·B production callback/Camera·C 함수/LLM/음성·전체 사람 조립 연결은 미검증이다. main 병합/실제 장치 실행은 하지 않는다.

2026-10-06 게시 결과: [Draft PR #12](https://github.com/suuuhululu/C-2/pull/12)를 생성했다. main `7c51549` 기반 게시용 원격 브랜치 `work/suhyun-day4-integration-updates`, head `6eb0d9476f347cf49fcd6c140dc939a2d4f0aec1`. 검증한 30개 파일과 게시 내용을 바이트 단위로 대조했고 기존 main 파일 102개를 보존했다. 게시 트리 검사 **1045 passed**, 종료 코드 0. 별도 DB/컨테이너·미완료 공통 문서/발표 자료 제외, 로컬 지정 브랜치/HEAD와 다른 기존 변경 보존. main 병합·실제 장치 명령 없음. 이 결과 문장은 PR 생성 후 로컬 기록이며 별도 원격 커밋을 추가하지 않았다.

## 최신 C PR #11 함수 통합 시험 준비 (2026-10-06)

- C head `4a0300e72ade26312a7889bd4829d3e2e75b4b61`, 병합 `f45e9f3afdea992256518d0686bf3eec7589dd9c` 확인. 로컬에 없던 C 원본/검사/문서/scripts 29개를 수정 없이 가져왔으며 SHA/바이트 일치를 확인했다. A `f9b841c`, B 합성 callback `c75c803`, D 기존 지정 브랜치/미커밋 구현을 연결했다.
- [시험 안내](D_C_FUNCTION_INTEGRATION.md): 실제 C 공개 함수의 텍스트/LLM 모드, Difference 최소 변환, Qt 비동기 질문/결과, 활성 ID/version/revision/STOP 채택 gate. C 알고리즘·공통 계약·음성 모델·Robot 경로는 변경하지 않았다. C 함수 offline/mock 생성과 live/API 호출을 명시적으로 구분하고 API 실패를 Mock 성공으로 대체하지 않는다.
- 새 검사 **16 passed**, 전체 **1206 passed / 21 skipped**, 종료 코드 0. DB DSN 미설정 검사 21개 제외. 실제 C/A/D/Qt·B deliver_example을 호출했고 LIVE 경로의 HTTP 응답은 Fake다. 정상 완료는 관측 후, Revised는 Current 9개/revision 9 보존 및 Remaining 10 Step/최종 19개, KEEP 정리 보류·취소/키 누락/401 실패 보류·불명확 명시 선택·STOP/Current 변경/중복 결과 차단을 확인했다.
- 결과: 로컬 `logs/c-live-preparation/`의 JUnit/manifest/summary. HMI snapshot/JSONL도 검사했다. API key는 에이전트 환경에 없으며 실제 OpenAI 호출·STT/TTS·Camera·Robot·실기 성공은 미검증이다. 사용자 확인 모델은 설계 gpt-4o. 터미널에서 키/LLM 플래그를 설정한 뒤 안내 명령으로 실제 호출을 시험할 수 있다.
- 자체 수정은 연결/기존 시험 진입점/검사/안내·기록 7개 파일, 신규 구체 클래스 1개, 신규 dependency/DB/framework 없음. 누적 LOC 검토 신호를 넘으므로 사람 리뷰가 필요하다. Qt가 멈추지 않도록 thread/signal을 사용했으며 상태 Owner와 C 공개 경계를 유지했다.
- 기존 branch/HEAD·미완료 변경·원자료·두 C 저장 JSON 보존. 이번 변경은 PR #12에 자동 포함되지 않으며 commit/push/PR/merge·장치 명령을 실행하지 않았다. 다음은 사용자 터미널의 실제 API 접근/Initial/Revised 확인이다. 음성·B production·REAL Robot은 별도 연결/검증 범위다.


## 2026-10-06 — 현재 Step에 누적 Current와 목표 함께 표시

이번 변경은 로컬 Backend→HMI 표시 개선이다. 공정 판단·Expected·Robot/A/B/C·DB·버튼 정책은 변경하지 않았다. 사용자 지정 브랜치를 유지하고 기존 미커밋 자료를 보존한다.

화면 계약에 필수 `current = {current_revision, blocks}`를 추가했다. [snapshot 생성](../app/snapshot.py)은 Backend의 채택 Current를 그대로 전달하고 [HMI Consumer](../app/hmi_contracts.py)는 기존 `completion._current`로 검사한 뒤 전체 snapshot을 복사한다. [공통 Schema](../interfaces/schemas/day4.schema.json)의 `$defs/current`를 [HMI Schema](../interfaces/schemas/hmi.schema.json)에서 참조한다. [HMI Fixture](../interfaces/fixtures/hmi.json)와 [전달판 표시 Fixture](../interfaces/fixtures/team_handoff.json)도 동일 계약으로 맞췄다. Current를 visible_blocks·완료 Step·Design으로 재구성하지 않는다. 필수 필드 추가이므로 별도 화면 생산자가 있다면 같은 필드를 제공해야 하며, 누락을 빈 Current로 보정하지 않는다.

[Qt 창](../app/qt_hmi.py)은 같은 최신 snapshot의 Current와 Step 목표를 [기존 투영](../app/hmi_board.py)에 함께 전달한다. 작은 24×24점 전체판에는 누적 구조 전체, 확대에는 목표 주변 4점 여유 범위의 블록·아래층을 표시한다. 확대가 전체 Current를 뜻하지 않도록 ‘주변 확대’를 표기했다. 좌표는 최소 모서리, 6점 0°=X2/Y3·90°=X3/Y2이며 입체 투영 축은 X↘·Y↙·층↑다. 창 장식 포함 960×900, 기존 표·모니터·질문·상황별 버튼을 유지한다.

| 상태 | 그림 의미 |
|---|---|
| 첫 Step | 빈 채택 기록 + 점선/반투명 목표. 실제 보드가 비었다고 추정하지 않음 |
| 부분 조립 | Current 실제 노랑/파랑·실선 + 이번 목표 점선·‘이번 목표’ 표기 |
| 목표와 여섯 필드 일치 | 몸체는 중복 없이 한 번, 해당 Current 블록에 점선 강조·‘Current에 반영됨’ |
| 위치·색상·층 차이 | 실제 Current 위치/색/층 유지. 목표는 별도 윤곽. 같은 위치의 색 차이는 목표 색으로 실제 색을 덮지 않음 |
| 이번 목표 관측 불가 / 아래층 가림 | 채택 Current 유지. 미확인 목표는 반투명이며 이번 프레임만으로 구조를 바꾸지 않음 |
| STOP / 재계획 | STOP은 현재 그림 유지. 재계획은 새 snapshot의 Current·Design·Step을 함께 갱신 |
| 완료 | 최종 Current만 표시, 다음 목표 없음 |
| REAL 단일 전달 / 현장 수동 시험 | 미채택 조립 구조를 만들지 않음. 단일 전달은 종류 그림만, 수동 입력 배치는 Current와 표에 표시하고 Camera 확인과 구분 |

검증: 신규 [누적 구조 검사](../tests/unit/test_hmi_current.py) **34개**, 관련 기존 검사까지 **248 passed**, 최종 전체 **1240 passed, 21 skipped**, 각각 종료 코드 0. 21 skip은 별도 history PostgreSQL의 `HISTORY_TEST_DSN` 미설정이다. Consumer/Schema/Fixture, 원본·Backend 상태 불변, 정상 FakeRobot/JSONL, 가림 유지·중복 방지·색/위치/층 차이·재계획·4층 가장자리·기존 REAL Fake 프로세스 검사를 실행했다. lint/type 설정은 미구성이며 도구를 설치하지 않았다.

실행 명령:

```bash
cd /home/ms-02/C_2
QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q
QT_QPA_PLATFORM=offscreen PYTHONPATH=.:tests/unit python3 logs/hmi-current-guidance/render.py
```

검사/화면 색인 (`logs/hmi-current-guidance/summary.json`, 로컬 산출물)에 JUnit·원본 보존 검사·변경 파일/해시·입력 snapshot·렌더링 배치·18개 PNG·Mock Job JSONL을 남겼다. Qt offscreen 실제 페인트 결과에서 아래층/목표/범례/표/안내/버튼 잘림을 직접 확인했다. 운영 모니터/WM/DPI·실제 Camera/Robot 연결·실제 C API 호출은 이번에 검증하지 않았다. REAL 화면 캡처도 Fixture/FakePorts만 사용했으며 실제 장치 성공이 아니다. 기존 실행 중인 Python 창은 자동 갱신되지 않으므로 다음 실행에서 새 표시가 적용된다.

변경 파일 13개: application 4, Schema 2, Fixture 2, 검사 3, 기록 2. 새 class/dependency/framework/통신/DB 없음. 300줄 변경 검토 신호는 상태별 표시 검증과 Fixture의 명시적 Current 기록에 따른 것이며, JSON 원래 형식과 다른 담당 원본/Robot 설정은 보존한다. 커밋·게시·PR·merge·장치 실행 없음.

범위 밖 발견: 기존 `hmi_board._project`의 return 뒤 전달판 문구 그리기 코드는 실행되지 않는다. 전달 시험의 하단 캡션은 기존 Qt QLabel에서 표시되고 이번 누적 구조 개선에 영향이 없어 별도로 수정하지 않았다.


## 2026-10-06 — HMI 가로폭 확대

사용자가 반폭 제한보다 조립 그림/표의 가독성을 우선해 가로 확대를 승인했다. [Qt 창](../app/qt_hmi.py)의 기본 창 장식 포함 크기를 **1200×900**으로 변경했다. 1920×1080 기준 오른쪽 720px를 터미널에 사용할 수 있다. 단일 고정 창·최대화 금지·기존 버튼과 Backend 판단은 유지하며, 사용 가능한 화면 범위를 넘지 않도록 제한한다. 생성자의 `window_size`로 기존 960×900도 지정할 수 있고 두 크기를 검사했다. 앞 절의 960×900 결과는 당시 크기의 시험 기록이다.

Qt/누적 Current/REAL Fake 프로세스/A–D/B 합성/C 함수 Mock·저장 응답 관련 **163 passed**, 종료 코드 **0**. 새 크기 검사 2개와 기존 모든 상태별 표시 검사를 실행했다. 새 크기로 첫 목표·부분/다층 구조·일치·차이·가림·정지·재계획·완료·REAL 표시 Fixture의 Qt 화면 18개를 렌더링했다. 실제 그림·범례·표·안내·모니터·버튼이 잘리지 않음을 확인했다. 화면/검증 색인 (`logs/hmi-wide/summary.json`, 로컬 산출물), 현재 구조와 목표 (`logs/hmi-wide/waiting.png`, 로컬 산출물), 위치 차이 (`logs/hmi-wide/position_mismatch.png`, 로컬 산출물).

변경은 Qt 창·관련 검사 2개·진행 기록 2개로 제한했다. 이전 렌더 재현 스크립트는 960×900을 명시해 과거 크기를 유지한다. 장치/API 실행·커밋·게시·PR·merge 없음. 운영 모니터의 WM/DPI는 미검증이며, 실행 중인 창은 재실행해야 새 크기가 적용된다.


## 2026-10-06 — C 마이크 STT·질문 TTS와 Fake Robot 연결

사용자 승인 범위의 음성 시험을 준비했다. `app/abd_input_hmi.py`의 `--c-voice`와 `app/c_text_connection.py`에서 C PR #11의 `voice.listen/transcribe/speak`·텍스트 C 공개 함수, 실제 A `plan_from_current`, D/Qt/JSONL, B 합성 callback을 연결했다. C 원본 7개 Python 파일은 해시 동일이며 공통 계약·공정 완료 판단·실제 Robot 경로는 수정하지 않았다. 새 dependency/framework/버튼은 없다. 정상 합성 확인은 기존 터미널 입력이며 음성을 조립 완료 증거로 쓰지 않는다.

정상·색상 불일치·KEEP/REVISE/취소·무음/장치/401/403·지원하지 않는 목표·UNCLEAR 후 명시 선택·STOP·Current 변경 중 늦은 응답을 검사했다. TTS가 끝난 후 답변 녹음하며 실패하면 HOLD, 두 번째 UNCLEAR 뒤 자동 녹음/질문을 반복하지 않는다. REVISE는 현재 블록 1개/revision 1을 보존하고 실제 A Remaining 14를 계산했으며 새 EMPTY 전 추가 Fake 전달은 없다. 기존 C 음성 대화의 무한 반복 경로 대신 D의 기존 요청/선택 정책을 유지하는 최소 연결이다.

새 연결 16개, 관련 기존 C/A/D/B/Qt 검사 포함 **581 passed**, 종료 코드 **0**. 코드 컴파일 확인도 종료 0. 증거 색인 (`logs/c-voice-preparation/summary.json`, 로컬 산출물)에 JUnit·Mock Qt 캡처·Job JSONL/snapshot을 기록했다. 기존 lint/type check는 미구성이다. 실제 마이크/스피커/네트워크는 검사 경계에서 Fake로 대체했고 이 에이전트 환경에 실제 API 키가 없어 실제 STT/LLM/TTS는 실행하지 않았다.

실행·키 분리·현장 입력·STOP 한계는 [C 연결 안내](D_C_FUNCTION_INTEGRATION.md#2026-10-06--마이크-stt질문-tts와-fake-robot-시험)에 추가했다. `OPENAI_API_KEY`(STT/설계)와 `OPENAI_TTS_API_KEY`를 사용자 터미널에서 설정하고 HMI 시작으로 녹음한다. 이미 시작한 C 녹음/HTTP/재생의 즉시 중단은 지원하지 않지만 반환 결과의 채택과 다음 진행은 취소한다. 실제 키 모델 권한·마이크/STT 품질·TTS 청취·Camera/Robot·운영 모니터는 미검증이다. 이번 파일만 로컬 변경했으며 커밋·게시·PR·merge 없음.


## 2026-10-06 — HMI 등받이 뒤쪽 시점·축 방향 보완

사용자가 등받이 뒤쪽에서 보는 그림과 축 방향을 채택했다. `hmi_board.BoardView._project`의 화면 가로 투영만 `(y-x)`로 변경해 **+X ↙ / +Y ↘ / 층 ↑**로 맞췄다. 전체 Design·누적 Current/이번 목표의 전체판과 확대 그림에 같은 투영을 사용하며, `qt_hmi`에 시점을 명시했다. X/Y 라벨 위치도 실제 투영한 축 끝점에 맞춰 잘림을 방지한다. 원점은 입체 그림의 위쪽 모서리이며 물리 조립판의 사진 기준 원점/좌표와 다른 새 좌표를 발급하지 않는다.

표시만 변경했다. JSON x/y·orientation_deg·layer와 Design/Current/Expected·snapshot/Schema·완료 판단·Robot 경로·A/B/C는 그대로다. 표시 시점은 고정 +X/+Y 쪽이며 현장 Camera 방향 자동 추정이나 의자의 등받이 방향 자동 인식 기능은 아니다. 새로운 C Design의 방향이 달라지면 그 데이터 배치를 같은 보드 기준으로 그린다. 새 dependency·버튼·클래스 없음.

Qt/누적 Current/기존 REAL 표시 Fake/현장 수동 표시·A/B/C 합성 및 음성 Mock 관련 **167 passed**, 종료 코드 **0**. 신규 검사에서 두 화면의 축 증가 방향·층 상승·입력 사본 불변과 시점 문구를 확인하고, 기존 0/90도·다층·가림/차이·가장자리·Current 중복 방지 검사를 다시 실행했다. 코드 컴파일도 종료 0이며 기존 lint/type check는 미구성이다.

1200×900 Qt offscreen 화면 **20개**를 렌더링했다. 의자 부분 조립/완료·여러 층 그림을 직접 확인했으며 X/Y·아래 구조/점선 목표·표·범례·안내·버튼의 영역 검사를 실행했다. 검증 색인 (`logs/hmi-back-view/summary.json`, 로컬 산출물), 의자 아래 구조와 3층 목표 (`logs/hmi-back-view/chair_partial.png`, 로컬 산출물). Backend/Current/완료/snapshot/HMI Consumer·Robot Controller·A·Fixture/Robot 설정 10개 파일의 전후 해시가 동일하다. 실제 장치·API·운영 모니터/WM/DPI는 미검증이다.

실행 중인 HMI는 새 코드로 자동 갱신되지 않는다. 창을 닫고 기존 실행 명령을 다시 실행해야 적용된다. 이 재실행은 현재 Job을 새 화면으로 복원하는 기능이 아니므로 다음 시험 시작 때 적용한다. 원래 미완료 변경·브랜치를 보존했고 커밋·게시·PR·merge는 하지 않았다.
