# 1차 통합 — 정확도 개선과 분리한 B 연결 시험

실제 좌표·층 인식 개선은 후속 작업으로 분리한다. 이번 시험은 **합성 표본을 실제 B 판정·비동기 연결 코드로 처리**하는 시험이다. Robot·Camera를 실행하지 않으며 물리 성공 증거가 아니다.

## 먼저 실행

저장소 루트에서 실행한다. 출력 파일은 기존 결과와 다른 이름을 사용한다.

```bash
PYTHONPATH=.:perception python3 -m perception_mvp.replay_inspection \
  --sample perception/samples/inspection_replay/sample.json \
  --output /tmp/b_round1_sample_result.json
PYTHONPATH=.:perception python3 -m pytest \
  perception/perception_mvp/tests/test_replay_inspection.py \
  perception/perception_mvp/tests/test_team_connection.py \
  perception/perception_mvp/tests/test_round1_inspection.py -q
```

재생 예상: `SYNTHETIC replay: 7 checks PASS`. 정상 INITIAL/STEP/FINAL, 차이·관측 불가·오류를 확인한다. 테스트의 취소·늦은 결과 검사는 소프트웨어 검사이며 실제 Controller STOP 검증은 아니다.

## D 담당자에게 전달할 주입 방법

```python
import json
from pathlib import Path
from perception_mvp.replay_inspection import make_sample_observer
from perception_mvp.team_connection import connect_inspection

sample = json.loads(Path('perception/samples/inspection_replay/sample.json').read_text())
observer = make_sample_observer(sample, scenario_name='normal-and-failure')
connection = connect_inspection(
    result_queue.put,  # D 소유 스레드에서 큐를 읽고 처리
    observe=observer,
    geometry_reference=sample['geometry_reference'],
)
```

`result_queue`는 D가 준비한 큐이다. 표본의 해당 scenario `actions` 순서대로 `request`를 `connection.request()`에 전달하고, `load_plan`은 기존 `connection.load_plan()`에 전달한다. 요청별 결과를 받은 뒤 다음 요청을 보낸다. 검사 ID는 표본과 동일해야 하며 없는 ID는 ERROR다. 종료 시 `connection.close()`, 요청 취소는 `connection.cancel(check_id)`를 호출한다. cancel은 로봇 정지 증명이 아니다.

표본 관측 함수는 **자동 fallback으로 쓰지 않는다**. 실제 시험은 실제 관측 함수로 교체해야 한다. 좌표·층 근거가 부족하면 UNOBSERVABLE/초기 상태 미확인 오류를 유지하고 다음 조립 허가로 취급하지 않는다. D의 대기·STOP·결과 큐 처리와 실제 함수 주입은 D 담당자 확인 사항이며 이번 B 변경으로 구현됐다고 주장하지 않는다.

## 이번 시험에서 미루는 항목

실제 영상 외곽 추출·좌표/층 정확도, 보정 실측, Camera→D·공급판 집기·전체 실물 MVP. 표본 시험 통과와 별도로 기록한다. D production 코드·실측 기준은 변경하지 않는다.
