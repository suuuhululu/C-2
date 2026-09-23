# REAL 통합 실행 테스트 준비 · 2026-09-23

## 소스 기준

- main `8409fc6` + `feat/engraving-force-hold-return-home`의 `c64fc6de916eb869f724f9f381591370c908b64c` + 8점 seed/실행 표면 갱신.
- PR #82는 2026-09-23 15:35:48 KST에 위 조각 브랜치로 병합됐다. main 병합이 아니다. #73은 조회 시점 미병합이다.
- 로컬 브랜치: `codex/real-integration-ready-20260923`, worktree `.worktrees/real-integration-ready`. 커밋하지 않은 로컬 merge 준비 상태다. main과 기존 설정 작업 폴더는 보존했다.
- 충돌 6개를 대조했다. 측정 어댑터·보정·두 측정 시험·설정은 담당자의 baseline/복구 정책을 적용하고, README는 main ENTRY 설명과 최신 조각 함수 설명을 함께 유지했다. main의 ENTRY 정책·HMI 연결·공통 타입은 보존한다.

## 사용할 설정

같은 worktree의 `ws_cobot_pjt/ws_cobot1/src/c2_process/config/` 아래 두 파일:

- `workpiece_real_trial_0921.json`: 담당자 baseline/복구/비접촉 정책과 8점 seed 및 top XY 갱신.
- `real_execution_profile_20260923.json`: 8점 기하, fixed_depth 0.5 mm, CUT 5 mm/s, 기존 상대 ENTRY 정책.

side_search=10 mm, baseline lead-in=4.05 mm, start_gap=5 mm, inside_limit=5 mm, 이동 복구 최초 포함 3회, noncontact_hard_force_n=15 N. 프로파일 hard_force_n 및 조각 timeout을 올리지 않았다. 기존 HOME와 trial_scene 경계 유지.

[초기 8점 갱신 기록](2026-09-23-eight-point-config.md)의 '담당자 코드 확보 대기'는 이번 로컬 통합에서 해소됐다. 원본 시험 당시와 달라진 seed/top XY, Action 경로의 실기 검증은 여전히 별도다.

## 수행한 검사

| 검사 | 결과 |
| --- | --- |
| 공정 모의/계산 + 백엔드 REAL 설정/HMI 시험 | 1,118 passed, 2 skipped, 39.44 s |
| 새 Jazzy 설치 overlay로 생성 타입 교환·REAL HMI 시험 추가 | 30 passed |
| c2_interfaces/c2_path/c2_process 빌드 | 3 packages finished, 13.3 s |
| TypeScript/Vite production 빌드 | 성공 |
| 저장소 검사 | 249개 추적 파일 텍스트·구문·상대 링크 통과 |
| hook / Issue 로컬 시험 | 8 / 27 통과, 설정 검사 정상 |
| diff / cached diff 공백 검사 | 통과 |
| HMI HTTP snapshot / 공정 DDS 수신 | REAL/ROS2, connection=CONNECTED, state=IDLE |
| ROS 노드 | monitor_gateway_node, path_planner_node, process_controller_node |
| Action | prepare_workpiece, generate_path, execute_process 발견 |
| 물리 로봇 연결·모션 | 미수행, hardware UNKNOWN |

모의 시험에서 ROS 서버 시험 파일 3개는 제외했다. 표의 추가 생성 타입 시험은 새 설치본으로 수행했지만 실물 통신 시험은 아니다. Starlette/AnyIO deprecation 경고가 1건 있다.

pnpm wrapper는 공유 node_modules symlink를 교체하려다가 자체 보호로 중단했다. 기존 모듈을 삭제하지 않고 설치된 `typescript/bin/tsc -b`와 `vite/bin/vite.js build`를 직접 실행해 성공했다. 실행 Python은 ROS 환경을 source한 backend venv를 사용한다(시스템 Python에는 skimage가 없어 계산 노드에 사용하지 않음).

## 현재 기동 상태 및 시작 방법

이 PC의 실행 파일은 저장소 루트 `output/real-integration-ready-20260923/`에 준비했다. 환경은 `env.sh`, HMI는 `start_hmi.sh`, 공정은 `start_process.sh`이다. 두 시작 스크립트는 이미 실행 중이면 중복 실행하지 않는다.

- HMI: http://127.0.0.1:5174/operator
- API: http://127.0.0.1:8010
- ROS domain 20 / LOCALHOST / rmw_fastrtps_cpp
- controller prefix `/dsr01/dsr_controller2`
- 작업 데이터: 이 worktree의 `ws_cobot_pjt/backend/monitor_data/real_integration_20260923`
- 준비·실행 SQLite 원장: 같은 데이터 폴더의 `process_journals/`

HMI·경로 노드·REAL 공정 노드를 대기 상태로 기동하고 확인했다. MEASURE/Execute/Stop/그리퍼 명령은 보내지 않았다. 연결 표시 CONNECTED는 HMI↔공정 통신이며 물리 로봇의 연결 완료가 아니다.

두산 드라이버 프로세스/노드는 현재 확인되지 않았다. ROS service list에는 클라이언트가 사용하는 이름도 나오므로 `/dsr01/...` 이름만으로 공급자 서버가 켜졌다고 판단하지 않는다. 현장 확인된 M0609 REAL 드라이버를 같은 domain 20 / LOCALHOST로 기동한 후 HMI의 하드웨어 재조회를 통해 AUTO/REAL·STANDBY·제어권·TCP/하중을 확인해야 한다. 확인되지 않은 IP나 그리퍼 초기화 launch를 생성·실행하지 않았다.

외부 공급자 source는 `4d5657f36a160eedb533ab1c975cd8a30c3e53b2`이고 로컬 수정이 있다. 팀이 추적하는 제어권 패치 4개는 main과 바이트 일치한다. 별도 로컬 수정은 보존했고 이번에 드라이버를 재빌드하지 않았다. 설치 바이너리의 해당 패치 반영 여부는 실제 제어권 토픽 관측으로 확인할 항목이다.

## 실행 테스트 순서

1. 현장 로봇/드라이버와 HMI의 하드웨어 상태를 확인한다. 준비 화면에서 고정 장착·드릴 OFF 등 실제 확인을 입력한다.
2. MEASURE로 새 8점 결과와 HOME 복귀를 확인한다. 이번 자료를 원본으로 주입해 새 측정을 생략하지 않는다.
3. BIND 성공 뒤 이미지로 경로를 생성하고 미리보기를 확인한다.
4. 별도 실행 요청으로 PRECHECK→ENTRY→ENGRAVE 결과를 확인한다. 마지막 RETRACT 이후 자동 HOME 복귀는 prepared 경로에 연결되어 있지 않다.
5. 실행 ID·설정/경로 해시·측정/공정 결과를 같은 DB/로그로 보존한다. 물리적 깊이·가공 품질은 별도 기록한다.

현재 trial_scene Z 하한은 190 mm다. 경로 surface의 허용 v 범위 전체가 조각 ENTRY 허용 범위라는 뜻은 아니다. 첫 시험의 배치는 이 제한과 실제 IK 결과로 판단하며 범위·힘 제한을 자동 완화하지 않는다. 기존 검토에서 확인한 ENTRY 검사/실행 중간 궤적 차이에 관한 코드 수정은 이번 준비 작업에 포함하지 않았다.

## 작업셀 버전 불일치 수정

- 새 측정을 위한 실행 프로파일의 `workcell_version`을 현재 경로 소비자 기준 `1`로 정렬했다. `schema_version=2`와 측정·모션 설정은 유지한다.
- HMI 정적 설정 검사에서 c2_path의 공통 식별 검사를 호출한다. 완성된 REAL 스냅샷은 경로 소비자의 전체 검사 통과 후에만 BIND한다.
- 검증 불가한 측정 확인값은 템플릿으로 채우지 않고 BIND 전에 거부한다. 저장된 원본은 보존된다.
- 기존 BIND 교체나 재사용 기능은 추가하지 않았다. 사용자는 새 측정으로 진행한다. 실행 중 노드는 에이전트가 재시작하지 않는다.
- 적용: 사용자 관리 HMI 터미널을 종료한 뒤 기존 `start_hmi.sh`로 다시 기동한다. 이 스크립트가 HMI와 경로 노드를 함께 기동한다. 기존 스냅샷은 변경되지 않으며 새 측정 요청으로 새 설정을 반영한다.
- 배포 JSON→모의 측정 결과 결합→경로 검사 및 관련 시험 129개 통과. 실기 재측정·조각 검증을 의미하지 않는다.
- 추가 검증: backend 전체 242 passed / 6 skipped, c2_path·c2_process Jazzy 빌드 성공, 저장소 구문·문서 링크 검사 및 git diff --check 통과. 커밋·push 및 사용자 노드 재시작은 수행하지 않았다.

## 조각용 작업영역 분리

사용자 지정: c2_base 도구 끝 waypoint Z ≥ 0.05 m, 별도 XY 경계/Z 상한 없음.
ENTRY의 `_geometry_check`에서 측정용 TCP 박스 적용을 제거하고 독립 조각 작업영역 검사를 연결했다.
공정 실행 전에는 본경로와 오프셋 적용 실행 계획에도 같은 하한을 검사한다.
측정 trial_scene, 양초 간격, IK/관절 검사는 유지한다. 공통 ROS 타입 변경은 없다.
새 실행 프로파일에 명시하고 HMI가 불변 스냅샷에 연결한다. 기존 필드 누락 시 동일 하한으로 호환한다.
실행 중 노드 재시작·측정·조각 모션은 수행하지 않았다.
검증 결과: 공정 비실기 시험 + HMI 설정/스냅샷 시험 1139 passed, 2 skipped.
ROS 서버 시험 3개 파일은 실기 연결 없이 검증하기 위해 제외했다.
0.05 m 경계 허용/미만 거부, ENTRY 중간 샘플 거부, 측정 TCP 박스 분리,
도구 끝/TCP 좌표 구분, 모든 조각 구간 하한, 양초 간격 검사 유지 시험을 포함한다.
Jazzy c2_path·c2_process 빌드 및 저장소 검사·git diff --check 통과.
추가된 전체 프로파일 검증에 맞춰 기존 모의 measurement_record ID 1곳을 UUID로 정정했다.
적용은 사용자가 대기 상태에서 HMI·공정 노드를 종료/재기동한 뒤 새 측정·새 경로 생성으로 진행한다.
커밋·push 없음.
