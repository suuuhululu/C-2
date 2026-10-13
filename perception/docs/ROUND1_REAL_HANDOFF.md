# 팀 전체 1차 실물 시험 — B 실제 관측 연결

표본 시험과 별개다. B 진입점은 `perception_mvp.team_connection.connect_real_inspection`이다. D production 파일은 변경하지 않았다. 아래 호출은 **D 담당자가 실제 Controller 함수를 주입해야** 실행된다. 독립 명령만으로 로봇 관측점 이동을 제공하지 않는다.

## 통합 PC의 D 실행 코드에서 호출

ROS2 Jazzy 환경을 source하고 저장소 루트와 `perception`을 PYTHONPATH에 추가한다. 실제 모델·보정 파일을 통합 PC에 준비한다. raw RGB/Depth/aligned Depth 및 각 CameraInfo 토픽이 필요하다.

```python
from pathlib import Path
from perception_mvp.main import read_json
from perception_mvp.hand_cycle import live_hand_components
from perception_mvp.team_connection import connect_real_inspection

root = Path('perception').resolve()
settings = read_json(root / 'perception_mvp/config.yaml')
hand = dict(settings['hand'])
hand['weights'] = str(root / hand['weights'])
detector, gate = live_hand_components('V0', hand)
calibration = read_json(root / 'calibration/assembly_runtime_pitch16_flat0_20261013.json')
connection = connect_real_inspection(
    result_queue.put,
    gate=gate, hand_detector=detector,
    weights=root / 'models/block_v1_six_runs_20261010/blocks_yolo26s_best.pt',
    calibration=calibration, config=settings['geometry'], detector_confidence=.25,
    scene_id=scene_id, output_root=root / 'recordings/team_real',
    confirm_view=confirm_view, is_stopped=is_stopped, robot_pose=robot_pose,
    workflow_valid=workflow_valid, bundle_valid=bundle_valid,
)
```

## D에서 필요한 실제 함수

- `confirm_view(view)`: V0→D1→D3 이동·도착·정지를 확인한 뒤 True. 작업은 B worker에서 호출되므로 Qt/Controller 소유 스레드에 안전하게 위임해야 한다. STOP/취소 시 대기를 풀고 False. 고정 True로 대체 금지.
- `is_stopped(view)`: 해당 View 실제 정지 여부. `robot_pose(view)`: 촬영 시 실제 pose dict.
- `workflow_valid()`, `bundle_valid()`: STOP·장면 변경·요청 무효화 시 False. 안전 확인을 임의 True로 고정하지 않는다.
- `result_queue`: D 소유 스레드에서 처리. `scene_id`: 같은 보드 장면 식별 문자열.

기존 `connection.request({check_id, check_kind, plan_id, step_id})`·`load_plan(...)`·`cancel(check_id)`·`close()` 인터페이스를 사용한다. B가 Current/revision/Expected/Difference를 확정한다. D는 같은 값을 중계한다. STOP은 D가 로봇을 정지시키고 validity를 닫으며 활성 요청을 cancel한다. B cancel은 비상정지 명령이 아니다.

## 실제 순서와 판정

D INITIAL 요청 → V0 정지·손 없음/영상 안정 확인 → RGB-D 1쌍 촬영·분석 → D1/D3 실제 정지 후 각각 1쌍 → B 결과 큐. 이후 C 승인·A 계획의 실제 Plan을 B에 load_plan하고 STEP/FINAL 요청을 전달한다. 사람 조립 완료 엄지척은 D가 처리하며 B에서 새 손 진입·3초 이탈을 다시 요구하지 않는다.

촬영/모델/통신 실패는 ERROR, 유효 관측 근거 부족은 UNOBSERVABLE 또는 INITIAL_STATE_UNAVAILABLE 오류다. Current 미확정·관측 불가를 정상/빈 보드/다음 Step 허가로 취급하지 않는다. D의 대기 정책은 D 담당자가 확인한다. 확인된 아래층 이력은 보존한다.

## 현장 완료 기준·남은 병목

1. INITIAL 실제 카메라 수신·결과 ID 및 큐 수신 확인.
2. STEP·FINAL의 정상/차이/관측 불가와 Current/revision 전달 확인.
3. 수신·추론 중 STOP/취소, 늦은 결과가 상태를 바꾸지 않는지 확인.

현재 저장 영상 좌표·층 확정은 0개로, **전체 정상 시나리오 종료는 보장할 수 없다**. 외곽/높이 정확도 개선은 별도 병목이다. 장치 없이 연결 소프트웨어 검사만 수행했으며 실제 Camera→D·집기·조립 성공으로 보고하지 않는다. 공급판 실제 연결은 별도 담당 작업과 함께 확인해야 한다.
