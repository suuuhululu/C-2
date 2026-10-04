# 팀원 협업·독립 개발 안내

최신 책임은 시율 Design / HRI, 세은 Plan / 검증, 홍동 Observed, 수현 상태·비교·Robot / HMI / 통합입니다. 2026-10-04 사용자가 역할 분담을 재확인했습니다. 이전 문서에서 세은을 Design 생성 Owner, 시율을 deterministic 편차 비교 Owner로 읽지 않습니다.

## 독립 입력과 결과

| 담당 | 첫 입력 → 출력 | 제공물 | 책임 경계 |
|---|---|---|---|
| 시율 | 키워드 / 텍스트 → Initial / 유지 / Revised / 불명확 | Design·질문·출력 오류 예시 | 조립 순서·Current / Expected 제외 |
| 세은 | Design + Current + 제약 → Plan / Remaining / invalid | Step 목표 / 효과·Replan 예시 | 의도·Robot 경로·Expected 제외 |
| 홍동 | 저장 이미지 → Observed·품질 / 오류 | grid / layer / 방향·가림 / 실패 | 최종 Current 채택·Difference는 Backend |
| 수현 | 모듈 Fixture·전달 결과·버튼 → 상태 / Expected / 다음 요청 | Fake 전달·전이·지연 / 중복·HMI / 로그 | 의도·Design·Planner 알고리즘 대행 제외 |

계약이 미정이면 [초안](06_CONTRACT_DRAFT.md)의 해당 항목만 연결 담당과 확정합니다. Producer 전체를 기다리지 않습니다. 계산은 Job ID·ROS·장치 없는 Fixture로 시험하고 adapter가 식별·외부 연결을 붙입니다.

```text
시율 Design → 세은 Plan / 검증 → Design + Plan을 수현 Backend
→ 수현 Robot 전달 → 사람 조립 → 홍동 Observed
→ 수현 Current 채택 / Expected 비교
→ 실제 차이면 시율 질문 / 유지·수정 → 세은 Replan → 수현 채택
```

전달 성공은 조립 성공이 아닙니다. 불확실 관측은 Current 유지·보류합니다. 정상 조립 대기와 실제 차이의 구분은 홍동·세은·수현이 합의합니다.

## 작업 완료와 문서 관리

1. 작은 목표·입출력·정상 / 오류 기대값을 설명합니다.
2. Fixture와 실제 검증 결과를 준비합니다.
3. 인접 담당이 같은 필드·단위·오류로 소비하는지 확인합니다.
4. PR에 이유·계약 영향·실제 검증·미검증을 기록하고 사람 리뷰를 받습니다.
5. STATUS에 실제 진행과 다음 작업을 적습니다.

현재 실행 코드·pytest·CI는 없습니다. 이후 코드에는 UNIT_TEST_POLICY의 pytest·L1~L3를 적용합니다. 문서 확인·Mock·Sim 성공을 REAL 성공으로 표시하지 않습니다.

- `00_CURRENT_DECISIONS.md`: 현재 합의와 근거 ID.
- `06_CONTRACT_DRAFT.md`: 제안 / 확인 필요 계약.
- `STATUS.md`: 진행·증거·blocker·다음 작업.
- `docs/reference/`: 과거 원본 보존, 현재 합의로 오인하지 않음.

수현은 Backend·Robot·HMI 내부 구조를 정할 수 있습니다. 공유 Schema·좌표·관측·연결은 관련 담당과 맞춥니다. 실측·인식·정지 성능은 담당자 시험으로 확인합니다.

## Git 협업

feature → PR → 작성자 외 사람 리뷰 → Merge. 최초 빈 레포 준비는 [레포 가이드](05_REPOSITORY_GUIDE.md)를 따릅니다. 공통 계약은 통합·연결 담당 리뷰, Robot 동작 / 정지는 Robot Owner와 다른 사람 리뷰가 필요합니다. 팀원 GitHub 계정·권한·브랜치 보호는 이번 작업에서 설정하지 않습니다.

## 새 AI 채팅 요청 예시

```text
AGENTS.md, docs/00_CURRENT_DECISIONS.md, docs/STATUS.md를 읽어 주세요.
담당: [시율 / 세은 / 홍동 / 수현]
목표: [작은 기능 하나]
범위: [파일 / 모듈]
입출력: [합의된 계약·Fixture 또는 확인할 초안]
완료: [정상·실패·실제 결과]
최신 결정·제안을 구분하고 실제 검증·미검증·다음 작업을 기록하세요.
```
