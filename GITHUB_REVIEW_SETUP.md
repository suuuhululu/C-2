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
| Bypass list | 수현에게만 적용되는 대상 선택, For pull requests only |

팀원이 PR 작성 → 수현 리뷰·Approve → main 병합 순서입니다. 팀원 한 명의 일반 승인만으로 팀장 승인을 대신할 수 없도록 Code Owner review를 함께 요구합니다. CI가 구성되지 않았다면 필수 status check를 임의 추가하지 않습니다.

## 3. 수현 본인이 작성한 PR

PR 작성자는 자신의 PR을 Approve할 수 없습니다. 유일한 Code Owner가 수현이면 수현 계정으로 작성한 PR은 위 승인을 충족하지 못합니다. AI가 수현 로그인으로 만든 PR도 동일합니다.

확정 운영은 다음과 같습니다.

- 팀원 PR: 수현의 Code Owner Approve 후 병합합니다. 팀원 PR에는 승인 우회를 사용하지 않습니다.
- 수현 본인 PR: 수현이 변경 내용·검증 결과를 직접 확인한 뒤 PR을 통해 bypass 병합합니다. 자기 Approve가 아니라 승인 요건의 예외 병합입니다.
- AI가 수현 계정으로 작성한 PR: 같은 본인 PR 정책을 적용하지만, AI 검증이 수현의 사람 리뷰를 대신하지 않습니다. AI가 자동 승인하거나 자동 병합하지 않습니다.

설정은 Bypass list → Add bypass에서 수현에게만 적용되는 대상을 선택하고, 모드를 Always allow 대신 **For pull requests only**로 지정합니다. 일반적인 저장소 Ruleset UI는 역할·팀·앱을 대상으로 제공합니다. 이 개인 저장소에서 Repository admin 역할을 선택한다면 수현만 해당하는지 실제 권한 목록을 확인합니다. 다른 관리자도 있으면 그 관리자에게도 bypass가 적용되므로 수현 개인 전용 설정으로 표시하지 않습니다. Write/Maintain 역할 전체에 bypass를 부여하지 않습니다.

For pull requests only는 PR을 통한 예외 병합을 허용하며 직접 push를 허용하기 위한 설정이 아닙니다. GitHub가 '작성자가 수현인 PR만' 자동 제한하는 것은 아니므로 **본인 PR에만 사용**하는 규칙은 수현의 운영 책임입니다. PR에 변경·검증 결과와 본인 검토 후 bypass 병합한 사유를 남깁니다.

CODEOWNERS는 `* @suuuhululu`를 유지합니다. 다른 소유자를 추가해 일반 승인을 대체할 필요는 없습니다. 이 문서 수정은 운영 정책 기록이며 실제 Bypass 권한 설정·Ruleset 변경·PR 병합을 수행한 것은 아닙니다.

## 4. 설정 확인

1. CODEOWNERS가 main에 존재하고 GitHub 파일 화면에 문법·사용자 오류가 없는지 확인합니다.
2. 다른 팀원 계정에서 main 대상 일반 PR을 열고 수현에게 리뷰 요청이 생기는지 확인합니다.
3. 수현 승인 전 병합이 차단되는지, 승인 후 병합이 가능한지 확인합니다.
4. 승인 후 변경 commit을 추가하면 기존 승인이 해제되는지 확인합니다.
5. 수현 본인 PR에서 사람 검토 후 PR-only bypass 병합이 가능한지 확인하고, 팀원 PR에는 우회를 사용하지 않습니다. Bypass 대상 역할이 다른 팀원까지 포함하지 않는지 확인합니다.
6. main 직접 push·force push·삭제 차단은 실제 Ruleset 적용 화면에서 확인합니다. 검증을 위해 main 삭제나 강제 push를 실행하지 않습니다.

파일 게시, main 병합, Ruleset 활성화, 실제 팀원 PR 시험은 별도 상태입니다. 이 문서의 게시만으로 보호 설정 완료나 시험 통과를 주장하지 않습니다.

## 공식 근거

- [CODEOWNERS 위치·권한·base branch·필수 리뷰](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
- [Ruleset 규칙](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [PR 작성자의 본인 승인 제한](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews)

- [Ruleset bypass 대상과 For pull requests only](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)
