# 원본 로그 보존·DB 선별 적재 — 2026-10-14

사용자 결정에 따라 원본 JSONL은 별도 보존하고, 새 원본의 DB 적재에서 반복 진단을 선별한다.
웹은 도안 확인에 필요한 모형·층별 설계·제작자·완료·저장·공개 상태를 표시한다.
Robot 실행, B의 Current/Expected·공간 비교, 공통 메시지 계약은 변경하지 않는다.

## 저장·조회 범위

| 위치 | 포함 내용 |
|---|---|
| 원본 보관 폴더 | 읽기 시작 시점의 JSONL 전체 bytes. 공백·줄바꿈·미완결 마지막 행 포함 |
| 신규 DB 원본 | `operational-v1`로 선별한 이벤트·채택 자료·적재 진도·원본 검증 메타데이터 |
| 기존 DB 원본 | 기존 이벤트·자료·소유권·저장 영수증·공개 상태 유지. 진단 행 삭제 없음 |
| 웹 도안 상세 | 모형·층별 설계·제작자·완료·저장·공개 상태. 로그·대화·원본 경로 표시 없음 |

웹의 **EXPORT DESIGN JSON**은 선택한 Design 버전만 내보낸다. 다른 버전이나 작업 로그를 포함하지 않는다.
전체 DB 기록은 기존 운영 CLI `timeline`/`report`와 인증·소유권 검사를 거치는
`GET /api/jobs/<JOB_UUID>`에 유지한다. 웹 상세의 `/summary` 응답에는 타임라인과 원본 경로를 넣지 않는다.
선별 적재에서 제외된 샘플은 전체 DB API에도 없으며, 별도 보존한 원본 파일에서 확인한다.

## 적재 정책

| 정책 | 적용 |
|---|---|
| `operational-v1` | 신규 source의 기본값. 일반 `ROBOT_CAMERA_CANDIDATE`·`ROBOT_MOTION_SAMPLE`만 제외 |
| `all` | 모든 완결 행 적재. 기존 source는 이 정책으로 보존하며 필요할 때 신규 source에 명시 선택 |

두 진단 이벤트라도 document의 `reason`, result의 `error`가 null이 아니거나,
`success=false`, `status=ERROR/FAILED/REJECTED/STOPPED`이면 DB에 보존한다.
카메라의 `candidate_event`가 null이 아닌 실제 신호 후보도 보존한다.
카메라 result의 일반 프레임 판별 사유와 요청 식별자는 자체적으로 실패·신호를 뜻하지 않는다.
다른 이벤트와 알 수 없는 이벤트는 보존하며, `*_SAMPLE` 등의 이름 패턴으로 일괄 제외하지 않는다.

source의 입력 계약과 적재 정책은 최초 적재 후 바꿀 수 없다. 정책 옵션을 생략하면 기존 값을 유지한다.
같은 파일을 새 source 이름으로 다시 적재해 기존 정책을 우회하지 않는다. 기존 source의 append는 기존 정책을 따른다.
저장 manifest는 실제 DB에 적재된 이벤트 전체를 계속 사용하며, 웹 조회 축소로 저장 영수증을 바꾸지 않는다.

## 원본·재적재·실패 처리

- [archive.py](../history/archive.py)는 원본을 수정하지 않고 파일 크기를 상한으로 별도 스냅샷을 만든다.
  파일명은 `<SHA-256>.jsonl`, DB에 기록하는 보관 경로는 절대 경로다. 기존 스냅샷은 덮어쓰지 않는다.
- [records.py](../history/records.py)는 보존한 스냅샷의 모든 완결 행을 먼저 검사한 뒤 선별한다.
  잘못된 JSON·계약 위반은 제외 후보여도 적재 실패다. 마지막 줄바꿈이 없는 행은 `pending_line`으로 보류한다.
- source의 `last_line`은 선별 전 완결 행 수다. `prefix_sha256`으로 제외 행까지 기존 prefix의 변경·잘림을 거절한다.
  같은 source 재적재는 중복 이벤트를 만들지 않고, append는 새 완결 행만 처리한다.
- 원본 보존 실패 시 DB 적재와 진도를 commit하지 않는다. DB 실패 뒤 유효한 원본 스냅샷은 남을 수 있으며,
  파일 보존을 DB 저장 성공으로 표시하지 않는다. 자동 재시도·상태 복원·Robot 재실행은 하지 않는다.

직접 `store.ingest`를 호출할 때 기본 보관 위치는 입력 파일 부모의 `history_archive`다.
CLI 기본값은 `--source-root` 아래 `history_archive`이며,
`--archive-root` → `HISTORY_ARCHIVE_ROOT` → 기본 위치 순서로 적용한다.
보관 폴더는 원본과 별도 경로를 사용하고 Git에 기록하거나 재적재 입력으로 일괄 선택하지 않는다.

## 실행·검증

기존 [DB 접속 안내](D_DB_HISTORY.md)에 따라 환경을 지정한다. 다음 `<JOB_UUID>`는 실제 입력 파일명으로 바꾼다.
`init`은 [003 메타데이터 migration](../history/migrations/003_source_archive.sql)을 추가 적용하며 기존 업무 데이터를 초기화하지 않는다.

```bash
python3 -m history init
python3 -m history ingest --source-root logs --archive-root logs/history_archive \
  --contract final-mvp-20261008 logs/<JOB_UUID>.jsonl
```

Docker app에는 `HISTORY_ARCHIVE_ROOT=/reports/original_logs`를 제공한다.
기존 `/records:ro` 입력은 유지하며 보존 파일은 쓰기 가능한 `/reports` 볼륨에 저장한다.
원본/보존 폴더·DB 볼륨을 삭제하거나 기존 정책을 변경하는 이전 작업은 포함하지 않는다.

```bash
PYTHONPATH=.:tests/unit:tests/integration python3 -m pytest \
  tests/unit/test_history_selection.py tests/integration/test_history_selection_db.py \
  tests/integration/test_history_db.py tests/integration/test_history_personal_db.py \
  tests/integration/test_history_web.py -q
node tests/web/test_design_rendering.cjs
node tests/web/test_design_navigation.cjs
```

PostgreSQL 검사는 `_test`로 끝나는 별도 DB의 `HISTORY_TEST_DSN`이 필요하며, skip은 통과가 아니다.
검사 범위는 선별·SQL 일치·원본 bytes·중복/append·prefix 변경·미완결 행·실패 rollback·기존 소유권/저장/공개 유지다.
DOM 검사는 브라우저·실물 조립 검증을 대신하지 않는다. 실제 실행 결과는 [STATUS](STATUS.md)를 따른다.
