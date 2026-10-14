# 웹 도안 갤러리·DB 실행 안내 — 2026-10-12

**최신 2026-10-14:** 웹은 도안 중심으로 표시하고 원본 로그는 별도 보존한다.
신규 DB 적재 정책·보관 위치·재적재 규칙은 [원본 보존·DB 선별 적재](D_HISTORY_SELECTION.md)를 따른다.

## 반영 범위

현재 적용 대상은 `codex/integration-round2`다. 웹 기반은 2026-10-12의 `codex/integration-round1` (`02137d80ef28bab678e49855d7b6150219028881`)에서 시작했으며, 기존 계정·JSONL 적재·작업 소유권·개인 조회/저장 코드를 재사용한다. 현재 원본 보존·DB 선별·도안 중심 조회는 위 최신 안내를 따른다.

이번 변경에는 Qt HMI·HMI 로그인·새 작업 제작자 자동 연결·A/B/C 변경·로봇 실행기를 포함하지 않는다. `최종 통합용`의 실제 체결 시험 화면과 이 웹앱은 별도 경로이며, 시험 화면의 실행 목표 누적을 B Current로 간주하거나 DB에 자동 저장하지 않는다. 공개·조회 성공은 실제 촬영/조립/장치 검증이 아니다.

## 계정·저장·공개 의미

- 기존 DB 계정으로 로그인한다. 계정은 제작자 표시 및 자신의 도안 관리에 사용한다.
- 방문자는 로그인 없이 **공개된 도안**의 제작자명/ID와 3D 모형·층별 설계도를 볼 수 있다.
- 새 기록은 기본 비공개다. 제작자가 MY DESIGNS에서 PUBLISH / UNPUBLISH로 Job의 Design 버전별 공개 여부를 선택한다.
- 개인 Job 이력·대화·관측·로그 경로는 공개 API에 포함하지 않는다. 타 사용자 Job 조회·저장·공개 변경은 거절한다.
- DB 저장 확인은 공개 선택과 별개이며, 조립 완료를 새로 판정하거나 Robot을 실행하지 않는다.
- HMI가 DB와 연결된 경우 같은 DB를 지정해야 하지만, HMI 결선은 이번 PR 범위 밖이다.

## 실행

Python 3.12와 `requirements-history.txt`의 기존 psycopg 드라이버, PostgreSQL이 필요하다. 기존 Python 환경을 사용하거나 [DB 실행 안내](D_DB_OTHER_PC.md)에 따라 별도 환경을 준비한다. ROS·Qt·Camera·마이크·외부 LLM은 웹 실행에 필요하지 않다.

접속 정보는 실행 환경에 제공한다. 다음은 로컬 PostgreSQL의 예시이며 실제 DB 이름·포트·사용자는 설치 환경에 맞춘다. 비밀번호를 Git·명령 인자·공개 파일에 넣지 않는다.

```bash
export PGHOST=127.0.0.1
export PGPORT=55432
export PGDATABASE=c2_history_test
export PGUSER=c2_history
read -rsp 'PostgreSQL password: ' PGPASSWORD
echo
export PGPASSWORD
python3 -m history init
```

기존 `HISTORY_DATABASE_DSN`을 설정한 경우 그 DSN을 우선 사용한다. `init`은 기존 migration 적용 함수로 002 공개 테이블과 003 원본 보존·정책 메타데이터를 추가하며 계정·작업·이력을 초기화하지 않는다. 적용할 DB를 확인하고 기존 데이터는 별도 백업한다.

앱 계정이 없다면 다음 명령으로 생성한다. 각 명령에서 사용자 비밀번호를 숨겨 입력받으며, DB 접속 비밀번호와 앱 비밀번호를 구분한다. 이미 존재하는 계정은 기존 정책대로 덮어쓰지 않는다. 이 PR은 현재 PC의 계정 데이터나 비밀번호를 배포하지 않는다.

```bash
python3 -m history create-user tester 테스터
python3 -m history create-user suhyun 수현
python3 -m history.web --port 8765
```

브라우저에서 `http://127.0.0.1:8765/`를 연다. 공개 도안이 없는 새 DB에는 빈 갤러리를 표시한다. 임의로 시험 도안이나 계정을 자동 생성하지 않는다. 기존 JSONL 적재·Job 소유자 연결은 [DB 안내](D_DB_HISTORY.md)의 ingest/bind-job 절차를 사용한다.

웹 서버는 127.0.0.1 전용 로컬 서버다. 세션은 서버 메모리에서 30분간 유지되고 로그아웃/만료/서버 종료 시 인증이 필요하다. 외부 서비스 배포·HTTPS·다중 서버 운영은 검증하지 않았다. DB 연결/Schema/포트 오류는 명시적으로 실패하고 빈 정상 갤러리로 감추지 않는다.

## 검증 재현

웹은 새로고침 뒤에도 선택한 GALLERY / MY DESIGNS 보기를 유지한다. 목록 조회 중에는
Loading designs를 표시하며, 아직 응답을 받지 못한 상태를 빈 목록으로 표시하지 않는다.
개인 상세는 모형·층별 설계·제작자·완료·저장·공개 상태를 표시한다. 로그·대화·원본 경로는
표시하지 않으며, EXPORT DESIGN JSON은 선택한 Design 버전만 내보낸다.
전체 DB 기록의 운영 CLI·인증된 전체 API는 유지한다. 신규 source는 진단 샘플을 선별 적재하고
원본 JSONL을 별도 보존하며, 기존 DB 이벤트는 삭제하지 않는다.

운영 DB가 아닌 이름이 `_test`로 끝나는 별도 DB의 DSN을 `HISTORY_TEST_DSN` 환경변수에 제공한다. pytest/jsonschema는 기존 프로젝트 검사 환경을 사용한다.

```bash
PYTHONPATH=.:tests/unit:tests/integration python3 -m pytest \
  tests/unit/test_history.py tests/unit/test_history_views.py \
  tests/unit/test_history_selection.py tests/integration/test_history_selection_db.py \
  tests/unit/test_history_final_mvp.py tests/unit/test_accounts.py \
  tests/integration/test_history_db.py tests/integration/test_accounts_db.py \
  tests/integration/test_history_personal_db.py tests/integration/test_history_web.py -q
node tests/web/test_design_rendering.cjs
node tests/web/test_design_navigation.cjs
node --check history/web_assets/app.js
```

DB DSN이 없으면 PostgreSQL 검사는 skip하며 전체 DB 통과가 아니다. 웹 검사는 실제 PostgreSQL Fixture와 로컬 HTTP 서버를 사용하고 각 사례의 계정/Job/공개 기록은 rollback한다. 프런트 검사는 실제 SVG/UI 함수를 DOM 대역으로 실행하며 브라우저·실제 조립 검증을 대신하지 않는다. 최신 검사 결과는 [STATUS](STATUS.md)의 이번 웹·DB PR 절을 따른다.
