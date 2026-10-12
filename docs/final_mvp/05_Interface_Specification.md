# 05. 인터페이스 명세 — 최종 통합 갱신

## 2026-10-12 최신 적용 기준

최신 기준: 2026-10-12. 원격 integration 727d101(대상 코드 기준), main afd75d0b와 로컬 미병합 수정을 구분한다. 최신 확정 책임은 C 설계/대화 승인·의도, A 계획/도움/경로·동일 B/D 공유, B Expected/전체 관측 영역 비교/실제 Current·revision, D 실행/지정 검사/진행·HMI/제스처/기존 이력·웹이다. 인터페이스 결정·버전·배포는 수현이 담당한다.

계약 ① A→B·D: 승인 Design, 기존 Plan/Step, 고정 plan_base_current, 좌표·형상 기준을 동일하게 제공한다. 최초/새 Plan 생성 시 공유한다. 누락·기준 충돌·한쪽 전달 실패는 실행 보류다. A/B 전달 ACK나 새 Current 조회 API를 필수로 추가하지 않는다.

계약 ② D→B: check_id와 INITIAL/STEP/FINAL, plan_id·step_id 또는 기존 대응 문맥을 제공한다. INITIAL은 Plan/Step 없음, STEP은 둘 다 지정, FINAL은 Plan 지정·Step 없음이다. 작업 뒤 정지·관측 조건을 확인한 D가 요청한다. 재검사는 새 ID이며 B가 Step을 선택하지 않는다.

계약 ③ B→D: B가 관측·전체 판 비교·Current 확정을 끝낸 뒤 요청 대응, 실제 Current/revision, 판정, 실제 사용 Expected, 기존 missing/unexpected/unobservable 차이, 관측 근거를 반환한다. D는 대응·중복·취소·진행만 처리하며 Current나 revision을 다시 만들지 않는다.

Expected는 Plan 시작 기준 Current와 해당 Step까지의 효과로 고정한다. 전체 보이는 구조의 위치·색상·층 변경도 비교한다. 숨은 층은 이전 확인 이력이며 새 관측으로 쓰지 않는다. UNOBSERVABLE과 INVALID_INPUT/PLAN_NOT_FOUND/PROCESSING_FAILED 등 ERROR를 구분한다.

취소: D는 check를 닫고 기존 취소 연결로 B에 통지한다. B는 Current 확정 직전 활성 여부를 확인해 취소 경계 뒤 상태 쓰기를 차단한다. 이미 먼저 확정된 사실은 되돌리지 않으며 새 검사로 기준을 확보한다. 실제 Robot 정지와 검사 취소는 별도다. B에 로봇 lease/generation을 무조건 복제하지 않는다.

C 의도 입력은 실제 Current·단계 Expected·기존 Design·차이다. KEEP/REVISE/UNCLEAR를 재사용한다. Design 없는 REVISE도 변경 대기이며 후보·대화 승인 후 C→A로 연결한다. 기존 Design 동시 반환 경로는 보존한다. 계획 실패 KEEP은 보류이고 불일치 KEEP 재계획과 구분한다.

A-D는 전체 계획→실행 직전 재평가→Step 경로 계산의 3분류 호출을 유지한다. 후보는 execution_allowed=false이며 D 조건 확인 뒤 자동 승인·진행한다. 슬롯 예약·실제 도달/정지/파지·Contact 인계·도움 준비/해제 경계를 유지한다.

공급 파지는 패드 하단이 블록 밑면보다 5mm 위다. TCP 높이 5mm와 같지 않다. 교시 좌표에 과거 보정을 중복 적용하지 않는다. 공통 grid는 회전 뒤 최소 점유 stud가 기준이며 0° 긴 변 Y/90° 긴 변 X다. 실제 픽셀→Robot 변환·실기 정합은 확인 필요다.

문서 예시의 봉투/필드 매핑은 런타임 Schema 구현 완료 증거가 아니다. 별도 모델 ACK·중복 Difference·매 메시지 hash/version/generation·새 서비스/큐/DB 테이블을 추가하지 않는다. 기존 18개 계약 예시는 GitHub 배포 기준에 보존한다.

공급판 모델의 목적은 인식한 블록 중심을 파지 후보로 제공하는 것이다. 현재 RGB 후보는 상단 윤곽·대향점 중점을 사용해 원시 YOLO bounding box 중앙과 다를 수 있다. D 실제 호출·픽셀 중심→Robot 파지 좌표·종류/회전/슬롯 선택·2x1/1x2x1 매핑은 미연결/확인 필요다. 모델 파일만으로 로봇이 바로 사용할 수 없으며 실제 생산자 형식과 기존 D 연결을 먼저 확인한다. 새 서비스/조회 API를 이 문서로 확정하지 않는다.

[전체 책임·상태·담당자 개발 순서](../16_FINAL_INTEGRATION_CHAT_SYNC_20261012.md) · [핵심 계약·예시](CONTRACTS.md) · [문서 모음](README.md)
