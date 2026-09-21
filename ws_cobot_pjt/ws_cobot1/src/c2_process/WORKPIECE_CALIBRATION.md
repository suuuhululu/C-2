# 양초 측정 모듈 · 제어 노드 내부 호출용

갱신 2026-09-21. PR #42로 측정 모듈 병합, 후속 브랜치 `codex/workpiece-home-entry` / [PR #45](https://github.com/suuuhululu/C-2/pull/45).
후속 작업은 main `829db40`을 pull한 기준이다.
이 문서의 함수 계약은 새 코드에 구현되어 있다. ROS Action 타입/이름과 다른 담당의
로더가 이미 변경됐다는 뜻은 아니다. 9/21 11:34 팀장 제안에 맞춰 별도 측정 서버 대신
제어 노드에서 준비 검사 후 측정 함수를 호출하는 구조로 다시 정리했다.

## 9/21 15:07 사용자 시험 bag와 상공 복귀 편차 수정

- bag `workpiece_bag_20260921_150734`, 측정 ID `workpiece-test-8eb46cc9ae8a4157a278110084c490a9`: 윗면·옆면 8점 완료 후 `home_x`에서 `PATH_DEVIATION`, 283.939초, 실제 정지 확인. 이 실행은 전체 성공이 아니다.
- 정지 직전 제어기 TCP 선분 편차 약 0.647 mm가 기존 0.5 mm를 넘었다. 힘 한계에 의한 정지가 아니다. bag에는 level 1 / code 3205 특이점 영역 진입 알림 6건도 있어 원인을 단순 진동으로 확정하지 않는다.
- REAL 예제의 `guards.overhead_line_error_mm=1.0`은 **시험용 상공 이동 추종 허용폭**이며 측정 정확도·제조사 안전 한계가 아니다. TCP와 드릴 끝 모두 상공 경계(300 mm)보다 허용폭+회전 여유 이상 높고 작업대 경계 안인 `travel` 자세 유지 이동에만 적용한다. 접촉/접근/초기 후퇴/회전은 이 확대 대상이 아니다.
- 실행 중 실제 위치에서 남은 경로의 양초·도구 선분 검사도 반복한다. 도구가 양초를 가로지르는 이동은 허용하지 않는다. 측정용으로 지정한 PROBE 접촉은 계속 허용한다. 힘·관절·보호정지·최종 도착 허용차는 변경하지 않았다.
- 기존 정지 전 TCP 표본을 fixture로 재생하면 이전 설정은 같은 이탈로 실패하고 새 설정은 해당 편차에서 중단하지 않는다. 이후 도착은 모의로 합성했으므로 **당시 수정본의 실기 완주 확인은 미완료였고, 아래 후속 실행에서 완료**하다.
- 무조건 재전송·보호정지 해제·실패 지점에서 자동 재개는 추가하지 않았다. 모션 응답/정지 결과 미확인 상태에서 재송신하면 중복 실행될 수 있다. 이번 수정은 확인된 상공 편차에서 불필요하게 정지를 요청하지 않는 범위다. 실패 후 `/start`를 새로 호출하면 전체 측정을 다시 시작한다.

후속 변경 검증: 선택 시험 6건과 가짜 장치 전체 흐름 3건 통과. 분리된 localhost/domain 87에서 ROS SIMULATION 시작 요청·성공 결과 수신·자동 종료(exit 0)를 확인했다. 로봇에는 연결하지 않았다.

## 후속 사용자 실기 결과

`workpiece-test-6eb5748f567c4dc598ab225ad84fabe3`: 301.603초,
`SUCCEEDED`, `stop_confirmed=true`, `home_return_confirmed=true`.
근거는 현장 JSONL `workpiece_41cfd0f96f684832905b539a779102e0.jsonl`의 최종 result다.
이것은 자동 종료·새 길이/추정값 반환을 추가하기 전 코드의 모션 완주 결과다. 새 결과 계산은 모의로 검증한다.

## 공정 노드 어댑터 구성

공정에서는 `workpiece_process_adapter.create_process_measurement_adapter()`를 사용한다.
공유 잠금/취소·실제 준비 근거 주입 예시는 [공정 연결 안내](PROCESS_MEASUREMENT_INTEGRATION.md)에 있다.
단독 시험 팩터리를 공정에 사용하지 않는다. 새 서버가 아니라 기존 공정 노드 안에서 구성한다.

## 단독 실물 시험 수신부 (추가)

공통 준비 Action을 기다리지 않고 실제 `measure_workpiece()`를 호출하는 **시험 전용**
`test/workpiece_test_node.py`를 추가했다. 별도 운영 노드/공통 통신 계약을 추가한 것이 아니다.
내장 `workpiece_real_trial.create_adapter`가 REAL I/O·상태 재확인·단독 소유권·실험 영역 검사를 연결한다.

현재 REAL 예제는 사용자 요청에 따라 `measurement_scope=INTEGRATION_ESTIMATE`다.
그리퍼 밑면 오프셋을 정밀 실측하지 않고, 설정의 `estimated_contact_offset_tool_m=[0,0,0]`을
명시적인 임시 가정으로 사용한다. `top_z_m`은 접촉 당시 TCP Z, 바닥은 높이 150 mm를 뺀 값이다.
`validity=ESTIMATED`, `geometry_ready=true`, `absolute_top_verified=false`이며 독립 정확도는 미검증이다.
기존 `CONTACT_REFERENCE`를 선택하면 종전의 null/REFERENCE_ONLY 반환을 유지한다.
새 유효성 값과 출처 필드는 공정 로더/HMI가 확인해야 하며 그 담당 코드를 여기서 수정하지 않는다.

첫 옆면 접촉은 `tool_projection_check`도 계산한다. 기존 양초 모델의 중심/반지름으로 만든 기준면과
접촉 당시 제어기 TCP를 사용해 `projection_m`, `projection_mm`, `difference_m`를 반환한다.
`lateral_x_m`은 재사용하고 새로 재지 않는다. 추가 이동·3점 보정은 호출하지 않는다.
기준 양초가 이동하거나 반지름이 달라지면 그 오차가 길이 추정에 포함되므로
`validity=ESTIMATED_FROM_REFERENCE_SURFACE`, `independently_verified=false`로 명시한다.
동일 8점으로 새로 맞춘 중심/반지름을 다시 길이 계산에 사용하지 않는다.
이번 측정 경로와 좌표 계산은 검사한 기존 `tool_reference.offset_tool_m`을 계속 사용하며,
`tool_projection_check.offset_applied=false`다. 새 길이를 몰래 적용해 검사 경로를 바꾸지 않는다.
기존 TipCalibration/3점 API는 호환용으로 남아 있으나 새 측정 흐름에서 호출하지 않는다.

시험 수신부는 기본적으로 1회 결과를 발행·파일 저장하고, 작업 스레드 종료와 결과 ACK 확인 후
자동 종료한다. 반복 대기가 필요할 때만 `--keep-alive`를 사용한다. UNKNOWN은 자동 종료하지 않는다.
bag은 독립 프로세스이므로 운영자가 Ctrl+C로 별도 종료한다. 공통 제어 노드에는 자동 종료를 적용하지 않는다.

터미널은 기존 sodreal 환경을 사용한다. 패키지 디렉터리 기준 세 명령:

```sh
python3 test/workpiece_test_node.py --mode REAL --operator-ready
```

```sh
ros2 bag record --qos-profile-overrides-path config/workpiece_bag_qos.yaml -o /tmp/workpiece_trial_$(date +%Y%m%d_%H%M%S) /workpiece_test/feedback /workpiece_test/result /workpiece_test/telemetry /dsr01/joint_states /dsr01/error /rosout
```

```sh
ros2 service call /workpiece_test/start std_srvs/srv/Trigger '{}'
```

첫 명령은 대기만 한다. `--operator-ready`는 드릴 OFF, 양초/철사 고정 유지,
작업 공간 비움, 단독 제어, 비상정지 대기라는 현장 조건을 운영자가 확인한다는 뜻이다.
드릴 OFF를 센서로 검출하거나 네이티브 제어권을 자동 취득하지 않는다.
시작 서비스는 **접수**만 반환한다. 마지막 결과/정지는 result 토픽 또는 아래 status로 확인한다.
기본 출력 폴더 `/tmp/workpiece-unit-test`에도 센서·명령·진행·결과 JSONL을 저장한다.
telemetry 기록 실패가 정지 명령 송신을 막지 않도록 처리한다.

- 취소: `ros2 service call /workpiece_test/cancel std_srvs/srv/Trigger '{}'`
- 조회: `ros2 service call /workpiece_test/status std_srvs/srv/Trigger '{}'`
- 터미널 1 Ctrl+C: 취소 신호 후 정지 확인 작업이 끝날 때까지 executor를 유지한다.
- UNKNOWN 뒤 재시작은 수신부가 차단한다. 실제 상태/원인을 확인해야 한다.
- 시험 수신부는 기존 공정 노드와 동시에 사용하지 않는다. 공통 소유권 통합을 대체하지 않는다.

현재 REAL 설정은 9/21 현장 실험의 고정 양초와 장착 상태 전용이다. 새 현장의 범용 기본값이 아니다.
현재 관절 확인 → 필요 시 상공 홈으로 진입 → 홈 도착 확인 → 바로 수직 윗면 접근·접촉·후퇴 → 상공에서 외곽 이동 →
수직 하강 → 중심을 바라보며 8점 측정 → 마지막 외곽 후퇴 → 원 맞춤 → 검사한 경로로 상공 홈 복귀·정지 확인 순서다.
센서 접촉 판정을 독립 실측 정확도 인증으로 표시하지 않는다.

이전 상공 편차 수정 검증: 모의 시험 **156건** 통과. 여기에는 실제 측정 어댑터 + 가짜 장치로 전체 8점 완료,
시작이 홈인 경우 홈 이동 생략, 두 번째 점에서 이탈 시 정지하고 다음 동작 차단이 포함된다.
이 가짜 장치의 IK/FK는 물리 모형이 아니므로 실제 도달성·서보 추종·충돌 검사를 대체하지 않는다.
별도 ROS 도메인 121에서 Trigger → 함수 → 윗면/8점/후퇴 결과와 bag 저장을 확인했다.
기록: `test/fixtures/workpiece_ros_sim_0921.json`.

최초 실물 취소 이력은 `test/fixtures/workpiece_real_trial_0921.json`에 보존한다.
그 뒤 수정본으로 진행한 실물 시험은 아래와 같다. **감독 시험 8에서 처음으로 윗면·8점·계산·마지막 후퇴를 완료했다.**

| 시험 | 확인한 동작 | 종료 결과 |
| --- | --- | --- |
| 감독 시험 1 | 이미 홈이면 이동 생략, 윗면 접촉 TCP Z 234.871887 mm. 사용자가 그리퍼 밑부분 실제 접촉 확인 | 첫 옆점 앞 기준 힘 수집 중 약 0.103 mm 정착 변화로 중단, 정지 확인 |
| 감독 시험 2 | 홈이 아니면 검사한 통로로 홈 이동, 윗면 TCP Z 234.839722 mm, 옆면 1점 완료 | 두 번째 접근 중 횡오차 0.303686 mm로 0.3 mm 제한 초과, 정지 확인 |
| 감독 시험 3 | 홈 이탈 경로 사전 검사 | 같은 자세를 ZYZ로 재변환하는 수치 오차로 실행 전 거절. 이동 없음 |
| 감독 시험 4 | 동일 자세의 native 각도 유지 수정 후 홈·윗면·첫 점 완료 | 두 번째 접근 횡오차 0.302922 mm, 정지 확인 |
| 감독 시험 5 | 기준 힘 수집 전 실제/지시 TCP 정착 확인 후 옆면 6점 완료. 두 번째 점 최대 횡오차 0.216108 mm | 6점 뒤 바깥 이동 중 원신호 힘 10.185 N으로 중단, 정지 확인. 사용자: 물체에 닿거나 걸리지 않았음 |

| 감독 시험 6 | HOME의 첫 짧은 이탈 | 10.278 N으로 정지 확인. 사용자 걸림 없음. 정지 후 5초 조회 힘 6.325~6.506 N |
| 감독 시험 7 | 외곽 이탈과 상공 회전 통과 | 같은 회전 목표 중복 명령으로 이동 시작 미확인. 정지 확인, 중복 목표 제거 |
| 감독 시험 8 | 홈 → 윗면 → 옆면 8점 → 원 맞춤 → 마지막 외곽 후퇴 | **SUCCEEDED / 정지 확인, 270.394초**. 중심 (426.204, 0.083) mm, 반지름 34.227 mm, 원 맞춤 RMS 0.091 mm |

| 감독 시험 9 | 이전 8점 종료 자세 → HOME 회전 경유 → 윗면·8점 → 계산·후퇴. 공중 soft 판정 제거, 외곽 속도 60 mm/s | **SUCCEEDED / 정지 확인, 299.295초**. 중심 (426.174, 0.100) mm, 반지름 34.201 mm, RMS 0.082 mm |

사용자의 접촉 확인은 시험 1의 윗면에만 연결했다. 두 Z 값 차이 약 0.032 mm는 반복 기록의 차이이며
양초 절대 윗면 Z 정확도나 밑면 오프셋 검증이 아니다. 후속 시험에서 서보 정착을 기다린 뒤 두 번째 점을 통과했지만 과거 모든 실패의 원인이 같다고 단정하지 않는다.
힘·경로 이탈 한계를 올려 통과시키지 않았다. 제어기 `get_desired_posx` 읽기 전용 조회와
`probe_deviation` 로그를 추가해 다음 현장 시험에서 실제 위치와 비교할 수 있게 했다.
과거 실패 로그에 지시 위치가 없으므로 당시의 추종 오차 원인을 확정하지 않는다.
원본 로그 해시·발췌: `test/fixtures/workpiece_supervised_0921.json`.

현장 사용자가 자리를 비운 동안에는 실물 이동을 실행하지 않았다. 이후 복귀 확인 뒤 위 감독 시험을 진행했다. 재실행할
세 터미널 명령은 [실행 안내](WORKPIECE_TRIAL_COMMANDS.md)에 정리했다.

## 홈 경유 및 시간 목표 (9/21 후속 수정)

사용자가 HOME 선택을 정정했다. **윗면 측정 직전 상공의 GripperDA_v1 TCP**를 새 HOME으로 사용한다.
`[0.42624374301578377, 0.000046709476999166216, 0.330] m`, quaternion `[0,1,0,0]`이다.
그리퍼 TCP 기준이며 드릴 끝 좌표나 조각 실행기의 HOME과 구분한다. 이전 `[0.4218, 0.0001, 0.2644] m`는
`home.entry_tcp_poses`의 확인된 진입 통로로만 보존한다. 해당 위치에서 시작하면 위로 이탈해 새 HOME으로 이동한다.
`workcell.home`에 출처와 허용차를 저장하며 현재 관절·TCP 관측은 결과의 `initial_state`에 남긴다.

- 이미 새 홈(위치 0.3 mm·자세 0.3° 이내): 준비·IK 검사와 홈 도착 상태만 확인한다. **재상승·상공 X/Y 정렬 명령 없이 바로 윗면 접근**한다. `home_move_skipped=true`를 기록한다.
- 홈이 아님: 양초 옆에서는 동일 자세로 방사선 바깥 이탈 → 수직 상승 → TCP Z 330 mm 상공에서 자세 정렬 → X/Y 분리 이동 → 새 상공 홈 도착(추가 하강 없음).
- 윗면/홈의 확인된 수직 통로에서는 먼저 수직 상승한다. 홈 도착과 정지가 확인되어야 윗면 측정을 시작한다.
- **임의 자세의 일반 경로 탐색기는 아니다.** 양초 내부·방향 불명·확인된 작업 영역 밖·기울어진 시작 자세는 `HOME_PATH_UNAVAILABLE` 또는 `SCENE_REJECTED`로 거절한다. 자동 손목 풀기/관절 홈 직행/그리퍼 열기는 추가하지 않았다.
- 새 요청 시작 때의 홈 경유이며, 실패 후 홈으로 자동 이동하는 기능은 아니다. 실패·취소 처리 원칙은 동일하다.
- 홈 관절 숫자를 임의 생성하지 않는다. 현재 관절부터 같은 IK 가지의 연속성을 검사하고 최종 관절·TCP를 `home_state`에 남긴다.

진행에 `HOME_CHECK`, `HOME_MOVE`, `HOME_READY`가 추가된다. 탐색 중 2초마다
`probe_progress` telemetry와 터미널의 이동 거리/남은 거리/기준 힘 수집 여부를 표시한다.

이동 60 mm/s, 접근 30 mm/s, 이탈 5 mm/s로 시험 프로파일을 조정했다. 윗면 접촉 0.3 mm/s,
옆면 접촉 1 mm/s는 유지한다. 윗면 접근 시작은 기존 확인 범위 위 4 mm인 TCP Z 240.705 mm로
줄이며 탐색 하한은 그대로다. 이동 기준 수집(2~3.25 mm)이 가장 높은 예상 접촉 위치보다
위인지 검사한다. 빈 공간 기준 힘 변화 한계(기존 가드 5 N)와 수집 후 접촉 변화 한계(2 N)를
분리해, 기준 수집 전에 접촉 한계로 중단되던 문제를 수정했다. 원신호 접촉 한계 10 N은 유지한다.

**120초 완료 목표는 아직 달성하지 못했다.** 기록된 시작 위치와 현재 접촉 속도로 계산한
이동·기준 수집·정지 안정화 예상은 약 186초이며 IK·ROS 지연이 더해진다. 따라서
`target_duration_s=120`은 요청 목표, `runtime_timeout_s=360`은 실패 처리 상한이다.
시간초과를 완료로 표시하지 않는다. 단독 전체 8점은 270.394초, 빠른 후퇴 반복 시험은 HOME 회전 경유 포함 299.295초에 완료했다. 후자의 실행 당시 전체 제한은 300초였다. 재실행 시 지연 여유를 위해 전체 제한만 360초로 늘렸으며, 속도/힘/동작별 제한은 동일하다. 360초 변경과 지시 위치 유한값 검사는 모의 검증이며 추가 실기 회차로 세지 않는다.
홈 경유 포함 983점의 제어기 IK/FK 조회는 통과했다. 조회 검사만 약 36.6초였고 실제 이동은 없었다.
근거: `test/fixtures/workpiece_home_preflight_0921.json`. 기존 실행 중인 시험 수신부는 종료 후 다시 실행해야 수정본이 적용된다.

### 수직 자세 및 기준 힘 수집 수정

- ZYZ `(A,B,C)`와 `(A+180,-B,C+180)`이 같은 회전을 나타내는 점을 이용해 현재 각도에 가까운 표현을 선택한다. `B≈-179.99°`를 반대 표현으로 바꾸면서 중간 경로가 뒤집혀 보이던 오류를 수정했다. 실제 기울기나 허용차는 변경하지 않는다. 경로 검사와 명령 생성이 같은 변환 함수를 사용한다.
- 정지 후 기준 힘 수집 중 위치가 0.1 mm 이상 변하면 수집 창을 다시 시작한다. 명목 시작점에서 0.3 mm 밖으로 벗어나거나 이동 상태가 관측되면 중단하며, 전체 안정화 제한 10초는 유지한다. 안정화가 끝난 실제 위치를 접근 시작 관측으로 사용한다.
- 접근 중 0.3 mm 횡오차 검사는 그대로이며, 실제 접촉 후보도 원래 검사한 선분 기준으로 다시 검사한다. 실패 후 후퇴·다음 점·홈 복귀를 자동 호출하지 않는다.

### 6점 이후 재시험 수정

- 동일 자세로 평행 이동할 때 현재 native ZYZ를 그대로 유지해 변환 왕복 오차로 검사와 명령의 자세가 미세하게 달라지는 문제를 없앴다.
- 기준 힘 수집은 실제/지시 TCP 위치 차이가 0.02 mm·자세 차이가 0.02° 이내로 정착된 구간에서만 진행한다. 센서 힘이 안정적이어도 위치가 아직 정착 중이면 수집 창을 다시 시작한다. 최대 대기 10초와 접근 횡오차 0.3 mm 한계는 그대로다.
- 6점 후 바깥 이동의 가속도는 40→20 mm/s²로 낮춰 재시험한다. 접근 속도 30 mm/s, 접근 원신호 힘 한계 10 N은 유지한다. 이 값 변경 자체는 실기 통과 근거가 아니다.
- HOME 계획에서 분할 회전 끝점과 같은 최종 정렬 목표를 중복 전송하지 않는다. 중복 명령으로 이동이 발생하지 않아 시작 감시가 중단하던 오류를 수정했다.
- 새 측정 요청의 HOME 계획은 관측한 J6를 사용해 상공에서 회전 방향을 선택할 수 있다. 중간 회전은 90° 이하로 나누고 실제 IK/FK·관절 검사를 전 구간 통과해야 움직인다. 실패 후 자동 복귀가 아니라 **새 요청 시작 시 또는 정상 측정 종료 후의 홈 경로**다. 현재 고정 장착/상공 통로에 한정한다.

- 과거 성공 실행기와 대조해 `workcell.outer_move_profile=escape`와 `profiles.escape`를 추가했다. 생략한 기존 호출자는 `approach`를 계속 사용한다. 사용자의 후속 요청을 반영한 REAL 예제의 escape는 공중 이동과 같은 60 mm/s·60 mm/s², 15 N 즉시 정지만 적용한다. travel/escape의 12 N 지속 판정은 제거했다. 15 N은 기존 소프트웨어 상한이며 충돌 세기의 인증값이 아니다. 접촉 후 저속 후퇴를 마친 외곽 이동과 이미 표면에서 벗어난 HOME 외곽 이동에만 사용한다. 접촉 탐색·표면 인근 저속 후퇴·안쪽 접근은 10 N을 유지한다. 제어기 보호 설정을 바꾸지 않는다.
- 이미 표면에서 `slow_retract_gap_m` 이상 벗어난 시작점에서는 HOME용 짧은 저속 후퇴를 반복하지 않고 검사된 외곽 이탈로 시작한다.

## 호출 경계

1. 대쉬보드 → 세은의 제어 노드: 준비·측정 Action 요청(이름/필드는 합의 전).
2. 세은: 로봇 준비 상태 검사 후 `measure_workpiece()` 내부 함수 호출.
3. 우리 모듈 → 세은 제어 노드 → 대쉬보드: 진행 Feedback과 최종 측정 Result.
4. HMI → 홍동: 실측 스냅샷으로 경로 생성 → 미리보기.
5. 조각 실행 요청 → 세은의 최종 경로·관절 검사 → 시율 `execute_path()` 호출.

별도 시율 측정 Action 서버는 만들지 않는다. 세은의 제어 노드가 측정과 조각의
공통 모션 소유권을 관리한다. 측정용 IK/FK 검사는 시율 측정 어댑터에서 수행하며,
세은 `joint_check.py`를 수정하거나 이 모듈에서 호출하지 않는다.

## 현재 구현·확인 수준

| 항목 | 상태 |
| --- | --- |
| 윗면 측정 → 45° 간격 옆면 8점 → 원 맞춤 → 마지막 후퇴 확인 | 코드 + 기하 모의 + 단독 실기 CONTACT_REFERENCE 완료 |
| 시작/윗면/점별 성공/완료 Feedback 콜백 | 코드 + 모의 시험 |
| 취소·실패·시간 초과·통신 단절·정지 미확인 | 코드 + 장애 주입 시험 |
| 중심과 반지름을 동시에 추정 | 기존 8점 실측 자료 재계산 대조 |
| REAL 서비스 I/O/관측/정지/접촉/IK·FK 어댑터 | 코드 + 가짜 I/O + 실제 ROS 이동/취소·정지 확인. 단독 CONTACT_REFERENCE 모드 윗면·8점·후퇴 연속 2회 완료. 공통 Action 통합/절대 윗면 Z 검증과 구분 |
| 운영 준비 Action 수신부 및 `.action` 타입 | 미구현. 시험용 Trigger 수신부와 구분. 수현·세은과 계약 필요 |
| 그리퍼 밑면 접촉점 오프셋 | REAL 미확인. SIM 예제의 10 mm는 합성값 |
| 현장 진입·원호·후퇴 검사/모션 소유권 | 제한된 현장 단독 시험용 연결 구현. 공통 제어 노드 소유권 통합은 별도 |

기존 시험의 176초는 옆면 8점 재측정의 기록이다. 이번 윗면 포함 함수의 3분 완료나
실기 정확도를 확인한 기록이 아니다. 새 코드의 REAL 실행은 이 문서만으로 승인되지 않는다.

## 파일

- `c2_process/workpiece_calibration.py`: 측정 순서·설정 검사·이벤트·원 맞춤·StepResult.
- `c2_process/measurement_robot_adapter.py`: 측정 전용 내부 어댑터. 실제 상태/힘/관절 조회,
  표본 IK/FK 검사, 비동기 이동 후 완료 확인, 접촉 후 정지 확인. 새 ROS 노드는 아니다.
- `c2_process/workpiece_simulation.py`: ROS를 전혀 호출하지 않는 원통 기하 모의 백엔드.
- `config/workpiece_simulation.json`: 바로 호출 가능한 SIM 설정. REAL 사용 금지.
- `config/workpiece_trial_guards.json`: 이전 시험을 출처로 한 검토용 가드 설정.
  제조사 관절 사양이나 새 실행 코드의 실기 인증값이 아니다.
- `test/workpiece_simulation_demo.py`: 수신부 내부 호출 예제, 실행 가능한 모의 데모.

기존 `robot_adapter.py`, `engraving.py`, `tool_calibration.py`와 다른 담당의 파일은 수정하지 않았다.

## 바로 호출하기

패키지 디렉터리에서:

```sh
python3 test/workpiece_simulation_demo.py
python3 -m pytest -q test/test_workpiece_calibration_mock.py test/test_measurement_robot_adapter_mock.py
```

```python
from c2_process.workpiece_calibration import MeasurementContext, measure_workpiece
from c2_process.workpiece_simulation import SimulatedWorkpieceAdapter

ctx = MeasurementContext(
    measurement_id="measurement-001",
    preparation_id="preparation-001",
    source_mode="SIMULATION",
    motion_lock=shared_motion_lock,
)
adapter = SimulatedWorkpieceAdapter(config["workcell"], clock=ctx.monotonic)
result = measure_workpiece(
    adapter, config["workcell"], config["profiles"], ctx,
    on_progress=publish_feedback,  # 수신부에서 Action Feedback으로 변환
)
```

`config`는 JSON을 읽은 사전, `shared_motion_lock`은 수신부가 보관하는 공통 Lock,
`publish_feedback`은 콜백이다. 모의 데모에는 이 세 가지의 실행 가능한 예가 들어 있다.
측정은 동기 함수이므로 Action 콜백에서 executor를 막지 않도록 작업 스레드에서 실행한다.

취소는 `ctx.cancel.set()`으로 전달한다. 이후 반환이 STOPPED인지 UNKNOWN인지 확인하고
Action의 canceled/aborted 상태로 변환한다. 취소 요청 접수 자체를 정지 완료로 표시하지 않는다.

## 동작과 좌표

- 길이: m, 힘: N, 자세: `[x,y,z,qx,qy,qz,qw]`, 관절: rad, 좌표계: `c2_base`.
- 입력/어댑터 내부 목표 pose는 드릴 끝 기준. native TCP mm/ZYZ 변환은 어댑터가 담당한다.
- 윗면은 **그리퍼 밑면**으로 접촉한다. 드릴 끝 관측 pose에서 도구 오프셋을 빼 TCP를
  복원하고, 그리퍼 밑면 오프셋을 더해 실제 접촉점 Z를 계산한다.
- 옆면은 tool -Y가 중심을 보고 tool +Z가 base -Z를 향하도록 8점 생성한다.
- 기준 중심·반지름은 탐색 경로를 정하는 입력이다. 최종 원 맞춤에서는 둘 다 자유 변수다.
- 150 mm 높이는 `height_source=OPERATOR_RULER`로 재사용한다. 로봇이 높이까지 독립적으로
  재측정했다고 표시하지 않는다. `bottom_z=top_z-height`는 계산값이다.
- 위/아래 10 mm 제외 → 윗면 기준 아래쪽 v=10~140 mm,
  base Z 범위 `[top_z-0.140, top_z-0.010]`.
- 수직 원통 가정. 기울기·테이퍼·가공 깊이 정확도는 이번 측정으로 검증하지 않는다.
- 최초 진입 및 윗면→옆면 이동은 임의로 안전하다고 가정하지 않는다. REAL의 `scene_check`
  콜백이 현재 위치부터 탐색 끝점·접촉 후 후퇴 전체를 검사해야 다음 단계가 시작된다.

## Feedback 사전

| 필드 | 의미 |
| --- | --- |
| `measurement_id` | 요청자가 발급한 측정 ID |
| `sequence` | 해당 호출에서 1부터 증가하는 이벤트 번호 |
| `measured_at` | 이벤트 생성 UTC 시각(센서 취득 시각과 다름) |
| `stage` | START / HOME_CHECK / HOME_MOVE / HOME_READY / TOP_APPROACH / TOP_TOUCH / SIDE_START / SIDE_TOUCH / FIT / COMPLETE / TERMINAL |
| `status` | RUNNING / SUCCEEDED / FAILED / STOPPED / UNKNOWN |
| `point_index`, `total_points` | 윗면은 0, 옆면은 1~8; 전체 옆면 점 수 8 |
| `message` | 화면 표시 문구 |
| `values` | 확보한 윗면 Z 또는 점 좌표, 마지막에는 최종 결과 |

초록색은 `TOP_TOUCH` 또는 `SIDE_TOUCH`의 SUCCEEDED에서 표시한다. 명령 수락만으로 보내지
않으며 접촉 판정·실제 정지·측정값 유효성을 확인한다. 8번째 점 성공, 마지막 외곽 후퇴, 홈 복귀 완료는
다른 사건이다. 전체 성공은 Action 최종 Result까지 확인해야 한다.
HMI는 이벤트를 ID/sequence 기준으로 저장해야 새로고침 후에도 이력을 볼 수 있다.
콜백에는 복사본을 전달한다. 콜백 예외는 통신 전달 실패로 취급하여 정지를 확인하고 종료한다.

## 최종 StepResult

`result.observed_state`:

- `measurement`: 중심 `axis_xy_m`, `radius_m`, 윗면 `top_z_m`, 높이·출처,
  바닥 Z, 작업 높이 범위, 각 접촉점·법선 힘, 원 맞춤 RMS/최대 잔차, 유효성.
- `measurement.source_mode`: SIMULATION / REAL. SIM 결과의 `validity`는 SIMULATED.
- `measurement.geometry_ready`: 해당 실행 모드에서 기하 계산·수집이 완료됐는지.
  이것만으로 실기 조각/충돌/깊이 정확도 검사가 끝났다는 뜻이 아니다.
- `measurement.measured_at`: 결과 계산 완료 UTC. `started_at`은 시작 UTC.
  접촉점에는 센서 관측 `measured_at_monotonic_s`와 전달 `received_at`을 구분한다.
  monotonic 값은 PC 간 절대시각 비교에 사용하지 않는다.
- `measurement.profile_snapshot_id/profile_sha256`: 호출자가 전달한 등록 스냅샷 참조.
  이 함수가 HMI 최종 파일 바이트의 해시를 발급/검증하지 않는다. 수신부가 파일을 확인한다.
- `plans`: 실제 검사에 넘긴 계획·설정 객체의 내부 SHA-256과 검사 보고.
  이 해시를 HMI 파일의 profile_sha256으로 대신 쓰지 않는다.
- `events`: 이번 호출의 진행 이력, `partial`: 미완료 여부, `stop_confirmed`: 정지 확인,
  `elapsed_s`: 사전 검사와 전체 측정을 포함한 함수 소요 시간.

| outcome | 의미 |
| --- | --- |
| SUCCEEDED | 윗면·8점·형상 검사·마지막 후퇴 및 홈 복귀·정지 확인 완료 |
| FAILED | 입력/준비 불충족 또는 동작 실패. 동작 시도 뒤에는 정지 확인된 실패 |
| STOPPED | 취소됨. 동작 시도 뒤에는 실제 정지 확인 |
| UNKNOWN | 동작/정지 결과 확인 불가. 성공으로 바꾸거나 다음 작업 호출 금지 |

이동을 시도하지 않은 초기 실패/취소에서는 `stop_confirmed=null`이다. 불필요하게 다른
작업의 로봇에 정지 명령을 보내지 않는다. 실패·취소 후 자동 후퇴, 홈 이동, 재전송은 없다.
부분 접촉점은 보존하되 `geometry_ready=false`, `validity=INCOMPLETE`로 반환한다.

## REAL 연결 계약

`GuardedMeasurementAdapter`는 다음 의존성을 받는다.

- `io=RosMeasurementIO(node, controller_prefix, timeout_s)`: 별도 스레드에서 spinning 중인
  기존 executor/node를 사용한다. `controller_prefix`는 ROS namespace이며 파일 절대경로가 아니다.
  설치된 Jazzy dsr_msgs2 소스 대조 및 첫 단독 실물 시험에서 실제 조회·이동·정지 호출을 확인했다.
- `tool_offset_m`: 승인한 고정 장착 기준. workcell 설정과 일치해야 한다.
- `guards`: 위 검토용 JSON과 같은 키의 명시적 설정. 하드웨어 보호 설정을 바꾸지 않는다.
- `readiness(context)`: 최신 로컬 상태를 읽어 `measurement_id`, `checked_at_monotonic_s`,
  `ownership_confirmed`, `drill_off_confirmed`, `mount_fixed`, `control_authority`를 반환한다.
  값을 상수 True로 채우는 실행용 콜백은 허용하지 않는다. 매 감시 주기 호출되므로 비차단 조회여야 한다.
- `scene_check(steps, workcell, initial_observation)`: 전체 진입/전환/원호/탐색/후퇴와 도구 형상의
  간섭 검사를 수행해 `path_checked`, `probe_envelopes_checked`와 검사 기록을 반환한다.
  표본 IK 통과를 충돌 검사 통과로 대신 쓰지 않는다. 단독 시험에는 workpiece_real_trial.check_trial_scene를 연결한다. 범용 현장 검사기를 뜻하지 않는다.

ABSOLUTE_GEOMETRY의 REAL workcell에는 `tcp_id`, `load_id`, `top.offset_status=VERIFIED`, `top.offset_record_id`와
실제로 확인된 `top.contact_offset_tool_m`가 필요하다. ctx에는 등록 스냅샷 ID/해시가 필요하다.
미확인 그리퍼 밑면 오프셋을 0이나 SIM의 10 mm로 채워 실행하면 안 된다.

측정 어댑터는 모든 계획 구간을 설정 간격으로 보간하여 고정 solution space의 IK/FK와
관절 범위·연속성을 확인한다. ZYZ B=180°에서 A/C 표현에 의한 가짜 장회전을 줄여 같은 표현을
명령에도 사용한다. 제어기 내부의 연속 궤적/완전한 충돌 검증은 아니며 실기 대조가 필요하다.

Action 수신부에서 추가로 구현할 것:

1. `.action` 이름·필드와 HMI 변환. 이 모듈의 내부 사전 형식을 기존 ROS 계약으로 오인하지 않는다.
2. 동일 측정 ID의 중복 요청 거절/이전 결과 반환. 함수 자체는 요청 원장을 관리하지 않는다.
3. 측정·조각 공통 소유권/취소·비상정지 연결. `MeasurementContext.motion_lock` 기본값은
   **컨텍스트 하나의 Lock**뿐이므로 여러 요청은 반드시 서버의 공유 Lock을 전달한다.
   별도 프로세스 간 배타 제어는 이 Lock으로 해결되지 않는다.
4. HMI 스냅샷 파일 해시 확인, 최종 결과 저장·스냅샷 등록, 측정 변경 시 경로 재생성.

## 검증

기존 패키지 시험 포함 106건 통과:
정상 윗면/8점, 점별 Feedback, 독립 원 맞춤, 기존 8점 기록 재계산,
잘못된 입력/좌표계/오프셋, 미지원 어댑터, 중복 동시 실행 Lock,
취소 전/중, callback 오류, 실제 정지 미확인, 통신 단절, 시간 초과,
잘못된 접촉 위치, 사전 검사 누락/실패, 마지막 후퇴 실패,
목표 미도달/가짜 조기 완료, ZYZ 단회전, 힘 한계와 윗면/옆면 접촉 모의.
운영 Action 통합 및 절대 윗면 검증은 미실시다. 단독 시험 수신부와 제어기 조회 검증은 상단 추가 기록 참조.

## 공정 연결용 반환 예시

[정상/실패/취소/시간 초과/통신 단절 예시](test/fixtures/workpiece_contract_samples/README.md)는 현재 함수의 실제 SIMULATION 호출 결과 발췌다. 장치 정지 확인 코드는 `measurement_robot_adapter.py:stop_measurement()`이며, 정상 정지 관측이 확인되어야 `stop_confirmed=true`를 반환한다. `.action`과 세은 담당 수신부는 이 변경에 포함하지 않았다.

### 실기 완료의 제한

- 시험 8/9의 bag을 다시 읽어 각 27개 진행 이벤트, 1~8점 완료, SUCCEEDED, stop_confirmed=true를 확인했다.
- 홈 상공 경유에서 제어기 level 1 코드 3205/3206(특이점 영역 진입/이탈) 알림이 기록됐다. 정지 알람이나 관절 한계 초과로 종료되지는 않았지만 **특이점 영역에 전혀 들어가지 않았다고 주장하지 않는다**. 현재 J3/J5 수치 여유 검사와 제어기 영역 판정이 같지 않다는 제한을 보존한다. 관련 메시지는 실기 fixture에 포함했다. 제어기의 singularity handling/보호 설정은 변경하지 않았다.
- 반복 측정 중심 차이는 약 0.034 mm, 반지름 차이는 약 0.026 mm다. 같은 고정물의 두 센서 추정 비교이며 독립 측정 정확도가 아니다.
- 2분 목표, 그리퍼 밑면 오프셋/절대 윗면 Z, 운영 준비 Action 통합은 남아 있다.

## HOME 위치 정정 및 정상 종료 복귀 (최신 변경)

- 새 HOME은 윗면 접근 직전 상공 TCP다. 이미 홈이면 `build_top_plan()`의 첫 이동은 `top_approach`다.
- 형상 계산·검사가 통과한 뒤 `HOME_RETURN/RUNNING` → 현재 위치/관절 조회 → `build_home_plan()` → 경로 IK/FK/통로 검사 → 복귀 → 홈/정지 확인 → `HOME_RETURN/SUCCEEDED` → `COMPLETE` 순서다.
- 추가 결과 필드: `observed_state.home_return_confirmed`(bool), `home_return_start`와 `final_state`(관측 구조). 홈 검사/이동 실패·취소 시 완료를 반환하지 않고 기존 정지 확인 절차를 적용한다. 실패 후 자동 복귀는 여전히 없다.
- 세은·HMI 연결 시 진행 단계 `HOME_RETURN`을 표시하고, 새 성공 의미에 맞춰 COMPLETE를 기다린다. 함수 인자와 공통 ROS Action 정의는 바꾸지 않았다. 설정을 사용하는 쪽에서는 새 스냅샷으로 등록해야 한다.
- 검증: 관련 시험 147개 통과. 현재 8점 종료 자세에서 새 홈까지 **485개 제어기 IK/FK 표본 조회 통과**(이동 없음). `test/fixtures/workpiece_overhead_home_preflight_0921.json` 참조.
- **이번 HOME 변경·종료 복귀를 포함한 전체 실물 실행은 아직 하지 않았다.** 위 감독 시험 8/9는 이전 HOME·외곽 종료 방식의 기록이다. 기존 실기 시간을 새 홈 왕복 시간으로 표시하지 않는다.
