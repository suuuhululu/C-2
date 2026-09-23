# HMI 상단 정지·경로 진행 색상 검증

- 기준: `origin/main` `7fc2710`, 브랜치 `codex/hmi-emergency-progress-20260923`
- 범위: HMI 표시와 기존 HTTP/ROS 계약 소비. 공통 타입·백엔드·공정 노드는 변경하지 않음.
- 발견 경로: 1차 통합 시험에서 준비·측정 중 상단 정지 버튼 비활성, REAL 실행 중 경로 색상 진행 표시 없음.

## 반영 내용

1. 상단 `정지 요청`은 `ExecuteProcess`의 `ACCEPTED/RUNNING/STOPPING/UNKNOWN`뿐 아니라 `PrepareWorkpiece`의 `ACCEPTED/RUNNING/CANCELING`에서도 활성화한다.
2. 준비·측정 중 누르면 기존 `/api/operator/preparations/{request_id}/cancel`로 Action 취소를 요청한다. 실행 중에는 기존 `/api/operator/runs/{run_id}/stop`을 유지한다.
3. REAL처럼 `mock-execution-preview/1` 구간 판정이 없을 때는 동일 경로 ID·버전·SHA-256을 확인하고 `engraving_progress`를 3D CUT 길이에 대응해 미완료(검정), 진행(황색), 이동 완료(파랑)로 표시한다.
4. 연결 또는 실행 상태가 미확인이면 마지막 완료 길이는 파랑으로 보존하고 이후 경로는 회색 점선으로 표시한다. 파랑을 품질 합격의 초록과 구분한다.

## 실행한 검사

- `pnpm build`: TypeScript·Vite 생산 빌드 성공, 1,589개 모듈 변환.
- 프런트엔드 단위시험 16개 통과: 준비 상태별 상단 정지 활성 조건, CUT 길이 50% 색상 매핑, 연결 미확인 표시를 포함.
- MOCK 브라우저 확인: 준비·측정 진행 시 상단 상태가 `준비·측정 진행 중`으로 바뀌고 `정지 요청` 활성화. 버튼 클릭 후 취소 안내와 최종 `준비 취소 완료`·`정지 확인: 확인됨 (SIM)` 표시를 확인.
- MOCK 실행 확인: 실행 접수 뒤 상단 정지 활성화와 실시간 경로 범례 표시 확인.

## 미검증 범위

- 실제 M0609에 연결하지 않았고 모션·실기 정지 시간은 검증하지 않았다.
- REAL 공정의 실제 피드백으로 파란 경로가 화면에서 순차 갱신되는 현장 확인은 다음 통합 시험에서 수행해야 한다.
- 상단 버튼은 소프트웨어 정지/Action 취소 요청이며 물리 비상정지 장치를 대체하지 않는다.
