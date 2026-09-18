# C-2 협동로봇 프로젝트

두산 M0609와 2점 그리퍼를 사용하는 교육·팀 프로젝트 저장소입니다. 현재 서비스 방향은 **고객 도안을 원기둥 표면에 새기는 맞춤 음각**이며 ROS 2 기준은 **Jazzy**입니다.

## 음각 프로젝트 문서

- [현재 축소 시나리오: 3개 노드 인터페이스·팀 협업 안내](ws_cobot_pjt/docs/INTERFACE_GUIDE.md)
- [목표 디렉토리·파일별 역할](ws_cobot_pjt/docs/SYSTEM_STRUCTURE.md) · [통신 필드·완료 조건 권장안 v1](ws_cobot_pjt/docs/INTERFACE_RECOMMENDATION.md)
- [0917 개발 일지: 지점토 단위 실기·측정 기능·알고리즘 검토](ws_cobot_pjt/docs/daily/2026-09-17.md)
- [서비스 목표·기능별 구현 상태](ws_cobot_pjt/docs/PROJECT_PLAN.md)
- [전체 기능 흐름: 가공·세척·오류 처리](ws_cobot_pjt/docs/SERVICE_FLOW.md)
- [9/17 이전 설계: PC·웹앱·모니터·ROS 역할](ws_cobot_pjt/docs/SYSTEM_ARCHITECTURE.md)
- [기존 중심선·가공 경로의 세 차례 오프라인 검증](ws_cobot_pjt/docs/ALGORITHM_VALIDATION.md)
- [PNG·JPEG → SVG 비교와 Potrace 선택: 영역·굵기 보존](ws_cobot_pjt/docs/SVG_VECTORIZATION_VALIDATION.md)
- [실험과 정량 기록 계획](ws_cobot_pjt/docs/EXPERIMENT_PLAN.md)
- [현장 설정과 DRL 초안의 확인 범위](ws_cobot_pjt/docs/HARDWARE_STATUS.md)

2026-09-18 설계 범위는 고객용 웹앱 없이 시스템 모니터에서 입력·실행·상태 확인을 수행하는 구조입니다. 작업대·대상은 고정 좌표, 그리퍼는 고정 장치이며 교체 도구를 사용합니다. 새 3개 노드 계약은 구현 목표입니다. [8페이지 draw.io 시스템 아키텍처](ws_cobot_pjt/docs/architecture/README.md)에서 송수신 데이터와 구현 상태를 확인할 수 있습니다. 기존 Clay 코드·전용 실행 안내는 사용자 요청으로 로컬 보관 후 저장소에서 제거했습니다. [보관·복구 기록](ws_cobot_pjt/docs/LEGACY_CLAY_ARCHIVE.md).

2026-09-17 지점토 평면의 선분·정사각형·원·별 그리기 수행 보고와 시율의 사전 작업 기능 개발을 일지에 추가했습니다. 원기둥 실기, 자동 파지·세척·반납, 시스템 모니터의 통합 완료와는 구분합니다. 정량 측정값·시험 코드 버전의 확보 여부는 일지에 표시했습니다.

## 먼저 읽기

1. [진행 현황과 남은 작업](docs/REVIEW_STATUS.md)
2. [프로젝트 운영·학습·분업 가이드](docs/PROJECT_GUIDE.md)
3. [워크스페이스·환경 가이드](docs/WORKSPACES.md)
4. [Git·PR 협업 가이드](docs/GIT_GUIDE.md)
5. [Issue 자동 배정·일정 변경](docs/ISSUE_AUTOMATION.md)
6. [팀장 운영 가이드](docs/TEAM_LEAD_GUIDE.md)
7. [팀원 시작 가이드](docs/TEAM_ONBOARDING.md)
8. [기술 참고 자료와 확인 범위](docs/REFERENCES.md)
9. [AI 공통 지침](AGENTS.md)

## 현재 진행 상황

2026-09-17 확인: 초기 구성 [PR #1](https://github.com/suuuhululu/C-2/pull/1)과 외부 실행환경 제외 [PR #3](https://github.com/suuuhululu/C-2/pull/3)은 동료 승인 후 main에 병합됐습니다. [Issue #2](https://github.com/suuuhululu/C-2/issues/2)도 종료됐고, Issue 자동화가 실제 실행 중입니다.

메인 중심 구조와 음각 설계 문서는 [PR #4](https://github.com/suuuhululu/C-2/pull/4)로 9/17 main에 병합됐습니다. 추가 0917 일지는 `docs/0917-unit-function-log` 작업 브랜치에서 정리합니다. 게시·PR·병합 상태와 실기 확인 범위는 [진행 현황](docs/REVIEW_STATUS.md)을 확인하세요.

## 폴더 구조

```text
C-2/                              현재 로컬 clone 폴더명: collaborative
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

2026-09-17 사용자 요청에 따라 [ws_cobot_pjt](ws_cobot_pjt/README.md)의 메인 프로젝트 중심으로 정리했습니다. Git 저장소는 하나이며 `ws_cobot_pjt` 폴더와 Git의 `main` 브랜치는 다른 개념입니다.

ROS 워크스페이스는 `ws_cobot_pjt/ws_cobot1`, `ws_cobot_pjt/ws_dsr` 두 곳입니다. 준비된 `ws_dsr` 위에서 팀 코드인 `ws_cobot1`을 빌드합니다. [환경 준비·공유 방법](docs/WORKSPACES.md)을 먼저 확인하세요.

저장소에는 팀 코드·문서·설정만 공유합니다. `ws_cobot_pjt/ws_dsr/src` 전체는 각 PC에서 준비하는 외부 `cobot_rg2` 원본이므로 Git에서 제외하며, 새로 clone한 C-2에는 이 폴더가 없습니다. 이미 설치한 PC는 그대로 사용하고, 출처·버전·새 PC 준비 방법은 [의존성 기록](docs/DEPENDENCIES.md)을 따릅니다. `build/`, `install/`, `log/`, `node_modules/`, Dart 로그도 각 PC에서 생성하며 Git에서 제외합니다.

## 팀원 시작 순서

새 팀원은 현재 main을 clone해 시작합니다. 이미 clone한 팀원은 기존 작업을 보존하고 [Git 가이드](docs/GIT_GUIDE.md)에 따라 최신 변경을 받습니다.

```sh
git clone https://github.com/suuuhululu/C-2.git
cd C-2
sh tools/setup-git-hooks.sh
python3 tools/check_repository.py
python3 tools/test_git_hooks.py
```

이후 [Git 가이드](docs/GIT_GUIDE.md)에 따라 작업 브랜치를 만들고 PR을 제출합니다. PR은 작업 브랜치를 push한 뒤 `main` 반영을 요청하는 절차입니다.

GitHub Actions의 `repository-checks`는 문서·소스 구문·hook 동작을 검사합니다. **ROS 빌드·시뮬레이터·실기 시험을 대신하지 않습니다.**

`Issue management`는 main에서 활성화됐습니다. Issue #2에서 분류·마감 기록·검토 상태·종료 반영을 확인했습니다. 네 팀원의 역할은 아직 모두 general이며, 미배정 작업의 자동 분배와 일정 변경 승인 전체 과정은 [팀원 연습](docs/TEAM_ONBOARDING.md)으로 원격 검증해야 합니다. 사용법은 [Issue 자동화](docs/ISSUE_AUTOMATION.md)를 따릅니다.
