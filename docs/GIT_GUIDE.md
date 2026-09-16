# Git·PR 협업 가이드

## 기본 흐름

`Issue → 작업 브랜치 → 로컬 검사 → 커밋 검토 → 작업 브랜치 push → PR → 동료 승인 → main 병합`

PR 자체가 push를 대신하는 것은 아니다. 작업 브랜치는 원격에 push하고, `main`에 반영하는 단계는 GitHub PR로 진행한다. 2026-09-16 사용자가 최초 초안의 commit·push를 승인했다. main 직접 push나 보호 규칙 우회는 하지 않는다.

Issue 등록은 [작업 양식](../.github/ISSUE_TEMPLATE/task.yml)을 사용한다. 자동 배정·상태·마감 변경은 [Issue 자동화](ISSUE_AUTOMATION.md), 팀 운영은 [팀장 가이드](TEAM_LEAD_GUIDE.md)를 따른다. GitHub에 파일을 반영하기 전에는 봇이 동작하지 않는다.

## 최초 초기화와 사용 시작

2026-09-16 사용자 요청으로 빈 기준 커밋 `46e0d1b0abe78b663fc4f8541845ade64d84382f`에서 GitHub API로 `main`을 생성하고 기본 브랜치로 지정했다. 기존 `main-pr-only` 규칙은 유지했으며, main 보호가 적용됨을 확인했다. 프로젝트 파일은 `docs/workspace-setup`에 게시되어 있다.

팀원 `gimseeun`, `roh4195`, `sskywalker1209-prog` 모두 초대를 수락했고 Write 권한을 확인했다. 초기화를 다시 하거나 작업 브랜치 이름을 main으로 바꾸지 않는다.

[첫 PR #1](https://github.com/suuuhululu/C-2/pull/1)의 동료 승인과 병합이 완료된 뒤 아래 일상 작업 순서를 사용한다. 필수 검사와 Issue 자동화 검증 여부는 [준비 상태](REVIEW_STATUS.md)를 확인한다. 승인 전의 빈 main에는 아직 프로젝트 파일이 없는 것이 정상이다.

로컬 hook은 최초 main 생성 push도 차단한다. 이후에는 main 직접 push 없이 작업 브랜치와 PR을 사용하며, hook이나 서버 규칙을 우회하지 않는다.

## 각 팀원 clone의 로컬 보호

초안 병합 이후 clone한 팀원은 저장소 루트에서 실행한다.

```sh
sh tools/setup-git-hooks.sh
git config --local --get core.hooksPath
python3 tools/test_git_hooks.py
```

기대 설정은 `.githooks`다. 설치 도구는 이 clone의 설정만 바꾸고 기존 다른 hook 설정이 있으면 덮어쓰지 않는다.

`pre-push`는 목적지가 `refs/heads/main`이면 차단한다. 현재 브랜치와 관계없이 `HEAD:main`, 다른 브랜치에서 main으로 보내기, main 삭제, 여러 참조 중 main이 포함된 push도 대상이다.

로컬 hook은 설치한 clone에만 적용되고 사용자가 우회할 수 있으므로 팀 전체의 강제 보호는 GitHub Ruleset이 담당한다. 새 clone에는 자동 설치되지 않는다.

## 일상 작업 명령

다음은 원격 `main`의 초기화가 완료된 후 사용하는 예시다. Issue 번호·브랜치·파일 경로는 실제 작업에 맞춘다.

```sh
git status --short --branch
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c feat/23-mini-gripper-feedback

# 파일을 수정한 다음
python3 tools/check_repository.py
python3 tools/test_git_hooks.py
git diff --check
git diff
git status --short
```

새 파일은 일반 `git diff`에 표시되지 않으므로 파일을 직접 열어 검토한다. 검토가 끝나면 의도한 파일만 `git add`하고 `git diff --cached`로 커밋 대상도 확인한다. 사용자 검토 전에는 이 단계를 자동으로 수행하지 않는다.

```sh
# 아래는 검토·커밋 승인이 끝난 이후에만 실행하는 예시
git add ros2_ws/README.md
git diff --cached
git commit -m "docs(mini): 실습 실행 절차 정리"
git push -u origin feat/23-mini-gripper-feedback
```

GitHub에서 base를 `main`, compare를 작업 브랜치로 선택해 PR을 만든다. 작성 중이면 Draft로 두고 검토 준비가 끝나면 동료에게 리뷰를 요청한다.

## 브랜치와 변경 단위

- 예: `feat/23-mini-gripper-feedback`, `fix/41-main-timeout`, `docs/52-experiment-report`.
- 1 PR에는 한 목적의 변경만 담는다. 로봇·그리퍼·화면을 모두 바꾸는 큰 변경은 연결 규칙을 먼저 합의한다.
- 다른 사람의 브랜치 이력을 덮어쓰거나 `main`에 직접 push하지 않는다.
- 충돌 시 관련 담당자와 의도·기준 버전을 확인하고 해결 후 다시 검사한다.
- 삭제·초기화로 충돌을 숨기지 않는다. 커밋 수로 개인 기여도를 평가하지 않는다.

## GitHub의 main 보호

저장소는 개인 계정 `suuuhululu` 소유의 공개 저장소로 확인했다. 조직 저장소의 세부 역할 구성을 현재 이미 적용한 것으로 취급하지 않는다.

목표 규칙 `main-pr-only`:

- 적용 상태 Active, 대상 이름 `main`.
- PR을 통한 변경 필수, 승인 1명 이상.
- 새 커밋으로 변경되면 기존 승인 무효화.
- 검토 대화 해결 필수.
- main 삭제와 강제 push 차단.
- 우회 대상 없음.

`Restrict updates`는 PR 병합까지 막을 수 있으므로 직접 push 차단을 위해 이 옵션만 켜지 않는다. PR 필수 규칙으로 운영한다. `Restrict creations`는 초기화와 관계되므로 현재 설정과 제한을 [준비 상태](REVIEW_STATUS.md)에 구분해 기록한다.

GitHub 관리자는 규칙 자체를 수정할 권한이 있다. "우회 대상 없음"이 관리자 설정 변경까지 불가능하다는 뜻은 아니다.

현재 적용·검증 상태와 설정 주소는 [준비 상태](REVIEW_STATUS.md)를 따른다. 규칙 파일을 저장소에 넣는 것만으로 GitHub 설정이 적용되지는 않는다.

## 리뷰와 자동 검사

- 작성자 외 Write 권한을 가진 동료 최소 1명이 검토한다. 본인 PR을 본인이 승인하는 방식으로 대체하지 않는다.
- [PR 양식](../.github/PULL_REQUEST_TEMPLATE.md)에 변경 이유·실행한 검사·미검증 범위·실기 증거를 적는다.
- `repository-checks`는 문서 링크·텍스트·Python 구문·hook 동작 검사다. 아직 ROS 패키지가 없으므로 ROS 빌드와 실기 성공을 보고하지 않는다.
- GitHub에서 `repository-checks` 실행 성공을 확인했다. 필수 검사 적용과 최신 PR 실행 결과는 [준비 상태](REVIEW_STATUS.md) 및 해당 PR의 Checks에서 확인한다.
- 코드 검토 통과와 실기 완료를 다른 Issue로 관리한다. 병합 후 자동으로 실기 완료 처리하지 않는다.

팀원 계정은 team.json에 등록되어 있다. 담당 분야가 확정되면 `CODEOWNERS`를 추가해 경로별 동료 검토자를 연결한다. 현재 역할은 미정이므로 CODEOWNERS와 해당 승인은 설정하지 않았다.

## AI 사용

공통 기준은 루트 [AGENTS.md](../AGENTS.md)를 사용한다. 리뷰를 요청할 때 관련 Issue·변경 목적·미검증 환경을 함께 제공한다.

Codex GitHub 리뷰는 대상 저장소의 Codex cloud 연결과 Code review 설정이 필요하다. 준비된 뒤 PR에서 `@codex review`로 요청하고, 자동 리뷰는 팀 계정 연결·사용량·적용 범위를 확인한 후 켠다. 현재 이 저장소의 AI 연결 상태는 확인하거나 변경하지 않았다.

AI는 PR 요약·오류 후보·수정안을 만들 수 있지만, 팀원 승인과 실제 시험을 대신하지 않는다. 검토 후 코드가 바뀌면 다시 검사·승인받는다.

## 근거

- [Git pre-push 문서](https://git-scm.com/docs/githooks#_pre_push)
- [Git core.hooksPath](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corehooksPath)
- [GitHub Rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
- [GitHub PR·승인·검사 규칙](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [Codex GitHub 리뷰](https://learn.chatgpt.com/docs/third-party/github)
