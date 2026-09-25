# 문서 길잡이

> 2026-09-25 원격 `main` `987a3b7` 기준. AI와 팀원은 아래 **현재 구현 문서 → 원본 코드·ROS 타입** 순서로 확인한다. 날짜가 붙은 기록·제안서는 작성 당시 커밋의 근거이며 현재 구현을 덮어쓰지 않는다.

## 현재 구현을 볼 때

1. [전체 진행·검증 수준](../../docs/REVIEW_STATUS.md), [프로젝트 README](../README.md)
2. [시스템 구조](SYSTEM_STRUCTURE.md) — HMI·경로·공정의 코드 위치와 책임
3. [호출 흐름](INTERFACE_GUIDE.md) — MEASURE/BIND, 경로, 별도 실행·정지
4. [Interface Specification](INTERFACE_SPECIFICATION.md) — HTTP·WebSocket·ROS 필드, 상태·오류·제한 시간·중복/정지 규칙
5. [ROS·파일 인터페이스 기준](INTERFACE_RECOMMENDATION.md) — 이름·단위·ID/해시·모드·완료 조건
6. [공통 타입](../ws_cobot1/src/c2_interfaces/README.md), [경로](../ws_cobot1/src/c2_path/README.md), [공정](../ws_cobot1/src/c2_process/README.md), [HMI 서버](../backend/README.md), [화면](../frontend/README.md), [실행 안내](../ws_cobot1/doc/README.md)

세부 필드는 같은 커밋의 `.action`·`.srv`·`.msg`와 코드가 원본이다. 현재 문서와 코드가 다르면 차이를 기록하고 현재 설치본·원격 main을 다시 확인한다. `schema_version=2`만으로 서로 다른 타입 정의가 호환되지는 않는다.

## 날짜별 근거

- [9/21 일지](daily/2026-09-21.md) · [9/22 일지](daily/2026-09-22.md)
- `daily/`: 그날 병합된 변경·보고. `validation/`: 당시 시험 명령과 결과. `evidence/`: 해당 시험의 입력·출처·산출물.
- [가상 셀 기록](VIRTUAL_CELL_20260922.md), [REAL HMI 통합 기록](HMI_REAL_INTEGRATION_FIXES_20260922.md): 9/22 브랜치·PC의 시험 범위. 가상 장치 결과는 실제 M0609 조각의 합격 기록이 아니다.
- `HMI_*`, `PREPARE_WORKPIECE_ACTION.md`, `C2_FIXED_DRILL_20260919.md`, `ALGORITHM_VALIDATION.md`, `SVG_VECTORIZATION_VALIDATION.md`, `HARDWARE_STATUS.md`, `EXPERIMENT_PLAN.md`, `LEGACY_CLAY_ARCHIVE.md` 등 오래된 문서는 구현 과정·설계 제안·실험 이력이다. 현재 실행 지침은 위 현재 구현 문서와 패키지 README를 따른다.

현재 공정과 다른 자동 집기·스펀지 세척·반납을 설명하던 서비스 계획·아키텍처 도면과 완료된 작업 지시서는 2026-09-23 문서 정리에서 제거했다. 필요한 역사적 비교는 Git 이력의 해당 날짜 커밋에서 읽는다.
