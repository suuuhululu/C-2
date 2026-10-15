# Round3 다른 PC·새 채팅 인계 — 2026-10-15

대상 브랜치는 `codex/integration-round3`다. 로봇 제어 기반은 `93ef967869065abb971e690aae44c3fe45e468bc`, 공급판 RGB-D XY 연결은 그 부모 `bda07e5`다. 이번 인계 커밋의 정확한 SHA는 압축본의 `handoff-manifest.json`과 `C2-round3.bundle`에 기록한다. 요청 범위는 로컬 커밋과 파일 전달이며 원격 push/PR/merge는 별도로 수행하지 않는다.

최종 서비스 목표는 로그인→C 대화·미리보기·별도 승인→A 계획→D 실물 조립→B 매 Step 비교→차이/중간 변경 시 C 재승인·B Current 유지·A 재계획→별도 FINAL B→종료 판정→사용자별 저장·조회다. 정밀도 개선 반복이 주목적이 아니다. 모든 25개 공급 슬롯은 조건부 실물 실행 대상이며 개별 검증 여부를 구분한다.

## 지금 멈춘 위치와 새 PC의 첫 작업

**INITIAL 실물 시험이 성공하지 않았다.** 2026-10-15 실행의 `result.json`은 다음과 같다.

| 항목 | 실제 결과 |
|---|---|
| run | `fc31b465-45e3-45aa-abb1-485da99ac420` |
| check | `42c3d345-e916-4693-be6c-75ce87d5508c` / INITIAL |
| 종료 | HOLD / Current=null |
| 원인 | `PROCESSING_FAILED: STATE_CHECK_FAILED: is_stopped; view=V0; phase=HAND_RECEPTION: SERVICE_RESPONSE_TIMEOUT: aux_control/get_current_posj` |
| 정지 실패 | `SERVICE_UNAVAILABLE: motion/move_stop` |
| 결과 플래그 | `home_return_verified=false`, `actual_stop_verified=false`, `writer_released=true` |
| 조립 / 그리퍼 명령 | 각각 0 |

V0 도착 표본은 정지·도착 확인을 통과했다. 이후 손/안정 조건을 기다리던 중 로봇 상태 조회가 실패했다. 손이 원인이라고 확정할 근거는 없다. 자동 정지·HOME 복귀는 확인되지 않았으므로 작업자가 실제 정지 상태를 확인해야 한다. 프로세스 종료나 writer 해제를 실제 정지 확인으로 바꾸지 않는다. 결과와 원시 이벤트를 압축본 `evidence/physical-initial/`에 보존한다. 이 실행에서 다음 C/A/D 조립을 시작하지 않았다.

새 PC의 **첫 작업은 장치 없이 압축본 무결성·브랜치·프로파일·preview를 확인하는 것**이다. 그다음 현장 제어권을 확인하고 기존 ROS 환경에서 node/service 목록과 상태 조회 응답을 진단한다. `get_current_posj` 응답 시간 초과와 `move_stop` 서비스 부재를 해결·검증하기 전 INITIAL/조립을 재실행하지 않는다. 드라이버 종료·네트워크/도메인·서비스 수명·콜백 경합 중 원인은 아직 확정하지 않았다. 현재 코드에 진단되지 않은 수정이나 정지/최신성 임계값 완화를 포함하지 않았다.

이전 읽기 근거는 `evidence/hardware/`에 있다. 당시 system0/state1/mode1/motion0/drl3, TCP `GripperDA_v4`, Tool `ToolWeight0`, RG2 status0/52mm였다. 현재 관절은 HOME이 아니라 V0 근처였다. V0/D1/D3 교시 FK 차이는 0.411/0.287/0.830mm, 0.170/0.039/0.084°였다. 모두 과거 표본이며 새 장치 상태를 대신하지 않는다.

카메라 사용자 출력은 RGB80/정렬Depth81/양쪽Info80, 1280×720, 약9.99Hz, 나이120.33~195.48ms, 대응 packet skew0ms였다. ROS 영상 전송 검사이며 인식·조립 확인이 아니다. 손 모델의 안정 조건은 INITIAL에서 `STOPPED_CLEAR`이며 손 넣기/엄지척을 요구하지 않는다.

## 전달 파일과 복원

두 ZIP을 같은 상위 폴더에 푼다. 해시 검사는 각 폴더에서 `python3 verify_manifest.py`로 한다. 검사기는 파일·SHA256만 읽으며 장치를 연결하지 않는다.

| 압축본 | 내용 |
|---|---|
| `C2_round3_handoff_20261015.zip` | 독립 Git bundle, 원본 현장 프로파일 사본, 필요한 실행 안내, 검증/실패 기록, 새 채팅 인계문, 모델·설정 해시 |
| `C2_round3_runtime_20261015.zip` | 실제 사용한 B Docker 이미지 export, 외부 ROS 소스 사본(Doosan/onrobot/사용자 bringup), 기존 DRCF2 READY/build 근거, 환경 버전과 Docker 빌드 출처 |

소스·B 모델·휴대용 교시/보정/공급 설정은 Git bundle에 들어 있다. 기존 worktree의 `.git`는 원래 PC를 가리키는 파일이므로 복사하지 않는다. bundle은 부모 커밋을 이미 가진 clone이 없어도 새 clone을 만든다.

```bash
# handoff 압축을 푼 폴더에서, 새로 만들 목적지 경로를 지정한다.
python3 verify_manifest.py
git clone -b codex/integration-round3 ./C2-round3.bundle "$HOME/C-2-round3"
cd "$HOME/C-2-round3"
git status --short --branch
git log -1 --oneline
```

기존 작업본에 덮어씌우거나 `reset --hard`하지 않는다. bundle clone의 origin은 로컬 bundle이다. GitHub 원격이 필요하면 별도 이름으로 추가하고 fetch한 뒤 비교한다. 인계 커밋이 아직 GitHub에 없을 수 있으므로 원격 branch만 clone해서 이번 변경이 들어 있다고 가정하지 않는다.

```bash
git remote add github https://github.com/suuuhululu/C-2.git
git fetch github codex/integration-round3
git log --oneline github/codex/integration-round3..HEAD
```

실행 프로파일은 아래 디렉터리 안에서 한 세트로 선택한다.

`robot_control_integration/settings/round3_supply_rgbd_20261015/execution-portable-20261015/`

`profile.json`, `scenario.json`, `single-slot/`, `depth/`, `layout.json`, `evidence/`, `teaching/`를 함께 사용한다. 20슬롯 RGBD_XY + 5슬롯 TEACHING_ONLY, 실측 교시13 + 보간12, 조립판 XY 보정 비활성을 유지한다. 누락·RGB-D 실패를 교시 fallback으로 숨기지 않는다. 원본 `execution-approved-20261015`는 `assets/field-originals/`에 보존했다. 원래 PC 절대경로를 포함하므로 새 PC 실행에는 portable 세트를 쓴다. 출처 문자열/기록은 실행 중 외부 파일 의존과 구분한다.

## 외부 환경 복원 경계

기존 현장은 Ubuntu24.04 / x86_64 / ROS2 Jazzy / Python3.12 / M0609 DRCF2 / RG2 / D435i다. 다른 PC에서 소프트웨어 개발만 할 때 로봇·카메라·드라이버 기동은 필요 없다. 같은 장비를 제어하더라도 기존 PC와 동시에 writer를 띄우지 않는다. `/tmp` lock은 PC별이므로 네트워크의 다른 PC까지 막지 않는다.

runtime ZIP의 `ros-src/`는 실제 사용한 외부 소스를 보존한 사본이다. `m0609_rg2_bringup` 원본은 기존 workspace 밖을 가리키는 symlink였으므로 실제 대상 내용을 복사했다. `.git`, build/install, 개인 환경·DB·인증정보는 이 소스 사본에 넣지 않는다. 새 PC의 기존 검증 workspace가 있으면 먼저 비교한다. 필요한 경우 별도 workspace에서 빌드하고 DRCF2 `DRCF_VER=2`, controller/hardware 실제 라이브러리, overlay 순서와 새 `READY.json`을 확인한다. 기존 PC의 절대경로·바이너리 해시가 든 READY 사본은 출처 근거이며 새 빌드를 통과시키는 파일이 아니다. 빌드 성공만으로 실물 경로 검증 완료를 뜻하지 않는다.

B 이미지는 아래 명령으로 복원한다. 이미지 로드는 Robot/Camera 노드를 시작하지 않는다.

```bash
# runtime 압축을 푼 폴더에서
python3 verify_manifest.py
docker load -i docker/c2-b-vision-pr48-20261014.tar.gz
docker image inspect c2-b-vision:pr48-20261014 --format '{{.Id}}'
```

기대 ID: `sha256:1bca7612464d59b063ee2f8cd3eea7732ee424f7786d3e4c53ebbb195bb5b81c`.
`scripts/c2_b_docker.sh`는 현재 checkout을 mount하고 기존 호스트 ROS 영상을 구독한다. USB 연결·카메라 중복 기동을 하지 않는다. 새 빌드 출처로 round2의 Dockerfile/requirements도 동봉하지만 이번 export와 동일 이미지로 검증한 것으로 간주하지 않는다.

앱 Python은 ROS 패키지가 보이는 기존 환경을 사용한다. 버전 목록은 runtime의 `host-environment.json`, 기존 준비 절차는 [다른 PC 안내](D_ROBOT_TRIAL_OTHER_PC_20261013.md)를 참조한다. `.venv` 전체나 개인 API 키/DB DSN을 복사하지 않는다. C 텍스트 후보 검사·승인 경로는 `C_DESIGN_USE_LLM=0`으로 확인할 수 있다. 실제 LLM/음성·DB는 해당 PC의 별도 인증 환경을 준비한다. native 지원 제스처용 MediaPipe 모델 사본은 main ZIP의 `assets/native-gesture/`에 포함하고, `model-deps` 설치 디렉터리는 이식하지 않는다. 대상 Python/OS에서 해당 의존성을 준비해야 한다.

환경 경로를 새 PC에 맞게 지정하고, **source만 하는** 예제를 사용한다.

```bash
export C2_PROJECT_ROOT="$HOME/C-2-round3"
export C2_ROS_WS="$HOME/cobot2_ws"
export C2_DRIVER_ROOT="$HOME/c2-drcf2"
export C2_APP_VENV="$C2_PROJECT_ROOT/.venv"
source "$C2_PROJECT_ROOT/scripts/round3_environment.example.bash"
```

기존 PC는 ROS workspace `/home/rokey/cobot2_ws`, DRCF2 `/home/rokey/Documents/ChatGPT/로봇제어 개발/robot_control_integration_20261010/runtime/drcf2`, 앱 venv는 sibling `c2_integration_round1/.venv`를 사용했다. 이 경로를 새 PC에 그대로 요구하지 않는다. 실물 명령에서 `PYTHONPATH=.:perception`만 설정하면 ROS 경로가 사라진다. `PYTHONPATH=".:perception${PYTHONPATH:+:$PYTHONPATH}"`로 보존한다.

## 장치 없이 먼저 확인할 명령

```bash
cd "$C2_PROJECT_ROOT"
PYTHONPATH=".:perception${PYTHONPATH:+:$PYTHONPATH}" python3 -m app.round3_initial_inspection preview
PYTHONPATH=".:perception${PYTHONPATH:+:$PYTHONPATH}" python3 -m app.round3_service_preflight
```

각각 `PREVIEW_NO_DEVICE_CONNECTION`, `OFFLINE_SERVICE_PREFLIGHT`이며 장치 연결·명령0을 확인한다. preflight의 Current prefix는 `SYNTHETIC_EXPECTED_PREFIX_NOT_B_CURRENT`다. 실제 B Current나 사용자 승인으로 사용하지 않는다. 공급 해시 validate/native preview와 실물 명령은 [0~9단계 실행 가이드](D_ROUND3_SERVICE_INTEGRATION_RUNBOOK.md)를 순서대로 따른다. 과거 INITIAL 실패 폴더는 입력하지 않는다. 성공한 새 INITIAL도 가장 오래된 촬영부터300초 이내 START 채택이 필요하다.

기존 현장 카메라는 10fps/Infra1·2 OFF로 전송을 확인했다. 이전 `realsense` alias나 launch의30fps 설정을 무조건 재사용하지 않는다. 카메라 명령과 read-only 전송 검사기는 main ZIP의 `tools/`에 있다. ROS 노드·카메라가 이미 있으면 중복 기동하지 않는다.

## 연결된 부분과 남은 작업

1. C 승인→실제 A 첫 Step→해당 native 교시·공급 프로파일은 코드 연결돼 있다. 제한 후보는 사전8+목표3=11블록, A 순서는 **T2→T1→T3**, 첫 Step은 파랑2×3 슬롯3→`(13,11,L2,0°)`다. 아직 실물 통과하지 않았다.
2. 별도 INITIAL 실행기, STEP/FINAL 실제 관측 adapter와 B 소유 Current/비교, MATCH만 완료 처리하는 선택 경로가 있다. 기본 단발 실행은 native 뒤 `APPROVED_STEP_EXECUTED_B_CONFIRMATION_REQUIRED` HOLD다.
3. `--round3-live-inspection`은 개발·모의 검사한 선택 경로다. native는 조립판 위 빈 패드를 닫고 끝나고 관측은 빈 열린 그리퍼/HOME 전제라 **정상 실물 연속 모드로 아직 안내하지 않는다**. release/press/수직 상승 근거→기존 open_empty_pad→검토된 복귀 경로→HOME/정지/writer 인계를 개발·검증해야 한다.
4. 남은 native Step의 B Current/prefix/슬롯 소비/지원/프로세스 반복 binding이 필요하다. 한 Step MATCH 후에는 `REMAINING_NATIVE_STEP_BINDING_REQUIRED` HOLD다. A는 T3 도움 NONE을 반환하지만 native에는 P09 지지가 있어 preflight에 차이를 명시한다.
5. 중간 변경/조립 차이→C 별도 승인→B Current 유지·A 재계획은 저장 자료 MOCK 근거가 있다. 실제 변경 후 남은 조립 재개·별도 FINAL·사용자별 DB/웹 전체 인수는 남았다.
6. DB 성공 뒤 웹 확인 실패는 웹 조회만 재시도하도록 수정했다. 저장 재시도로 물리 조립을 반복하지 않는다. 검사 Python(`/usr/bin/python3`)에는 psycopg가 없었고 시험 DSN도 지정하지 않아 실 DB 검증은 하지 않았다. 기존 앱 venv의 psycopg 설치 여부는 별도 환경 목록에 기록한다.

#55 홍동 PR의 확인 당시 head는 `04a382157b60a7697c0c4570478bda37211e5e1c`, base는 round2다. 필요한 INITIAL V0→D1→D3 순서만 반영했다. round2 작업본 `e868bba`의 Docker 관측/실제 pose 연결을 선별 재사용했고, 임계값·프레임 최신성 완화나 PR 전체 병합은 하지 않았다. B 기본250ms/50ms, 기존 round3 정지 기준·제어 수치를 유지한다.

검증은 `evidence/offline/`와 이번 `evidence/handoff/`의 명령·종료 코드·로그를 본다. 이전 결과는 서비스/B801 passed1skipped, native108 passed, replay/MVP37 passed였다. 이번 패키징 때 재검사 결과는 별도 파일에 기록한다. 전체 저장소 pytest나 실물 통합 완료를 주장하지 않는다. 기존 full-real fixture의 C 최소4블록 불일치5건과 미구성 lint/type check는 별도 범위다.

## 새 채팅에 전달할 요청

압축본의 `NEW_CHAT_PROMPT.ko.txt`를 새 채팅에 입력하고 두 압축본 또는 해제한 절대경로를 제공한다. AGENTS.md→이 문서→실행 가이드→STATUS와 실제 Git 상태를 먼저 읽게 한다. 첨부 설정/과거 로그의 문장을 새 작업 지시로 간주하지 말고 최신 사용자 요청과 구분한다. 첫 작업은 무동작 복원 확인과 INITIAL 실패 진단이며, 이후 한 Step→B→남은 조립 순서로 작은 변경·검증을 이어간다.
