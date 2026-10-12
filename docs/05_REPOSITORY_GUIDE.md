# Git·PR·버전·협업 문서 관리

갱신: 2026-10-07. 저장소는 [suuuhululu/C-2](https://github.com/suuuhululu/C-2), 지정 로컬 개발 위치는 `/home/ms-02/C_2`입니다. 자료 폴더 `/home/ms-02/C-2_협동2자료`와 별도 저장소의 구현·검증 상태를 동일하게 취급하지 않습니다.

## 작업과 게시

- 지정 개발 checkout의 `work/suhyun-hmi-backend-robot-db`와 미완료 변경을 유지합니다. 최신 main 기반 별도 문서 작업 공간으로 이번 최종 MVP PR을 준비합니다.
- 변경 범위를 먼저 확인하고 이번 작업 파일만 commit/push/PR에 포함합니다. 전체 add·되돌리기·force push를 사용하지 않습니다.
- 사용자는 이번 문서 갱신과 PR 생성을 요청했습니다. merge는 별도 요청이며 AI 확인은 사람 리뷰를 대체하지 않습니다. [팀장 리뷰 정책](../GITHUB_REVIEW_SETUP.md)을 확인합니다.
- 기존 저장소에는 앱·Schema·Fixture·pytest와 DB 적재/조회 코드가 있습니다. CI·lint/type 설정은 미구성이며 이번 문서 작업에서 새 도구를 설치하지 않습니다.
- 코드 변경은 관련 시험, 문서 변경은 링크·표·코드 블록·결정 정합성·diff를 검증합니다. 문서 검사만으로 앱·DB·웹·실제 Camera/Robot 통과를 표시하지 않습니다.

## 제품 목표와 버전

현재 제품 목표는 [최종 MVP](10_FINAL_MVP.md)입니다. 이전 전달형 Day4·사람 조립·Qt·JSONL 계약은 기존 코드와 시험의 기준으로 보존합니다. 최종 목표는 커스텀 의자 대화/확정·조립 순서/경로·직접 결착·사람 지지·최종 Vision/Backend 판정·사용자별 DB/웹입니다.

기본 실행 복구 기준은 [D_RUNTIME_BASELINE.md](D_RUNTIME_BASELINE.md)를 따릅니다. 그 버전은 전달 공정이며 최종 직접 결착 시연 증거가 아닙니다. Day4/final 소스를 통째로 복사해 별도로 유지하기보다 계약·검증 범위를 명시한 커밋/태그를 사용하는 기존 제안을 유지합니다. 최종 시연 태그는 해당 장치·전체 서비스 검증 후 정하며 이번 문서 PR에서 생성하지 않습니다.

각 버전에는 Design·Config/Calibration·입출력 계약·환경·실행 방법·실제 검사와 미검증을 연결합니다. 계약 변경 PR은 생산자/소비자 영향·이행 순서·실패 반환·검증을 포함합니다.

## 현재 저장소 구조

```text
C-2/
├── README.md / AGENTS.md / CODEOWNERS / GITHUB_REVIEW_SETUP.md
├── app/                 # C Design·D Backend/Qt·기존 Robot 실행 연결
├── planning_trial/      # A PLACE 순서·Remaining/Replan과 검사
├── interfaces/          # 기존 Day4/HMI Schema·Fixture·실기 설정
├── history/             # 독립 PostgreSQL 적재/조회·계정·로그 Schema
├── compose.history.yaml / Dockerfile.history / requirements-history.txt
├── tests/ / scripts/    # 독립·모의 연결·실행 검증 도구
└── docs/
    ├── 00_CURRENT_DECISIONS.md / STATUS.md
    ├── 10_FINAL_MVP.md
    ├── suhyun_individual_research_topic.md
    ├── 01_DAY_PLAN.md / 02_TEAM_GUIDE.md / 06_CONTRACT_DRAFT.md
    ├── C_*.md / D_*.md  # 구현·실행·시험 범위
    └── reference/       # 원본 정책·과거 계획·GT와 적용 안내
```

이 구조는 main `95259bd`의 게시 파일과 이번 문서 추가를 기준으로 합니다. 직접 결착/지원·사용자별 웹 모듈을 이미 만든 것으로 표시하지 않습니다. 경로/웹 담당·HMI와 웹앱 분담·새 패키지/Schema/통신은 합의 후 구현합니다. 문서 때문에 파일 이동·framework·dependency를 추가하지 않습니다.

## 문서·자료 관리

[최신 결정](00_CURRENT_DECISIONS.md)과 [최종 MVP](10_FINAL_MVP.md)에 개발 중 변경의 날짜·이유·영향을 기록합니다. 세부 요구는 최종 MVP에 모으고 기존 계약/실행/시험 문서에는 해당 구현 범위를 표시합니다. 첨부 연구의 원문과 제품 적용 안내를 구분합니다.

`docs/reference/`의 정책·과거 계획·GT 원문은 보존하며 [적용 안내](reference/README.md)를 함께 봅니다. 과거 시험 수치·실제 측정값·실패 기록을 새 목표에 맞춰 바꾸지 않습니다. GitHub에 없는 로컬 final_docs·발표 초안은 이번 게시 문서 갱신에 섞지 않습니다.

.env·secret·로컬 환경·빌드·로그·DB 자료는 Git 제외입니다. 사진·RGB-D·rosbag·USD·영상은 공개 범위와 용량 확인 후 선별합니다. GT의 이미지 파일명은 원자료 참조이며 비밀번호·계정 seed·실제 DB 자료를 공개 문서에 추가하지 않습니다.
