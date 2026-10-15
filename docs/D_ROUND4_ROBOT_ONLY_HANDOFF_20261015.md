# Round4 로봇 단독 조립 인계·설계 과제

2026-10-15 사용자 요청. 이 문서는 개발 목표이며 round3의 사람 인계·지지 동작을 변경하지 않는다.
`codex/integration-round4`는 최신 로컬 `codex/integration-round3`와 같은 커밋에서 시작한다.
원격 게시 인증 대기 상태와 성공 여부는 `D_ROUND3_PUBLISHED_RUNTIME_20261015.md` 및 실제 remote ref를 확인한다.
새 채팅용 요청문은 [ROUND4_NEW_CHAT_PROMPT](ROUND4_NEW_CHAT_PROMPT.ko.txt)에 있다.

## 목표와 현재 한계

빈 조립판 INITIAL → 로그인/C 설계 대화·미리보기·사용자 승인 → A 전체/매 Step 계획 →
D 공급 집기·운반·직접 결착·개방·가압·상승·HOME → 실제 B STEP → 남은 조립 → 별도 B FINAL →
사용자별 DB 저장·웹 표시를 사람의 전달/조립/지지 없이 연결한다. 설계 승인과 정지/현장 확인은 유지한다.

현재 round3는 ROBOT_GRIP/x/NONE의 제한된 native 결착과, 불가능한 Step의 실제 A HUMAN_ASSEMBLY
재평가·place board 전달을 지원한다. 후자는 round4 목표의 구현 증거가 아니다. round4에서는 미교시·충돌·
도구 접근 불가를 사람이 받는 동작으로 바꾸지 않고 HOLD/C 재설계 대상으로 남겨야 한다.

C의 `MIN_SUPPORT_STUDS=4`는 노랑/파랑2×2에4점,2×3에 최소4점,빨강1×2에 자기2점 전부를 요구한다.
이 조건만으로 로봇 접근·하부 구조의 안정성·개방/가압·이탈 가능성이 증명되지는 않는다.
A의 `test_total_four_studs_does_not_erase_per_lower_hold`처럼 합계4점이어도 개별 하부 지지가 남는 경우를
검토한다. 사용자 의도에 맞는 지지 모델을 먼저 정하고, 도움 필드를 NONE으로 덮어써 통과시키지 않는다.

## 1. 우선 확인할 코드

| 구간 | 주요 파일 | 현재 상태와 round4 작업 |
|---|---|---|
| C | `app/c_design/validator.py`, `llm.py`, `designer.py`, `main.py` | 4점/빨강2점 지지는 이미 존재. 로봇으로 수행 가능한 grasp/방향/배치 조건과 새 빨강 방향 정의 반영 여부 검토. 미리보기·별도 승인 유지 |
| A | `planning_trial/assembly_optimizer.py`, `assembly_geometry.py`, `assembly_profiles.py`, `assembly_target.py`, `assembly_wire.py` | x/y 접근, 하부 HOLD·human press·RELEASE_PRESS 평가가 존재. 가용 교시와 실제 D capability를 이용해 로봇 단독 후보/순서/모션을 선택하도록 수정 필요 |
| B | `perception/perception_mvp/{contracts,depth_grid,inspection,backend_adapter,assembly_roi}.py` | Current/revision/공간 비교/검사 결과 소유 유지. 빨강 방향 의미 변경 시 경계 변환과 예상/실제 footprint 일치 검증 필요 |
| D 기하·교시 | `app/cad_trial.py`, `app/assembly_board_calibration.py`, `robot_control_integration/app/round2_operator_teaching.py` | 현재교시의 적용 범위·손목/TCP 관계 확인. grip별 공급/조립 교시 binding과 좌표 계산 수정 필요 |
| D 공급 비전 | `robot_control_integration/app/supply_stud/{execution_profile,depth_center}.py`, `robot_control_integration/scripts/supply_pick_release_trial.py` | 기존 RGB-D/깊이 중앙값·관측 자세/시각 검사 유지. 1/2/3점축 grasp 중심과 TCP 오프셋 분리 필요 |
| D 제어 | `robot_control_integration/scripts/{held_corner_stud_trial,held_xy_seating_trial,round2_three_step_trial}.py`, `robot_control_integration/app/assembly_step_runner.py` | I/O/P/U 수동 시험과 고정 자세 가정 존재. 검증된 자동 상태 전이 및 grip/방향별 결착·해제·가압·상승 경로 구현 필요 |
| D 통합 | `app/round3_service.py`, `round3_handover.py`, `round3_service_hmi.py`, `round3_stack_review.py` | round3 사람 전달/지원·B 실패 체크박스 존재. round4에서 전달 fallback 및 정상 과정 수동 완료 신호를 비활성화하고 로봇 단독 capability로 연결 |
| 저장·웹 | `history/mvp_save.py`, `history/personal.py`, `history/web.py` | 원칙적으로 재사용. robot 완료/B 완료/저장 완료를 분리하고 저장 재시도로 로봇을 재실행하지 않음 |

단순히 HUMAN_ASSEMBLY를 supported_modes에서 빼는 것으로 끝나지 않는다. x만 허용한 service,
교시 없는 y/3점축, 공통35mm 파지 가정, canonical 방향과 실제 grasp 방향, 수동 I/O/P/U,
RELEASE_PRESS 및 하부 지원 검사를 각각 검토한다. 제거/비활성화/수정/재사용/신규 교시를 파일별 표로 제출한다.

## 2. 방향 계약: 빨강은 현재 코드와 사용자 요청이 반대

아래 X/Y는 조립판에 표시한 축이며 로봇 Base축·카메라 픽셀축·J6와 다르다.

| 블록 | 현재 C/A 표준 | round4 사용자 요구 |
|---|---|---|
| 빨강1×2 | 0°=X1/Y2,90°=X2/Y1 | **90°=X1/Y2(1×2),0°=X2/Y1(2×1)** |
| 노랑/파랑2×3 | 0°=X2/Y3,90°=X3/Y2 | 기존 표준을 확인·유지하며 grasp 회전과 구분 |
| 노랑/파랑2×2 | 공통 Design은0°만 허용 | 정사각형 footprint와 별개로 TCP/파지90° 교시가 필요 |

red 방향은 표시문구/J6 값만 뒤집으면 안 된다. C validator/LLM, A footprint/support/grip 판단,
B expected/observed, D 판좌표 변환, HMI preview, 저장 이력까지 같은 의미인지 검토한다.
공통 계약을 바꿀지 경계에서 버전 있는 변환을 둘지 근거를 제시하고 결정한다. 과거 round3 저장 Design과
촬영 GT는 원래 의미를 보존하고, 같은 여섯 필드의 숫자를 조용히 재해석하지 않는다.
2×2의 물리적90° 파지를 Design orientation 허용 확대와 동일시하지 않는다.

## 3. 교시 행렬과 안내

먼저 기존 파일/실측 근거에서 존재/부족/미검증을 목록화한다. 아래 항목을 이미 교시된 것으로 가정하지 않는다.

- 2×3: **3점축 파지 신규 교시**와 기존2점축 재검토. 공급의 두 파지 방향 각각과 조립 목표0°/90°의 조합.
- 2×2: 두 직교 파지 방향의 공급·조립 교시. 조립판에서 물리적으로90° 파지한 상태의 교시를
  블록 canonical0°에도 연결한다. 정사각형이라 TCP/손가락 오프셋까지 같다고 가정하지 않는다.
- 빨강1×2: **1점축 파지 신규 교시**와2점축 파지의 존재/필요성 검토. 사용자 정의0°(2×1)/90°(1×2) 각각.
- 모든 사용 파지에서90°로 회전한 공급/조립 자세를 검토한다. 특히 **조립판90° 교시는2×2와
  2×3 목표0°에도 필요**하다. 이는 물체 목표 방향과 그리퍼의 파지 방향이 독립이라는 뜻이다.
- 색상별 동일 형상의 측정 재사용은 치수·도구 오프셋·슬롯/영상 근거가 일치할 때만 근거를 남긴다.
  공급25슬롯은 조건부 대상이며 전부 같은 pose로 처리하지 않는다. 층1~5의 높이 및 이탈 여유도 확인한다.

새 채팅은 표의 각 셀마다 `supply/assembly`, 블록/색/슬롯, 닫는 축의 stud수,
공급판 설치 방향, 목표판 방향, TCP 파지 회전, layer, 존재하는 교시 출처/해시, 추가 교시 필요 여부를 제시한다.
먼저 정지 상태의 읽기·사진/preview로 축을 설명하고, 현장 사용자가 한 조합씩 교시하도록 안내한다.
실제 이동 전에 해당 셀의 접근/접촉/이탈 경로와 작업공간을 검토한다.

각 기록은 공급/조립의 **전체 posj 6개와 posx XYZ+ZYZ 6개**, TCP/Tool,
좌표계·판 원점/축·블록 anchor/중심·파지폭/실측폭·접촉 단계·검토 상태를 구분해 저장한다.
공급판 J6와 조립판 J6는 서로 다른 자세다. J6 하나를 복사하거나 모든 목표에 J6+90을 쓰지 않는다.
가능하면 `T_Base_TCP`, 측정된 `T_TCP_Block`, 목표 `T_Base_Block` 관계로 계산하고 FK/IK·관절 범위와
손목 branch를 실제 로봇 기준으로 검토한다. 기존 retarget_pose의 ZYZ/강체 변환을 우선 재사용한다.
LLM이 관절각·교시 pose·힘·궤적을 생성하게 하지 않는다.

## 4. 비전과 중앙값/중심 추정

현재 `depth_center.rgbd_target`는 작은 유효 depth 패치 중앙값과 원본 카메라 보정·Base 변환으로
공급 표면 중심을 추정한다. 기존 stud 중심과 pose 검증을 재사용하되 중심을 얻었다는 이유로 파지점을
같은 값으로 놓지 않는다. grasp 축별 TCP↔블록 중심 변환은 별도 교시 근거가 필요하다.

1. 올바른 슬롯 ROI/stud 배열과 RGB 원본 좌표 변환을 확인한다. shadow/가림/잘못된 블록은 미확인으로 둔다.
2. 정지한 같은 관측 자세에서 fresh 동기 RGB-D와 CameraInfo의 유효 표본만 모아 중앙값/분산을 기록한다.
   NaN/0 depth/ROI 밖/이상치는 제외하되 표본 부족·시각/pose 불일치를 정상값으로 채우지 않는다.
3. 관측 중심을 매번 원본 교시에 대해 계산한다. 이전 Step/슬롯 오차를 다음 기준에 누적하지 않는다.
   공급 XY 보정을 조립판 목표 오프셋으로 재사용하지 않는다.
4. 최소 stud anchor→물체 중심→grasp TCP를 명시적으로 변환한다.1/2/3점축과90°의 half-pitch 차이를 시험한다.
5. 조립판은 독립 판 보정/층 높이/목표 방향/파지 강체 관계를 사용한다. 공급과 조립의 J6·회전/좌표계를
   분리한 overlay와 부호/비누적 모의 검증을 제시하고 작은 실물 교시로 검증한다.

## 5. round3에서 보존할 설정·근거

- 공급/HOME 준비/전달판 개방53mm·실폭40~80mm. 조립판 O 및 조립판 위 빈 패드 개방47mm·32~55mm.
- 빨강1×2의1점축 파지20mm·실폭10~40mm이며 grip 상태2도 필요하다. 3점축의 닫힘/해제 폭은 미교시다.
  **3점축 블록의 실제 폭보다47mm 개방이 충분한지 별도 확인**한다. 넓은 피드백 허용만으로 해제를 증명하지 않는다.
- I 반력 정지50N, P 반력 정지60N, P 합력70N 이상 HOLD, 접촉3mm/s, 일반 이동 기존2배.
  현재 P는 위치 하강+반력 STOP이며 일정60N 힘 제어나 실제70N 상한 보장이 아니다. compliance/desired_force는 사용하지 않는다.
- 공급 RGB-D 수평/높이/깊이 퍼짐10mm 등 현재 등록값·깊이518~542mm와25슬롯 binding을 먼저 읽는다.
  새로운 교시/축 요구를 이유로 임계값을 추가 완화하거나 원본 pose/교시를 덮어쓰지 않는다.
- B32157af(ROI/빈 칸 근거) 통합. INITIAL_MAX_UNKNOWN60열 등 실제 계약과 fresh 관측/STOP/HOME/writer 검사를 유지한다.
- 최신 실제 round3 Job69f17f49는 빈 판 INITIAL 성공 후 첫 전달판 개방 실제50.3mm가 과거 상한50mm에 걸려 HOLD였다.
  새 폭 설정은 모의 검증만 완료됐으며 새 인계 실물 성공·실제 연속 결착·별도 FINAL 성공은 아니다.
- DB/웹 재시도는 물리 동작을 반복하지 않는다. 계정·키·DSN·로컬 환경은 Git에 넣지 않는다.

## 6. 최종 ABCD 통합 설계와 단계별 완료 기준

1. **계약/교시 목록**: 빨강 방향·좌표계 표, grasp capability 행렬, 지지/하부 도움 모델을 확정한다.
2. **무장치 계산**: 1/2/3점축×목표0/90×층별 중심/강체 변환·좌표 부호·비누적과 불가 조합 HOLD를 검증한다.
3. **교시**: 공급 사전 정렬/닫힘→운반→조립 접근/착지→개방→가압→이탈의 대응 자세를 조합별로 채운다.
   사람이 현장 조건을 확인한 단발만 안내하며 자동 연속 이동/재시도는 교시 수집에 넣지 않는다.
4. **D 단발**: 검증된 각 grasp/방향에서 파지·끼우기·해제·가압·수직 상승·HOME 근거를 확인한다.
   충분한 근거 뒤 I/O/P/U를 자동 상태 전이로 바꾸고, 실패 시 보류/정지하며 자동 복구하지 않는다.
5. **C/A 연결**: 승인된 Design에서 로봇 단독 capability로 전체 순서·매 Step 모션을 만들고 실제 교시/config에 바인딩한다.
   사람 모드/지원이 필요한 후보는 HOLD/C 별도 수정 승인·재계획으로 처리한다. 도움 필요성을 지워 실행하지 않는다.
6. **B 매 Step**: D 해제/상승/HOME 이후 실제 B 비교. MATCH만 다음 Step, 나머지는 HOLD.
   round3 B 실패 체크박스는 생산 robot-only 모드의 통과 수단으로 쓰지 않는다. 시험용 수동 기록은 실제 B와 분리한다.
7. **변경/종료**: B Current 유지→C 수정 후보 별도 승인→A 남은 순서·모션 재계획→남은 조립→별도 FINAL MATCH→종료 판정.
8. **HMI/DB/웹**: 현재 grasp/축/교시·실행 상태/실제 B 결과·미검증·보류 사유를 표시한다.
   B와 별개인 로봇 동작 완료·저장 완료를 분리하고 사용자별 이력/권한·저장 재시도 무동작을 검증한다.

최종 산출물은 파일별 변경/재사용 표, 교시 행렬과 단계별 현장 명령, 기하·단발·전체 통합 검사 결과,
미검증/불가능 조합과 사유다. 모든 설계를 무조건 성공시킬 수 있다고 약속하지 않는다.
이 브랜치 복사만으로 round4 실행기를 구현/검증 완료한 것으로 표시하지 않는다.

## 새 PC/새 채팅 시작

로컬 round4 경로는 `/home/rokey/협동2/C-2-round4`다. Git 상태·브랜치·커밋과 AGENTS.md,
이 문서, STATUS, round3 service/runbook을 먼저 읽는다. 읽기/무장치 preview부터 시작하고 로봇을 자동 동작시키지 않는다.
현재 PC의 Python/ROS 환경은 기존 C-2-round3를 재사용할 수 있으나 .env는 비공개·미추적이다.
새 checkout의 launcher는 `C2_ROUND3_BASE_ROOT`로 기존 환경/가상환경 위치를 지정할 수 있다.
실행 코드 ROOT는 새 checkout으로 고정하고, source가 바꾼 cwd와 이전 alias 경로를 다시 확인한다.
