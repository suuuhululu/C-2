# 조립판 실제 저장 영상 재생 — 2026-10-13

## 최신 후속 — 평면 기반 표면 재수집

같은 높이의 수평band만 사용하던 방식을 관측된body 평면에 맞춘 residual band로 재수집하도록 수정했다. 최대3회이며 최소점수50/허용기울기10도/band±0.75mm/joint지지25%/외곽55%/층±2.5mm는 유지한다. 몸체와스터드는 동일XY에서 약4mm 간격을 유지해야 하며 서로 기울기가 다른patch의 높이중앙값 차이만으로 통과시키지 않는다.

- 같은6장/14검출에서 표면 분리 통과3→4, 구분보류11→10, 외곽보류3→4이며 좌표·층확정은여전히0이다.
- 외곽내부지지 V0 1층기록33.8%, D1 2층기록47.1%, V0 3층기록41.4%로55% 미달이다. 새로 분리된D1 4층기록은4점 외곽후보가없다. 영상/폴더명의층을GT로자동채택하지않았다.
- 최신결과는 recordings/assembly_replay_20261013_parallel_surface_refinement/report.json 및실제PNG다. plane_refinement는 동일XY간격검사추가전의중간결과로보존하며 최신결과와구분한다.
- B검사365 passed,1 skipped,종료0. 허용범위내기울어진쌍의전체표면재수집/10도초과거부/서로비평행한표면거부를추가검증했다. 실제외곽성공·전체판정성공으로보고하지않는다.

## 후속 수정·동일6장 재시험

몸체/스터드 분리 뒤 몸체만25%를 요구하던 검사를 확인된 몸체+스터드 쌍의 윗면 지지25%로 수정했다. body/stud 각각의 최소점수·수평성·4mm 간격은 유지하고 높이 계산에는 body만 사용한다. RGB 외곽 증거에도 쌍의 윗면을 사용하되 역투영은 body 높이로 수행한다. 숫자 임계값을 낮춰 통과시키지 않았다.

- 변경 전14개 검출 중 표면 분리 통과1개/구분 실패13개, 좌표·층 확정0개.
- 변경 후 표면 분리 통과3개/구분 실패11개, 좌표·층 확정0개. 통과3개는 모두RGB 외곽 확인에서 보류됐다.
- 외곽 후보의 내부 표면 지지 최댓값은 V0 1층 기록32.1%, D1 2층 기록44.9%, V0 3층 기록41.2%로 현재55% 조건을 충족하지 못했다. 이는 해당 후보의 내부 표면 증거 부족이며 이미지가 없거나Depth 전체가0이라는 뜻이 아니다. 이55%를 임의로 낮추지 않았다.
- surface_diagnostics에 표면 점수/쌍의 지지 비율/plane·간격 실패 횟수 및 외곽 단계별 보류 횟수를 기록한다. 각 level/contour의 거부 횟수는 물리 블록 개수가 아니다.
- 최신 원본 재생/실제 추론 결과는 recordings/assembly_replay_20261013_outline_diagnostics/report.json 및 View별PNG에 보존했다. 중간 joint_top_support 결과와 최초 body_stud_trial도 덮어쓰지 않았다.
- 회귀340 passed,1 skipped, 종료0. 신뢰성 향상/실기 전체 판정 성공률의 GT 검증이 아니다. 정상 좌표·층이 나온 것으로 보고하지 않는다.

## 결과

실제 ROS RGB-D6장(V0/D1/D3 각2장)에 blocks_yolo26s_best.pt와 현재 integrated_view 설정을 적용했다. 새 촬영/Robot/D 요청은 실행하지 않았다. 모델 실행과 파일 처리는 종료0이지만 판정 성공이 아니다.

- 검출14개 모두 yellow_2x2/노랑으로 출력됐으나 GT 정확도 검증은 아니다.
- 좌표/층 확정0개. body_stud_surfaces_unverified13개, rgb_top_outline_unverified1개.
- 출력은 recordings/assembly_replay_20261013_body_stud_trial/report.json과00~05 View별 실제 분석 PNG다. 원본 metadata의 pose/check ID를 임의 보충하지 않았으며 D 결과/verified_regions를 생성하지 않았다.

## 입력

- block_depth_check/scene_01_yellow_2x2_layer_01/V0/20261007T094351691156Z
- block_depth_check/scene_02_yellow_2x2_layer_02/D1/20261007T105733133222Z
- block_depth_check/scene_02_yellow_2x2_layer_02/D3/20261007T105810419609Z
- block_depth_check/scene_03_yellow_2x2_layer_03/V0/20261007T110344124429Z
- block_depth_check/scene_04_yellow_2x2_layer_04_repeat/D1/20261007T111714128286Z
- block_depth_check/scene_04_yellow_2x2_layer_04_repeat/D3/20261007T111756071963Z

파일/폴더명의 층 기록을 새 보드 높이 기준의 GT로 자동 채택하지 않는다. 당시 실제 로봇 자세와 현재 보정의 반복성은 별도 확인해야 한다.

## 확인된 병목

V0 첫 영상에서 mask3004픽셀 중 nonzero Depth2984픽셀이 존재한다. 그러나4mm 표면 쌍 후보에서 최대 body band support는633픽셀(유효Depth의21.2%)로 현재25% 조건을 충족하지 못했다. 따라서 이 영상의 주요 보류는 단순 Depth0 부족이 아니라 표면 구분/지지 조건이다. 값은 원본 mask/실제 Depth를 별도 분석해 확인했다.

V0 세 번째 영상은 몸체/스터드 분리를 통과했으나 rgb_top_outline_unverified에서 보류됐다. 모든 View의 실패를 동일한 원인으로 단정하지 않는다.

## 다음 검증

시험 조건을 낮춰 정상 결과를 만드는 대신, 보정 자세가 맞는 현재 실물에서 빈 보드와1층을 우선 촬영해 보드 기준면/몸체·스터드 표면 분포/외곽 근거를 확인한다. 그 결과로 표면 추출 개선을 결정해야 한다. 현재 BODY_TOP_PLUS_STUD 구현의 실물 성능은 미완료다.

## 재생 실행

저장소 루트에서 다음 명령을 사용한다. output은 기존 폴더를 덮어쓰지 않으므로 실행마다 새 경로를 사용한다. --recording을 반복하면 여러 입력을 처리한다.

```bash
PYTHONPATH=.:perception python3 -m perception_mvp.assembly_replay \
  --weights perception/models/block_v1_six_runs_20261010/blocks_yolo26s_best.pt \
  --calibration-root perception/recordings \
  --recording perception/recordings/block_depth_check/scene_01_yellow_2x2_layer_01/V0/20261007T094351691156Z \
  --output perception/recordings/assembly_replay_new_run
```

실제 모델 결과의 reason과 전체 성공/실패를 구분한다. 재생 함수의 단위 검사는 모델/영상 처리를 대체하므로 실물 판정 증거가 아니다.
