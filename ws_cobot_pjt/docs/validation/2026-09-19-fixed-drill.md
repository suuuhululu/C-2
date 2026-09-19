# 고정 드릴 v2 변경 검증

- 시험명 / 작성자 / 확인자 / 날짜: 고정 드릴 계약·HMI·문서 정합성, Codex(사용자 요청), 사람 검토 대기, 2026-09-19.
- 기준 / 시험 코드: main `301ea6ea6bafcf44fa854ecaac8d10dbccf7e748`, `codex/fixed-drill-contract`에서 이 기록을 추가한 커밋. PR에 최종 커밋·원격 검사 결과를 연결한다.
- 수준: 문서·구문, Jazzy 타입 빌드·직렬화, 서버/DB 모의 응답, 로봇 어댑터 오프라인 시험, TypeScript/Vite 빌드.
- 환경: Ubuntu 24.04 계열 편집 PC, ROS 2 Jazzy, Python 3.12.3, 기존 backend 가상환경, Vite 6.4.1. 별도 worktree의 ws_cobot1 산출물을 사용했다.
- 현장 조건: 적용 없음. 로봇·그리퍼·외부 드라이버를 기동하지 않았다. TCP·힘·보정·J6 실측값을 새로 검증하지 않았다.

| 시나리오 | 기대 결과 | 실제 결과 | 판정 |
| --- | --- | --- | --- |
| 타입 생성 | 기존 5개 통신에 v2 상수·기본값, Python 타입 직렬화 | Jazzy build 성공, pytest 11개 통과 | 통과 |
| 고정 드릴 정상 | PRECHECK→TOOL_CHECK→APPROACH→ENGRAVE→RETRACT→FINISH, 장착 유지 | 단계·상태 전송을 수집해 집기/청소/반납·OPEN/OPENING 없음 확인 | 통과 |
| 장착/닫힘 미확인 | PRECHECK 실패, 조각 진입 차단 | 기존 실패 사례를 새 단계에 맞춰 확인 | 통과 |
| 보정 확인 실패 | TOOL_CHECK에서 실패, 경로·설정 덮어쓰기와 조각 진입 금지 | PROFILE_MISMATCH, 진행 0, 경로 바이트 보존 | 통과 |
| 보정 확인 중 정지 | 정지 확인 후 접근·조각 없음, 그리퍼 열기 없음 | 가짜 상대의 단계·상태 기록으로 확인 | 통과 |
| v1 혼입 | 이전 요청/도구/설치 타입 거절, 오래된 상태를 fresh로 표시하지 않음 | HTTP 422, ROS 설치 버전 검사 오류, 상태 STALE | 통과 |
| 과거 DB 경로 | 조회는 가능, 새 실행은 차단 | v1 경로 행을 재현해 조회 200, 실행 409 UNSUPPORTED_SCHEMA_VERSION | 통과 |
| 한 획 180° 초과 | 실행 경로 없이 진단만 제공 | U=-60..60 mm 한 획으로 모의 r=34 mm의 180° 범위 초과 확인 | 통과 |
| 기존 어댑터 회귀 확인 | main 소스를 유지하고 기존 오프라인 동작 확인 | 모의 시험 7개 통과; frame 변경은 별도 PR #23 | 통과 |
| 화면 빌드 | v2 요청·6개 단계·고정 드릴 표시 타입 정합 | TypeScript 및 Vite production build 통과 | 통과 |
| 문서 점검 | 현재 설계·실행 지침과 보관 기록 구분 | 기존 docs Markdown 31개 점검, 25개 갱신·6개 유지 | 완료 |
| 실제 보정·J6·전체 공정 | 현장 프로파일과 실제 모션·정지 확인 | 대상 노드·실측 설정 준비 전 | 미수행 |

## 실행 명령·결과

```bash
source /opt/ros/jazzy/setup.bash
cd ws_cobot_pjt/ws_cobot1
colcon build --packages-select c2_interfaces --symlink-install
source install/local_setup.bash
colcon test --packages-select c2_interfaces --event-handlers console_direct+
colcon test-result --verbose
python3 src/c2_process/test/test_robot_adapter_mock.py
```

타입 pytest 11개, 어댑터 모의 7개 통과. colcon 집계 12 tests는 pytest 11개와 CTest 실행 단위 1개를 포함하며 실패·오류·skip은 0이다. c2_process의 ROS 패키지 빌드가 완료됐다는 뜻은 아니다.

위 Jazzy·workspace를 source한 환경에서 backend의 기존 가상환경으로 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`를 실행했다. 모니터 21개 + ROS 변환/설치 타입 9개 = **30개 통과**. 최초 획 각도 시험의 식물 도안 폭은 목표 경계를 넘지 않아 시험이 실패했고, 의도한 경계만 검사하는 단일 직선으로 입력을 수정한 뒤 재실행해 통과했다. 14.39초, 기존 Starlette/AnyIO 폐기 예정 경고 1개. 제한 환경에서의 기존 비동기 시험 정지를 피하려고 제한 밖에서 실행했으며 로봇 연결은 없다.

frontend는 설치된 의존성을 사용해 `tsc -b`, `vite build`를 수행했다. 이번 문서 변경에서 브라우저의 모든 화면·실제 장치를 다시 시험했다고 보고하지 않는다.

저장소 검사: `tools/check_repository.py`, `tools/test_git_hooks.py`, `tools/issue_manager.py`, `tools/test_issue_manager.py`, `git diff --check`. GitHub Repository checks도 이 범위만 검사하며 ROS 빌드·실기 성공의 증거가 아니다.

## 남은 항목·변경 한계

- 3점 실제 보정·1점 확인·J6/IK·그리퍼 고정 피드백 검증, 좌표·공정 노드, engraving main 이관, artifact_loader는 후속 담당 작업이다. 보정 시험의 현재 결과는 가짜 성공/실패 분기다.
- 어댑터 기본 frame 변경이 PR #23과 중복되는 것을 확인해 이번 변경에서 제외했다. robot_adapter와 그 시험 소스는 main 그대로이며, 모션·접촉·정지 제어 알고리즘은 변경하거나 실기 검증하지 않았다. c2_base가 실제 base와 같게 등록되는 것은 실행 환경에서 확인해야 한다.
- 미확정 z·힘·보정 허용차·J6 한계값을 실행 YAML로 작성하지 않았다. 과거 evidence와 담당 기능 브랜치를 보존했다.
- 타입·소비자 배포는 함께 진행한다. 문제 시 실행을 중지하고 모의/조회로 확인한다. 철사 고정 중에는 열기를 포함한 v1 실행으로 롤백하지 않는다.
