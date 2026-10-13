# Adaptive Co-Assembly — 통합 실행

C가 블록 설계 후보를 만들고 사용자가 승인하면, A가 조립 순서·사람 도움·이동 후보를 계산한다. D가 HMI와 로봇 실행·검사를 관리하며 작업 기록을 PostgreSQL과 웹에 저장한다.

이 배포는 `codex/integration-round1`의 **ebeeef2**(2026-10-13, PR #36 반영)에서 실행에 필요한 파일만 가져온다. 검사·재생 표본·개별 demo·과거 보고서·Isaac/MoveIt은 기본 구성에서 제외한다. A 계산 코드는 하나이며, 파일명이 sample/fixture/fake/trial이어도 현재 실행에서 사용하는 코드·설정·교시 자료는 유지한다.

## 시작 순서

1. [설치·환경 설정](docs/INSTALL.md)에서 사용할 기능의 의존성과 외부 자료를 준비한다.
2. [실행 안내](docs/RUN.md)의 장치 없는 통합 실행으로 HMI·C 승인·A 계산·MOCK 진행을 확인한다. 별도 설계 예제 파일을 주입하지 않고 C 생성 함수를 사용한다.
3. DB가 필요하면 같은 안내에서 계정·제작자 로그인·저장·웹 조회를 설정한다.
4. 현장 REAL 시험은 설치·교시·장치 조건을 확인한 뒤 [REAL 절차](docs/RUN.md#현장-real-시험)를 사용한다. offline C도 REAL 진입점에서는 실제 로봇을 실행한다.

## 코드 위치

| 부분 | 현재 진입점/위치 |
|---|---|
| C·A·HMI·MOCK 통합 | `python3 -m app.mvp_integration` |
| 현장 C·A·D 시험 | `python3 -m app.mvp_real_trial` |
| C 설계·검토·수정 | `app/c_design/main.py` |
| A 전체 계획·재평가·이동 후보 | `planning_trial/assembly_adapter.py`의 세 handle API |
| D 별도 실행 프로세스 | `robot_control_integration/scripts/robot_integration_runtime.py` |
| B 상태·검사 연결 | `perception/perception_mvp/team_connection.py` |
| DB CLI / 웹 | `python3 -m history` / `python3 -m history.web` |

[모듈 연결·계약](docs/INTEGRATION.md)은 호출 순서, Current/revision 책임, 실패·도움·체결 경계를 설명한다.

## 지원 범위와 확인 수준

소프트웨어 범위는 24×24 stud, layer 1~5, C 후보 1~40블록이다. 노랑·파랑은 2×2×1/2×3×1, 빨강은 1×2×1을 지원한다. 실제 공급·교시·관측·체결 가능 범위는 같은 의미가 아니다.

| 범위 | 이 배포에서의 의미 |
|---|---|
| MOCK 통합 | 실제 C/A/B 상태 함수와 가상 D 실행·합성 관측을 사용한다. 실물 조립 증거가 아니다 |
| 현장 REAL 진입점 | 실제 D 로봇·제스처와 **합성 B 관측**을 사용한다. Camera→B 실제 전체 판 관측 성공으로 보고하지 않는다 |
| A 이동 결과 | waypoint/motion proposal이다. MoveIt 전체 궤적 계산·충돌 회피 엔진은 이번 배포에 포함하지 않는다 |
| DB·웹 | 제작자 로그인·Job 소유권·명시 저장·조회·선택 공개 코드가 포함된다. 저장 성공과 조립 확인은 별도 상태다 |
| 외부 환경 | ROS/DRCF2·RG2·제스처 모델·개인 API 키·PostgreSQL 데이터는 별도로 준비한다 |

이 배포의 준비 과정에서 실제 Robot·Camera·제어권·그리퍼·힘/모드/controller를 변경하지 않는다. 실제 장치·관측 정확도·40N 체결 결과는 현장 검증 범위다.

## 보존 자료

main에서 제외한 자료는 GitHub에 남는다. 이력을 재작성하거나 원본을 덮어쓰지 않는다.

- [통합 전체 원본·실측·검사·B 자료·Isaac](https://github.com/suuuhululu/C-2/tree/archive/integration-20261013-ebeeef2)
- [이전 main 전체](https://github.com/suuuhululu/C-2/tree/archive/main-20261013-afd75d0)
- [원본 파일 목록·Git blob·제외 경로 명세](https://github.com/suuuhululu/C-2/blob/codex/archive-runtime-20261013/ARCHIVE_MANIFEST.json)

Isaac/MoveIt은 별도 개발 완료 후 추가한다. 회귀 검사가 필요하면 위 통합 보존 기준에서 가져온다. 현재 실행용 main에 없는 예제/검사 명령을 기본 사용법으로 실행하지 않는다.
