# Git·PR·버전·협업 문서 관리

레포: https://github.com/suuuhululu/C-2.git · 로컬: /home/ms-02/C_2.
2026-10-05 origin/main에는 기존 문서와 C skeleton 및 PR #2 / #3 변경이 있습니다. 아래 빈 레포 설명은 최초 준비 당시 기록입니다. 현재는 최신 main 기반 별도 브랜치에서 작업하고 PR로 게시합니다. 기존 미커밋 변경과 이력을 보존합니다.

## 빈 레포의 최초 PR

비교 기준 브랜치가 없으므로 현재 상태로는 바로 PR을 열 수 없습니다. 최소 기반 커밋과 문서 변경 커밋을 분리해 준비합니다.

- 로컬 `bootstrap/pr-base`: 기존 .gitignore만 포함하는 최소 기반 커밋.
- 로컬 `docs/latest-decisions-collaboration`: 기반 위에 최신 문서·참고 원본·협업 템플릿을 담는 변경.
- 변경 설명과 검증 결과를 사용자에게 전달한 뒤 원격 초기 게시·PR 생성 단계로 진행.

아래는 게시 단계의 예시이며 이 가이드 작성이 push를 실행한 것은 아닙니다. 게시 직전 원격에 새 커밋이 생겼는지 다시 확인합니다. 원격 main이 생겼으면 기존 이력을 먼저 받아 비교하고 강제 push하지 않습니다.

```bash
git ls-remote --heads origin
git push origin bootstrap/pr-base:main
git push -u origin docs/latest-decisions-collaboration
```

이후 GitHub에서 base=main, compare=docs/latest-decisions-collaboration의 Draft PR을 만들 수 있습니다. PR 제목·본문은 이번 작업의 검토 결과로 준비합니다. 팀원 초대·권한·브랜치 보호·Merge는 별도 작업입니다.

## 일상 개발

main → feature/작은-작업 → PR → 작성자 외 사람 리뷰 → Merge를 기본 제안으로 합니다. 장기 dev 브랜치는 팀 필요가 확인될 때 도입합니다. 공유 계약은 통합 책임자·연결 담당 리뷰, Robot / 정지 변경은 Robot Owner와 다른 사람의 리뷰를 받습니다.

현재 앱·테스트·CI는 없습니다. 코드가 추가되면 pytest·계약·Mock 통합 검증을 PR CI에 연결합니다. 문서 확인을 시스템 테스트 통과로 표시하지 않으며 GitHub CI에서 REAL Robot을 움직이지 않습니다.

## Day 4 코드와 최종 코드 보존

권장 운영은 **같은 모듈 코드 + 검증된 버전 태그**입니다. Day 4 시연 커밋을 고정하고 이후 feature에서 최종 버전을 확장합니다. 별도 day4 / final 소스 복사본을 동시에 관리하면 수정과 계약이 서로 달라질 수 있습니다.

| 시점 | 보존할 버전 | 조건 |
|---|---|---|
| Day 4 | `day4-mvp` 태그 | 실제 시연·설정·지원 범위·시험 결과를 확인한 커밋 |
| 최종 발표 | `final-demo` 태그 | 최종 시나리오·장치·실행 절차를 검증한 커밋 |
| Day 4 유지보수 | 필요 시 Day 4 태그 기반 수정 브랜치 | 최종 기능 변경과 구분하고 수정 태그·증거 기록 |

태그명은 운영 제안이며 이번 문서 작업에서 태그를 만들지 않습니다. Day 4 기능은 최신 결정의 최초 생성·전달 / 사람 조립·관측·Intervention이며, 최종 추가 범위는 Day 4 이후 팀이 정합니다.

각 버전에는 Design·설정 / Calibration 버전·입출력 계약·Python / ROS / driver 정보·실행 방법·시험 / 미검증을 함께 기록합니다. 기능 선택이 필요하면 확정된 설정으로 표현하고 core 곳곳에 Day 번호 분기를 넣지 않습니다. 공유 계약 변경 시 버전·생산자 / 소비자 영향과 migration을 PR에 적습니다.

## 현재 저장소 구조

아래는 최초 문서 준비 당시 구조이며 현재 원격에는 C skeleton과 C 구조 / 진행 문서도 있습니다. 실제 파일 목록은 Git 트리를 확인합니다.

```text
C-2/
├── README.md
├── AGENTS.md / AGENT.md
├── .gitignore
├── .github/
│   ├── pull_request_template.md
│   └── ISSUE_TEMPLATE/team_task.md
└── docs/
    ├── 00_CURRENT_DECISIONS.md
    ├── 01_DAY_PLAN.md
    ├── 02_TEAM_GUIDE.md
    ├── 03_MEASUREMENT_GUIDE.md
    ├── 04_ISAAC_SIM.md
    ├── 05_REPOSITORY_GUIDE.md
    ├── 06_CONTRACT_DRAFT.md
    ├── STATUS.md
    └── reference/                 # 원본 정책·기존 계획·GT
```

문서 배치는 이번 PR의 검토안입니다. 코드 파일·공통 Schema·Fixture·설정의 정확한 위치는 아래 제안과 연결 담당자 확인을 거쳐 정합니다.

## 코드 구조 초안

아래는 초기 구조 제안이며 C는 현재 app/c_design/의 승인된 skeleton을 유지합니다. 이번 계약 갱신으로 파일 이동·전체 runtime 생성·dependency 도입을 실행하지 않습니다.

```text
app/
  design.py       # 시율 Initial / Revised·HRI 계산
  planning.py     # 세은 사람 조립 Plan / Validation
  perception.py   # 홍동 이미지 → Observed
  workflow.py     # 수현 Current / Expected·진행·비교
  robot.py        # 수현 전달·슬롯·실행 상태
  adapters/       # 실제 Camera / Robot / LLM / HMI 연결, 필요 파일만
tests/            # unit·contract·mock integration, 구현 시 추가
```

HMI는 Qt 단일 화면으로 결정되었습니다. 공통 Schema 위치·정확한 패키지·Qt 바인딩은 연결 담당자가 구현에서 맞춥니다. 사용하지 않는 추상계층·DB·서비스를 미리 생성하지 않습니다.

## 문서·자료·비밀정보

협업 Markdown은 docs에서 PR로 관리합니다. docs/reference 원본은 그대로 보존하고 현재 결정을 별도로 명시합니다. .env·secret·로컬 환경·빌드·로그는 Git 제외입니다. 실제 좌표 기록은 실행 설정과 분리합니다.

사진·RGB-D·rosbag·USD·영상은 공개 범위·용량 확인 후 선별합니다. 현 레포에 이미지 파일은 없습니다. GT의 파일명은 원자료 참조입니다. 라이선스·팀원 권한은 사용자 또는 팀 결정 없이 추가하지 않습니다.
