# 참고자료의 적용 범위

갱신: 2026-10-07. 이 폴더의 과거 계획·합의·정책·GT **원문은 변경하지 않고 보존**합니다. 현재 제품 목표는 [최종 MVP](../10_FINAL_MVP.md), 결정 우선순위는 [현재 결정](../00_CURRENT_DECISIONS.md), 현재 구현·시험 증거는 [STATUS](../STATUS.md)를 확인합니다.

| 자료 | 사용할 범위 |
|---|---|
| [프로젝트 초기 계획](adaptive_coassembly_project_plan.md) | 과거 기능·일정·담당·DB/서비스 제안. 최신 최종 MVP 또는 역할 재배정의 근거로 자동 적용하지 않음 |
| [초기 인터페이스 수정본](<Adaptive Co Assembly 인터페이스_수정본.md>) | 당시 입출력/TBD 근거. 직접 결착·사용자별 DB/웹의 확정 Schema가 아님 |
| [인터페이스 정책](adaptive-co-assembly-interface-policy.md) | 당시 합의/검증 원칙. 현재 코드 계약과 새 요구의 이행을 구분 |
| [엔지니어링 원칙](adaptive_coassembly_engineering_principles.md) | 설계·증거 관리 참고. 현재 요청 없이 새 시스템/도구를 추가하는 지시가 아님 |
| [AI 코드 정책](AI_CODE_POLICY.md) | 최소 변경·개발자 설명·사람 리뷰 원칙; 이번 문서 변경의 검증과 실제 실행을 구분 |
| [단위 시험 정책](UNIT_TEST_POLICY.md) | 계약 Fixture·L1~L4 증거 수준; 실물 안전 조건은 Mock 성공으로 대체하지 않음 |
| [의자1 GT](assembly_board_블럭의자1/ground_truth_notes.md) | 원본 촬영·좌표 기록. 과거 0-based layer 등과 현재 공통 좌표를 구분 |
| [의자2 GT](assembly_board_블럭의자2/chair_2_ground_truth_notes.md) | 원자료의 빨강 등 지원 밖 블록을 새 유효 입력/최종 생성 범위로 추정하지 않음 |

새 최종 목표는 LLM/사용자 커스텀 의자 확정·조립 순서/경로·Robot 조립판 직접 결착·사람 지지·세 단계 종료·사용자별 DB/웹입니다. 과거 전달/사람 조립·DB/웹 제외 문구는 최종 제품 요구를 덮어쓰지 않습니다. [수현 연구 설계](../suhyun_individual_research_topic.md)는 새 첨부 근거이며 원문의 ‘확정’, 필드/역할 초안과 제품 적용 상태를 구분합니다.
