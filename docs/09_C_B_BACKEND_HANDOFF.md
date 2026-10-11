# C·B와 Backend 연결 합의 및 검증

2026-10-11 1차 통합: 배치·`verified_regions.layer`는 1~5층입니다. B는 실제 관측을 생산하고 D는 Current 채택·revision·Expected 비교·완료를 관리하는 현행 책임을 유지합니다. 별도 A API 문서와의 차이는 [인터페이스 점검](11_ROUND1_INTERFACE_AUDIT.md)에 기록합니다.

> 2026-10-07 적용 범위: 아래는 기존 Day4의 C/B/D 연결 합의와 검사 기록입니다. 현재 제품 목표는 [최종 MVP](10_FINAL_MVP.md)이며, 설계 확정·직접 결착·지원 응답·최종 Vision 확인·사용자별 DB/웹의 새 계약은 별도 합의가 필요합니다. 기존 block_id 필수 제외·OK/UNOBSERVABLE·check/촬영 순서 의미는 현행 코드에 유지합니다. 연구의 brick_id·PASS/FAIL/UNKNOWN을 합의 없이 기존 callback에 강제하지 않습니다. 두 stud 기하 기준은 최종 Support Risk/결착 증거가 아닙니다.

합의 기준 2026-10-05, GitHub 반영 2026-10-06. 시율의 개발 기준 공유와 홍동의 연결 동의 DM, 이후 사용자의 최종 결정 및 홍동에게 회신한 내용을 반영합니다. DM 자체의 제안을 모두 확정으로 취급하지 않습니다. 기본 계약은 main에 병합된 [Day4 공통 계약](https://github.com/suuuhululu/C-2/blob/main/docs/06_CONTRACT_DRAFT.md)입니다. 이 문서는 이후 결정의 보완이며 구현·장치 시험 결과와 구분합니다.

## C 연결 결정

| 항목 | Day4 적용 |
|---|---|
| 배치 비교 | brick_type, color, x, y, layer, orientation_deg 여섯 필드와 개수로 비교. block_id를 공통 필수값으로 사용하지 않음 |
| C 내부 ID | 논리적 목표 식별은 내부에서 사용할 수 있지만 D가 물리 블록 동일성을 판정하거나 Current / Difference에 ID를 제공하는 조건을 강제하지 않음 |
| 버전 | C가 design_version을 발급, D는 채택 버전을 관리. 최초 1, 실제 전체 목표 배치 변경 시 증가. 탈락 후보·KEEP·동일 배치·배열 순서 변화만으로 증가하지 않음 |
| parent_version | 공통 Design 필수값 아님. C 내부 진단 정보는 경계의 전체 Design 형식과 분리 |
| Revised | 최신 D 채택 Current의 실제 배치를 존중하면서 전체 목표를 생성. 과거 완료 이력이나 block_id로 변경·제거된 배치를 고정하지 않음 |
| 최종 채택 | C의 Validator 통과는 후보 검증. A의 검증된 Plan과 함께 D가 활성 요청·목표 버전·base_current_revision을 확인한 뒤 채택 |
| 무응답 | Day4는 5분 경과 자동 취소·자동 KEEP·임의 Job 종료 없음. 사용자 입력 대기 |
| UNCLEAR | 선택지를 설명해 재질문하고 계속 불명확하면 명시 선택 대기. 무응답·호출 실패와 구분 |
| 후보 거부 | 한 후보의 Validator 탈락이 곧바로 전체 Job 실패는 아님. C 내부에서 유한하게 재생성하고 한도 도달 시 사유와 실패 결과 반환 |
| 취소 | STOP·닫힌 요청에 대한 중단 연결을 지원. 늦게 도착한 결과를 새 질문이나 현재 목표에 채택하지 않음 |

재생성 횟수는 C 내부 정책이며 공통 계약에 3회 같은 숫자를 강제하지 않습니다. 실패·취소의 정확한 반환 envelope는 C와 D의 정상 / 실패 예시로 확인합니다. 현재 D의 HRI dispatch·C 호출 취소 기능이 구현됐다는 뜻은 아닙니다.

### A와 C의 지지 판정

2026-10-06 세은의 동의와 수현의 회신에 따라 A / C의 **Day4 기하 지지 기준을 바로 아래 layer와 겹치는 고유 stud 총 2개 이상으로 통일했습니다.** 중복 stud는 중복 합산하지 않으며, 아래 블록의 개수와 무관합니다. layer=1은 Board 위 첫 층으로 이 아래층 지지 검사에서 제외합니다. C는 전체 Design, A는 각 PLACE 시점의 지지·선행 관계를 검증합니다. 이미 조립된 지지 블록의 실제 변경은 최신 Current를 기준으로 판단합니다. 이 합의는 실제 체결·하중·전도 등 물리 안정성 검증 완료나 프로젝트 전체의 영구 기준을 뜻하지 않습니다.

## B 연결 합의

B 내부의 YOLO·Depth/Grid·다중 시점 융합·이전 상태 추적 형식은 유지할 수 있습니다. 경계에서는 기존 Observed의 check_id, observation_seq, status, visible_blocks, verified_regions, reason을 사용합니다. 상세 confidence·View·추적 이력·미확인 영역을 이 여섯 필드에 임의 추가하지 않고 별도 진단 정보로 구분합니다.

| 담당 | 책임 |
|---|---|
| B | 촬영 가능한 안정 조건·필요 View·판별 가능 여부·Observed·품질 사유 |
| D Backend | 활성 확인 대기·촬영 요청 연결·결과 수신·Current 채택·Expected 비교·완료 / 보류·다음 전달 |
| D Controller | 검증된 관측 자세 이동·실제 정지 확인·실행 중단. B가 joint / TCP / 경로를 생성하지 않음 |
| HMI | 상태·사유 표시와 사용자 명령. 매 Step 조립 완료 버튼을 추가하지 않음 |

### 확인 대상과 촬영 순서

- Backend가 check_id를 발급하고 Job / Plan / Step에 연결합니다. B에게 check_id와 목표 after를 전달하며 즉시 촬영을 강제하지 않습니다.
- Vision 연결부는 촬영 당시 check_id를 고정합니다. 결과 수신 시점의 현재 Step ID로 다시 붙이지 않습니다.
- observation_seq는 촬영 순서 기준입니다. 같은 활성 check에서 이미 처리한 순번 이하 결과는 Current를 덮어쓰지 않습니다. check가 닫혔으면 결과를 진행에 사용하지 않습니다.
- **구현 확인이 남은 제안:** 여러 View를 한 Observed로 반환하면 묶음 시작 시 순번을 고정합니다. 증가 범위(check별 / 전체 세션)와 callback 제공 방식은 B 예시로 확인합니다. D는 check별 마지막 처리 순번을 비교하며 새 고유 check에서는 첫 순번이 0 또는 더 큰 값이어도 수용합니다. 재개·같은 Step 재확인은 새 check입니다.
- 다중 View 중 장면 변화·STOP·확인 대기 변경이 발생하면 그 묶음으로 완료를 확정하지 않습니다. 자동 재관측 요청 여부와 timeout 숫자는 별도 구현 정책이며 무제한 Robot 이동을 요구하지 않습니다.

### 실제 확인 영역과 과거 추적

verified_regions는 공통 assembly grid 좌표·layer 기준으로 점유 상태를 실제 확인한 영역입니다. 한 영역에는 블록과 빈 stud가 함께 있을 수 있으므로 영역 전체를 occupied / empty 단일 값으로 강제하지 않습니다. visible_blocks와 함께 읽습니다.

- occluded_or_unverified는 verified_regions에 넣지 않습니다. 필요하면 B 진단 정보에서 표현합니다.
- 확인 영역에 걸친 실제 블록은 경계 밖으로 뻗더라도 배치를 보고합니다. 검출 누락을 실제 비움으로 주장하지 않습니다.
- visible_blocks에는 이번 관측(동일 관측 묶음의 View 융합 포함)에서 실제 확인한 블록을 담습니다. 과거 추적만으로 유지한 배치를 새 검출값으로 넣지 않습니다.
- 확인 완료한 가린 아래층은 D Current에 유지합니다. B 추적 상태가 D 채택 결과와 어긋났다면 임의로 Current를 덮어쓰지 않습니다. 추적 피드백의 구체적 연결은 B / D가 별도로 확인합니다.
- 현재 Step을 판단할 정보가 부족하면 완료·다음 전달을 보류합니다. 이전 아래층만 가렸고 이번 Step을 읽을 수 있으면 그 가림 자체로 진행을 막지 않습니다.
- OK는 판별 가능이며 MATCH를 의미하지 않습니다. 완료 확인 시점의 확인된 빈 목표 영역은 불일치이며, 미수신 / 미확인과 구분합니다.

### 전달판과 View 구성

전달판은 조립판 상태와 독립적으로 판단합니다. 제시한 표현은 확인된 EMPTY, 확인된 OCCUPIED, UNOBSERVABLE + 사유입니다. 대기 / 미수신은 null이며 EMPTY로 바꾸지 않습니다. 이 의미를 유지하면 별도 verified 불리언을 필수로 중복 추가할 필요는 없습니다.

정확한 B 반환 필드명·전달판 사유를 전달하는 별도 envelope는 callback 예시에서 확인합니다. 현재 HMI는 monitor.place_status와 notice.reason에 표현할 수 있습니다. HMI에 EMPTY를 표시하는 것만으로 새 전달을 허가하지 않습니다. 기존 프레임의 EMPTY를 새 전달 전 비움 증거로 재사용하지 않으며 현재 확인 문맥에 연결해야 합니다.

V0·D1~D4는 초기 시험에서 검출률·가림·촬영 / 이동 시간을 측정한 뒤 실제 공정의 최소 View 구성을 정합니다. 매 Step 다섯 View 필수 촬영·사람 완료 버튼을 공통 전제로 추가하지 않습니다. 실제 pose·정지·이동 성능은 Controller 장치 시험 대상입니다.

## 연결 예시와 소비 검사

`interfaces/fixtures/team_handoff.json`은 기존 `interfaces/fixtures/day4.json`과 `interfaces/fixtures/hmi.json`을 바탕으로 D가 작성한 예시입니다. **B / C 실제 출력·통합 성공·장치 검증 증거가 아닙니다.** 기존 공통 Schema와 Consumer 형식을 그대로 사용합니다. 이 코드·Fixture·시험 파일은 수현의 로컬 개발 checkout에 있으며 이번 문서 게시에는 포함하지 않습니다.

| 예시 | 현재 검사 범위 |
|---|---|
| 현재 목표가 보이고 지지 아래층은 가림 | 기존 Current 유지하며 실제 새 배치 채택 |
| 실제 색상 불일치 | 목표로 덮어쓰지 않고 실제 Current 채택 |
| 확인한 빈 영역 | 해당 층의 이전 배치 삭제 증거 |
| 가림 / 품질 불충분 | Current 유지·HOLD·사유, 순번으로 옛 결과 차단 |
| 다른 layer / 일부 이전 영역만 확인 | 확인 근거가 부족한 기존 배치 삭제 금지 |
| 닫힌 check·역순·중복·새 check | 활성 대상·촬영 순번 기준 수용 / 무시 |
| 전달판 EMPTY / OCCUPIED / UNOBSERVABLE / 대기 | HMI 계약에서 값·사유 보존. 실제 다음 전달 gate 검증 아님 |
| KEEP / Revised Design 후보 | 여섯 배치 필드·전체 Design 형식 검사. 실제 C 생성 / HRI 해석 / A 기하 검증 아님 |

검사는 tests/unit/test_team_handoff.py에서 기존 validate_observed → adopt_observation과 HMI Consumer를 사용합니다. Fixture의 중간 expected는 테스트 기대값이며 B가 반환하는 필드가 아닙니다. 완료·Difference 생성·다음 전달 gate·HRI 호출을 이 검사에서 임의 구현하지 않습니다.

## 다음 연결 순서

1. 홍동의 실제 callback 예시와 비교: 관측 묶음 순번 범위·진단 분리·전달판 사유·현재 확인 문맥 연결.
2. 시율의 수정 계약 / 정상·실패·취소 예시 확인: block_id 필수 제외·버전·유한 재생성·현재 요청 연결.
3. A / C가 합의된 지지 기준(바로 아래층 고유 stud 총 2개 이상)을 동일하게 적용하는지 연결 사례로 확인. D는 Planner의 지지 계산을 대신 구현하지 않음.
4. Backend Expected / Difference / 완료 및 다음 전달 gate를 해당 개발 단계에서 구현·검증.
5. Fake B / C를 실제 구현으로 하나씩 교체해 L3 확인. 다중 View Controller 이동·촬영은 관련 독립 검사 후 실제 장치 시험으로 분리.

## 게시와 이행

이 작업은 work/suhyun-hmi-backend-robot-db에서 기존 미커밋 개발을 보존하여 수행합니다. 이 로컬 checkout의 옛 문서와 GitHub main의 최신 계약은 아직 전체 이력으로 통합하지 않았습니다. 다른 사람의 C 브랜치를 직접 수정하지 않습니다. 공통 docs의 이번 보완은 게시 여부를 실제 원격 결과로 기록하고, C의 계약·코드·Fixture 조정은 시율 작업으로 구분합니다.

## 관측 반환 형식 예시

아래는 완료 확인 시 실제로 읽을 수 있는 2층 목표 영역이 비었다는 D 작성 예시입니다. 가림이나 미수신과 다르며 B의 실제 출력·성능 증거가 아닙니다. 이전에 확인한 1층 블록은 이 영역만으로 삭제하지 않습니다.

```json
{
  "check_id": "J01:C07",
  "observation_seq": 14,
  "status": "OK",
  "visible_blocks": [],
  "verified_regions": [{"x": 3, "y": 5, "width": 3, "height": 2, "layer": 2}],
  "reason": null
}
```
