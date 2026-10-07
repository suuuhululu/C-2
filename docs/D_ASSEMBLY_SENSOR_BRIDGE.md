# 직접 조립 연구: 무이동 조회→Backend 연결

2026-10-07. 기존 현장 `scripts/no_motion_check.py`의 `probe`, `receive_rgbd`,
`save_rgbd`를 재사용한다. 새 ROS/Modbus 조회기를 만들거나 Day4 앱을 실행하지 않는다.

## 연결 범위

`probe` 원문 + `save_rgbd` metadata → `project_no_motion_readings` →
7단계 snapshot → `Backend.on_assembly_sensor_snapshot` → 진단 상태/JSONL.

- 로봇/그리퍼/Camera는 실제 읽기 대상, Backend는 driver 없는 FAKE 진단 인스턴스다.
- 최초 world/target은 기존 연구 Fixture의 **가상 시험 기하**다. 실제 stud 좌표,
  calibration, Current/Expected, Step 완료나 기존 앱 재개 상태로 사용하지 않는다.
- 조회 직전에 attempt/source epoch와 host monotonic 시각을 동결한다.
  원본 query UTC와 Camera 수신 UTC가 획득 창 안에 있어야 한다.
  이것은 PC 수신 창 검사이며 장치의 계측 시각·ROS 시계 동기화 검증은 아니다.
- 과거 파일 변환은 `live=False`가 기본이다. 과거 파일에 새 시각을 붙여 LIVE라고
  표시해도 원본 수신 시각이 창 밖이면 거절한다. 실행 도구는 과거 파일을 조회 입력으로 받지 않는다.
- force ref=0/1 중 하나를 선택한다. 두 순차 샘플을 합치지 않으며 좌표계는 UNKNOWN으로
  남긴다. frames_verified=false, device timestamp 없음이며 접촉 분류는 구현하지 않는다.
- READ + response.success=true + 해당 필드가 있어야 읽힌 값으로 전달한다.
  조회 실패/ACK만 있음/누락은 미확인이다. 중복 service/request는 거절한다.
- RG2 register 267/268의 원시 값을 사용한다. 다른 주소 매핑은 거절하고,
  폭·파지 없음·DRL LAST를 해제/정상 실행 완료로 바꾸지 않는다.
- RGBD CameraInfo 크기·header·encoding·명시된 mm 단위를 보존한다.
  원본 zero fraction을 정확한 zero count나 ROI 품질로 추정하지 않는다.
- 자동 이동·STOP·안전 reset·그리퍼 개폐·설정 변경은 발행하지 않는다.

## 현장 실행

기존 현장 브랜치 `work/suhyun-hmi-backend-robot-db`와 미커밋 파일을 유지한다.
현재 검증된 실행 사본은 다음 폴더에 있고 기존 app/scripts를 덮어쓰지 않았다.

`/home/ms-02/C_2/logs/assembly_sensor_bridge_20261007_c4762d97_v2`

`deployment_v2.json`에 실행 파일의 SHA256을 보존한다. Git에서 제외된 시험 사본이므로
새 clone에는 없다. 다른 PC/버전에 배포할 때 해당 코드와 실제 조회 도구를 다시 확인한다.
검토한 조회 도구 SHA256은
`549ec50c220c6dbf9a43a139358da9c2ac6aa5d650746c3c8d3eca2d62fbb5e9`다.
변경된 reader는 import 전에 거절하며, 새 hash를 자동 채택하지 않는다.

장치 연결과 기존 조회/Camera 노드가 준비된 상태에서 한 번 실행한다.
아래 domain 20과 CycloneDDS 설정은 실행 중인 현장 로봇/Camera 프로세스의 확인값이다.
SSH는 로그인 터미널의 ROS 환경을 자동 상속하지 않는다. 이 현장의 DDS 설정은
loopback `lo`를 사용하므로 domain만 맞추면 노드가 보이지 않을 수 있다.
조회 프로세스에만 같은 환경을 적용하며 장치/네트워크 설정 파일은 변경하지 않는다.
다른 현장에 이 값이나 설정 파일 경로를 기본값으로 적용하지 않는다.
`max-age=2`는 이 읽기 진단의 명시적 허용 시간이며 접촉/안전 제어 임계값이 아니다.
기록 경로는 새 경로여야 한다. 실패 기록을 덮어쓰거나 같은 실패를 반복하지 않는다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/ms-02/cobot2_ws/install/setup.bash
export ROS_DOMAIN_ID=20
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///home/ms-02/.config/cyclonedds/cyclonedds.xml
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
cd /home/ms-02/C_2/logs/assembly_sensor_bridge_20261007_c4762d97_v2
python3 -m scripts.assembly_sensor_bridge --live-read \
  --reader /home/ms-02/C_2/scripts/no_motion_check.py \
  --reader-sha256 549ec50c220c6dbf9a43a139358da9c2ac6aa5d650746c3c8d3eca2d62fbb5e9 \
  --config /home/ms-02/C_2/interfaces/robot_trial.json \
  --fixture interfaces/fixtures/assembly_evidence.json \
  --out live_03 --expected-domain 20 --max-age 2 --force-ref 0
```

`--live-read` 없이 실행하면 안내만 출력하며 ROS/reader를 import하거나 조회하지 않는다.
장치/노드 실행, 네트워크 재설정, E-stop/오류 해제는 이 도구가 수행하지 않는다.

## 기록과 완료 기준

`feedback.json`, Camera 원본/사진(수신 성공 시), `projection.json`,
`backend_reply.json`, `backend_state.json`, `events/`, `result.json`을 보존한다.
Camera 실패 시 `camera_error.json`을 남기고 다른 읽기 값의 차단 근거를 유지한다.
`CONNECTED_READ_ONLY`와 종료 0은 필요한 조회/metadata가 Backend에 연결됐다는 뜻이다.
SAFE_STOP이어도 읽기 연결 자체는 성공할 수 있다. 결착이나 물리 안전 성공은 아니다.
PARTIAL_READS_OR_INPUT_REJECTED/FAILED는 종료 1이며 원인과 입력을 보존한다.

첫 실제 시험은 이전 사본의 `live_01`에 보존했다. Robot 조회 8개 SERVICE_UNAVAILABLE,
RG2 연결 실패, RGBD timeout이었다. 획득 창 약 39.4초가 age=2초를 초과해 STALE_EVIDENCE로
거절했고 HOLD/SAFETY_UNKNOWN, 이동/개폐 명령 0회였다. 유선 enp3s0는 DOWN이며
RG2 주소 192.168.1.1 경로가 Wi-Fi로 나갔다. 이는 최초 시험 당시 상태다.
이 실패는 정식 5장면 시험이나 정상 무이동 장치 연결 통과로 표시하지 않는다.

가장 최근 코드의 로컬 관련 검사 563개, 현장 사본 연구 검사 375개,
기존 조회 도구 검사 6개가 통과했다. 최신 사본에는 수신 UTC 창 검사를 보강했고
환경 변화 없이 같은 실패를 반복하지 않았다.

## 장치 준비 후 SSH 무이동 시험 결과

사용자가 로봇/Camera를 켠 뒤 최신 사본의 `live_02`를 실행했다.
로봇 주소 192.168.1.100과 RG2 주소 192.168.1.1의 유선 연결 환경에서,
실행 중인 노드의 domain/RMW/DDS 설정을 조회 프로세스에 맞춰 확인했다.
`/camera/rgbd` publisher 1개와 로봇 서비스가 확인됐다.

- 2026-10-07 15:37:19~20 KST: `CONNECTED_READ_ONLY`, 종료 **0**.
- 로봇 서비스 8개 READ/성공, 힘·모멘트 6축 수신. 좌표계/부하 보정은 미검증이다.
- RG2 raw status=0, width=621(62.1mm). 해제 완료 증거나 이동 허용으로 해석하지 않는다.
- RGB/Depth: 1280×720, rgb8/16UC1, 동일 header stamp/frame, metadata 사용 가능.
- 획득 창 약 **0.430초 < age 2초**, Backend accepted=true, committed=false.
- Backend **HOLD/SAFETY_UNKNOWN**, 접촉/비전 UNKNOWN, 물리 완료 false,
  이동/개폐 명령 **0회**. Backend/기하는 가상 진단 문맥이다.

원문·사진·Depth·projection·Backend/JSONL 결과는 현장 `live_02`와 로컬
`logs/assembly_attempt/stage8_28a736d4/live_02`에 보존했다.
이번 결과는 실제 센서 조회→진단 Backend 연결 통과이며,
첫 결착 목표·안전 허용·접촉 제어·블록 인식/좌표 보정은 아직 미검증이다.
다음 개발은 제한 목표 비전이며, 실제 이동은 별도 조건 검증 뒤 수행한다.
