# c2_path · 좌표·경로 생성

2026-09-21: [취소 가능한 계산 프로세스](../../../docs/HMI_GENERATION_CANCEL.md)을 지원한다. 기존 GeneratePath v2의 표준 취소를 사용하며 공통 ROS 타입 변경은 없다.

`path_planner_node`는 HMI가 등록한 PNG/JPEG를 읽어 중심선 또는 평행선 해칭 SVG → 2D 좌표 →
원통 3D 도구 끝 경로 → 기하 검증 산출물을 만드는 ROS 2 Jazzy Action 서버다.
이 패키지는 로봇·그리퍼·두산 API를 호출하지 않는다.

## 구현 구성

| 위치 | 담당 기능 |
| --- | --- |
| `c2_path/node.py` | `/c2/generate_path` Action 수신, 진행·결과·취소·중복/동시 요청 처리 |
| `c2_path/pipeline.py` | 계산 단계 조합, 입력/프로파일 검사(스냅샷 `/1`·`/2` 구분), 일부 획 실패·빈 경로 차단, 산출물 확정 |
| `c2_path/artifacts.py` | HMI 관리 UUID→파일 해석·해시 검사, 산출물 묶음 원자적 등록 |
| `c2_path/image_to_svg.py` | PNG/JPEG → 중심선 SVG(Otsu·세선화·골격·Bézier) |
| `c2_path/image_to_hatch.py` | PNG/JPEG의 검은 면 → 경계 보정된 단방향 평행선 해칭 SVG·픽셀 획 |
| `c2_path/extract_2d.py` | SVG → 2D 좌표(mm), 크기·배치·회전, 적응형 샘플링 |
| `c2_path/optimize_2d.py` | NN+2-opt 획 방문 순서 최적화(형상·진행 방향 보존) |
| `c2_path/map_3d.py` | 원통 해석 매핑, 이음매·180° 분할, 도구 자세 |
| `c2_path/generate_path.py` | 안전비용 정렬, offset-cylinder 이동, pose7 경로 구성 |
| `c2_path/validate_path.py` | 형식·표면(옆면 안)·간격·이음매·자세·빈 경로 검증 |
| `c2_path/readiness.py` | 로봇 잠정 작업 범위 사전 점검(`execution_readiness`). 생성 성공과 별개 |
| `c2_path/worker.py` | 취소·시간 초과 시 계산을 별도 프로세스로 종료·회수하는 실행기. 산출물 저장은 부모 프로세스만 한다 |
| `c2_path/ordering.py` | 획 순서 2-opt 공용 구현(비용 행렬 + 접두합). 글자 많은 이미지도 수 초 이내 |
| `c2_path/workcell.py` | 현재 test_only 워크셀·도구 값 |
| `c2_path/bundle.py` | 파일 묶음(폴더) 방식 입·출력: `manifest.json` 작성·검증, ROS 없이 `GeneratePipeline` 실행 (1차 통합 시험용) |
| `c2_path/snapshot.py` | 스냅샷 `surface` ↔ 공정 `workcell` 입력 연결·일치 검사, 실측 프로필 기하 필드의 구조 조건 |

## 계약과 안전 범위

- Action: `/c2/generate_path`, `c2_interfaces/action/GeneratePath`, schema version 2.
- 출력 waypoint: `[x, y, z, qx, qy, qz, qw]`, `c2_base`, m,
  드릴 끝 기준 정규화 quaternion.
- 도구 자세: tool −Y=표면 안쪽, tool +Z=base −Z.
- 원통: 반지름 34.25 mm, 도안 u=0은 +X(0°), 이음매는 −X(±180°).
- 도안은 원기둥 옆면 전체(둘레 360°, 높이 0~150mm)에 놓을 수 있고, 옆면 밖(높이 0 미만·150mm 초과)만 생성 실패다.
- 로봇 잠정 작업 범위(바닥 기준 높이 10~140mm(양초 150mm 기준 윗면 아래 10~140mm), 9/21 시율님 지시로 이전 85~130mm 에서 변경 / θ −135°~135° 원통 도달각 참고 범위, 9/20 J5 실측)는 생성 조건이 아니라 **실행 사전 점검**이다.
  범위 밖이어도 경로·미리보기는 만들어지며, 검증 보고서·미리보기의 `execution_readiness`(`WITHIN_LIMITS`/`OUT_OF_LIMITS`)로
  표시한다. **생성·검증·미리보기 성공은 실행 가능을 뜻하지 않는다** (`executability` 는 항상 `NOT_JUDGED`).
  ±135° 는 실제 J5 관절 판정이 아니다(`not_checked` 의 `J5_JOINT_LIMIT`). J5 정밀값은 아직 확정 전이다. 자세한 계약은 `BUNDLE_SPEC.md` 13절.
- 스냅샷 `contract`: `/1` 은 코드 상수와 정확히 같을 때만 받는다(`valid_v_range_mm=[10,140]`, 바닥 기준). `/2` 는 `surface.height_reference="bottom"`·`surface.v_direction="up"`·`calibration_status="SIMULATION_ONLY"` 가 필수이고 원통 치수(반지름·높이·축 원점)·작업 범위·도달각을 요청별 값으로 받아 그 값으로 경로를 계산한다(축 방향·u 원점·이음매는 아직 상수와 같아야 함). 자세한 표는 `BUNDLE_SPEC.md` 4.1절.
- `workcell.py`는 승인 REAL 설정 파일이 아니므로 노드는 기본으로 `SIMULATION`만 허용한다. 파라미터 `allow_real_preview:=true` 를 명시하면
  스냅샷 `/3`(REAL 추정값·**미리보기 전용**)과 함께인 REAL Goal 도 받지만, 그 경로도 `test_only` 라 실행할 수 없고 `executability` 는 `NOT_JUDGED` 로 남는다.
  REAL 을 SIMULATION 으로 바꿔 통과시키지 않는다. 필드와 조건은 `BUNDLE_SPEC.md` 14절(이름은 합의 전 제안).
- 실제 실행 후보는 `/3`을 승격하지 않고 별도 `c2-path-real-execution-profile/1` 계약으로 받는다.
  `allow_real_execution:=true`를 명시하고, 준비 BIND·`ABSOLUTE_GEOMETRY`·출처가 있는 접촉 오프셋·실행/관절/도구 확인 설정이
  같은 스냅샷에 있을 때만 `test_only=false`, `real_execution_allowed=true` 경로를 만든다. 잠정 작업 범위를 벗어나면
  경로는 진단용으로 남기되 `real_execution_allowed=false`다. `executability=NOT_JUDGED`는 계속 유지하며 공정팀이
  ExecuteProcess에서 최종 IK·관절·J6 검사를 통과한 경우에만 `execute_path()`로 넘긴다. 자세한 계약은 `BUNDLE_SPEC.md` 15절.
  `offset_status=ESTIMATED`, `validity=ESTIMATED`, `absolute_top_verified=false`는 실행 후보 생성의 일괄 거절 사유가 아니며
  상태·출처를 승격하지 않고 산출물에 그대로 보존한다.
- 성공 경로에도 `J6_RANGE`는 미검사로 남는다. 실행 전 공정팀의 전체 경로
  IK/J5/J6·충돌·보정 확인이 별도로 필요하다.
- 매핑 실패 획이 하나라도 있거나 CUT가 비면 전체 생성이 실패한다. 실패/취소 시
  `path_id/path_sha256`을 공개하지 않는다.

지원 입력 preset은 다음 두 개다.

- `raster_centerline_bezier`: 가는 선·윤곽을 중심선으로 변환한다.
- `raster_parallel_hatch`: 굵은 선·채워진 면을 단방향 평행선으로 변환한다. 모든 CUT 획의
  진행 방향을 유지하고 획마다 기존 APPROACH/RETRACT를 사용한다. 간격은 HMI 입력이 아니라
  코드의 SIMULATION/test_only 고정값 `0.8mm`(가정 홈 폭 `1.6mm`의 50%)다. 이 수치는 실측
  승인값이 아니며 실제 재료·깊이·공구로 홈 폭을 측정한 뒤 코드와 검증 근거를 함께 갱신해야 한다.

기존 HMI의 `simulation_centerline`은 고정 모의 샘플 이름이므로 실제 이미지 변환으로 묵시 해석하지 않는다.
해칭 preset도 별도 간격 값을 Goal/HMI에서 받지 않는다.

## 관리 파일 연결

노드는 브라우저 경로나 임의 절대 경로를 Goal에서 받지 않는다. HMI의
`monitor_data/monitor.sqlite3`에 등록된 UUID와 `assets/<UUID>.bin`만 읽으며
바이트 SHA-256을 다시 확인한다. 산출물(path/SVG/preview/validation)도 같은
`assets` 테이블과 디렉터리에 한 묶음으로 등록한다.

현재 HMI의 `mock-profile/1`은 반지름·유효 높이·워크셀 버전이 이 패키지 값과
다르므로 노드가 `PROFILE_MISMATCH`로 거절하는 것이 정상이다. 통합 시험에는
`pipeline.matching_test_profile()`과 동일한 내용을 서버가 불변 프로파일로 등록해야
한다. REAL 프로파일로 사용하면 안 된다.

## 파일 묶음 방식 (1차 통합 시험용, 제안)

PC 한 대 시험에서는 설정으로 지정한 공통 폴더의 파일 묶음으로 입력을 받고 결과를 내보낼 수 있다.
ROS 액션(위)과 **같은 `GeneratePipeline`** 을 쓰며 ROS·SQLite 없이 동작한다. 기존 ROS 연동을 대체하지 않는다.

```bash
cd ws_cobot_pjt/ws_cobot1/src/c2_path
python3 -m c2_path.bundle run --input <입력 묶음> --output <출력 묶음>   # 생성 실패여도 실패 결과 묶음을 남기고 종료코드 2
python3 -m c2_path.bundle verify <묶음>                                  # 파일·해시·참조 관계 검사
python3 build_bundle_samples.py                                          # samples/bundles/ 재생성
```

파일 묶음 시험 결과와 ROS 통신 시험 결과는 구분해서 기록한다. 스냅샷·`manifest.json` 형식과 담당별 미정 항목은
[`BUNDLE_SPEC.md`](BUNDLE_SPEC.md) 를 본다 (공통 규격으로 확정되기 전의 **제안**).

## 빌드·실행

저장소 루트 기준:

```bash
source /opt/ros/jazzy/setup.bash
cd ws_cobot_pjt/ws_cobot1
colcon build --packages-select c2_interfaces c2_path --symlink-install
source install/local_setup.bash

ros2 run c2_path path_planner_node --ros-args \
  -p managed_data_dir:=../backend/monitor_data    # 명령을 실행한 폴더(ws_cobot1) 기준 상대 경로
```

준비 BIND에 연결된 REAL 실행 후보 생성은 명시적으로 다음 파라미터를 추가한다. 이 노드는 경로만 만들며 로봇을 움직이지 않는다.

```bash
ros2 run c2_path path_planner_node --ros-args \
  -p managed_data_dir:=../backend/monitor_data \
  -p allow_real_execution:=true
```

`managed_data_dir`를 지정하지 않았거나 HMI 저장소가 초기화되지 않았으면 노드는
기동하되 Goal을 `NOT_READY`로 실패시킨다. 생성 제한 시간 기본값은 120초다.
파라미터 대신 환경 변수 `C2_MONITOR_DATA` 로도 지정할 수 있다.

## 경로 규칙 (PC 한 대 · 절대 경로 금지)

통합 시험과 최종 시연은 모두 PC 한 대에서 돌린다. 그래서 **코드와 데이터 파일에 절대 경로를 쓰지 않는다.**

- 코드에는 `/home/...`·`C:\...` 같은 고정 경로를 넣지 않는다. 폴더는 명령 인자(`--input`, `--output`), ROS 파라미터
  `managed_data_dir`, 환경 변수 `C2_MONITOR_DATA` 로 받고, 상대 경로는 **명령을 실행한 폴더 기준**으로 푼다.
  저장소 안의 파일(샘플·예제 등)은 소스 파일 위치(`__file__`)에서 상대적으로 찾는다.
- 요청·`manifest.json`·`result.json`·산출물 안에는 경로 문자열 대신 **UUID·해시·묶음 내부 상대 파일명**만 적는다.
- 이 규칙은 `test/test_no_absolute_paths.py` 가 소스와 샘플 묶음을 검사한다.

순수 계산 시험:

```bash
cd ws_cobot_pjt/ws_cobot1/src/c2_path
python3 -m unittest discover -s test -v
```

`test_loader_compat.py` 는 옆의 `c2_process`(`engraving.validate_path`, `joint_check.check_path_joints`, 모의 어댑터)가
있을 때만 실행되며, ROS·실제 로봇은 쓰지 않는다.

ROS 빌드 후 Action 서버/클라이언트 통합 시험은 별도로 수행한다. 노드가 생겼다는
사실만으로 HMI 전체 연동이 완료되는 것은 아니다. 백엔드 `RosBridge`의
`artifact_loader`, 실제 preset 허용, 이 test_only 프로파일 등록을 같은 계약으로
연결해야 한다.
