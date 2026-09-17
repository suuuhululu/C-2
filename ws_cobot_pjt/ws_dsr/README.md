# ws_dsr · 로봇·그리퍼 실행환경

메인 프로젝트가 사용하는 외부 로봇·그리퍼 실행환경 `cobot_rg2`를 `src/`에 준비한다. `src/` 전체는 Git에서 제외한다. 팀이 직접 만드는 메인 ROS 패키지와 launch 파일은 옆의 `ws_cobot1/src/`에서 관리한다.

2026-09-17 기록 정리: 외부 src 제외는 [PR #3](https://github.com/suuuhululu/C-2/pull/3)으로 main에 반영됐다. 9/16 사용자는 MSI Ubuntu에서 Docker 에뮬레이터로 가상 로봇을 움직였다고 보고했으며 해당 PC의 정확한 설치 버전은 확인 대기다. 이시율은 별도 PC의 Ubuntu 24.04·Jazzy, cobot_rg2 커밋·수정 여부, dsr_emulator 3.0.1과 가상 이동 결과를 보고했다. 자세한 출처·버전은 [의존성 기록](../../docs/DEPENDENCIES.md)에 구분했다. 이번 작업의 직접 구동 시험이나 실기 검증은 아니다.

- 외부 패키지는 [의존성 기록](../../docs/DEPENDENCIES.md)에 출처·브랜치·커밋·필요한 설치 과정을 기록하고 같은 버전으로 준비한다.
- `src` 안의 `doosan-robot2`, `onrobot-ros2`, `rg2`, `rokey` 등은 모두 로컬 전용이다. 외부 저장소의 `src/.git`을 삭제하거나 외부 소스를 강제로 추가하지 않는다. 같은 두산 패키지를 여러 원본으로 동시에 넣지 않는다.
- 팀 패키지를 `src/` 안에 작성하면 C-2로 공유되지 않는다. 공정·연동·실행환경 확장 패키지는 `ws_cobot1/src/`에 둔다.
- 이 README, 상위 `docker/`의 설치 스크립트, `ws_cobot1/doc/`의 실행 문서는 별도 검토를 거쳐 공유할 수 있다.
- `.gitkeep`은 Git 추적에서 제거했다. 새 C-2 clone에 `src/`가 없는 것은 정상이다. 기존 외부 저장소는 다시 clone하지 않고, 새 PC만 [준비 방법](../../docs/DEPENDENCIES.md)을 따른다.
- 다른 워크스페이스의 build/install/log를 복사하지 않는다. 빌드·환경 적용은 [워크스페이스 가이드](../../docs/WORKSPACES.md)를 따른다.
