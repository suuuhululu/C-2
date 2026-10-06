# 기본 실행 코드 버전과 복구 기준

2026-10-07. 사용자 요청으로 현재 로컬의 미게시 실행 변경을 PR로 보존하고 팀장 계정으로 main 병합을 준비한다. 게시 기준 main은 `a459e13`(DB PR #13 병합)이다. 복구용 버전명은 `c2-runtime-baseline-2026-10-07`이며 PR 병합 커밋에 태그를 생성한다. 이 문서는 실기 안전 검증이나 사람 리뷰가 완료됐다는 뜻이 아니다.

## 포함한 변경

- Backend/Qt의 현재 실제 배치 표시, 고정 화면과 현장 입력 처리.
- 기존 C 함수를 사용하는 텍스트·음성/STT/TTS 연결, 실제 A의 Remaining 재계획 연결.
- 기존 실기 원본과 측정 hash를 재사용하는 네 공급열 실행 연결, 명시적 HOME→Observe 사전 이동.
- 기존 실행의 정지 표식·MoveStop 요청·상태 probe·이전 프로세스 종료·블록 상태 확인을 분리하고, 확인된 명령 기록만 재개하는 실행부.
- 관련 Schema/Fixture와 단위·모의 통합 검사, 실행·미검증 기록.

원래 `/home/ms-02/C_2`의 지정 브랜치와 미커밋 파일은 보존하고 별도 worktree에서 PR을 구성했다. 최신 main의 팀 계약·CODEOWNERS·C/A/B 원본·DB 구현을 오래된 로컬 문서로 덮어쓰지 않았다. 로컬의 발표/제출 문서 초안은 이번 실행 코드 PR에서 제외한다.

새 사람 전달 기능인 `handover_enabled`, 전달 요청/취소/수신 신고, 개발 데모와 0단계 검사는 이번 기본 버전에 포함하지 않는다. 원래 로컬 파일과 별도 백업에 보존하고, main 기준의 전달 개발 브랜치에서 이어간다. 이 버전의 기본 Robot 목적지는 기존 Place Board다.

## 이번 게시 트리의 검증

```bash
env -u HISTORY_TEST_DSN QT_QPA_PLATFORM=offscreen \
  python3 -m pytest tests planning_trial/test_planner.py -q
```

실제 결과: **1371 passed, 24 skipped**, 실패/오류 0, 종료 0. 24개는 별도 PostgreSQL DSN이 필요한 DB 통합 검사다. 이번에 DB 자료/계정을 조작하거나 Robot/Camera/마이크/스피커/음성 API를 실행하지 않았다. REAL 파일명 검사는 QProcess/driver/HTTP/음향 mock을 사용한다. Python 구문·JSON 파싱과 diff 공백도 확인했다. CI/lint/type 도구는 추가하지 않았다.

아직 필요한 현장 확인: 실제 STOP/재개 및 재개 궤적, 보호정지 복구 정책, 현재→HOME 경로, gripper 보유/개방 상태, Camera 생산자/시각/시야, STT/TTS 권한·음향 장치. 태그는 소프트웨어 복구 기준이며 이런 조건의 충족을 보증하지 않는다. 기존 pose/TCP/tool/속도/측정 원본을 변경하지 않았다.

검사 원자료와 기존 파일 백업은 로컬 `/home/ms-02/C_2_backups/2026-10-07-before-runtime-pr/`에 있다. `working-files.tar.gz`/`manifest.json`은 전달 0단계를 포함한 현재 파일 188개를 보존한다. `external-references/`는 외부 Robot 원본·측정 파일 2개와 hash를 보존한다. 환경변수·비밀값·로컬 로그·DB 자료는 공개 저장소에 올리지 않는다.

## 리뷰와 병합 상태의 구분

사용자는 팀원들이 취침 중이라 리뷰가 어렵다고 설명하고 “PR 해주고 팀장 권한으로 병합해주세요”라고 명시했다. 이 요청에 따라 작성자/팀장 계정의 PR 병합을 수행하며, 사람의 동료 리뷰나 자기 Approve를 만들어 표시하지 않는다. 저장소의 기존 필수 검사·CODEOWNERS·보호 규칙을 변경하지 않는다. PR 본문에 검증 수준과 이 예외 사유를 기록한다. 실제 게시/병합 결과는 PR의 상태와 커밋·태그로 확인한다.

## 기존 파일을 덮어쓰지 않는 복구 방법

병합·태그 게시 후 기존 작업 폴더에서 다음 명령으로 별도의 복구 폴더를 만든다.

```bash
git fetch origin --tags
git worktree add --detach ../C_2-baseline-recovery c2-runtime-baseline-2026-10-07
```

원래 진행 중인 폴더를 reset하거나 미커밋 변경을 삭제하지 않는다. 실제 실행에 필요한 외부 로봇 원본/측정과 현장 설정은 별도로 대조하고 준비한다. 실행 명령은 [Robot/HMI 안내](D_BACKEND_RUN_ROBOT_PLAN.md)를 따르며 Git 복구 자체는 로봇이나 그리퍼를 실행하지 않는다. 후속 전달 기능을 main에 반영할 때도 별도 PR을 사용한다.
