# HMI ↔ c2_path 부분 통합 · 2026-09-20

2026-09-21: 담당자 간 일반 파일 전달을 위한 [스냅샷·ZIP 교환 화면](HMI_FILE_INTEGRATION.md)을 추가했다.
아래 기존 ROS 공유 저장소 연결을 유지하며, 파일 교환 기능과 검증 범위를 구분한다.

기준은 main `72618aa4c966936f47a9d80f1f0d09146b7b2739`에 병합된
[홍동님 PR #38](https://github.com/suuuhululu/C-2/pull/38)이다.
`c2_interfaces` v2와 `c2_path`의 제출 계약을 유지하고 HMI의 파일 해석·입력·표시를 연결했다.
관련 Issue는 [#35](https://github.com/suuuhululu/C-2/issues/35)다.

## 연결 범위

```text
브라우저 HMI → HTTP/WebSocket → FastAPI / monitor_gateway_node
                                      ↓ rclpy / GeneratePath v2
                                 path_planner_node
                                      ↓
                     같은 PC의 monitor.sqlite3 + assets/<UUID>.bin
                                      ↓
                         HMI artifact_loader → 미리보기
```

`RosBridge`는 프로젝트의 Python ROS 2 클라이언트 이름이다.
`rosbridge_suite` WebSocket 서버(9090)에 브라우저가 직접 연결하는 구조가 아니다.
한 PC에 저장소와 환경을 한 번 준비하고 아래 통합 실행기로 HMI와 경로 노드를 함께 켠다.
이미지를 홍동님 PC나 소스 폴더로 옮기지 않는다. 공유 관리 저장소의 UUID·해시를 전달한다.

`SIMULATION`은 이 경로의 실기 사용이 승인되지 않았다는 뜻이다.
ROS 모드에서는 첨부 이미지를 실제로 계산한다. 고정 샘플 응답을 쓰는 MOCK과 구분한다.
공정 노드·실제 로봇·그리퍼는 시작하지 않으며 HMI와 API 모두 실행 요청을 차단한다.

## 제출 계약에 맞춘 내용

| 항목 | 적용한 계약과 처리 |
| --- | --- |
| Action | `/c2/generate_path`, `c2_interfaces/action/GeneratePath`, `schema_version=2` 그대로 |
| preset | ROS는 `raster_centerline_bezier`, MOCK은 `simulation_centerline`. 모드와 다르면 422 |
| 프로파일 | `c2_path.pipeline.matching_test_profile()` 반환값을 그대로 불변 등록. 별도 좌표 복제 없음 |
| 입력 | PNG/JPEG, 도안 중심 U/V·크기 mm·회전 deg. 중심선 종횡비를 유지해 요청 크기 안에 맞춤 |
| 초기 배치 | ROS 24×24 mm, U=0, V=유효 높이 범위 중앙(현재 107.5 mm), 회전 0° |
| 공유 저장소 | `monitor.sqlite3`의 `assets`와 `assets/<UUID>.bin`, 양쪽 프로세스가 같은 절대 디렉터리 사용 |
| path ID 해석 | 논리 `path_id`는 파일 UUID가 아님. assets metadata의 path_id/path_version으로 유일한 path asset 조회 |
| 파일 검증 | 경로·SVG·preview·report의 종류/MIME/크기/SHA-256, 요청·이미지·프로파일·경로 ID 연결 검사 |
| 보고서 | 합격·누락 획 없음·구간 수·절삭 길이 일치 확인. `not_checked`는 숨기지 않고 표시 |
| 등록 | 로더는 읽기만 수행. 검증 후 HMI `finish_generation`이 성공 결과와 path_versions를 같은 트랜잭션에 등록 |
| 미리보기 | `c2-path-preview/1`의 `segments`를 그대로 전달. CUT의 UV와 각 구간 points_m가 실행용 waypoint에 대응하는지 검사 |
| 표시 좌표 | `c2_base` 절대 좌표에서 profile 원통 원점을 빼고 U=0(+X)을 앞면으로 표시. 로봇 TCP 변환·파일 수정 없음 |
| 분리 구간 | `connect_to_next=false`, split 메타데이터 보존. 전개면은 CUT, 원기둥은 CUT와 비절삭 점선을 각각 표시 |
| 연결 표시 | Action 서버 준비와 `/c2/process_state` 신선도를 별도 표시. 공정 상태가 없어도 경로 생성 가능 |
| 실행 제한 | 현재 ROS 산출물은 `test_only=true`, J6_RANGE 미검사. 시작 버튼 비활성, POST runs는 NOT_READY |

원본 비교·편집 중 미리보기는 배치 참고용이다. 입력 변경 시 확인을 해제하며 다시 생성한
산출물만 검증 완료로 표시한다. 화면은 새 경로를 계산하거나 도구 자세를 생성하지 않는다.
등록 이후 결과 조회에서도 등록 당시 파일 해시를 다시 확인한다.
기존 MOCK API·공정 시험을 유지하며 공통 ROS 타입 및 SQLite 스키마는 바꾸지 않았다.

HTTP snapshot에는 `path_generation`(preset, preview_contract, ready, execution_enabled,
execution_block_reason, default_placement)을 추가했다. 경로 조회는 원본 preview와 함께
`profile_snapshot`, `test_only`, `validation_not_checked`를 반환한다. 화면·서버는 함께 배포한다.

## 한 PC에서 준비·실행

아래 예시는 ROS 2 Jazzy가 설치된 Linux의 **bash** 기준이다. macOS 검증 환경은
[검증 기록](validation/2026-09-20-hmi-path-integration.md)에 구분했다.
ROS Python과 backend 가상환경의 Python 버전/ABI가 같아야 한다. 기존 MOCK 전용
가상환경에서 rclpy를 읽을 수 없다면 기존 환경을 보관하고 ROS Python으로 다시 준비한다.

```bash
# 저장소 루트, Jazzy 설치·colcon 준비 후
source /opt/ros/jazzy/setup.bash
cd ws_cobot_pjt/ws_cobot1
colcon build --packages-select c2_interfaces c2_path --symlink-install
source install/local_setup.bash
cd ../backend
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-ros.txt
cd ../frontend
pnpm install --frozen-lockfile
cd ../..
python3 ws_cobot_pjt/run_monitor.py --transport ros
```

새 터미널마다 Jazzy와 `ws_cobot_pjt/ws_cobot1/install/local_setup.bash`를 source한다.
zsh에서는 대응하는 `.zsh` 파일을 사용하거나 bash 터미널에서 위 명령을 실행한다.
`requirements-ros.txt`는 시험한 추가 직접 의존성(scikit-image/networkx)을 고정하며
rclpy나 c2_interfaces를 pip로 임의 대체하지 않는다. Node.js 22 이상/pnpm 11을 사용한다.

- 화면: http://127.0.0.1:5174/operator
- API: http://127.0.0.1:8010/docs
- 기본 ROS 저장소: `ws_cobot_pjt/backend/monitor_data/ros_path` (MOCK 저장소와 분리).
- `C2_MONITOR_DATA=/절대/경로`로 지정하면 양쪽에 같은 값이 전달된다.
- 실행기가 저장소를 **먼저 초기화**한 뒤 경로 노드·서버·화면을 시작한다.
- 기본 ROS domain 173, `LOCALHOST`, 정적 피어 없음, `rmw_fastrtps_cpp`. `--ros-domain-id`로 시험 domain 지정 가능.
- `--external-path-node`는 경로 노드를 직접 띄우는 경우만 사용한다. 이때 같은 domain/RMW/저장소,
  저장소 초기화 후 노드 시작 순서를 직접 맞춰야 한다. 노드를 잘못된 저장소로 먼저 켰다면 재시작한다.
- 종료는 Ctrl+C. 현재 PR #38 노드에는 SIGINT 종료 중 rclpy 이중 shutdown 오류가 관찰됐다.
  계산/파일 등록 성공과 별개인 종료 문제이며 아래 검증 기록에 남겼다.
- `--transport mock` 또는 옵션 없는 기본 실행은 기존 MOCK 화면이다. REAL 모드는 지원하지 않는다.

## 화면에서 시험하기

1. 상단에 **ROS 경로 노드 연결**이 보이는지 확인한다. **공정 상태 미수신**은 현재 부분 통합에서 예상된 상태다.
2. 흰 바탕의 단순 검은 선 PNG를 첨부하고 초기 배치 24×24 mm/U0/V107.5로 생성한다.
3. 전개면과 원기둥에 같은 중심선이 보이는지, 원본·SVG·경로·보고서의 요청이 같은지 확인한다.
4. `기하 검사 통과 · 실기 미검증`, `미검사: J6_RANGE`를 확인한다. 미리보기 확인을 체크해도 시작은 비활성이다.
5. V=50으로 변경해 재생성하면 유효 높이 밖 오류가 나고 새 경로가 등록되지 않아야 한다.
   실패 보고서와 추출 SVG 링크로 원인을 확인한다.
6. 경로 노드를 종료하면 연결 상태와 생성 버튼이 비활성으로 바뀌어야 한다.

## 재현 시험

```bash
# 위와 같이 Jazzy와 빌드 overlay를 source한 backend 디렉터리
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 C2_RUN_ROS_TESTS=1 \
  .venv/bin/python -m pytest -q tests

# frontend 디렉터리 (이 단위 시험은 Node 24에서 확인)
node --experimental-strip-types --test tests/preview.test.mjs
pnpm build
```

통합 시험은 임시 DB·LOCALHOST domain 174를 사용하며 c2_path만 별도 프로세스로 시작한다.
ROS가 없거나 활성화 변수가 없으면 실제 ROS 시험이 skip된다. 로더 시험도 c2_path 계산
의존성이 없으면 skip되므로 **skip을 통합 성공으로 기록하지 않는다.**

## 후속 협의

홍동님께 기존 산출물을 다른 이름으로 다시 전송하거나 로더 코드를 제공해 달라고 할 필요는 없다.
현재 제출된 preset/프로파일/파일/preview 계약으로 HMI 연결이 가능하다.
향후 프로파일 및 산출물 형식 변경 시 HMI와 함께 검토하고 버전을 관리한다.
실기 통합에는 승인된 보정 스냅샷, 전체 경로 IK/J5/J6·충돌 검증, 공정 노드와 상태/정지 계약
시험이 별도로 필요하다. 이번 경로 성공 결과가 그 검증을 대신하지 않는다.
