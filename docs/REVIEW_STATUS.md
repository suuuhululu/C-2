# 현재 개발·검증 현황

> 기준: 2026-09-25 원격 `main` `987a3b7`(PR #90 병합). 이 문서는 코드의 현재 구현 범위와 저장소에서 확인한 시험 기록을 구분한다. 설치 PC의 버전·현장 상태와 이후 병합은 다시 확인한다.

## 코드에 있는 것

| 영역 | 현재 구현 | 확인 경계 |
| --- | --- | --- |
| 공통 계약 | `c2_interfaces`: `PrepareWorkpiece`, `GeneratePath`, `ExecuteProcess` Action, `StopProcess` Service, 상태·이벤트 Message | 같은 커밋의 타입을 모든 ROS 노드에서 사용해야 한다. |
| HMI·서버 | React HMI, FastAPI·SQLite, 관리 자산과 ID·SHA-256, MOCK/ROS SIM/REAL 분기, 준비→경로→미리보기→별도 실행 요청 | 화면 표시나 요청 수락만으로 실제 동작 완료가 되지 않는다. |
| 경로 | 이미지→SVG/2D→원통 3D 경로, 미리보기·기하 보고서. REAL 설정과 측정 스냅샷을 받은 실행 후보 생성 | 경로 노드는 모션을 실행하지 않는다. 기하 검사로 전체 궤적 간섭·가공 품질을 보증하지 않는다. |
| 공정 | 측정 MEASURE/BIND, 상태·제어권 관측, 현재/HOME→첫 APPROACH entry 계획, 최종 경로·설정·관절 검사, 조각·검사된 HOME 복귀·정지 및 REAL 공정 노드 | REAL 또는 승인된 entry 활성 prepared 정상 실행은 `PRECHECK → ENTRY → ENGRAVE → RETURN_HOME → FINISH`. 실제 장치 제어는 외부 드라이버와 현장 설정에 의존한다. |
| 실행기 | `run_monitor.py`가 HMI·서버·필요시 경로 노드를 시작 | 공정 노드·드라이버는 별도 기동. REAL은 `--transport ros --mode REAL`과 확인된 준비 설정이 필요하다. |

현재 REAL 또는 승인된 entry 활성 작업 순서는 **MEASURE → 측정 원본·설정의 스냅샷 BIND → GeneratePath → 운영자 미리보기 → 별도 ExecuteProcess → PRECHECK → ENTRY → ENGRAVE → RETURN_HOME → FINISH**다. entry와 HOME 복귀 정책은 실측 윗면에 대한 상대 여유와 검사 기준이며 양초의 절대 표면값이 아니다. 정상 성공 경로의 검사된 HOME 복귀와 실패·보호정지·정지 미확인 뒤 자동 복귀 금지를 구분한다. entry 비활성 호환 흐름에서는 두 콜백이 생략될 수 있다. 고정 드릴을 쓰며 그리퍼 개폐, 자동 집기·반납·청소는 없다. 드릴 ON은 HMI의 수동 확인 입력으로, 전원 감지나 자동 제어가 아니다. 세부 계약은 [시스템 구조](../ws_cobot_pjt/docs/SYSTEM_STRUCTURE.md), [호출 흐름](../ws_cobot_pjt/docs/INTERFACE_GUIDE.md), [인터페이스 명세](../ws_cobot_pjt/docs/INTERFACE_SPECIFICATION.md)를 따른다.

## 검증 수준

- 저장소에는 Jazzy 빌드, Python/프런트엔드 단위·통합 시험, MOCK 흐름과 가상 셀 시험 기록이 있다. 가상 셀은 실제 HMI·경로·공정 ROS 코드를 연결하되 측정·로봇 장치 경계에 모의 어댑터를 썼다. 정상·IK 실패·모션 실패·정지 시나리오 기록은 [가상 셀 검증](../ws_cobot_pjt/docs/VIRTUAL_CELL_20260922.md)에 있다.
- 9/21에는 실제 준비 Action 응답의 접촉 9점과 `ESTIMATED` 측정 결과를 HMI API에서 읽기 전용으로 확인한 기록이 있다. 측정 정확도·절대 높이·실제 조각 성공은 그 기록으로 입증되지 않는다. [9/21 일지](../ws_cobot_pjt/docs/daily/2026-09-21.md)
- 9/22에는 REAL 실행 계약·HMI 연결과 가상 셀 시험이 main에 들어왔다. [9/22 일지](../ws_cobot_pjt/docs/daily/2026-09-22.md)
- 9/23 PR #74는 제어기 prefix 구성과 상태·하드웨어 관측 경로를 보완했다. 이를 포함한 `main`에서 실제 M0609 측정→BIND→경로→연속 조각, 물리적 홈 깊이·품질, 충돌 회피와 정지 시간을 끝까지 검증했다는 근거는 확인되지 않았다. [PR #74](https://github.com/suuuhululu/C-2/pull/74)
- 9/23 PR #75는 REAL 옆면 측정의 baseline 구간과 접촉 허용 구간을 분리하고, 복구 가능한 한 점 오류에 한해 정지 확인·검사된 후퇴 뒤 제한적으로 재측정하는 코드를 추가했다. 분리된 공중 이동의 IK 표본 간격도 설정 범위 안에서 조절한다. 해당 변경의 모의 시험 파일은 있으나 실제 M0609 측정 성능·간섭이 검증됐다는 뜻은 아니다. [PR #75](https://github.com/suuuhululu/C-2/pull/75)
- 9/23 PR #76은 HMI가 NumPy 실수형 관절값을 읽기 전용 관측으로 수용하도록 수정했고, PR #78은 REAL 경로 생성의 곡면 해칭과 배치 메타데이터를 확장했다. PR #79는 배포 프로파일 소비 시험을 보강했다.
- 9/23 PR #80은 현재/HOME에서 첫 APPROACH까지의 entry 후보 생성·읽기 전용 IK/관절·단순 원통 간격 검사·해시 고정·실행을 prepared 공정에 연결했다. 전체 메시 충돌 검사나 실제 M0609 감독하 진입 검증 완료를 뜻하지 않는다. [PR #80](https://github.com/suuuhululu/C-2/pull/80)
- PR #87·#88은 조각 후 실측 기하를 사용하는 검사된 HOME 복귀 계획을 prepared 성공 경로에 연결했다. PR #90은 HMI 단계 표시와 PRECHECK 중 준비 BIND 유지 조건을 최신 공정 순서에 맞췄다. 코드·단위시험 반영과 실제 M0609의 전체 HOME 복귀·정지 실기 검증은 구분한다.

실제 현장 실행을 판단할 때는 사용 PC의 두산 드라이버·ROS 도메인·설정 파일 버전, 로봇·공구의 실제 상태, 입력 자산과 경로·설정의 ID/해시, 공정의 최종 검사를 함께 확인한다. `ESTIMATED` 형상과 명시 waypoint의 IK 결과를 독립 정밀 측정이나 전 궤적 충돌 검사로 해석하지 않는다.

## 다음 확인 항목

1. 실제 실행 PC의 설치본과 이 `main`의 타입·노드·설정이 일치하는지 기록한다.
2. 준비 측정의 원본 접촉·실측 높이·스냅샷 신뢰도를 물리적 기준으로 재검증한다.
3. 동일 ID·해시의 최종 경로에 대해 로봇 상태, 접근·이탈, 관절·간섭·정지 동작을 현장에서 검증한다.
4. 작은 시험 조각의 깊이·선폭·오류·복구를 반복 측정하고 실행 커밋과 설정을 결과에 남긴다.

과거 서비스안, 날짜별 실험·이관·검증 기록은 당시 근거로 보존한다. 현재 구조를 이해할 때는 [프로젝트 README](../README.md)와 위 현재 문서부터 읽는다.

## 2026-09-23 REAL 첫 통합 완료 기록

[검증 기록](../ws_cobot_pjt/docs/validation/2026-09-23-first-real-integration.md): 측정→BIND→경로→PRECHECK→ENTRY→55구간 실행→FINISH 성공 원장 확보. 조각 형상 차이는 미해결이며 가공 품질 합격을 뜻하지 않는다. 로봇 없는 단위시험 샘플을 함께 제공한다.
