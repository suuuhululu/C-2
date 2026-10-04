# AI-Generated Code Policy

> **Purpose:** AI를 빠른 pair programmer로 사용하되, 팀원이 이해할 수
> 없는 대규모 코드와 불필요한 복잡성이 repository에 축적되는 것을
> 방지한다.

## 1. Core Principles

**MUST --- Architecture is human-owned.**

AI는 확정된 architecture/interface 안에서 작은 기능을 구현한다.

**MUST --- Human owns the code even when AI writes it.**

AI 코드라도 PR 작성자는 입력, 출력, 핵심 flow, failure path,
dependency를 설명할 수 있어야 한다.

**SHOULD --- Prefer the smallest implementation that satisfies the
current requirement.**

YAGNI/KISS를 기본으로 한다.

## 2. Code Budget

숫자는 절대 금지선이 아니라 warning threshold다.

### SHOULD

-   일반 함수: 약 10\~40 LOC
-   복잡한 함수: 약 60 LOC 이하 권장
-   일반 Python module: 약 50\~250 LOC
-   주석은 WHAT보다 WHY 중심

### REVIEW REQUIRED

PR에서 이유를 설명한다. - 파일 400 LOC 초과 - AI 한 작업 변경량 300 LOC
초과 - 신규 파일 5개 이상 - 신규 class 3개 이상 - 신규 dependency -
새로운 abstraction layer

### MUST --- STOP & REPORT

다음이 예상되면 구현 전에 계획을 보고한다. - 약 800 LOC 이상 생성/변경 -
10개 이상 파일 생성/변경 - architecture/interface 변경 - 새로운
framework/service/DB 필요

``` text
EXPECTED SIZE:
FILES:
WHY THIS SIZE IS NECESSARY:
SIMPLER OPTION CONSIDERED:
CONTRACT IMPACT:
```

## 3. AI 작업 단위

**MUST:** 가능한 한 기능 1개씩 요청한다.

나쁜 요청: "Perception 전체 구현해줘."

좋은 요청: "`camera_frame → block_detection[]`만 구현하고 schema를
만족하는 unit test를 추가하라."

권장: signature 확인 → 최소 구현 → unit test → 실행 → 다음 기능.

## 4. Over-Engineering 금지

현재 요구 없이 다음을 도입하지 않는다. -
Factory/Manager/Service/Repository 계층 중복 - 사용처 하나뿐인 abstract
base class - speculative plugin system - dependency injection
framework - 별도 cache/message queue - generic future-proof framework -
의미 없는 `utils/`, `helpers/`, `common/`

**SHOULD:** abstraction은 최소 2개 이상의 실제 사용처가 생겼을 때
검토한다.

## 5. File Split

파일이 길다고 무조건 쪼개지 않는다. 서로 다른 책임, 독립 테스트 가치,
반복 사용, flow 이해 개선이 있을 때 분리한다.

100줄 기능을 10개 파일로 쪼개는 것도 과도한 복잡성이다.

## 6. Comment Policy

> **WHAT은 코드로, WHY는 주석으로.**

코드를 그대로 번역한 장황한 주석은 제거한다. 설계 이유, 안전 이유,
비직관적 선택을 설명하는 주석을 남긴다.

## 7. Dependency Policy

신규 dependency는 REVIEW REQUIRED.

``` text
DEPENDENCY:
WHY:
WHY CURRENT STACK IS INSUFFICIENT:
VERSION:
```

dependency 오류를 전체 package 최신화로 해결하지 않는다.

## 8. Refactoring

"깔끔하게 리팩터링" 같은 모호한 요청을 피한다.

권장: \> behavior와 public interface를 유지하면서 LOC와 abstraction 수를
줄여라. 새로운 framework/pattern/class를 도입하지 말고 기존 테스트를
유지하라.

가능하면 전후 `Files / LOC / Classes / Dependencies / Tests`를 기록한다.

## 9. Human Explainability Gate

AI가 PR 본문을 작성할 수 있지만 Human Review는 자동화하지 않는다.

작성자는 다음을 설명할 수 있어야 한다. 1. 입력은? 2. 출력은? 3. 핵심
로직은? 4. 실패하면? 5. 어떤 interface/dependency에 연결되는가?

설명하지 못하면 Merge하지 않는다.

> **AI may write the PR. Human must own the PR.**

## 10. PR Template

``` text
## What
## Why
## Input / Output
## Flow
## Failure
## Test

## Complexity
Files changed:
Approx. LOC changed:
New classes:
New dependencies:

## Policy Exception
위반한 SHOULD와 이유:

## AI-generated
Yes / No
```

## 11. Review / Merge

일반 PR: - MUST: CI PASS - MUST: 작성자 외 Human reviewer 1명 승인 -
MUST: 작성자가 flow 설명 가능

특수 PR: - `interfaces/`, DB schema, Docker Compose, ROS2 contract →
Integration Owner 승인 포함 - REAL M0609 / safety → Robot Owner + 다른
Human reviewer 승인

자기 PR을 혼자 승인하지 않는다.

## 12. MUST / SHOULD / MAY

-   **MUST:** 위반 시 원칙적으로 Merge 불가
-   **SHOULD:** 기본적으로 지키되 예외 시 PR `Policy Exception`에 이유
    기록
-   **MAY:** 상황에 따라 선택

SHOULD의 목적은 숫자 강제가 아니라 복잡성이 증가할 때 사람이 이유를
생각하게 하는 것이다.

## 13. AI 금지사항

-   repository 전체 재설계
-   unrelated file 대규모 수정
-   interface/DB/ROS 이름 임의 변경
-   테스트 삭제/assertion 약화
-   broad `except: pass`
-   dependency 일괄 최신화
-   사용하지 않는 abstraction
-   "production-ready"를 이유로 framework 확대
-   secret 출력/commit
-   "작동할 것"을 실제 테스트 결과처럼 보고

## 14. Test Code Exception

테스트 코드는 production code보다 길 수 있다. LOC 정책의 핵심 대상은
application code의 불필요한 복잡성이다.

## 15. Team Rule

> **Every line of code is a liability until its necessity is
> demonstrated.**

완료 기준은 코드량이 아니라 필요한 기능, 계약 준수, 테스트 가능성, 팀의
이해, 실패 동작 설명 가능성이다.

> **Architecture is human-owned. Interfaces are contract-owned. AI
> implements small tasks. Code has a budget.**
