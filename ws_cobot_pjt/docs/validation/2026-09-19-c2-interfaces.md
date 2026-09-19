# 공통 인터페이스 v1 빌드·타입 변환 검증

- 시험명 / 작성자 / 확인자 / 날짜: c2_interfaces 초안, Codex(사용자 요청으로 작성), 사람 검토 대기, 2026-09-19.
- 기준 / 시험한 코드: main `42e84160edc1a6ae4b0790bab4d21cbd66cce57b`에서 분리한 `codex/c2-interfaces-v1`. 이 기록을 추가한 커밋의 타입·게이트웨이 코드를 시험했다. PR에는 해당 커밋과 원격 검사 결과를 연결한다.
- 시험 수준: 문서·구문, ROS 패키지 빌드, 생성 타입 직렬화, 게이트웨이 변환, HMI 모의 회귀. 실제 ROS 상대 노드 통합·실기 시험은 미수행.
- 환경: 편집 PC Ubuntu 24.04 계열, Python 3.12.3, ROS 2 Jazzy, rclpy 7.1.12, rosidl-parser 4.6.9. 생성 타입 시험은 시스템 Python/pytest 7.4.4, HMI 회귀는 기존 backend 가상환경을 사용했다.
- 빌드 위치: 별도 worktree `/tmp/c2-interfaces-v1-20260919/ws_cobot_pjt/ws_cobot1`. 원래 체크아웃과 ws_dsr의 산출물을 사용하거나 변경하지 않았다.
- 공작물·지그·TCP·하중·현장 조건: 적용 없음. 시험 수치는 직렬화 확인용 가짜 값이다. 제어기·그리퍼 연결과 모션 명령은 실행하지 않았다.

| 시나리오 | 기대 결과 | 실제 결과 | 판정 | 증거 |
| --- | --- | --- | --- | --- |
| Jazzy 공통 타입 빌드 | Action 2개·Service 1개·Message 2개 생성 | c2_interfaces 패키지 빌드 성공 | 통과 | `colcon build --packages-select c2_interfaces --symlink-install` |
| 생성 타입 왕복 직렬화 | 한글, ID, 해시, 경로 버전·구간, 시각·단위 보존 | 11개 pytest 통과 | 통과 | [타입 시험](../../ws_cobot1/src/c2_interfaces/test/test_generated_contract.py) |
| 빈 메시지 | 성공·고정 확인·정지 접수 false, 상태·품질 UNKNOWN | 기본 생성자 확인 | 통과 | 위 시험의 기본값 사례 |
| 게이트웨이 Goal 매핑 | 기존 HTTP 필드와 ROS 필드 일치, 미등록 필드 거절 | GeneratePath·ExecuteProcess·StopProcess 확인 | 통과 | [변환 시험](../../backend/tests/test_ros_contract.py) |
| 시각·품질 변환 | RFC3339 시간대·나노초 보존, 미확인·오래된 신호를 정상 수치로 표시하지 않음 | UTC 변환·JSON null·프레임·측정 시각 보존. 시간대 없는 입력 거절 | 통과 | 변환 시험 8개 통과 |
| HMI 회귀 | 임시 DB·가짜 상대의 정상/실패·중복·정지·복구 동작 유지 | 기존 15개 + 변환 8개 = 23개 통과 | 통과 | backend pytest 전체 |
| 저장소 기본 검사 | 문서 링크·구문·충돌 표시·공백·hook·팀 설정 정상 | 아래 명령 결과 기록 | 통과 | 저장소 검사 및 GitHub Repository checks |
| 실제 좌표·공정 상대와 ROS 통신 | Goal/Feedback/Result·상태·정지의 실제 상호 운용 | 상대 노드·artifact_loader 미구현으로 미수행 | 미수행 | 후속 담당자 연동 |
| 실기 파지·조각·청소·정지·품질 판정 | 현장 조건에 따른 실제 성공 확인 | 연결·명령 없음 | 미수행 | 별도 실기 계획 필요 |

## 재현 명령과 결과

저장소 루트에서:

```bash
source /opt/ros/jazzy/setup.bash
cd ws_cobot_pjt/ws_cobot1
colcon build --packages-select c2_interfaces --symlink-install
source install/local_setup.bash
colcon test --packages-select c2_interfaces --event-handlers console_direct+
colcon test-result --verbose
```

빌드 1개 성공. pytest 11개 성공. `colcon test-result`는 이 pytest 11개에 CTest 실행 단위 1개를 더해 `12 tests, 0 errors, 0 failures, 0 skipped`로 집계한다. 서로 다른 시험 12개를 작성했다는 뜻은 아니다.

Jazzy와 위 워크스페이스를 source한 터미널에서 backend로 이동하여:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

23개 통과. Starlette/AnyIO의 기존 BlockingPortal 폐기 예정 경고 1개가 있었다. 제한된 실행 환경에서는 비동기 TestClient 시험이 진행되지 않아 중단하고, 같은 명령을 제한 밖에서 다시 수행해 11.30초에 통과했다. ROS 상대나 로봇을 시작하지 않았다.

저장소 루트 검사:

```bash
python3 tools/check_repository.py
python3 tools/test_git_hooks.py
python3 tools/issue_manager.py
python3 tools/test_issue_manager.py
git diff --check
```

문서·Python 구문·링크 검사 통과, Git hook 8개·Issue 관리자 27개 시험 통과, 팀 설정 형식 정상(활성 4/4, 네트워크·변경 없음), diff 공백 검사 통과. 원격 Repository checks는 이 기본 검사 범위이며 ROS 빌드·실기 검증을 대신하지 않는다.

## 한계와 인계

- ROS 메시지는 자료형을 제공한다. UUID·해시·버전·진행률·배열 길이·측정 신선도·quaternion·고정 확인·실제 정지 조건은 수신/발행 노드가 명세대로 검사해야 한다. 직렬화 시험은 그 노드의 의미 검증 완료를 뜻하지 않는다.
- TCP 측정은 제어기 기준, 경로 waypoint는 도구 끝 기준이다. 현재 제어기 TCP는 그리퍼 끝점 `GripperDA_v1`이며 실제 변환·프로파일 승인 검증은 공정 담당 영역이다.
- 압력·누락 구간 판정은 아직 모의 HMI 기능이다. 새 공통 타입이 품질 판정 센서나 전체 공정 구현을 제공하지 않는다.
- 후속: 담당자 모두 같은 패키지 커밋으로 빌드·source, 좌표·공정 노드 구현, 산출물 파일 계약과 artifact_loader 연결, ROS 가짜 상대 통합, 현장 설정·실기 확인.
- 되돌리기: 타입과 해당 타입을 쓰는 소비 코드를 같은 이전 커밋으로 함께 되돌려 다시 빌드·재시작한다. DB 스키마는 이번 작업에서 바꾸지 않았다.
