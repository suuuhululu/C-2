# 외부 패키지·설치물 기록

2026-09-19 후속: 팀 앱은 React·Vite·FastAPI·SQLite를 사용하며 잠금 파일은 frontend/package-lock.json·backend/requirements.lock.txt에 있다. 공통 타입 의존성은 c2_interfaces/package.xml의 Jazzy·rosidl·geometry_msgs·builtin_interfaces 등으로 관리한다. 이번 고정 드릴 변경은 외부 드라이버·제어기 설치나 버전을 변경하지 않는다. 아래 9/16~17 표는 당시 보고다. [현재 구현](../ws_cobot_pjt/docs/HMI_MONITOR_IMPLEMENTATION.md).

2026-09-17 기록 정리. 설치·동작 보고는 아래에 명시한 9/16 사용자·팀원 보고를 기준으로 하며 이번에 장비 시험을 추가 수행하지 않았다. 외부 실행환경은 실행 PC에 설치하고 C-2에는 출처·버전·재현 방법을 기록한다. 같은 폴더 이름이나 같은 날짜에 받은 소스가 같은 버전을 보장하지 않으므로 정확한 커밋을 확인한다.

| 대상 | 위치 | 확인 상태 |
| --- | --- | --- |
| 메인 로봇·그리퍼 환경 | ws_cobot_pjt/ws_dsr/src | 수업 지정 [ahnisinc/cobot_rg2](https://github.com/ahnisinc/cobot_rg2). 폴더 전체 Git 제외는 PR #3 병합 완료. 이시율 PC의 커밋·수정 여부 보고 확보, 공용 MSI와 팀 공통 고정 버전은 확인 대기 |
| 공식 두산 참고 소스 | 대상 src 아래 doosan-robot2 | 공식 Jazzy 소스 확인. 강사 수정본과 동일한 것으로 취급하지 않음 |
| Dart Platform | ws_cobot_pjt/DartPlatform | 교육 자료의 2.12.1 표기. 실제 배포 파일·OS·설치본은 확인 필요 |
| Backend·Frontend·팀 컨테이너 구성 | ws_cobot_pjt의 각 폴더 | 팀 앱 프레임워크·의존성·Dockerfile·Compose 미정 |
| 외부 Docker 에뮬레이터 | 각 실행 PC의 설치 위치 | MSI에서 가상 동작 보고. 이시율 PC의 dsr_emulator 3.0.1 보고는 아래 표 참조 |

상위 개인 프로젝트의 doosan은 [공식 저장소](https://github.com/DoosanRobotics/doosan-robot2/tree/jazzy)의 jazzy 브랜치다. 2026-09-16 로컬 커밋 `8e033f0e2284be0a25b655266e02878ebc915c50`을 재확인했다. 이번 작업에서는 이동·복사하지 않았다. 강사 수정본의 dsr_rokey 같은 패키지를 공식 원본이 제공한다고 가정하지 않는다.

## 설치·공유 규칙

- 같은 워크스페이스에 서로 다른 원본의 dsr 패키지를 중복으로 넣지 않는다. 사용할 원본을 먼저 정한다.
- `ws_cobot_pjt/ws_dsr/src/` 전체는 외부 원본 전용이며 Git에서 제외한다. 내부 폴더 이름에 관계없이 같은 규칙을 적용한다.
- 팀이 만드는 메인 ROS 패키지·launch 파일은 `ws_cobot_pjt/ws_cobot1/src`에 둔다. `ws_dsr/src` 안의 팀 코드는 C-2에 공유되지 않는다. 설치 스크립트·실행 문서는 각각 `ws_cobot_pjt/docker`, `ws_cobot_pjt/ws_cobot1/doc`에서 별도 PR로 검토한다.
- 실제 그리퍼 모델·강사 소스 출처를 확인하기 전 다른 드라이버 저장소를 임의로 선택하지 않는다.
- 외부 원본을 수정해야 하면 수정·배포·버전 고정 방법을 먼저 PR에서 합의한다.
- Dart 설치 파일·로그 대신 배포 위치·설치 버전·재현 절차를 공유한다.
- Mac은 편집·Git 관리용이며 외부 실행환경을 설치하지 않는다. 공용 MSI 등 이미 동작하는 실행 PC는 설치를 유지한다.

## 수업 지정 cobot_rg2

| 항목 | 기록 |
| --- | --- |
| 원본 URL | `https://github.com/ahnisinc/cobot_rg2.git` |
| 원본 브랜치 | `main` |
| 로컬 설치 위치 | C-2 루트 기준 `ws_cobot_pjt/ws_dsr/src` |
| 원본 조회 기준 커밋 | [`4d5657f36a160eedb533ab1c975cd8a30c3e53b2`](https://github.com/ahnisinc/cobot_rg2/commit/4d5657f36a160eedb533ab1c975cd8a30c3e53b2) — 2026-09-16 원격 존재 확인 |
| 팀 실사용 고정 커밋·로컬 수정 여부 | 확인 대기. 위 조회 기준 커밋이 모든 PC에 설치됐다고 가정하지 않음 |
| 사용자 확인 내용 | MSI Ubuntu에서 Docker 에뮬레이터 설치 후 시뮬레이터를 켜고 로봇을 움직였다고 보고함 (2026-09-16) |
| 이시율 PC의 소스 확인 보고 | Ubuntu 24.04·ROS 2 Jazzy, `main`의 `4d5657f36a160eedb533ab1c975cd8a30c3e53b2`. 추적된 소스 수정은 없으며 `.gitkeep`·`__pycache__`만 표시됐다고 보고함. [Issue #2 확인 기록](https://github.com/suuuhululu/C-2/issues/2#issuecomment-5691159901) (2026-09-16) |
| 이시율 PC의 실행 보고 | Docker·dsr_emulator 3.0.1 설치, `colcon build --symlink-install` 35개 패키지 성공, `mode:=virtual` 브링업과 `/dsr01/dsr_controller2/motion/move_joint` 호출로 가상 로봇 이동 확인. 위 Issue 댓글의 보고이며 이번 문서 작업에서 직접 실행하지 않음 |
| 아직 미확인 | 공용 MSI의 정확한 OS·ROS·Docker·에뮬레이터 설치 버전과 소스 커밋·로컬 변경, 나머지 팀원 환경, 실제 장비 동작. 이시율 PC 보고만으로 팀 전체의 고정 버전을 확정하지 않음 |

원본에는 `doosan-robot2`, `onrobot-ros2`, `rg2`, `rokey`가 포함된다. 기존 예시의 `onrobot_rg2`와 실제 `onrobot-ros2`는 폴더명이 다르므로 메인 실행환경은 하위 폴더를 따로 열거하지 않고 `src/` 전체를 제외한다. 원본 조회와 사용자 보고를 이 작업에서 직접 수행한 설치·실기 시험으로 표현하지 않는다.

### 이미 설치한 PC

기존 `src`, `src/.git`, build/install/log와 Docker 설치를 그대로 둔다. 이번 Git 제외 변경을 위해 재설치·재clone·버전 변경을 할 필요는 없다. 추후 같은 환경을 재현할 때 설치된 외부 저장소에서 커밋과 수정 여부를 확인해 위 표를 갱신한다. 다음은 C-2 루트에서 실행하는 읽기 전용 확인이다.

```bash
if [ -e ws_cobot_pjt/ws_dsr/src/.git ]; then
  git -C ws_cobot_pjt/ws_dsr/src rev-parse --show-toplevel
  git -C ws_cobot_pjt/ws_dsr/src rev-parse HEAD
  git -C ws_cobot_pjt/ws_dsr/src status --short
else
  printf '%s\n' '이 위치에는 외부 Git 저장소가 없습니다. 실제 설치 위치를 확인하세요.'
fi
```

수정 내역이 있으면 SHA만으로 같은 소스를 재현할 수 없다. 변경 파일·patch 또는 별도 fork·커밋을 검토해 기록하며 `.git`을 지워 C-2에 통째로 올리지 않는다.

### 새 PC에서 원본 받기

팀의 실사용 고정 커밋을 확인한 후 진행한다. 아래는 `src`가 없는 새 환경에서 원본을 받는 수업 절차이며 설치·빌드·실행 명령은 아니다. C-2 저장소의 실제 루트에서 시작하고 개인 홈 경로를 하드코딩하지 않는다.

```bash
cd ws_cobot_pjt/ws_dsr
git clone --branch main https://github.com/ahnisinc/cobot_rg2.git src
```

복제에 성공한 새 `src`에서는 `git -C src checkout --detach 확인한_커밋_SHA`의 마지막 값을 팀에서 확인한 정확한 SHA로 바꿔 버전을 고정한다. `main`이나 “2026-09-16 최신”이라는 표현만으로 버전 고정을 대신하지 않는다. 이미 설치된 PC는 이 절차를 반복하지 않는다.

이전 C-2의 `src/.gitkeep`은 Git 추적에서 제거했다. 기존 clone에 자리표시자만 남아 새 clone을 방해하면 그 파일이 자리표시자인지 확인하고 `.gitkeep`만 정리한다. 기존 외부 소스 폴더 전체를 삭제하지 않는다.

### Git 제외 확인

C-2 루트에서 다음을 확인한다.

```bash
git check-ignore -v --no-index ws_cobot_pjt/ws_dsr/src/
git ls-files --stage -- ws_cobot_pjt/ws_dsr/src
```

첫 명령에는 `.gitignore`의 `/ws_cobot_pjt/ws_dsr/src/` 규칙이 표시되고 두 번째에는 출력이 없어야 한다. `git status`가 깨끗하다는 사실만으로 추적되지 않는다고 판단하지 않는다. 이미 파일이나 저장소 포인터가 추적된 PC에서는 내용을 보존한 채 추적 해제 범위를 검토한다. `.gitignore`는 일반적인 `git add` 실수를 막는 규칙이며 강제 추가나 이미 추적된 파일까지 차단하지는 않는다.

## 설치가 확정되면 채울 항목

- 대상과 적용 워크스페이스:
- 원본 URL 또는 승인된 배포 위치:
- 브랜치·태그·정확한 커밋 또는 설치 버전:
- 실제 ROS·OS·CPU·제어기·그리퍼 버전:
- 필요한 의존성과 설치·빌드 명령:
- 실행·검증한 환경과 결과:
- 확인자·확인일·관련 Issue·PR:

접근 토큰·비밀 값·개인 이메일은 기록하지 않는다. [워크스페이스 가이드](WORKSPACES.md)에 맞춰 각 PC에서 같은 소스로 준비한다.
