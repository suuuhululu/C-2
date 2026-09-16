# 최초 초안 준비 상태

작성일: 2026-09-15. 구조 갱신: 2026-09-16. 이 문서는 최초 검토를 위한 시점 기록이며 이후 커밋·설정 변경 때 갱신한다.

## 파일과 Git

- 저장소: `https://github.com/suuuhululu/C-2.git`.
- 구성: 수업·미니 ros2_ws, 메인 ws_cobot_pjt. ROS 워크스페이스는 ros2_ws·ws_cobot1·ws_dsr 3곳, Git 저장소 1개.
- 게시 대상 브랜치: `docs/workspace-setup`. 빈 기준 커밋과 프로젝트 변경 커밋을 구분한다.
- 2026-09-16 사용자 요청으로 commit·push가 승인되었다. main 직접 push·규칙 우회·자동 병합은 하지 않는다.
- ROS 패키지·장비 연결·빌드는 아직 수행하지 않았다.

## 보호와 검사 상태

| 항목 | 현재 상태 |
| --- | --- |
| 로컬 main push 차단 hook | 이 clone에서 활성화. `core.hooksPath=.githooks` |
| GitHub main Ruleset | `main-pr-only` 생성·Active 저장 확인, ID `23389654` |
| 문서·구문·상대 링크 검사 | 통과 |
| hook 입력 시험 | 8개 통과. 원격 push나 테스트 커밋 없이 표준입력으로 검사 |
| GitHub Actions | 파일 초안만 작성, 원격 실행 미수행 |
| Issue 자동 배정·일정 승인 | 워크플로·양식·처리 코드 작성, 27개 로컬 동작 시험 통과. 원격 미실행 |
| 팀원 설정 | 4명 GitHub 계정 연결, 분야 general. 협업자 초대 수락·Write 권한은 미확인 |
| GitHub Projects·외부 일정 동기화 | 미구성. Issue 라벨·봇 댓글을 기준으로 운영하도록 준비 |
| 필수 CI 상태 검사 | 최초 원격 실행 후 추가 예정 |
| Codex 자동 PR 리뷰 | 미설정·연결 상태 미확인 |

### 저장한 서버 규칙

[main-pr-only 설정](https://github.com/suuuhululu/C-2/settings/rules/23389654)에서 2026-09-15 다음 값을 저장·확인했다.

- 이름 `main-pr-only`, Enforcement `Active`, 대상 `refs/heads/main`.
- PR 필수, 동료 승인 1명, 새 커밋 시 기존 승인 무효화, 검토 대화 해결 필수.
- 브랜치 삭제·강제 push 차단, 우회 대상 없음.
- 생성 제한·업데이트 전체 제한·Code Owners 승인·필수 상태 검사는 설정하지 않음.

GitHub 본인 확인 이후 `Ruleset created`와 Active 상태, 승인 수 1을 확인했다. 저장소가 아직 비어 있어 `Applies to 0 targets`로 표시된다. 규칙은 `main` 이름을 대상으로 저장되어 있지만, 최초 기준 커밋 생성과 그 이후 실제 PR·push 거절 시험은 아직 수행하지 않았다.

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

Issue 시험: 담당자 분배·한도·기존 배정 유지·실제 권한 필터, 팀장 승인·반려·과거 요청 거절, 한국 날짜 기준 임박·지연, 반복 실행·중복 댓글 방지·실패 후 복구, 외부 사용자 명령 차단, 실기 Issue 자동 종료 방지를 모의 GitHub 환경에서 확인했다. 실제 GitHub Issue를 생성·수정하거나 팀원에게 메시지를 보내지는 않았다.

GitHub 아이디는 팀장 확인과 공개 프로필 조회를 통해 suuuhululu, gimseeun, roh4195, sskywalker1209-prog로 반영했다. 전달받은 이메일은 저장소 파일에 넣지 않았다.

## 검토할 결정

- 강사 구조에 맞춘 ros2_ws·ws_cobot_pjt 구분과 메인의 ws_dsr·ws_cobot1 구성.
- 실제 팀원·검토자, 최소 승인 1명 운영.
- 미정인 그리퍼·제어기·ROS 실행 PC 정보.
- 빈 저장소 최초 기준 커밋의 내용과 초기화 절차.
- 최초 PR 이후 CI 필수 검사와 AI 리뷰를 활성화할 시점.
- 자동 배정 한도(열린 Issue 2개·진행 1개), 평일 18:40 점검, 팀장 승인 방식.

새 자동화는 [Issue 운영 문서](ISSUE_AUTOMATION.md), 팀장·팀원 역할은 [팀장 가이드](TEAM_LEAD_GUIDE.md)와 [팀원 시작 가이드](TEAM_ONBOARDING.md)를 검토한다. 이후 main 반영·협업자 권한 확인·연습 Issue를 통한 원격 검증을 완료해야 실제 운영 상태로 바꿀 수 있다.

초기화 제약과 일상 작업 순서는 [Git 가이드](GIT_GUIDE.md)를 확인한다.

## 2026-09-16 폴더 구조 변경

기존 실습·기획·검증 문서를 새 경로로 옮기고 메인에 backend/app·frontend/src/public·docker·DartPlatform·ws_cobot1/doc·ws_dsr/src를 준비했다. 설치물·생성 파일의 Git 제외 규칙과 경로 안내도 갱신했다. 강사 소스·Dart·웹 프레임워크 설치와 원격 반영은 하지 않았다. [환경·공유 안내](WORKSPACES.md)와 [외부 소스 기록](DEPENDENCIES.md)을 따른다.
