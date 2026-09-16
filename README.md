# C-2 협동로봇 프로젝트

두산 M0609와 2점 그리퍼를 사용하는 교육·팀 프로젝트 저장소입니다. ROS 2 기준은 **Jazzy**입니다.

## 먼저 읽기

1. [현재 준비 상태와 검토 항목](docs/REVIEW_STATUS.md)
2. [프로젝트 운영·학습·분업 가이드](docs/PROJECT_GUIDE.md)
3. [워크스페이스·환경 가이드](docs/WORKSPACES.md)
4. [Git·PR 협업 가이드](docs/GIT_GUIDE.md)
5. [Issue 자동 배정·일정 변경](docs/ISSUE_AUTOMATION.md)
6. [팀장 운영 가이드](docs/TEAM_LEAD_GUIDE.md)
7. [팀원 시작 가이드](docs/TEAM_ONBOARDING.md)
8. [기술 참고 자료와 확인 범위](docs/REFERENCES.md)
9. [AI 공통 지침](AGENTS.md)

## 폴더 구조

```text
C-2/                              현재 로컬 clone 폴더명: collaborative
├── ros2_ws/                      수업·미니 실습 ROS 2 워크스페이스
│   ├── docs/                     실습 결과·복습 기록
│   ├── exercises/                DRL 등 ROS 패키지가 아닌 실습
│   └── src/                      실습 ROS 2 패키지
├── ws_cobot_pjt/                 메인 프로젝트
│   ├── DartPlatform/             설치 위치 안내 (프로그램·Logs는 로컬 전용)
│   ├── backend/app/              서버 코드
│   ├── docker/                   컨테이너 구성
│   ├── docs/                     기획·인터페이스·검증 결과
│   ├── frontend/
│   │   ├── public/               화면 정적 파일
│   │   └── src/                  화면 소스
│   ├── ws_cobot1/                팀 공정 ROS 2 워크스페이스
│   │   ├── doc/                  실행·설정 문서
│   │   └── src/                  팀 공정·노드·launch 패키지
│   └── ws_dsr/                   로봇·그리퍼 실행환경 워크스페이스
│       └── src/                  외부 cobot_rg2 원본 (로컬 전용, Git 제외)
├── docs/                         팀 공통 운영·환경·Git 가이드
├── .github/                      PR·Issue 양식, 팀 계정, 자동화
├── .githooks/                    main 직접 push 방지
└── tools/                        Git hook 설치, 로컬 검사, Issue 처리
```

2026-09-16 전달받은 강사 디렉토리 구조에 맞췄습니다. 미니 실습은 [ros2_ws](ros2_ws/README.md), 메인은 [ws_cobot_pjt](ws_cobot_pjt/README.md)에서 진행합니다. Git 저장소는 하나이며 `ws_cobot_pjt` 폴더와 Git의 `main` 브랜치는 다른 개념입니다.

ROS 워크스페이스는 `ros2_ws`, `ws_cobot_pjt/ws_cobot1`, `ws_cobot_pjt/ws_dsr` 세 곳입니다. 수업 환경과 메인 환경을 섞지 않으며, 메인은 준비된 `ws_dsr` 위에서 `ws_cobot1`을 빌드하도록 구분합니다. [경로 변경·준비·공유 방법](docs/WORKSPACES.md)을 먼저 확인하세요.

저장소에는 팀 코드·문서·설정만 공유합니다. `ws_cobot_pjt/ws_dsr/src` 전체는 각 PC에서 준비하는 외부 `cobot_rg2` 원본이므로 Git에서 제외하며, 새로 clone한 C-2에는 이 폴더가 없습니다. 이미 설치한 PC는 그대로 사용하고, 출처·버전·새 PC 준비 방법은 [의존성 기록](docs/DEPENDENCIES.md)을 따릅니다. `build/`, `install/`, `log/`, `node_modules/`, Dart 로그도 각 PC에서 생성하며 Git에서 제외합니다.

## 팀원 시작 순서

최초 저장소 초기화와 이 문서의 PR 병합이 완료된 뒤 적용합니다.

```sh
git clone https://github.com/suuuhululu/C-2.git
cd C-2
sh tools/setup-git-hooks.sh
python3 tools/check_repository.py
python3 tools/test_git_hooks.py
```

이후 [Git 가이드](docs/GIT_GUIDE.md)에 따라 작업 브랜치를 만들고 PR을 제출합니다. PR은 작업 브랜치를 push한 뒤 `main` 반영을 요청하는 절차입니다.

GitHub Actions의 `repository-checks`는 문서·소스 구문·hook 동작을 검사합니다. **ROS 빌드·시뮬레이터·실기 시험을 대신하지 않습니다.**

`Issue management`는 미배정 작업 분배, 댓글을 통한 상태 변경, 팀장 승인 후 마감 변경, 마감 임박·지연 표시를 처리합니다. 네 팀원 계정을 등록했으며 역할은 아직 모두 general입니다. **2026-09-16 작업 브랜치의 commit·push가 승인되었습니다. Issue 자동화는 기본 브랜치 main에 반영된 뒤 활성화합니다.** 팀원 권한 확인과 main 반영 후 [활성화 절차](docs/ISSUE_AUTOMATION.md)를 진행합니다.
