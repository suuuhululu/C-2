# Backend 소비 검사 안내

이 자료는 합성 입력입니다. 수현님의 실제 Backend에 넣어 Current 채택·비교·보류를
검사하는 데 사용합니다. 자체 pytest 통과가 Backend 처리·HMI 통합 통과라는 뜻은 아닙니다.

## 전달 파일

- fixtures/*.observed.json: 공통 여섯 필드만 있는 Backend 입력.
- fixtures/*.diagnostics.json: 임시 표현 표시와 proposed_diagnostics가 있는 별도 검토 자료.
  전체 wrapper를 Observed callback에 넣지 않습니다. 진단 소비 연결은 수현님과 맞춥니다.
- fixtures/check_change_sequence.json: 순번 시작/도착 순서 설명 자료. 단일 Observed가 아닙니다.
- callback_examples.py: 같은 자료를 만드는 예시 및 callback 전달 함수.
- tests/test_callback_examples.py: JSON 자료와 코드 예시의 일치·형식·로컬 전달 검사.

## 실제 Backend에서 입력하는 절차

1. 각 사례를 독립적으로 시작합니다. 아래의 Current·목표를 Backend 시험 환경에 준비합니다.
   Robot 이동은 필요하지 않습니다. HMI 표시 검사는 실제 연결돼 있을 때만 수행합니다.
2. Backend가 해당 목표 after의 활성 완료 확인 check를 엽니다.
3. observed.json의 설명용 check_id를 Backend가 발급한 실제 ID로 교체합니다.
   진단 자료의 proposed_diagnostics.check_id도 같은 값으로 맞춥니다.
4. observation_seq는 첫 묶음 0부터 시작합니다. 이미 같은 check에 결과를 입력했다면
   그 check의 마지막 처리 순번보다 큰 값을 사용하고 진단 순번도 함께 맞춥니다.
5. Observed 여섯 필드를 실제 Backend 수신 함수로 전달합니다. 함수명·호출 방식은
   수현님 연결부를 사용합니다. 이 폴더에 임의 ROS/HTTP/HMI 전송 경로는 없습니다.
6. 별도 진단의 전달판 상태 등은 수현님이 연결부에서 맞춘 경로로 입력합니다.
   Observed만 넣으면 전달판 UNOBSERVABLE의 소비 검사를 수행한 것이 아닙니다.
7. 실제 Current·비교·완료·다음 전달 보류·표시 사유를 확인하고 결과를 기록합니다.

Expected와 이전 Current는 시험 사전 조건이며 Vision이 반환하는 필드가 아닙니다.
아래 배치는 모두 x=4, y=6, orientation_deg=0이고 brick_type=2x2x1입니다.
실제 카메라·보정·검출 성능을 주장하지 않습니다.

## 사례별 사전 조건과 확인 결과

| JSON 이름 | 이전 Current / 현재 목표 after | Backend에서 확인할 결과 |
|---|---|---|
| normal_match | 빈 Current / 노랑 1층 | 노랑 실제 배치 채택, 목표 MATCH·완료 처리 확인. 다음 전달 허가는 별도 gate에 따름 |
| mismatch | 빈 Current / 노랑 1층 | 파랑 실제 배치 채택, MISMATCH·다음 전달 보류. Expected로 관측을 덮어쓰지 않음 |
| verified_empty | 빈 Current / 노랑 1층 | 목표 footprint를 확인했지만 비어 있음. OK인 미배치 차이이며 WAITING/UNOBSERVABLE로 숨기지 않음 |
| occlusion_or_low_quality | 채택된 노랑 1층 / 파랑 2층 | 이번 목표 Depth 부족으로 UNOBSERVABLE. 아래층 Current 유지, 완료·다음 전달 보류, 사유 확인 |
| delivery_unobservable | 빈 Current / 노랑 1층 | 조립판은 OK·MATCH. 전달판 UNOBSERVABLE은 별도 입력 후 다음 전달 보류 확인. 조립판을 실패로 바꾸지 않음 |
| lower_layer_only_occluded | 채택된 노랑 1층 / 파랑 2층 | 2층은 OK·판별 가능, 아래층 기록 유지. 아래층 가림만으로 전체 보류하지 않음 |

normal_match/mismatch는 합성으로 1층 전체를 확인했다고 선언하므로 표에 지정한 빈
Current를 사용합니다. 임의의 기존 배치가 있는 공정에 그대로 주입하지 않습니다.
verified_empty는 (4,6)의 2×2 영역, 1층만 확인합니다. 다른 영역·층을 비움으로 해석하지 않습니다.
기존 노랑 1층을 Current에 둔 별도 제거 검사도 가능하지만, 기본 사례의 초기 조건과 구분해 기록합니다.

## 순번·다중 View·늦은 결과

예시 정책은 check A의 0→1, 새 check B의 0→1입니다. check마다 초기화합니다.
여러 View를 하나의 묶음으로 반환하면 묶음 시작 check/seq를 공유합니다.
View 목록은 예시 메타이며 다섯 View 촬영을 공통 필수로 강제하지 않습니다.

순번 자료의 bundles_in_start_order에는 A/0, A/1, B/0, B/1이 있습니다.
arrival_order=[1,2,0,3]은 A/1→B/0→A/0→B/1 도착을 뜻합니다.
A/1 입력 후 A를 닫고 B를 열어 B/0을 입력합니다. 늦은 A/0은 원래 ID를 유지하며
Backend 진행에 사용되지 않아야 합니다. 같은 활성 check의 역순·중복 검사도 수현님 쪽에서 확인합니다.
실제 발급 ID로 A/B를 치환할 때 Observed·진단을 함께 맞춥니다.
observed_at은 진단 전용입니다. 최신 선택 기준은 check_id와 observation_seq입니다.

## 로컬 검사

ZIP을 풀고 perception_backend_callback_examples/ 폴더에서:

```bash
python3 perception_mvp/callback_examples.py
python3 -m pytest -q perception_mvp/tests/test_callback_examples.py
```
