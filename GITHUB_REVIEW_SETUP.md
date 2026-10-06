# 팀장 리뷰와 main 보호 설정

2026-10-06 · 저장소 suuuhululu/C-2 · 팀장 GitHub 계정 @suuuhululu

## 1. 파일 적용

저장소 루트의 [CODEOWNERS](CODEOWNERS)를 main에 병합합니다.

```text
* @suuuhululu
```

모든 파일과 CODEOWNERS 자체의 리뷰 담당자를 수현으로 지정합니다. 이 파일만으로 승인 강제나 main 직접 push 차단이 설정되지는 않습니다. PR의 base branch에 파일이 있어야 적용되며 Draft는 Ready for review로 바뀔 때 자동 리뷰 요청이 발생합니다. 추후 .github/CODEOWNERS를 만들면 그 파일이 루트 파일보다 우선하므로 규칙을 따로 중복 관리하지 않습니다.

## 2. GitHub에서 별도 설정

Settings → Rules → Rulesets → New ruleset → New branch ruleset에서 아래를 설정합니다. 화면 명칭은 GitHub UI에 따라 다를 수 있습니다.

| 항목 | 설정 |
|---|---|
| Ruleset name | main-team-lead-review |
| Enforcement status | Active |
| Target branches | main만 지정 |
| Require a pull request before merging | 켜기 |
| Required approvals | 1 |
| Require review from Code Owners | 켜기 |
| Dismiss stale pull request approvals when new commits are pushed | 켜기 |
| Block force pushes | 켜기 |
| Restrict deletions | 켜기 |
| Bypass list | 기본은 비워두기 |

팀원이 PR 작성 → 수현 리뷰·Approve → main 병합 순서입니다. 팀원 한 명의 일반 승인만으로 팀장 승인을 대신할 수 없도록 Code Owner review를 함께 요구합니다. CI가 구성되지 않았다면 필수 status check를 임의 추가하지 않습니다.

## 3. 수현 본인이 작성한 PR

PR 작성자는 자신의 PR을 Approve할 수 없습니다. 유일한 Code Owner가 수현이면 수현 계정으로 작성한 PR은 위 승인을 충족하지 못합니다. AI가 수현 로그인으로 만든 PR도 동일합니다.

현재처럼 단일 팀장 승인 정책을 유지한다면, 팀원이 실제로 작성·제출하는 PR을 수현이 리뷰하는 방식으로 운영합니다. 수현 자신의 PR도 정상 리뷰로 병합하려면 별도 리뷰 담당자를 추가하는 정책을 팀에서 결정해야 합니다. 같은 줄에 두 소유자를 넣으면 어느 한 명의 승인으로 충족되며, 팀장 승인을 항상 강제하는 정책과 의미가 달라집니다.

Bypass는 승인 없이 병합 가능한 예외 권한이므로 이 안내를 이유로 자동 추가하지 않습니다. 본인 PR 예외가 필요하면 대상·허용 상황을 결정한 뒤 별도로 설정합니다.

## 4. 설정 확인

1. CODEOWNERS가 main에 존재하고 GitHub 파일 화면에 문법·사용자 오류가 없는지 확인합니다.
2. 다른 팀원 계정에서 main 대상 일반 PR을 열고 수현에게 리뷰 요청이 생기는지 확인합니다.
3. 수현 승인 전 병합이 차단되는지, 승인 후 병합이 가능한지 확인합니다.
4. 승인 후 변경 commit을 추가하면 기존 승인이 해제되는지 확인합니다.
5. main 직접 push·force push·삭제 차단은 실제 Ruleset 적용 화면에서 확인합니다. 검증을 위해 main 삭제나 강제 push를 실행하지 않습니다.

파일 게시, main 병합, Ruleset 활성화, 실제 팀원 PR 시험은 별도 상태입니다. 이 문서의 게시만으로 보호 설정 완료나 시험 통과를 주장하지 않습니다.

## 공식 근거

- [CODEOWNERS 위치·권한·base branch·필수 리뷰](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
- [Ruleset 규칙](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [PR 작성자의 본인 승인 제한](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews)
