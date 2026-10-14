# 잡힌 블록 모서리 ↔ stud 격자선 상대각도 시험

첫 실행은 노랑2×2 슬롯1/span2 파지 → 잡은 상태로 기존194.733mm 경유 경로 이동 → 조립판(11,11)상공 정지 → OpenCV 팝업이다. 원가압/해제/하강끼우기/자동회전은 실행하지 않는다. 실제위치선검사·STOP·Grip2·힘35N·단독잠금을 재사용한다.

```bash
python3 robot_control_integration/scripts/held_corner_stud_trial.py --execute --start-zone supply --confirm-hand-clear
```

공급판 관측점에서 시작하며 빈그리퍼60mm개방을확인한다. 출발이조립판이면 --start-zone assembly. 이미잡고(11,11)상공에있는경우에만 --observe-only를추가한다. 그경우파지/운반을하지않고현재정지Grip2를확인한다.

팝업:
- B: 그리퍼에 잡힌 노랑 블록만 드래그 선택. 선택후 Enter. 기존조립판노랑블록은포함하지않는다.
- S: 목표근처의 보이는 stud 격자영역을 드래그 선택. 각방향으로3개이상stud가보이는작은ROI권장. 선택후Enter.
- A: 비교할격자축전환. 기본은모서리와가까운영상축.
- SPACE: 원영상/overlay/검출/각도/로봇표본/가능한pairedDepth저장.
- ESC/창닫기/Ctrl+C: STOP요청. 블록은그리퍼에잡힌상태유지한다.

노랑선은블록모서리후보,청록선은선택stud축,파란선은다른stud축,자홍점은원후보다. Angle difference는 stud선각도−블록모서리각도이며화면상의수평을강요하지않는다. 각도0은회전방향평행후보로만기록하며XY일치/목표cell/실제기울기/체결성공이아니다. 같은stud의중복원을근접병합하고가까운이웃만연결해대각선방향혼합을줄인다. 큰perspective/가림/모서리오인/잘못된원격자는UNKNOWN또는오차원인이므로첫시험에서원영상과검출선검토가필요하다.

목표층 근접 시험: --approach-cycle --target-layer N으로 기존 해당층 배치 TCP보다20mm 위에서 관측한다. 1층TCP35.516mm,2층53.636mm. 1층은 기존블록을치워대상비어있음을확인한경우에만--confirm-target-empty를추가한다. --observe-only와함께사용하면현재파지상태재사용해근접하강/관측을한다. B/S재선택후R은0.5deg시험회전,반응이확인되면후속R마다최대0.5deg보정한다(총2deg제한). U는원상공높이수직상승하고종료한다. ESC는STOP/현위치유지로상승하지않는다. 아직user실물검증전이며XY자동보정/가압/해제없다.

가상격자 시험: --virtual-grid로 실제 원검출을 사용하지 않고기존조립판calibration을현재카메라영상에투영한다. 첫시험은 `python3 robot_control_integration/scripts/held_corner_stud_trial.py --execute --observe-only --virtual-grid --target-layer 1 --confirm-hand-clear`이다. 현재높이를그대로유지한다. 청록색은아래stud격자,노란색은목표층+20mmhover몸체윤곽,자홍색은해당층체결상태몸체윤곽이다. 현재보정은PROVISIONAL이며원영상offlinepreview에서어긋남확인,실제보정으로자동채택하지않는다. E를누르고실제로보이는몸체윗면모서리두끝을클릭하면픽셀각도비교후보가표시된다. A는비교축전환,SPACE는모든원근거저장. 가상격자모드R실제회전은차단하며U상승(approachcycle사용시)/ESC종료를유지한다.

방향만회전시험: 현재(11,11)1층목표+20mm접근위치라면 `python3 robot_control_integration/scripts/held_corner_stud_trial.py --execute --observe-only --virtual-grid --yaw-test --target-layer 1 --confirm-hand-clear`. E로윗면모서리두끝선택→실제stud행/열과가상선평행을눈으로확인→G기록→R최초0.5deg반응시험→결과안정후R마다최대0.5deg보정→U상공상승종료. XYphase는회전방향검토와구분하며위치투영의독립검증false상태유지. 2deg전체순변화한도/목표각도0.5deg미만에서추가회전없음. 이동성공은조립성공이아니다.

初期誤差시험: 상공194.733mm에서정지/Grip2유지한후 --approach-cycle --initial-yaw-deg1을추가한다. 처음BaseZ+1deg→目標TCP+20mm下降→PopupE/G/R→U상승. --initial-yaw-deg는최대±2deg이며低い접근높이에서직접시작하면拒否한다. INITIAL_YAW_COMPLETED로실제로돌았는지확인한다.

XY+끼우기추가: --xy-seat-test로X/I/O를활성화한다. E→G→R보정후X로교시목표XY를맞춘다(2mm한도,영상XY보정아님). I는角度0.5deg미만/교시XY/目標+20mm에서만2mm/s·1mm단계끼우기를한번시도한다. rawforce10N/기준Fz변화5N/모멘트변화1Nm은낮은시험용STOP값으로재료한도가아니다. 접촉중단이면결착미확인/파지유지,U로상승한다. target높이도달이면실제로결착되었는지눈으로확인한뒤O로개방하고U로상승한다. O입력/명령완료는B Current/최종체결판정이아니다. 자동재시도없다.

HOME独立路径: --start-zone homeは实际关节[0,0,90,0,90,0]を検証し現在ABC維持/上空Zで(11,11)へ直接移動する。失败したbody→place経由は使わず旧経路disableは保持。--go-high-onlyなら上空まで、それ以外では后続试验へ继续。

## 2026-10-14 연속 결착 및 닫힌 패드 윗면 누르기

기존 통합의 반력 중단 누르기(`assembly_native_press.reaction_stop_press` → `assembly_press_trial.press`)를 참고한다. 가압 목표 유지 제어는 아니다.

- X: 교시 XY 보정. I: 6mm/s 단일 연속 결착 하강. 5N 접촉 변화·10N 임시 시험 중단은 제거하고 기존 35N 힘 중단을 유지한다.
- I는 각도 안정/0.5도/한 번만 실행 조건으로 막지 않는다. 화면 각도는 사용자가 먼저 확인한다. 정지·장치 상태·파지·IK/FK 검사와 목표 좌표 검사는 유지한다.
- O: 작업자가 놓기를 확인하는 키. 높이는 진단으로 기록하며, 그리퍼60mm 열기→기존 상공 수직 상승→빈 패드4mm 닫기를 수행한다. 닫힌 폭9.3mm/상태2를 물체 파지로 오인하지 않는다.
- 빈 닫힌 패드를 해당 블록 윗면에 가볍게 수동 접촉시키고 정지 후 AUTO로 전환한다. T: 현재 실제 윗면 접촉 pose 기록→수직10mm 상승. 이전 미검증 raw 기록은 자동 접촉 좌표로 채택하지 않는다.
- P: 기록한 방향/XY 유지, 6mm/s 반력 중단 누르기(35N, 접촉점보다 최대2mm 아래까지 이동 한도)→10mm 위 상승. 최대 이동만 도달하면 가압 완료로 표시하지 않는다. 힘 초과가 남으면 상승도 중단할 수 있다.
- U: 상공 상승 후 종료, ESC: 중단. 가압 중 자동 XY 기울기 탐색은 이번 흐름에 포함되지 않는다. 실제 결착/누르기는 현장 검증 필요.

## 1~4번 연결 시험: 노랑4점 슬롯1 → (11,11)1층

현재 조립판 영역에서 빈 그리퍼60mm로 시작한다. 대상(11,11)1층을 비우고, 슬롯1에 노랑2×2를 채운다.

```bash
python3 robot_control_integration/scripts/held_corner_stud_trial.py --execute --integrated-cycle --start-zone assembly --confirm-target-empty --confirm-hand-clear
```

현재 공급판 영역에 있으면 `--start-zone supply`를 쓴다. HOME에서 집기를 생략하던 기존 observe 흐름과 혼동하지 않도록 이 모드에서는 home을 지정하지 않는다.

공급판 관측/새 OpenCV stud-array 탐지(실패도 기록)/좌표 우선 파지(슬롯1 span2)→기존 held transport→목표보다20mm 위 하강→조립판 팝업.
E/G/R로 모서리 방향을 확인·조정하고 X/I로 교시 XY 및6mm/s 연속 결착한다. O는 놓기 확인 및 **열기→상공 상승→4mm 닫기→저장된 실제 패드 접촉점 위10mm로 접근→35N 반력 중단 누르기→상승→종료**를 함께 실행한다. 이 모드에는 추가 T/P가 필요 없다.

기본 pad reference는 operator-pad-top-current.json의 실측 pose다. 해당 목표의 실제 윗면 접촉점을 기준으로 현재 trial에만 재사용하며, 다른 층/블록으로 확장하지 않는다. 공급판 인식됐더라도 독립 검증된 픽셀→로봇 XY 매핑이 없으면 교시좌표를 유지한다. 조립판 X도 교시 XY다. 가압 중 자동 XY 기울기 제어 및 최종 Vision 조립 판정은 포함되지 않는다.

## 최신: HOME 시작 / 3번째 경유지를 조립판 관측점으로 교체

```bash
python3 robot_control_integration/scripts/held_corner_stud_trial.py --execute --integrated-cycle --start-zone home --confirm-target-empty --confirm-hand-clear
```

홈 관절 [0,0,90,0,90,0]에서 빈 그리퍼로 시작한다. 빈 패드가4mm 명령으로 닫혀 있으면60mm로 열고 진행한다. 물체를 쥔 상태로 시작하지 않는다.

기존 integration_native35/profile.reference.json의 SUPPLY/BODY 경유지는 유지하고 PLACE만 (11,11) 관측 상공 XY로 바꾼다. 파지 후 수평 경유지는 정확히 **공급판 경유지→몸통 우회 경유지→조립판 관측점**, 세 점이며 추가 PLACE 경유지는 없다. 홈→공급판은 교체한 세 점의 역방향과 공급판 카메라 관측점으로 연결한다.

모든 경유점은 기존 move_line_async/movel로 이동한다. movej/movej home 명령은 없다. 수평120mm/s, 상승·하강 및 이번 통합 모드 누르기12mm/s. 공급판 비전 팝업과 조립판 정렬 팝업을 유지한다. E/G/R→X/I→O(놓기/상승/패드닫기/저장점누르기/상승)를 사용한다. 즉시 정지 거절을 대기로 바꾸되 힘35N/장치 오류/파지/TCP/IK-FK 보호는 유지한다. 가압 중 자동 XY 기울기 보정은 아직 없다.

## 최신 보완: 일시적 정지 상태 조회 지연·ROI·현재 조립판 재개

정지 상태의 완결된 조회가0.5초를 넘으면, 정상 장치/힘인 경우 최대5초 동안 새 상태를 다시 읽는다. 오래된 값의 시간을 바꾸거나 동작 중의 지연·힘 초과·장치 오류를 무시하지 않는다. FEEDBACK_REFRESH_WAIT에 원래 조회시간을 기록한다.

개선된 OpenCV ROI는 다른 채팅방 live_compare_supply_20261014/slots.json에서 가져와 supply_sequence_20261014/opencv_stud_layout.json에 저장했다. 실제 슬롯은 종류별 오른쪽부터1~5이므로 instance를6-slot으로 변환한다. 팝업은 CLAHE 스터드 배열 점/배열 중심선/중심점을 표시한다.

HOME 출발 경로에서 불필요한 조립판 우회는 제외한다. 홈에서 수직 상승→BODY→SUPPLY→공급판 관측점이다. 파지 후에는 SUPPLY→BODY→교체된 조립판 관측점, 기존3점 구성이다.

이미 블록을 잡고 조립판 정렬 상공에 정지해 있으면 다음 명령은 파지·이송·접근을 반복하지 않고 팝업부터 재개한다:

```bash
python3 robot_control_integration/scripts/held_corner_stud_trial.py --execute --integrated-cycle --resume-assembly --confirm-target-empty --confirm-hand-clear
```

현재 위치가 실제 정렬 상공인지 검사하며, 하강/파지를 자동 재시도하거나 STOP을 해제하지 않는다.

### 파지 후 공급판 상공에서 중단된 경우

슬롯1 노랑2×2를 잡고 공급판 파지 위치의 이송 상공에 그대로 정지해 있는 경우:

```bash
python3 robot_control_integration/scripts/held_corner_stud_trial.py --execute --integrated-cycle --resume-transfer --confirm-target-empty --confirm-hand-clear
```

그리퍼를 열거나 다시 파지하지 않고 SUPPLY→BODY→조립판 관측 경유점으로 이송, 정렬 팝업과 X/I/O 흐름을 이어간다. 수평 경유는 정지 후 실제 현재 Z를 유지한다. 원래 실패한 물리 명령을 자동 재전송하는 경로는 아니다.

## (17,17) 1층 기울기 보정 실물 시험 — 사용자가 팝업에서 실행

```bash
python3 robot_control_integration/scripts/held_corner_stud_trial.py --execute --integrated-cycle --start-zone home --target-x 17 --target-y 17 --tilt-accuracy-test --confirm-target-empty --confirm-hand-clear
```

홈/빈 그리퍼/슬롯1 노랑4점으로 시작하고(17,17)1층을 비운다. 기존 cad_trial의(11,11) 실측 anchor와 affine 격자 step으로(17,17) TCP=[568.1646,181.0695,15.8815]mm, 접근Z35.8815mm를 계산한다. 이는 새17점 실측 교시가 아니며 계산 후보임을 기록한다. 원래11점 교시 자료를 덮어쓰지 않는다.

- 조립판 팝업 E/G/R로yaw 확인 후 H: 현재 기준 자세 기록. J: Base X/Y 회전벡터 각각+0.5도 명령. XYZ 고정, 무접촉 상공에서만 수행.
- K: 기록한 기준 자세로 복귀 보정. 화면의 Base X/Y 상대각과 TILT_ACCURACY_RESULT의 회전오차를 확인한다. 합성 회전오차≤0.05도·위치오차≤0.1mm이면 TCP_REFERENCE_RETURN_PASS다.
- 이 PASS는 로봇 TCP가 작업자가 선택한 기준 자세로 돌아온 정확도이며, 블록 윗면 절대 수평/조립판 평행성 또는 가압 중 보정의 독립 검증이 아니다. 모서리/힘값만으로 절대 기울기 측정이라고 표시하지 않는다.
- 이후 X→I→O로 결착/놓기/상승/패드닫기를 진행한다.17점의 패드 접촉은11점에서 이동한 계산값뿐이라 자동 눌림에 채택하지 않는다. 실제17점 윗면에 닫힌패드를 수동으로 가볍게 대고 정지/AUTO→T로 기록·10mm 상승한다.
- 빈 패드의 T 이후 상공에서도 H→J→K로 동일 정확도를 비교한 뒤 P로45N 반력 중단 누르기, U로상승/종료한다. 누르는 동안의 기울기 탐색은 활성화하지 않았다.
- 수평120mm/s/상하12mm/s, 합력중단45N. 실제 실물 측정값은 사용자의 해당 키 실행 뒤 journal에 기록되며 아직 실행되지 않았다.

## 같은 XY에서 닫힌 패드 직하강 시험 — 재교시 생략

```bash
python3 robot_control_integration/scripts/held_corner_stud_trial.py --execute --integrated-cycle --start-zone home --target-x 17 --target-y 17 --same-xy-press --confirm-target-empty --confirm-hand-clear
```

홈/빈그리퍼/노랑4점슬롯1/(17,17)1층빈상태에서 실행한다. 조립판 E/G/R→X→I 후 실제 놓기를 확인하여 O. O는놓기직전 실제 XY/방향을 저장하고 열기→40mm이상 수직상승→4mm닫기를 한다. P를누르면 같은XY/방향으로 수직접근→45N 반력중단누르기→상승, U로종료한다. T접촉 재교시는 필요없다.

닫힌패드의접촉높이는 기존실측높이차로 추정하는 현장시험이다. 중심부근교시가정과직하강동작을 검증하며, 자동피치/롤보정이 활성화된것은아니다. --tilt-accuracy-test를 추가하면 결착전 H/J/K 기준복귀시험도 할수있다.
