# 수현 DB 이력 — 독립 적재·조회 실행 안내

## 최종 MVP의 저장·웹 이행 (2026-10-07)

[최종 MVP](10_FINAL_MVP.md)는 현재 설계와 조립 기록의 **사용자별 DB 저장과 웹앱 반영**을 서비스 종료의 3단계에 포함합니다. 아래 명령/Schema는 현재 게시된 독립 JSONL→PostgreSQL 적재·조회/계정 구현이며 유지합니다. ‘개인 도안·소유자·웹 제외’는 당시 구현 범위이며 최종 제품의 제외 조건이 아닙니다.

현재 [schema.sql](../history/schema.sql)의 jobs는 job_id만 저장하고 users와 연결되지 않습니다. 계정 확인은 세션·웹 권한을 발급하지 않습니다. 새로운 사용자–Job 소유자 연결과 채택 Design/Plan·Current·Step/최종 판정·지원/실패 근거의 저장 계약, 사용자별 조회·웹 반영 경로가 필요합니다. 저장 시점·이벤트/필드·중복 방지·세션/권한은 아직 확정하지 않았으며 이번 PR에서 SQL·적재 코드·API를 변경하지 않습니다.

1. 필요한 블록 사용 종료만으로 DB에 정상 조립 완료를 기록하지 않습니다.
2. Vision 근거와 Backend 최종 판정으로 물리 조립 종료를 기록합니다.
3. 사용자 연결·설계/조립 이력 저장·웹 반영 결과를 따로 확인합니다. 저장/반영 실패를 성공으로 숨기거나 Robot 재실행으로 해결하지 않습니다.

기존 Job에 소유자를 추정해서 붙이거나 DB에서 Current를 자동 복원하지 않습니다. JSONL 주요 이벤트·실험 F/T 원자료의 보관 위치/참조 관계는 별도 설계하고, 기존 DB에 매 프레임·힘 시계열이 이미 저장됐다고 표시하지 않습니다. 기존 집계의 전달→사람 조립 시간도 직접 결착의 삽입 시간으로 이름만 바꾸지 않습니다.

## 기존 DB 구현·실행·검증 안내

2026-10-06 사용자의 최신 요청으로 **기존 Day4 공정을 유지하면서 컨테이너·PostgreSQL을 병행 개발**한다. 과거 DB 제외 결정에 대한 이번 추가 범위다. 구현·검증 뒤 사용자의 PR 게시 요청에 따라 DB 변경만 별도 PR로 게시한다. merge는 별도 승인 범위다. 개발 위치는 `/home/ms-02/C_2`, 브랜치는 `work/suhyun-hmi-backend-robot-db`다.

## 구성과 입력·출력

```text
기존 환경의 Backend/Robot/Camera/Qt
  → 기존 Job별 JSONL (원본 유지)
  → 별도 history 명령 컨테이너
  → PostgreSQL의 c2_history Schema / 영속 볼륨
  → Job 목록·타임라인·채택 자료·사유 집계·JSON 보고서
```

app 서비스는 요청한 명령을 실행하고 종료한다. 웹 서버나 상시 폴링 서비스가 아니다. DB 지연·연결 실패는 이 명령의 실패이며 공정 Backend는 이 프로그램을 호출하지 않는다. 정상 Step의 HMI 입력·판단·Current·Expected·Robot 경로는 그대로다. DB에서 상태를 복원하거나 Robot을 다시 실행하는 기능은 없다.

| 기존 근거 | 재사용 방식과 한계 |
|---|---|
| [JsonlLog](../app/jsonl_log.py) | timestamp·job_id·plan_id·step_id·request_id·event·result·reason. Job은 기존 canonical UUID, 다른 식별은 문자열/null이다. 공통 event_id 추가 없음 |
| [Backend](../app/backend.py)의 PLAN_ADOPTED | 검증·채택 뒤 design, plan, base_current, confirmed_steps 원문이 이미 기록됨. 별도 내보내기와 공정 코드 변경 불필요 |
| INITIAL_DESIGN_RECEIVED / PLAN_RESULT / INTENT_RECEIVED | 후보와 결과는 이벤트 원문으로 보관. 채택 자료 테이블에는 PLAN_ADOPTED만 넣음 |
| CURRENT_ADOPTED | Current·Observed 상세는 기존 result에 있는 만큼 보관. 매 프레임/영상/이미지 추가 저장 없음 |
| Expected | 공정에서 고정 Plan 기준으로 계산. 독립 원문 로그가 없으므로 DB에 있었다고 가정하거나 최신 Current로 재계산하지 않음 |
| JOB_STARTED / JOB_COMPLETED | 확인 가능한 시작·완료 근거. 완료 없는 Job은 NO_COMPLETION_RECORDED. 오류를 최종 실패나 자동 취소로 단정하지 않음 |

Schema는 [schema.sql](../history/schema.sql), 적재는 [records.py](../history/records.py)·[store.py](../history/store.py), 집계는 [report.py](../history/report.py), 실행은 [__main__.py](../history/__main__.py)다. jobs는 Job 식별을 저장하고 결과·시각은 events에서 조회한다. events는 조회 필드와 원문 JSONB·raw_line을 함께 저장한다. artifacts는 DESIGN / PLAN / BASE_CURRENT 원문을 저장한다. `(Job, kind, version 또는 plan_id)`가 같은데 내용이 달라지면 덮어쓰지 않고 오류로 반환한다. 서로 다른 Job의 v1 또는 동일 plan_id는 독립 자료다. 동일 Design을 재계획에 다시 채택해도 Plan별 채택 이벤트·기준 Current가 남는다.

공정용 Python 의존성은 변경하지 않았다. 별도 [requirements-history.txt](../requirements-history.txt)의 `psycopg[binary]==3.3.6`을 사용한다. 기존 스택에 PostgreSQL 드라이버가 없고 표준 라이브러리만으로 연결할 수 없어 추가했다. ORM·pool·벡터 DB·브로커 없이 SQL과 트랜잭션을 직접 사용한다. binary 패키지는 이 컨테이너에서 빌드 도구 없이 설치할 수 있다. 드라이버의 JSONB와 트랜잭션 동작은 [Psycopg 공식 안내](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)·[JSON 변환 안내](https://www.psycopg.org/psycopg3/docs/basic/adapt.html#json-adaptation)를 확인했다. 볼륨은 [Compose 공식 안내](https://docs.docker.com/reference/compose-file/volumes/)에 맞춘 named volume이다.

## 컨테이너 실행과 Mock 기록 생성

아래는 별도 시험 프로젝트·DB·포트를 사용하는 재현 순서다. 저장소 루트에서 실행한다. 기존 운영 자료를 적재하지 않고 공통 Fixture만 사용한다. 비밀번호는 예제에 적거나 Git에 넣지 않는다.

```bash
cd /home/ms-02/C_2
export HISTORY_DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
export HISTORY_DB_NAME=c2_history_test
export HISTORY_DB_PORT=55439
export HISTORY_UID="$(id -u)"
export HISTORY_GID="$(id -g)"
mkdir -p logs/history_mock logs/history_reports

docker compose -p c2-history-test -f compose.history.yaml up -d --wait db
docker compose -p c2-history-test -f compose.history.yaml build app
docker compose -p c2-history-test -f compose.history.yaml run --rm app init

python3 -m history.mock_record --directory logs/history_mock
python3 -m history.mock_record --directory logs/history_mock --revise
```

생성되는 출력 예시는 `{"job_id":"<UUID>","status":"COMPLETE","path":"logs/history_mock/<UUID>.jsonl"}`다. 정상은 3번 전달과 3번 관측 확인, Revised 시나리오는 첫 전달 뒤 색상 변경을 실제 관측으로 채택하고 C/A 형태의 Fixture v2/Plan을 받아 나머지 2 Step을 확인한다. [mock_record.py](../history/mock_record.py)는 기존 FAKE Backend·JSONL을 사용하며 실제 C/A 알고리즘·Camera·Robot 성공을 뜻하지 않는다. Robot 성공 callback만으로 Current·Step을 완료하지 않는다.

재접속할 때는 해당 볼륨을 만들 때의 비밀번호와 프로젝트명·DB명을 그대로 사용한다. 위 비밀번호 생성 줄을 매번 다시 실행하면 기존 DB 비밀번호와 달라질 수 있다. 로컬에 저장할 때는 `.env` 또는 Git에서 제외되는 파일에 권한 600으로 보관한다. 이번 시험 설정은 `logs/history_validation.env`에 있으며 파일 내용을 출력하지 않는다.

현재 남겨둔 시험 환경은 아래와 같이 접속한다. 해당 설정 파일은 로컬 시험 산출물이므로 새 clone에는 없다.

```bash
docker compose --env-file logs/history_validation.env -p c2-history-test -f compose.history.yaml run --rm app jobs
```

## 적재와 조회

첫 명령의 두 UUID는 앞 단계에서 생성된 실제 Job으로 바꾼다. `/records`는 호스트의 `logs`를 읽기 전용으로 연결한다. `--source-root` 아래 상대 경로가 적재 식별이므로 호스트에서도 `--source-root logs`를 사용하면 같은 식별을 얻는다. 다른 root를 지정해 경로를 바꾸거나 같은 파일을 다른 이름으로 복사해 적재하면 별도 원본으로 취급한다. 파일 이동 시 원래 상대 경로를 유지한다.

```bash
docker compose -p c2-history-test -f compose.history.yaml run --rm app ingest \
  --source-root /records /records/history_mock/<정상_JOB>.jsonl /records/history_mock/<변경_JOB>.jsonl

docker compose -p c2-history-test -f compose.history.yaml run --rm app jobs
docker compose -p c2-history-test -f compose.history.yaml run --rm app timeline <변경_JOB>
docker compose -p c2-history-test -f compose.history.yaml run --rm app reasons --job-id <변경_JOB>
docker compose -p c2-history-test -f compose.history.yaml run --rm app artifacts <변경_JOB>
docker compose -p c2-history-test -f compose.history.yaml run --rm app report <변경_JOB> \
  --output /reports/revised-job.json
```

`reasons`의 `--job-id`를 생략하면 전체 Job을 집계한다. 조회 출력은 JSON이다. 보고서는 `logs/history_reports/revised-job.json`에 저장되며 jobs·timeline·reasons·episodes·durations·artifacts와 designs·currents·plans·hri를 담는다. raw_line은 입력 JSON의 공백·줄바꿈까지 비교할 수 있고 document는 JSON 구조 비교용이다. app은 기본 uid/gid 1000으로 실행하며 다른 사용자 환경은 위 환경변수로 지정한다. 폴더는 호스트에서 미리 생성한다.

적재 출력 예시는 `{"source":"history_mock/<UUID>.jsonl","inserted":30,"skipped":0,"pending_line":null}`이며 재적재는 inserted=0, skipped=30이다. 성공 종료 코드는 0, 입력/DB/파일 오류는 1이다. 입력 오류는 `파일:행번호:사유`를 반환한다. DB 연결 오류는 연결 문자열·비밀번호를 출력하지 않는다. 자동 재시도는 없으며 원본을 보존하고 명시적으로 다시 실행한다.

## 중복·실패·진행 중 파일의 규칙

- 적재 내부의 `(source_key, 1부터 시작하는 행번호)`가 이벤트 식별이다. 동일 내용이 다른 행에 있으면 각각 저장한다. SHA-256은 기존 행 변경 확인용이며 내용 해시로 이벤트를 합치지 않는다.
- 파일 하나는 한 트랜잭션이다. 이벤트·새 Job·채택 자료·적재 진도가 함께 commit/rollback된다. 여러 파일 중 앞 파일이 성공하고 뒤 파일이 실패하면 앞 파일은 유지되며 stdout에 파일별 결과가 남는다.
- 같은 원본의 동시 적재는 DB transaction advisory lock으로 직렬화한다. 별도 원본에서 같은 채택 식별을 기록한 경우는 유일 제약과 원문 비교로 보호한다.
- 기존 적재 행을 수정하거나 잘라낸 파일은 오류다. 신규 자료는 새 파일로 기록하며 이미 저장한 내용은 덮어쓰지 않는다. 오류 난 새 행을 바로잡아 재실행하면 기존 prefix는 건너뛰고 새 행만 저장한다.
- 읽기 시작 당시 파일 크기를 상한으로 읽는다. 마지막 행에 줄바꿈이 없으면 JSON이 완전해 보여도 `pending_line`으로 보류한다. 다음 실행에서 줄바꿈까지 기록된 뒤 적재한다. 종료된 파일도 마지막 줄바꿈이 필요하다. JSONL 쓰기/완료 처리는 생산자 책임이며 적재부가 원본에 줄바꿈을 붙이지 않는다.
- 필수 필드 누락·잘못된 JSON·중복 키·NaN·시간대 없는 timestamp·잘못된 Job UUID·채택 자료 연결 오류는 위치와 사유를 반환한다. nullable 식별은 기존 계약대로 허용한다.

## 집계와 시간의 의미

| category | 기록 근거 |
|---|---|
| ASSEMBLY_WAIT | Step이 있는 DELIVERY_RESULT.success=true → STEP_CONFIRMED. 전달 뒤 조립·확인까지 구간이며 정상 대기다 |
| INTENT_WAIT | hri REQUEST_SENT → KEEP/REVISE INTENT_RECEIVED 또는 새 Plan 채택. UNCLEAR/추가 질문은 같은 대기다 |
| UNOBSERVABLE | OBSERVATION_HOLD 또는 전달판 UNOBSERVABLE. 조립과 전달판의 회복 근거를 분리한다 |
| ROBOT_FAILURE | 실패 DELIVERY_RESULT 또는 원래 요청이 robot.*인 CALL_FAILED |
| MODULE_FAILURE / PLAN_ERROR | 기타 호출 실패 / INVALID Plan 결과. 모듈 판단의 오류 사유를 보존한다 |
| CORRECTION_WAIT / SUPPLY_WAIT / STOP_WAIT | 사람 정리·공급 보충·정지 관련 이벤트 |

episodes는 Job·종류·관측 대상 안에서 같은 사유와 Plan/Step이 지속되는 동안 하나를 센다. 반복 증거는 evidence_count만 늘린다. 명시적인 해제 뒤 다시 나타나거나 사유/Plan/Step이 달라지면 새 구간이다. 사유 변경만으로 이전 사유가 회복됐다고 추정하지 않는다. `reason_counts.episodes`는 이 구간 수이며 프레임·행 수나 장애 총수가 아니다. 정상 대기와 의도 확인도 종류별로 반환하므로 전체 합을 오류 수로 사용하지 않는다.

Job 시작→완료, Robot REQUEST_SENT→동일 request_id의 DELIVERY_RESULT, 전달 성공→관측 Step 확인, 질문→채택 응답의 로그 구간만 계산한다. 끝이 없거나 시간이 역전되면 duration_seconds는 null이다. 관측 보류는 실제 복구 순간이 로그에 없을 수 있어 이후 명시 확인까지의 **기록 구간**이며 정밀한 물리 downtime이 아니다. 부분 Current 채택만으로 이번 target의 관측 보류를 끝내지 않는다. 대기 구간은 서로 겹칠 수 있어 합산해 총시간으로 쓰지 않는다.

`unresolved_conditions`는 종료 근거가 없는 이력이다. 실제 현재 Backend 상태를 조회한 값이 아니다. 해당 이벤트가 없는 과거 기록의 Plan 검증 실패·LOG_FAILED·대기 진입·작업 취소 시각을 만들어내지 않는다. 진성/가성 알람·가성 완료율은 실제 정답 자료가 필요하므로 산출하지 않는다. 설계 사례 원문은 검색 기반이 되지만 RAG·벡터 검색·매뉴얼 생성·HMI 이력 페이지는 후속 범위다.

## 재적재와 영속성 재현

위에서 적재한 동일 파일 명령을 다시 실행하면 inserted=0이어야 한다. 아래 명령은 컨테이너만 재생성하며 볼륨을 삭제하지 않는다.

```bash
docker compose -p c2-history-test -f compose.history.yaml up -d --force-recreate --wait db
docker compose -p c2-history-test -f compose.history.yaml run --rm app timeline <변경_JOB>
docker compose -p c2-history-test -f compose.history.yaml run --rm app artifacts <변경_JOB>
docker compose -p c2-history-test -f compose.history.yaml run --rm app ingest \
  --source-root /records /records/history_mock/<변경_JOB>.jsonl
```

운영용 실행은 다른 `-p` 프로젝트명·DB명·포트·로그 입력을 선택한다. 시험과 운영 볼륨은 Compose 프로젝트별로 분리된다. 시험에서도 `down -v`나 volume 삭제는 사용하지 않는다. 종료는 `stop db`, 다시 실행은 `up -d --wait db`다. 시험 데이터의 DB 접근이 필요할 때만 DB를 실행해둔다.

## 단위·실제 DB 검사 실행

JSONL/집계 단위 검사는 드라이버 없이 기존 Python 환경에서 실행할 수 있다.

```bash
python3 -m pytest tests/unit/test_history.py -q
```

호스트에서 실제 DB 검사할 경우 별도 설치 경로를 사용한다. 이 환경에는 ensurepip가 없어 venv 생성이 실패했으며 OS 패키지·전역 의존성은 변경하지 않았다.

```bash
python3 -m pip install --target .venv/history-deps -r requirements-history.txt
export PYTHONPATH="$PWD/.venv/history-deps"
export HISTORY_TEST_DSN="$(python3 -c 'import os; from urllib.parse import quote; print("postgresql://c2_history:"+quote(os.environ["HISTORY_DB_PASSWORD"],safe="")+"@127.0.0.1:"+os.environ["HISTORY_DB_PORT"]+"/"+os.environ["HISTORY_DB_NAME"])')"
QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q
```

DB tests는 HISTORY_TEST_DSN이 없으면 skip하며, 연결한 DB명이 `_test`로 끝나지 않으면 실패시켜 운영 DB에서 시험하지 않는다. 시험마다 새 Job·source를 발급하고 기존 행·테이블·볼륨을 지우지 않는다. 실제 SQL `SELECT 1/0` 실패를 채택 자료 적재 중 일으켜 새 Job·event·artifact·source 전체 rollback과 재실행을 검증한다. 실제 DB 환경을 지정하지 않은 skip 결과는 DB 통합 성공이 아니다.

## 현재 검증 기록

최종 수치와 컨테이너 시험 결과는 [STATUS의 DB 항목](STATUS.md)에 기록한다. 시험 보고서와 로그는 `logs/history_reports/`·`logs/history_mock/`에 있으며 Git에서 제외된다. 새 clone에서는 위 명령으로 다시 생성한다. lint/type check는 기존 설정이 없어 미구성이다. 실제 Robot·Camera 실행은 하지 않았으며 기존 장치·다른 담당의 구현은 수정하지 않았다.

계정·적재·조회 실행 코드와 별도 검증·컨테이너·Schema·안내 파일은 요청한 적재·조회·재실행·영속성 검증에 직접 필요하다. 단순 파일 복사/CSV는 DB 누적·유일 제약·트랜잭션 목적을 만족하지 못하므로 제외했다. 새 class는 위치를 전달하는 InputError 하나이며 Repository/Service/Factory 계층은 없다. 신규 파일·의존성·전체 변경 규모는 사람 리뷰 대상이고 자체 검사로 사람 리뷰·Integration Owner 승인을 대체하지 않는다.

## 2026-10-06 — DB 내부 사용자 계정 추가

사용자 요청으로 `c2_history.users`를 추가했다. 필드는 `user_id`(UUID), `username`(중복 없는 로그인 ID), `display_name`, `password_hash`, `created_at`이다. 현재 사용하는 로컬 시험 DB `c2_history_test`에 수현/suhyun, 세은/seeun, 시율/siyul, 홍동/hongdong, 테스터/test를 생성했다. 사용자가 지정한 개발용 비밀번호로 설정했으며 비밀번호 원문은 코드·문서·SQL seed·로그·조회 출력에 저장하지 않는다.

[accounts.py](../history/accounts.py)는 계정 생성·안전한 필드 조회·비밀번호 확인만 담당한다. 같은 ID의 재생성은 오류로 반환하고 기존 이름·비밀번호를 덮어쓰지 않는다. 비밀번호 확인은 사용자 정보 또는 인증 실패를 반환하며 **세션을 발급하지 않는다**. 새 library 없이 Python 표준 `hashlib.scrypt`를 사용했다. 계정별 랜덤 16-byte salt, n=131072/r=8/p=1, 32-byte 결과와 형식 정보를 password_hash에 저장하고 constant-time 비교를 한다. OpenSSL 메모리 상한은 256 MiB로 명시했다. 근거는 [Python 3.12 hashlib](https://docs.python.org/3.12/library/hashlib.html#hashlib.scrypt)와 [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)다. password 입력은 1~1024 UTF-8 bytes이며 이번 개발용 계정을 위한 추가 길이 정책은 강제하지 않는다.

기존 DB 계정과 앱의 사용자 계정은 별개다. 아래는 DB 관리자/개발자용 로컬 명령이며 일반 사용자 HMI나 접근 권한 서비스가 아니다. `users`는 비밀번호 해시를 반환하지 않는다. `check-user` 성공도 HMI 로그인 세션 생성이나 도안 접근 권한 부여를 뜻하지 않는다.

```bash
docker compose --env-file logs/history_validation.env -p c2-history-test -f compose.history.yaml build app
docker compose --env-file logs/history_validation.env -p c2-history-test -f compose.history.yaml run --rm app init
docker compose --env-file logs/history_validation.env -p c2-history-test -f compose.history.yaml run --rm app users
docker compose --env-file logs/history_validation.env -p c2-history-test -f compose.history.yaml run --rm app check-user suhyun
```

`check-user`는 터미널에서 비밀번호를 숨겨 입력받는다. 추가 계정 생성은 `create-user <로그인ID> <표시이름>`으로 실행하고 비밀번호를 두 번 확인한다. 자동 시험에는 `--password-stdin`으로 한 줄을 입력한다. 비밀번호를 명령 인자에 넣거나 출력하지 않는다. 인증 실패/중복/입력 오류는 종료 코드 1이다. 사용자 조회·생성·비밀번호 확인의 성공 출력은 `user_id, username, display_name, created_at`만 담는다. 기존 사용자의 정보나 해시가 잘못돼 있으면 자동 재설정하지 않는다.

현재 요청에 따라 HMI/Backend/Robot/Camera와 계정 연결은 하지 않았다. 기존 Job에 사용자 소유자를 임의로 붙이지 않았으며 개인 도안 보관함, 로그인 세션, QR/얼굴인식은 아직 없다. 이후 통합할 때 제안하는 화면 흐름은 `앱 실행 → 로그인 화면 → 인증 성공/세션 생성 → 개인 도안·이력 및 공정 화면`이다. 이는 제안이며 현재 HMI 실행/시작 조건을 변경한 것이 아니다. 작업 중 계정 전환·세션 종료와 기존 정지/재개 처리의 구체 정책은 통합 범위에서 정한다.

저장표는 **5개**(users/jobs/events/artifacts/sources)다. 아래 **10종류는 조회 내용의 분류**이며 각각 별도 테이블이 있는 것은 아니다. 현재 DB 명령/JSON으로 확인하며 HMI 개인별 화면은 미연결이다.

| 번호 | 조회 내용 | 저장·조회 형식 | 실제 포함 내용 |
|---|---|---|---|
| 1 | 사용자 계정 | users 행 / JSON 목록 | 사용자 번호, 로그인 ID, 표시 이름, 생성 시각. 비밀번호/해시는 일반 조회에서 제외 |
| 2 | 전체 작업 목록·결과 | jobs 식별 + events에서 계산한 JSON | Job, 기록된 시작/완료 시각, 완료 여부, 이벤트 수 |
| 3 | 채택 Design | artifacts의 DESIGN / JSON 객체 | Job, design_version, 블록의 종류·색상·x/y·층·방향 |
| 4 | 채택 Plan·Step | artifacts의 PLAN / JSON 객체와 steps 배열 | plan_id, Design 버전, 기준 revision, Step 순서·목표·선행 조건 |
| 5 | Current 기록 | BASE_CURRENT 및 CURRENT_ADOPTED 원문 / JSON | Plan 채택 당시 기준 배치와 기록된 실제 채택 배치·revision |
| 6 | Observed 근거 | CURRENT_ADOPTED 안의 observed / JSON | 채택 근거로 남은 visible_blocks, verified_regions, check_id, observation_seq, 상태·사유 |
| 7 | 이벤트 타임라인 | events 행 / 시간순 JSON 목록 | 전달 요청/결과, Step 확인, 의도 질문/응답, 정지 등과 관련 Job·Plan·Step·요청 |
| 8 | 대기·보류·오류 사유 | events에서 계산한 JSON 집계·episodes 배열 | 정상 조립 대기, 의도 확인, 관측 불가, Robot 실패 등의 사유·구간 수·반복 증거 수 |
| 9 | 기록 구간의 소요 시간 | events에서 계산한 JSON 숫자 또는 null | 작업 시작→완료, Robot 요청→결과, 전달→조립 확인 등. 끝이 없으면 null |
| 10 | 원본·적재 상태 | sources/events 행 / 원본 문자열과 관리 조회 | 원본 상대 경로, 적재 완료 행, 행별 원문·해시. 공정 Step 진도와 구분 |

Expected는 현재 Backend의 비교 계산값이며 독립 저장 자료로 추가하지 않았다. Observed는 기존 주요 채택 이벤트에 포함된 것만 보관하고 모든 프레임을 기록하지 않는다. JSON 보고서는 위 작업·자료·타임라인·집계 결과를 묶은 출력 형식이다. 개인별 도안 이름·즐겨찾기·소유자 필터 등은 아직 없다.

## 2026-10-06 — DB 내부 의미별 조회와 JSON 검사 보완

PostgreSQL·Job별 JSONL·별도 적재를 유지하면서 시율의 Design/Current/Plan/HRI 분류를 조회 기능에 반영했다. 기존 다섯 테이블에서 읽어 계산하므로 새 테이블·ALTER·데이터 초기화·계정 변경은 없다. C/A/B/D·Qt·Robot의 생산 계약과 실행 코드는 변경하지 않는다. 계정과 Job 소유자 연결, 개인 도안, 로그인 세션, 자동 복원은 이번 범위에 포함하지 않는다.

다음 명령은 위 시험 환경에서 저장된 Job UUID로 실행한다. DB에 적재한 기록까지 조회하며 실행 중 Backend 상태를 직접 읽지 않는다.

```bash
docker compose --env-file logs/history_validation.env -p c2-history-test -f compose.history.yaml run --rm app designs <JOB_UUID>
docker compose --env-file logs/history_validation.env -p c2-history-test -f compose.history.yaml run --rm app currents <JOB_UUID>
docker compose --env-file logs/history_validation.env -p c2-history-test -f compose.history.yaml run --rm app plans <JOB_UUID>
docker compose --env-file logs/history_validation.env -p c2-history-test -f compose.history.yaml run --rm app hri <JOB_UUID>
```

| 명령 | 출력과 근거 |
|---|---|
| designs | PLAN_ADOPTED만 대상으로 Job/버전별 전체 Design·최초 채택 시각·각 Plan의 채택 근거를 반환. 후보 C 응답은 채택 자료로 취급하지 않음 |
| currents | PLAN_BASIS와 OBSERVATION_ADOPTED를 구분하고 revision·실제 배치·관측/check/촬영 순번 반환. 같은 revision의 기준 스냅샷·반복 채택 근거도 보존 |
| plans | Plan·고정 기준 Current·목표 버전·기준 revision·채택 근거·다음 Plan으로 교체된 시각/ID 반환. 정상 Current 증가는 Plan 교체가 아님 |
| hri | Job/요청 ID로 요청 당시 Design/Current/Difference·질문·C 원문 응답·채택 의도·호출 실패를 연결. 각각 근거 시각/파일/행을 포함 |

plans의 `is_last_adopted`는 적재 기록상 마지막 채택 Plan이다. 완료·정지 뒤에도 마지막 채택 이력은 남으므로 실시간 active 상태를 뜻하지 않는다. `superseded_at`은 다른 Plan의 채택 사건으로 계산하고 동일 Plan의 반복 기록은 adoptions 근거에 보존한다. 작업 종료만으로 교체 시각을 만들어 넣지 않는다.

hri의 record_status는 INTENT_RECORDED / C_RESPONSE_RECORDED / FAILURE_RECORDED / NO_RESPONSE_RECORDED다. C_RESPONSE_RECORDED도 C 원문의 status가 FAILED/CANCELLED일 수 있으므로 성공으로 해석하지 않는다. UNCLEAR 이후 새 요청에 문맥 스냅샷이 없으면 이전 질문의 문맥을 자동 복사하지 않는다. 문맥 누락은 null, 미기록 질문·응답은 빈 배열이며 사용자의 원래 발화를 기록에 없는데 생성하지 않는다. report JSON에도 네 분류를 포함한다. 기록 없는 Job의 새 조회는 빈 배열을 반환한다.

[로그 Schema](../history/log.schema.json)는 기존 이벤트 봉투와 조회가 소비하는 결과 형식을 정의하고 [공통 Schema](../interfaces/schemas/day4.schema.json)를 참조한다. Schema ID의 log-v1은 형식 식별이며 Design의 목표 변경 버전과 다르다. 기존 메시지에 schema_version 필드를 강제 추가하지 않는다. `https://schemas.c2.invalid/`는 식별 전용 URI이며 외부 서버에서 가져오지 않는다. 검사에서는 day4.schema.json 참조를 로컬 공통 Schema에 연결한다.

적재부는 Python 표준 처리와 기존 Consumer 검사 함수로 실행한다. JSON Schema 검사는 로컬에 이미 설치된 jsonschema로 단위 시험에서 수행하며 신규 실행 의존성을 추가하지 않았다. 검사 범위는 새 조회의 필드·타입·요청/check/버전 연결이며 실시간 최신성이나 실제 조립 완료를 DB에서 재판정하지 않는다. 기존 C 응답에서 생략된 진단 필드는 허용하고 알 수 없는 이벤트 원문도 보존한다. C 후보의 범위 위반은 A/D 진단 근거이므로 보존하며, 최종 채택 Design·Plan·Current에는 기존 채택 자료 검사를 적용한다. 오류는 파일/행/사유를 반환하고 파일 트랜잭션을 rollback한다. 이미 적재된 기록을 수정하지 않는다.

추가 단위 검사는 tests/unit/test_history_views.py다. 기존 tests/integration/test_history_db.py에 네 CLI·보고서 일치, C 실패 원문/문맥 누락, 새 입력 검사 실패/재적재 검사를 추가했다. 최신 실행 수치와 컨테이너 증거는 STATUS의 이번 항목과 logs/history_reports/views-container-validation.json을 따른다.

계정 독립 검사는 `tests/unit/test_accounts.py`, 실제 PostgreSQL 검사는 `tests/integration/test_accounts_db.py`다. 신규 account fixture는 트랜잭션 rollback으로 격리해 실제 다섯 계정에 섞지 않는다. 최종 결과는 [STATUS](STATUS.md)에 기록한다. 계정표/해시/명령/검사와 직접 관련 안내만 추가했으며 HMI·공정 코드·장치·의존성은 변경하지 않았다.
