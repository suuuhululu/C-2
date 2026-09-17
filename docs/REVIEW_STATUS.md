# 진행 현황과 남은 작업

확인일: 2026-09-17 (한국 시간). GitHub의 PR·Issue·Actions·main 보호 규칙과 현재 로컬 작업을 대조한 기록이다. 문서는 자동 동기화되지 않으므로 후속 작업 때 실제 상태를 다시 확인한다.

## GitHub에 반영된 작업

| 항목 | 확인한 결과 | 근거 |
| --- | --- | --- |
| 초기 폴더·협업·자동화 구성 | 9/16 `gimseeun` 승인 후 PR #1 병합 | [PR #1](https://github.com/suuuhululu/C-2/pull/1) |
| 외부 로봇 실행환경 Git 제외 | 9/16 `sskywalker1209-prog` 승인 후 PR #3 병합. `ws_dsr/src/` 전체 제외, 자리표시자 추적 해제, 출처·환경 기록 반영 | [PR #3](https://github.com/suuuhululu/C-2/pull/3) |
| 관련 Issue | #2 닫힘, 봇 운영 현황과 라벨 모두 `done` | [Issue #2](https://github.com/suuuhululu/C-2/issues/2) |
| 기본 브랜치 | `main`, 확인한 커밋 `fbc24045d9e8e9de0c4c0384fc3867c03aba524c` | [main 확인 커밋](https://github.com/suuuhululu/C-2/commit/fbc24045d9e8e9de0c4c0384fc3867c03aba524c) |
| 원격 작업 목록 | 조회 시 열린 PR 0개, 열린 Issue 0개. 프로젝트 구현 완료를 뜻하지 않음 | [PR 목록](https://github.com/suuuhululu/C-2/pulls), [Issue 목록](https://github.com/suuuhululu/C-2/issues) |

main에는 이미 초기 파일과 외부 소스 제외 변경이 있다. 저장소 초기화나 첫 PR 병합을 다시 할 필요는 없다.

## 로컬에만 준비된 변경

현재 브랜치는 `chore/remove-mini-workspace`이며 위 main 커밋에서 시작했다. 아래 변경은 **커밋·push·PR 전의 검토용 작업**이다.

- 사용자 요청으로 연습용 워크스페이스와 전용 실습 문서·빈 폴더를 삭제했다.
- 메인 프로젝트 `ws_cobot_pjt`와 공통 운영 문서를 중심으로 경로·안내를 정리했다.
- Issue/PR 양식과 처리 코드의 프로젝트 분류를 `main`·`common`으로 정리했다.
- 현재 진행 상황에 맞게 완료·확인 대기·로컬 변경을 문서에 구분했다.

따라서 현재 로컬 구조와 원격 main의 구조·양식은 일부 다르다. 팀원에게 일괄 삭제를 요청하기 전에 이 변경을 검토·커밋하고 작업 브랜치 push → PR → 동료 승인 → main 병합으로 공유한다. 원격 CI 성공 기록을 이 미게시 변경의 검사 결과로 사용하지 않는다.

## 보호와 자동 검사

- 9/17 재확인: main의 `protected` 상태와 `main-pr-only` 규칙이 활성 상태다. [서버 규칙](https://github.com/suuuhululu/C-2/rules/23389654).
- PR 필수, 승인 최소 1명, 새 커밋 시 이전 승인 무효화, 검토 대화 해결, main 삭제·강제 push 차단이 설정되어 있다.
- 필수 검사 `repository-checks`는 GitHub Actions 출처(ID 15368)와 최신 main 반영을 요구한다. 우회 대상 없음은 9/16 인증 조회에서 확인한 기록이며, 이번 공개 조회에서는 우회 목록을 재확인하지 않았다.
- 이 clone의 `core.hooksPath=.githooks`를 확인했다. 다른 팀원은 각 clone에서 [hook 설치](GIT_GUIDE.md)를 해야 한다.
- PR #3 최종 커밋 `09f2be641ab838f06a9ba0e2025b93f754b8f184`의 [push 검사](https://github.com/suuuhululu/C-2/actions/runs/35049166460)와 [PR 검사](https://github.com/suuuhululu/C-2/actions/runs/35049169231)가 성공했다.
- 현재 로컬 검사: 문서·Python 구문·상대 링크 30개 파일, Git hook 시험 8개, Issue 자동화 시험 27개, 팀 설정 형식·셸 구문·공백 검사 통과. 네트워크·로봇에 연결하지 않는 검사다.

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
- C-2에는 팀 ROS 패키지·서버·화면 구현이 아직 없고 기획·검증 양식이 준비되어 있다. 서비스 주제·공작물·성공 기준·역할은 [프로젝트 계획](../ws_cobot_pjt/docs/PROJECT_PLAN.md)에서 확정해야 한다.
- 실제 그리퍼·제어기·배선과 실기 동작은 확인 대기다. 가상 이동과 PR 병합을 실제 파지·공정 완료로 표현하지 않는다.
- GitHub Projects·외부 캘린더 동기화와 AI 자동 PR 리뷰는 이 작업에서 구성한 기록이 없다. 연결 상태는 별도 확인이 필요하며, 현재 자동화의 기준은 Issue 라벨과 봇 댓글이다.

## 다음에 할 일

1. 로컬 폴더 정리와 문서 변경을 검토하고 별도 PR로 공유한다.
2. 팀원이 연습용 Issue로 미배정 자동 분배 → 시작 → 일정 요청·승인 → 검토 → 종료를 확인하고 실제 결과를 기록한다.
3. 프로젝트 주제·최소 시연 기능·성공 기준과 담당자·검토자를 정하고 구현 Issue를 만든다.
4. 공용 MSI의 실제 소스 버전과 수정 여부를 기록한다. 동작 중인 설치를 이번 문서 정리 때문에 재설치하지 않는다.
5. 제안된 `setup_host.sh`와 `setup_and_run.md`는 아직 C-2에 없다. 팀원이 제공하면 설치 스크립트와 실행 문서를 별도 PR로 검토한다.
