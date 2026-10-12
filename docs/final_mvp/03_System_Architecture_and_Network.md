# 03. 시스템 구조와 네트워크 — 최종 통합 갱신

## 2026-10-12 최신 적용 기준

최신 기준: 2026-10-12. 원격 integration 727d101(대상 코드 기준), main afd75d0b와 로컬 미병합 수정을 구분한다. 최신 확정 책임은 C 설계/대화 승인·의도, A 계획/도움/경로·동일 B/D 공유, B Expected/전체 관측 영역 비교/실제 Current·revision, D 실행/지정 검사/진행·HMI/제스처/기존 이력·웹이다. 인터페이스 결정·버전·배포는 수현이 담당한다.

최신 논리 연결은 사용자↔C → 승인 Design → A이며, A가 같은 계획 자료를 B와 D에 제공한다. D는 A의 실행 직전 재평가·Step 경로 후보를 받아 조건을 확인하고 Robot을 실행한다. D→B 지정 검사와 B→D 확정 결과로 진행·보류·C 호출을 결정한다.

B가 Expected·전체 관측 영역 비교·Current/revision을 소유한다. D가 공간 비교나 Current 채택을 다시 수행하지 않는다. 제스처 생산·활성 요청 응답 관리·HMI·기존 JSONL→DB/웹은 D 책임이다. 인터페이스 최종 결정·버전 관리·배포 담당은 수현이다.

A의 whole 계획·Step 재평가·Step 경로 계산 분리는 유지한다. API 0.5.1·bundle 0.1.1 계산 후보는 execution_allowed=false다. D 실행 조건 확인 후 자동 진행하며 매 Step 사용자 승인을 추가하지 않는다.

기존 함수·콜백·Robot 프로세스·ROS/장치 어댑터를 우선 재사용한다. 이번 변경에서 새 서비스·큐·B 전용 DB·Current 조회 API·모델 준비 ACK·Current 채택 회신을 만들지 않는다. 문서만으로 실제 ROS graph나 포트 구성이 확정됐다고 표현하지 않는다.

MOCK 통합은 실제 A/B/C 함수와 합성 관측·MOCK Robot이다. CAD REAL은 B 없는 로봇 단독 경로이며, 로컬 full-real은 실제 Robot/제스처와 가짜 B다. 가짜 B의 Current·FINAL MATCH는 실물 완성 증거가 아니다.

[전체 책임·상태·담당자 개발 순서](../16_FINAL_INTEGRATION_CHAT_SYNC_20261012.md) · [핵심 계약·예시](CONTRACTS.md) · [문서 모음](README.md)
