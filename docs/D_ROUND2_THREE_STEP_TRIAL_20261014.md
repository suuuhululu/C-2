# D Round2 세 단계 · 세 사이클 시험 안내 — 2026-10-14

공급판에서 노랑 2×2 슬롯 4 → 파랑 2×3 슬롯 3 → 노랑 2×3 슬롯 5를 한 번씩 집어 조립한다. **총 세 사이클**이며, 각 블록을 세 번 반복하는 아홉 사이클이 아니다. 마지막 단계에서는 사람이 아래 구조를 잡고 로봇이 삽입·놓기·윗면 누르기를 수행한다.

실행 코드는 `robot_control_integration/scripts/round2_three_step_trial.py`다. 기존 공급판 인식·파지와 조립판 팝업을 이어서 사용한다. 최신 수정은 T2의 실측 파지·결착·패드 교시와 영상 XY 보정을 적용한다. 구현·오프라인 검증 중 물리 명령은 보내지 않았다. D 단위 시험 결과는 B Current 갱신이나 최종 조립 완료 판정이 아니다.

## 시험 전 사전 배치 8개

좌표 `(x,y)`는 **0부터 시작하는 공통 stud 좌표의 최소 모서리**이며 블록 중심 좌표가 아니다. 그림의 실선은 사전 배치, 점선은 로봇이 놓을 목표다.

층별 그림은 현장 작업 폴더의 `reports/round2_three_step_trial_20261014/assembly_three_layers.png`에 보존한다. 저장소의 사전 배치 기준은 아래 표와 scenario.json이다.

 layer는 1부터 시작한다. 비정방형 블록은 **0°에서 긴 변이 공통 Y 방향**, **90°에서 긴 변이 공통 X 방향**이다. 2×2는 0°를 사용한다. 공급 슬롯 번호는 해당 색·종류 열 안의 물리 슬롯 번호다.

먼저 아래층 여섯 블록 P01~P05/P10을 두고, 그 위에 P06/P09를 둔다. 목표 T1~T3는 아직 놓지 않는다.

| 사전 블록 | 색·종류 | (x,y) | layer | 방향 | 역할 |
|---|---|---|---|---|---|
| P01 | 노랑 2×3 | (9,9) | 1 | 0° · 긴 Y | T1 바닥·왼쪽 기반 |
| P02 | 파랑 2×3 | (11,11) | 1 | 90° · 긴 X | T2 왼쪽 바닥 |
| P03 | 노랑 2×3 | (14,11) | 1 | 90° · 긴 X | T2 오른쪽 바닥 |
| P04 | 파랑 2×3 | (13,13) | 1 | 90° · 긴 X | T2 뒤쪽 바닥·P09 지지 |
| P05 | 노랑 2×3 | (14,15) | 1 | 90° · 긴 X | P09 지지 |
| P10 | 빨강 1×2 | (16,14) | 1 | 90° · 긴 X | P09의 나머지 지지 |
| P06 | 파랑 2×3 | (9,11) | 2 | 90° · 긴 X | P01/P02 연결·4/6 지지 |
| P09 | 노랑 2×2 | (15,14) | 2 | 0° | T3 아래 구조·4/4 지지 |

P09의 네 지지 stud는 `(15,14)`의 P04, `(15,15)`·`(16,15)`의 P05, `(16,14)`의 P10이다. 사전 배치의 좌우 기반은 분리되어 있으며 T2가 연결한다. **사전 구조만 완성 Design으로 표현하면 연결성 검사를 통과하지 않는다.** 세 목표를 포함한 완성 11블록 Design은 C의 연결성·최소 지지 규칙을 통과했다. 점유 범위는 x=9~17, y=9~16이다.

시나리오 원본은 [scenario.json](../robot_control_integration/settings/round2_three_step_trial_20261014/scenario.json)이다. 계산 근거 `layout_robot_feasible.json`, 반복 실행 파일과 과거 시험 기록은 현장 작업 폴더의 `reports/round2_three_step_trial_20261014/`에 보관한다.

## 세 목표와 A 판단

| 순서 | 공급 블록·슬롯 | 조립 목표 | 지지 | 추가 현장 시험 |
|---|---|---|---|---|
| T1 | 노랑 2×2 · 슬롯 4 | (9,9), layer 2, 0° | 4/4 | 로봇 결착 |
| T2 | 파랑 2×3 · 슬롯 3 | (13,11), layer 2, 0° | 6/6 | 실측 중앙 파지·완전 결착·빈 패드 교시 적용 |
| T3 | 노랑 2×3 · 슬롯 5 | (15,14), layer 3, 0° | 4/6 | 사람이 P09 아래 구조를 잡고 로봇 결착 |

현재 8개 사전 배치에서 실제 A 재평가·모션 계산은 세 단계 모두 `ROBOT_GRIP/NONE`, `CANDIDATE`다. 같은 per-step 보정 사본으로 계산한 공급 픽업 XYZ·조립 seated XYZ가 D 후보와 일치했다. 이는 수치 모델의 결과이며 실물 경로·결착·충돌·힘 안정성 승인이나 검증을 뜻하지 않는다.

A 전체 최적화는 동일 층의 동률 선택 때문에 **T2→T1→T3**를 반환했다. 사용자 지정 **T1→T2→T3**는 A의 `build_plan(ordered_blocks=targets)`·`validate_plan`과 각 단계 재평가로 별도 검증했다. 자동 전체 계획의 순서를 바꾸어 기록하지 않았다.

원래 9개 사전 배치에는 T2 양옆에 빨강 1×2 `(12,11,L2)`와 파랑 2×3 `(15,11,L2)`가 있었다. 이전 A 0.5.1은 접근·해제 공간이 막혀 `HUMAN_ASSEMBLY/MANUAL_ASSEMBLY`를 선택했고, 파지 하단 높이를 모델상 5→15mm로 높여도 동일했다. 원래 `layout_analysis.json`은 보존했다. A PR50의 0.5.2에서는 전체 밑면 지지·접근 불가인 원래 T2가 `RELEASE_PRESS` 후보가 되며, 이 새로운 놓기·가압 실물 시험은 상공 해제 pose가 아직 미정이다. 현재 8개 사전 배치 시험은 그 두 장애물을 빼고 바닥 연결을 조정한 일반 로봇 조립 배치다.

T2는 [T2.operator_teaching.json](../robot_control_integration/settings/round2_three_step_trial_20261014/T2.operator_teaching.json)의 절대 TCP 세 좌표를 사용한다. 이전 +10mm 후보를 대체하며 추가 Z 보정을 적용하지 않는다. 약 8mm 파지 높이는 사용자 추정이다. T3의 사람 HOLD는 사용자 지정 현장 정책이다. A의 `assistance_kind=NONE`은 그대로 보존하며 4/6 지지 자체가 A 자동 HOLD 조건이라고 표시하지 않는다.

## 장치 연결 없는 명령

현재 작업본은 `/tmp/c2-round2-robot-control-20261014`다. checkout을 옮기면 `C2_TRIAL_ROOT`를 실제 위치로 바꾼다.

```bash
export C2_TRIAL_ROOT=/tmp/c2-round2-robot-control-20261014
bash '/home/rokey/Documents/ChatGPT/로봇제어 개발/reports/round2_three_step_trial_20261014/run_three_step_offline.sh'
```

다른 PC에서 checkout 전체를 사용하면 저장소 안의 같은 실행 파일을 사용한다.

```bash
bash robot_control_integration/scripts/run_round2_three_step_offline.sh
```

이 파일은 네트워크 연결을 차단한 native 회귀 검사 → 세 단계 설정 preview → 합성 세 사이클 replay 순서로 실행한다. `three_step_native_tests.xml`, `preview/preview.json`, `replay/<timestamp>/events.jsonl`·`result.json`을 저장한다. replay는 합성 RGB에 실제 공급판 stud 검출을 적용하고 공급·이송·삽입·놓기·press 함수를 호출한다. 이상적인 이동 종점과 입력 반력을 사용하며 실물 충돌·접촉 물리를 재현하지 않는다. 실기 조립 팝업의 영상 yaw는 replay하지 않으며 사람 준비 응답도 합성이다.

직접 설정만 확인하려면 저장소 루트에서 다음 명령을 사용한다. 장치 연결이나 팝업 없이 종료한다.

```bash
python3 robot_control_integration/scripts/round2_three_step_trial.py preview
```

| 검증 범위 | 현재 기록 |
|---|---|
| 8개 사전 배치 + 3개 목표의 C 검사 | 오류 없음 |
| 사용자 순서 A 계획·각 단계 재평가·모션 계산 | 검증 통과 / 세 단계 CANDIDATE |
| 로봇 PR 사본 native 전체 검사 | 1,509 통과 / 실패·오류 0 |
| 영상 XY·가상 격자 검사 | 49 통과 / 실패·오류 0 |
| 별도 A–D 연결 사본의 A·Workflow·HMI·D 검사 | 652 통과 / 실패·오류 0 |
| 세 사이클 preview·합성 replay | 8 사전 블록 / T1→T2→T3 완료 / 장치 명령 0 |
| 사용자 이전 실물 실행 | T1 완료 / T2 삽입 반력 중단 / T3 미실행 |
| 최신 교시·영상 XY 적용 실물 세 사이클 | 미검증 |

검사 범위가 겹치므로 수치를 합산하지 않는다. 마지막 PR 사본의 결과는 [로봇 현장 수정 기록](D_ROUND2_ROBOT_FIELD_FIXES_20261014.md)에 남긴다. 사용자 이전 실행 `real_runs/1791948221337662597`에서 T2가 목표보다 약 2.77mm 위에서 중단됐다. 공급 검출은 성공했지만 실측 픽셀→XY 연결이 없어 교시 파지를 사용한 기록이다. 최신 T2 교시와 XY 보정의 실물 결착 성공 근거로 사용하지 않는다.

## 로봇 연결 후 실행 명령

기존 실기 터미널에서 사용하던 ROS Jazzy와 검증된 로봇 드라이버 overlay 환경을 로딩한다. 기존 HOME 관절 `[0,0,90,0,90,0]`에 빈 그리퍼로 시작한다. `--start-zone home`은 HOME 이동 명령이 아니다. 공급판의 노랑 2×2 슬롯 4·파랑 2×3 슬롯 3·노랑 2×3 슬롯 5에 해당 블록을 두고, 위 8개 사전 구조를 준비한다.

```bash
source /opt/ros/jazzy/setup.bash
export C2_TRIAL_ROOT=/tmp/c2-round2-robot-control-20261014
export C2_ROBOT_ROOT="$C2_TRIAL_ROOT/robot_control_integration"
export ROS_DOMAIN_ID=20
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

기존 로봇·카메라 드라이버가 가동 중이면 그대로 사용한다. 새로 시작할 때 기존 launch를 사용하고 `ROBOTON2_READY`를 확인한다.

```bash
ros2 launch "$C2_TRIAL_ROOT/scripts/roboton2.launch.py" camera:=true rviz:=false
```

다른 터미널에서 준비한 실행 파일을 실행한다. 아래 파일은 **실제 로봇·그리퍼 명령**을 보낸다. 기존 `--execute`·`--confirm-hand-clear` 옵션을 사용한다.

```bash
bash '/home/rokey/Documents/ChatGPT/로봇제어 개발/reports/round2_three_step_trial_20261014/run_three_step_real.sh'
```

다른 PC에서는 저장소 루트에서 `bash robot_control_integration/scripts/run_round2_three_step_real.sh`를 사용한다. 재시험 전에는 목표 T1~T3를 제거하고 사전 8개 구조로 초기화한다. 이미 수동으로 결착한 T2 위에 같은 사이클을 다시 실행하지 않는다.

같은 명령을 저장소 루트에서 직접 실행하면 다음과 같다.

```bash
ROS_DOMAIN_ID=20 python3 robot_control_integration/scripts/round2_three_step_trial.py run \
  --execute --confirm-hand-clear --start-zone home
```

기준 TCP 기울기 복귀 시험을 추가하려면 wrapper 또는 직접 명령 끝에 `--tilt-accuracy-test`를 붙인다. 기본 세 사이클에는 이 선택 시험을 넣지 않는다.

## 각 사이클의 팝업과 입력 순서

공급판 창은 대상 슬롯 ROI·stud 배열·`Recognized`·`XY assist`·`Reason`을 보여준다. 픽셀→로봇 XY 연결이 없는 관측은 `XY assist=false`로 교시 픽업을 사용한다. T2 슬롯3은 이번 중앙 파지 교시로 교체했고 슬롯4·5는 기존 보간 후보다. 파지와 이송 후 조립판 창이 열린다.

1. **목표 outline의 변 1~4 선택 → E → 그 변과 대응하는 몸체 윗면 모서리 양 끝점 두 번 클릭.** 이후 새 영상에서 추적하며 자동 yaw를 보정한다. 다른 목표 변을 선택하면 실제 모서리도 다시 선택한다. A로 축을 수동 전환한 뒤에는 1~4를 다시 고른다. 이 경로는 yaw 보정이며 두 점으로 roll/pitch를 측정하지 않는다.
2. **X:** 화면의 영상 기반 dX/dY mm를 현재 TCP에 적용하고 I 착좌 XY도 함께 바꾼다. paired Depth가 없으면 기존 가상 격자의 예상 높이 평면으로 계산한다. 투영 좌표 정확도는 실물 미검증이며 작업자가 후보를 확인해 X로 적용한다.
3. **I:** 현재 자세를 유지해 배치 reference로 하강하여 삽입한다. **T3만** 이때 support-ready 팝업이 먼저 열린다. P09 노랑 2×2 `(15,14,L2)`의 아래 구조를 잡고 ENTER를 눌러 준비 응답한다. 이후 삽입·놓기·누르기·상승이 끝날 때까지 잡는다. ESC는 해당 시험을 중단한다.
4. **O:** 작업자가 실제 배치를 확인한 뒤 놓기. 놓기 직전 XY·자세를 저장하고 그리퍼 개방 → 수직 상승 → 빈 패드 닫기를 수행한다.
5. **P:** T2는 교시한 닫힌 빈 패드의 윗면 접촉 XYZ·자세로 접근하여 누른 뒤 상승한다. 치우친 파지 보정으로 TCP가 옮겨져도 원래 블록 목표에 대한 패드 목표는 함께 이동하지 않는다. T1/T3는 기존 패드 높이 기준을 사용한다.
6. **U:** 상공으로 상승하고 조립판 팝업을 종료한다. press까지 완료된 경우 다음 사이클은 빈 패드를 개방하고 다음 공급판 슬롯을 집는다. T3 완료 후 support-finished 팝업이 열리면 아래 구조를 놓고 ENTER로 닫는다.

중간 ESC·창 닫기·Ctrl+C는 STOP 흐름이다. 삽입·press를 끝내지 않은 채 U로 나가면 `INCOMPLETE`로 종료하며 다음 슬롯 파지를 시작하지 않는다. 정상 세 사이클 종료는 `THREE_CYCLES_COMPLETED`이며 `assembly_completion=false`, `current_update=false`를 유지한다.

선택 `--tilt-accuracy-test`에서 H는 작업자가 선택한 현재 TCP 기준을 저장하고, J는 Base X/Y 각각 +0.5° 시험 회전, K는 저장 기준으로 복귀한다. SPACE는 RGB·overlay·로봇 표본·CameraInfo와 가능한 paired Depth를 저장한다. 같은 모서리 두 점의 깊이는 XY 높이 계산을 도울 수 있다. 실제 윗면 평면으로 절대 roll/pitch를 보정하는 등록된 3D surface producer는 아직 연결하지 않았다.

누르기는 하강 중 측정 반력 45N에서 중단하는 위치 제어다. 가압 후 약 58~60N이 남았다는 이유로 상승·일반 이동을 다시 중단하지 않는다. 실기 설정의 `motion_force_stop_n=null`로 접촉값과 분리했다. `target_only_motion=true`에서는 관측점·XY·삽입·패드 기준점의 좌표/자세 오차와 IK/FK 수치 오차를 실행 차단에 사용하지 않는다. 미세한 속도 피드백이 정확히 0인지도 요구하지 않으며 컨트롤러 `motion_status=0`으로 이동 완료를 판단한다. 좌표 오차는 진단 로그에만 남기며 실제 위치 정확도나 결착 완료로 확정하지 않는다. 영상 신선도, 장치 상태·통신 피드백과 기존 ESC/STOP 처리는 유지한다. 기본 통합 경로의 수평 이송은 120mm/s, 상하·삽입·press는 12mm/s 설정을 사용한다.

현장 기존 wrapper의 실기 로그는 `/home/rokey/Documents/ChatGPT/로봇제어 개발/reports/round2_three_step_trial_20261014/real_runs/<timestamp>/`에 저장된다. 저장소 wrapper의 기본 경로는 `$C2_TRIAL_ROOT/reports/round2_three_step_trial_20261014/real_runs/<timestamp>/`이며 `C2_THREE_STEP_OUTPUT`으로 바꿀 수 있다. `events.jsonl`과 단계별 T1/T2/T3 관측, 최종 `result.json`에서 명령 종료와 실제 결착 관찰을 구분해 확인한다.


## 기존 명령과 새 배치의 연결 수정

기존 `bash "$C2_CYCLE_TOOLS/run_cycle_real.sh"`도 이제 이 세 Step 진입점을 실행한다. 기존 `run_offline_checks.sh` 역시 같은 세 Step preview/replay를 사용한다. 이전slot1/(11,11,L1) 한 사이클명령을새8블록배치에혼용해충돌한로그를확인하여연결을수정했다. T1은slot4/(9,9,L2)다.

충돌 실행 `trial-1791946671023653020`은정지요청실패·robot_state5/gripper_status3을기록했다. 현재정지와구조물상태를가정한resume는수행하지않는다. 펜던트의정지/보호정지·끼임과사전배치를확인한뒤정상초기상태에서세Step시험을선택한다. 이전문서의 `--resume-assembly` 예시는이충돌후재개절차로사용하지않는다.

수정진입점은장치없이실제argv와preview를검증했다. [충돌로그와진입점수정](D_ROUND2_ENTRY_COLLISION_20261014.md)에기록했다.
