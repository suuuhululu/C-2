# A README 재현·보존 확인 — 2026-10-12

## 기준과 변경 범위

- 소스 기준: `codex/integration-round1 @ 1b8204050521303f18c5538ec1cc392b447e522f`.
- 정리 branch: `codex/a-documentation-classification-20261012`.
- 루트 A 링크, 현재 A README, 원문 README 보존, 자료 분류·SHA 목록, 이 검증 기록과 STATUS만 변경한다.
- 기존 A 계산·계약·설정·Fixture·실측·모델·테스트·Git 이력은 변경하지 않는다.
- 미게시된 Isaac 계약 정렬 `eb78ad7`은 포함하지 않는다.

## 새 사본과 환경

현재 통합 소스에서 만든 문서 branch의 `b588c05`를 로컬 Git에서 **새 clone**으로 받았다. 별도 가상환경에 설치했으며 기존 worktree의 Python 패키지를 공유하지 않았다. 후속 문서 갱신은 계산 소스를 바꾸지 않는다. GitHub 게시 후 원격 clone에서도 동일 예제·보존 경로를 확인한다.

실행한 clone 명령의 로컬 원본 경로는 이 PC의 문서 worktree였다:

```bash
git clone --depth 1 --single-branch --branch codex/a-documentation-classification-20261012 file:///home/rokey/Documents/ChatGPT/협동2/tmp/a-documentation-classification-20261012 /home/rokey/Documents/ChatGPT/협동2/tmp/a-docs-fresh-clone-20261012
```

재현 환경: Ubuntu 24.04, Python3.12.3, pip24.0, jsonschema4.10.3, pytest7.4.4.
기본 `python3 -m venv .venv`는 ensurepip 미설치로 종료 코드1이었다. 시스템 패키지/전역 Python을 바꾸지 않고 README의 대안으로 준비했다:

```bash
unset PYTHONPATH
python3 -m venv --without-pip .venv
python3 -m pip --python .venv install pip==24.0 jsonschema==4.10.3 pytest==7.4.4
. .venv/bin/activate
python3 -m pip check
```

설치·pip check 종료 코드0, `No broken requirements found.`.
A에 ROS Python 경로가 섞이지 않도록 테스트 shell에서 PYTHONPATH를 해제하고 pytest 플러그인 자동 로딩을 비활성화했다.
numpy/scipy/Qt/ROS/Isaac/FCL을 가상환경에 설치하지 않았다. sudo/apt, 드라이버 시작, overlay 변경은 수행하지 않았다.

## 실제 명령과 결과

저장소 루트에서 다음을 실행했다. 생성 결과는 Git 제외 reports에 저장하고 기존 입력·sample 출력은 덮어쓰지 않았다.

```bash
mkdir -p reports/a-readme/basic
python3 planning_trial/planner.py planning_trial/sample_design.json --output reports/a-readme/basic/plan.json
```

종료 코드0. S01~S12 PLACE 및 Plan JSON 생성. 층별 개수 `1:4 / 2:4 / 3:2 / 4:2`.
다음 정상 실패 반환도 종료 코드0으로 확인했다:

```bash
python3 - <<'PY'
from planning_trial.planner import plan_from_current
from planning_trial.assembly_api_fixtures import whole_request
request = whole_request()
result = plan_from_current(request["design"], {"current_revision": -1, "blocks": []})
assert result["status"] == "INVALID" and result["plan"] is None
print(result)
PY
```

실제 결과: `status=INVALID / plan=null`, errors의 `Current.current_revision must be a nonnegative integer`, `block=null`.

```bash
python3 -m planning_trial.run_assembly_apis --actor agent --output-dir reports/a-readme/api-run
```

종료 코드0. `Checks: 34/34 PASS; actor=agent; no robot/D/Isaac execution`.
전체 계획 READY → 재평가 CANDIDATE → 이동 후보 CANDIDATE, 같은 Plan의 다음 Step, 부분 Current 재계획과 남은0단계를 확인했다.
실패 사례에는 NEEDS_CORRECTION, INVALID, INVALID_CONTEXT, NO_FEASIBLE_ORDER, 잘못된 예약/평가/프로필의 BLOCKED, 오래된 결과 IGNORE_STALE_RESULT가 포함된다.
모든 계산 반환의 execution_allowed=false와 로컬 소비 검사 robot_commands_issued=0를 확인했다.

`23_common_b_d_bundle/distribution_refs.json`의 B/D file·SHA256·Plan ID는 동일했다.
로컬 자료 일치 검사이며 실제 B/D 배포/수신 성공이 아니다. Plan ID는 실행마다 달라질 수 있다.
이 실행의 API 보고서 시각은 `2026-10-12T11:23:03.657448+00:00`, report.json SHA256은
`347e74365954593a7b5934b70f79bc42c618e462478a042ef769c39d66dea040`이다. raw 입력·반환은 위 명령으로 재생성할 수 있다.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest planning_trial -q -p no:cacheprovider --junitxml=reports/a-readme/planning-tests.xml
```

종료 코드0. **448 passed, 1 skipped in 6.66s**. 루트 전체·C/D·SIM 시험이 아니다.
제외된 검사는 `test_world_z_grip_rotation_is_not_a_rotation_matrix_from_swapped_grid_labels`이며 독립 비교 라이브러리 `scipy.spatial.transform`이 최소 환경에 없어서 기존 importorskip이 적용됐다. SciPy 설치 환경의 과거 시험을 이번 결과에 합산하지 않는다.
API34 검사와 pytest448 검사는 범위가 겹치므로 합산하지 않는다.

## 보존·문서 확인

- manifest253파일의 보존 경로 존재·SHA256이 기준 커밋과 모두 일치했다.
- 이전 planning_trial/README.md 457줄이 A_README_HISTORY_1b820405.txt와 바이트 단위로 일치했다.
- 분류: 현재 코드31, 예제·검사58, 외부 모델/실측·분석·참고104, 과거 보존60.
- 기존 253파일 가운데 현재 안내로 다시 쓴 README는 원문 사본으로 보존했고, 나머지 파일은 기존 경로·바이트를 유지했다.
- 새 안내의 상대 링크와 Git diff 공백 검사를 확인했다.
- 원본·라이선스·실측·보정 JSON 변경, 파일 이동·삭제, Git 이력 재작성·force push는 없다.

보존 목록은 [manifest](A_PRESERVATION_MANIFEST_20261012.json), 의미·사용 조건은 [분류 안내](A_MATERIALS_AND_PRESERVATION.md), 현재 사용법은 [A README](../planning_trial/README.md)에 있다.

## 별도 작업과 미검증

- 기준 1b820405에서 Isaac 요청0.5 / 현재A0.5.1 불일치 및 제거된 함수 import는 별도 기능 수정 대상이다. 문서 정리로 해결했다고 표시하지 않는다.
- 직접 B/D 수신·자동 승인, 현장 수동 Current와 실제 배치 대조, 공급 슬롯 보정은 미검증.
- ROS/MoveIt 설치·빌드·trajectory 계산/실행, Isaac 물리, 실제 로봇·그리퍼·힘·mode/controller 변경·제어권 요청, Contact 인계·체결 성공은 이번에 수행하지 않았다.
- 전체 팀 root pytest, Camera, LLM/STT/TTS, PostgreSQL, HMI/DB/Web end-to-end는 수행하지 않았다.
- 외부 Release 업로드/다운로드·출처와 라이선스의 법적 판정·모델 설치 환경의 재구축은 미검증이다.
- 공식 설치 링크는 안내 출처다. ROS 공식 페이지는 자동 조회에서 접근 제한이 있었으며 링크 전체의 HTTP 접속 성공이나 실제 설치 성공을 주장하지 않는다.
- integration 병합과 사람 리뷰는 별도 단계다.
