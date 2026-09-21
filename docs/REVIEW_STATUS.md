# 진행 현황과 남은 작업

## 2026-09-21 최신 main 기준

원격 `main`은 `19ef4c6`(PR #40 병합)이다. 9/20에는 PR #34·#32·#36·#38·#39가 병합돼 공정 보조 모듈, 실측 근거, c2_path 계산/Action 서버, HMI↔c2_path 부분 통합이 반영됐다. 9/21에는 PR #41의 SIM 스냅샷·ZIP 파일 교환과 PR #40의 실측 선행 공정 역할 문서가 추가됐다. 상세 일자별 근거는 [0920 개발 일지](../ws_cobot_pjt/docs/daily/2026-09-20.md)와 각 검증 기록을 따른다.

### 현재 구현

| 영역 | main 상태 | 검증·제한 |
| --- | --- | --- |
| 공통 계약 | `c2_interfaces`의 Action 2개·Service 1개·Message 2개, 고정 드릴 `schema_version=2` | Jazzy 타입 빌드·직렬화 기록 있음. 측정 선행 준비 요청·결과 계약은 아직 미반영 |
| HMI·서버 | React·FastAPI·SQLite, MOCK 흐름, native rclpy `RosBridge`, 관리 파일 로더, 경로 미리보기, SIM 파일 교환 | HMI↔c2_path 정상/실패/중복/단절 시험 기록 있음. 실제 공정·로봇 연결은 미검증 |
| c2_path | 이미지→SVG→2D→원통 3D 경로→검증, `/c2/generate_path` Action 서버와 산출물 저장 | main 존재. 고정 상수 기반 `SIMULATION/test_only`; 승인 REAL 설정과 실제 제어기 IK·충돌·가공 미검증 |
| c2_process | `robot_adapter.py`, `tool_calibration.py`, `joint_check.py`, `engraving.py`와 모의/비동작 확인 코드 | 내부 소스만 존재. `node.py`·상태 기계·preconditions·패키지/launch/실행 YAML·`workpiece_calibration.py` 없음 |
| 전체 공정 | 목표 순서와 담당 경계 문서화 | 준비·양초 실측→스냅샷→경로 생성→미리보기→최종 검사→조각의 송수신/함수 통합과 실기 미완료 |

### 현재 통합 기준

역할 연결은 **이시율 측정 → 실측 좌표 전달 → 노홍동 경로 생성 → 김세은 관절 검사 → 이시율 조각**이다. 철사 고정 드릴은 그리퍼 열기·자동 집기·반납·청소를 금지한다. 도구 장착 보정과 양초 위치 측정을 구별하고, 첫 통합에서는 기존 장착 기준을 재사용하면서 양초 중심·높이 측정과 모의 연결을 우선한다. 생성 후 경로를 다시 옮기는 `prepared_path.py` 단계는 제외한다.

최종 미리보기·관절 검사·실행은 같은 경로 ID·버전·해시와 설정/측정 스냅샷을 사용해야 한다. 현재 v2에는 경로 생성 전 준비 요청, 측정 결과 전달, 취소 가능한 드릴 ON 확인 입력이 없으므로 명세·공통 타입·송수신자·시험을 함께 변경하기 전까지 구현된 계약으로 취급하지 않는다.

### 우선 남은 작업

1. `workpiece_calibration.py`와 측정 접근·터치·후퇴의 사전 검사, 취소·정지·실패 반환을 구현한다.
2. 준비 요청·측정 스냅샷 등록/전달 계약을 확정하고 HMI·공정·c2_path를 같은 버전으로 연결한다.
3. c2_path의 test_only 상수를 실측 스냅샷 입력으로 바꾸고 설정 ID·해시·단위·좌표계 검사를 유지한다.
4. `process_controller_node`, state_machine, preconditions, c2_process 빌드/launch/설정 로딩을 구현한다.
5. 같은 최종 경로의 전체 IK/J5/J6·보간·충돌 검사와 실패·중복·시간 초과·정지 후 진입 차단을 모의 통합한다.
6. SIMULATION 통합 뒤 승인된 현장 설정으로 짧은 실기, 반복 측정, 물리적 홈 깊이·품질을 별도 검증한다.

GitHub 원격 참조는 `git fetch origin --prune`으로 확인했다. 이 환경에는 `gh` CLI가 없어 열린 PR·Issue·Actions의 인증 조회는 수행하지 못했으며, 병합 상태는 fetch한 main 이력과 저장소 내 검증 기록으로 대조했다. 아래 절은 날짜별 과거 기록이며 최신 상태로 사용하지 않는다.

## 2026-09-19 현재 확인

main `301ea6e`에서 PR #16·#17·#18·#20·#21 병합을 확인했다. 공통 타입 v1·HMI·SQLite·MOCK·로봇 어댑터가 있으며 전체 좌표/공정 노드·보정·실기 통합은 미완료다. 작업 중 재조회에서 [PR #23](https://github.com/suuuhululu/C-2/pull/23)(frame), [PR #25](https://github.com/suuuhululu/C-2/pull/25)(engraving), [PR #27](https://github.com/suuuhululu/C-2/pull/27)(tool_calibration)이 추가됐으며 아직 미병합이다. 세 PR의 repository-checks는 성공했고 실기 통합 완료는 아니다.

이번 `codex/fixed-drill-contract` 변경은 [고정 드릴 6개 모듈·통신 v2](../ws_cobot_pjt/docs/C2_FIXED_DRILL_20260919.md)와 HMI 모의 흐름·문서 정합성을 반영한다. 이 문서 작성만으로 main 병합 완료를 뜻하지 않는다. 담당자 배정은 제안이며 Issue·일정 자동화를 바꾸지 않았다. [문서 점검 목록](../ws_cobot_pjt/docs/DOCS_AUDIT_20260919.md).

아래 9/18·9/17 PR·역할·구현 상태는 당시 기록이다. 현재 기준으로 재사용하지 않는다.


## 2026-09-18 일지 기준 현황

Notion과 GitHub를 대조한 [0918 개발 일지](../ws_cobot_pjt/docs/daily/2026-09-18.md)를 추가했다. 기준 main은 `c414821`이며 PR #5·#7·#9·#10·#11·#13이 9/18 main에 병합됐다. 로봇 어댑터는 main에 있고, PR #15의 조각·청소는 `feat/12-robot-adapter`에만 병합됐다. PR #16(아키텍처·Clay 보관/제거)과 #17(HMI·SQLite·모의 게이트웨이)은 확인 시점 Draft·미병합이다.

일지에는 곡면 가상 검증, 어댑터 단위 실기 **보고**, 조각·청소 및 HMI 모의 시험 **보고**, 공통 설정 담당과 통합 전 대조 항목을 구분했다. 원본 bag 분석이나 로봇 재시험은 수행하지 않았다. 새 3개 노드 전체 공정의 ROS 통합·실기 완료는 미확인이다. 아래 9/17 현황은 당시 기록이며 오늘의 병합·역할·구현 상태는 0918 일지와 각 PR을 우선 확인한다.

확인일: 2026-09-17 (한국 시간). 0917 일지 작업에서 GitHub의 main·PR·최근 Actions를 다시 조회하고 로컬 기준 커밋과 대조했다. Issue·상세 보호 규칙은 아래에 표시한 앞선 확인 기록을 유지한다. 문서는 자동 동기화되지 않으므로 후속 작업 때 실제 상태를 다시 확인한다.

## GitHub에 반영된 작업

| 항목 | 확인한 결과 | 근거 |
| --- | --- | --- |
| 초기 폴더·협업·자동화 구성 | 9/16 `gimseeun` 승인 후 PR #1 병합 | [PR #1](https://github.com/suuuhululu/C-2/pull/1) |
| 외부 로봇 실행환경 Git 제외 | 9/16 `sskywalker1209-prog` 승인 후 PR #3 병합. `ws_dsr/src/` 전체 제외, 자리표시자 추적 해제, 출처·환경 기록 반영 | [PR #3](https://github.com/suuuhululu/C-2/pull/3) |
| 메인 구조·음각 설계 문서 | PR #4가 9/17 18:20:46 KST에 main으로 병합됨 | [PR #4](https://github.com/suuuhululu/C-2/pull/4) |
| 관련 Issue | #2 닫힘, 봇 운영 현황과 라벨 모두 `done` | [Issue #2](https://github.com/suuuhululu/C-2/issues/2) |
| 기본 브랜치 | `main`, 확인한 커밋 `baf12997c87588cbdb0e3bc73ff2e56e8455a3f0`. 이번 일지의 작업 시작 커밋과 일치 | [main 확인 커밋](https://github.com/suuuhululu/C-2/commit/baf12997c87588cbdb0e3bc73ff2e56e8455a3f0) |
| 원격 작업 목록 | 일지 작성 전 열린 PR 0개를 재확인. Issue 0개는 앞선 같은 날 조회 기록. 프로젝트 구현 완료를 뜻하지 않음 | [PR 목록](https://github.com/suuuhululu/C-2/pulls), [Issue 목록](https://github.com/suuuhululu/C-2/issues) |

main에는 초기 파일·외부 소스 제외·메인 구조·음각 설계 문서가 있다. 저장소 초기화나 이미 병합된 PR을 다시 처리할 필요는 없다.

## 현재 작업 브랜치와 설계 기록

앞선 `chore/remove-mini-workspace` 작업에서는 아래 25개 파일 변경을 `7fdfe7f`로 커밋하고, 음각 설계를 `a18adfe`로 추가했다. 두 변경은 PR #4로 main에 병합됐다.

- 사용자 요청으로 연습용 워크스페이스와 전용 실습 문서·빈 폴더를 삭제했다.
- 메인 프로젝트 `ws_cobot_pjt`와 공통 운영 문서를 중심으로 경로·안내를 정리했다.
- Issue/PR 양식과 처리 코드의 프로젝트 분류를 `main`·`common`으로 정리했다.
- 현재 진행 상황에 맞게 완료·확인 대기·로컬 변경을 문서에 구분했다.

추가로 사용자와 정리한 원기둥 음각 프로젝트의 서비스 흐름, 중간 세척·오류 처리, PC·웹앱·ROS 아키텍처, 알고리즘 검증 보고서, 현장 설정 확인 범위와 실험 계획을 `ws_cobot_pjt/docs`에 문서화했다. [프로젝트 계획과 문서 색인](../ws_cobot_pjt/docs/PROJECT_PLAN.md).

현재 추가 작업은 `docs/0917-unit-function-log`다. [0917 개발 일지](../ws_cobot_pjt/docs/daily/2026-09-17.md)를 `6f594b1`로 먼저 커밋했고, 사용자의 추가 요청에 따라 [수현의 SVG 비교 검증보고서 2](../ws_cobot_pjt/docs/SVG_VECTORIZATION_VALIDATION.md)를 반영했다. 이번 요청 범위는 작업 브랜치 게시와 PR 작성까지다. [작업 브랜치](https://github.com/suuuhululu/C-2/tree/docs/0917-unit-function-log)와 [PR 목록](https://github.com/suuuhululu/C-2/pulls)에서 게시 상태를 확인하고, main 병합은 동료 승인과 필수 검사 이후 별도로 진행한다.

| 구분 | 문서에 정리한 내용 | 검증 수준 |
|---|---|---|
| 서비스·시스템 설계 | 원기둥 맞춤 음각, 운영 PC 1대, 웹앱 세 화면, 작업 관리자·ROS·제어기 분리 | 설계 문서 |
| 세척·오류 흐름 | 스펀지 세척 시점·동작·복귀, 오류 대기·확인 후 재개 | 설계 문서, 실기 미수행 |
| 알고리즘 결과 | 작업선 73.36%, 최종 좌표 12.39%, 전개도 비가공 이동 70.30% 감소 | 기존 오프라인 수치 기록, 실물 성능 아님 |
| 평면 DRL 초안 | 기본 비활성화·설정 누락 시 모션 호출 없음 등 이전 확인 요약 | Python 대체 검사 기록, native DRL·실기 미검증 |
| 후속 시험 | 전환·사람 작업·세척 시간, 각도별 홈 깊이·폭·실패율 | 시험 계획 |
| 0917 평면 단위 실기 | 지점토의 선분·정사각형·원·별, 재료 뭉침 관찰 | 사용자·Notion 수행 보고. 정량 품질·반복성·실행 코드 연결 보완 필요 |
| 시율 사전 작업 자동화 | 접촉식 측정 노드의 흐름·코드, 수동 공구 전달·길이 측정·SVG 크기 맞춤 개발 | 본문·코드 확인과 사용자 보고. 원본 로그·공통 모듈·수정 후 실기 재검증은 별도 |
| 팀 알고리즘 검토 | 홍동의 말 SVG 수치, 세은의 좌표 변환 검증 표, 수현의 기존 전처리 결과 | 서로 다른 입력·단위의 오프라인 결과. 일지 작성 중 재실행하지 않음 |
| SVG 영역 보존 추가 검증 | 네 도안·네 후보 비교, Potrace 1.16 선택, 독립 요소 140/140·빈 영역 254/263 | 첨부 보고서 전체 열람·수치 전사. 실험 재실행·실물 가공 검증 아님 |

개인 작업 폴더의 원본 이미지, 전체 알고리즘 소스·SVG·좌표 파일과 실행 초안은 이번 문서 변경에 포함하지 않았다. 결과 근거 일부와 해시를 공유했으며, C-2만 clone해서 기존 실험이나 로봇 작업을 바로 실행할 수 있다는 의미가 아니다.

## 보호와 자동 검사

- 9/17 재확인: main의 `protected` 상태와 `main-pr-only` 규칙이 활성 상태다. [서버 규칙](https://github.com/suuuhululu/C-2/rules/23389654).
- PR 필수, 승인 최소 1명, 새 커밋 시 이전 승인 무효화, 검토 대화 해결, main 삭제·강제 push 차단이 설정되어 있다.
- 필수 검사 `repository-checks`는 GitHub Actions 출처(ID 15368)와 최신 main 반영을 요구한다. 우회 대상 없음은 9/16 인증 조회에서 확인한 기록이며, 이번 공개 조회에서는 우회 목록을 재확인하지 않았다.
- 이 clone의 `core.hooksPath=.githooks`를 확인했다. 다른 팀원은 각 clone에서 [hook 설치](GIT_GUIDE.md)를 해야 한다.
- PR #3 최종 커밋 `09f2be641ab838f06a9ba0e2025b93f754b8f184`의 [push 검사](https://github.com/suuuhululu/C-2/actions/runs/35049166460)와 [PR 검사](https://github.com/suuuhululu/C-2/actions/runs/35049169231)가 성공했다.
- PR #4의 `a18adfe`에 대한 [push 검사](https://github.com/suuuhululu/C-2/actions/runs/35203334752)와 [PR 검사](https://github.com/suuuhululu/C-2/actions/runs/35203492559) 성공을 이번 일지 작업에서 재확인했다. 일지 브랜치의 원격 CI 성공으로 바꾸어 표시하지 않는다.
- 앞선 설계 문서 작업에서는 텍스트·Python 구문·상대 링크 35개 파일을 검사했다. 0917 일지 추가 작업에서는 문서 검사 대상 36개 파일, Git hook 시험 8개, Issue 자동화 시험 27개, 팀 설정 형식·셸 구문·공백 검사를 통과했다. 원격 CI와 ROS·실기 시험은 별도로 구분한다.
- 검증보고서 2 추가 후 문서 검사 대상 37개 파일, Git hook 8개·Issue 자동화 27개 시험, 팀 설정·공백 검사를 다시 통과했다. 첨부 보고서 해시와 전사 수치의 요소 합계·반올림 평균도 대조했다. 알고리즘이나 실기 재시험은 아니다.

## Issue 자동화의 실제 확인 범위

`Repository checks`와 `Issue management` 워크플로는 모두 활성 상태다. Issue·댓글 이벤트와 [예약 실행](https://github.com/suuuhululu/C-2/actions/runs/35107869058)의 성공을 확인했다. 예약 설정은 평일 18:40 KST이며 실제 실행은 지연될 수 있다.

| 확인한 동작 | 증거·한계 |
| --- | --- |
| 운영 현황 댓글·분류 라벨·최초 마감·임박 안내 | [Issue #2](https://github.com/suuuhululu/C-2/issues/2)에서 생성됨 |
| 기존 담당자 유지 | #2는 처음부터 `suuuhululu`가 지정되어 있었음. 미배정 작업 자동 분배를 원격 검증한 사례는 아님 |
| 검토 상태 명령 | 한 줄짜리 `/team review`로 `todo → review` 반영. [봇 응답](https://github.com/suuuhululu/C-2/issues/2#issuecomment-5691224662) |
| 종료 상태 반영 | PR #3 병합으로 #2가 닫힌 뒤 봇이 `done`과 일정 라벨을 정리. [실행 결과](https://github.com/suuuhululu/C-2/actions/runs/35059330474) |
| 아직 원격 연습이 필요한 동작 | 미배정 자동 분배, 시작·막힘·재열기, 일정 변경 요청과 팀장 승인·반려. 로컬 시험 통과와 구분 |

상태 명령에 설명·PR 링크를 같은 댓글로 붙이면 거절된다. `/team start`, `/team review`, `/team todo`는 **명령만 적은 별도 댓글**로 작성한다. 결과 설명과 링크는 다른 댓글에 남긴다. [자동화 사용법](ISSUE_AUTOMATION.md).

## 팀·환경·구현 상태

- 팀 계정 4명은 `.github/team.json`에 활성·`general`로 등록되어 있다. 담당 분야는 아직 미정이다. 팀장 Admin, 나머지 세 명의 초대 수락·Write 권한은 9/16 확인 기록이며 이번에는 권한 변경을 하지 않았다.
- 공용 MSI Ubuntu: 사용자가 Docker 에뮬레이터를 통한 가상 로봇 동작을 보고했다. 정확한 소스 커밋·설치 버전·로컬 수정 여부는 확인 대기다.
- 이시율 PC: Ubuntu 24.04·Jazzy, `cobot_rg2` 커밋 `4d5657f36a160eedb533ab1c975cd8a30c3e53b2`, dsr_emulator 3.0.1, 35개 패키지 빌드·가상 로봇 이동 성공을 [팀원이 보고](https://github.com/suuuhululu/C-2/issues/2#issuecomment-5691159901)했다. 문서 작성자가 직접 수행한 시험이나 팀 전체의 버전 확정은 아니다.
- Mac은 편집·Git 관리에 사용한다. 이 작업에서 ROS·Docker·시뮬레이터를 설치하거나 로봇을 구동하지 않았다. 환경별 자세한 기록은 [DEPENDENCIES.md](DEPENDENCIES.md)를 따른다.
- C-2에는 원기둥 맞춤 음각 서비스의 기획·검증 결과·시스템 설계를 문서화했고, 0917 일지에 평면 단위 실기와 팀별 개발 보고를 추가했다. 팀 ROS 패키지·서버·화면의 통합과 원기둥 실기는 아직 완료되지 않았다. 현재 개발 담당과 장기 통합·검토 책임 배정도 구분한다. [프로젝트 계획](../ws_cobot_pjt/docs/PROJECT_PLAN.md).
- 평면 단위 실기 수행 보고는 확보했지만 실제 그리퍼 모델·제어기·배선, 시험별 코드 버전과 정량 품질 기록은 보완이 필요하다. 가상 이동·단위 시연·PR 병합을 전체 파지·가공 공정 완료로 표현하지 않는다.
- GitHub Projects·외부 캘린더 동기화와 AI 자동 PR 리뷰는 이 작업에서 구성한 기록이 없다. 연결 상태는 별도 확인이 필요하며, 현재 자동화의 기준은 Issue 라벨과 봇 댓글이다.

## 다음에 할 일

1. 0917 일지·추가 SVG 비교 문서를 작업 브랜치와 PR로 공유하고 동료 검토를 진행한다. 시험 조건·실행 코드·사진·로그·정량값과 Potrace의 미달 빈 영역 9곳 자료를 보완한다. 기존 폴더 정리·설계 PR #4는 이미 병합됐다.
2. 팀원이 연습용 Issue로 미배정 자동 분배 → 시작 → 일정 요청·승인 → 검토 → 종료를 확인하고 실제 결과를 기록한다.
3. 문서화한 음각 서비스의 최소 시연 범위·실기 성공 기준과 담당자·검토자를 정하고 구현 Issue를 만든다.
4. 공용 MSI의 실제 소스 버전과 수정 여부를 기록한다. 동작 중인 설치를 이번 문서 정리 때문에 재설치하지 않는다.
5. 제안된 `setup_host.sh`와 `setup_and_run.md`는 아직 C-2에 없다. 팀원이 제공하면 설치 스크립트와 실행 문서를 별도 PR로 검토한다.
