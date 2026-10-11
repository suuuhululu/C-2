# 다른 컴퓨터 실행·의존성 가이드

대상: C2_DB_20261011에서 이식한 이 저장소의 DB 소스. 코드와 새 DB를 실행하는 안내이며 기존 PC의 계정·작업 데이터는 압축본에 포함되지 않습니다. 권장 실행 방식은 Docker입니다. HMI·웹·Robot·Camera와 연결하는 안내는 별도 개발 범위입니다.

## 1. 필요한 프로그램과 코드 의존성

| 항목 | Docker 실행 PC에 별도 설치 | 압축본에서 사용하는 구성 | 목적 |
|---|---|---|---|
| Docker + Docker Compose | 필요 | Compose V2 형식의 `docker compose` 명령 | DB와 적재 앱 실행 |
| Python | 불필요 | app 이미지 `python:3.12-slim` | DB 명령·JSON 검사 |
| PostgreSQL | 불필요 | db 이미지 `postgres:17-bookworm` | 이력·계정·소유권 저장 |
| psycopg | 불필요 | 앱 이미지에서 `psycopg[binary]==3.3.6` 설치 | Python–PostgreSQL 연결 |
| 공통 Python 코드 | 불필요 | 압축본 app/·planning_trial/ | 기존 기록 검사 및 장치 없는 FAKE 예시 생성 |
| pytest·jsonschema | DB 실행에는 불필요 | 호스트에서 독립 시험할 때 설치 | 테스트·Schema 검사 |
| ROS2·Qt·CUDA·Camera·Robot driver | 불필요 | 이번 DB 실행 범위에서 사용하지 않음 | 실제 장치·HMI는 미연결 |

`history.records/final_mvp → app.contracts/completion/current`를 참조합니다. `history.mock_record → app.backend/jsonl_log → app.hmi_contracts/replan`도 참조하며, Backend의 지연 연결 import에 필요한 `app.planning_connection → planning_trial.planner`까지 넣었습니다. 다른 PC의 C_2 저장소나 현재 PC의 절대 경로 없이 이 압축본만으로 해당 코드가 import되도록 구성했습니다.

모든 내부 코드는 원본에서 복사한 현재 스냅샷입니다. 배포본의 Dockerfile·dockerignore만 planning_trial을 빌드에 포함하도록 보완했습니다. 원본의 상태와 변경 내역은 SOURCE_MANIFEST.json에서 구분합니다. DB 서비스와 앱 사용자는 별개입니다. `.env`의 DB 비밀번호는 PostgreSQL 접속용이며 `create-user`에 입력하는 비밀번호는 개인 로그인용입니다.

## 2. PC 준비

Windows/macOS는 [Docker 공식 설치 안내](https://docs.docker.com/get-started/get-docker/)에서 해당 OS의 Docker Desktop을 설치·실행하고 Linux 컨테이너 환경을 사용하세요. Linux는 같은 안내의 Docker Engine/Compose 또는 Desktop 설치 방법을 따르세요. 실행 사용자가 Docker를 사용할 수 있어야 합니다.

먼저 저장소를 내려받고 **compose.history.yaml이 있는 저장소 루트**를 터미널의 작업 위치로 설정합니다. 동기화/네트워크 드라이브보다 사용자에게 쓰기 권한이 있는 로컬 폴더를 권장합니다. 다음 두 명령이 성공해야 합니다.

```text
docker version
docker compose version
```

처음 빌드에는 Python/PostgreSQL 이미지와 Python 라이브러리를 내려받을 인터넷 연결이 필요합니다. 이 ZIP은 오프라인 Docker 이미지 묶음이 아닙니다. macOS의 Apple Silicon이나 Windows의 실행 환경은 해당 PC에서 빌드·정상 반환을 확인해야 합니다. 실제 검증은 Linux x86_64에서 수행했으며 다른 OS/CPU에서 시험했다고 표시하지 않습니다.

## 3. 운영체제별 환경 설정

Linux/macOS:

```bash
cp .env.history.example .env
mkdir -p logs/history_reports
id -u
id -g
```

Windows PowerShell:

```powershell
Copy-Item .env.history.example .env
New-Item -ItemType Directory -Force logs/history_reports
```

텍스트 편집기로 `.env`를 열어 다음을 설정합니다.

| 설정 | 값/주의 |
|---|---|
| HISTORY_DB_PASSWORD | 새 PC에서 사용할 DB 접속 비밀번호를 직접 입력. 기본값은 비어 있음 |
| HISTORY_DB_NAME | 처음 시험은 c2_history_test. 운영 DB와 분리 |
| HISTORY_DB_PORT | 기본 예시는 55449. 이미 사용 중이면 빈 포트로 변경 |
| HISTORY_LOG_DIR | ./logs. 사용자 JSONL 입력을 여기에 복사 |
| HISTORY_REPORT_DIR | ./logs/history_reports. 앱이 보고서·FAKE 예시를 쓸 폴더 |
| HISTORY_UID/HISTORY_GID | Linux는 위 id 명령의 숫자로 설정. macOS는 파일 쓰기 권한을 확인하고 필요한 값을 설정. Windows Desktop은 예시값 1000/1000으로 먼저 확인 |

비밀번호 값에 `$` 등 Compose 해석 문자가 있으면 `.env`에서 작은따옴표로 감싸 리터럴 값을 사용하세요. [Compose 환경변수 공식 안내](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)를 참고하세요. 셸에 남아 있는 같은 이름의 HISTORY_* 환경변수는 파일 값을 덮어쓸 수 있으므로 이전 프로젝트의 값이 적용되지 않는지 확인합니다. 실제 `.env`·접속 DSN은 공유하지 않습니다.

## 4. 처음 실행과 계정 생성

아래 명령은 세 OS에서 동일합니다. 먼저 Docker 앱/서비스가 켜져 있어야 합니다.

```text
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml up -d --wait db
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml build app
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml run --rm app init
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml run --rm app create-user test 테스터
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml run --rm app check-user test
```

사용자 비밀번호를 숨겨 입력합니다. check-user 성공은 인증 확인이고 HMI 세션 생성이 아닙니다. 기존 PC의 수현·세은·시율·홍동·test 계정은 자동으로 옮겨지지 않습니다. 필요하면 create-user 명령으로 각각 새 계정을 생성합니다. 비밀번호 seed 파일은 제공하지 않습니다. init은 Schema 생성과 미적용 SQL 변경을 적용하며 기존 자료를 지우지 않습니다.

## 5. 장치 없이 동작 확인

실제 로그가 없으면 다음으로 **기존 Day4 FAKE 예시**를 생성합니다. 장치를 호출하지 않습니다. 최신 MVP 전체 공정을 시뮬레이션한 결과와는 구분합니다.

```text
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml run --rm --entrypoint python app -m history.mock_record --directory /reports/demo
```

출력의 job_id를 복사합니다. 다음 명령의 JOB_UUID를 그 값으로 치환합니다. `< >` 표시는 실제 명령에 입력하지 않습니다. HISTORY_REPORT_DIR를 예시와 다르게 설정했다면 로그 입력 경로도 맞춰야 합니다.

```text
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml run --rm app ingest --source-root /records /records/history_reports/demo/JOB_UUID.jsonl
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml run --rm app bind-job JOB_UUID test --reason owner_verified_for_demo
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml run --rm app my-jobs test
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml run --rm app my-designs test
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml run --rm app my-job test JOB_UUID
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml run --rm app save-job test JOB_UUID --save-key demo-save-01
```

소유자 배정은 관리자가 확인한 작업에만 합니다. 로그의 user_id만으로 소유자가 설정되지 않습니다. 같은 저장 키·같은 내용은 중복 저장하지 않고, 그 키로 다른 작업/내용을 저장하면 오류입니다. 새 스냅샷에는 새 저장 키를 씁니다. save-job 성공이 조립 성공이나 웹 표시 성공을 뜻하지 않습니다.

동일 ingest를 다시 실행하면 inserted=0이고 기존 행은 skipped입니다. 실제 최신 MVP 보관 형식의 JSONL에만 `ingest --contract final-mvp-20261008`을 선택합니다. 같은 source를 이미 적재한 뒤 계약 이름을 바꿀 수 없습니다. 새 형식은 [DB 안내](D_DB_HISTORY.md)의 최신 절과 Schema를 참고하세요.

## 6. 저장·중지·다른 PC로 이동

DB 데이터는 Compose의 named volume에 있고, JSONL·보고서는 logs/ 아래에 있습니다. 이후 실행에서도 같은 `-p c2-db-bundle`을 사용해야 기존 볼륨에 연결됩니다. 프로젝트명이 다르면 다른 DB 볼륨으로 실행될 수 있습니다.

```text
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml stop db
docker compose --env-file .env -p c2-db-bundle -f compose.history.yaml up -d --wait db
```

ZIP만 다른 PC에 복사하면 **코드만 이동**합니다. 기존 사용자 계정·소유권·저장 확인까지 옮기려면 별도 PostgreSQL 백업/복원이 필요합니다. JSONL만 옮기고 재적재하면 기록은 가져올 수 있지만 사용자 계정·관리자 소유권 배정·저장 확인은 자동 복원되지 않습니다. 초기화 목적으로 `down -v`나 volume 삭제를 실행하지 마세요.

## 7. Docker 없이 Python으로 실행하는 선택 경로

Python 3.12, 별도 PostgreSQL 17, Python 패키지가 필요합니다. Python은 운영체제별로 별도 설치해야 하며 기존 시스템 Python 대신 전용 환경을 권장합니다. [psycopg 설치 안내](https://www.psycopg.org/psycopg3/docs/basic/install.html)를 참고하세요.

Linux/macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-history.txt
# 시험할 때만 추가
python -m pip install pytest jsonschema
python -m pytest tests -q
```

Windows PowerShell (venv 활성화 정책 변경 없이 직접 실행):

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-history.txt
.venv/Scripts/python.exe -m pip install pytest jsonschema
.venv/Scripts/python.exe -m pytest tests -q
```

위 설치 명령은 사용자가 선택한 새 환경에서 실행할 명령입니다. 실제 DB 명령은 HISTORY_DATABASE_DSN 또는 PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD를 별도로 설정해야 합니다. Compose의 .env를 호스트 Python이 자동으로 읽지는 않습니다. DB 연결은 `python -m history init`으로 확인합니다. 시험 DSN은 HISTORY_TEST_DSN으로 지정하며 DB명은 `_test`로 끝나야 합니다. 미지정이면 실제 PostgreSQL 시험 33개가 skip됩니다. 단위 통과만으로 DB 연결 성공이라고 표시하지 않습니다.

## 8. 자주 만나는 오류

| 증상 | 확인·조치 |
|---|---|
| docker 명령 없음 / daemon 연결 실패 | Docker 설치·앱/서비스 실행·실행 사용자 권한 확인 |
| HISTORY_DB_PASSWORD required | `.env` 복사 여부와 빈 비밀번호 수정 |
| port already allocated | HISTORY_DB_PORT를 빈 포트로 변경 |
| permission denied 또는 보고서 작성 실패 | logs/history_reports 쓰기 권한과 UID/GID, Desktop 파일 공유 설정 확인 |
| DB connection/query failed | DB 서비스 상태·DB명/계정/비밀번호·init 실행 확인. 원본 로그는 유지 |
| 로컬 Python의 No module named psycopg | 해당 Python 환경에서 requirements-history.txt 설치. Docker 실행은 호스트 설치 불필요 |
| 원본 행 변경 / 계약 변경 / save_key 충돌 | 원본을 덮어쓰지 말고 오류를 확인. 다른 원본/새 스냅샷에 별도 source/새 저장 키 사용 |
| 개인 이력 빈 목록 | 인증 계정과 Job 소유권 배정 확인. 새 PC에 실제 데이터가 자동 전달되지 않음 |
| 계정/자료가 사라진 것처럼 보임 | Compose 프로젝트명·볼륨·DB명 일치 여부 확인. volume 삭제나 계정 재설정으로 해결하지 않음 |

실행 안내대로 진행한 새 PC의 init·FAKE 예시 생성·적재·인증·개인 조회·저장·재적재 결과를 확인한 뒤 사용하세요. 현재 검증 대상 OS와 이번 압축본 실제 시험 결과는 [압축본 검증](D_HMI_DB_ROUND1.md)을 참고하세요.
