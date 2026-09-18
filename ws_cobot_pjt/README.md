# ws_cobot_pjt · 메인 프로젝트

## 현재 로컬 모니터 구현 · 2026-09-18

사용자 승인에 따라 **새 모니터 HMI·FastAPI·SQLite·모의 게이트웨이**를 구현했다. 저장소 루트에서 `python3 ws_cobot_pjt/run_monitor.py`로 실행하고 http://127.0.0.1:5174/operator 를 연다. 새 DB는 `backend/monitor_data/monitor.sqlite3`다. [구현·DB·계약 인계](docs/HMI_MONITOR_IMPLEMENTATION.md), [서버](backend/README.md), [화면](frontend/README.md).

현재 기본 화면은 운영자 전용이며 고객 웹앱·주문·대기열을 사용하지 않는다. 좌표 담당자 답변의 r34mm 및 GripperDA_v1/칼끝 구분을 반영했다. 나머지 높이·유효 구간은 모의 값이다. ROS 연결 코드는 작성했으나 공통 타입·파일 계약 연동과 실기 검증은 남아 있다. 아래 이전 진행 기록의 치수·재료·이관 상태와 구분한다.

## 이전 진행 기록

목표는 고객 도안을 M0609와 헤라로 원기둥 표면에 음각하는 공정을 도안 입력부터 결과 확인까지 연결하는 것이다. 현재 목표 형상은 지름 70mm·높이 200mm이며 지점토·비누베이스를 재료 후보로 둔다. 팀 담당 배정과 실기 합격 기준은 추가 확정한다.

2026-09-18 축소 설계는 **고객용 웹앱 없이 시스템 모니터 → 좌표·경로 생성 → 공정 제어**의 세 노드로 구성한다. 작업대·대상의 고정 좌표와 고정 그리퍼·교체 도구 조건을 반영했다. [팀 인터페이스 안내](docs/INTERFACE_GUIDE.md), [목표 디렉토리](docs/SYSTEM_STRUCTURE.md), [상세 통신 계약](docs/INTERFACE_RECOMMENDATION.md)을 개발 기준 초안으로 사용한다. 현재 `clay_carving`·`clay_hmi` 코드의 구현 상태와 새 계약의 구현 목표를 구분한다.

이전 고객 웹앱·HMI 초안은 개발 PC에 별도로 보존했다. GitHub의 이번 모니터 초안에는 고객용 흐름을 포함하지 않는다. 현재 구현과 ROS 통합 대기 범위는 위 모니터 구현 안내를 따른다.

2026-09-17 기준 C-2에는 서비스·시스템 설계, 알고리즘 검증 결과와 시험 계획을 문서화했다. 알고리즘과 평면 DRL 초안은 개인 작업 폴더에서 수행한 기록이며 이번 문서 반영에 실행 코드를 가져오지 않았다. C-2의 팀 공정·서버·화면 구현과 원기둥 실기는 아직 완료되지 않았다. 외부 환경의 가상 로봇 이동 보고도 메인 공정 완료와 구분한다. [현재 진행 현황](../docs/REVIEW_STATUS.md).

9/17 추가 기록: 지점토 평면의 선분·정사각형·원·별 그리기 수행 보고, 시율의 접촉식 위치·치수 측정과 공구 전달 기능 개발, 팀별 알고리즘 검토를 [0917 일지](docs/daily/2026-09-17.md)에 정리했다. 단위 실기의 정량 품질·반복성, 자동화 전체 연결과 원통 실기는 별도 검증 대상이다.

## 배치

- `ws_cobot1/src/`: 팀 공정·ROS 노드·launch 패키지. 현재 구현은 `clay_carving`·`clay_hmi`다. `c2_interfaces`·`c2_path`·`c2_process`는 [개발 폴더·역할 안내](ws_cobot1/src/README.md)를 준비했고, 빌드 설정·메시지·노드는 구현할 대상이다.
- `ws_cobot1/doc/`: 실제 ROS 실행 순서·필요 설정·종료·재현 절차.
- `ws_dsr/src/`: 로컬 외부 로봇·그리퍼 실행환경. 폴더 전체는 Git 제외이며 `ws_cobot1`과 같은 패키지를 중복 복사하지 않는다.
- `backend/app/`: 새 모니터의 FastAPI API·DB·모의 상대·ROS 게이트웨이 연결 코드. 기본 실행은 MOCK이며 ROS 통합은 대기 중이다. [서버 실행 방법](backend/README.md).
- `frontend/src/monitor/`, `frontend/public/`: React·TypeScript 운영자 HMI와 모의 샘플. 기존 PyQt HMI는 `ws_cobot1/src/clay_hmi`에 보존한다. [화면 실행 방법](frontend/README.md).
- `docker/`: 팀에서 합의한 Dockerfile·Compose·이미지 버전 기록.
- `DartPlatform/`: 로컬 설치 위치. 설치 프로그램·로그는 Git에서 제외하고 안내만 공유한다.
- `docs/`: 기획, 구성도, 인터페이스 합의, 통합·실기 시험 결과.
- 공용 모듈이 필요해지면 먼저 연결 규칙과 의존성을 합의한다.

## 공정 설계 초안

아래는 설계 예시이며 제조사 규정이나 실행 코드가 아니다.

`도안 준비 → 경로·DRL 확정 → 현장 준비 확인 → 파지 확인 → 가공 ↔ 스펀지 세척 → 반납·해제 확인 → 복귀 → 품질 확인 → 대기`

각 단계의 진입 조건·완료 조건·제한 시간·오류 처리를 정의한다. 실제 피드백이 없는 항목은 미확인으로 기록하고 대체 확인 방법을 합의한다.

## 시작할 문서

- [현재 3개 노드의 인터페이스·팀 협업 안내](docs/INTERFACE_GUIDE.md)
- [목표 디렉토리·노드·파일별 역할](docs/SYSTEM_STRUCTURE.md)
- [Action·Service·Topic 상세 계약 v1](docs/INTERFACE_RECOMMENDATION.md)
- [0917 단위기능 테스트·개발 일지](docs/daily/2026-09-17.md)
- [서비스·인터페이스 계획](docs/PROJECT_PLAN.md)
- [서비스 흐름과 세척·오류 처리](docs/SERVICE_FLOW.md)
- [시스템 아키텍처와 실행 배치](docs/SYSTEM_ARCHITECTURE.md)
- [기존 중심선·경로 최적화 검증](docs/ALGORITHM_VALIDATION.md)
- [SVG 영역·굵기 보존 비교와 Potrace 선택](docs/SVG_VECTORIZATION_VALIDATION.md)
- [실험·기록 계획](docs/EXPERIMENT_PLAN.md)
- [현장 설정 확인 범위](docs/HARDWARE_STATUS.md)
- [통합·실기 시험 기록 양식](docs/VALIDATION_TEMPLATE.md)
- [일정과 분업](../docs/PROJECT_GUIDE.md)
- [환경과 워크스페이스](../docs/WORKSPACES.md)
- [외부 패키지 출처·버전 기록](../docs/DEPENDENCIES.md)
- [ROS 실행·설정 기록](ws_cobot1/doc/README.md)

`main`에 병합된 코드는 동료 검토를 통과한 코드다. 실기 검증 완료는 별도 시험 기록과 시험한 커밋으로 판단한다.
