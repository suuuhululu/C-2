교육용 공급판 프로파일 — Git 배포용

진입 파일: 이 폴더의 profile.json
Native 시나리오: scenario.json
슬롯별 단일 공급 설정: single-slot/*.json
깊이 기준: depth/*.json / ROI: layout.json

20슬롯 RGB-D 조건부 승인 + 5슬롯 교시 전용. 승인과 전체 실파지 검증은 다릅니다.
실파지 근거: 현재 RGB-D 단일 파지2개/교시 전용 단일 파지2개와 과거 교시 검토 자료.
실측 교시13개와 보간12개를 구별하며 조립판 XY는 비활성입니다.
기존 Z·회전·닫힘 폭·힘·속도를 보존합니다. RGB-D 실패 시 교시로 자동 전환하지 않습니다.
T1 패킷300ms, T2/모델310ms, 시각차50ms. 18개 모델 슬롯의 XY 상한1mm.
B 실제 조립 확인·최종 DB 저장·전체 ABCD 실물 완료를 뜻하지 않습니다.

의존 자료
- evidence/의 JSON26개는 로봇 PC 원본 바이트를 그대로 복사했습니다. SHA256 검증을 유지합니다.
- evidence-index.json은 원래 출처와 복사본 해시, 포함하지 않은 과거 영상/초안 위치를 구별합니다.
- 원본 JSON 안의 /home/... 및 logs/... 문자열은 당시 기록입니다. 실행 시 이 중첩 문자열을 따라 파일을 열지 않습니다.
- 실제 로더가 읽는 source_sha256은 이 폴더 기준 상대경로입니다. 원본 logs/·reports/나 원래 PC 경로가 필요하지 않습니다.
- 원본 영상/Depth 배열/ROS bag은 포함하지 않습니다. 이 배포본은 실행 설정 및 근거 요약이며 원영상 재분석 데이터셋은 아닙니다.
- 장치 식별·IP·ROS 도메인·TCP 설정은 기존 현장 값을 유지했습니다. 다른 장치에 자동 적용하면 안 됩니다.

오프라인 확인 (기존 Python/ROS 환경을 준비한 뒤, 저장소 최상위에서)
python3 robot_control_integration/scripts/organize_supply_profile.py validate \
  --directory robot_control_integration/settings/round3_supply_rgbd_20261015/execution-portable-20261015

Native 미리보기 (로봇·카메라 연결 없음)
cd robot_control_integration
python3 -m scripts.round2_three_step_trial preview \
  --scenario settings/round3_supply_rgbd_20261015/execution-portable-20261015/scenario.json \
  --execution-profile settings/round3_supply_rgbd_20261015/execution-portable-20261015/profile.json

단일 공급 미리보기 (위 native 폴더에서)
python3 scripts/supply_rgbd_single_trial.py preview \
  --config settings/round3_supply_rgbd_20261015/execution-portable-20261015/single-slot/blue_2x3x1_03.json \
  --execution-profile settings/round3_supply_rgbd_20261015/execution-portable-20261015/profile.json

실제 실행 옵션
HMI 고정 T1: --round3-fixed-step --fixed-trial-scenario <scenario.json> --execution-profile <profile.json>
승인 Step 시험 경로는 별도 C/A/B 초기 관측 계약과 검사 대상입니다. 이 파일 준비만으로 실제 후속 B 검사·DB 저장이 연결되지는 않습니다.
단일 공급 run --execute --confirm-slot-ready --confirm-hand-clear는 실제 접근·그리퍼 닫기 후 정지합니다. 자동 상승·결착 없음.
check도 실제 로봇·카메라 조회를 합니다. 제어권 반환·장착/TCP/관측 자세/배치/영상 확인 후 작업자가 실행해야 합니다.
--start-zone home은 현재 시작 구역 선언이며 HOME 이동 명령이 아닙니다.
다른 팀 장치 인계 후 이번 패키징에서는 장치 연결·동작을 하지 않았습니다.

새 데이터로 재생성하는 build는 원본 PC 측정 자료가 필요합니다. validate는 이 배포본만으로 가능합니다.
기존 절대경로 원본 execution-approved-20261015는 현장에 보존하며 Git 배포 대상에서 제외합니다.
