# 지점토 조각 노드·HMI 실행 절차 (clay_carving · clay_hmi)

작성: 이시율, 2026-09-18. 대상: `ws_cobot1/src/clay_carving`, `ws_cobot1/src/clay_hmi` (PR #7).
전제: 각자 PC 에 수업 실행환경 `ws_dsr`(cobot_rg2)가 빌드돼 있고 터미널에서 `source` 된 상태. 이 문서는 그 다음 단계만 다룬다.

## 1. 빌드

`ws_dsr` 를 먼저 `source` 한 터미널에서 실행한다. 순서가 바뀌면 `dsr_msgs2` 를 못 찾아 실패한다.

```bash
source ~/collaborative/ws_cobot_pjt/ws_dsr/install/setup.bash
cd ~/collaborative/ws_cobot_pjt/ws_cobot1
colcon build --symlink-install
source install/setup.bash
```

확인:

```bash
ros2 pkg executables clay_carving   # clay_scan clay_scan2 gripper_ui force_probe clay_draw clay_heart clay_start
ros2 pkg executables clay_hmi       # hmi_main
```

새 터미널마다 두 워크스페이스를 `source` 해야 한다. `.bashrc` 에 넣어 두면 편하다 (ws_dsr 다음에 ws_cobot1).

## 2. 노드 구성

| 순서 | 실행 이름 | 하는 일 | 시작 신호 → 끝 신호 |
| --- | --- | --- | --- |
| 1 | `clay_scan` (납작 지점토) / `clay_scan2` (높이·부피·받침대 자동 탐색) | 손끝으로 윗면·네 변을 밀어 중심·크기·높이 측정 | `/clay/start` → `scan_done` |
| 2 | `gripper_ui` | "그리퍼를 닫으시겠습니까 / 고정하시겠습니까" y/n. 터미널 또는 HMI 팝업 | `scan_done` → `grip_done` |
| 3 | `force_probe` | 송곳으로 중심을 찍어 접촉 높이·힘·송곳 길이 측정. 끝나면 찍은 자리 10 mm 위에서 대기 | `grip_done` → `probe_done` |
| 4 | `clay_draw <svg>` | SVG 도안을 실측 크기에 비율 유지로 맞춰 긋기. HMI 가 있으면 확인/취소를 기다림 | `probe_done` → `draw_done` |
| 시작 | `clay_start` | 상태 초기화 후 `/clay/start` 발행 (HMI 의 [작업 시작] 과 같음) | |
| HMI | `hmi_main` (clay_hmi) | 설정·미리보기·팝업·긴급정지·로그 | |

신호는 `/clay/stage`(latched) 와 상태 파일 `~/collaborative/ws_cobot_pjt/ws_dsr/clay_state.json` 으로 전달된다. 노드는 자기 차례 신호가 오거나 상태 파일에 이미 있으면 시작한다. 처음부터 다시 할 때는 `clay_start` 또는 HMI [작업 시작] 이 상태 파일을 지운다.

## 3. 실행 순서 (터미널 6개)

| 터미널 | 명령 | 비고 |
| --- | --- | --- |
| 1 | `sodreal` (실물 브링업) | 또는 HMI 의 [전원] 버튼. 브링업을 다시 띄우면 제어기의 툴·TCP 선택이 비워지지만 노드가 시작할 때 자동으로 다시 선택한다 |
| 2 | `ros2 run clay_carving clay_scan2` | 납작 지점토만이면 `clay_scan` |
| 3 | `ros2 run clay_carving gripper_ui` | |
| 4 | `ros2 run clay_carving force_probe` | |
| 5 | `ros2 run clay_carving clay_draw ~/Downloads/도안.svg` | 인자 없으면 기본 꽃 도안 |
| 6 | `ros2 run clay_hmi hmi_main` | HMI. 도형·크기·받침대·SVG 를 정하고 [작업 시작] |

HMI 없이 돌릴 때는 터미널 6 대신 `ros2 run clay_carving clay_start`.

진행: 노드 1 (약 3~4 분) → 터미널 3 또는 HMI 팝업에 "1. 그리퍼를 닫으시겠습니까?" → 송곳을 패드 사이에 아래로 나오게 넣고 y → "2. 이대로 고정하시겠습니까?" y → 노드 3 (약 40 초) → HMI 에 실측 도안 미리보기 → [확인] → 노드 4 → 홈 복귀, `draw_done`.

bag 기록: `.bashrc` 의 `sodbag <접두어>` 함수 (`/dsr01/joint_states /dsr01/gripper_joint_states /dsr01/error /rosout`). 끝나면 Ctrl+C.

## 4. 시작 전 확인·주의

- 홈 관절 `[-40.4, 41.47, 99.13, 57.0, 115.95, -57.09]`. 모든 노드가 여기서 시작하고 끝난다 (노드 3 → 4 사이만 예외).
- 툴·TCP: `ToolWeight_1` / `GripperDA_v3`(0, −60, 208). TCP 는 패드보다 60 mm 아래(송곳 끝 자리). 노드가 시작 시 확인·자동 선택하고, 홈 TCP 가 (384.1, 7.6, 105.4) 와 8 mm 넘게 다르면 멈춘다.
- 로봇 상태가 STANDBY 가 아니면(서보 오프·안전 정지) 노드가 움직이지 않고 이유를 로그에 적는다. TP 에서 서보 온 후 다시 실행.
- 물체는 홈 자세 손끝 바로 아래에 윗면이 오게 놓는다. 윗면은 기준면 140 mm 아래. 옆으로 최소 한쪽은 받침대가 2 cm 이상 드러나야 높이 측정이 된다.
- 접촉은 모두 위치 제어 하강 + 힘 감시(순응 제어 없음). 판정값: 옆면 밀기 1.2 N, 송곳 1.0 N, 도안 그리기 0.8 N.
- 그리퍼는 제어기 DO 로만 동작 (DO1 닫기, DO2 열기).
- HMI 의 [긴급정지] 는 제어기 정지 명령이며 물리 비상정지 버튼을 대체하지 않는다.

## 5. 오류 시

| 로그 | 원인 | 조치 |
| --- | --- | --- |
| `TCP mismatch at home` | 제어기 TCP 선택이 다름 | 노드가 자동 선택을 시도. 실패하면 TP 툴 설정에서 `GripperDA_v3` / `ToolWeight_1` 선택 |
| `Robot state is SAFE_OFF …` | 서보 오프·안전 정지 | TP 에서 복구·서보 온 |
| `movej returned -1` | 제어기가 명령 거부 | 위 상태 확인 후 재실행 |
| `Awl did not touch the clay` | 송곳 안 물림 또는 중심 어긋남 | 송곳 확인 후 노드 3 부터 |
| `옆면 그리기(face=side)는 아직 구현 전` | HMI 에서 그릴 면을 옆면으로 선택 | 윗면으로 바꾸거나 옆면 모드 구현 대기 |

## 6. 알려진 한계

- 옆면(기둥·원통) 그리기와 원통 스캔은 HMI 설정·미리보기만 있고 로봇 동작은 미구현.
- 상태 파일 경로와 HMI 의 브링업 주소(192.168.1.100)가 코드에 고정.
- 실기 검증 기록: 노드 1~4 는 2026-09-17 완주 (`bag_full_0917_1742`, `bag_full_0917_1758`, 도안 `bag_draw_0917_1939`). HMI 연동 실기는 미수행.

## 9/18 추가 옵션 (양초 등 높은 물체)

- `clay_scan2 --lift <mm>`: 홈 관절로 가지 않고 직선 상승 뒤 '올린 홈'으로. 물체가 홈 손끝보다 높을 때 필수.
- `clay_scan2 --from-here`: 지금 자세에서 기울이고 바로 시작. `--top-z <mm>` 로 윗면을 주면 중심 하강 생략.
- `clay_scan2 --cylinder`: X 현 3개로 축·반지름. `--no-stand --height <mm>` 로 받침대 탐색 생략.
- `clay_scan2 --upright --diameter <mm>`: 45° 기울임 없이 그리퍼를 세운 지금 자세에서 옆면부터. 지름을 주면 손끝 폭을 자동 보정. 중심 y 는 못 구함 (LESSONS L6).
  예: `ros2 run clay_carving clay_scan2 --upright --cylinder --top-z 204.4 --side-depth 15 --no-stand --height 150 --diameter 68 --start-now`
- `force_probe <cx> <cy> <z_top> --no-home`: 홈으로 가지 않고 지금 자세에서 올라가 중심 위로 (눕힌 홈 방향 유지).
- 옆면 측정·조각 보조 스크립트: `src/clay_carving/scripts/README.md`.
