# 2026-10-14 사전 배치와 실행 진입점 불일치

이 기록의 원본 로그·교체 전 wrapper와 JSON 근거는 현장 폴더 `/home/rokey/Documents/ChatGPT/로봇제어 개발/reports/round2_entry_collision_20261014/`에 보존한다. 아래의 `.before`·증거 파일은 이 저장소의 docs 폴더 파일이 아니다.

사용자가 보고한 충돌 실행은 `trial-1791946671023653020`이다. 기존 `run_cycle_real.sh`가 standalone held 한 사이클을 실행하여 공급 노랑2×2 **slot1 → (11,11),layer1**을 명령했다. 요청한 세 Step의 T1은 **slot4 → (9,9),layer2**다. 자료/명령을 혼용 가능하게 남긴 D 진입점 오류다.

| 항목 | 이번 실제 로그 | 올바른 T1 |
|---|---|---|
| 프로그램 | held_corner_stud_trial.py | round2_three_step_trial.py |
| 공급 슬롯 | 노랑2×2 종류별1 | 노랑2×2 종류별4 |
| 배치 | (11,11),1층 | (9,9),2층 |
| 목표 TCP XY | [472.054993,85.742577]mm | [439.346779,53.590132]mm |
| 접근 Z | 35.516249mm | 53.635532mm |
| placement reference Z | 15.516249mm | 33.635532mm |

잘못된2×2 footprint는 (11,11),(11,12),(12,11),(12,12)다. 사전1층 P02 파랑2×3과4/4가 겹치며, 2층 P06 파랑2×3과는 (11,11),(11,12) 두 점이 겹친다. 정확히 어떤 면이 먼저 닿았는지는 로그만으로 구분하지 않는다.

line363에서slot1, line1041에서잘못된접근목표, line1048에서하강명령을확인했다. 마지막full표본line1130은 TCPZ48.83075mm/velZ−9.2129mm/s/motion_status2/robot_state5/gripper_status3/합력75.3272N/Fz73.6799N이다. line1131의STOP 요청은acknowledged=false, stillness_verified=false이며 `SERVICE_FAILED: motion/move_stop`을반환했고 정리STOP도실패했다. I/O/P 이벤트는없다. 가압45N 단계전접근에서문제가발생했다.

현재 정지·파지·보호정지 해제 여부를 이 로그로 확인하지 못한다. 실제 펜던트의 정지/보호정지와 끼임·구조물 상태를 작업자가 확인해야 한다. 충돌 상태를 정상 held 상태로 가정하여 이전 resume 명령으로 이어가는 조치는 하지 않았다. 실제 로봇·그리퍼·ROS 연결이나 복귀 명령을 수행하지 않았다.

기존 `run_cycle_real.sh`는 현재 `run_three_step_real.sh`로, 기존 `run_offline_checks.sh`는 `run_three_step_offline.sh`로 연결했다. 두 기본 명령이 같은8블록배치/세Step을사용한다. 시작표시는 T1 slot4/(9,9,L2)와세사이클을명시한다. 이전wrapper 원문과로그는이폴더의 `.before`/events.jsonl로보존했다.

검증: bash문법, 격리된 fake-python으로실제wrapper가호출하는argv/cwd확인, 장치없는실제preview로T1 slot4/(9,9,L2)/XYZ를대조했다. 모두PASS이며 physical_commands0/실제driver생성0이다. 제어값·장치조건·힘·pose gate를추가하지않았다. 기존오프라인1446PASS는제어코드검증이고이번수정wrapper검증과구분한다. 수정된새진입점의실물재실행은미검증이다.

근거: collision_excerpt.json, entrypoint_verification.json, launcher_dry_invocation.json, three_step_preview.json, 원events.jsonl.
