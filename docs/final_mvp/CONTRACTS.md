# 최종 통합 핵심 계약·실패 처리·예시

2026-10-12 배포 기준. 책임과 호출 의미는 확정 계약이며, 구체적인 새 봉투/필드 매핑은 문서용 초안이다. 런타임 Schema나 실행 코드를 변경하지 않는다. [기존 10/8 명세와 18개 JSON 예시](../handover/final_mvp_interface_20261008/README.md)를 재사용한다.

## 책임과 연결

| 담당 | 최신 책임 |
|---|---|
| C 시율 | 사용자 설계 대화·수정 후보 제공·대화 승인·차이 의도 확인 |
| A 세은 | 전체 계획·작업/도움·직전 재평가·경로 계산 및 연결 어댑터; 동일 계획 B/D 공유 |
| B 홍동 | Expected·관측 가능한 조립판 전체 비교·실제 Current/revision 확정 |
| D 수현 | Step 실행·Robot·B 지정 검사·판정별 진행/재관측/C 호출/변경 대기·HMI/제스처·기존 이력/웹; 인터페이스 결정·버전·배포 |

```text
사용자↔C → 수정 후보 → D/HMI(실행 승인 Design과 구분)
  → C 대화 APPROVE → A 전체 계획 → 동일 Plan/baseline/형상 → B + D
  → D 준비 → A 직전 재평가 → A Step 경로 후보 → D 조건 확인·자동 실행
  → D 지정 STEP 검사 → B 전체 관측 판 비교/Current 확정 → D 진행·보류·C 대화
  → 모든 Step 확인 → B FINAL/D 종료 → 기존 JSONL→DB→사용자별 웹
```

## 핵심 3계약

| 연결 | 입력·출력 | 호출 시점 | 실패 처리 |
|---|---|---|---|
| A→B·D | 기존 Design/Plan/Step, Plan 시작 기준 Current 사본, 좌표/형상 기준. 같은 plan_id·design_version·base_current_revision·Step/baseline 내용 공유 | 최초/재계획의 새 Plan 생성·갱신 | 무효/기준 충돌/한쪽 공유 실패는 보류. B 계획 누락은 오류. 공유만으로 B 검사나 D 실행 없음 |
| D→B | check_id, INITIAL/STEP/FINAL, Plan·Step 식별/기존 호출 문맥 | INITIAL: 계획 기준 확보; STEP: 지정 작업 후 정지·관측 조건 확인; FINAL: 필요한 Step 확인 뒤 | 입력 오류·Plan/Step 누락·처리 실패와 관측 불가를 구분. B는 Step을 선택/진행하지 않음 |
| B→D | 요청 대응, 확정 Current/revision, 판정, 실제 비교 Expected, 기존 Difference(missing/unexpected/unobservable), 관측 근거/이력 구분 | B가 관측·비교·Current 확정을 끝낸 뒤 | D는 대응·중복·취소·진행만 판단. ERROR를 정상/UNOBSERVABLE로 대체하지 않고 공간 비교/Current 채택을 반복하지 않음 |

INITIAL은 Plan/Step 없음, STEP은 둘 다 지정, FINAL은 Plan 지정·Step 없음이다. 재검사는 기존 요청을 닫고 새 check_id로 같은 대상을 요청한다. 새로운 검사라는 이유로 집기·접촉·슬롯·모의 장면 효과·완료 Step을 다시 적용하지 않는다.

Expected는 Plan 시작 시 고정 Current에 검사 Step까지의 목표 효과를 적용한다. 불일치 뒤 같은 Plan의 baseline을 실제 Current로 바꾸지 않는다. 새 Plan만 B 최신 확정 Current를 기준으로 한다. B는 최종 Design·단계 Expected·이전 Current로 관측 가능한 판 전체를 비교한다. 다른 위치·색상·층·기존 구조 변경도 포함한다. 비교 알고리즘은 B가 선택한다. 가려진 아래층은 이전 확인 이력이며 새 관측/숨은 변경 확인으로 표현하지 않는다.

## 취소와 결과 대응

1. D는 STOP·재계획·검사 교체 때 활성 check를 로컬에서 닫고 기존 연결로 B 취소를 요청한다.
2. B는 검사 확정과 취소를 순서화하고 Current 쓰기 직전 활성 여부를 확인한다. 취소 확정 경계 뒤의 결과는 Current/revision/확인 이력을 갱신하지 않는다.
3. 취소보다 먼저 확정된 사실은 되돌리지 않는다. D는 옛 결과로 진행하지 않으며 취소 경계 확인 후 새 검사로 최신 기준을 확보한다. 취소 실패/불명은 보류다.
4. 같은 ID/동일 내용은 재진행 없이 무시한다. 같은 ID/다른 내용은 원결과·진단을 보존하고 HOLD, 실행 중이면 정지 요청한다. 다른 옛 ID는 진행하지 않는다.
5. 실제 Robot 정지와 검사 취소는 별도 경계다. MOCK STOP_IDLE은 REAL 정지 증거가 아니다. 이 계약의 실제 B 취소 경쟁 상황·장치 연결 시험은 남는다.

## 의도와 실행 경계

D→C는 실제 Current/revision·해당 단계 Expected·기존 승인 Design·Difference/관측 한계를 전달한다. KEEP은 현재 계획 충족을 뜻하지 않는다. 관측 불일치 KEEP은 필요한 사람 정리/재검사 또는 최신 Current 기반 재계획이고, **계획 실패 대화 KEEP은 목표·Current 보존 후 보류**다. 동일 실패 계산을 자동 반복하지 않는다.

REVISE는 수정 의도 접수다. Design 없는 응답도 변경 대기이며 기존 동시 Design 반환은 보존한다. 새 후보→Preview→Review→C 대화 APPROVE→C→A→B/D로 연결한다. UNCLEAR/호출 실패/무응답은 자동 승인하지 않는다. 새 C 봉투/호출을 임의 추가하지 않는다.

A의 전체 계획→실행 직전 재평가→Step 경로 계산은 기존 3분류 호출이다. API 0.5.1·bundle 0.1.1의 후보는 `execution_allowed=false`이며 D가 조건을 확인한 뒤 자동 승인·진행한다. 슬롯 예약·실제 도달/정지/파지·Contact 인계·도움 준비/해제 경계를 유지한다. 새 B 계약에 Robot lease/generation을 그대로 복제하지 않는다.

공급 파지는 **패드 하단이 블록 밑면보다 5mm 위**다. TCP 높이 5mm로 해석하지 않으며 교시와 과거 보정을 중복 적용하지 않는다. 좌표 변환·회전·실물 정합이 확인되지 않은 부분은 확인 필요로 남긴다. 이 문서에서 실제 제어값을 생성하지 않는다.

로컬 손바닥 인계는 모든 Step의 Contact 시작 전만 허용한다. 집기 전 의도 보관→집기 확인→정지·파지 유지→전달판 상공→새 RECEIVE 응답→개방·철수→사람 조립→엄지척→지정 검사 순이다. 인계는 승인 목표를 변경하지 않고 A 방식과 D 전환을 구분해 기록한다. 사람 응답만으로 B Current/완성을 만들지 않는다.

## 계약 예시

아래 P1/S1/Q1 등은 설명용 식별자이며 발급 규칙을 추가하지 않는다. 기존 배포 JSON 예시에 대한 의미 검증용 사례다.

| 상황 | 입력/관측 | 결과·진행 |
|---|---|---|
| 정상 | P1 고정 기준 r0, D STEP Q1/P1/S1, B가 목표와 전체 보이는 구조를 확인 | B Current r1·MATCH·S1 Expected·빈 확인 차이/근거 반환 → D S1 한 번 완료·조건 확인 후 다음 실행 |
| 불일치 | Q2/P1/S2에서 목표 블록 외 다른 위치/색/층의 변경도 확인 | B 실제 r2·MISMATCH·고정 S2 Expected·missing/unexpected → D HOLD/C 요청. Expected를 r2로 바꾸지 않음 |
| 관측 불가 | Q3의 필요한 영역 가림 | UNOBSERVABLE·unobservable/근거, 확인 이력 유지 → D 보류·Q4 같은 대상 재검사. 슬롯 소비/Contact 반복 없음 |
| 처리 실패 | Q5 Plan 누락 또는 내부 처리 실패 | ERROR·실제 원인 보존 → HOLD. 원인 해소 후 새 Q6 검사. 빈 Current/MATCH로 대체하지 않음 |
| 옛 결과 | STOP이 Q7을 닫고 B 취소 확정 뒤 Q7 계산 완료 | B 상태 쓰기 차단·D 진행 없음. 먼저 확정됐던 사실은 새 검사로 확인 |
| 중복/충돌 | 수용한 Q8의 같은 내용 / 다른 Current·MISMATCH 내용 | 동일 중복은 무시. 충돌은 원결과·새 진단 보존/HOLD 및 필요한 정지, D revision 재발급 없음 |
| 설계 변경 | C REVISE(Design 없음), 이후 후보 D2 제공 | 기존 목표/Current 보존·변경 대기 → 후보 표시·대화 승인 → A P2 최신 B Current 기준 생성·동일 B/D 공유 |
| 계획 실패 KEEP | 승인 Design에 A NO_FEASIBLE_ORDER, C KEEP | 목표/Current/실패 사유 보존·HOLD. 같은 입력 A 자동 반복 없음; 사용자 수정·재승인 후 재계산 |

## 확정과 남은 확인

책임·검사 대상·Expected 고정·의도 의미·후보/실행 분리·기존 이력 경로는 확정 사항이다. 로컬 D 다섯 문제·인계/접촉 시험/ROUNDTRIP·계획 실패 KEEP 수정과 원격 integration의 코드는 구분한다. 실제 B 전체 판·취소·FINAL, C 비동기 후보 왕복, A 실패 조건 상세, Isaac 3호출 정렬, 공급 RGB 중심→Robot 좌표와 `2x1`/`1x2x1` 매핑, 실제 파지/체결/정지·전체 서비스·10분 성능은 남는다.

별도 모델 준비 ACK·Current 조회·D Current 채택 회신·중복 Difference·매 메시지 hash/version/generation·새 서비스/큐/DB 테이블은 추가하지 않는다. B 전용 저장 경로 없이 D의 기존 JSONL→DB/사용자별 웹으로 계획·검사·Current·의도·변경·완료를 전달한다.

[문서 10종](README.md) · [최신 상태·담당자 개발 순서](../16_FINAL_INTEGRATION_CHAT_SYNC_20261012.md)
