# 랜선 없이 HMI·경로·공정 노드 통합 실행

> **9/22 가상 셀 실행·검증 기록.** 아래 `/tmp/c2-hmi-partial-integration`은 당시 작업 디렉터리다. 현재 checkout에서는 저장소 루트에서 `bash ws_cobot_pjt/tools/run_virtual_cell.sh`를 사용한다. 아래 시험 수치·구현 상태는 당시 커밋의 기록이며 2026-09-23 `main`의 타입·현장 검증 상태는 [현재 현황](../../docs/REVIEW_STATUS.md)을 따른다.

기준 main `688c781` (홍동 PR #62, 세은 PR #63), 작업 브랜치 `codex/hmi-partial-integration`.
실제 로봇·두산 드라이버를 기동하지 않는다. 세 노드의 실제 코드를 ROS 2 Jazzy로 연결하고 장치 경계만 가상으로 대체한다. 모든 가상 요청/산출물은 SIMULATION이며 REAL 데이터로 위장하지 않는다.

## 실행 — 이 PC

```bash
cd /tmp/c2-hmi-partial-integration
bash ws_cobot_pjt/tools/run_virtual_cell.sh
```

브라우저: http://127.0.0.1:8020/operator

1. PNG/JPEG 도안을 선택한다.
2. 사전 검사·양초 측정 요청 → BIND 완료를 기다린다.
3. 배치를 정하고 경로 생성을 누른다. 실제 c2_path가 이미지를 계산한다.
4. 미리보기·고정 확인·시험용 드릴 ON 확인 후 실행한다.
5. 실제 c2_process의 단계·진행·결과를 확인한다. 정지 요청도 가능하다.

화면 상단은 ‘가상 장치 · 로봇 미연결’이다. ZIP·JSON 업로드는 없다. 가상 설정과 측정 결과는 HMI가 등록하고 경로/설정 ID·해시를 공정 노드와 대조한다.

다른 터미널에서 자동 왕복 검사:

```bash
cd /tmp/c2-hmi-partial-integration
bash ws_cobot_pjt/tools/run_virtual_cell.sh --check
# 사용자 도안으로 동일 흐름 검사
bash ws_cobot_pjt/tools/run_virtual_cell.sh --check --image /home/rokey/Pictures/Screenshots/도안용.png
```

`--check`는 가상 환경 표시·SIMULATION/ROS2 모드를 확인한 후에만 요청한다. 자동검사는 가상 준비·새 경로·가상 실행을 시작한다. 실제 서버에는 사용하지 않는다.

## 실패·정지 재현

이전 실행기를 Ctrl+C로 종료한 뒤 하나씩 기동한다. 같은 domain에 중복 기동하지 않도록 실행기가 잠근다.

```bash
# IK 실패
bash ws_cobot_pjt/tools/run_virtual_cell.sh --scenario ik_failure --data-dir /tmp/c2-virtual-ik
# 다른 터미널
bash ws_cobot_pjt/tools/run_virtual_cell.sh --check --expect FAILED
```

```bash
# 모션 명령 실패
bash ws_cobot_pjt/tools/run_virtual_cell.sh --scenario motion_failure --data-dir /tmp/c2-virtual-motionfail
# 다른 터미널
bash ws_cobot_pjt/tools/run_virtual_cell.sh --check --expect FAILED
```

```bash
# 이동 대기를 늘려 정지 확인
bash ws_cobot_pjt/tools/run_virtual_cell.sh --move-time .5 --data-dir /tmp/c2-virtual-stop
# 다른 터미널
bash ws_cobot_pjt/tools/run_virtual_cell.sh --check --stop-after .1 --expect STOPPED
```

정지/실패 상태를 강제로 정상화하지 않는다. 독립 시나리오를 다시 시험할 때 실행기를 종료하고 별도 data-dir로 시작한다. 기본 디렉터리의 이전 기록을 자동 삭제하지 않는다.

## 실제 코드와 가짜 경계

| 구성 | 사용 코드 |
| --- | --- |
| HMI/ROS gateway | backend/app/monitor.py, ros_bridge.py 실제 HTTP·ROS 클라이언트 |
| 경로 생성 | c2_path.node 실제 Action 서버·이미지 계산·검증·산출물 저장 |
| 공정 | c2_process.node의 create_ros_node/ProcessCoordinator 실제 Action·Service·상태·BIND·검사·실행 흐름 |
| 측정 장치 | SimulatedWorkpieceAdapter 가상 원통·접촉. 측정 알고리즘은 기존 코드 실행 |
| 로봇 장치 | 정확히 MockRobotAdapter 인스턴스. 합성 관절·TCP·IK·이동·정지 |

실행 어댑터와 준비 때 등록한 상태 어댑터는 같은 객체다. 공정의 준비 연결 검사를 생략하지 않는다. 최종 실행계획/관절 검사와 engraving은 기존 함수를 호출한다. 가상 IK·합성 상태가 실제 로봇의 도달성·충돌·힘·깊이·품질을 검증하는 것은 아니다. 정지 시험도 실제 비상정지 성능 시험이 아니다.

virtual_device 설정은 입력 설정과 최종 스냅샷에 포함되어 해시로 연결된다. 가상 실행 로더는 SIMULATION과 정확한 가상 설정만 받는다. 원본 경로·보고서·스냅샷의 바이트 검사를 기존 공정 로더에 맡기며 test_only/REAL 제한을 우회하지 않는다.

## 환경·로그

- `ROS_DOMAIN_ID=20`, localhost 한정, FastDDS. REAL 시연과 동일 domain 번호를 쓰지만 localhost 범위로 외부 로봇을 격리한다.
- 기본 포트 8020 (기존 8010 HMI와 분리), `--port`로 변경 가능. 검사에는 같은 `--url`을 사용한다.
- 기본 데이터: `ws_cobot_pjt/backend/monitor_data/virtual_cell`.
- `hmi.log`, `path.log`, `process.log`: 노드 로그. `device/virtual-motion-log.json`: 종료 시 가상 호출 기록.
- `device/preparation.sqlite3`, `device/execution.sqlite3`: 실제 공정 노드의 중복 방지 원장.
- Ctrl+C로 실행기와 세 자식 프로세스를 종료한다. 실기 종료 명령으로 사용하지 않는다.

셸 실행기는 이 작업트리의 Python 가상환경/ROS install을 우선하고, 없으면 같은 저장소의 기본 작업트리 환경을 사용한다. 당시 main 변경에는 c2_interfaces 변경이 없었으며 Python 소스는 항상 현재 작업트리에서 가져왔다. 새로운 PC는 Jazzy 및 c2_interfaces 빌드, backend requirements-image.lock.txt 설치, `pnpm --dir ws_cobot_pjt/frontend install --frozen-lockfile`와 `pnpm --dir ws_cobot_pjt/frontend build`가 필요하다. C2_PYTHON으로 가상환경 Python을 지정할 수 있다. ROS 드라이버 워크스페이스는 필요하지 않다.

## 최신 main 데이터 검사에서 수정한 연결 오류

1. 최신 REAL 실행 후보 `/4`는 calibration_status를 필수로 쓰지 않는데 HMI가 요구하던 조건을 제거했다. 측정 validity를 원본 값으로 갱신한다.
2. 공정 로더가 execution_readiness 존재만으로 c2_path 원본 보고서를 HMI 외피 형식으로 오인하던 부분을 고쳤다. 고유 필드 geometry_passed로 구별하고 기존 원본 보고서의 통과·항목·경로 연결 검사는 유지한다.

REAL 계약 데이터 검사에는 명시적 시험 측정/설정 fixture를 사용했다. 당시 `/4` 계산 → HMI 산출물 검증 → HMI HTTP 자산 조회 → 공정 실행 입력 로더까지 통과했다. 실제 REAL 측정·실기 실행 완료가 아니다. 당시 `PrepareWorkpiece` Action의 절대 윗면 확인 필드가 빠져 있었으나, 9/22 후속 PR #67에서 두 bool 필드가 추가됐다. 같은 커밋의 공통 타입을 빌드해야 한다.

## 검증 기록

- 최신 REAL 데이터/전송 검사 13개 통과. 로봇 모션 호출 없음.
- 백엔드 전체 회귀시험: 135개 통과, 4개 건너뜀.
- 공정 node/preparation 회귀시험 283개 통과, 2개 건너뜀.
- 실제 localhost ROS Action/Service 시험: 정상 SUCCEEDED, IK 실패 FAILED, 모션 명령 실패 FAILED, 이동 중 정지 STOPPED 확인.
- TypeScript·Vite 빌드, 저장소/구문·문서 링크, hook 8개·Issue manager 27개·설정·diff 검사 통과.
- 실물 구동·가공 품질·실제 IK/간섭 검증은 미수행. 이 문서의 시험 시점에는 해당 작업트리가 미커밋·미게시 상태였다. 이후 main 병합 여부는 [당일 일지](daily/2026-09-22.md)를 따른다.

사용자 `/home/rokey/Pictures/Screenshots/도안용.png` 실제 파일로도 준비/BIND → 경로 생성 → 공정 종료 `SUCCEEDED / 303 구간 완료`를 확인했다. 경로 ID `789b10ca-0e76-4fdf-8e0e-8d865c40c2de`, SHA-256 `7b677f860a7d4796586550a89b6f4255af37245b95210754f6b788f0b80e198a`. 기록은 `/tmp/c2-virtual-character`에 있다. 사용한 모션은 모두 MockRobotAdapter 호출이며 실제 로봇은 연결하지 않았다. 시험 실행기는 종료했다.

### 2026-09-22 실행 기록·완료 표시 보완

- 성공 결과는 HMI 실행 요약에 FINISH·100%로 저장하며, 이후 상태 토픽으로 종료된 실행 요약을 덮어쓰지 않는다. 실패·정지는 성공으로 변경하지 않는다.
- 가상 실행기는 각 실행의 성공·실패·정지 결과 기록 시 `device/motion-<run_id의 SHA256>.json`을 원자적으로 저장한다. 요청·실행·경로 ID/해시, 결과, 최종 실행계획 signature를 포함한 observed_state와 해당 실행의 가상 호출을 담는다. 이전 실행 호출은 제외한다. 강제 종료 전에 결과가 없으면 이 완료 로그도 없을 수 있다.
- 수정은 실행기 재시작 후 새 실행부터 적용된다. 진행 중 시험을 중단하거나 과거 상세 로그를 복원하지 않는다.
- 현재 제한: 경로 생성 대기 120초, ROS Goal 접수 3초, 실행 결과 대기 3600초. 실행 결과 대기 초과 시 취소 요청을 보내고 HMI는 결과 미확인으로 처리한다. 취소 접수는 실제 정지 확인이 아니다.
- 가상 프로파일의 개별 이동 제한은 90초이나 MockRobotAdapter는 deadline을 강제하지 않고 move_time(기본 0.06초)과 취소를 모의한다. 따라서 개별 이동 시간 초과 검증은 별도 가상 시나리오 보완이 필요하다. 전체 소요시간은 실기 가공시간의 예측값이 아니다.
- 검증: 모니터 회귀 및 가상 실행별 기록 시험 24개, 완료 후 늦은 상태 수신 회귀 시험 1개 통과. 실제 로봇 미연결.
