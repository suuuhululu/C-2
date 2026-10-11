# 오전 B 산출물·결과 보고

2026-10-06. 대상: Perception→Backend 반환 자료와 연결 기준.

| 오전 요구 | 넘기는 자료 |
|---|---|
| 이번 관측과 과거 추적 분리 | observed JSON의 visible_blocks / 별도 diagnostics의 tracked_blocks |
| check 연결과 순번 증가 범위 | Backend 활성 check ID 사용, 예시는 check별 0부터 묶음 시작마다 +1 |
| 좌표·층·영역 경계 | x/y 최소 footprint 모서리, +X 오른쪽/+Y 위, layer 1~4; x/y/width/height/layer 영역 |
| 정상·불일치·빈 영역·판단 불가·전달판 미확인 | fixtures의 다섯 기본 Observed/진단 쌍 |
| 아래층 가림 처리 | lower_layer_only_occluded 보충 사례; 아래층 유지, 이번 목표 OK |
| 순번·지연 사례 | check_change_sequence.json |
| 실행 방법·Backend 확인 절차 | README.md, BACKEND_TEST_GUIDE.md |
| 촬영 조건 | CAPTURE_CONDITIONS.md; 실제 장치 검증 전 조건·미확정 항목 명시 |

## 실제 확인

- normal_match.observed.json의 brick_type이 2x2x1인 것을 확인.
  사용자가 시험했던 2x6x1은 현재 해당 파일에 없으며 파일을 되돌릴 필요가 없었음.
- 이번 작업 후 callback 관련 pytest: **14 passed in 0.03s**, 종료 코드 0.
  JSON과 예시 소스의 일치, 공통 필드·별도 진단, 식별자·순번, 오류 전달을 확인.
- 이것은 합성 자료의 L1 자체 검사임. 실제 Backend Current 채택·비교·보류나 HMI 검사는 미수행.
- 실제 Camera·RGB-D 인식·다중 View·보정·Robot 정지·촬영 성능은 미검증.
- C-2는 읽기만 수행. Robot 이동·외부 메시지·GitHub 게시·dependency 설치 없음.

## 수현님에게 넘길 때

ZIP의 perception_mvp 폴더 전체를 공유합니다. 별도 진단의 위치·시각 상세 필드·추적 피드백은
제안 표시를 유지합니다. 공통 Observed를 실제 callback에 넣고 소비 검사 결과를 받는 단계가 남았습니다.
실제 Backend 통합 완료 또는 장치 검증 완료로 보고하지 않습니다.

## 전달 메시지 초안

수현님, 오전 B 산출물 준비했습니다. 정상 일치·불일치·확인된 빈 영역·가림/품질 부족·
전달판 UNOBSERVABLE의 반환 JSON과 아래층만 가린 OK 보충 사례를 첨부드립니다.

이번 검출과 과거 추적은 분리했고, 순번은 check별 0부터 관측 묶음 시작마다 증가하는
예시 규칙으로 적었습니다. verified_regions 좌표·층·경계, 전달판 별도 반환 위치 제안,
사례별 사전 Current/목표·확인 결과와 촬영 조건도 문서에 포함했습니다.

합성 자료의 로컬 자체 검사는 통과했습니다. 실제 Backend 소비 검사·HMI/장치 통합은
별도 단계입니다. 활성 check_id로 맞춰 Current 채택·비교·보류 처리를 대조 부탁드립니다.
진단·추적·전달판의 상세 연결 위치는 예시를 보고 함께 맞추면 됩니다.
