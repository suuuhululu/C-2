# 02. 시스템 요구사항 — 최종 통합 갱신

## 2026-10-12 최신 적용 기준

최신 기준: 2026-10-12. 원격 integration 727d101(대상 코드 기준), main afd75d0b와 로컬 미병합 수정을 구분한다. 최신 확정 책임은 C 설계/대화 승인·의도, A 계획/도움/경로·동일 B/D 공유, B Expected/전체 관측 영역 비교/실제 Current·revision, D 실행/지정 검사/진행·HMI/제스처/기존 이력·웹이다. 인터페이스 결정·버전·배포는 수현이 담당한다.

A는 동일 Design·Plan·Plan 기준 Current·좌표/형상 기준을 B와 D에 제공한다. B는 고정 기준과 Step 효과로 Expected를 만들고 관측 가능한 조립판 전체를 비교하며 실제 Current/revision을 확정한다. D는 검사 대상을 지정하고 결과 대응·진행을 관리한다.

D 검사 요청은 check_id와 INITIAL/STEP/FINAL 및 Plan·Step 문맥을 구분한다. 재검사는 새 check_id를 쓰며 집기·접촉·완료 Step·슬롯 소비를 반복하지 않는다. B가 실행 Step을 추정하거나 다음 Step으로 넘어가지 않는다.

같은 Plan의 Expected를 불일치 Current로 덮어쓰지 않는다. 재계획의 새 Plan은 B가 확정한 최신 Current를 기준으로 한다. 가려진 아래층은 과거 확인 이력으로 유지하며 새 관측이나 숨은 변경 확인으로 표시하지 않는다.

ERROR와 UNOBSERVABLE을 구분하고 모두 다음 실행을 보류한다. 같은 ID의 동일 결과는 무시하고, 다른 내용의 충돌은 원결과·진단을 보존해 HOLD 및 필요한 정지로 연결한다. STOP/재계획의 B 취소 경계 뒤 옛 검사가 Current를 갱신해서는 안 된다.

REVISE에 Design이 없어도 수정 의도 접수·변경 대기로 처리한다. 후보 제공→Preview→Review→C 대화 APPROVE 뒤에만 A로 전달한다. 계획 실패 대화의 KEEP은 목표·Current 보존 후 보류이며, 실제 관측 불일치의 KEEP 재계획과 구분한다.

결착 전 모든 Step의 손바닥 인계 전환은 D 로컬 시험에 연결됐다. 정지·파지 유지 확인, 전달 위치 도달, 새 RECEIVE 응답, 개방, 사람 조립, 엄지척, B 검사 순서를 유지한다. 실제 전체 Camera/Robot 통합과 물리 결착은 별도 검증 대상이다.

[전체 책임·상태·담당자 개발 순서](../16_FINAL_INTEGRATION_CHAT_SYNC_20261012.md) · [핵심 계약·예시](CONTRACTS.md) · [문서 모음](README.md)
