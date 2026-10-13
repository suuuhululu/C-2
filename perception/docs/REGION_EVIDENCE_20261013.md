# 조립판 확인 영역 생성 — 2026-10-13

## 구현 범위

ROI는 분석 범위일 뿐 확인 증거가 아니다. 공통 Observed의 verified_regions는 블록 존재와 실제 빈 공간의 두 근거에서 생성한다. 확인되지 않은 곳은 목록에 넣지 않는다. 공통 여섯 필드는 변경하지 않았다.

### 블록 존재 근거

- BODY_TOP_PLUS_STUD 경로에서 Depth/높이/크기/방향/좌표 검사를 통과한 CANDIDATE만 공통 배치로 변환한다.
- 공통 footprint의 실제 칸과 관측된 layer만 확인한다. 가려진 아래층이나 주변 빈 공간은 생성하지 않는다.
- 기존 확인 이력은 미확인 아래층 때문에 삭제하지 않는다. 변환/보정 ID 오류는 실패한다.
- process_saved/observe_cycle/process_saved_bundle에 연결하고 계산 근거를 measurement와 measured_occupancy_evidence.json에 저장한다. legacy 경로의 기존 의미는 유지한다.

### 빈 공간 근거

- 각 칸의 3D공간을 카메라에 투영하고, 해당 공간을 지나는 실제 픽셀의 Depth가 공간의 뒤쪽까지 도달하는지 ray-box 교차로 검사한다. 픽셀의 ray parameter와 센서값은 모두 camera optical Z(m)다.
- 검사 공간은 현재 flat-board0 기준에서 보드 스터드4mm+시험 오차2.5mm 위부터 5층96.5mm+시험 오차2.5mm까지다. 이 모델은 채택된 블록 범위의 빈 공간 추론이며 작은 외부 물체/안전 검증을 보장하지 않는다.
- 원본 Depth0/거리 범위 밖/한 ray라도 앞에서 막힘/객체 mask/시야 밖/지원픽셀 부족은 미확인이다. 칸별 모든 유효 검사ray를 요구하고 평균/YOLO미검출/ROI만으로 EMPTY를 만들지 않는다.
- 칸의 전체1~5층 공간이 확인된 경우만 각 layer의1x1 region을 생성한다. 측정된 블록 footprint와 겹치는 column은 빈 공간 결과에서 제외한다.
- 코드: region_evidence.empty_column_evidence. none/brown_conrady projection을 지원하며 unsupported distortion은 실패한다. Source pose/CameraInfo/단위/층 기준이 실제 촬영과 일치해야 한다.

## 기존 실제 빈 보드3장 진단 재생

원본RGB/Depth/CameraInfo, 현재 보정/설정을 사용했다. 실제 모델의 검출mask0을 확인했다. 기록이 서로 다른 시각의 과거촬영이며 당시 실제 robot pose와현재보정 반복성은 미확인이다. 실제 D INITIAL을 채택하거나 현재 보드 상태를 확정한 결과가 아니다.

| View | 계산상 clear columns | 미확인 columns |
|---|---:|---:|
| V0 | 366 | 210 |
| D1 | 269 | 307 |
| D3 | 442 | 134 |

진단상합집합은556/576칸으로20칸이 미확인이다. 실제 동일검사 bundle이 아니므로 이합집합을 D 결과로 전달하지 않았다. 모든 곳을 빈 Current로 초기확정할 근거는 부족하다.

- V0: 시야잘림48, invalidDepth162(누락96/범위밖106)
- D1: 시야잘림30, invalidDepth277(누락174/범위밖119)
- D3: 시야잘림33, invalidDepth101(누락81/범위밖87)

누락과범위밖은 같은 칸에서 동시에 발생할 수 있어 하위수치를 합산하지 않는다. 출력은 recordings/empty_column_review_20261013_detailed/report.json과 View별 evidence JSON에 보존했다. 앞선 결과도 덮어쓰지 않았다.

## 검증과 남은 작업

관련 합성검사는 완전히clear한Depth,앞쪽가림,누락,거리범위밖,객체mask,시야잘림,관측된층만positive로반환,아래층이력유지,부족한INITIAL보류와 저장→판정 연결을 확인한다. 실제 ROI·센서·표면 추출 정확도 검증이 아니다.

실제 블록6장에서는 여전히 좌표/층확정0개이며 외곽/표면 추출은 미완료다. 실제 촬영의 보정일치·전체INITIAL coverage·Controller/D주입 및 공동 시험은 장치 연결 후 확인해야 한다. 조건을 낮추거나 미확인칸을 빈 상태로 채우지 않았다.
