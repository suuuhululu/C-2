# A — 계획·사람 도움·이동 후보 계산

기준: `codex/integration-round1 @ 1b8204050521303f18c5538ec1cc392b447e522f` (2026-10-12).
이 문서의 자료 정리 변경은 계산·계약·보정값을 바꾸지 않는다. [자료 분류·보존 안내](../docs/A_MATERIALS_AND_PRESERVATION.md)와 [이번 재현 결과](../docs/A_DOCUMENTATION_VERIFICATION_20261012.md)를 함께 확인한다.

## 현재 사용하는 코드와 지원 범위

A 계산은 이 폴더의 단일 코드로 CPU·SIM·REAL 호출부가 공유한다. Fixture는 입력 예제이며 별도 Planner가 아니다.

| 진입점 | 입력과 결과 | 사용 목적 |
| --- | --- | --- |
| `planner.plan_from_current(design, current)` | Design + Current → `status / plan / errors` | 기존 기본 PLACE 순서·남은 작업 계산. 아래 CLI도 이 계열의 기본 계산 |
| `assembly_adapter.handle_whole_plan(request)` | WholePlanRequest → 전체 Plan·작업 방식·사람 도움·공통 계획 자료 | 확장 조립 후보 API |
| `assembly_adapter.handle_step_reassessment(request)` | 동일 Plan + 최신 Current → 단계 실행 전 평가 | 오래된 상태·방식·참조 불일치 검사 |
| `assembly_adapter.handle_step_motion(request)` | 평가 결과 + 공급 예약 + 로봇 상태 + 좌표 프로필 → 이동 후보 | waypoint 계산. MoveIt 궤적 계산·장치 실행 시간은 포함하지 않음 |
| `python3 -m planning_trial.run_assembly_apis` | 자체 제공 정상·실패 Fixture → 요청·원시 결과·반환·검사 보고서 | 장치 없는 전체 API 예제 |

계약은 `assembly-ad-calculation-draft/0.5.1`, 공통 계획 자료는 `a-b-d-planning-bundle-draft/0.1.1`이며 둘 다 초안이다. 모든 확장 A 반환의 `execution_allowed=false`를 유지한다. 구현 상세는 [계획 정책](../docs/A_ORDER_SEARCH_POLICY_20261012.md)을 본다.

- 24×24 stud, 정수 layer 1~5, Design 1~40블록.
- 노랑·파랑 `2x2x1 / 2x3x1`, 빨강 `1x2x1`. `x / y`는 점유 영역의 최소 모서리이며 stud 단위다. `orientation_deg`는 0/90도이고 2×2는 0도다.
- 확장 계획의 새 기본 입력은 낮은 층을 모두 완료한 뒤 다음 층으로 진행한다. 상태 수 제한은 적용하지 않는다. 도움 최적화의 30초 기준은 전체 응답 시간 상한이 아니다.
- 확장 API 지원 방식은 `ROBOT_GRIP / HUMAN_ASSEMBLY`. 사람 도움에는 지지·눌러주기·직접 조립이 포함될 수 있다. `ROBOT_RELEASE_PRESS`를 실행 가능한 방식으로 추가하지 않는다.
- 사람 손 접근 공간 검사는 제외되어 `HUMAN_ACCESS_NOT_CHECKED`로 표시한다. 사람 손 수의 최대 2개 제한도 제거했으며 필요한 손 수와 HOLD/PRESS/MANUAL_PLACE는 그대로 반환한다. 지지·겹침·삽입·로봇 접근 검사는 유지한다. D는 실제 도움 인원과 준비 응답을 관리한다.
- Current에 이미 조립된 블록을 보존하며 자동 제거·분해·설계 수정 계획을 만들지 않는다. 모든 설계의 성공을 보장하지 않으며 실제로 불가한 입력은 실패를 반환한다.

## 환경 준비 — 장치 없는 A 예제

시험 환경은 Ubuntu 24.04 / Python 3.12.3, `jsonschema==4.10.3`, `pytest==7.4.4`이다.
기본 Planner CLI는 표준 라이브러리만 사용하지만 확장 API는 jsonschema가 필요하다. 아래 A 전용 재현에는 Qt·ROS·Isaac·GPU·DB·카메라·로봇·외부 API 키가 필요 없다.

처음 저장소를 받는 경우:

```bash
git clone --branch codex/integration-round1 https://github.com/suuuhululu/C-2.git
cd C-2
git rev-parse HEAD
python3 --version
unset PYTHONPATH
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install jsonschema==4.10.3 pytest==7.4.4
python3 -m pip check
```

현재 정리 PR을 검토하는 동안은 같은 저장소의 `codex/a-documentation-classification-20261012` 브랜치를 받으면 이 안내를 읽을 수 있다. integration의 후속 변경은 이 문서에 기록한 기준 커밋과 구분한다.
Ubuntu에서 venv 기능이 없으면 `sudo apt install python3-venv`로 준비한다. 가상환경은 로컬 Git 제외 자료다.

이 PC처럼 `ensurepip`가 없지만 전역 pip 22.3 이상이 있는 경우에는 **가상환경 활성화 전** 아래 대안을 사용한다. 설치 대상은 `.venv`이며 전역 Python을 수정하지 않는다. 이미 ROS 환경을 source한 터미널이면 `unset PYTHONPATH`로 A 예제에 ROS Python 경로가 섞이지 않게 한다.

```bash
unset PYTHONPATH
python3 -m venv --without-pip .venv
python3 -m pip --python .venv install pip==24.0 jsonschema==4.10.3 pytest==7.4.4
. .venv/bin/activate
python3 -m pip check
```

이 대안은 [pip의 다른 Python 환경 관리 방법](https://pip.pypa.io/en/stable/topics/python-option/)을 따른다. 이번 재현에서는 이 방법을 사용했으며 sudo/apt 설치는 수행하지 않았다.

설치 근거: [Python 3.12 venv](https://docs.python.org/3.12/library/venv.html), [jsonschema 4.10.3 설치 안내](https://python-jsonschema.readthedocs.io/en/v4.10.3/#installation). 루트 `requirements.txt`는 Qt용이고 `requirements-test.txt`는 Qt 의존성을 함께 가져오므로 최소 A 예제에서는 위 두 패키지만 설치한다. 이번 정리는 의존성 파일이나 설치된 장치 환경을 변경하지 않는다.

## 예제 1 — 기본 Plan 생성

저장소 루트에서 실행한다. 출력은 원본 예제를 덮어쓰지 않도록 Git 제외 폴더에 저장한다.

```bash
mkdir -p reports/a-readme/basic
python3 planning_trial/planner.py planning_trial/sample_design.json --output reports/a-readme/basic/plan.json
```

예상 결과: 임의의 12블록 설계에서 S01~S12 PLACE를 출력하고 `plan.json`을 생성한다. 층별 개수는 1층 4개 → 2층 4개 → 3층 2개 → 4층 2개다. Plan ID는 호출마다 달라질 수 있다. 사진의 의자나 실물 성공을 재현한 자료가 아니다.

실패 결과를 같은 코드로 확인하려면:

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

예상 결과: `INVALID`, `plan=null`, `errors`에 잘못된 revision 사유. CLI 자체의 잘못된 입력은 `INVALID_INPUT` 및 종료 코드 2, 출력 저장 실패는 `OUTPUT_ERROR` 및 종료 코드 2로 처리한다.

## 예제 2 — 전체 계획 → 재평가 → 이동 후보와 실패 반환

```bash
python3 -m planning_trial.run_assembly_apis --actor agent --output-dir reports/a-readme/api-run
```

출력 폴더는 매번 새 경로여야 한다. 기존 폴더를 다시 지정하면 프로그램이 거절하므로 새 이름을 사용한다.
예상 마지막 출력은 `Checks: 34/34 PASS; actor=agent; no robot/D/Isaac execution`이다. 각 사례의 실제 입력과 원시 반환도 저장된다.

| 생성 파일 예시 | 확인할 결과 |
| --- | --- |
| `01_initial/whole.request.json / whole.raw.json / whole.result.json` | `calculation_status=COMPLETED`와 `planning_result.status=READY`, 전체 Plan·도움·최적화 정보 |
| `01_initial/reassessment.result.json / motion.result.json` | `CANDIDATE`; 이동 후보와 waypoint. `execution_allowed=false` |
| `04_needs_correction/whole.result.json` | `NEEDS_CORRECTION`, 실행 가능한 Plan 없음 |
| `05_support_invalid/whole.result.json` | `planning_result.status=INVALID`, 오류 사유 |
| `20_no_supported_method/whole.result.json` | `NO_FEASIBLE_ORDER`; 허용된 작업 방식으로 완성 순서를 찾을 수 없음 |
| `07_wrong_slot/motion.result.json` 등 | `BLOCKED`; 잘못된 공급 예약·평가 참조·프로필의 이동 거절 |
| `report.json / run.log` | 실제 검사 목록·원본 소스 해시·시각·환경·명시된 미검증 범위 |

성공 여부는 `calculation_status` 하나만 보지 않고 `planning_result.status`도 함께 확인한다. 실패의 `stage_errors`, 원시 결과의 `optimization / blocked_candidates`가 있는 경우 그대로 보존한다. 준비된 이동 후보는 실행 승인이나 장치 명령이 아니다.

A 전체 회귀 검사는 다음과 같다. 이 명령은 루트의 모든 팀 시험을 실행하지 않는다.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest planning_trial -q -p no:cacheprovider
```

이번 최소 환경 결과는 448 passed / 1 skipped다. SciPy가 없어 독립 회전 행렬 비교1검사가 기존 importorskip으로 제외됐으며 A 계산 함수의 SciPy 의존성을 뜻하지 않는다. 상세 사유는 재현 기록을 본다.

## 동일 계획 자료의 B/D 공유와 Current

최신 운영 기준에서 **B가 Current/revision·Expected·비교를 확정하고 D가 중계**한다. A는 전달받은 Current로 계획을 계산하며 관측을 확정하거나 revision을 발급하지 않는다. D는 실행·진행·HMI/DB와 실제 배포를 담당한다.

`WholePlanResult.shared_planning_bundle`에 같은 Design·Plan·기준 Current·프로필·단계별 기대 배치와 digest를 묶는다. 기대 배치는 계획 기대값이며 실제 관측이 아니다. D는 이 동일한 자료를 B/D 소비 경계에 연결하고 Plan ID·기준 revision·프로필·digest·요청 최신성을 대조해야 한다.

예제 2의 `23_common_b_d_bundle/common_planning_bundle.json`과 `distribution_refs.json`은 B/D가 동일 파일·SHA·Plan ID를 참조하는 로컬 예제다. 실제 B/D 수신이나 자동 승인 완료 증거는 아니다. 예제 Current와 예약·정지·파지 상태는 Fixture다. 비전 없이 현장에서 사람이 확인한 시험용 Current도 B 관측 확정값과 구분하고 배치 변경 시 갱신해야 한다.

## Isaac·MoveIt과 외부 환경 — 별도 준비

A 계산 코드와 ROS 궤적 실행 연결은 구분한다. [Isaac SIM의 기존 안내](../isaac_sim/README.txt)는 당시 이관·실행 범위를 기록한 문서다.

| 대상 | 기록된 환경·설치 경로 | 현재 한계 |
| --- | --- | --- |
| ROS 2 | Ubuntu 24.04 / Jazzy. [공식 설치](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)에서 저장소 등록·설치·환경 설정 | 새 로봇 드라이버 실행이나 기존 overlay 변경은 이 안내의 재현 범위 밖 |
| MoveIt 2 | 기존 SIM 기록 2.12.4. [공식 Jazzy 설치](https://moveit.ai/install-moveit2/binary/): ROS 준비 후 `sudo apt install ros-jazzy-moveit` | apt의 현재 패키지가 기록된 2.12.4와 같다는 보장은 없음. 실제 설치 버전을 기록할 것 |
| Isaac Sim | GPU 원본 기록 6.1.0-rc.26. [공식 설치 안내](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_workstation.html) | latest 문서는 rc.26 설치본 제공·동일 환경 복원을 보장하지 않음. 기존 설치본을 임의 업데이트하지 않음 |
| SIM Python | [isaac_sim/requirements.txt](../isaac_sim/requirements.txt), 설치 예시는 해당 README | 일부 버전이 고정되지 않았으며 CPU에 FCL/pycollada 없음. 이번에는 설치·SIM 실행 미검증 |
| Doosan·RG2 모델 | [원본 출처 기록](../isaac_sim/assets/original_robot/source_manifest.json), 원본·변환 메시와 라이선스 | 설치된 드라이버나 활성 ROS 수신부를 뜻하지 않음. 전체 REAL 환경 준비는 D 안내와 확인 필요 |

**기준 1b820405의 Isaac 입력은 여전히 API 0.5이며 A는 0.5.1이다.** 기존 SIM 검사에는 제거된 함수 import도 남아 있다. 별도 수정 `eb78ad7`은 CPU/GPU 준비 검사에서 확인했지만 이 자료 정리 PR에는 포함하지 않는다. 입력·연결부 기능 정렬이 별도 반영되기 전에는 기존 SIM 명령이 정상 동작한다고 보고하지 않는다.

## 검증 범위와 보존 자료

이번 [재현 기록](../docs/A_DOCUMENTATION_VERIFICATION_20261012.md)은 새 로컬 clone·독립 가상환경에서 위 A 예제를 검증한 결과다. ROS·MoveIt 계획·Isaac 물리·카메라·실제 로봇·그리퍼·제어권 변경은 수행하지 않는다. A waypoint, SIM mock Current 갱신, 위치 도달을 실제 체결 성공으로 기록하지 않는다.

모든 기존 코드·설정·예제·외부 원본·실측·시험 기록을 같은 GitHub 경로에 유지한다. 기존 A README는 [원문 보존본](../docs/A_README_HISTORY_1b820405.txt)에 바이트 그대로 보존했다. 그 안의 D Current 채택·4층·과거 시험 수치는 당시 기록이며 현재 운영 안내가 아니다. [파일별 SHA·분류 목록](../docs/A_PRESERVATION_MANIFEST_20261012.json)에서 원본과 보존 경로를 확인할 수 있다.
