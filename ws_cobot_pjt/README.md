# 새김 메인 프로젝트

> 기준: 2026-09-23 원격 `main` `6536a29`. 이 페이지는 현재 코드의 진입점이다. 날짜가 붙은 설계·검증 문서는 작성 당시의 기록으로 읽는다.

두산 M0609와 2점 그리퍼에 철사로 고정한 드릴을 사용하는 양초 원통 조각 시스템이다. 현재 공정에는 그리퍼 열기, 자동 집기·반납, 스펀지 청소가 없다. ROS 2 기준은 Jazzy이며, 현장 장비·설정과 실기 결과는 코드와 별도로 확인해야 한다.

## 코드 배치

| 경로 | 책임 |
| --- | --- |
| [`frontend/`](frontend/README.md) | React 운영자 HMI. 준비·측정, 이미지, 미리보기, 별도 실행·정지 요청과 이력 표시. |
| [`backend/`](backend/README.md) | FastAPI·SQLite·관리 파일, ROS 게이트웨이, 자산 ID·SHA-256 및 실행 전 조건 검사. |
| [`ws_cobot1/src/c2_interfaces/`](ws_cobot1/src/c2_interfaces/README.md) | 팀 공통 ROS Action 3개, Service 1개, Message 2개. |
| [`ws_cobot1/src/c2_path/`](ws_cobot1/src/c2_path/README.md) | PNG/JPEG 이미지 변환, 원통 3D 경로·미리보기·기하 검증. 로봇 모션을 실행하지 않는다. |
| [`ws_cobot1/src/c2_process/`](ws_cobot1/src/c2_process/README.md) | 양초 측정·스냅샷 BIND·최종 검사·조각·정지·상태. 모션 명령의 단일 소유자. |
| `ws_dsr/src/` | 실행 PC의 외부 드라이버·그리퍼 소스 설치 위치. 기본 Git 제외이며 제어권 관측 패치 4개 파일만 추적한다. |
| [`docs/`](docs/SYSTEM_STRUCTURE.md) | 현재 구조·계약과 날짜별 시험·개발 기록. |

## 운영 흐름

`양초 준비 → MEASURE(윗면 1점·옆면 8점) → 측정 원본 저장 → BIND_SNAPSHOT → 이미지 경로 생성·미리보기 → 운영자 별도 ExecuteProcess 요청 → 공정 최종 검사·조각·결과 기록`

REAL 측정의 원통 중심·반지름은 접촉 추정이며 높이는 운영자가 자로 측정한 값을 사용한다. 화면의 드릴 ON 체크는 수동 조작 확인 입력으로, 전원 센서나 드릴 제어 명령이 아니다. 경로 생성 성공, 실행 요청 수락, 실제 모션 완료와 가공 품질은 서로 다른 확인 단계다.

기본 실행은 저장소 루트에서 `python3 ws_cobot_pjt/run_monitor.py`다. MOCK 화면은 `http://127.0.0.1:5174/operator`, API는 `http://127.0.0.1:8010`에서 연다. 설치와 ROS SIM/REAL 옵션은 [백엔드 실행 안내](backend/README.md)를 따른다. `run_monitor.py`는 공정 노드와 두산 드라이버를 자동 기동하지 않는다.

## 현재 문서

[문서 길잡이](docs/README.md)에서 현재 구현 안내와 날짜별 근거를 구분한다.

- [시스템 구조](docs/SYSTEM_STRUCTURE.md) · [호출 흐름](docs/INTERFACE_GUIDE.md) · [인터페이스 계약](docs/INTERFACE_RECOMMENDATION.md)
- [ROS 실행·설정](ws_cobot1/doc/README.md) · [전체 진행 현황](../docs/REVIEW_STATUS.md)
- [9/21 개발 일지](docs/daily/2026-09-21.md) · [9/22 개발 일지](docs/daily/2026-09-22.md)
- `docs/daily/`, `docs/validation/`, `docs/evidence/`는 각 날짜·커밋의 근거이며 최신 실행 지침의 우선 출처가 아니다.

현재 코드에는 REAL 실행 후보 경로와 요청 연결이 있으나, 가상 셀과 단위·통합 시험 기록을 실제 M0609 연속 조각의 검증으로 확대해서는 안 된다. 최종 실행 전에는 현장 설정·설치 버전·로봇 상태와 해당 경로의 검사를 확인한다.
