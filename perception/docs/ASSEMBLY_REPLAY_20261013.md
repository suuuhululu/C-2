> 2026-10-14 참고: 이 문서의 층 허용 오차 ±2.5mm는 당시 시험값입니다. 현재 설정은 ±5mm이고 1층은 6~25mm입니다(`perception_mvp/config.yaml`). 아래 재생 결과는 당시 설정 기준 기록이라 바꾸지 않았습니다.

# 조립판 실제 저장 영상 재생 — 2026-10-13

## RGB 외곽·Depth 높이 근거 분리 적용

사용자 승인으로 외곽 내부 Depth 점유 55% 검사를 공간분포 검사로 대체했다. RGB 네 꼭짓점/면적150/마스크85%/윗면점 포함80%와 기존 높이·크기·각도·좌표 검사는 유지한다. Depth는 최소50점, 외곽 정규화 4구역 각12점 이상, 양축 분포폭 각50% 이상을 요구한다. 실측 검증 전 시험값이다. 한쪽 편중·중앙 작은 patch·한구역 가림·점수 부족은 보류한다. production DIRECT_STUD_TOP도 같은 함수를 적용하며 mask 회전사각형은 분포 좌표계로만 사용하고 빈 영역을 채우지 않는다.

실제6장14검출 재생 종료0: V0 3층 폴더 기록1개가 외곽·크기·좌표 검사를 통과해 grid[9,13], H54.775mm, 가산0mm를 출력했다. 3층 기준59.25mm에서4.475mm 차이로 ±2.5mm 밖이므로 layer=None/height_outside_layer_reference다. 좌표도 GT 미검증이며 정상 Current 확정이 아니다. 나머지 평면11개/Depth 지지2개 보류. 결과 recordings/assembly_replay_20261013_spatial_top/report.json. 보정·층 기준을 결과에 맞춰 임의 변경하지 않는다.

## 외곽 보류 조건 재검토 — 변경 전 확인 필요

converged_top에서 윗면 추출을 통과한 V0 기록은 RGB 네점 후보가 존재하고 마스크85%·윗면점 포함80% 검사를 통과했지만, 후보 내부의 직접 윗면 Depth 비율37.58%가55%보다낮아6개후보가모두보류됐다. RGB사진이없거나네꼭짓점을못찾은사례와구분한다.

DIRECT_STUD_TOP은좁은윗면plane점만사용하지만 외곽검사는그점이전체면적55%를채워야한다. 스터드끝은전체윗면을덮지않으므로 이두검사의의미가맞는지검토가필요하다. 선택된plane이실제로스터드끝인지도현GT없이는단정하지않는다. 단순55%완화가아니라RGB외곽증거와Depth높이증거의분리·공간분포검사로대체하는방향을사용자와확인해야한다. 현재코드/판정조건은유지했다.

## 직접 윗면 평면의 수렴 처리 개선

재수집3회 후 종료하던 직접 윗면 추출을 최대20회 내 점 집합 수렴까지 처리하도록 수정했다. 최소50점·25% 지지·기울기10도·잔차±0.75mm를 유지하고 수렴하지 않은 마지막 결과는 채택하지 않는다. 관련39검사 통과, 실제재생 종료0.

동일6장/14검출 중 V0 3층기록1개가17회에서 윗면 추출을 통과했다. 최종은 외곽검사에서보류. 나머지11개 평면검사·2개Depth지지검사보류, 좌표/층확정0개다. 이는 반복횟수 제한이 일부 추출을 막았다는 증거이지 실물정확도 성공이 아니다. 결과 recordings/assembly_replay_20261013_converged_top/report.json. 같은자료의 반복횟수를계속늘리지않고 실제표면/외곽근거와 보정반복성 확인이 필요하다.

## 직접 윗면 방식 실패 근거 추가

사용자가 현재 스터드 윗면 직접 측정 방식 유지를 선택했다. 직접 평면 추출에 best_parallel_points/fraction/height/slope와 plane_rejections를 추가했다. 이는 중간 후보의 진단이며 최종 승인된 윗면/층이 아니다. 반환 선택과 판정조건은 바꾸지 않았다.

최신 재생 direct_top_diagnostics: 6장14검출, 확정0개. 초기 윗면 평면 후보 지지 비율은 V0 1층기록25.3%, D1 2층기록24.6%, V0 3층기록37.5%, 그 외7.5~17.5%다. 대부분25% 지지조건 미달이며25%를 넘은 V0도 재수집 후 평면 residual/최종 지지조건을 모두 만족하지 않았다. 중간 후보 높이를 확정값으로 반환하지 않는다. 표면 분포·보정 자세 확인이 필요한 근거이며 반사 원인으로 단정하지 않는다. 관련38검사 통과·재생 종료0, 실제 장치 미검증.

## 현재 채택 — 윗면 직접 측정

사용자 요청으로 기본 Geometry를 DIRECT_STUD_TOP으로 전환했다. 높이가 가장 높은 지지된 평면을 선택하며 몸체/스터드4mm 쌍은 필수가 아니다. 50점/전체 지지25%/평면 기울기10도/±0.75mm residual 시험조건을 적용하며 단일 최대값을 쓰지 않는다. 기본 live/replay는 블록 스터드 가산0mm, production도0m이다. 보드 datum 변환+4mm는 별개로 유지하고 층 기준/허용오차는 유지한다. 명시적인 이전 BODY_TOP_PLUS_STUD 입력은 호환 경로로만 남긴다.

실제6장/14검출 재생은 좌표·층 확정0개로, 관측 가능한 충분한 윗면 평면 확보가 아직 실패한다. 최신 결과는 recordings/assembly_replay_20261013_direct_top_refined/report.json이며 이전 두면 분리 결과와 구분한다. 구별되는 평면이 없으면 의미적으로 스터드 끝이라는 보장은 없으므로 실측 GT·보정 자세 확인 없이 정상으로 채택하지 않는다. 실제 장치 연결 성공은 미검증이다.

## 외곽 후보 후속 시험 — 실제 판정 개선 없음

RGB/YOLO contour의 convex hull도 네 꼭짓점 후보로 검사하도록 보완했다. 마스크85%/Depth 포함80%/내부 지지55%·크기·층 조건은 변경하지 않았다. 관련 검사51 passed, 종료0. 최초 구현의 OpenCV contour tuple/list 오류는 수정 후 재검증했다.

동일6장/14검출 재생 결과는 여전히 표면 분리4개·외곽 보류4개·표면 분리 보류10개·좌표/층 확정0개다. 출력: recordings/assembly_replay_20261013_convex_outline_fixed/report.json. 최초 오류 실행은 convex_outline 폴더에 별도로 보존했다. 외곽 후보 추가만으로 실제 문제가 해결되지 않았으므로 같은 시험을 반복하거나55% 조건을 임의 완화하지 않는다.

표면 분리 성공 기록의 body 높이(보드 스터드 기준)는11.454/28.979/50.748/66.495mm다. 평면 datum+4 및 블록 stud+4 적용 시 시험 top은19.454/36.979/58.748/74.495mm. 폴더 층 이름이 실제GT라는 보장은 없으며, 현 층 기준과 다르다는 이유로 보정값을 맞춰 바꾸지 않는다. 카메라/보드 자세 반복성과 실제 기준면 확인이 다음 필요사항이다.

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
