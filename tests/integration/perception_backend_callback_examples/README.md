# Perception → Backend callback 검토용 예시

> 2026-10-07 적용: [최종 MVP](../../../docs/10_FINAL_MVP.md). 아래는 기존 Day4 Observed callback의 합성 예시입니다. 직접 결착·지원 응답·최종 완성상태의 생산 계약/성능 검증 자료가 아닙니다. 기존 check/seq와 OK/UNOBSERVABLE 의미를 유지하며 새 VerificationResult 필드는 별도 합의합니다.

Backend에 직접 입력할 JSON은 `fixtures/`에 있습니다.
사례별 사전 Current·목표·확인 결과와 로컬 실행 안내는
[BACKEND_TEST_GUIDE.md](BACKEND_TEST_GUIDE.md)를 참고하세요.
예시 check_id는 실제 소비 검사 시 Backend가 발급한 활성 ID로 교체해야 합니다.

촬영 조건·미정 장치 연결은 [CAPTURE_CONDITIONS.md](CAPTURE_CONDITIONS.md)를 확인하세요.

2026-10-06 PR #6의 C-2 공통 계약과 최신 팀장 답변에 맞춘 합성 데이터입니다.
Observed 여섯 필드는 공통 문서에 맞췄으며 별도 진단 envelope는 제안입니다.
실제 사진·모델·카메라 결과나 실제 Backend 소비 검증 증거는 아닙니다.

## 다섯 사례

| 사례 | Vision callback 내용 | Backend 확인 포인트 |
|---|---|---|
| normal_match | OK + 확인한 노랑 2×2 블록과 확인 영역 | 별도 Expected와 비교하면 일치 |
| mismatch | OK + 목표와 다른 파랑 블록도 그대로 반환 | OK는 판별 가능, Backend 비교 결과는 불일치 |
| verified_empty | OK + 목표 영역은 확인했고 visible_blocks는 없음 | 완료 확인 시 목표 미배치 차이, 미수신·정상 대기와 구분 |
| occlusion_or_low_quality | UNOBSERVABLE + 이번 목표의 가림/Depth 부족 사유 | 기존 기록 유지, 완료/다음 전달 보류 판단 |
| delivery_unobservable | 조립판 OK, 별도 전달판 UNOBSERVABLE + reason | 조립판 판단과 독립, 다음 전달 보류 판단 |

가림 범주의 보충 사례 `lower_layer_only_occluded`도 제공합니다.
이번 2층 목표는 읽혀 OK이며 이전 1층만 가립니다. 아래층 가림만으로 진행을 막지 않습니다.
총 다섯 기본 사례 + 한 보충 사례이며 각각 독립 시험입니다. 순차 촬영 여섯 건이라는 뜻은 아닙니다.

Expected와 사례 설명은 `backend_test_context`에 따로 둡니다.
callback에는 `vision_result`의 **check_id, observation_seq, status, visible_blocks,
verified_regions, reason**만 전달합니다. View·시각·추적·품질·전달판 정보는
별도의 `vision_diagnostics`에 두며, 이 진단 자료의 소비 연결은 합의 전 제안입니다.
Observed callback에 진단 필드를 추가하지 않습니다. 전달판 검토 시에는 별도 자료도 함께 확인해야 합니다.
Vision에서 Expected와 비교해 관측을 제거하지 않습니다.
Current 채택·누적, 닫힌 check_id 결과 처리, 완료·다음 전달 판단은 Backend 책임입니다.
이 예시는 Backend 동작이나 추적 알고리즘을 대신 구현하지 않습니다.

## 예시용 임시 표현 — 합의 필요

모든 사례 바깥의 `example_only: true`, `temporary_expressions`에 아래 사항을 표시했습니다.
이는 검토용 표시이며 callback의 확정 필드로 추가한 것이 아닙니다.

| 항목 | 예시에 사용한 임시 표현 |
|---|---|
| 관측 시각 | observed_at, UTC ISO 형식, 관측 묶음 시작 시각. 진단 전용이며 최신 판정에 쓰지 않음 |
| 추적 정보 | tracked_blocks, placement/basis/reason 구조 |
| 품질·진단·View·보정 | vision_diagnostics 및 quality/unverified_regions/view_ids/calibration_id의 구조 |
| 전달판 구조 | delivery_board라는 필드명은 임시. EMPTY/OCCUPIED/UNOBSERVABLE 상태 의미는 합의 내용 |
| 순번 예시 | 이번 예시는 check별 0부터 시작, 관측 묶음 시작마다 +1. 공통 계약의 필수 카운터 정책은 아님 |

수치·배치·ID·시각은 전부 합성값입니다. 실제 기하 계약이나 검증 점수로 사용하면 안 됩니다.
검토용 묶음에서 임시 표시를 유지한 채 팀장에게 전달해야 합니다.

## 공통 계약에 맞춘 표현

brick_type은 2x2x1/2x3x1, color는 yellow/blue입니다.
x/y는 0~23 최소 footprint 모서리, layer는 1~4입니다. +X 오른쪽, +Y 위이며
6점 0도는 X폭 2/Y길이 3, 90도는 X폭 3/Y길이 2, 4점은 대표각 0입니다.
이는 임의의 장축 각도 규약으로 바꾸지 않습니다.

`verified_regions`는 x/y/width/height/layer로 표현하는 실제 점유 확인 영역입니다.
영역 내부에는 블록과 빈 부분이 함께 있을 수 있으므로 빈 영역 목록이라는 뜻이 아닙니다.
카메라 시야 전체를 자동으로 확인 영역에 넣지 않습니다. 경계에 걸친 실제 블록도 반환해야 합니다.
블록 목록이 비었다고 보드 전체나 가려진 아래층을 빈 것으로 판단하면 안 됩니다.
가림 사례의 아래층 footprint는 확인 영역에 넣지 않고 별도 vision_diagnostics에 기록했습니다.
사선 View·가림을 실제로 검사해 해당 영역을 만든 코드는 아직 없습니다.

## 실행 및 callback 사용

작업 폴더에서:

```bash
python3 perception_mvp/callback_examples.py
python3 -m pytest -q perception_mvp/tests/test_callback_examples.py
```

첫 명령은 다섯 기본 사례, 아래층 가림 보충 사례, check 변경 순번 설명 자료를 출력합니다.
callback은 다음처럼 연결할 수 있습니다.
perception_mvp 폴더에서 실행하는 Python 예시입니다.

```python
from callback_examples import examples, deliver_example

def local_backend_callback(observed):
    print(observed)

# Backend에서 받은 값과 관측 묶음 시작 시 정한 순번을 넘깁니다.
case = examples(check_id="backend-issued-check", observation_seq=0)[0]
deliver_example(case, local_backend_callback)
```

예시 코드가 check_id를 발급하거나 수신 순서로 observation_seq를 바꾸지 않습니다.
도착 순서가 2 → 1이어도 원래 순번을 유지합니다. 최신 결과 선택은 구현하지 않았습니다.
callback 예외는 호출자에게 그대로 전달하며 성공으로 바꾸거나 자동 재시도하지 않습니다.
표준 라이브러리로 동작하며 pytest는 테스트에만 사용합니다. 신규 dependency 설치 없음.

## check 변경과 순번 예시 규칙

이번 제출 예시는 **check별 초기화**를 선택합니다. Vision 실행 전체에 걸쳐 계속 증가하는 방식이 아닙니다.
새 고유 check의 첫 관측 묶음은 0, 같은 check의 다음 묶음은 1입니다.
묶음 시작 시 check_id/순번을 고정하며 여러 View를 한 Observed로 반환하면 모두 그 묶음의 순번입니다.
실제 촬영 연결부의 카운터는 아직 구현하지 않았고 examples 함수는 외부에서 고정한 값을 받습니다.

| 묶음 시작 순서 | check_id | observation_seq |
|---|---|---|
| 1 | check-A | 0 |
| 2 | check-A | 1 |
| 3, A 닫고 B 열기 | check-B | 0 |
| 4 | check-B | 1 |

sequence_examples는 결과가 A/1 → B/0 → A/0 → B/1 순으로 도착하는 예를 제공합니다.
늦은 A/0도 A/0을 유지합니다. Backend가 닫힌 A 결과를 진행에 사용하지 않습니다.
동일 활성 check의 중복/역순 처리 역시 Backend 책임입니다. 이 예시는 필터를 구현하지 않습니다.
관측 시각은 진단·로그에만 쓰고 최신 결과 판정은 check_id와 observation_seq 기준을 유지합니다.
시각의 정확한 필드명·형식과 별도 진단 전달 위치는 연결부에서 합의할 제안입니다.

## 검증 범위

검토 예시의 필드 분리·ID 보존·빈 영역 범위·가림 정보·순서 역전·callback 오류를 시험합니다.
문서 기준 필드·값·영역 형식을 테스트했으며 실제 Backend의 validate_observed/adopt_observation
소비 검사·닫힌 check 처리·Current 채택은 미검증입니다.
실제 RGB-D 인식, 영역 검증, 추적, 촬영 성능도 이 예시 시험 범위 밖입니다.
