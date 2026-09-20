# c2_path · 좌표·경로 생성

`path_planner_node`는 HMI가 등록한 PNG/JPEG를 읽어 중심선 SVG → 2D 좌표 →
원통 3D 도구 끝 경로 → 기하 검증 산출물을 만드는 ROS 2 Jazzy Action 서버다.
이 패키지는 로봇·그리퍼·두산 API를 호출하지 않는다.

## 구현 구성

| 위치 | 담당 기능 |
| --- | --- |
| `c2_path/node.py` | `/c2/generate_path` Action 수신, 진행·결과·취소·중복/동시 요청 처리 |
| `c2_path/pipeline.py` | 계산 단계 조합, 입력/프로파일 검사, 일부 획 실패·빈 경로 차단, 산출물 확정 |
| `c2_path/artifacts.py` | HMI 관리 UUID→파일 해석·해시 검사, 산출물 묶음 원자적 등록 |
| `c2_path/image_to_svg.py` | PNG/JPEG → 중심선 SVG(Otsu·세선화·골격·Bézier) |
| `c2_path/extract_2d.py` | SVG → 2D 좌표(mm), 크기·배치·회전, 적응형 샘플링 |
| `c2_path/optimize_2d.py` | NN+2-opt 획 방문 순서 최적화(형상·진행 방향 보존) |
| `c2_path/map_3d.py` | 원통 해석 매핑, 이음매·180° 분할, 도구 자세 |
| `c2_path/generate_path.py` | 안전비용 정렬, offset-cylinder 이동, pose7 경로 구성 |
| `c2_path/validate_path.py` | 형식·표면·높이·간격·이음매·자세·빈 경로 검증 |
| `c2_path/workcell.py` | 현재 test_only 워크셀·도구 값 |

## 계약과 안전 범위

- Action: `/c2/generate_path`, `c2_interfaces/action/GeneratePath`, schema version 2.
- 출력 waypoint: `[x, y, z, qx, qy, qz, qw]`, `c2_base`, m,
  드릴 끝 기준 정규화 quaternion.
- 도구 자세: tool −Y=표면 안쪽, tool +Z=base −Z.
- 원통: 반지름 34.25 mm, 도안 u=0은 +X(0°), 이음매는 −X(±180°).
- CUT 잠정 허용각: −135°~135°. J5 정밀값은 아직 확정 전이다.
- `workcell.py`는 승인 REAL 설정 파일이 아니므로 노드는 `SIMULATION`만 허용한다.
- 성공 경로에도 `J6_RANGE`는 미검사로 남는다. 실행 전 공정팀의 전체 경로
  IK/J5/J6·충돌·보정 확인이 별도로 필요하다.
- 매핑 실패 획이 하나라도 있거나 CUT가 비면 전체 생성이 실패한다. 실패/취소 시
  `path_id/path_sha256`을 공개하지 않는다.

지원 입력 preset은 실제 PNG/JPEG 중심선 변환을 뜻하는
`raster_centerline_bezier` 하나다. 기존 HMI의 `simulation_centerline`은 고정 모의
샘플 이름이므로 실제 이미지 변환으로 묵시 해석하지 않는다.

## 관리 파일 연결

노드는 브라우저 경로나 임의 절대 경로를 Goal에서 받지 않는다. HMI의
`monitor_data/monitor.sqlite3`에 등록된 UUID와 `assets/<UUID>.bin`만 읽으며
바이트 SHA-256을 다시 확인한다. 산출물(path/SVG/preview/validation)도 같은
`assets` 테이블과 디렉터리에 한 묶음으로 등록한다.

현재 HMI의 `mock-profile/1`은 반지름·유효 높이·워크셀 버전이 이 패키지 값과
다르므로 노드가 `PROFILE_MISMATCH`로 거절하는 것이 정상이다. 통합 시험에는
`pipeline.matching_test_profile()`과 동일한 내용을 서버가 불변 프로파일로 등록해야
한다. REAL 프로파일로 사용하면 안 된다.

## 빌드·실행

저장소 루트 기준:

```bash
source /opt/ros/jazzy/setup.bash
cd ws_cobot_pjt/ws_cobot1
colcon build --packages-select c2_interfaces c2_path --symlink-install
source install/local_setup.bash

ros2 run c2_path path_planner_node --ros-args \
  -p managed_data_dir:=/절대/경로/ws_cobot_pjt/backend/monitor_data
```

`managed_data_dir`를 지정하지 않았거나 HMI 저장소가 초기화되지 않았으면 노드는
기동하되 Goal을 `NOT_READY`로 실패시킨다. 생성 제한 시간 기본값은 120초다.

순수 계산 시험:

```bashd
cd ws_cobot_pjt/ws_cobot1/src/c2_path
python3 -m unittest discover -s test -v
```

ROS 빌드 후 Action 서버/클라이언트 통합 시험은 별도로 수행한다. 노드가 생겼다는
사실만으로 HMI 전체 연동이 완료되는 것은 아니다. 백엔드 `RosBridge`의
`artifact_loader`, 실제 preset 허용, 이 test_only 프로파일 등록을 같은 계약으로
연결해야 한다.
