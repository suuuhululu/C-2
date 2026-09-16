# 최초 설정 진행 상태

작성일: 2026-09-15. 원격 설정 확인: 2026-09-16. 이 문서는 확인 시점의 기록이며 GitHub와 자동 동기화되지 않는다. 이후 작업 전 실제 PR·Actions·권한 상태도 확인한다.

## 파일과 Git

- 저장소: `https://github.com/suuuhululu/C-2.git`.
- 구성: 수업·미니 ros2_ws, 메인 ws_cobot_pjt. ROS 워크스페이스는 ros2_ws·ws_cobot1·ws_dsr 3곳, Git 저장소 1개.
- 기본 브랜치: `main`. 빈 기준 커밋 `46e0d1b0abe78b663fc4f8541845ade64d84382f`에서 생성했다.
- 작업 브랜치: `docs/workspace-setup`. 초기 구성 `0c125252fee97c721ee7c653337985295a8b5695`를 게시했다.
- [첫 PR #1](https://github.com/suuuhululu/C-2/pull/1): 작업 브랜치에서 main으로 반영 요청. `gimseeun`에게 동료 검토를 요청했으며 아직 승인·병합 전이다. 병합 전 main에 프로젝트 파일이 없는 것은 정상이다.
- 2026-09-16 사용자 요청으로 commit·push가 승인되었다. main 직접 push·규칙 우회·자동 병합은 하지 않는다.
- ROS 패키지·장비 연결·빌드는 아직 수행하지 않았다.

## 보호와 검사 상태

| 항목 | 현재 상태 |
| --- | --- |
| 로컬 main push 차단 hook | 이 clone에서 활성화. `core.hooksPath=.githooks` |
| GitHub main Ruleset | `main-pr-only` 생성·Active 저장 확인, ID `23389654` |
| 문서·구문·상대 링크 검사 | 통과 |
| hook 입력 시험 | 8개 통과. 원격 push나 테스트 커밋 없이 표준입력으로 검사 |
| GitHub Actions | 초기 구성의 [push 검사](https://github.com/suuuhululu/C-2/actions/runs/35043094825)와 [PR 검사](https://github.com/suuuhululu/C-2/actions/runs/35045950773) 성공. 이후 문서 갱신 커밋의 최신 검사는 PR Checks에서 확인 |
| Issue 자동 배정·일정 승인 | 워크플로·양식·처리 코드 작성, 27개 로컬 동작 시험 통과. 원격 미실행 |
| 팀원 설정 | 4명 연결, 분야 general. 팀장 Admin, 나머지 3명 초대 수락·Write 권한 확인. 대기 중 초대 없음 |
| GitHub Projects·외부 일정 동기화 | 미구성. Issue 라벨·봇 댓글을 기준으로 운영하도록 준비 |
| 필수 CI 상태 검사 | `repository-checks` 적용 완료. GitHub Actions가 보고한 검사만 인정하고 최신 main 반영 요구 |
| Codex 자동 PR 리뷰 | 미설정·연결 상태 미확인 |

### 저장한 서버 규칙

[main-pr-only 설정](https://github.com/suuuhululu/C-2/settings/rules/23389654)에서 2026-09-15 다음 값을 저장·확인했다.

- 이름 `main-pr-only`, Enforcement `Active`, 대상 `refs/heads/main`.
- PR 필수, 동료 승인 1명, 새 커밋 시 기존 승인 무효화, 검토 대화 해결 필수.
- 브랜치 삭제·강제 push 차단, 우회 대상 없음.
- 생성 제한·업데이트 전체 제한·Code Owners 승인은 설정하지 않음.
- 2026-09-16 필수 상태 검사 `repository-checks` 추가. 출처는 GitHub Actions 앱(ID 15368), 최신 main 반영 요구. 기존 PR 승인·삭제·강제 push 차단 규칙은 모두 유지.

2026-09-16 사용자 요청으로 기준 커밋에서 GitHub API를 통해 main을 생성하고 기본 브랜치를 지정했다. 로컬 hook이나 서버 규칙을 변경·우회하지 않았다. main의 protected 상태와 기존 규칙 유지, 우회 대상 없음, 동료 승인 수 1을 다시 확인했다. 실제 main push를 시도하는 시험은 수행하지 않았다.

이 문서와 서버 설정은 자동 동기화되지 않는다. 설정을 변경하면 상태 기록도 갱신한다. 로컬 hook은 이 clone의 push를 추가로 막으며 다른 팀원은 각 clone에서 설치해야 한다.

### 수행한 검사

```sh
python3 tools/check_repository.py
python3 tools/test_git_hooks.py
python3 tools/issue_manager.py
python3 tools/test_issue_manager.py
sh -n .githooks/pre-push
sh -n tools/setup-git-hooks.sh
```

hook 시험: main 갱신·다른 출발점에서 main 갱신·최초 main 생성·main 삭제·여러 참조 중 main 포함을 차단하고, 작업 브랜치·동명의 태그·변경 없음은 허용한다. 이 결과는 로컬 hook의 동작 확인이며 GitHub의 실제 push 거절 시험은 아니다.

Issue 시험: 담당자 분배·한도·기존 배정 유지·실제 권한 필터, 팀장 승인·반려·과거 요청 거절, 한국 날짜 기준 임박·지연, 반복 실행·중복 댓글 방지·실패 후 복구, 외부 사용자 명령 차단, 실기 Issue 자동 종료 방지를 모의 GitHub 환경에서 확인했다. 실제 GitHub Issue 생성·변경 시험은 첫 PR 병합 후 진행해야 한다.

GitHub 계정 suuuhululu, gimseeun, roh4195, sskywalker1209-prog의 저장소 권한을 인증된 API로 확인했다. 전달받은 이메일과 토큰은 저장소 파일에 넣지 않았다.

## 검토할 결정

- 강사 구조에 맞춘 ros2_ws·ws_cobot_pjt 구분과 메인의 ws_dsr·ws_cobot1 구성.
- 실제 팀원·검토자, 최소 승인 1명 운영.
- 미정인 그리퍼·제어기와 실행 PC의 설치 버전. 사용자는 공용 MSI Ubuntu에서 별도 설치 중이라고 확인했으며, 해당 PC의 설치·구동 상태는 이 작업에서 검증하지 않았다.
- 첫 PR의 동료 승인과 병합, 이후 연습 Issue 원격 검증.
- 별도 AI 자동 리뷰 연결 여부와 활성화할 시점.
- 자동 배정 한도(열린 Issue 2개·진행 1개), 평일 18:40 점검, 팀장 승인 방식.

새 자동화는 [Issue 운영 문서](ISSUE_AUTOMATION.md), 팀장·팀원 역할은 [팀장 가이드](TEAM_LEAD_GUIDE.md)와 [팀원 시작 가이드](TEAM_ONBOARDING.md)를 검토한다. 협업자 권한 확인은 끝났으며, 동료 승인·main 병합·연습 Issue 원격 검증이 남아 있다. 승인 조건을 없애거나 AI가 동료 대신 승인하지 않는다.

초기화 제약과 일상 작업 순서는 [Git 가이드](GIT_GUIDE.md)를 확인한다.

## 2026-09-16 폴더 구조 변경

기존 실습·기획·검증 문서를 새 경로로 옮기고 메인에 backend/app·frontend/src/public·docker·DartPlatform·ws_cobot1/doc·ws_dsr/src를 준비했다. 설치물·생성 파일의 Git 제외 규칙과 경로 안내도 갱신하고 작업 브랜치에 게시했다. 이 GitHub 초기 구성 작업에는 강사 소스·Dart·웹 프레임워크 설치가 포함되지 않는다. [환경·공유 안내](WORKSPACES.md)와 [외부 소스 기록](DEPENDENCIES.md)을 따른다.
