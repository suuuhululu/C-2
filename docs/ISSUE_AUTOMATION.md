# Issue 자동 배정·일정 운영

2026-09-17 확인: 초기 구성 PR #1은 병합됐고 **Issue management가 main에서 실제 실행 중**이다. [Issue #2](https://github.com/suuuhululu/C-2/issues/2)에서 분류·최초 마감·임박 안내, 검토 상태와 종료 반영을 확인했다. 미배정 자동 분배와 일정 승인 전체 과정은 아직 원격 연습이 필요하다. 근거와 남은 범위는 [진행 현황](REVIEW_STATUS.md)에 기록한다.

현재 양식명과 프로젝트 분류의 정리는 로컬 변경이며 main에 병합된 뒤 적용된다. 작업 브랜치가 기본 브랜치로 지정되더라도 main이 아니면 자동화는 실행을 건너뛴다.

## 자동으로 처리하는 일

| 상황 | 자동 처리 | 사람이 정할 것 |
| --- | --- | --- |
| 팀원이 작업 양식으로 Issue 등록 | 프로젝트·분야·유형 라벨, 최초 마감 기록, 미배정 작업 분배 | 목표·완료 조건·예상 시간·동료 검토자 |
| 역할 미정 | `general` 작업을 열린 Issue 수가 적은 등록 팀원에게 배정 | 작업 범위가 본인에게 적절한지 확인 |
| 역할 확정 | 해당 분야를 설정에 등록한 팀원 중 배정 | 역할표를 PR로 수정 |
| 담당자 댓글 명령 | 시작·검토·대기·막힘 상태 변경 | 결과·증거·막힌 이유 기록 |
| 마감 변경 요청 | 요청 번호와 승인 방법 안내, 변경 대기 라벨 | 팀장이 영향 확인 후 승인·반려 |
| 마감 변경 승인 | 확정 날짜 갱신, 이전 날짜·이유·승인자 기록, 일정 라벨 재계산 | 선행 작업·장비 예약·다른 작업 일정 조정 |
| 마감 임박·지연 | 라벨과 중복되지 않는 안내 댓글 | 범위 축소·지원·재배정·일정 변경 판단 |
| Issue 닫기·재열기 | 완료·대기 상태로 맞춤 | 실제 완료 조건 충족 여부 판단 |

다른 Issue의 마감, 마일스톤, Notion·개인 캘린더, GitHub Projects의 사용자 정의 날짜는 자동 변경하지 않는다. PR 리뷰 요청·병합과 실기 성공 판정도 이 자동화의 범위에 포함되지 않는다.

## 팀 설정과 배정 규칙

설정 원본은 [team.json](../.github/team.json)이다. 이메일은 기록하지 않았다.

| 이름 | GitHub 아이디 | 역할 | 배정 설정 |
| --- | --- | --- | --- |
| 이수현 | suuuhululu | 팀장, 분야 미정 | general |
| 김세은 | gimseeun | 분야 미정 | general |
| 노홍동 | roh4195 | 분야 미정 | general |
| 이시율 | sskywalker1209-prog | 분야 미정 | general |

2026-09-16 저장소에서 팀장 Admin, 나머지 세 계정의 초대 수락·Write 권한을 확인했다. 자동화는 실행할 때 실제 권한과 배정 가능 여부를 다시 조회한다.

- `active: true`, 유효한 GitHub 아이디, 저장소 Write 이상 권한, GitHub에서 배정 가능한 계정만 후보로 쓴다.
- `general`에는 활성 팀원 전체가 후보가 된다. 다른 분야는 `roles`에 그 분야가 있는 사람만 후보가 된다. 현재는 모두 미정이므로 **general을 선택한다.**
- 열린 Issue 수가 가장 적은 사람을 선택한다. PR은 세지 않으며, 자동화 밖의 열린 Issue도 작업량에 포함한다. 동률이면 아이디순으로 정한다.
- 기본 자동 배정 한도는 사람당 열린 Issue 2개다. 예상 시간·난이도는 계산하지 않으므로 팀장이 하루 계획에 맞게 조정한다. 한도에 다다르면 `assignment:needed`로 남긴다.
- 이미 담당자가 있으면 바꾸지 않는다. 담당자는 GitHub의 Assignees에서 팀장이 조정할 수 있다. 담당자를 모두 제거하면 다음 실행에서 다시 자동 배정된다.
- 휴가·불참은 `active: false`로 바꾸어 새 배정을 멈춘다. 기존 담당 작업은 유지되므로 팀장이 따로 인수인계를 정한다.
- 설정·분야를 바꾸어도 기존 배정을 자동으로 뒤집지 않는다. 본문의 프로젝트·분야·유형 변경은 라벨에 반영하지만 확정 마감은 승인 절차를 따른다.
- 진행 중(`doing`)은 사람당 1개를 기본으로 한다. `/team start` 실행 시 같은 담당자의 다른 진행 중 Issue가 있으면 거절한다. 팀원이 수동으로 라벨을 바꾸어 이 제한을 우회하지 않도록 합의한다.

## 팀원 사용법

1. GitHub Issues → New issue → **작업 · 검증** 양식을 선택한다.
2. 프로젝트는 `main`(프로젝트 기능) 또는 `common`(공통 환경·협업)으로 선택하고 분야, 최초 마감, 완료 조건을 작성한다. 날짜는 `YYYY-MM-DD`다.
3. 봇의 **팀 작업 운영 현황** 댓글에서 실제 담당자와 확정 마감을 확인한다.
4. 본인이 담당자로 배정되면 다음 댓글을 필요할 때 작성한다.

```text
/team start
/team review
/team todo
/team block 장비 예약이 겹쳐 오늘 시험할 수 없습니다. 대체 시간 확인이 필요합니다.
/team request-date 2026-09-23 장비 예약이 변경되어 검증 시간이 추가로 필요합니다.
```

명령은 댓글 첫 글자부터 작성한다. 코드 블록·인용 안에 넣지 않는다. `/team start`, `/team review`, `/team todo`는 명령만 적은 별도 댓글로 보내고 설명·PR 링크는 다른 댓글에 남긴다. Issue #2에서 설명을 붙인 상태 명령이 거절되고 단독 명령이 처리된 것을 확인했다. 명령 댓글을 수정해 재사용하지 말고 새 댓글을 작성한다. 날짜 명령은 한 줄로 작성한다. 예시 날짜는 실제 작업에 맞게 변경한다.

일정 요청은 최신 1개만 승인 대기 상태로 유지한다. 새 요청을 내면 이전 미승인 요청은 대체되며 과거 댓글은 기록으로 남는다. 봇이 안내한 요청 번호는 **Issue 번호와 다르다.**

팀장 또는 저장소 관리자가 다음과 같이 승인·반려한다.

```text
/team approve-date 123456789
/team reject-date 123456789 시연 일정과 충돌하므로 작업 범위를 먼저 줄이세요.
```

요청자가 승인 권한을 가진 팀장이면 본인의 요청도 승인할 수 있다. 일반 팀원은 자신의 일정 요청을 승인할 수 없다. 작업 상태·일정 요청 명령은 현재 담당자 또는 팀장·관리자에게만 허용한다.

## 날짜와 완료의 기준

- 확정 날짜의 원본은 봇이 작성한 운영 현황 댓글이다. Issue 본문의 **최초 마감일**은 최초 등록 기록이므로 이후 수정해도 확정 날짜가 바뀌지 않는다.
- 날짜는 한국 시간(Asia/Seoul) 기준으로 해당 날짜 종료까지다. 당일과 하루 전에는 `schedule:due-soon`, 지난 날짜에는 `schedule:overdue`를 붙인다.
- 최초 날짜가 잘못되었으면 `schedule:missing`으로 표시한다. 담당자 또는 팀장이 날짜 변경을 요청하고 팀장이 승인하여 채운다.
- 변경 요청·승인 시 과거 날짜를 거절한다. 연결된 마일스톤의 마감일이 있으면 그 이후 날짜도 거절한다. 승인 대기 중 마일스톤이 바뀌면 승인 시 다시 검사한다.
- 마일스톤을 앞당겨 기존 마감과 충돌하면 `schedule:milestone-conflict`로 표시한다. 다른 Issue의 날짜를 자동으로 당기지 않는다.
- 마일스톤의 하루 단위 비교는 발표 자료 업로드 11시·시연 14시 같은 시각을 대신하지 않는다. 해당 시각과 준비 여유는 Issue 완료 조건에 명시한다.
- 지연 표시만으로 Issue를 닫거나 마감을 연장하지 않는다. 실기 검증은 구현 PR과 별도 Issue이며 실제 결과 확인 후 사람이 닫는다.

## 실행·알림과 보드

실행 파일은 [워크플로](../.github/workflows/issue-management.yml)와 [처리 코드](../tools/issue_manager.py)다. Issue 변경, 새 `/team` 댓글, 마일스톤 수정, 수동 실행 때 동작한다. 평일 **18:40 KST**에도 점검한다. GitHub 사정에 따라 예약 실행이 지연될 수 있으며, 정확한 시각의 장비 예약 알람으로 사용하지 않는다.

매 실행은 현재 Issue와 아직 처리하지 않은 명령 댓글을 다시 읽는다. 같은 자동화끼리는 동시에 실행하지 않는다. 대기 실행이 새 이벤트로 대체되어도 다음 전체 점검이 누락된 작업을 처리한다. 실패한 실행은 Actions에서 원인을 확인한 뒤 재실행한다.

같은 날짜·같은 종류의 일정 알림은 한 번만 작성한다. 명령별 처리 결과도 한 번만 기록한다. 변화가 없으면 댓글을 반복 생성하지 않는다. GitHub 알림 전달은 팀원의 구독·이메일 설정에 따르며 외부 메일·Slack 메시지는 보내지 않는다.

현재 상태의 원본은 `status:todo / doing / review / blocked / done` 라벨이다. 이 작업에서 Projects 보드 연동을 구성한 기록은 없으며 이 코드가 보드의 Status·날짜 필드를 바꾸지는 않는다. 다음 Issue 검색을 북마크해 운영할 수 있다.

```text
is:issue is:open assignee:@me
is:issue is:open label:assignment:needed
is:issue is:open label:schedule:change-requested
is:issue is:open label:schedule:overdue
is:issue is:open label:status:blocked
is:issue is:open label:status:review
```

## 완료한 설정과 남은 연습

1. 완료: main 생성·기본 브랜치 지정, 9/16 팀원 권한 확인, PR #1 병합과 워크플로 활성화.
2. 완료: #2에서 봇 댓글·라벨·마감 기록, 단독 `/team review`, Issue 종료 후 `done` 반영. #2의 담당자는 사전에 지정돼 있었으므로 자동 분배 검증으로 세지 않는다.
3. 완료: Issue·댓글 이벤트와 [예약 실행](https://github.com/suuuhululu/C-2/actions/runs/35107869058) 성공. 초기화 목적의 수동 실행을 다시 할 필요는 없다.
4. 남은 연습: 미배정 Issue 하나로 자동 배정 → 시작 → 날짜 변경 요청 → 팀장 승인·반려 → 검토 → 종료를 확인한다. 실제 결과를 [진행 현황](REVIEW_STATUS.md)에 기록한다.
5. 운영: 팀장은 처음 며칠 실행 결과·배정량을 확인하고, 필요할 때 Actions의 **Issue management → Run workflow → main**으로 다시 점검한다.

워크플로는 기본 브랜치에 있어야 Issue·댓글·예약 이벤트로 실행된다. 별도 개인 토큰이나 AI API 키는 필요하지 않고, GitHub가 제공하는 `GITHUB_TOKEN`에 `contents: read`, `issues: write`만 요청한다. 저장소·조직 정책에서 Actions 사용이 허용되어 있어야 한다. PR의 소스를 쓰기 권한으로 실행하지 않고 기본 브랜치의 코드만 사용한다.

## 중지와 문제 해결

| 증상 | 팀장 확인·조치 |
| --- | --- |
| 아무 반응 없음 | main에 파일이 있는지, Actions가 활성인지, 실행 실패가 있는지 확인 |
| 배정 대기 | 초대 수락·Write 권한, active, 역할, 열린 Issue 2개 한도를 확인 |
| 기존 Issue가 자동화되지 않음 | 팀 협업자가 작성했는지, 새 양식의 프로젝트·분야·유형 항목이 있는지 확인 |
| 날짜 수정이 반영되지 않음 | 최초 마감 본문 수정 대신 요청·승인 명령 사용 |
| 명령 거절 | 현재 담당자인지, 요청 번호가 최신인지, 팀장 권한·마일스톤·날짜를 확인 |
| 날짜 알림 중복 우려 | 운영 현황 댓글을 삭제하지 말고 실패한 실행 재실행. 처리 번호로 중복 방지 |
| 특정 작업만 중단 | Issue에 `automation:paused` 라벨 부여. 제거 후 전체 점검에서 미처리 명령도 처리되므로 중단 중에는 명령을 쓰지 않음 |
| 전체 자동화 중단 | Actions에서 Issue management를 Disable. 장기 중지는 team.json의 enabled를 false로 변경해 PR 반영 |

운영 현황 댓글의 숨은 데이터는 수정·삭제하지 않는다. 삭제하면 이전 승인 상태를 복구할 수 없고 최초 등록 기준으로 다시 시작할 수 있다. 수동 변경이 필요하면 자동화를 중지하고 담당자와 원본 기록을 확인한다.

## 확인한 공식 근거

- [이벤트·기본 브랜치·예약 실행 제한](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [워크플로 동시 실행 제어](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#concurrency)
- [GITHUB_TOKEN 권한](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token)
- [Issue Forms 형식](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms)
- [Issue·라벨·담당자 변경 API](https://docs.github.com/en/rest/issues/issues#update-an-issue), [배정 가능 확인](https://docs.github.com/en/rest/issues/assignees#check-if-a-user-can-be-assigned)
- [협업자 권한 조회](https://docs.github.com/en/rest/collaborators/collaborators#get-repository-permissions-for-a-user), [댓글 갱신](https://docs.github.com/en/rest/issues/comments#update-an-issue-comment)
