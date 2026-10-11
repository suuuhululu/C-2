# 현재 진행 상황

## 2026-10-11 수현 HMI·DB 1차 통합 제출

- 최신 기준: 10/8 B 소유 Current·revision·Expected·비교, D 실행·진행·최종 종료. 공통 정수 layer 1~5.
- HMI·DB ZIP 소스 선택 반영, 4→5층 정합, B 검사/완료 표시 충돌 거절, PostgreSQL 개인 이력과 실행 안내 포함.
- 관련 회귀 1,159 passed(실제 DB 시험 포함), 별도 DB 33 passed, 이력 Docker 이미지 빌드 통과. 탐색적 전체 시험은 기존 PC 절대경로와 C 실패로 PASS가 아닙니다.
- 최신 실제 B→D·HMI 요청 수신·로그인 owner·웹·Robot/Camera 실기는 미완료/미검증. Draft PR로 리뷰합니다. 상세 범위·실행 환경·차단 사항은 [검토 기록](D_HMI_DB_ROUND1.md)을 따릅니다.



## 1차 통합 5층·인터페이스 정합 점검 — 2026-10-11

- 대상은 사용자 생성 `codex/integration-round1`이며 시작 SHA는 main과 같은 `afd75d0b0943d85b44248ea563e89f860921e1dd`다. 기존 `fix/common-five-layer-support`의 `27907c8` 변경을 별도 작업본에 재사용했다. C/A/D MAX_LAYER, 블록/관측 영역 Schema, HMI·합성 관측·수동 Current 확인을 1~5층으로 맞춘다. 원격 반영은 해당 PR의 병합 상태로 구분한다.
- 공통 계약의 block_id/parent_version 요구·무응답 자동 취소 표현을 실제 C·D 계약에 맞췄다. 팀 가이드·C 구조의 미확정 지지 표현과 A/D 인계의 현재 5층 invalid 설명을 정리했다. [1차 통합 인터페이스 점검](11_ROUND1_INTERFACE_AUDIT.md)에 기준·수정 사항·별도 브랜치 차이·담당별 연결 과제를 기록했다. 과거 시험·원본 Fixture·측정값·참고자료는 보존한다.
- 기존 5층 연결 시험에 C/A/D/Schema 상한 일치와 B 합성 callback의 5층 관측 채택·가린 아래층 보존·6층 입력 거절 후 상태 보존·중복 무효화를 추가했다. 새 production 모듈·class·framework·실행 dependency는 없다.
- 실제 관련 검사 **678 passed**, 실패·오류·skip **0**, 종료 코드 **0**. C validator·A planner·D contracts/current/replan·HMI/Qt·A/D·A/B/D 합성 callback·C 저장 응답·5층/30블록·Schema/HMI 참조·팀 인계 및 B 예시 검사를 포함한다. Qt는 offscreen, Robot은 Fake, B는 합성 입력이다. 로그와 JUnit은 ignored `logs/round1-interface/tests.log`·`tests.xml`이다. 기존 RefResolver deprecation 경고 2건이 남는다.
- 환경은 Python 3.12.3·pytest 7.4.4·기존 PyQt5다. 초기 관련 검사에서 `referencing` 미설치로 Schema 시험 1건만 실패(312 passed)했고, 이전 5층 검증에서 사용한 jsonschema 4.26.0과 해당 의존성을 `/tmp/c2-round1-schema-test-deps`에만 준비해 재검사했다. 저장소 dependency·ROS 환경은 바꾸지 않았다. LLM/음향 key·HISTORY_TEST_DSN은 child process에서 unset했고 pytest plugin 자동 로드를 끈 장치 없는 시험이다.
- 전체 저장소 시험은 이번에 실행하지 않았다. 아래 2026-10-07 기록의 기존 전체 실패·장치 자료 경로·C HTTP Fake 정합 문제를 해결했다고 주장하지 않는다. 실제 Camera/Robot·LLM/음향·DB/웹은 이번 시험 범위 밖이다. lint/type/CI는 미구성이다.
- 문서·정적 검증: 기존 5층 변경을 포함한 변경 파일 **34개**, 상대 링크 **245개**, JSON 예시 코드 블록 **25개**(보존된 JSON Lines 블록 1개 포함)를 검사했다. 새 누락 링크·새 잘못된 anchor **0**, 변경 Python/JSON 파싱·`git diff --check` 통과. ignored 과거 로그를 가리키는 기존 누락 링크 **23개**는 보존했다. reference 원문 변경 **0**. 결과는 ignored `logs/round1-interface/static-checks.json`이다.
- 남은 BLOCKER: A API 0.5 문서의 B Current/revision Owner 표현과 현행 D 단일 상태 Owner 차이, A 재평가/경로 wire와 D 최종 Schema 미연결, B 실제 촬영 생산자/최종 확인 미제출. 설계 확정 이벤트·좌표 단위/frame 변환·직접 결착/정지·사용자–Job/웹 연결도 담당 PR로 검증해야 한다. 이 점검을 전체 인터페이스 통합 완료나 실물 5층 성공으로 표시하지 않는다.

관련 검사 실행 명령:

```sh
env -u OPENAI_LLM_API_KEY -u OPENAI_API_KEY -u OPENAI_TTS_API_KEY -u HISTORY_TEST_DSN \
  QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  PYTHONPATH=/tmp/c2-round1-schema-test-deps \
  python3 -m pytest planning_trial/test_planner.py \
  tests/unit/test_contracts.py tests/unit/test_hmi_current.py tests/unit/test_qt_hmi.py \
  tests/unit/test_current.py tests/unit/test_replan.py tests/unit/test_hmi_contracts.py \
  tests/unit/test_planner_results.py tests/unit/test_team_handoff.py \
  tests/unit/c_design/test_validator.py tests/integration/test_a_backend.py \
  tests/integration/test_abd_callback.py tests/integration/test_c_saved_results_hmi.py \
  tests/integration/test_five_layer_pipeline.py \
  tests/integration/perception_backend_callback_examples/tests/test_callback_examples.py \
  -q --junitxml=logs/round1-interface/tests.xml
```

## 공통 5층 지원 — 2026-10-07

- **기준/작업 위치:** 원격 main `afd75d0b0943d85b44248ea563e89f860921e1dd`(PR #17 병합)을 확인하고 독립 clone의 `fix/common-five-layer-support`에서 수정했습니다. 완료 시 원격 main도 동일했습니다. 로컬 `work/suhyun-assembly-evidence`/`62b7ffd`의 기존 Backend 연구 코드와 작업 상태는 보존했습니다. 저장소 AGENTS와 관련 정책·계약을 읽었으며 저장소/관련 작업본에 `.agents/skills`는 없었습니다. 검증 단계에서는 commit/push/PR/merge를 하지 않았으며, 이후 사용자 승인으로 이 변경의 commit/push·draft PR 게시를 진행합니다. 병합은 하지 않습니다.
- **변경:** A `MAX_LAYER`·오류 문구, D 블록/관측 영역 검사·`supported_scope`, Day4 Schema를 1~5층으로 통일했습니다. HMI Schema는 Day4 정의를 참조하므로 같은 범위를 적용합니다. 합성 관측과 수동 Current 확인도 D의 층 상수를 사용합니다. 여섯 배치 필드·PLACE·지지 2 stud·24×24 좌표·판 footprint·Plan/Current 최신성 의미는 유지합니다.
- **30블록:** C 생성 상한 30을 유지하고 C 검증→실제 A→D 채택→Qt→합성 관측/FakeRobot 완료를 확인했습니다. A/D에 새 수량 제한은 추가하지 않았습니다. REAL 수동 시험의 네 공급열×여섯 슬롯(최대 24 Step) 제한은 유지하며 실제 직접 결착·Vision 판별 범위를 확장했다고 주장하지 않습니다.
- **검사 변경:** 기존 5층 범위 초과 시험은 6층으로 옮겼습니다. 보관 C 응답과 A 첨부 자료·해시는 보존하고 A의 승인된 두 변경만 제외해 원본 해시를 대조합니다. 새 연결 검사는 1~5층 정상, 30블록, 부분 Current 보존/Remaining, 6층 거절/미채택, 지지 부족/판 밖 좌표, Schema 및 수동 확인 입력을 다룹니다. Qt 기존 4층 가장자리 검사를 유지하고 5층 조건을 추가했습니다.
- **관련 L1/L3:** `planning_trial/test_planner.py`, unit의 contracts/hmi_current/qt_hmi/current/replan/hmi_contracts/planner_results/c_design validator, integration의 a_backend/abd_callback/c_saved_results_hmi/five_layer_pipeline를 실행해 **645 passed**, 종료 코드 **0**입니다. 5층 가장자리와 30블록 완료 PNG를 실제로 열어 표시를 확인했습니다. Qt offscreen·Robot/관측/LLM/음향은 Fake 또는 미연결이며 실제 장치 검증이 아닙니다.
- **전체 비교:** 변경 전 main은 **1405 passed, 41 failed, 24 skipped, 11 errors**, 변경 후 최종은 **1444 passed, 41 failed, 24 skipped, 11 errors**, 각각 종료 코드 **1**입니다. 실패·오류 52건의 node ID 집합은 동일하며 새 실패 0건입니다. 24 skip은 별도 실제 DB DSN 미설정입니다. 전체 PASS로 표시하지 않습니다.
- **분리한 기존 제한:** C LLM의 `OPENAI_LLM_API_KEY`와 D 시험의 `OPENAI_API_KEY` 설정이 다릅니다. 해당 값 대신 시험 프로세스의 명시적 더미와 HTTP Fake만 사용한 10개 비교 검사도 전/후 각각 **3 passed, 7 failed, 1 teardown error**로 동일했습니다. 키 문제 뒤에는 최근 C metadata/judge 호출과 기존 D Fake의 호출 횟수 기대(1/2회)·대기 조건 불일치도 남습니다. Robot 관련 시험은 `/home/ms-02/C_2/...` 설정·외부 원본/측정 자료가 이 편집 PC에 없어 실패합니다. 별도 문제의 코드·장치/계정 설정은 수정하지 않았습니다.
- **시험 환경:** 편집 Python 3.12.10 / pytest 9.1.1 / Qt offscreen. ROS `launch_testing`과 pytest 충돌로 이번 명령에서만 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`을 사용했습니다. 기존 Schema 시험에 필요한 jsonschema 4.26.0을 `/tmp/c2-five-layer-test-deps`에만 준비하고 기존 ROS 환경 site-packages와 함께 PYTHONPATH로 지정했습니다. 저장소 dependency/framework 추가는 없습니다. 일반 검사는 OPENAI 세 key와 `HISTORY_TEST_DSN`을 child process에서 unset했고 실제 비밀값·LLM/Robot/ROS 제어를 사용하지 않았습니다.
- **최종 확인/후속:** 변경 Python/JSON 파싱, Markdown 새 누락 상대 파일 링크 0, `git diff --check` 통과. lint/type/CI 미구성. 사람 리뷰와 실제 5층 Vision/직접 결착·30블록 실행 환경 검증, D LLM Fake 갱신과 외부 Robot 자료 경로 정합성이 후속입니다. 이전 시험 기록은 아래에 그대로 보존합니다.
- **문서 전체 재점검:** 저장소 Markdown·작업 지침·Schema와 층 관련 코드/시험을 검색해 callback 예시 README의 현재 계약 누락을 1~5층으로 고쳤습니다. C/D 진행 기록에는 현재 범위 안내를 추가하고 과거의 4층 계약·시험 결과를 보존했습니다. 기존 1~4층 Fixture·고정 예시·Qt 회귀 시험·A 원본 해시 비교는 당시 자료 또는 유효한 하위 범위 사례입니다. Day1~4는 일정, 공급열/시작 슬롯 1~4와 REAL 최대 24 Step은 장치 시험 한계, Schema의 width/height 최대 24는 판 크기이므로 층 상한 변경 대상이 아닙니다. 실제 Vision/직접 결착의 5층 성능은 미검증입니다.

전체 실행 명령(원격·실기 연결 없음):

```sh
env -u OPENAI_LLM_API_KEY -u OPENAI_API_KEY -u OPENAI_TTS_API_KEY -u HISTORY_TEST_DSN \
  QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  PYTHONPATH=/tmp/c2-five-layer-test-deps:/Users/suhyun/miniforge3/envs/ros2_jazzy/lib/python3.12/site-packages \
  python3 -m pytest tests planning_trial/test_planner.py -q
```


## 최종 MVP 문서 이행 — 2026-10-07

사용자 요청으로 GitHub main `95259bd`의 Markdown/docs를 커스텀 의자 최종 MVP에 맞춰 정렬합니다. [최종 MVP](10_FINAL_MVP.md)에 설계 대화·사용자 확정 → 조립 순서/경로 → Backend/HMI → 로봇 공급판 집기·조립판 직접 결착·필요 시 사람 지지 → 세 단계 종료를 정의했습니다. 목표는 개발 과정에서 수정될 수 있습니다.

- 1단계는 해당 계획에 필요한 모든 블록 사용 종료, 2단계는 Vision 완성상태 확인과 Backend 최종 조립 판정/종료, 3단계는 사용자별 현재 설계·조립 기록 DB 저장과 웹앱 반영입니다. 명령 완료·마지막 블록 사용·JSONL만으로 세 단계 완료를 처리하지 않습니다.
- [첨부 연구 설계](suhyun_individual_research_topic.md)를 제품 적용 안내와 함께 포함했습니다. 지지 프로토콜을 반영하고 원문 D1~D13·접촉/복구·필드·역할 제안은 연구 설계와 팀/장치 합의 상태로 구분합니다.
- README·최신 결정·AGENTS·계약/팀 가이드·개발 단계·측정·실행·DB·C/A/B 연결/시험 안내를 정렬했습니다. 기존 전달형 Day4 계약·코드 명령·시험 수치·측정 원자료는 보존하며 [reference 적용 안내](reference/README.md)를 추가했습니다. GitHub에 없는 로컬 final_docs/발표 초안·미완료 코드 변경은 포함하지 않습니다.
- **현재 구현:** C Design/HRI·A PLACE Plan·D/Qt/기존 전달·B 합성 callback과 독립 PostgreSQL 이력/계정 코드가 게시되어 있습니다. 이 문서 작업에서 앱을 다시 시험하지 않았으며 아래 이전 시험 수치는 당시 대상의 기록입니다.
- **남은 구현/합의:** 직접 결착 좌표·경로/접촉 인계·지원 제스처/준비·최종 Vision 계약·사용자–Job 소유자/세션/웹 반영·Qt/웹 분담. 계정표는 있지만 jobs에 사용자 소유자 연결이 없고 사용자별 웹 화면도 없습니다. 기존 전달/Mock·DB 검사는 최종 서비스 전체 검증이 아닙니다.
- **이번 검증:** 변경 Markdown 29개를 포함한 문서 38개의 상대 링크 298개·표 123개·fenced 코드 블록 128개(JSON 예시 36개)를 검사했습니다. 신규 링크/앵커·표·JSON/코드 블록 오류 0, 종료 코드 0입니다. Git 제외 로컬 logs 산출물을 가리키는 기존 미존재 링크 28개는 게시 원자료의 한계로 보존했습니다(D_ABD_SYNTHETIC_CALLBACK_TEST·D_A_PLANNER_HANDOFF·D_BACKEND_RUN_ROBOT_PLAN·STATUS). diff 공백 검사 종료 코드 0, 기존 reference 원문 8개·첨부 원문 본문·측정/개발/시험 기록 본문 보존을 확인했습니다. 코드·Schema·장치 설정은 변경하지 않았고 앱·실제 DB·웹·Camera/Robot 검사는 수행하지 않았습니다. 기존 CI/lint/type는 미구성이며 새 도구를 도입하지 않았습니다.
- 지정 `/home/ms-02/C_2`의 개발 브랜치·미완료 변경을 보존하고 최신 main 기반 별도 `docs/final-mvp-chair` 작업 공간에서 문서만 commit/push/PR을 준비합니다. merge·장치 실행은 요청 범위가 아닙니다.

## 이전 개발·시험 기록의 범위

아래는 각 기록 날짜의 구현·검증 결과입니다. 새 제품 목표의 구현·통합 완료율이나 이번 문서 PR의 재검사 결과로 사용하지 않습니다.

## A파트 — 지지 합의 문구 정리·Day3 재검사 (2026-10-07)

- 2026-10-06 세은의 동의와 수현의 회신에 맞춰 A/C의 지지 조건을 바로 아래층과 겹치는 고유 stud 총 2개 이상으로 문서·C 주석에 통일했습니다. 아래 블록 개수와 무관하고 중복 stud를 합산하지 않으며, layer=1은 제외합니다. Day4 기하 검사 기준이며 실제 체결·물리 안정성 검증이나 프로젝트 전체의 영구 기준은 아닙니다.
- 새 수정은 현재 결정·공통 계약·C/B 연결 합의·C 계약·C validator의 설명·이 진행 기록입니다. A/C 함수·조건·상수·입출력·로봇 설정은 변경하지 않습니다. 사용자가 이번 문서 PR에 한해 별도 브랜치를 허용했습니다. 최신 main에서 문구 수정만 준비하며, 고정 A 브랜치의 기존 자료·이력은 유지합니다.
- 수정 전 main `6fb971cad619de398b1c47e7d669912cdb470fad`에서 A 독립 **112 passed**, A–D **24 passed**, C 함수→A/D·Qt **16 passed**, C 공개 Mock 재현 **17 checks PASS**를 확인했습니다. 사용자가 같은 명령을 직접 실행한 로그도 모두 종료 코드 0입니다. 사용자 직접 실행과 에이전트 검사 로그는 별도 경로·Job으로 보존합니다.
- 문구 수정 후 C validator 기존 검사 **52 passed**·종료 코드 0, diff 공백·Markdown 코드 블록·새 문서 링크와 변경 범위를 확인했습니다. validator의 실행 AST는 주석/docstring을 제외하고 main과 동일하며 A 계산·재현 파일·README는 변경하지 않았습니다.
- 직접 실행 사례: Initial 15 PLACE → D Current 4개·revision 5 → Revised v2의 11 PLACE 채택. Current 보존·중복 PLACE 제외·선행 조건·최종 목표 일치를 확인했습니다. C는 Mock 또는 HTTP Fake, 관측은 fixture, Robot은 Fake, Qt 검사는 offscreen입니다. 실제 LLM·음성·Camera·Robot·사람 조립은 이번 결과에 포함하지 않습니다.
- 이번 PR은 문서 5개와 C validator 설명만 변경합니다. 재현 스크립트·README·A 과거 진행 기록은 포함하지 않습니다. 기존 재현 코드는 고정 A 브랜치 `work/seeun-planning`의 `319a275`에 그대로 보존하며, 새 알고리즘·dependency·class·SIM/REAL 계산 분리는 추가하지 않습니다.
- 공유 압축 파일은 사용자 직접 실행 로그·입출력·해당 Job JSONL·검증 기록과 실행 명령을 별도로 제공합니다. 생성 산출물은 원격 소스에 커밋하지 않습니다. 다음 작업은 실제 C 출력과 같은 기준의 D Current, 실물 조립 순서 및 최종 목표 대조입니다. 문구 정리의 main 반영은 수현 리뷰·승인 후 별도로 확인합니다.

## 수현 누적 D 수정 PR 게시 준비 (2026-10-06)

- 사용자 요청으로 Robot 시험 진입점/설정·수동/합성 HMI·잘못 놓음 표시·A–B–D callback·C 저장 Design·블록 비율의 누적 수정과 검사를 PR로 준비했다. 별도 DB/컨테이너·발표/제출 초안·미완료 공통 문서는 제외한다. [게시 범위와 검증](D_BACKEND_PROGRESS.md#2026-10-06--누적-d-수정-pr-게시-준비).
- PR #9/B PR #10 병합 후 최신 main `7c51549`를 기준으로 게시본을 만들고 실제 A/B 원본과 main의 C 코드·공통 문서를 보존했다. 독립 게시본의 전체 검사 **1045 passed**, 종료 코드 0. Robot 검사는 이 호스트의 검증된 원본/측정 자료 경로에 의존하며 다른 PC에서의 전체 실행은 그 자료가 필요하다. C 저장 응답은 저장소 Fixture 경로로 실행할 수 있다.
- 로컬 지정 브랜치/HEAD/기존 미커밋 변경과 기존 원격 브랜치는 유지하며, 최신 main에서 만든 게시용 원격 브랜치 `work/suhyun-day4-integration-updates`에 후속 수정만 게시한다. 사람 검토용 초안 PR이며 실제 C 함수/B 인식/Camera/Robot STOP·재개/전체 장치 시연 통과를 주장하지 않는다. GitHub CI는 미확인, main 병합과 장치 명령은 실행하지 않는다. logs/PNG·원자료는 Git 제외/원래 위치에 보존한다.


## HMI 블록 높이·돌기 비율 수정 (2026-10-06)

- 사용자 요청에 따라 [표시 코드](../app/hmi_board.py)의 납작한 층 높이를 LDraw 기본 brick 비율(가로20:몸체 높이24)과 동일 축척의 투영으로 수정하고 돌기 지름/높이를 표시했다. 높이 비율은 BoardView의 표시 인자로 변경 가능하다. 전체판·확대의 범위에 모든 몸체 모서리와 돌기 높이를 포함한다. 현재 Step/전달 블록은 위에서 보는 시점을 유지한다. Design/좌표/층/Current/완료 계산·Robot 보정은 변경하지 않았다.
- 기존 Qt 검사에 표시 비율/설정·판 가장자리 4층/좁은 창·원본 유지 **6개**를 추가했다. 관련 **40 passed**, 전체 **852 passed, 11 skipped**, 각각 종료 코드 0. 11개 skip은 기존 history PostgreSQL 통합의 HISTORY_TEST_DSN 미설정이며 이번 HMI 범위는 모두 검사했다. offscreen Qt의 C Initial/Revised 그림·전체 창과 경계 사례를 확인했다. [수정 후 미리보기](../logs/hmi-brick-proportion/board-after.png), [표시 변경 기록](D_BACKEND_PROGRESS.md#2026-10-06--hmi-블록-비율-수정). 실제 장치 동작/실물 치수 검증은 수행하지 않았다.
- 이번 파일은 표시 코드/기존 Qt 검사/진행 기록/STATUS 네 개다. 새 dependency/class/framework 없음, 공통 계약/Backend/A/B/C 산출물/Robot 경로 설정/기존 변경을 보존했다. lint/type 미구성이다. 지정 브랜치 유지, GitHub 게시/PR/merge 없음. 기존 FAKE 창을 닫고 동일 명령으로 다시 실행하면 새 표시가 적용된다.

## 사용자 제공 C 저장 Design 응답 → 실제 A/D·Qt 통합 (2026-10-06)

- C Initial/Revised 두 Downloads 원본을 동일 바이트의 Fixture로 보관했다. 생성 커밋/실제 C 함수는 미제공이다. 기존 [합성 입력 화면 실행부](../app/abd_input_hmi.py)에 파일 옵션과 실제 배치/저장 Revised 입력만 추가하고 실제 A `plan_from_current`, 기존 D 채택/재계획, B 원본 `deliver_example`, Controller/FakeRobot, snapshot/Qt/JSONL을 사용했다. 관측은 D 작성 합성 프레임, 전달판은 시험 입력이며 B production 구현으로 표시하지 않는다. [파일·입력·실행 안내](D_A_PLANNER_HANDOFF.md#사용자가-제공한-c-저장-응답으로-adqt-시험-2026-10-06).
- Initial v1은 15 Step/전체 Current 15개·revision 15로 완료했다. 부분 Current 0/4/8개에서 Remaining 15/11/7을 실제 A로 계산했다. S09 (9,9) 2층 노랑 6점/90°를 파랑으로 관측하면 Current 9개/revision 9·8/15·의도 확인 대기다. 저장 Revised v2는 이를 보존하고 4블록을 추가해 전체 19블록·Remaining 10 Step을 채택한다. 새 EMPTY/관측을 Step마다 입력해 Current 19개/revision 19·10/10 완료를 확인했다. Robot 성공만으로 Current/Step은 변경되지 않는다.
- 실제 x=7인 배치에 같은 Revised를 넣으면 A NEEDS_CORRECTION·사람 정리 대기다. Current/기존 Design을 보존하고 추가 전달하지 않았다. 조기/중복 Revised·STOP 뒤 늦은 응답·지원 밖 색상/Boolean 좌표도 진행하지 않는다. C 저장 질문/전체 응답은 HMI/JSONL에 보존한다. Revised는 해당 색상 차이용 저장 응답이며 임의의 불일치에 자동 적용하지 않는다.
- 신규 검사 **13개**, 관련 **182 passed**, 최종 전체 **805 passed**, 각각 종료 코드 0. [산출물 색인](../logs/c-saved-results-final/summary.json)에 JUnit·Job JSONL·snapshot JSON·화면 PNG·소스 SHA를 남겼다. native Qt는 파일 로드/창 열기/EOF 종료만 확인했고 START 이후 화면/진행은 offscreen Qt로 검사했다. 초기/재계획/보류 그림도 확인했다. 다수 관측 배치를 한 표에 표시하면 열이 좁아지는 기존 HMI 표시 한계는 남아 있으며 이번에 UI를 재설계하지 않았다. lint/type check 미구성이다.
- 이번 파일 6개: 기존 실행부/연결 안내/이 STATUS 3개, 새 C 원본 Fixture 2개와 새 통합 검사 1개. application 236줄, 신규 class/dependency/framework/DB 없음. 300줄 변경량 검토 신호는 원본 JSON 보관과 정상/재계획/보류 검증에 따른 것이며 공통 계약·Schema·Backend 핵심·A/B 원본·Robot 설정은 보존했다. 지정 브랜치/HEAD 유지, commit/push/PR/merge/장치 실행 없음. 실제 C의 최신 Current 기반 응답 생성, B 실제 관측/전달판·촬영 판별, 실제 Robot/STOP·재개 연결은 미검증이다.
- 마무리 검사: 시작 파일 118개 중 이번 기존 파일 3개 외 115개와 Downloads 원본 두 개를 동일 해시로 보존했다. Python AST·JSON 원본 바이트/구문·공백·문서 코드 블록·로컬 링크 110개·git diff --check 종료 코드 0. [보존 검사 기록](../logs/c-saved-results-final/preservation-audit.json)을 남겼다. 원본/팀원 코드/장치 설정을 덮어쓰거나 이전 미완료 변경을 되돌리지 않았다.

## A–B–D 합성 입력 Qt 화면 시험 준비 (2026-10-06)

- 사용자 승인 범위: 실제 HMI 창에서 정상·불일치·가림·전달판 보류를 확인할 시험 준비. [abd_input_hmi.py](../app/abd_input_hmi.py)를 추가해 기존 Backend/Qt·실제 A plan_from_current·B 원본 deliver_example·Controller/Fake driver를 연결했다. 시작으로 Design/Plan 채택, 터미널 place_empty로 Fake 전달, 복귀 뒤 observe로 합성 관측을 한 번씩 공급한다. 실행/입력/화면 확인 순서는 [화면 시험 안내](D_ABD_SYNTHETIC_CALLBACK_TEST.md#합성-입력을-넣으며-qt-화면-확인하기-2026-10-06)에 있다.
- 정상 3-Step 마지막 Fake 전달 뒤에는 2/3 대기, 마지막 observe 후에만 3/3 완료다. 불일치/빈 영역은 실제 합성 Current 또는 미배치 차이를 유지하며 의도 대기, 이번 목표 가림은 기존 Current 유지/보류, 아래층만 가림은 이번 목표 완료를 허용한다. 전달판 판단 불가는 새 after=null check에서 별도로 넣고 EMPTY 전 추가 집기 없음을 확인한다. 가림 사전 Current와 추가 위치의 D 합성 프레임은 source/이벤트로 표시한다. Fake STOP/재개 및 옛 check 거절을 확인했다.
- 신규 연결 검사 **17개**, 관련 검사 **59 passed**, 최종 전체 **792 passed**, 종료 코드 0. 실제 CLI의 명시 모드/입력 오류·보류/EOF 종료와 DISPLAY=:0 native 창 열기/EOF 종료를 확인했다. native 실행은 시작 버튼/Job/전달 없이 끝났으며 화면 상태는 offscreen Qt/PNG로 확인했다. [산출물 색인](../logs/abd-hmi-final/summary.json), Job JSONL·snapshot JSON·화면 PNG·JUnit을 logs에 남긴다. 첫 테스트 속성명 오류와 전달판 캡처 파일 덮어쓰기 문제를 수정했고, 추가 마지막 Step 검사에서 D 작성 3층 합성 프레임의 visible/verified 층 불일치를 찾아 그 프레임을 고쳤다. Consumer/assertion을 변경하지 않고 영향 검사를 재실행했다.
- 이번 파일은 신규 진입점/검사와 기존 안내/STATUS 네 개다. 실행 파일 198줄·신규 class 1개이며 약 500줄 규모의 검토 이유는 대화형 callback 연결과 외부 결과 검증이다. application 핵심/Schema/Fixture/A/B 원본/장치 설정/기존 변경은 보존했고 새 dependency/framework/DB/통신은 없다. C Mock·B 합성 자료·Robot FAKE다. B 생산 코드/실제 Camera·Robot/실제 C·실제 STOP/재개 통과를 의미하지 않으며 GitHub 게시/PR/merge/장치 실행 없음.
- 마무리 검사: 신규 Python AST·공백·문서 코드 블록·로컬 링크 115개·산출물 JSON·git diff --check, 종료 코드 0. 시작 파일 116개 중 이번 두 문서만 갱신되고 나머지 114개를 동일 해시로 보존했다. 새 파일은 위 실행부/검사 두 개뿐이다(`/tmp/c2-abd-hmi-audit.json`). lint/type는 미구성이며 새 검사 도구를 설치하지 않았다.

## B production callback 후속 연결 착수 확인 (2026-10-06)

- 사용자가 집중 검사 **166 passed**를 직접 재현한 뒤 다음 단계 진행을 요청했다. 원격 PR 목록과 PR #10 head 전체 파일 트리를 다시 조회했으나 `c75c80374b848a395fded62ad901020d06b92913` 그대로이며 B 제공 범위는 합성 예시 18개다. 실제 관측 생산 코드/등록 callback/별도 전달판 전달 함수는 아직 없다.
- 사용자 확인: 추가 B 구현은 아직 없으며 현재 커밋에 올라온 코드가 전부다. 실제 생산자 연결은 B 구현 제공 후 이어간다.
- D의 vision 요청(check_id/after, after=null 포함), on_observation, on_place 및 실패/지연 확인 지점을 [후속 연결 기록](D_ABD_SYNTHETIC_CALLBACK_TEST.md#후속-production-callback-연결-착수-확인-2026-10-06)에 정리했다. BLOCKER: 실제 B 실행 코드 위치 미제공. REQUIRED CHANGE: 홍동의 실제 구현 PR/커밋 또는 로컬 경로 제공 후 해당 생산 함수를 기존 D 경계와 연결. AFFECTED INTERFACE: B 촬영 요청/Observed callback/전달판 결과. REASON: 현재 PR은 JSON 저장·callback 합성 예시이며 실제 인식 생산 모듈이 아니다.
- 이번 변경은 이 STATUS와 기존 검사 기록 두 문서만이다. application/Schema/Fixture/팀원 코드/브랜치/기존 미완료 변경을 보존했고 새 통신·B 알고리즘·장치 실행·Git 게시/병합은 수행하지 않았다. 문서 링크·코드 블록·공백·diff와 파일 보존을 확인했다. 새 pytest 실행은 없으며 직전 합성 166/775 통과를 production 연결 완료로 재사용하지 않는다.

## A–B–D 합성 JSON callback 통합 검사 (2026-10-06)

- [B PR #10](https://github.com/suuuhululu/C-2/pull/10) head `c75c80374b848a395fded62ad901020d06b92913`의 변경 18개를 원본대로 가져왔다. 실제 인식 코드가 아닌 합성 JSON/로컬 callback 예시다. [PR #9](https://github.com/suuuhululu/C-2/pull/9) head `a825e2d6b7440a4ab77fb5c02540484e04dd3acc`와 대조해 A·planning_connection·Current·completion·replan이 동일함을 확인하고 이후 로컬 REAL/HMI 변경을 보존했다. 개발 브랜치와 HEAD `7af9daeb3812f9e87fb36f172293434fd827e42f`는 유지했다.
- 실제 A `plan_from_current(design,current)` → D status/plan/errors 채택·보류 → FakeRobot 성공 → B 원본 `deliver_example()` callback → D Current/Expected/Step → snapshot·Qt offscreen·JSONL을 연결했다. 저장 Plan 주입, C 실제 함수, 실제 카메라/Robot 호출은 없다. B에 없는 별도 진단 전달 함수/ROS/HTTP를 구현하지 않았다. 전달판 state/reason은 검사 내부 최소 변환으로 기존 on_place에 전달했고 전체 진단 제안을 공통 필수 계약으로 확정하지 않았다.
- 정상 일치·불일치 실제 Current 채택/의도 대기·확인된 빈 영역·이번 목표 가림·아래층만 가림·전달판 UNOBSERVABLE·부분 Current/Mock Revised 실제 A 재계획·닫힌/역순/중복 check/seq를 검사했다. after=null 전달판 요청과 새 EMPTY 필요성을 확인했고 마지막 전달만으로는 2/3 대기, 마지막 관측 확인 후에만 3/3 완료다. 자세한 입력·결과·명령·커밋·제한은 [통합 검사 기록](D_ABD_SYNTHETIC_CALLBACK_TEST.md)에 있다.
- 최종 집중 **166 passed**, 종료 코드 0 (신규 A–B–D 16 + B 원본 14 + 기존 A–D 24 + A 독립 112). 전체 **775 passed**, 종료 코드 0. B CLI 7묶음 출력/종료 코드 0. 첫 검사 준비 오류 두 건은 실제 A 층 정렬과 Fake tuple 접근을 수정해 재검사했다. [결과/소스 해시 색인](../logs/abd-callback-final/summary.json), 사례별 result.json·Job JSONL·HMI PNG와 JUnit을 logs에 남겼다. logs는 Git 제외다.
- 이번 작성분은 신규 통합 검사/기록과 이 STATUS 세 파일이며 B 원본 18개를 별도로 구분한다. application·공통 계약·Schema·팀원 원본·장치 설정은 수정하지 않았다. lint/type 미구성, 새 dependency/framework/DB/class 없음. B production callback/별도 전달판 수신 경로·실제 보정/촬영 안정 조건·Robot 정지/촬영 신호·C 실제 함수 연결은 blocker다. 합성 callback 통과를 인식 성능·Camera/Robot 통합 통과로 표시하지 않는다. commit/push/새 PR/merge/장치 실행 없음.
- 마무리 확인: B 원본 18개를 고정 커밋 원격 내용과 바이트 대조했다. 시작 시 기존 파일 96개 중 STATUS만 갱신했고 나머지 95개를 동일 해시로 보존했다(`/tmp/c2-b-callback-audit.json`). 이번 작성 Python AST·공백·Markdown 코드 블록·문서 로컬 링크 102개·산출물 JSON·git diff --check 검사 종료 코드 0. 실제 Qt 화면에서 노랑 목표/파랑 관측 불일치와 전달판 판단 불가/사유 표시를 시각 점검했다.

## 잘못 놓음 수동 입력·좌표 비교·확인 전 완료 방지 검수 (2026-10-06)

- 사용자 요청: 잘못 놓았다는 터미널 신고를 남기고 HMI에 현장 좌표와 목표를 비교. 시험 좌표 **(9,5)**, 적용 검수는 **S03/목표 (7,5), 파랑 4점·1층·0°**. 마지막 조립 확인 전에 완료가 표시되는지도 검수했다. C 때문에 입력/표시가 막히는 것은 아니며, 실제 배치 제공은 B 또는 현장 입력, 목표 생성/수정은 C, Current/Difference/표시는 D 책임이다. 목표 변경/정리 후 재개·Robot MOVE까지 범위를 확대하지 않았다.
- 변경: 기존 REAL 진입점의 assembly `confirmed:false`를 수동 불일치 신고로 로그·HOLD 처리한다. 좌표가 없는 신고는 Current/관측/Step을 변경하지 않는다. actual 여섯 필드가 있으면 기존 조립 유지와 목표 영역 확인을 전제로 수동 Observed를 만들고 기존 Backend 계산으로 실제 Current/차이를 반영한다. Expected/전체 Design/미확인 Step을 목표 기준으로 유지한다. C/HRI 실제 미연결을 유지하고 자동 KEEP/추가 전달/완료하지 않는다.
- HMI: 선택 표시 필드 reported_placement를 snapshot·Consumer·Schema에 명시했고 REAL 수동 MISMATCH 및 해당 Observed에 포함된 배치만 허용한다. Qt는 그 블록을 현장 입력 열에 보여주고, 목표 채움과 실제 입력의 빨간 테두리를 그린다. Actual/목표 좌표·층·색상·방향이 비교되며 물리 블록 대응/기하/완료를 Qt가 계산하지 않는다. Camera 미연결 표시를 유지한다. [실행·제한 안내](D_BACKEND_RUN_ROBOT_PLAN.md)에 입력과 새 실행 필요 조건을 갱신했다.
- 실제 검사: 최종 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` → **745 passed**, 종료 코드 0. 관련 REAL 파일은 38개 검사(기존 18 + 신규 20). 첫/두 번째/세 번째 Step의 좌표 없는 신고와 실제 배치 신고, Current 유지/실제 채택·revision·고정 기준·Step 미완료·차이·다음 집기 없음·중복/옛 결과 거절·JSONL/Schema/화면을 확인했다. 같은 위치 색상 불일치, 잘못된 Boolean·필드/범위·이전 블록 겹침·목표와 같은 actual·정상 확인에 actual·표시 출처 불일치·로그 실패도 검사했다.
- **마지막 확인 전 완료 검수:** 세 번째 전달·복귀 성공만으로는 Qt **WAIT_ASSEMBLY/사람 조립 관측 대기·2/3**, Current revision 2 유지, JOB_COMPLETED 없음. (9,5) 신고 뒤 **HOLD·2/3**, 실제 Current revision 3·위치 (9,5) 채택/목표 (7,5) 유지, 완료 이벤트/다음 전달 없음. 정상 마지막 확인을 별도로 입력한 경우에만 COMPLETE·3/3이다. 검사 assertion을 삭제/완화하지 않았다. [확인 전 화면](/tmp/c2-s03-before-confirmation.png), [신고 후 화면](/tmp/c2-s03-misplaced-preview.png), `/tmp/c2-s03-misplaced-65t4o8vb/result.json`과 같은 폴더의 stdout/Job/모의 driver 로그, 종료 코드 0. 실제 A·Qt·모의 QProcess이며 장치 호출/실행은 없다.
- 범위 **9개 기존 파일**: real_workflow_hmi·snapshot·hmi_contracts·hmi Schema·Qt·BoardView·해당 통합 검사·이 STATUS·실행 안내. 약 350줄 규모 검토 신호이며 신규 파일/class/dependency/framework/DB 없음. 수신 검증과 신고 결과 처리는 책임별로 분리(45줄 receive/18줄 report), 실행 모듈 188줄. 검사 파일 407줄은 실제 계약/외부 결과를 검증하는 테스트로 정책의 Test Code Exception에 해당하며 application 분할/추상 계층을 추가하지 않았다. Backend/Current/Expected/A/Robot 제어·경로·설정은 변경하지 않았다. 사용자 입력 오류를 줄이려고 활성 ID·actual 여섯 필드가 있는 한 줄 양식을 출력하며 실제 좌표로 바꾸어 입력하도록 명시했다.
- 활성 REAL 창은 소스 수정으로 자동 갱신되지 않는다. 사용자 현재 Job/Robot/창을 중단·재시작하지 않았으며, 소모 슬롯이나 이전 check를 새 Job에 재사용하는 지시를 하지 않았다. 새 코드에서 같은 Job을 이어받는 종료 후 복구는 미지원이다. 현재 사용자가 진행 중인 세 번째 REAL 실행의 오류 처리 성공으로 이번 모의 검수를 표시하지 않는다. 아직 Camera/B 실제 인식·수정 후 재관측/재개·C/HRI 의도/목표 변경·REAL STOP/재개는 미연결/미검증이다. 다음 단위에는 실제 관측/현재 상태를 공급하는 홍동 반환 또는 명시 수동 재관측 입력과 정리 후 진행 규칙을 검토해야 한다. commit/push/PR/merge/실제 Robot 동작 없음.
- 마무리 검사: 해당 Python/JSON 구문·공백·문서 링크 101개·코드 블록·git diff --check, 종료 코드 0. 시작 해시와 비교해 위 9개만 변경되고 범위 밖 기존 87개 및 원본 제어/설정/A를 보존했으며 신규 파일은 없다(`/tmp/c2-misplaced-report-audit.json`). lint/type는 미구성이고 새 검사 도구를 설치하지 않았다.

## REAL 3 Step 현장 수동 확인 진입점 구현·독립 검증 (2026-10-06)

- 사용자 답변: **3개 블록을 한 번 조립/총 3회 전달**, 슬롯 모두 충전, 색상/슬롯 임의 선택 허용, 다음 전달 전 현장 조립/전달판 확인은 터미널 입력. 재현 가능한 첫 시험으로 **파랑 4점 공급 슬롯 1→2→3**을 사용한다. 사용자가 노랑 2번 및 파랑 5번 전달·observe 복귀를 확인한 것과 이번 신규 세 슬롯의 실제 시험을 구분한다.
- 변경: [진입점](../app/real_workflow_hmi.py)에서 가짜 C 3블록 → 실제 세은 A → 기존 Backend → 같은 REAL Qt 화면 → 기존 한 블록 CLI를 연결했다. START는 Design/Plan 채택·전체 목표/현재 Step/0/3 표시까지만 한다. 최초 `place_empty` 수동 입력이 첫 실제 이동을 시작하고, 복귀 후 각 `assembly` 수동 입력이 Current/Step을 확인한다. 첫/두 번째 확인 뒤 다음 실제 전달, 세 번째는 누적 Current/Design 대조와 수동 확인 3/3으로 끝난다. Robot 성공만으로 조립 완료하지 않는다.
- 관측 경계: 홍동 Camera/B는 미연결이다. 수동 확인은 **기존 조립 유지 + 현재 목표 일치 + 전달판 비움 + 손/장애물 여유**의 운영자 확인이며, `MANUAL_FIELD_CONFIRMATION`과 REAL 현장 수동/Camera 미연결 표시를 남긴다. 정상 매 Step HMI 확인 버튼을 추가하지 않았다. 실제 차이/불확실은 true를 보내지 않고 보류한다. 수동 입력을 Camera의 실제 반환/독립 안전 판별로 표시하지 않는다.
- Controller는 집기 확인 때만 슬롯을 한 번 소모하고 실행마다 증거를 초기화한다. 서로 다른 실행 ID, observe 복귀/종료 후 다음 실행, 설정 고정, 최대 3회, 실패 후 추가 집기/재개/두 번째 Job 차단을 유지한다. 실제 STOP/재개는 미검증으로 비활성화한다. Robot 경로·pose·TCP/tool·속도·원본 측정·설정 JSON·A 원본은 변경하지 않았다.
- 신규 검사 **18 passed**, 최종 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` → **725 passed**, 각각 종료 코드 0. 정상 실제 A 3 PLACE·같은 REAL 화면의 3블록/3회·슬롯 1/2/3·실행 ID·수동 전 Current 불변·revision 1/2/3·전체 완료·JSONL을 확인했다. 시작 전/실행 중/옛 check/중복/미확인 입력, 유효하지 않은 C/A 기하 결과, 이전 실행 result·4번째 전달, 집기/놓기/복귀 증거 재사용, driver 실패/비정상 종료/설정 변경/로그 기록 실패에서 추가 집기 차단을 검사했다. 초기 중복 거절 메시지와 같은 색 기존 블록의 이동 모호성 실패를 실제 재현 후 수정했으며 assertion을 완화하지 않았다. 수동 Observed는 운영자가 유지 확인한 누적 Current와 현재 목표를 함께 기록해 이동 여부를 추정하지 않는다.
- 실제 진입점 `main`/stdin reader/Qt 버튼/queued 입력/실제 A/Backend/모의 QProcess로도 3회 전체를 실행했다. `/tmp/c2-real-three-main-smoke/result.json`, 해당 `logs/`의 Job/모의 driver JSONL, [S01 화면](/tmp/c2-real-three-step-preview.png), [완료 화면](/tmp/c2-real-three-complete-preview.png), 종료 코드 0. ROS/Robot 이동/Camera 호출 없음. 기존 파랑 공급열로 슬롯 1/2/3 각각 **18 명령·15 이동 요청·집기 1회·동일 observe 종점**의 계획 생성만 확인했다(`/tmp/c2-real-three-offline-plan.json`, 종료 코드 0). IK/FK·충돌/실제 놓임 검사로 확대하지 않는다. 실제 장치 조회는 사용자 실행 시 기존 CLI가 수행한다.
- 범위 **11개 파일**: 신규 `app/real_workflow_hmi.py`, `interfaces/fixtures/c_three_blue4.json`, `tests/integration/test_real_workflow_hmi.py`; 기존 Backend·단일 시험 Controller·snapshot·HMI Consumer/Schema·Qt 6개; 이 STATUS/실행 안내 2개. 신규 실행 모듈 147줄·검사 253줄·기존 확장과 문서 포함 약 600줄 규모이며 새 구체 실행 클래스 1개·검사 spy 1개, dependency/framework/DB/추상 계층 없음. 10파일/300줄 검토 신호를 사전 보고했고 단일 시험 재사용보다 이 연결이 필요한 이유는 Design/A/진행/슬롯/생산자·Consumer·Schema를 함께 검증해야 하기 때문이다. 기존 477줄 Backend는 작은 mode 분기만 확장했으며 무관한 분할/리팩터링하지 않았다. 사람 리뷰를 자체 검사로 대체하지 않는다.
- 작업 시작 파일 해시 대조에서 위 범위 밖 기존 파일은 보존됐다. 지정 수현 브랜치 유지, commit/push/PR/merge/실제 이동 없음. lint/type 설정은 미구성이며 새 도구를 설치하지 않았다. 실행 방법은 [REAL 3 Step 안내](D_BACKEND_RUN_ROBOT_PLAN.md#real-3-step-가짜-c--실제-a--backendhmi--현장-수동-확인-2026-10-06)다. 아직 실제 3회 전달/현장 조립, Camera 시야/촬영/EMPTY/Observed, 실제 C/음성/HRI, REAL STOP/재개·실패 복구는 검증하지 않았다. 다음 제공물은 홍동의 실제 촬영/Observed/전달판 반환과 현장 세 슬롯 시험 로그이며 공통 필드를 다시 작성하라는 요청이 아니다.
- 마무리: 이번 Python AST·JSON 구문·11파일 공백·관련 문서 링크 96개·코드 블록 균형·`git diff --check`를 확인했다. 원본 A/Planner adapter/Robot 실행부·노랑/파랑 설정은 시작 해시와 같고 범위 밖 기존 파일 보존 및 신규 파일 3개만 확인했다. 감사 기록 `/tmp/c2-real-three-change-audit.json`, 종료 코드 0. `/tmp`와 logs는 로컬 시험 산출물이며 GitHub 게시물이 아니다.

## 3 Step 실제 전달 통합 시험 준비 — 실기 실행 전 (2026-10-06)

아래는 사용자 답변을 받기 전 준비 기록이며, 답변 반영/현재 실행 진입점은 위 절을 따른다.

사용자가 가짜 C Design을 3개로 늘리고 실제 공정을 반복하는 시험과 실행 명령을 요청했다. 현재 REAL 진입점은 단일 전달만 허용하므로 반복 실행 명령을 제공하거나 장치를 실행하지 않았다. 총 3회/9회 의미, 사용할 4점 색상·준비된 공급 슬롯, 실제 관측 미연결 상태에서 전달판 비움·사람 조립 확인 방법을 질문했다. 해당 답변과 REAL 3 Step 연결 검증이 필요하다.

독립 준비로 파랑 4점 3개짜리 **초안** C 응답을 실제 A에 넣어 READY/3 PLACE를 확인했다. 색상은 아직 실기 확정값이 아니다. 실제 A + 기존 D + Fake Robot/관측으로 전달 3회·Current revision 3·진행 3/3·COMPLETE를 확인했다. `/tmp/c2-three-step-real-preparation/draft_c_response.json`, `draft_a_result.json`, `fake_three_step_check.json` 및 `/tmp/c2-three-step-fake-check-iigxm2fh`의 Job 로그, 종료 코드 0. Robot/Camera 동작 없음, 실제 3회 전달·조립 성공 아님. 실행 코드·A 원본·Robot 경로·설정은 수정하지 않았고 GitHub 게시/커밋 없음.

## 수동 입력 정지·재개 누락 및 REAL 전달 대상 표시 수정 (2026-10-06)

- 사용자 재현: FAKE 수동 입력 창은 STOP 요청을 출력만 해 `STOP_PENDING`에 머물렀고 재개가 비활성화됐다. `step_input_hmi.py`에 장치 없는 모의 정지/복귀 응답을 Qt timer로 연결하고 새 Planner 요청 ID를 추적한다. 같은 Job·키워드/후보 Design/채택 Plan·Current를 유지하며 재개한다. 정지 중 입력은 계속 거절한다. 공통 Backend 정지/실행 완료 검사와 실제 Robot 제어는 바꾸지 않았다.
- REAL 화면: 해당 창은 별도 단일 전달 시험이므로 다른 FAKE 창의 Design/Plan을 받지 않는다. 단일 시험 Controller의 `transfer_target={brick_type,color,slot}`를 Backend snapshot → HMI Consumer/Schema → Qt로 전달해 **파랑 4점 5번의 그림/종류/색상/공급 슬롯/고정 전달판 목적지**를 표시한다. 진행 메시지가 바뀌어도 대상 안내를 유지한다. 조립 Design/좌표/층/방향은 미채택, Current/조립 완료는 그대로다. 이 필드는 REAL 단일 전달의 선택적 표시 정보이며 공통 Robot goal/result·팀 조립 계약을 바꾸지 않는다.
- 검사: 수정 전 시작 직후·키워드 후·Design 후·Plan 후 STOP 회귀 4개에서 같은 HOLD 오류를 재현했다. 수정 후 각 단계 반복 STOP/재개·새 요청 ID·Plan 계속 입력·재집기 없음이 통과했다. 실제 main/stdin/Qt 버튼으로도 후보 저장 → 정지 → 재개 → Plan 채택/3개 목표/0/3/종료를 확인했다. `/tmp/c2-step-input-stop-main-result.json`, `/tmp/c2-step-input-stop-main-logs/607c3284-9325-440a-aca8-23ded27b6216.jsonl`, 종료 코드 0.
- 전달 대상 검사 5개 추가: 조회 전/준비/전달 중/끝난 뒤 동일 5번 대상과 파란 그림 실제 렌더링, 조립 배치/완료 미생성, FAKE로 전환 시 전달 그림 제거, 슬롯/색상/배치 필드/모드 오류 거절. 관련 두 파일 **28 passed**, 최종 전체 **679 passed**, 각각 종료 코드 0. 전체 수치는 다른 동시 작업의 검사 증가가 포함된 현재 저장소 결과이며 이번 신규 회귀는 9개다. Schema 검사는 설치된 jsonschema의 로컬 참조 resolver를 사용했다. 미설치 referencing 및 공통 Schema URN/상대 URI 매핑 문제를 검사 코드에서 해결했고 dependency/검사 기준을 추가·완화하지 않았다.
- 수정 화면 `/tmp/c2-real-transfer-target-preview.png`는 모의 프로세스로 렌더링했다. ROS 이동/조회 없이 표시만 검증했으며 실제 파랑 성공·STOP/재개 성공을 주장하지 않는다. 사용자가 실행 중인 REAL 프로세스는 중단/재시작하지 않았다. 새 코드는 기존 실행 창에 자동 반영되지 않으므로 전달/복귀 종료 후 다시 열어 확인한다. 창 열기는 조회만 하며 표시 확인을 위해 START를 다시 누를 필요가 없다.
- 범위 11개: 수동 입력/검사 2개, 표시용 Board·Qt·단일 시험 Controller·snapshot·HMI Consumer/Schema·REAL 검사 7개, 이 STATUS/실행 안내 2개. 표시는 필드 생산자와 Consumer·Schema·그림까지 함께 검사해야 해 여러 파일을 건드렸으나 새 class/dependency/framework/DB/Robot 경로는 없다. 기존 Backend·trial·블록/슬롯 설정·다른 작업을 보존한다. GitHub 게시/커밋 없음. 실제 Design/Plan 기반 Robot 전달·Camera/사람 조립·REAL STOP/재개는 이번에 연결하지 않았다.
- 마무리 검사: 이번 Python/JSON 구문·공백·관련 상대 링크 88개·코드 블록·`git diff --check` 확인, 지정 브랜치 유지. 실제 trial 실행 코드와 파랑 슬롯 설정은 작업 시작 해시와 동일하다. Backend에는 다른 동시 작업의 변경이 감지돼 원본 해시 동일 주장에서는 제외하고 되돌리거나 수정하지 않았다.

## 터미널 단계 입력 FAKE HMI (2026-10-06)

사용자가 시작 후 가짜 음성 키워드 → 그 키워드의 Design Fixture → 해당 Design의 Plan Fixture를 직접 넣어 단계별 확인하도록 요청했다. 신규 [step_input_hmi.py](../app/step_input_hmi.py)는 기존 Qt/Backend/JSONL을 재사용하고 stdin JSON을 Qt thread로 전달한다. 필수 `--fake-inputs` 모드이며 ROS/실제 Robot/LLM/Planner를 호출하지 않는다. 실제 생성/경로 계산으로 표시하지 않으며 Plan은 사람 조립 순서다. REAL 한 블록 시험 창은 별도 실행한다.

- 입력: 시작 → `keyword.text` → `design.file/key` → `plan.file/key`. 후보 Design만으로는 미리보기/목표를 채택하지 않는다. 유효한 Plan과 함께 채택한 뒤 전체 Design·S01 목표·0/3을 표시하고 첫 전달판 확인 결과를 기다린다. 자동 관측/Robot 전달/완료 없음, Current revision 0 유지.
- [신규 검사](../tests/unit/test_step_input_hmi.py) 8개: 정상 채택/후보 미표시/화면 갱신, 시작 전·순서 오류·없는 파일·잘못된 Plan·중복 후보·닫힌 요청 거절, 실제 stdin reader thread의 잘못된 JSON/비객체 거절과 Qt 전달. REAL HMI 검사와 함께 **19 passed**, 종료 코드 0. 초기 화면 assertion 실패는 Qt queued signal 처리 전에 검사했기 때문이며 이벤트 처리 후 동일 assertion으로 확인했다. 화면 안내도 queued snapshot의 질문/사유 영역에서 유지한다.
- 최종 전체 `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` → **558 passed**, 종료 코드 0. 실제 `main`/stdin pipe/Qt 시작 버튼/이벤트 루프로 세 입력을 처리해 Design 3개·S01·0/3·HOLD(전달판 관측 대기)·Ctrl+D 종료를 확인했다. `/tmp/c2-step-input-main-result.json` 및 `/tmp/c2-step-input-main-logs/ba053157-c74d-41b5-865e-c76006c557b5.jsonl`에 기록했다. 첫 임시 실행 검사는 존재하지 않는 WAIT_PLACE 상태를 기대해 실패했으며 기존 HOLD/WAIT_PLACE_EMPTY 의미를 확인한 뒤 실행을 다시 검사했다. 제품 상태 계약은 바꾸지 않았다. 1920×1080 논리 화면 기준 반폭 offscreen 미리보기 `/tmp/c2-step-input-hmi-960.png`도 확인했다. 실제 모니터·장치 증거는 아니다.
- 실행 방법과 세 JSON 입력은 [실행 안내](D_BACKEND_RUN_ROBOT_PLAN.md#시작-후-터미널에서-가짜-키워드designplan-입력)에 기록했다. 이 추가 단위는 실행/검사 2개와 관련 기록만 수정한다. 새 dependency/framework/DB/Robot 경로 없음. 아래 REAL HMI 변경과 함께 이번 작업 파일은 총 15개다. 실제 팀 생성 결과·촬영·자동 전달·조립 검증은 연결하지 않았다.
- 마무리: 이번 파일 15개의 Python/JSON 구문·관련 문서 상대 링크 102개/코드 블록·`git diff --check`, 원본 제어/측정 SHA 일치를 확인했다. 초기 해시 대상 77개 중 이번 기존 파일 10개 및 다른 작업 변경 9개를 제외한 58개가 보존됐다. 지정 브랜치/HEAD `7af9dae` 유지, 커밋/게시/Robot 이동 없음. lint/type check 미구성이다. 수동 입력의 처리 객체와 Qt signal bridge 두 클래스는 입력 순서 처리와 GUI thread 전달에 필요한 구체 클래스이며 별도 추상 계층이 아니다. REAL Controller와 함께 신규 클래스 3개·큰 Backend 파일은 정책의 사람 리뷰 신호로 기록한다.

## 실제 한 블록 HMI 연결·파랑 4점 5번 첫 시험 준비 (2026-10-06)

사용자가 노랑 4점 2번의 실제 픽앤플레이스와 observe 복귀를 확인했고 HMI 연결을 요청했다. 다음 대상으로 **파랑 4점 5번**을 선택하고 미실기 좌표도 바로 시험하며 배우겠다고 명시했다. 이 최신 지시에 따라 파랑 1/6번 측정 끝점과 기존 보간/경유 코드를 사용한 **첫 실기 시험 설정**을 준비했다. 파랑 5번이 이미 검증됐다고 기록하지 않는다. HMI 첫 실제 실행은 아직 사용자가 누르지 않았으며 에이전트는 조회만 수행했다.

### 변경과 연결 경계

- 신규 [real_trial_hmi.py](../app/real_trial_hmi.py): 기존 Qt 창·Backend에 단일 시험 Controller/QProcess를 연결한다. 창 열기는 실제 조회만 실행, 조회/현재 실제 observe FK 확인 뒤 준비 확인·시작으로 한 블록만 실행한다. Qt thread에서 ROS 이동을 동기 대기하지 않는다. 활성 프로세스 중 창 종료로 이동을 끊지 않는다. STOP/재개 버튼은 미실기 검증 상태를 명시하고 비활성화한다.
- Backend·snapshot: REAL은 명시 `single_trial=True`와 같은 REAL Controller 바인딩으로만 허용. 기존 goal/result 3필드 유지, 한 Job/실행 UUID·중복 START/늦은 결과/추가 전달 차단. 슬롯은 Controller가 driver의 집기 이벤트로 갱신하며 Backend/Qt가 계산하지 않는다. 전달 뒤 HOLD(조립 미확인), Current/revision·조립 진행 0 유지. Planner/Design/Observed Fake를 REAL에 연결하지 않는다.
- HMI Schema/Consumer·Qt: REAL 표시와 제한된 단일 시험의 버튼/0진행 규칙을 추가했다. 예전 Fake 전체 조립 snapshot의 mode만 REAL로 바꾸는 입력은 계속 거절한다. 준비/작동/집기·놓기·복귀/오류를 같은 화면/JSONL에 표시한다. Plan/Design은 미채택으로 표시하고 카메라/조립 완료를 만들지 않는다.
- [robot_trial_blue5.json](../interfaces/robot_trial_blue5.json): 자료의 `blue_4.start/end`를 그대로 복사하고 측정 파일 경로/해시를 고정. `pick_line`은 해당 공급열만 지정하며 노랑 값으로 대체하지 않는다. 5번 XYZ는 `[-580.9066,91.1324,-10.2376]`, 자세는 원본 Slerp로 계산한다. 잘못 복사된 blue posj는 사용하지 않고 기존 IK 해 분기의 IK/FK 검사로 진행 여부를 정한다. 원본 파일/TCP/tool/속도/고정 전달 위치/HOME·observe 값은 유지했다. 공급열 변경은 사용자 요청에 따른 새 실기 시험이며 경로 충돌/집기 성공을 조회만으로 보증하지 않는다.
- 입력 설정은 조회 당시 복사본과 START 시 파일을 대조해 실행 중 변경을 반영하지 않는다. HMI START는 **이번 대상 블록 준비·전달판 비움의 사람 확인** 의미이며 이때 실행 복사본에 해당 flag를 기록한다. 자동 조회나 Fake가 물리 확인을 대신하지 않는다. 단일 실행 후 START를 다시 허용하지 않으며 재개/앱 종료 후 이어하기는 없다.

### 실제 검증

- 노랑 4점 2번 실기: [사용자 실행 로그](../logs/robot_trials/5969d3bf-047e-4011-b725-0c3dc20f2c82.jsonl)의 집기 확인/다음 슬롯3·놓기·복귀·success=true와 현장 사용자 확인을 대조했다. 관측 Actual FK `[400.9931,8.6160,315.1089,175.1950,-179.5748,175.6306]`·대기/이동 없음·빈 그리퍼 기록이다. 사용자 출력은 쉘 프롬프트로 정상 복귀했으며 직접 종료 코드는 제공되지 않았다. 전체 조립/STOP/재개 통과로 확대하지 않는다.
- 파랑 5번 실제 **무이동** CLI: 현재 실제 observe 시작 검사·**40점 IK/FK·15개 ROS 이동 메시지 변환** 성공, 종료 코드 0. 로그 `/tmp/c2-blue5-check-logs/0d3f6b58-d114-4979-82c5-401b240672af.jsonl`. 파랑 경로 충돌/실제 집기·놓임은 미검증이다.
- 실제 QProcess↔ROS/RG2 조회↔Backend↔Qt: offscreen HMI로 같은 파랑 설정을 연결했다. 자식 인자는 `--check --require-observe-start`, Job=null·실행/이동 없음·REAL 표시·시작 활성·정지 비활성 확인, 종료 코드 0. `/tmp/c2-blue5-real-hmi-preview/result.json` 및 해당 driver JSONL에 `ROBOT_CHECK_COMPLETE`까지 있고 `ROBOT_TRIAL_STARTED`는 없다. [화면](/tmp/c2-blue5-real-hmi.png)을 시각 점검했다.
- 신규 모의 프로세스/Backend/Qt 검사 11개: 조회/실행 분리, 단일 START·같은 goal/ID, 집기 1회/다음 슬롯, 실패/증거 누락/비정상 종료/잘못된 로그·보류/재시도 없음, 설정 변경/다른 공급열 거절, 중복 pick/result·늦은 결과, 활성 실행 중 창 유지, 정지/재개 요청 차단을 확인했다. 관련 기존 검사와 파랑 측정/해시 3개 보완 포함 **146 passed**, 종료 코드 0. 과거 Fake FULL→REAL 입력 검사도 유지했다. 신규 테스트 helper 이름이 pytest의 module setup으로 인식된 오류와 제한 REAL 버튼 표/공개 BoardView 속성 대조를 수정 후 재검사했다. assertion을 삭제하거나 약화하지 않았다.
- 최종 전체 `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` → **550 passed**, 종료 코드 0. 이전 중간 전체는 525개였고 다른 작업의 검사 보완 25개가 함께 반영된 현재 저장소 수치다. 관련 146개 결과와 구분한다. lint/type check/CI 미구성, 새 dependency/framework/DB 없음. 실제 STOP/재개·긴 이동 중 HMI STOP·Camera/홍동 EMPTY/관측·사람 조립·전체 Design 채택 연결은 다음 별도 단위다. Backend/driver 로그 실패 뒤 추가 실행은 차단하지만 이미 실행 중인 독립 CLI의 정지/복구는 현재 HMI가 제공하지 않는다. 이를 완성된 Day4 REAL Controller로 표시하지 않는다.

### 이번 파일·범위와 다음

이번 파일은 신규 실행부/파랑 설정/검사 3개, 기존 Backend·snapshot·HMI Consumer/Schema·Qt·trial·trial 검사 7개, 이 STATUS·실행 안내·설계 3개로 **13개**다. 파랑 첫 시험 요청으로 최초 계획의 11개에서 설정/측정 검사 범위가 늘었다. 실행 파일 신규 클래스는 실제 QProcess Controller 1개뿐이며 Factory/추상 driver 계층은 없다. 기존 Backend 규모 검토/사람 리뷰 요구는 유지한다. 사용자 설정/실기 원본·측정 파일/실패 기록을 보존하고 GitHub 게시/커밋/PR/merge는 하지 않는다.

동시에 `app/contracts.py`, `app/fake_demo.py`, `app/replan.py`, `tests/unit/test_replan.py`, `tests/unit/test_qt_hmi.py`, `interfaces/schemas/day4.schema.json`, `docs/D_BACKEND_PROGRESS.md`, `docs/06_CONTRACT_DRAFT.md`, `docs/09_C_B_BACKEND_HANDOFF.md`에 다른 작업의 변경이 감지됐다. 에이전트는 이 9개를 수정하지 않았고 이번 파일 목록/검증 범위에서 별도로 구분한다. 그 변경을 되돌리거나 수현 HMI 변경으로 표시하지 않는다.

다음은 아래 실행 안내대로 HMI에서 파랑 5번 한 번을 시험하고 실제 놓임/observe 복귀 결과를 기록하는 것이다. 자동 다음 전달·정상 매 Step 확인 버튼·DB·실제 STOP/재개 시험은 추가하지 않았다. 홍동에게 필요한 제공물은 실제 촬영/전달판/Observed 생산자이며 기존 공통 필드 재작성 요청은 아니다.

## Robot 6단계 첫 실행 실패 — ROS float64 타입 수정 (2026-10-06)

사용자가 현장 설정의 `empty_place_and_slot=true`를 저장하고 단일 전달을 실행했다. 사전 IK/FK 37점 검사는 성공했으나 첫 HOME 요청의 ROS C 변환기에서 `PyFloat_Check(field)` assertion으로 프로세스가 abort됐다. **한 블록 전달/observe 복귀는 성공하지 않았으며 실제 재실행은 아직 하지 않았다.**

- 원인: JSON의 `joint_speed=20`, `joint_acc=20`이 Python int로 원본 `movej`에 전달됐다. 원본 CLI는 argparse float였으나 새 설정 연결부가 이 차이를 처리하지 않았다. 설치된 `_move_joint_s.c` 85행은 `vel`의 Python float 검사이며 `acc`도 같은 조건이다. 원본 제어·TCP·pose·속도 값의 문제가 아닌 새 입력 경계의 타입 오류다.
- 수정: [robot_trial.py](../app/robot_trial.py)에서 유효한 수치 설정과 observe pose를 float로 정규화했다. slot/식별/boolean은 그대로다. [회귀 검사](../tests/unit/test_robot_trial.py)는 정수 JSON 입력의 값 동일·ROS 실수 타입 변환·원본 입력 보존을 검사한다. 사용자가 바꾼 설정 JSON·기존 실기 원본은 수정하지 않았다.
- 실제 API 변환 검사: 원본 `RowRobot.movej/line` 호출을 같은 설정/목표로 재사용하고, 실제 `dsr_msgs2` Request와 `rclpy.serialize_message`로 **15개 이동 요청**을 직렬화했다. 이 검사에는 노드/클라이언트/이동 송신이 없다. `--check`와 실행 전 사전 검사에 포함하고 `ROBOT_REQUEST_CHECK` 이벤트로 기록한다. 기존 IK/FK 조회만으로는 이 오류를 찾지 못했던 검증 공백을 보완했다.
- 실제 결과: 관련 순수 검사 **105 passed**, 전체 offscreen 회귀 **511 passed**, 각각 종료 코드 0. 수정 후 실제 `--check` **37점 IK/FK·15개 메시지 변환 통과**, 종료 코드 0, [조회 로그](/tmp/c2-robot-ros-numeric-check-logs/26b78048-569d-42ca-aaa3-f1f3fdb2c09b.jsonl). 신규 이동/개폐/STOP 명령 없음. 실패 이후 조회는 robot_state=1·check_motion=0이다. 조회/직렬화 성공을 장치 전달 성공으로 표시하지 않는다.
- 실패 원자료: 사용자 조회 로그 `logs/robot_trials/90e51355-a0ba-48e2-9f5c-5e2d4e0a7b83.jsonl`, 실행 로그 `logs/robot_trials/efe81e4b-2329-42ca-b6c8-f69d7ca024a1.jsonl` 보존. 실행 로그는 첫 `ROBOT_TRIAL_COMMAND`(HOME)에서 끝난다. C assertion의 프로세스 abort는 Python 예외/STOP/finally를 실행하지 않아 최종 실패 result가 기록되지 않았다. 이를 정상 종료/정지 확인으로 채우지 않았다.
- 범위: 실행 파일·검사와 직접 관련 기록/실행 안내 4개만 변경. 설정 파일의 사용자 확인 변경을 보존하며 GitHub 게시/Robot 재실행 없음. 다음은 현장에서 같은 단일 전달을 재실행하고 실제 놓임/observe 복귀를 확인하는 6단계다. 7단계 실제 STOP/재개·촬영·HMI REAL binding은 여전히 미검증이다.

## Robot 5단계 — 실제 한 블록 시험 준비·무이동 연결 검사 (2026-10-06)

사용자가 Robot **6단계까지 승인**했다. 이번에는 5단계의 단일 시험 실행부와 실제 ROS/RG2 조회를 검증했다. **6단계 실제 전달은 현장 전달판 비움·2번 슬롯 블록·기존 속도/경로 확인 답변을 기다리며 아직 움직이지 않았다.** HMI는 기존 FAKE 연결이다.

- 파일: [robot_trial.py](../app/robot_trial.py), [robot_trial.json](../interfaces/robot_trial.json), [test_robot_trial.py](../tests/unit/test_robot_trial.py) 신규. 이 STATUS·[설계](D_ROBOT_CONTROLLER_DESIGN.md)·[실행 안내](D_BACKEND_RUN_ROBOT_PLAN.md)·[수현 기록](D_BACKEND_PROGRESS.md)만 갱신했다. 기존 Controller/Backend/Qt·공통 Schema·다른 담당/미커밋 자료는 수정하지 않았다.
- 입력/출력: 명시 REAL·검증 원본 경로/해시·슬롯 2·기존 속도/TCP/tool·사용자 observe posj/posx·현장 확인 → 기본 오프라인 계획 / `--check` 조회 / `--execute` 한 블록 전달과 HOME→observe 복귀 / 기존 3필드 result·독립 시험 JSONL. 전달 완료를 조립 Current/Step 완료로 기록하지 않는다. 공급 소모는 상승 후 grip 유지 확인 때 한 번 기록하며 기존 Job/Controller 공급에 연결하지 않았다.
- 재사용/조정: 원본 `--start-block 2`는 2~6번 연속 실행이다. 해당 슬롯 명령만 선택하고 원본 HOME 복귀와 사용자 검증 observe 경로를 연결했다. 원본 pose/TCP/tool/속도/궤적/보간 코드를 바꾸지 않았다. 설정 해시 입력의 초기 오타는 장치 생성 전 차단됐고 원본 실제 SHA-256으로 정정했다. ROS interface 조회 최초 실패는 기존 workspace 환경을 읽어 해결했다. 설치/build/driver 수정 없음.
- L1/Fake 검사: 신규 시험 입력·모드/설정 누락·소스 변경·한 슬롯 제한·정상 명령/속도·상승 후 집기 확인·미감지 집기·놓기/복귀 timeout·보류/재시도 없음·조회 시 이동/개폐 없음·JSONL 식별/로그 실패 차단 **25개**. 최종 전체 `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` → **510 passed**, 종료 코드 0. 기존 485개 포함. 새 클래스는 검사 spy 2개뿐이며 실행 코드의 새 클래스/추상 계층/dependency 0개. lint/type check/CI는 미구성이다.
- 실제 장치 조회: running real M0609/RG2 노드/서비스, robot_state=1(대기), check_motion=0, robot_mode=1, TCP=`GripperDA_v4`, tool=`ToolWeight0`, RG2 status=0/폭 62.1mm 확인. 이름 조회는 TCP 오프셋 측정을 대신하지 않으며 현장 사용자가 TCP/tool 변경 없음을 확인했다.
- 실제 무이동 `--check`: 기존 경로 **37개 표본점 IK/FK**, 사용자 observe 관절의 FK와 제공 posx 일치 확인, 종료 코드 0. [조회 로그](/tmp/c2-robot-stage5-check-logs/8a29e914-22ca-4d22-befa-b62dfb586db3.jsonl). **이동/그리퍼 개폐 없음**, 충돌/시야/전달 성공 증거로 확대하지 않는다.
- 현장 제공물: 노랑 4점 **2번**, 기존 배치 유지, onsite 감시/비상정지 가능 사람·TCP/tool 동일, 제공 observe 좌표와 기존 전달 경로→HOME→observe posj 복귀 검증을 사용자가 확인했다. 실행 직전 빈 전달판/해당 블록·기존 속도(20°/s·40/80mm/s) 확인만 남아 설정의 `empty_place_and_slot=false`로 차단한다.
- 규모/보존: 신규 실행 206줄·검사 251줄·설정 33줄과 직접 관련 문서 4개, 총 7개 파일만 이번 단위다. 기존 전체 시스템을 REAL로 바꾸는 대안은 Fake Vision으로 여러 실제 전달이 나갈 수 있어 단일 시험 경계를 사용했다. 문서 로컬 링크 113개·코드 블록·신규 파일 공백/구문·`git diff --check` 확인, 종료 코드 0. 작업 전 해시 74개 중 문서 4개 외 70개(실기 원본 4개 포함)가 그대로다. 지정 브랜치/HEAD `7af9dae` 유지. GitHub 게시/커밋/PR/merge 없음. 자체 검사는 사람 코드 리뷰를 대신하지 않는다.
- 남은 확인: 6단계 실제 한 번 전달 후 현장 블록 놓임/observe 복귀 확인. 7단계 실제 STOP/재개·이전 요청 종료·블록 상태, 긴 이동 중 HMI STOP, 네 공급열 전체, Camera/홍동 촬영/EMPTY·실제 Backend/HMI binding은 미구현/미검증이다. `move_stop` ACK·프로세스 종료를 실제 정지/재개 허용으로 바꾸지 않는다.

## Robot 4단계 — Controller ↔ Backend·JSONL·Qt Fake 연결 (2026-10-06)

사용자가 Robot 4단계까지 승인해 3단계를 독립 검증한 뒤 4단계를 연결했다. **현재 HMI 시작/정지/재개/보충은 Backend를 통해 Fake Controller/driver로 전달된다. 실제 Robot/ROS/Camera 연결/동작은 없다.**

### 이번 3·4단계 파일과 입출력

- 실행 파일: [robot_controller.py](../app/robot_controller.py), [fake_robot_driver.py](../app/fake_robot_driver.py), [backend.py](../app/backend.py), [fake_demo.py](../app/fake_demo.py), [snapshot.py](../app/snapshot.py). 기존 goal/result 3필드·stop/resume 요청과 공통 HMI Schema 유지. Qt 코드는 수정하지 않았고 기존 버튼/표시 소비 경계를 사용한다.
- 검사: [test_robot_controller.py](../tests/unit/test_robot_controller.py), [test_qt_hmi.py](../tests/unit/test_qt_hmi.py) 보완, [test_robot_backend.py](../tests/unit/test_robot_backend.py) 신규. 다른 담당/기존 검사는 변경하지 않았다.
- 문서: 이 STATUS, [설계](D_ROBOT_CONTROLLER_DESIGN.md), [실행/단계 안내](D_BACKEND_RUN_ROBOT_PLAN.md), [수현 기록](D_BACKEND_PROGRESS.md). 지정 브랜치 유지. 기존 11개 파일 변경과 신규 검사 1개만 이번 단위에 해당한다. 다른 미커밋 변경/실기 자료와 이전 진행 기록은 보존한다.

### 실제 검증 결과

- 3단계 독립 검사 당시 **58 passed** 뒤 연결 경계/잘못된 준비 증거 검사를 추가했다. 최종 `python3 -m pytest -q tests/unit/test_robot_controller.py tests/unit/test_robot_backend.py` → **79 passed**(독립 60개·연결 19개), 종료 코드 0. 장치·ROS·LLM·Qt 없는 검사다.
- `QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/unit/test_qt_hmi.py` → **20 passed**, 종료 코드 0. 기존 HRI/KEEP/REVISE/UNCLEAR 시나리오도 새 Controller에 연결한 상태로 검사했다.
- 최종 전체 `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` → **485 passed**, 종료 코드 0. 기존 팀 연결 소비 검사 17개 포함. lint/type check/CI 미구성, 신규 도구 설치/검사 완화 없음.
- 정상: 3 Step 실제 채택 Current/누적 가림 유지·전체 Design 완료, 슬롯 순서·단일 최종 결과·Job JSONL의 실행/Step 식별·설정 전체 기록을 확인했다. 전달 성공 때는 Current/Step 진행이 증가하지 않으며 새 EMPTY와 조립 관측 확인 뒤에만 다음 전달이 나온다.
- 경계/실패: OCCUPIED/UNOBSERVABLE·색상 차이·닫힌 check·중복/늦은 결과, 공급 보충과 이전 Job 명령 거절, STOP 3상황·증거 누락, 집기/놓기/복귀 실패·timeout·호출 예외, 오류 후 STOP/별도 준비·빈 그리퍼 확인/새 START, 집기·놓기·복귀 로그 실패 시 다음 이동 차단과 STOP 유지, 잘못된 설정/REAL/파일 변경 시 현재 Job 고정을 확인했다.
- Qt 미리보기: offscreen 960×900 창을 실제 렌더링하고 `/tmp/c2-robot-stage4-hmi.png`를 시각 확인했다. 첫 전달 뒤 사람 조립 관측 대기, 진행 0/3·노랑 4점 다음 슬롯 2를 함께 표시한다. 실제 모니터/사람 조립/장치 증거가 아니다. CLI 도움말에서 새 옵션도 확인했다.
- 마무리 검사: 관련 문서의 로컬 링크 97개·코드 블록·JSON 예시, Python 구문·공백·문서의 독립 실행 예를 확인했다. 지정 브랜치/HEAD `7af9dae` 유지, 작업 전 해시 대상 중 이번 11개 변경 외 55개 파일과 추가 tracked 참고 문서 3개·실기 원본/기록 4개가 보존됐다. `git diff --check` 종료 코드 0. 초기 보존 검사에서 한글 Git 경로 인용을 신규 파일로 잘못 비교한 부분은 NUL 구분 경로/HEAD 대조로 수정했다. 저장소 코드/원자료 변경 없이 검증 방식만 바로잡았다.

### 연결 중 조정

1. 정지에서 들고 있음/놓았음이 확인되면 늦은 집기 callback 없이도 해당 슬롯을 한 번 소모한다. 모순된 미집기/불명확 증거는 재집기에 사용하지 않는다.
2. Fake driver가 다음 집기 요청의 상태를 새 미집기로 구분한다. 이전 Step의 놓았음이 다음 Step의 STOP 판정을 대신하지 않는다.
3. 복귀만 요청의 반복 STOP/재개도 새 ID를 사용하고 공급 효과가 없다. 오류 후 STOP 중복이 새 미확인 요청을 남겨 정리 확인을 막지 않는다.
4. 닫힌 Fake Vision/HRI 타이머는 모의 실제 배치/질문도 바꾸지 않는다. 로그 실패 뒤에는 다음 driver 이동을 발행하지 않는다.
5. 설정과 3 Step Fixture 경로·모의 지연은 실행 인자로 주입한다. START마다 읽고 활성 Job/RESUME에서는 설정 복사본을 유지한다. 정상 START는 초기 조립판/전달판 비움·공급판 채움의 명시 확인이다. 오류 정리 확인만으로 Current/슬롯을 초기화하지 않는다.

### 규모·미검증·다음

두 승인 단위의 누적 실행 코드 변화 약 350줄·검사 보완 약 530줄과 직접 관련 문서다. 신규 검사 파일 1개, 신규 클래스/추상 계층/dependency 0개. 누적 규모와 Backend 436줄은 AI 코드 정책의 사람 리뷰 대상이다. 최소 정상/Fake driver 구조를 유지하면서 독립/인접/Qt 검사에 필요한 결과만 검사했으며 자체 검사로 사람 리뷰를 대신하지 않는다.

실제 driver·Robot pose/TCP/속도·안전·Camera/홍동/팀 생산자 연결·장치 시연은 미구현/미검증이다. GUI 오류 상태의 자동 정리는 없고 별도 준비 증거 입력은 현재 독립/Fake 시험 API다. 5단계에서 그 생산자를 연결한다. 추가 GitHub 게시/커밋/PR/merge 없음. 다음은 별도 승인 후 **Robot 5단계 실제 adapter 준비(장치 움직임 없음)**이며 검증된 네 공급열/observe point/복귀 경로, pick/놓기/정지·이전 실행 종료·준비/빈 그리퍼 확인 API, 홍동의 실제 촬영/전달판 반환이 필요하다. 기존 계약 필드 재작성 요청은 아니다.

## Robot 3단계 — Fake 실패·STOP/재개 독립 검증 (2026-10-06)

사용자의 4단계까지 승인 중 3단계를 먼저 진행했다. Controller/Fake driver/기존 Controller 검사와 이 기록만 변경했다. 장치/ROS/Qt 없는 독립 검사 `python3 -m pytest -q tests/unit/test_robot_controller.py` → **58 passed**, 종료 코드 0.

- 집기 전·들고 있음·놓았음의 STOP 뒤 새 실행 ID로 각각 집기/전달/복귀부터 재개한다. 요청 ACK만으로 재개하지 않고 정지·이전 실행 종료·블록 상태 세 증거를 모두 요구한다. 모순된 미집기 증거/UNKNOWN/증거 누락은 보류한다.
- 집기·놓기·복귀 실패/timeout/driver 호출 예외는 실패 결과 한 번과 보류다. 자동 재시도 없음. 확인된 슬롯 소모를 유지하며 일반 재개로 오류를 해제하지 않는다. 오류 정리 후 새 Job 경로는 이어지는 4단계에서 연결한다.
- 추가 조정: 집기 callback이 늦어도 정지 확인에서 실제로 들고 있음/놓았음이 확인되면 슬롯을 한 번 소모한다. 복귀만 재개하던 요청을 다시 STOP/재개해도 새 집기/슬롯 소모가 없다. 이전 실행/정지 결과는 새 실행을 완료하지 않는다.
- 4단계 연결·HMI/로그·설정 식별은 아직 이 검사에 포함하지 않았다. 실제 정지/그리퍼 증거·장치 안전을 검증한 결과가 아니다. 기존 실기 원본·브랜치 유지, 추가 GitHub 게시 없음.

## Robot 2단계 — Fake 정상 전달·슬롯·외부 설정 (2026-10-06)

사용자의 2단계 승인 범위만 구현했다. 기존 브랜치 `work/suhyun-hmi-backend-robot-db`와 다른 미커밋/자료 파일을 유지한다. 신규 파일은 [robot_controller.py](../app/robot_controller.py), [fake_robot_driver.py](../app/fake_robot_driver.py), [robot.json](../interfaces/fixtures/robot.json), [test_robot_controller.py](../tests/unit/test_robot_controller.py)다. 진행 문서는 이 STATUS, [Robot 설계](D_ROBOT_CONTROLLER_DESIGN.md), [실행/단계 안내](D_BACKEND_RUN_ROBOT_PLAN.md), [수현 진행 기록](D_BACKEND_PROGRESS.md)만 갱신했다. 아래 이전/다른 담당 기록은 보존한다.

- 입력/출력: 기존 `execution_id, brick_type, color` goal → 수락 여부/사유 → 모의 집기/놓기/observe point 도착·정지 확인 → 기존 `execution_id, success, reason` 최종 결과 1회. Controller가 조립 완료·Current·기하를 계산하지 않는다.
- 정상/경계 검사: 네 열의 정상 전달, 집기 명령만으로 슬롯 미소모, 집어 올림 확인에만 1회 소모, 복귀 확인 전 성공 없음, 활성/종료 ID 중복·동시 실행·ID 충돌·잘못된 ID·역순·이전 실행의 늦은 확인, 각 열 1~6 소모 후 보충 대기/해당 열만 1번 복원, 기존 3 Step Plan Fixture의 열별 순서를 확인했다. 반복 집기·추가 소모·이중 최종 결과 없음.
- 가변 설정 검사: 지정 파일을 읽고 Fake 공급/전달/관측 위치 이름·슬롯 수를 주입한다. 기본 6, 축소 Fake 검사 1~6 허용. 네 열/지원값/필수값/명시 FAKE를 검사하고 누락·REAL·지원 외 값·잘못된 goal·파일 오류는 그대로 거절한다. 생성 뒤 외부 dict/반환 snapshot 변경이 실행 설정/슬롯을 바꾸지 않는다. 실제 pose/TCP/속도 설정을 생성하지 않았다. Job별 설정 주입/로그는 4단계 대상이다.
- 실제 실행: `python3 -m pytest -q tests/unit/test_robot_controller.py` → **41 passed**, 종료 코드 0. `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` → **438 passed**, 종료 코드 0. 전체에는 기존 팀 연결 소비 검사 17개와 Qt offscreen 11개가 포함된다. Fake Controller 독립 검사는 장치·ROS·LLM·Qt 없이 실행했다. lint/type check는 미구성이며 새 검사 도구를 설치하지 않았다.
- 규모/이유: 실행 코드 약 145줄, 검사 약 240줄, 설정 13줄과 관련 진행 문서만 추가/갱신했다. 신규 클래스 2개·dependency 0개·추상 계층 0개. 300줄 검토 신호는 정상/오류 입력·중복/소모/보충 외부 결과를 확인하는 검사까지 포함한 규모이며, Controller와 명시적 모의 driver의 두 책임만 분리했다. 사람 리뷰는 아직 받지 않았다.
- 미구현/미연결: 실행 실패/timeout·STOP/재개는 Robot 3단계, 새 Controller의 Backend/HMI/로그 연결은 4단계다. 기존 HMI는 이전 QTimer Fake를 사용하고 공급 슬롯은 여전히 미확인이다. 실제 장치·Camera·팀 생산자 연결·사람 조립 시험 없음. 추가 GitHub 게시/커밋/merge 없음.
- 다음: 승인 후 Robot **3단계 Fake 실패·STOP/재개**. 미집기/들고 있음/놓았음의 동작 차이와 정지·이전 실행 종료·블록 상태 확인 부족 시 보류를 검사한다. Fake 검사에 팀원의 계약 재작성은 필요 없다. 실제 연결에는 검증된 네 공급열/observe point/driver 증거와 홍동의 촬영·전달판 실제 반환이 필요하다.

## Robot 0·1단계 — 기존 제어 점검·경계/가변 설정 설계 (2026-10-06)

사용자가 Robot 1단계까지 진행을 승인했고, observe point·협업 설정·Day4 이후 확장 값이 변경 가능해야 한다고 추가 지시했다. 이번 수정은 [Robot 점검/Controller 설계](D_ROBOT_CONTROLLER_DESIGN.md) 신규 문서, [실행/단계 안내](D_BACKEND_RUN_ROBOT_PLAN.md), [수현 진행 기록](D_BACKEND_PROGRESS.md), 이 STATUS다. 신규 Controller/Fake driver/설정 loader/ROS 코드 구현·실기 원본 변경·장치 실행·추가 GitHub 게시는 수행하지 않았다.

- 0단계: 노랑 4점 원본 두 스크립트와 JSON/TXT 실기 기록을 읽었다. 기록상 2~6번 자동 전달/마지막 HOME 복귀와 1번 이전 수동 전달을 구분했다. 과거 설정 13개(TCP/tool·HOME·속도·높이·그리퍼)를 코드와 기록으로 정적 대조했다. 한 블록별 observe point 복귀, 나머지 세 조합, 실제 STOP/재개·집기/놓기 증거는 미검증이다. `--check`도 장치 통신을 사용하므로 실행하지 않았다.
- 1단계: 기존 robot.deliver/stop/resume payload와 callback 의미를 유지했다. Controller의 단일 실행·중복 차단·실제 집어 올림 확인에만 슬롯 1회 소모·보충·STOP 3상황/복귀만 재개·실패 보류를 설계했다. ROS transport와 실제 증거 API는 미확정이며 설계만으로 공통 Schema를 늘리지 않았다.
- 추가 설정 요구: 새 Controller는 외부 설정을 검사해 전달받는다. observe point/pose·동작 값·공급·연결 이름/주소·지원 규격을 분리하고, 활성 Job은 시작 때 검증한 설정을 유지하며 변경 값은 다음 Job에 적용한다. Day4의 PLACE/지원 범위 기본과 실행 중 보정 변경 제외를 유지한다. 이후 새 기능은 설정 값뿐 아니라 담당 기능/공통 계약/검사도 바꿔야 한다. 현재 전체 Python이 이미 가변화됐다고 표시하지 않는다.
- 현재 연결 차이: 공급 snapshot은 null/보충 actions 미연결, SUPPLY_REFILLED는 Controller 미연결 응답, Robot fault 후 HOLD에서 START 경로는 아직 없다. 4단계에서 보충/초기화/오류 정리 후 새 시작·설정 로그 연결을 검토한다. 이번 설계 요청에 코드 수정을 섞지 않았다.
- 실제 검증: 기존 Backend/snapshot/log **33 passed**, 종료 코드 0. 문서 상대 링크/anchor **21개**, JSON 예시 **4개**, 기존 Robot 요청 payload **3종**과 정지 확인 flag **3개** 정적 대조 통과. 상세 `/tmp/c2-robot-stage01-validation.json`. 문서/원본 보존 검사와 기존 구현 검사이며 Controller/Fake driver/장치 성공 결과가 아니다. lint/type check 미구성, 새 검사 도구 설치 없음.
- 지정 로컬 브랜치와 미커밋 자료/실기 원본·설정·측정 기록을 보존했다. 다음 승인 단위는 **2단계 Fake 정상 전달·슬롯·설정 주입 검사**다. 원격에서 독립 진행 가능하다. Real 연결에는 검증된 observe point/네 공급열 설정·실제 pick/놓기/정지·실행 종료 증거가 필요하다. 공통 계약을 팀원에게 다시 작성해 달라는 요청이 아니다.


## C / B 연결 합의 문서 게시 준비 (2026-10-06)

- 사용자 요청으로 C/B DM 이후 합의 내용을 09_C_B_BACKEND_HANDOFF.md에 추가하고 현재 결정·팀 가이드·공통 계약·README에서 연결했습니다. 확정 조건과 지지 수치·관측 묶음 순번 범위·전달판 반환 envelope 등 확인 대상을 구분합니다.
- 최신 main 7dffb50 기반 문서 변경만 리뷰 브랜치로 게시합니다. 수현의 로컬 개발 브랜치 work/suhyun-hmi-backend-robot-db와 기존 미커밋 코드·발표 자료·reference는 보존합니다. 다른 팀원의 C 브랜치·production 코드는 변경하지 않습니다.
- 실제 로컬 확인: 2026-10-06 수현 checkout에서 tests/unit/test_team_handoff.py의 소비 검사 17개 통과, 종료 코드 0. 2026-10-05 전체 283개 통과는 당시 기록입니다. 코드·Fixture·테스트는 현재 별도 로컬 미커밋 개발 상태이며 이번 문서 PR에 포함하지 않습니다. 이 문서 게시를 GitHub CI·실제 B/C 연결·Camera/Robot·다음 전달 gate 검증으로 표시하지 않습니다.
- 다음 확인: B 실제 반환/순번/전달판 예시, C 수정 반환 예시, A/C 지지 후보 규칙. 이후 해당 개발 단계에서 완료·전달 gate 및 실제 모듈 연결을 검증합니다.


## 최신 작업 — Day4 결정 계약과 팀원 준수 사항 (2026-10-05)

- 사용자 요청으로 현재 대화의 결정을 공통 docs에 반영. PLACE·좌표 / 각도·before / after·관측 check·verified_regions·가림 이력·최소 ID / 버전·HRI·Replan·슬롯·STOP 3방향 재개·Qt·JSONL을 정리했습니다.
- 채택 Design의 전체 미리보기를 Qt 한 화면에 포함하고 기존 여섯 snapshot 묶음에 전체 Design 표시 데이터를 추가하도록 명시했습니다. 홍동의 observe point / 전달판 판별은 수정 가능한 제안으로 분리했습니다.
- 기존 C 필드 / 의도명 차이를 이행 표로 남겼습니다. C production skeleton·기존 진행률·실제 장치 설정·reference 원본은 변경하지 않았습니다.
- GitHub 최신 main(4b4f193) 기준 별도 docs/day4-confirmed-interfaces 브랜치에서 문서 10개만 변경합니다. 다른 로컬 브랜치의 미커밋 문서·final_docs·발표 자료는 포함하지 않습니다.
- 현재 계약은 문서상 결정입니다. 공통 실행 Schema·callback / Action / Qt 연결·실제 Robot 정지 / 재개·Camera 인식·전체 Day4 시연은 이번 작업에서 구현하거나 검증하지 않았습니다. 별도 자료 폴더의 과거 독립 시험을 이 저장소의 시험 통과로 표시하지 않습니다.
- 실제 문서 정적 검증: 변경 Markdown 10개, 상대 링크 25개 존재, JSON 예시 5개 파싱, 정상 3 Step 예시의 footprint / 범위 / 지지 / 선행 관계·Design / Plan 연결 확인, 문서만 변경한 범위·git diff --check 통과. README의 존재하지 않는 AGENT.md 안내 링크 제거. 로컬 상세 결과: /tmp/day4_docs_validation.json.
- 실행 앱·Camera·Robot 시험은 수행하지 않았습니다. 다음 작업은 담당별 Fixture와 공통 형식 이행·Mock 연결이며 실제 장치 시험은 별도로 기록합니다.

아래는 이전 작업 당시 기록입니다. 오래된 웹 HMI·미정 좌표 / 식별·원격 게시 전 설명은 현재 결정으로 적용하지 않습니다.


## 최신 작업 — AI 개입 범위와 검증 보고 규칙 (2026-10-05)

- 사용자 제공 노마드 코더 영상의 설명·영어 자동 생성 자막을 확인하고 AGENTS.md에 간결한 답변, 가정 확인, 최소 수정, 기존 자동 검사 활용, 검증 증거 후 완료 보고를 반영.
- 질문/검토와 파일 변경 요청을 구분하고 요청 밖 정리·리팩터링·추상계층·dependency 추가, 실패 은폐, 테스트 약화, 사용자 변경의 혼입을 제한. 승인된 범위는 반복 확인 없이 끝까지 진행.
- 맥락에 필요한 문서만 읽도록 안내를 조정. 기존 역할·목표·구현 경계 보존. 별도 자료 폴더의 최신 계약 결정을 이 저장소의 공통 계약으로 임의 승격하지 않음.
- 별도 로컬 `협동2_프로젝트` 자료 폴더에도 AGENTS.md를 작성해 해당 작업 위치의 새 대화에 지침을 제공. 이미 열린 다른 대화의 자동 재로딩은 미검증.
- 실제 확인: 자료 폴더 53줄/9,168 bytes, 저장소 72줄/10,747 bytes. 상대 링크 4개 존재·외부 출처 링크 3개 표기, 코드 블록·후행 공백·기존 구현 경계 보존 확인 통과. 외부 출처는 영상·공식 문서 조회로 확인. 로컬 상세 결과: `/tmp/c2_agents_validation.json`.
- 실행 코드·Schema·Robot 설정 변경 없음. 앱 테스트·장치 시험·새 lint/CI 설치 없음. 문서 확인을 시스템 통과로 보고하지 않음. 다음 작업은 이번 변경만 담은 새 PR 생성과 사람 리뷰.

아래는 이전 작업 당시 기록이며 현재 원격 상태·구현 완료 여부의 신규 확인 결과가 아닙니다.

갱신: 2026-10-04. **최신 결정 반영·협업 문서·로컬 PR 준비 단계입니다. 앱 구현·장치 시험은 미완료입니다.**

| 항목 | 상태 | 다음 작업 |
|---|---|---|
| 역할·Day 4 범위 | 역할 사용자 재확인·최신 TBD 범위 반영 | 담당별 계약·Fixture 확인 |
| 환경 | Python 3.12.3 로컬 확인, Ubuntu 24.04 / Docker 29.8.2 / NVIDIA 4060 / Jazzy / M0609 / D435i / RG2 사용자 확인 | 실제 OS·Docker·GPU driver·ROS·펌웨어·장치 확인 |
| Design / Plan / Observed | Owner·의미 정리, 정확한 Schema 미정 | 생산자·소비자가 정상 / invalid 예시 확인 |
| Current / Expected·완료 | Backend Owner·전달 / 조립 완료 분리 | 정상 대기 / 실제 차이·최신성 규칙 합의 |
| HMI / 저장 | 웹 HMI API·파일 로그 방향 | framework·API·파일 형식 확인 |
| 공급·Robot | 종류 / 색상별 1~6 순서·고정 전달 | 보충 신호·실패 시 번호·STOP / 취소 시험 |
| 좌표·GT | 과거 기록·원본 pose 보존 | 공통 grid·layer·방향·판별 범위·실측 확인 |
| 일정 | H12의 Day 1~4 개발 단계 | 실제 날짜·가용 시간·시험 횟수 합의 |
| Day 4 / 최종 버전 | 공통 코드 + 검증 태그 운영 제안 | 팀 합의·시연 검증 후 태그 생성 |
| Git / PR | 빈 원격 확인·최소 기반과 문서 변경 준비 | 사용자 변경 검토 후 게시·Draft PR |
| 실행 코드·테스트·CI | 이 저장소에 없음 | 계약 합의 후 작은 기능별 구현·검증 |
| C Design (시율) | `app/c_design/` docstring skeleton·문서, 진행률 0% — [C_DESIGN_PROGRESS.md](C_DESIGN_PROGRESS.md) | C Contract |
| Isaac Sim | 후속 검토 후보 | Day 4 결과·목적·PC 사양 확인 |

## 이번 문서 작업

- README·현재 결정·역할·일정·측정·Sim·Git·에이전트 안내·PR 템플릿을 최신 결정으로 정렬.
- `06_CONTRACT_DRAFT.md`와 팀원 작업 Issue 템플릿 추가. 필드·정책 초안은 확정된 계약과 구분.
- `docs/reference/` 8개 원본과 기존 pose 배열 보존. 사진·Depth·실행 코드 추가 없음.
- 기존 파일 대비 10개 수정·2개 추가. 문서 간 과거 역할·일정의 충돌을 함께 수정하기 위한 범위이며 runtime 구조·dependency 변경 없음.
- 로컬 기반 브랜치 `bootstrap/pr-base`, 변경 브랜치 `docs/latest-decisions-collaboration`로 최초 PR 비교를 준비. 원격 게시·PR 생성·태그 생성은 후속 단계.

## 사용자 검토 반영

2026-10-04: Ubuntu 24.04 / Docker 29.8.2 / NVIDIA 4060과 역할 분담 확인을 반영했습니다. 실제 문서 폴더와 향후 코드 구조 제안을 Git 가이드에서 구분합니다. 앱 폴더·공통 Schema·Docker 실행 구성은 아직 생성·확정하지 않았습니다.

## 실제 확인과 미검증

- `python3 --version`: Python 3.12.3.
- 원격 조회: GitHub size=0·브랜치 없음, 로컬 커밋 없음 확인 후 기반 준비.
- 문서 정적 확인 통과: 현재 Markdown 13개·상대 링크 16개·표 15개·코드 블록 7개. 참고 원본 8개 해시 일치·pose 기록 일치. 외부 링크의 접근성과 앱 동작은 이 검사 범위 밖.
- Git 공백 검사: 현재 문서 통과. 전체 최초 추가에는 참고 원본 2개 파일의 기존 후행 공백 17줄이 경고로 남으며 원본 보존을 위해 수정하지 않음.
- 미검증: 앱·Schema·pytest / CI·D435i 인식·ROS Action·Robot 전달 / STOP / 취소·HMI·전체 시연. 문서 검토를 시스템 성공으로 표시하지 않음.

## 다음 구현 전에 확인할 사항

1. 시율·세은·홍동·수현: 동일 Design / 상태의 필드·기하·grid·layer·방향·정상 / invalid Fixture.
2. 세은·수현: Step 목표 / 효과·제거 / 재배치·Robot 전달 필요 여부.
3. 홍동·수현: 관측 품질·가림·정상 조립 대기 / 차이·callback / Topic 관계.
4. 시율·수현: 모델·구조화 출력·질문 / STT·비정상 응답·식별 / 버전.
5. 수현: 공급 보충 / 실패 처리·실제 driver·고정 좌표·STOP / 재개·HMI API / 로그.

내부 문서·PR 준비는 진행할 수 있습니다. 공유 필드·물리 판별·실측 값은 담당자 확인이 필요하며 이번 작업에서 임의 확정하지 않습니다.

## 작업·trial 기록 양식

작업: 날짜 / 담당 / 작은 목표 / 변경 파일 / 입력·출력 계약 / 실행한 검증 / 실제 결과 / 미검증 / blocker / 다음 작업.

trial 항목 제안: trial_id, scenario_id, mode, 입력 관측·촬영 시각, Design / Plan / Calibration 버전, 비교 Step·Difference, 질문·응답, 채택 결과, Robot 실행·전달 결과, 검증 범위·성공 / 실패 사유·소요 시간·증거 파일. 정확한 영문 필드명은 계약 확인 후 정하며 실패 trial도 기록합니다.

## 2026-10-06 — 실제 A Planner 연결 검증

세은의 a_manual_execution.tar.gz를 읽고 원격 work/seeun-planning의 f9b841c8f090b0b25c30ab27459781ad2017fd9e에서 planning_trial을 수정 없이 가져왔다. Planner 소스 SHA-256이 첨부 실행 기록과 일치한다. C의 첨부 Mock Initial/Revised 응답을 받아 실제 A 함수를 D에 연결했다. Initial 성공 응답은 on_initial_design으로 받으며, design이 있는 planner 요청은 run_planning_request로 실행한다. C에 Current blocks 목록을 전달하는 helper와 성공 HRI 응답 연결도 준비했다. 실제 C/LLM/음성 함수는 호출하지 않았다.

빈 Current READY 15 Step, 부분 Current READY 11 Step, 색상 차이 NEEDS_CORRECTION, 5층 INVALID를 A 실제 함수로 재현해 D 채택/보류·Qt·JSONL을 확인했다. 네 관측 Step의 Current revision=4로 재계획하면 11 Step이며 base_current_revision=4다. 첨부 묶음 Current의 revision=1 사례와 구분한다. 이동된 Current를 유지하는 C Mock Revised v2와 실제 A의 11 Step을 채택해 FakeRobot·관측으로 전체 완료했고, 별도 정상 15 Step도 전체 완료했다. 전달 성공만으로 Step/Current를 완료하지 않는다. Revised에서 누적 공급 6개 이후 보충 대기·명시 보충·새 EMPTY를 유지했다.

첫 Plan 채택 전 사람 정리 재관측의 이전 미연결 제한을 해소했다. D 내부 check의 plan_id/step_id를 둘 다 null로 허용하고 가짜 Plan/Step을 발급하지 않는다. Vision 외부 callback 필드는 바꾸지 않았다. 이 문맥은 Current 채택만 가능하고 조립 Step 완료 증거가 될 수 없다. 단위·통합 검사를 추가했다. startup의 실제 빈 보드 관측 자동 연결은 이번 범위가 아니다.

최종 코드 변경 후 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` → **707 passed**, 종료 코드 0. A 독립 검사 **112 passed**, 새 실제 A/D 연결 검사 **24 passed**, 각각 종료 코드 0. Qt는 offscreen, Robot/Observed는 Fake이며 실제 장치 성공이 아니다. [실행 결과 JSON](../logs/a-backend-connection-guy8gbim/results.json)과 같은 폴더의 시나리오별 Job JSONL을 보존했다. logs는 로컬 산출물로 원격 clone에 없다. lint/type는 미구성이고 새 dependency를 설치하지 않았다.

[연결 안내](D_A_PLANNER_HANDOFF.md)에 호출법·범위·남은 작업을 갱신했다. 기존 3-Step FakeDemo는 별도 독립 시험용으로 유지한다. C 실제 호출의 다른 인자·Difference 변환·음성/질문·취소 Workflow, B 실제 callback·촬영, 실제 Robot driver/pose/STOP/재개는 남아 있다. 자동 복구·DB·MOVE/REMOVE·미검증 pose를 추가하지 않았다. 로컬 작업 브랜치와 기존 미커밋 변경을 보존하고 이번 PR에서 연결 코드와 검증 기록을 게시한다. main 병합은 하지 않는다.


이번 게시에는 A–D 통합이 사용하는 Fake Robot Controller·driver와 관련 검사도 포함한다. 별도 작업의 REAL 장치 시험·터미널 수동 입력 HMI·발표 자료·팀 공통 문서 변경은 포함하지 않는다. 707개는 로컬 전체 검사이며, 게시 파일과 최신 main을 합친 독립 검사 결과는 PR에 별도로 기록한다.


PR 게시 대상과 최신 main을 합친 독립 파일 트리에서 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` 실행: **884 passed**, 종료 코드 0. main의 C 검사도 포함하며, 별도 REAL 장치 시험·수동 입력 HMI 검사는 이번 게시 범위에서 제외한다. 실제 Camera/Robot 시험은 수행하지 않았다.

## 2026-10-06 — 독립 DB 이력·계정·의미별 조회 PR

사용자 요청으로 기존 DB 병행 개발을 별도 PR로 준비했다. 기존 Day4 공정은 Job별 JSONL을 유지하고, 별도 명령 컨테이너가 PostgreSQL에 적재·조회한다. 공정 Backend·Qt·A/B/C·Robot·Camera 소스와 공통 계약은 이번 PR에서 변경하지 않는다. 실행 방법과 출력 의미는 [DB 이력 안내](D_DB_HISTORY.md)를 따른다.

- 저장표는 jobs/events/artifacts/sources/users 5개다. 원본 JSONL 문자열과 JSONB, 채택 Design/Plan/고정 기준 Current를 보관한다. 동일 원본/행 재적재는 건너뛰고 변경 원본·채택 자료 충돌·입력 오류는 파일 트랜잭션을 rollback한다. 줄바꿈 전 마지막 행은 보류한다.
- 계정 생성·목록·비밀번호 확인, designs/currents/plans/hri 조회와 JSON 보고서를 포함한다. 비밀번호는 계정별 salt와 scrypt 해시로 저장하며 일반 반환에서 해시를 제외한다. 사용자 지정 다섯 계정은 기존 로컬 시험 DB에만 있고 PR에 비밀번호·계정 seed·DB 자료는 포함하지 않는다. 새 설치는 init 후 create-user로 계정을 만든다.
- 조회는 적재된 이력이다. 마지막 채택 Plan을 실시간 active 상태로 해석하지 않으며 누락 문맥은 null/빈 배열로 둔다. HMI 로그인 세션·개인 도안 소유자·QR/얼굴인식·DB 상태 자동 복원은 미연결이다. 전달 성공을 사람 조립 완료로 처리하지 않는다.
- 로그 Schema는 기존 봉투와 소비 결과를 구조화하고 공통 Schema를 참조한다. Python 적재부는 기존 Consumer 검사를 재사용한다. Docker 빌드 제외 설정에 공통 Schema 경로를 포함해 이미지 복사를 확인했다. 신규 실행 의존성은 별도 history 환경의 psycopg[binary]==3.3.6이며 ORM·웹 서버·추상계층은 없다.

게시 기준은 main f45e9f3이다. 기존 지정 checkout을 전환하지 않고 별도 Git worktree에서 DB 파일만 구성해 검증했다.

- 게시 트리 전체 tests 및 planning_trial/test_planner.py: **1241 passed**, 종료 코드 **0**. Qt offscreen·별도 실제 PostgreSQL c2_history_test DSN을 사용했다. 로컬 미게시 HMI 변경은 이 검사 대상에 섞지 않았다.
- 해당 게시 이미지의 실제 DB 명령 **23개**: 성공 경로 22개는 종료 **0**, 없는 입력 파일 실패 경로 1개는 예상 종료 **1**. 정상 FAKE Job 24행·Revised FAKE Job 30행의 원문, 네 조회와 보고서 일치, 재적재 inserted=0/skipped=24·30, 기록 없는 Job의 빈 배열, 공개 계정 목록을 확인했다.
- 컨테이너 시험 직전 기존 이벤트·채택 자료와 다섯 계정 전체 값을 시험 후 대조해 보존을 확인했다. init은 자료를 지우지 않았고 볼륨 삭제·운영 DB 사용·계정 초기화는 하지 않았다. 실제 장치 실행은 없다.
- DB 관련 단위·실제 PostgreSQL 검사만 실행한 결과도 **102 passed**, 종료 코드 **0**이다. 게시 결과는 별도 후속 기록에 남긴다. 증거는 Git에서 제외되는 로컬 logs/history_reports/pytest-pr-publication-full.txt·pytest-pr-publication.txt·pr-container-validation.json이다. 새 clone은 안내의 재현 순서로 생성한다. 기존 lint/type check·CI는 미구성이며 실제 Camera/Robot·C API·전체 장치 통합과 사람 리뷰는 미검증이다.


## 2026-10-07 — 미게시 HMI·음성·Robot 실행 코드의 기본 버전 PR

- 사용자 요청으로 현재 로컬 기본 실행 코드를 PR로 보존하고 팀장 계정 병합을 준비했다. 최신 main `a459e13`에서 별도 worktree를 만들어 미게시 Backend/Qt·C 함수/STT/TTS·네 공급열·명시 사전 이동·STOP/probe/확인된 기록 재개와 관련 검사/Schema/Fixture만 옮겼다. 기존 main의 C/A/B/DB·최신 팀 계약·CODEOWNERS를 유지했다. 로컬 발표/제출 초안과 새 사람 전달 0단계는 이 PR에서 제외하고 원본/백업에 보존했다.
- 게시 트리 검사 `env -u HISTORY_TEST_DSN QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q`: **1371 passed, 24 skipped**, 실패/오류 0, 종료 0. 24개는 별도 실제 DB DSN 필요 검사다. Robot/Camera/음향/외부 API는 실행하지 않았다. Python/JSON 파싱·diff 공백 확인. CI/lint/type 추가 없음. 기존 실기 STOP/재개·현재→HOME 경로·음성/Camera 연결의 현장 미검증 상태는 유지한다.
- 팀원 리뷰가 어려운 상황에서 사용자가 팀장 권한 병합을 명시적으로 요청했다. PR에 동료 리뷰 미수행과 사용자 승인 사유를 기록하며 자기 Approve나 가짜 사람 리뷰를 발행하지 않는다. 기존 보호 규칙은 변경하지 않는다. [기본 버전·백업·복구 방법](D_RUNTIME_BASELINE.md)을 확인한다. 실제 병합과 태그는 GitHub PR/커밋 상태로 구분한다.
