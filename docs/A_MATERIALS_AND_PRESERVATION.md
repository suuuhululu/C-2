# A 자료 분류·출처·보존 안내

기준 커밋: `1b8204050521303f18c5538ec1cc392b447e522f` (integration-round1, 2026-10-12).
현재 실행은 [A README](../planning_trial/README.md), 실제 재현은 [검증 기록](A_DOCUMENTATION_VERIFICATION_20261012.md)을 따른다.
이 작업은 문서와 목록만 정리한다. 기존 코드·Fixture·모델·실측 파일의 위치와 바이트, Git 이력은 유지한다.

## 네 종류의 분류

| 분류 | 위치·역할 | 유지·보존 방법 |
| --- | --- | --- |
| CURRENT_CODE | `planning_trial` 계산·adapter·계약·profile·CLI, `isaac_sim/scripts` 및 프로젝트 ROS 연결 코드 | 현재 코드의 사용처를 기록. 기본 Planner/확장 API/SIM 연결은 동일한 A 계산을 사용 |
| EXAMPLES_TESTS | 입력 JSON, test/check 실행 도구, SIM 설정·템플릿, 계약 요청 예제 | 현재 코드용·기능 정렬 대기 입력을 구분. 예제는 실제 관측·장치 상태가 아님 |
| EXTERNAL_MEASURED | 원본/변환 모델·라이선스, 측정·명목 치수·물성 참고·좌표 분석 | 외부 출처, 변경, 측정 조건, 단위, 적용 한계와 현재 사용처를 기록 |
| HISTORICAL | `fixtures/original_a`, `review`, 저장된 Plan/Replan 출력, 과거 API 설명·정책/시험 기록 | 보존 목적과 기준 커밋 명시. 새 Planner로 개발하거나 현재 성공 증거로 사용하지 않음 |

파일별 분류·크기·SHA256·보존 경로는 [manifest](A_PRESERVATION_MANIFEST_20261012.json)에 있다.
범위는 기준 커밋에서 Git이 추적하는 `planning_trial/**`, `isaac_sim/**`, A 계획 정책 문서다.
동일 파일이 예제이면서 실행 중 읽히기도 하므로 category만으로 제거 가능 여부를 판단하지 않는다.
`runtime_use`와 `source_record`를 함께 본다. 목록에 없는 B/C/D 원자료를 이 작업으로 정리하지 않는다.

## 현재 직접 사용하는 원본과 설정

- `assembly_contract.py`는 `connection_contract_review_20261008_v4/schema.json`을 읽어 현재 계약을 구성한다. 이름이 오래됐어도 실행 필수다.
- `assembly_api_fixtures.py`는 같은 폴더의 `01_whole.request.json`을 seed로 사용한다. Fixture·현재 schema 변경·원본 보존을 구분한다.
- `supply_pick.load_supply_profile`은 measurements의 공급판 모서리·배치·첫 파지·닫힌 팁·받침대 파지·파지 깊이·블록 치수·ABS 참고 자료 8파일을 읽는다.
- `assembly_target.load_assembly_target_profile`은 handoffs의 `points.json / position_analysis.json / sequence_plan.json`과 치수·물성 자료를 읽는다.
- `supply_pick_candidates.user_20261007.json`은 과거 계산 후보이며 회귀 시험이 읽는다. 측정 원본과 다르다.
- `fixtures/source/01_initial`의 motion·reassessment 요청은 SIM 호출 템플릿이다. 입력 버전/연결부 정렬은 별도 기능 작업이다.
- 원본 보존 SHA 목록 `isaac_sim/fixtures/protected_sources.json`은 test_portability 및 저장 실행 검사에서 사용한다.

## 외부 원본·프로젝트 변환 모델

| 위치 | 출처·변환과 현재 사용처 | 보존 상태 |
| --- | --- | --- |
| `isaac_sim/assets/original_robot` | Doosan M0609 DAE, OnRobot RG2 STL, 결합 URDF와 license/package.xml. 독립 FCL 충돌 검사 `route_collision.py`에서 읽음 | GitHub 동일 경로 유지 |
| `isaac_sim/assets/isaac_robot`, `aligned_robot.sim.usda` | Isaac 가져오기/정렬로 생성한 USD·payload. 외부 원본과 프로젝트 변환을 포함하며 `sim_host.py`에서 사용 | 동일 경로 유지; 바이너리 USD를 설치 환경으로 오인하지 않음 |
| `isaac_sim/ros_ws/src/m0609_rg2_sim_model` | 프로젝트용 변환 URDF/STL/SRDF·설정·CMake. MoveIt 패키지와 prepare_config에서 사용 | 동일 경로와 라이선스 유지 |

[원본 source_manifest](../isaac_sim/assets/original_robot/source_manifest.json)에 Doosan 기준 commit
`4d5657f36a160eedb533ab1c975cd8a30c3e53b2`, 원래 PC source 경로, mesh SHA, xacro 확장·상대 경로·world joint 변경이 기록돼 있다.
이 기록은 원자료이며 그 안의 `assets/robot` 경로는 현재 이관된 `assets/original_robot` 경로와 다르다.
OnRobot 기준 commit·전체 설치 절차는 그 기록만으로 확정할 수 없다. 출처/해시를 보존하되 임의 버전을 채우지 않는다.
모델과 드라이버는 구분한다. 이 모델을 받았다는 사실만으로 REAL FollowJointTrajectory 서버나 실제 로드된 DRCF 환경이 확인되지 않는다.
라이선스의 법적 해석이나 재배포 승인 여부를 이번 정리 결과로 확정하지 않는다.

## 실측 원본·명목값·분석 결과

| 자료 | 의미·사용 조건 |
| --- | --- |
| 공급판 corners, first_supply_grasp, closed_tip_reference, pedestal_grasp | 사용자 보고 원본 TCP/관절/자세. 해당 측정 당시 배치·TCP·단위·파지 조건을 함께 유지. 과거 8mm 파지 보고와 현재 선택한 5mm 정책은 구분 |
| supply_layout, supply_grasp_depth_policy | 사용자 배치/파지 정책. 레이아웃 가정과 실기 보정 완료는 다름 |
| block_geometry.user_20261008.rev2.json | 사용자 제공 body19mm·stud4.5mm·pitch16mm·pre-contact bottom gap20mm 기준. 소켓·실제 체결 물리 검증 완료가 아님 |
| abs_reference_properties.user_20261008.json | ABS 제품 물성 참고값. 실제 사용 블록의 밀도·탄성·마찰·체결력 실측값이 아님 |
| handoffs/data/points.json | 사용자 taught seated TCP 원본, Base mm / ZYZ degree. 설정 TCP와 파지 상태를 함께 확인 |
| handoffs/data/position_analysis.json, sequence_plan.json, generated/sim_targets.json | 원본 좌표의 분석·계획·생성 결과. 모두 실측 원본이라고 표시하지 않음 |
| supply_pick_candidates.user_20261007.json | 과거 공급 좌표 계산 후보; 현장 실행 승인값이 아님 |

GripperDA_v4 flange offset228mm, 공급 파지5mm와 pre-contact bottom 간격20mm는 각 기준의 의미가 다르다.
공급판 모서리 원본 Z는 접촉 TCP 기록이며 그대로 물리 표면 Z라고 해석하지 않는다.
보정·피팅·명목 확장·실제 표면 확인을 구분하며 측정 JSON의 과거 설명을 최신 결정에 맞춰 덮어쓰지 않는다.
현장 공급 슬롯 수정은 이번 정리에서 수행하지 않는다.

## 과거 보존 자료와 찾는 방법

- `isaac_sim/fixtures/original_a`: 과거 A 49파일의 frozen 사본. 현재 실행은 저장소 루트의 planning_trial을 사용하며 사본은 무결성·출처 기록용이다.
- `isaac_sim/review`: 이관 당시 파일 목록·path diff·원격 기준·preservation 보고서 6파일. 최신 구현/이번 재현 결과를 대신하지 않는다.
- `planning_trial/sample_plan.json / sample_replan.json`: 과거 계산 출력 예시. 새 실행은 reports 아래에 결과를 생성하여 원본을 덮어쓰지 않는다.
- `docs/A_ORDER_SEARCH_POLICY_20261012.md`: 기존 기능 정책·시험 결과. 이 문서는 원본 그대로 유지하며 날짜가 다른 수치를 이번 시험 수치로 합산하지 않는다.
- [이전 A README 원문](A_README_HISTORY_1b820405.txt): 기준 커밋의 457줄을 바이트 그대로 보존. 원문 상대 링크는 원래 planning_trial/README.md 위치 기준이다. [기준 원문](https://github.com/suuuhululu/C-2/blob/1b8204050521303f18c5538ec1cc392b447e522f/planning_trial/README.md)에서도 찾을 수 있다.
- 이전 실패·음성·DB·ROS·Isaac 실행 기록은 해당 담당 문서/원본 commit에서 보존하며 여기서 성공으로 재해석하지 않는다.

외부 자료의 Release 이동이나 폴더 재배치는 이번 작업에 포함하지 않는다. 선택 후 진행할 경우 먼저 GitHub 보존 위치·기준 commit·파일 목록·해시를 기록하고, 보존본을 실제 받아 일치 여부와 현재 사용처를 검증한 뒤 별도 PR에서 실행 경로를 변경한다. CPU/GPU 로컬 백업만으로 GitHub 보존을 완료했다고 표시하지 않는다.

## 별도 기능 작업

`eb78ad7`의 Isaac0.5→0.5.1 및 최신 SIM 요청/검사 정렬은 미게시된 별도 기능 변경이다.
이번 branch에는 해당 계산/시나리오 변경을 포함하지 않는다. 기준 1b820405의 SIM 계약 문제를 문서에 표시한다.
실제 B/D 수신·자동 승인·MoveIt 전체 궤적 실행·정지/파지/Contact 인계·Isaac 물리·실물 체결은 별도 검증이다.
