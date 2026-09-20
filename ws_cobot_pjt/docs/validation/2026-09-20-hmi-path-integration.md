# HMI ↔ c2_path 부분 통합 검증 · 2026-09-20

- 작성: Codex 실행 기록. 사람의 코드 승인·실기 확인은 별도다.
- 기준: main `72618aa4c966936f47a9d80f1f0d09146b7b2739`, [PR #38](https://github.com/suuuhululu/C-2/pull/38), 관련 Issue #35.
- 시험 코드: `feat/hmi-c2-path-integration` 작업 트리. 이 기록 시점에는 새 커밋·push·PR을 만들지 않았다.
- 수준: 구문/빌드, MOCK 회귀, 실제 ROS 2 Action/HTTP 통합, 브라우저 확인. 실기·가상 두산 제어기 시험은 하지 않았다.
- 환경: macOS arm64, 로컬 Miniforge `ros2_jazzy`, Python 3.12, backend venv(system-site-packages),
  Node 24.16, pnpm 11.19. 계산 의존성은 requirements-ros.txt.
- ROS: 동일 기준 소스의 c2_interfaces/c2_path를 `/private/tmp/c2-hmi-72618aa-ros`의 별도 build/install/log에 빌드했다.
  실제 Action 시험은 LOCALHOST/domain 174, 실행기·브라우저 시험은 domain 173, rmw_fastrtps_cpp.
- 조건: matching_test_profile의 SIMULATION/test_only, c2_base, 드릴 끝 m/quaternion xyzw.
  실제 로봇·제어기·그리퍼 연결 및 현장 보정값 검증은 없음. 공정 노드 미기동.

## 자동 시험

| 시나리오 | 실제 결과 | 판정·증거 |
| --- | --- | --- |
| 기존 MOCK의 업로드·생성·공정·실패 흐름 | 기존 21개 통과 | backend/tests/test_monitor.py |
| PR #38 원본 pipeline의 산출물 해석 | ID가 다른 논리 경로/파일 asset을 올바르게 연결, 파일을 수정하지 않음 | test_path_artifacts.py, 전체 15개 통과 |
| 결과 변조·누락·다른 요청·중복 논리 ID·저장 경로 이탈 | 파일 해시 및 의미 연결 검사로 거절 | 위 로더 시험 |
| 실제 HTTP 업로드→GeneratePath→등록→GET path | 검은 선 PNG, 3개 구간(APPROACH/CUT/RETRACT), 0.024 m, preview/파일 조회 200 | test_ros_path_integration.py |
| 같은 요청 재전송 / 같은 ID에 다른 입력 | 결과 재사용 / 409, path_versions 1건 | 위 실제 통합 시험 |
| 등록 후 파일과 DB hash를 함께 변경 | 등록 당시 hash와 달라 경로 조회 409 HASH_MISMATCH | 위 실제 통합 시험 |
| V=50의 범위 밖 배치 | FAILED/VALIDATION_FAILED, 새 경로 미등록 | 위 실제 통합 시험 |
| ROS에 MOCK preset 전달 | 422 UNSUPPORTED_FORMAT | 위 실제 통합 시험 |
| 경로 노드 종료 | ready=false, 새 생성 FAILED/NOT_READY | 위 실제 통합 시험 |
| test_only 결과의 공정 시작 시도 | 409 NOT_READY, runs 0건. ROS 실행 Action 호출 없음 | 위 실제 통합 시험 |
| Jazzy 타입·시각·품질 변환 | 9개 통과 | test_ros_contract.py |
| 원통 원점/U0 표시·구간 분리·mock 호환 | 3개 통과 | frontend/tests/preview.test.mjs |
| TypeScript 및 화면 배포 빌드 | pnpm build 성공, 1583개 모듈 변환 | frontend |

backend 전체는 **47 passed, skip 0**, 프런트엔드 표시 시험은 **3 passed**다.
저장소의 문서·구문 검사(109개 파일), Git hook 8개, Issue 설정 검사(네트워크·변경 없음),
Issue 관리 27개 시험 및 `git diff --check`도 통과했다.
ROS HTTP 통합 파일은 2개 시험 안에서 정상·실패·단절·실행 차단을 검증한다.
Starlette/AnyIO 및 ROS Lark의 폐기 예정 API 경고 3건이 있었으며 시험 실패는 아니다.

재현 명령은 [통합 안내](../HMI_PATH_INTEGRATION.md#재현-시험)를 따른다.
로컬 보관 로그: 프로젝트 작업 폴더의 `outputs/hmi_integration_2026-09-20/logs/backend-tests.txt`.
이 outputs 폴더는 저장소 밖 개인 검증 자료로 PR에 포함하지 않는다.

## 브라우저에서 확인한 결과

통합 실행기의 `--transport ros`로 c2_path·FastAPI·Vite를 실제 시작하고
http://127.0.0.1:5174/operator 에서 확인했다. PNG 업로드/생성 1회 성공,
배치 수정/재생성 1회 실패 시나리오를 수행했다. 성능·성공률 통계를 낸 시험은 아니다.

- 초기값 24×24 mm/U0/V107.5, 상단 **ROS 경로 노드 연결 / 공정 상태 미수신**.
- line.png(200×200)의 실제 중심선이 전개면·원기둥에 표시됨. 생성 결과 3구간,
  `기하 검사 통과 · 실기 미검증`, `미검사: J6_RANGE` 표시.
- 미리보기 확인을 체크해도 **시작 요청**과 공작물 고정 확인은 비활성.
- V를 50으로 바꾸면 이전 결과/재생성 필요 표시, 미리보기 확인 해제.
- 재생성 실패 시 제외된 획 오류·실패 검증 보고서·추출 SVG 링크 표시.
- 설정에서 `ROS2 / c2-path-preview/1 / raster_centerline_bezier` 표시, MOCK 시나리오 조작 없음.
- 시험 중 브라우저 error 로그 0건.

## 알려진 한계와 후속

- PR #38 node.py 종료부에서 SIGINT 때 `rclpy.shutdown()`의 이중 종료 RCLError가 관찰됐다.
  프로세스는 종료됐고 결과 계산·등록 성공과는 별개다. ROS 시험 fixture는 종료 exit code를
  성공 판정에 쓰지 않는다. 이번 HMI 변경에서 홍동님 노드 소스는 수정하지 않았다.
- 최초 ROS 시험 호출에서 bash setup을 zsh로 source해 typesupport 로딩에 실패했다.
  bash로 환경을 올바르게 불러온 후 전체 47개를 재실행해 통과했다. 소스 오류로 처리하지 않았다.
- 브라우저 초기 연결 시 개발 서버의 WebSocket 프록시에 EPIPE 로그 1건이 있었고 자동 재연결됐다.
  이후 업로드·생성·실패 보고서 표시를 완료했다. 마지막 Ctrl+C로 실행기와 자식 프로세스를 종료했다.
- Linux 실행 명령은 팀 Jazzy 빌드 구조에 맞춘 안내이며 이번 실측 실행 환경은 macOS다.
- test_only 프로파일 및 잠정 각도 범위는 실기 승인값이 아니다. J6/IK/충돌·보정·실제 공정 상태와 정지 검증은 별도다.
- 공통 Action/Message/Service 스키마·경로 계산·robot_adapter·그리퍼 동작은 변경하지 않았다.
- 되돌리기: `--transport mock`으로 기존 모의 흐름 사용. ROS 저장소는 별도 디렉터리에 보관한다.
  정상 종료 후 디렉터리 전체를 백업하며 원본/검증 산출물을 임의 덮어쓰지 않는다.
