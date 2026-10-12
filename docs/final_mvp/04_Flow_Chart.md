# 04. 최종 MVP 동작 흐름도 — 최종 통합 갱신

## 2026-10-12 최신 적용 기준

최신 기준: 2026-10-12. 원격 integration 727d101(대상 코드 기준), main afd75d0b와 로컬 미병합 수정을 구분한다. 최신 확정 책임은 C 설계/대화 승인·의도, A 계획/도움/경로·동일 B/D 공유, B Expected/전체 관측 영역 비교/실제 Current·revision, D 실행/지정 검사/진행·HMI/제스처/기존 이력·웹이다. 인터페이스 결정·버전·배포는 수현이 담당한다.

정상 흐름: C 수정 후보/HMI 미리보기 → C 대화 승인 → 필요한 INITIAL로 B Current 확보 → A 전체 계획 → 같은 계획 B/D 공유 → D Step 준비 → A 직전 재평가 → A 경로 후보 → D 조건 확인·실행 → D 지정 STEP 검사 → B 확정 MATCH → D 해당 Step 한 번 완료·자동 다음 Step.

불일치 흐름: B 전체 관측 영역 MISMATCH → D 실행 보류 → 실제 Current·단계 Expected·기존 Design·차이를 C에 전달 → KEEP/REVISE/UNCLEAR. KEEP도 현재 Plan을 만족하지 않으면 다음 Step으로 직행하지 않는다. 새 Plan은 최신 B Current 기준으로 만든다.

관측 불가 또는 처리 실패: UNOBSERVABLE과 ERROR를 구분해 사유 표시·HOLD → 원인 해소 → 명시적 재검사 → 새 check_id로 같은 Plan/Step 확인. 집기·접촉·슬롯 소비를 다시 하지 않는다.

설계 변경: REVISE 의도 접수 → 기존 승인 목표·Current·진행 이력 보존 → 수정 후보 제공·HMI 표시 → C 대화 재승인 → 기존 C→A→B/D 경로로 새 계획. 계획 실패 대화 KEEP은 같은 입력의 자동 재호출을 중단하고 보류한다.

손바닥 인계: 결착 시작 전 요청 → 이동 정지·파지 확인 → 전달판 상공 → 새 RECEIVE 응답 → 개방·철수 → 사람 조립 → 엄지척 → 검사/진행. Contact가 시작된 뒤에는 인계로 전환하지 않는다. 제스처는 설계 승인·조립 완료 판정이 아니다.

종료: 필요한 Step 확인/작업 소진 → B FINAL·D 조립 종료 판단 → 사용자별 이력 저장·웹 반영. STOP/재계획은 활성 검사 종료 및 B 취소 확정 경계와 실제 로봇 정지를 별도로 확인한다.

[전체 책임·상태·담당자 개발 순서](../16_FINAL_INTEGRATION_CHAT_SYNC_20261012.md) · [핵심 계약·예시](CONTRACTS.md) · [문서 모음](README.md)
