# 실제 Perception 처리 코드

## 2026-10-15 팀 통합 조립판 ROI 연결

- `make_inspection_observer` 및 이를 사용하는 `connect_real_inspection`은 기본으로 패키지 기준 `recordings/assembly_board_roi`의 V0·D1·D3 최신 `assembly_roi.json`을 읽는다. 단독 live_view의 `--roi-root` 지정과 독립적으로 적용한다. 다른 위치는 geometry의 `assembly_roi_root`로 지정하며 상대 경로는 perception 폴더 기준이다. config.yaml에도 이 기본 경로를 명시했다.
- 관측 전에 ROI 설정을 고정하고 cycle context에 남긴다. 각 View에서 `조립판 ROI 적용` 로그와 `<cycle>/<View>/assembly_roi.json`, measurement의 `assembly_roi`로 적용 파일·polygon·해상도를 확인한다. 지정된 파일 누락·View/해상도 불일치는 오류이며 전체 화면으로 자동 대체하지 않는다. 현재 저장된 ROI는 1280×720용이다.
- YOLO는 ROI 외접 사각형의 원본 RGB를 분석하고 mask를 원본 영상 좌표로 복원한다. polygon 밖 후보는 제외하고 경계에 걸친 후보는 UNKNOWN으로 유지한다. 저장 영상 재분석도 동일한 ROI 필터를 적용한다. 보드 기준면과 빈 공간 검사에 ROI 밖 픽셀을 사용하지 않으며 ROI 자체가 빈 공간 확인 근거가 되지는 않는다.
- 실제 초기 검사에서의 후보 3개가 ROI 밖 오검출이었는지는 미확인이다. 수정본 적용 후 같은 pose/해상도의 원본과 mask로 재검증해야 한다. ROI 안의 오검출 및 미확인 Depth가 자동 해결됐다는 의미는 아니다.

## 2026-10-15 INITIAL의 블록 위 빈 공간 확인 보완

- V0에서 좌표·층이 확정된 블록의 footprint에 대해 `empty_above_block_evidence`가 위쪽 공간을 별도로 검사한다. 예를 들어 2층 블록 위의 3~5층 공간을 통과한 모든 유효 Depth ray가 그 공간 뒤쪽 표면에 도달해야 확인 영역으로 추가한다. 블록이 있다는 이유만으로 위쪽이 비었다고 추정하지 않는다.
- 기존 층 기준과 높이 허용값으로 검사 하한을 정한다. UNKNOWN 후보 mask, 0 Depth, 거리 범위 이탈, 가림, 영상 바깥 영역은 제외한다. 확인하지 않은 아래층은 추가하지 않으며 D1/D3의 미채택 층을 근거로 상부 공간을 확정하지 않는다. 원래의 전체 빈 열 증거와 새 상부 증거는 `verification_basis`/진단에 구분해 남긴다.
- 윗면 검출·좌표·층 임계값 및 INITIAL 전체 범위 조건은 유지한다. 실제 실패 촬영 자료의 보정 오차/윗면 탈락 원인은 별도 분석과 실물 재검증이 필요하다.

## 2026-10-13 시험용 평균 층 기준

- body/stud 추출은 관측된body 평면의residual band로최대3회재수집한다. 허용기울기내의표면을수평slice로잘라버리지않으며, 둘의동일XY간격이4mm±0.75mm로유지되는지도검사한다. 검사수치와원본보정/층기준은변경하지않았다. 단일표면/비평행/지원부족은미확인이다. 같은실제6장에서는분리통과4개이지만좌표·층확정0개라실물판정완료로표시하지않는다.

- 확인 영역 생성은 `depth_grid.occupied_region_evidence`(측정 완료 블록의 실제 footprint/layer만)와 `region_evidence.empty_column_evidence`(1~5층 공간을 지나는 모든 검사ray가 뒤쪽까지 clear할 때만)로 연결했다. 감지되지 않은 곳/ROI/가려진 아래층을 EMPTY로 간주하지 않는다. 원본 Depth누락/거리범위/객체mask/가림/시야잘림은 미확인으로 남긴다. 과거 실제 빈 보드3장 진단상556/576칸 합집합이며 실제같은check bundle/현재보드 확정이 아니다. 상세 근거와 미완료 범위는 `perception/docs/REGION_EVIDENCE_20261013.md`다.

- 표면 분리 이후 높이는 몸체만 사용한다. 윗면 존재25%/RGB 외곽의 표면 증거는 확인된 몸체+스터드를 합쳐 사용한다. 분리 때문에 몸체만으로 전체 윗면 지지 비율을 요구하지 않는다. `surface_diagnostics`는 점수/지지 비율/거부 조건/외곽 내부 증거를 기록하며 공통 Observed 필드를 확장하지 않는다. 실제6장 재시험의 최신 실패/미완료 범위는 docs/ASSEMBLY_REPLAY_20261013.md를 참고한다.

- 최신 사용자 요청: 각 위치의 최상층은 `BODY_TOP_PLUS_STUD`로 측정한다. 몸체 윗면을 추출하고 그 위치에 스터드4mm를 한 번만 더한 높이를 기존 층 기준과 비교한다. 층수×4mm를 더하지 않고 기존 기준표에도4mm를 다시 더하지 않는다. board stud-top→flat-board datum 이동4mm와 block stud4mm는 서로 다른 연산이다. 몸체 좌표로 윗면 역투영을 계산하며 저장 결과의 body_surface_height_m/body_height_mm와 block_stud_added_m/mm로 연산을 확인할 수 있다.
- 시험 추출은 약4mm 간격의 두 board-parallel 표면이 충분히 관측된 경우 높은 몸체/스터드 쌍의 몸체만 선택한다. 현재 높이 band±0.75mm, 최소50픽셀(생산자는 설정값), plane 기울기10도는 실물 검증 전 시험값이다. 단일 표면만 있거나 둘을 구별하지 못하면 body_stud_surfaces_unverified로 보류하며 이미 측정된 스터드 높이에 다시4mm를 더하는 fallback은 없다. 이는 의도한 몸체/스터드 구분의 실제 성능 검증이나 전체 확인 영역 생성 완료가 아니다. 명시적 layer-reference JSON에는 block_stud_height_mm:4를 제공해야 화면에 이 방식이 적용된다.

- 기본 손 설정은 저장된 V0 hand_config의 ROI·polygon·해상도·confidence/안정·Depth 품질값을 재사용한다. `--hand-config` 미지정 시 config.yaml을 읽고 모델 상대 경로는 perception 폴더 기준으로 해석한다. 별도 설정을 지정하면 그 설정이 우선하며 D1/D3 손 모델은 로드하지 않는다. 실제 보드/카메라 위치가 달라지면 기존 ROI의 적용 조건을 다시 확인한다. 새 ROI를 생성할 때는 이전 ROI의 품질값을 자동 확정하지 않는다.
- Geometry calibration_id는 `assembly_pitch16_flat0_20261013`으로 연결했다. 중심→최소 스터드 좌표 변환은 공통 footprint/방향 계약에서 계산했고, 보드 경계[-8,376]mm 및 블록 크기32x32/32x48/16x32mm는16mm 피치에서 계산한 명목값이다. 플라스틱 몸체를 새로 실측한 값이 아니다. 기존 integrated/grid_anchor의 시험값(유효Depth80%, 최소50픽셀, 좌표0.25stud, 크기0.35stud, 방향10도)을 재사용하고 `temporary_test`로 표시한다.
- Depth 범위는 flat-board 변환에서 보드 경계[-8,376]mm×[-8,376]mm, 높이0~99mm(5층96.5mm+층 오차2.5mm)의8개 모서리를 카메라로 역변환해 optical Z 최소/최대를 구한다. 추가5mm는 시험용 카메라-Z 여유이며 층 오차±2.5mm와 별개이고 센서 정확도 근거가 아니다. 경계를 바깥 방향1mm로 반올림한 기본값은 V0 443~573mm, D1 334~763mm, D3 397~696mm다. `depth_ranges_from_board`로 재계산할 수 있다. 보드 전체 물리 영역을 사용하며 화면에 보이지 않는 위치의 관측 가능성을 주장하지 않는다.
- `process_saved`는 metadata의 View에 해당하는 `depth_ranges_m`를 선택하며 설정된 View가 빠지면 실패한다. 공통 min/max는 전체 합집합의 이전 직접 함수 호출 호환값이며 production 저장 영상은 View별 범위를 사용한다. 기본 통합 live_view에도 View별 범위를 적용한다. 명시적 --layer-reference JSON을 사용하는 경우 depth_ranges_m도 포함해야 같은 제한을 적용한다. 상태는 calibration_derived_trial_not_depth_validated다.
- `max_height_spread_m=0.005`는 한 블록 표면의 P95-P5가5mm 이하인지 검사하는 시험값이다. ±2.5mm 층 허용 오차의 전체 폭5mm를 품질 게이트의 초기 제한으로 재사용했으며 실측 잡음의 통계적 검증값은 아니다. 이는 표면 내부 일관성 검사이고 층 기준 대비 정확도와 다르다. BODY_TOP_PLUS_STUD를 사용하는 production/기본 live_view는 추출한 몸체 표면에서 검사한다. 차이 초과는 surface_height_conflict로 보류한다. 역투영 방식이 달라 두 경로의 검사 대상 픽셀이 같다고 주장하지 않는다.
- 현재 Geometry 설정은 null 없이 형식 검사를 통과하지만 시험값의 정확도/전체 확인 영역 생성/실제 연결 완료는 아니다. ROS 경로에서 사용하지 않는 직접 USB camera serial/fps/timeout는 임의로 채우지 않는다. 실제 빈 보드/5층 Depth와 보정 자세 반복성을 검증한 뒤 범위를 확정해야 한다. 명시적 layer-reference override에는 max_height_spread_mm를 제공해야 화면에 동일 품질 제한이 적용된다.

- 사용자 채택 증가량: `(96.5 - 22) / 4 = 18.625mm/층`. 1층부터 기준 높이는 22 / 40.625 / 59.25 / 77.875 / 96.5mm, 시험용 허용 오차는 ±2.5mm다. 블록 단독 실측으로 만든 모델이며 보드 부착1층22mm는 검증 전 임시 절편이다. 실물 보드 기준 높이 검증 결과나 깊이 센서 정확도로 표시하지 않는다.
- `config.yaml`의 geometry에 저장하고 통합 live_view의 기본 층 판정에 사용한다. `--layer-reference` JSON을 주면 그 설정이 우선한다. 기본 화면 높이/층 판정은 기존 stud-top0 높이에4mm를 더한 flat-board0 기준이며, 윗면 역투영에는 원래 높이를 사용한다. 범위 밖은 L:?이다. 16mm 스터드 피치는 XY 좌표용이며 층 증가량과 별개다.
- B 생산자용 flat-board 변환은 `perception/calibration/assembly_runtime_pitch16_flat0_20261013.json`이다. 기존 3개 pose와 사용자 실측 board stud4mm로 도출한 변환이며 새 실기 보정 검증이 아니다. `config` calibration_id/나머지 Geometry 설정 및 실제 확인 영역 준비는 여전히 필요하다. 기본 live_view 계산과 생산자 함수 주입은 별도 연결이다.

## 비교 구간 3D 안내 표시

기본 overlay-mode는 auto다. B 요청 처리 시작의 OBSERVING에서는 target을,
MATCH/MISMATCH 확정의 CONFIRMED에서는 changes를 선택한다. UNOBSERVABLE은
변화 확정 화면으로 전환하지 않고 목표 비교를 유지한다. 새 검사/계획·취소/오류/종료는
표시를 지운다. connect_inspection의 선택 display_sink는 해당 상태/None을
화면 소유 스레드에 enqueue하는 callback이다. 공통 D 결과 봉투는 변경하지 않는다.
표시 sink·실제 비교 프레임/투영 입력의 실행기 결선은 여전히 필요하며,
이 옵션을 추가했다고 기존 단독 카메라 명령이 팀 검사 결과를 자동 생성하지는 않는다.

`InspectionConnection.comparison_display_state()`는 B 비교 확정 전의 previous_current,
확정 후 current, 실제 비교 expected 및 check/Plan/Step 문맥을 복사해 제공한다.
공통 Observed 및 D 결과 봉투는 바꾸지 않는다. 새 검사/계획·취소·종료에서
이전 표시 상태를 무효화한다. 표시 자체는 완료·Robot 권한이 아니다.

`visualization.render_comparison_overlay()`의 mode는 target(Current/Expected),
changes(이전/현재 Current)다. 호출자는 실제 RGB와 payload를 전달한다:
state(위 snapshot), projection(기존 3D 투영 입력), projection_valid,
phase=COMPARISON, view_id, 실제 frame_stamp_ns, height_reference=board_flat_surface.
평평한 보드 윗면을 Z=0으로 쓴 실제 투영/층 높이 입력만 채택한다.
기존 stud 기준 transform에 표시용 문자열만 붙여 사용하지 않는다.

로컬 live_view는 선택 옵션 `--comparison-overlay <실제 표시 입력.json>`과
`--overlay-mode target|changes`로 같은 함수를 호출한다. 이 JSON은 로컬 화면
전달용이며 새 필수 공통 계약이 아니다. 팀 실행에서는 동일 함수를 호출하는
화면 연결부를 쓰면 된다. D production 결선이나 입력 파일 자동 생산은 이 수정으로
완료되지 않았다. actual compare frame과 stamp/View가 다르거나 이동 중·V0 손
조건 미확인·취소 phase·높이 기준 미확인이면 숨긴다. 관측 진단 옵션은 손 조건을
우회해 3D 비교를 허용하지 않는다. 아직 실제 Current/Expected 입력 없이
기존 명령만 실행하면 3D 안내는 나타나지 않는다.

## 2026-10-12 PR29 리뷰 — 검사 시작 조건과 촬영/분석 경계

- 2026-10-15 수신 보완: 통합 촬영의 ROS 콜백은 전용 수신 스레드에서 처리해 Controller 상태 조회가 느려도 수신을 계속한다. 상태 확인이 끝난 뒤 최신 유효 묶음을 선택하며, 정상/실패 모두 수신기를 종료한다. 기존 15초 대기·50ms 동기화·250ms 최신성·정지/취소 조건은 유지한다.

- 자동 단발 촬영 함수는 `ros_capture.capture_inspection_view(manifest, view, is_active, *, output_root, scene_id, calibration_id, robot_pose, is_stopped, verify_occupancy=None)`다. `functools.partial`로 실제 장면 ID/보정 ID, Controller의 `robot_pose(view)`와 `is_stopped(view)`를 지정하면 `make_inspection_observer`의 `capture_view` 인자로 사용할 수 있다. Robot 이동 명령은 없다. 고정 ROS raw RGB/원본 Depth/aligned Depth 및 CameraInfo 토픽을 전용 Context/Executor에서 수신하고 한 묶음 저장 후 종료한다. D ROS Context를 종료하지 않는다. 정지/활성 요청을 반복 확인하며 요청 후 프레임·기본 50ms 동기화·250ms 신선도를 요구한다. ROS PC 간 시계 동기화가 필요하며 오래된 프레임/시간 초과는 실패로 반환한다. RGB·원본 Depth·정렬 Depth 구독은 BEST_EFFORT depth1, CameraInfo는 기존 BEST_EFFORT인 sensor_data QoS다. V0 손 수신·live_view·공급판 ROI RGB 구독에도 동일한 BEST_EFFORT 방침을 적용한다.
- `verify_occupancy(directory, manifest, view)`는 실제 저장 영상에 근거한 `verified_regions`·`verification_basis`를 반환해야 한다. 미제공 시 확인 영역은 빈 목록이며 정상 판정 근거가 아니다. ROI를 확인 영역으로 바꾸지 않는다. Controller/확인 영역 함수와 실제 Geometry/층 높이 설정이 없으면 이 함수만으로 전체 시나리오가 완성되지 않는다.
- V0 손 수신은 `ros_capture.stream_ros_hand(is_active, is_stopped)`를 제공한다. `make_inspection_observer(..., hand_stream=None, is_stopped=실제정지확인함수)`로 선택하면 요청 활성 조건과 연동된다. V0 정지 후 raw RGB와 aligned 16UC1 Depth를 별도 수신 스레드에서 받고 기존 HandDetector/HandCycle로 판정한다. 매 분석에는 새로운 최신 동기화 묶음을 사용하며 큐는 제한된다. 준비 완료/STOP/이동/통신 오류 시 stream을 닫고 B 전용 Context만 종료한다. 손 추론 중 block YOLO는 실행하지 않고 준비 완료 후 별도 RGB-D 단발 촬영/분석을 수행한다. 기본 한 프레임 수신 제한15초, 동기화50ms, 신선도250ms이며 실제 성능은 장치에서 검증해야 한다. 영상 끊김/UNKNOWN을 손 없음으로 취급하지 않는다. 이 손 감지는 엄지척 인식이나 안전 인증이 아니다.
- ROS 수신 저장 연결: `rgbd_io.save_capture(directory, messages, infos, topics, view, 50., context=context)`에 `scene_id`, 실제 `robot_pose`(frame/단위/기준 포함), `calibration_id`, `check_id`, 정수 `observation_seq`를 제공한다. 메시지는 실제 정지 후 새로 받은 RGB/raw Depth/aligned Depth이며 수신 측이 요청 최신성과 STOP/취소를 확인해야 한다. ROS CameraInfo 원문을 유지하고 실제 K/D를 Depth 역투영 필드로 함께 기록한다. 이 파일은 `load_frame` 입력 형식과 호환된다. `context` 없는 기존 진단 촬영 의미는 유지한다. 이 함수는 수신 구독/Controller 이동을 수행하지 않으며 `verified_regions`나 층 기준을 생성하지 않는다. 실제 확인 영역 근거는 별도 필요하다.
- make_inspection_observer의 INITIAL/FINAL 기본 시작 조건은 STOPPED_CLEAR다. 새 손 진입과 손 이탈 3초 대기는 요구하지 않는다. 실제 V0 정지·안전 확인, 손 ABSENT·설정된 영상 안정 시간·프레임 품질 확인은 계속 필요하다. 저장된 시험 안정값은 밝기 차이 평균 3 이하·연속 1초이며 안전 인증이나 독립 성능 검증값이 아니다. UNKNOWN이나 손 PRESENT를 무시하는 무조건 촬영이 아니다.
- 2026-10-13 팀 요청 기준: D가 엄지척(사람 조립 완료) 또는 로봇 작업 완료 후 STEP 검사를 요청한다. make_inspection_observer의 STEP 기본도 STOPPED_CLEAR로 변경했다. 새 손 진입/이탈 3초를 다시 기다리지 않고 실제 정지·손 없음·영상 안정을 확인한다. 엄지척 인식은 D 책임이며 B가 MATCH로 치환하지 않는다. 독립 손 기반 호출은 start_condition 함수로 HUMAN_ASSEMBLY를 명시할 수 있다. 공통 요청/Observed 필드는 변경하지 않았다. 로컬 live_view의 독립 손 사이클은 이번 변경 대상이 아니다.
- hand 대기와 begin_observation에는 프레임 유효성 검사를 유지한다. 실제 V0 캡처 문맥을 확인한 뒤 freeze_capture로 CAPTURED 단계에 들어가며, 이후 CPU 분석 시간이 마지막 손 프레임 age를 증가시켰다는 이유로 finish_observation을 실패시키지 않는다. 기존 bundle_valid/is_active/STOP·취소 검사는 분석 후·전달 전에도 유지한다.
- 수신 종료 뒤 새 손 진입을 감지할 수 있다고 주장하지 않는다. 캡처 후 장면 연속성/로봇 이동/STOP은 실제 Controller·capture hook의 유효성 근거가 필요하다. 이 변경은 D 실행기나 로컬 live_view의 시작 정책을 자동 교체하는 것이 아니다.
- 실제 검증: B MVP/legacy/calibration/supply 및 로컬 소비자 입력 검증 함수 대조 310 passed, 종료 0. 새 손 진입 없는 INITIAL/FINAL, 사람 STEP 진입 필수, 명시 로봇 STEP, UNKNOWN/불안정 차단, 1초 허용 간격·1.1초 분석의 상태기계 및 캡처/분석 경로를 검사했다. 합성 clock·관측/장치 hook 결과이며 실제 Camera/Robot 시험은 아니다. 기존 사용자 변경 보존. 다른 팀 코드·문서 및 STATUS.md 변경·commit/push 없음.
- 3초 대기 제거 후 재검사: 2026-10-12 동일 B 관련 범위 316 passed in 5.51s, 종료 0. STOPPED_CLEAR에서 안정 1초 충족 후 즉시 허용, 사람 모드 정확히 3초 거절/3초 초과 허용, 손 재진입/UNKNOWN/프레임 끊김/불안정의 안정 시간 초기화, 다음 사람 요청의 기존 조건 복원, STOP 때 stream 종료를 추가 확인했다. 기존 취소·분석 지연 검사도 재실행했으며 이전 310개 수치와 합산하지 않는다. 실제 카메라 시험은 별도다.

## 2026-10-12 B 관측 생산자 INITIAL/STEP/FINAL 연결 보완

최신 통합을 포함한 로컬 9f57a7e 기준에서 B 코드만 보완했다. 다른 팀의 코드·문서는 수정하지 않는다.

- main.make_inspection_observer는 기존 connect_inspection의 observe(context, is_active)에 전달할 B callable을 만든다. capture_view(manifest, view, is_active)는 실제 촬영 데이터 폴더·verified_regions·verification_basis를 반환해야 한다. confirm_view, workflow_valid, bundle_valid, 손 stream은 실제 Camera/Controller 조건의 hook이며 함수 존재만으로 실기 연결 완료가 아니다.
- 요청 문맥을 복사한 뒤 V0 손 진입/이탈·안정 → V0/D1/D3 정지·1쌍 촬영·View별 분석·저장을 수행한다. capture에 전달한 문맥 복사본 변경으로 원래 check_id/순번/검사 종류가 바뀌지 않는다. 취소 시 is_active와 기존 유효성 검사를 적용한다.
- INITIAL/FINAL에서는 target_after=None이며 가짜 Step 블록을 생성하지 않는다. INITIAL의 전체 24×24×5 확인 범위 부족은 UNOBSERVABLE Observed로 보고하고 검사 코어가 초기 Current 미확인을 유지한다. FINAL 새 확인 근거 없음도 UNOBSERVABLE이다. FINAL의 일부 유효 근거가 있다는 OK는 MATCH가 아니며 실제 Current/Expected 비교는 VisionInspection이 담당한다.
- STEP과 기존 ASSEMBLY 호출의 기본 동작은 유지한다. 공통 여섯 Observed 필드, 기존 Current/revision 소유, 아래층 이력 정책을 변경하지 않는다. 예상 배치·ROI·빈 검출 목록을 실제 확인 영역으로 대신하지 않는다.

연결 형태(실제 hook이 준비된 경우의 Python 호출 안내이며 독립 실행 명령이 아님):

```python
from perception_mvp.main import make_inspection_observer
from perception_mvp.team_connection import connect_inspection

observe = make_inspection_observer(
    gate, hand_detector, hand_stream, capture_view,
    weights, calibration, geometry_config, confidence,
    confirm_view=confirm_view, workflow_valid=workflow_valid,
    bundle_valid=bundle_valid, output_root=output_root,
)
b = connect_inspection(enqueue_result, observe=observe,
                       geometry_reference=geometry_reference)
```

실제 Geometry의 보드 기준면·층 높이·허용오차·통합 변환, 실제 정지/안정 hook, verified_regions 생산 근거는 아직 준비/연결 필요다. D 실행기의 합성 observe를 실제 callable로 교체하는 것은 D 담당자가 확인해야 하며 이번 작업에서는 해당 파일을 수정하지 않았다. LLM/API·DB·Robot 제어를 이 함수가 수행하지 않는다.

검증 기록: 2026-10-12 B MVP/legacy/calibration/supply + 로컬 D consumer 입력 검증 함수 대조 **298 passed**, 종료 0. 신규 검사에는 INITIAL/FINAL 범위·가짜 target 거부·문맥 고정/취소와 V0→D1→D3 캡처/저장 hook 실행이 포함된다. 배열·관측 영역·장치 hook은 합성 Fixture이므로 실제 Camera 정확도나 안전·실물 체결 증거가 아니다. Python 문법과 대상 diff 검사도 확인했다. 과거 317개 최신 모의 통합 결과와 중복하므로 합산하지 않는다. 실제 Camera/Controller/DB·웹 검증, commit/push는 수행하지 않았다.

## 이 PC 실행 환경 — CPU 전용

사용자 결정으로 이 PC는 GPU가 아닌 CPU를 사용합니다. 블록/손 predict는 device=cpu를
명시하며 train/evaluate의 기본 --device도 cpu입니다. GPU 드라이버를 변경하지 않습니다.
사용자 요청에 따라 기본 Python의 사용자 계정 설치를 사용합니다.
가상환경 활성화 없이 실행합니다. 시스템 파일을 삭제/덮어쓰지는 않지만 사용자 패키지가
기존 패키지보다 우선될 수 있으므로 ROS/모델 호환성은 실제 실행으로 확인해야 합니다.

```bash
cd /home/roh/C-2/perception
python3 -m perception_mvp.local_test preflight
```

이후 아래 명령은 기본 python3로 실행하세요. 이전 .venv는 운영 환경으로 사용하지 않습니다.
CPU 실행은 가능 여부/속도를 실제 모델·데이터로 확인해야 하며 학습 완료를 보장하지 않습니다.

## HMI 없이 실제 데이터로 단독 시험

단독 진입점은 `python3 -m perception_mvp.local_test`입니다. 기존 운영 14개 파일을
재사용하는 별도 시험 도구 1개이며 알고리즘/데이터를 복제하지 않습니다.
Backend check/순번/목표 after를 만들거나 요구하지 않습니다. 결과는 LOCAL_ONLY이며
Observed/Current/조립 완료/Robot 실행 권한으로 보내거나 채택하지 않습니다.

```bash
cd /home/roh/C-2/perception
python3 -m perception_mvp.local_test preflight
python3 -m perception_mvp.local_test devices
python3 -m perception_mvp.local_test capture --help
python3 -m perception_mvp.local_test check-recording --help
python3 -m perception_mvp.local_test infer-rgb --help
python3 -m perception_mvp.local_test measure --help
python3 -m perception_mvp.local_test watch-hand --help
```

| 명령 | 실제 필요한 입력 | 출력/목적 |
|---|---|---|
| preflight | 현재 Python 환경 | 패키지 설치 여부; 자동 설치/장치 검증 없음 |
| devices | 연결된 RealSense와 SDK | 실제 serial과 장치가 제공하는 공통 RGB8/Z16 해상도·FPS |
| capture | config.camera, 실제 Robot pose 파일, 직접 정지·이탈 확인 | 원본 RGB/Depth/metadata와 rgb.png |
| check-recording | 실제 촬영 폴더 | 배열 형식·Depth 유효 비율·카메라 거리·센서 시각 차이 |
| infer-rgb | 실제 촬영 폴더, 실제 블록 .pt, confidence | 보정 없이 실제 클래스/confidence/mask와 겹쳐보기 |
| measure | 동일 실제 장면의 View 폴더, 블록 .pt, 실측 calibration/config | 실제 Depth/Grid 후보·충돌·시점 통합·UNKNOWN 이미지 |
| watch-hand | config.camera/hand, 별도 손 모델, 실제 V0 정지 확인 | 실제 진입·이탈·3초 초과/안정 상태 변화 로그 |

실행 준비는 한 번 config.yaml의 camera 항목에 devices에서 확인한 serial/stream 설정과
현장 시험에서 정한 timeout을 입력합니다. 임의 기본 stream 설정을 선택하지 않습니다.
capture의 --robot-pose로 실제 V0 pose 파일을 지정하고 --stopped-and-clear로 직접 확인합니다.
--config를 생략하면 패키지 config.yaml을 읽습니다. --output을 생략하면
작업 폴더 recordings/UTC촬영식별 또는 local_results/UTC시험식별에 자동 저장합니다.
기존 폴더는 덮어쓰지 않습니다. --scene-id를 생략하면 실제 수집 폴더명으로 장면을 식별합니다.
여러 View를 같은 장면으로 시험할 때는 같은 실제 scene-id를 지정해야 합니다.

단독 capture는 observation_context를 생략해 기존 실제 수집 함수를 호출합니다.
보정 전에도 저장 가능하지만 이후 Board 좌표 계산에는 실제 보정 파일이 필요합니다.
이 기록을 Backend 통합용으로 재사용하려고 가짜 check/순번을 붙이지 않습니다.
통합 시험에서는 기존 main.capture로 촬영 당시 실제 Backend 문맥을 기록하세요.

measure의 --scene-stable은 담당자가 해당 View 묶음의 정적 장면을 실제 확인한 경우에만 지정합니다.
미지정이면 통합 증거를 확정하지 않습니다. --regions는 선택적 실제 점유 검증 근거 파일이며,
View ID별 verified_regions와 verification_basis를 입력합니다. 미제공이면 영역은 미확인입니다.
--previous-accepted는 실제 이전 채택 배치 JSON 목록을 받아 추적 함수를 시험합니다.
현재 결과를 자동으로 이전 채택 상태로 저장하지 않습니다. --ground-truth는 사람이 확인한 실제
배치 목록이며 Expected가 아닙니다. 정확 배치 비교값이 true여도 Backend 완료 PASS가 아닙니다.

라벨 검사·학습·평가·색상 검수는 아래 기존 main 명령도 이미 HMI 없이 사용 가능합니다.
단독 도구가 verified_regions 자동 판정·전달판 판단·Robot 이동의 미구현 기능을 대신하지 않습니다.
실제 입력이 없는 경우 성공 결과를 만들지 않고 오류를 반환합니다.

2026-10-06 누적 설계 조건·코드 생성 요청서 적용. 운영 진입점은 `python3 -m perception_mvp.main`입니다.
새 예시 데이터·가짜 검출·합성 시험을 만들지 않습니다. 기존 예시/데모/tests는 보존한 과거 검증 자료이며 운영 import에 포함하지 않습니다.
루트의 과거 rgbd_io/capture_rgbd/depth_grid/saved_perception 구현은 보존본입니다. 신규 실행은 이 패키지 내부 구현만 사용합니다.

## 주요 운영 구성

### V0 손 감지 보드 ROI 선택

카메라 ROS 노드는 켜 두고 로봇을 실제 V0로 이동·정지한 후 손을 보드에서 빼세요.
아래 명령은 로봇 이동을 하지 않으며 원본 RGB 토픽만으로 ROI를 선택할 수 있습니다.

```bash
source /opt/ros/jazzy/setup.bash
cd /home/roh/C-2/perception
python3 -m perception_mvp.live_view --view V0 --select-hand-roi \
  --stopped-and-clear --output /home/roh/C-2/perception/recordings/hand_roi/V0
```

화면에서 r → 보드 전체를 포함하는 사각형 드래그 → Enter로 확정합니다.
ROI 창에서 C는 취소이며 빈 선택은 저장하지 않습니다. q로 실시간 화면을 종료합니다.
RGB 해상도를 유지한 상태에서 선택하세요. ROI는 손 감지 영역이며 블록 인식/Grid
영역을 줄이는 것이 아닙니다. 보드가 영상에서 기울어져 있으면 전체 보드를 포함하는
외접 사각형을 선택하므로 모서리 주변 배경도 포함될 수 있습니다.

`recordings/hand_roi/V0/<UTC 시각>/hand_config.json`과 roi_preview.png를 새로 저장합니다.
hand 설정에 board_roi_v0=[left,top,right,bottom] 및 board_image_size=[width,height]를
기록합니다. 재선택은 새 폴더에 저장해 이전 설정을 덮어쓰지 않습니다.
설정의 손 모델 경로는 현재 모델이고 confidence·Depth 품질·안정화·프레임 간격은
미설정 null을 유지합니다. 이 ROI 설정만으로 3초 이탈 사이클을 실행할 수는 없습니다.
기록한 해상도와 다른 RGB에서는 감지기를 오류/UNKNOWN으로 처리합니다.

### 관측 사이클 자동 저장

`main.observe_cycle`은 실제 정지·안정화와 활성 요청을 확인한 뒤 capture_view가
반환한 실제 RGB-D를 자동 보존합니다. 기본 경로는 패키지 위치 기준
`recordings/observation_cycles/<UTC 촬영묶음 시각>/V0`, `D1`, `D3`입니다.
`output_root`로 저장 루트를 지정할 수 있으며 정상/재관측/inspect 진입점에서도
같은 인자를 전달합니다. c 입력이나 별도 저장 프로그램 실행은 필요 없습니다.

- 묶음: context.json에 check_id·순번·설정/보정·모델 경로를 고정 기록.
- 관측점: rgb.npy/png, depth_raw.npy/png, depth_aligned.npy/png, metadata.json,
  source.json, capture_evidence.json. Depth PNG/배열은 uint16을 유지합니다.
- 각 View 검증 직후: measurement.json, view_result.json, partial_observed.json,
  diagnostics.json. partial_observed는 중간 결과이며 Backend로 전송하지 않습니다.
- 묶음 통합: observed.json, diagnostics.json. callback 반환은 submission.json에
  기록하지만 D 채택·완료 판정 성공을 뜻하지 않습니다.
- 실패·취소: 가능한 기존 자료를 남기고 failure.json/HOLD를 기록하며 재시도하지 않습니다.

디렉터리와 JSON은 exclusive 생성이며 기존 자료를 덮어쓰지 않습니다. 저장 실패는
다음 View/결과 전송을 막습니다. 실제 처리 runtime에서 observe_cycle을 호출해야
적용됩니다. 이 변경이 미연결 Controller나 B processor를 구현한 것은 아닙니다.
`live_view` 로컬 화면은 기존 c 수동 저장을 유지하며 매 프레임 자동 저장하지 않습니다.

### 손 대기를 포함한 정상 관측 진입점

`main.run_observation_cycle`은 실제 정지 V0 확인 후 손 감지기를 초기화하고,
`wait_for_hand_ready`로 손 진입→연속 3초 초과 이탈·안정화를 확인한 다음
기존 `observe_cycle`의 V0→D1→D3 촬영·각 View 검증·통합·callback을 호출합니다.
명시적인 REAL 문맥을 고정하며 STOP/닫힌 요청 검사 함수가 실패하면 HOLD로 중단합니다.
`hand_stream`은 정지 확인 후 여는 실제 프레임 스트림 factory입니다.
이 함수는 Robot 이동을 생성하거나 Controller 안전 신호를 대신하지 않습니다.
V0 손 대기 동안 frame_sink로 영상을 표시하고 각 View 결과는 view_sink로 표시합니다.
`live_view` CLI가 이 진입점을 호출하도록 연결된 것은 아닙니다.

현재 저장소의 `app/vision_connection.py`에서 D bridge 요청 목적·세 결과 callback은
확인됐습니다. B의 실제 비동기 worker, 실제 Controller의 V0/D1/D3 정지/이동
인터페이스, View별 검증 설정·전달판 실제 판별 근거는 별도 연결이 필요합니다.

### RealSense ROS 손 검출 단독 시험

카메라 ROS 노드는 실행된 상태로 두고 로봇이 실제 정지한 V0에서 시험합니다.
아래 명령은 `/camera/color/image_raw`를 구독하며 USB를 직접 열지 않습니다.

```bash
source /opt/ros/jazzy/setup.bash
cd /home/roh/C-2/perception
python3 -m perception_mvp.live_view --view V0 --hand-detect-only \
  --weights /home/roh/C-2/perception/models/hand_yolo11n_added_20261012/weights/best.pt \
  --confidence 0.25 --output /home/roh/C-2/perception/recordings/hand_live_test
```

CPU 손 박스·점수만 표시합니다. confidence 0.25는 시험값입니다. 보드 ROI·Depth·
안정화 설정 없이 영상 전체의 손 검출만 확인하며 보드 진입/이탈 3초 판정,
Backend 결과 전송·로봇 진행·안전 기능은 없습니다. 자동 저장 및 c/1/2 동작은
비활성화하며 q로 종료합니다. 기존 통합 손 사이클 시험은 실제 hand-config가 필요합니다.

| 파일 | 역할 |
|---|---|
| README.md | 실행·데이터 준비·한계 |
| requirements.txt | 최소 실행 dependency, 전체 호환 버전은 실제 환경 확인 후 고정 |
| config.yaml | 실측 카메라·손·기하 설정; null은 미입력 |
| dataset.yaml | 실제 학습/검증 경로와 네 클래스 |
| contracts.py | 공통 여섯 배치 필드·전체 footprint·anchor 변환 |
| rgbd_io.py | ROS/직접 D435i 수집·원본/정렬 Depth·저장·로딩·V0 스트림 |
| yolo_pipeline.py | 실제 라벨/장면 분할 검사·학습·평가·원본 RGB mask 추론 |
| depth_grid.py | 역투영·Board/Grid/layer 검증·관측 묶음 계산 |
| multiview.py | 동일 배치 중복 제거·충돌 제외·이전 Backend 상태와 유지/변화 비교 |
| backend_adapter.py | Observed 구성·주입 callback 전달 |
| visualization.py | 실제 HSV 검수·mask/Depth 결과 표시 |
| hand_cycle.py | 별도 손 모델·V0 진입/이탈/안정화 관측 게이트 |
| main.py | 실제 명령·정상 관측·안전 V0 복귀 확인 후 새 요청으로 한 번 재관측 |

RGB-D 구현은 `rgbd_io.py`, 다중 시점/이전 상태 비교는 `multiview.py`,
정상/재관측 사이클은 `main.py`로 통합했습니다. 기존 외부 호출 보존을 위해
`ros_capture.py`, `state_tracking.py`, `reobservation.py`는 재수출만 하는
호환 파일로 남습니다. 15개 파일 중 실제 구현은 12개이고 물리적 파일 수는 유지됩니다.
ROS 촬영은 `python3 -m perception_mvp.rgbd_io ...` 또는 기존
`python3 -m perception_mvp.ros_capture ...` 모두 같은 처리입니다.

## 실행 위치와 환경

```bash
cd /home/roh/C-2/perception
python3 -m perception_mvp.main --help
```

촬영에는 pyrealsense2, 학습/손/블록 추론에는 ultralytics, 설정에는 PyYAML이 필요합니다.
2026-10-06 기본 /usr/bin/python3의 사용자 계정 설치 완료:
ultralytics 8.4.173, pyrealsense2 2.58.4.10922, torch 2.14.1+cpu,
torchvision 0.29.1+cpu, OpenCV 4.11.0.86. 기존 NumPy 1.26.4 유지.
관련 import 및 ROS Jazzy cv_bridge import 확인, CUDA build=None 확인.
전체 pip check는 기존 다른 패키지의 9개 의존성 경고로 실패했습니다. 특히
/usr/local의 SciPy 1.18.1은 NumPy>=2.0을 요구하지만 현재 NumPy는 1.26.4입니다.
이번 설치에서 해당 SciPy/NumPy는 변경하지 않았습니다. 실제 학습/추론에 영향을 주는지
확인해야 하며 전체 Python/ROS/장치 환경 호환성이 검증됐다는 뜻은 아닙니다.
사용자 계정 설치는 기존 시스템 OpenCV 파일을 지우지 않지만 기본 import는 새 OpenCV를 우선 사용합니다.
CPU 설치 근거: [PyTorch 공식 설치 안내](https://pytorch.org/get-started/locally/).
모델은 실제 로컬 .pt만 받습니다. 임의 모델 선택/자동 다운로드를 하지 않습니다.

## 데이터 준비·라벨 검사·학습

원본 RGB와 검수한 블록별 instance polygon을 사용합니다. YOLO 클래스는
0 yellow_2x2, 1 yellow_2x3, 2 blue_2x2, 3 blue_2x3입니다. 의자/층/조립 순서를 클래스로 늘리지 않습니다.
dataset.yaml의 path를 실제 절대경로로 입력하고 images/train,val과 labels/train,val을 대응시킵니다.
장면 메타데이터 JSON은 실제 이미지마다 image(데이터셋 상대경로), scene_id,
split(train 또는 val), reviewed(true), empty_confirmed(bool)를 기록한 항목 목록입니다.
검수자는 빈 보드를 실제 확인한 이미지에만 empty_confirmed=true를 기록합니다.
미검수/누락 라벨을 정상 빈 라벨로 처리하지 않습니다. 코드가 사람의 mask 정확성을 보장하지는 않습니다.
같은 조립 장면의 연속 프레임·여러 View는 같은 split입니다. 장면 중복과 동일 이미지 내용의 분할 누출을 검사합니다.

아래 대문자는 실제 파일/학습 설정으로 치환하는 명령 인자이며 예시 데이터가 아닙니다.

```bash
python3 -m perception_mvp.main check-labels --dataset perception_mvp/dataset.yaml --scene-manifest ACTUAL_SCENES_JSON
python3 -m perception_mvp.main train --dataset perception_mvp/dataset.yaml --scene-manifest ACTUAL_SCENES_JSON --weights LOCAL_SEGMENTATION_INIT_PT --device DEVICE --imgsz IMAGE_SIZE --epochs EPOCHS --batch BATCH --output NEW_TRAIN_DIR
python3 -m perception_mvp.main evaluate --dataset perception_mvp/dataset.yaml --scene-manifest ACTUAL_SCENES_JSON --weights TRAINED_BLOCK_PT --device DEVICE --imgsz IMAGE_SIZE --output NEW_EVAL_DIR
```

train은 실제 네 클래스가 모두 있어야 진행합니다. evaluate는 학습과 분리한 실제 val 장면을 사용합니다.
파일/클래스/polygon/최소 점/좌표/빈 라벨 확인 실패는 예외로 보고합니다.
실제 라벨 생성은 사람 담당입니다. 같은 색 접촉은 OpenCV 영역 하나로 합쳐질 수 있으므로 instance를 직접 분리합니다.

## 실제 촬영·색상 확인·추론

```bash
python3 -m perception_mvp.main capture RECORDING_DIR --serial CAMERA_SERIAL --scene-id SCENE_ID --view-id V0 --robot-pose ROBOT_POSE_FILE --calibration-id CALIBRATION_ID --check-id BACKEND_CHECK_ID --observation-seq SEQ --mode REAL --stopped-and-clear --width WIDTH --height HEIGHT --fps FPS --timeout-ms TIMEOUT_MS
python3 -m perception_mvp.main color-check RECORDING_DIR --settings ACTUAL_HSV_SETTINGS --output NEW_COLOR_REVIEW_DIR
python3 -m perception_mvp.main infer --manifest ACTUAL_BUNDLE_JSON --weights TRAINED_BLOCK_PT --calibration MEASURED_CALIBRATION --config perception_mvp/config.yaml --detector-confidence VALIDATED_THRESHOLD --output NEW_RESULT_DIR
```

capture는 담당자의 Robot 정지·사람 이탈 확인을 명시적으로 받는 독립 수집 도구입니다.
이 플래그만으로 자동 손 게이트/안전/조립 완료를 통과했다고 주장하지 않습니다.
RGB/원본 Depth/정렬 Depth는 npy, 보정/시각/pose/촬영 check·순번은 metadata.json으로 저장합니다.
묶음 시작에 고정한 check와 순번을 모든 View에 함께 사용합니다. 증가 범위는 외부 연결부 정책이며 CLI가 임의 결정하지 않습니다.

HSV 설정은 threshold_status(temporary_test/validated), hsv_ranges의 yellow/blue별 lower/upper 세 정수 배열입니다.
H=0..179, S/V=0..255. 실제 조명에서 기준을 정하며 기본 시험값을 넣지 않았습니다.
color-check는 원본·노랑/파랑 mask·비교 이미지와 검수 JSON을 저장합니다. Backend 관측/정답 라벨이 아닙니다.
YOLO에는 OpenCV로 자른 영상이 아닌 원본 RGB를 입력합니다.

ACTUAL_BUNDLE_JSON 필수 항목: mode=REAL, check_id, observation_seq, scene_stable(bool),
target_after(공통 배치), previous_accepted_blocks(실제 Backend 채택 상태), recordings 목록.
각 recording은 directory를 지정하며 상대경로는 manifest 기준입니다.
실제 독립 점유 검증이 있는 경우에만 verified_regions와 verification_basis를 입력합니다.
확인 영역은 보정된 보드의 3D 열과 실제 Depth 광선으로 산출합니다. ROI/검출 0개만으로 빈 보드를 확정하지 않습니다.
RGB ROI는 블록 검출·보드 평면 추출에 사용하며, 측면에서 ROI 밖으로 투영되는
보드 상부 공간까지 자르는 마스크로 사용하지 않습니다. 빈 공간은 보정된 24×24·5층
범위에서만 검사하며 영상 밖으로 잘린 범위, 장애물, 거리 범위 이탈은 미확인으로 유지합니다.
`geometry.empty_min_valid_fraction: 0.99`는 빈 공간 검사에서 0인 Depth를 최대 1%만
허용하는 시험용 품질 기준입니다(미설정 시 100%). 유효값 최소 50개와 모든 유효
광선의 공간 통과 조건은 유지합니다. 결손 복원이나 안전 보장은 아닙니다.
확인 근거가 부족하면 실제 검출 블록을 담더라도 UNOBSERVABLE로 반환합니다.

INITIAL은 사용자 지정 기준으로 미확인 보드 열 최대60개까지 허용하고 61개부터 보류합니다.
한 층이라도 미확인이면 해당 (x,y) 열 전체를 미확인1칸으로 셉니다(전체576칸).
미확인 칸은 빈 공간으로 확정하지 않으며, B는 그 칸에 걸치는 Plan 로드와 Step 시작을
`PLAN_REGION_UNVERIFIED`로 거부합니다. 해당 범위를 실제 확인하는 추가 INITIAL 후
계획을 다시 전달해야 합니다. STEP·FINAL 비교 기준과 로봇의 정지 조건은 변경하지 않습니다.

calibration은 calibration_id와 V0/D1~D4별 Camera→Board rigid 4x4 views 행렬(translation m)입니다.
config.geometry는 실측 stud pitch/footprint/상면 1~5층 높이/중심 lattice/anchor 차이/허용 오차를 받습니다.

2026-10-11 층 범위를 1~5로 확장했습니다. 기존 4개 높이 보정값은 그대로 사용할 수 있으나
5층 판정 및 5층 Current/Expected 투영에는 동일 보드 기준의 다섯 번째 실측 높이가 필요합니다.
평균 증가량으로 5층 실측값을 자동 생성하지 않습니다. 보정 누락은 미확인/투영 숨김으로 처리합니다.
null은 미보정 상태이며 실패합니다. identity나 임의 좌표를 기본 적용하지 않습니다.
none은 pinhole, brown_conrady/inverse_brown_conrady는 실제 coefficients로 SDK 역투영을 사용합니다.
그 외 왜곡 모델은 명시적 오류입니다. SDK 경로·처리 시간·실측 정확도는 미검증입니다.
결과: observed.json, diagnostics.json, View별 실제 mask/측정 후보/UNKNOWN 이미지. 기존 결과 폴더는 덮어쓰지 않습니다.

## V0 손 진입·이탈과 관측 사이클

```bash
python3 -m perception_mvp.main watch-hand --config perception_mvp/config.yaml --check-id BACKEND_CHECK_ID --output NEW_HAND_EVENT_JSONL --at-stopped-v0
```

사용자는 실제 검증한 별도 detect 모델(.pt, hand 클래스)과 V0 board ROI를 입력합니다.
손 모델 선정/학습은 아직 미제공이며 블록 네 클래스/피부색을 손 모델 대신 사용하지 않습니다.
WAIT_ENTRY → HAND_PRESENT → WAIT_EXIT_STABLE → READY 순서입니다.
손 진입 선확인, 연속 ABSENT **3초 초과**, 별도로 실측한 영상 안정 지속 시간을 모두 만족해야 READY입니다.
UNKNOWN·긴 프레임 간격·재진입은 이탈 대기를 초기화합니다. 이미 READY/OBSERVING이면 결과 확정 권한을 취소합니다.
손 검출 누락의 실제 성능은 시험이 필요하며 영상 안정/Depth 품질이 물리 안전을 보장하지 않습니다.
모니터는 상태 변화 JSONL만 기록하고 종료 시 HOLD를 남깁니다. Robot·다음 블록 전달을 호출하지 않습니다.

통합 함수 `main.observe_cycle(gate, capture_view, manifest, weights, calibration,
config, detector_confidence, callback=..., confirm_view=..., bundle_valid=..., view_sink=...)`는
정상 및 재관측의 한 묶음을 처리합니다. 기존 collect_recordings 일괄 수집 API는 이 함수에서 교체했습니다.
manifest의 `view_order`는 최신 사용자 조건에 따라 **["V0", "D1", "D3"]**로 고정합니다.
묶음 시작 시 문맥/이전 Current/보정/설정을 복사하고 각 View를 촬영한 즉시 YOLO·Depth/Grid로
검증합니다. view_sink는 각 View 측정·부분 통합·이전 상태 비교 결과를 내부 기록/표시로 받습니다.
마지막에만 통합 Observed callback을 호출하며 V0 복귀·다음 Step 진행은 요청하지 않습니다.
confirm_view(view_id)는 실제 이동 완료·정지·안전·영상 안정 확인 후에만 True를 반환해야 합니다.
capture_view(view_id)는 실제 한 View를 저장하고 directory, 필요 시 verified_regions와 실제
verification_basis를 반환합니다. 이 Python 연결점은 미합의 D 통신/JSON Schema가 아닙니다.
bundle_valid()는 활성 check·STOP/오류·장면 유지·재진입 정책을 실제로 확인해야 하며
고정 True 함수로 대체하지 않습니다. 실패하면 HOLD로 중단하고 예외를 연결부에 전달합니다.
V0 처리 직후 신선한 V0 게이트를 종료하고, 대각점에서는 별도 bundle_valid 확인을 요구합니다.
카메라 1대가 V0를 떠나는 다중 View 동안 동일 V0 감지가 가능한 것으로 가정하지 않습니다.
View별 손 감지 ROI/안전·연속 감시 방법은 Controller와 실제 구성 확인이 필요합니다.
watch-hand CLI와 infer CLI만 따로 실행했다고 자동 관측 사이클이 연결되었다고 기록하지 않습니다.
독립 infer는 실제 저장 데이터 계산 검증용이며 라이브 손 게이트/Robot 안전 승인을 대신하지 않습니다.

### 보류 후 수정·재관측 (2026-10-07)

`main.reobserve_once`는 Backend가 수정 또는 관측 조건 개선을 요청한 뒤 호출하는
공통 B 진입 함수입니다. View별 복제나 자동 재시도 루프는 없습니다. 한 View가 부족해도
`observe_cycle`은 남은 View를 진행하고, 최종 통합 결과를 Backend에 전달합니다.
Expected와 다르다는 이유로 B가 실제 블록을 제외하거나 완료/다음 전달을 결정하지 않습니다.

연결부가 제공해야 하는 내부 함수는 다음과 같습니다. 이는 공통 통신 필드의 확정이 아닙니다.

| 연결 함수 | 필수 의미 |
|---|---|
| `close_check(previous_check_id)` | Backend가 이전 요청을 종료하고 다음 전달을 보류했으면 True |
| `return_to_v0()` | Controller가 검증된 경로로 안전 복귀를 완료하면 True. V0에서는 호출하지 않음 |
| `confirm_view(view_id)` | 실제 정지·안전·영상 안정 확인 |
| `workflow_valid()` | STOP·로봇 오류·전달판 등 별도 보류가 없어 수정 흐름을 진행할 수 있는지 |
| `reset_hand_detector()` | 실제 HandDetector.reset을 연결해 이전 안정화 영상 초기화 |
| `wait_for_hand(gate)` | V0 실시간 프레임으로 새 손 진입→연속 이탈 >3초→안정화 확인. READY를 임의로 설정하지 않음 |
| `request_context()` | 손 조건 확인 후 Backend가 새 check와 최신 Current/Expected·유효 Step/Plan의 manifest 제공 |
| `bundle_valid()` | 새 활성 check·버전·장면 연속성·중단 상태 확인, 닫힌 요청 결과 거부 |
| `notice(event)` | WAIT_SAFE_V0 / WAIT_HUMAN_CORRECTION / REOBSERVING / WAIT_BACKEND_REVALIDATION / HOLD 표시 |

`hold_kind`는 Backend가 분류해 주는 내부 제안 값 ACTUAL_PLACEMENT 또는
OBSERVATION_CONDITIONS입니다. 필요한 위치·색상·방향·층/조건 개선 안내는 Backend의
reason과 HMI 연결부가 제공해야 합니다. STOP·로봇 오류·전달판 점유를 사람 재조립으로 처리하지 않습니다.
V0 복귀·정지 확인 전에 human_correction_allowed=true를 보내지 않습니다.

기존 check 재사용은 거부합니다. 순번은 Backend 제공 정책을 유지하며 B가 임의로 발급하거나
초기화하지 않습니다. 재관측은 항상 V0→D1→D3 한 번이며 최종 판별 불가도 그대로 반환합니다.
Current/Expected 갱신·완료·재계획·다음 전달은 Backend 책임입니다. 최신 오버레이 snapshot은
새 request_context에 맞춰 표시 연결부가 다시 freeze_overlay_states로 생성하고 묶음 중 고정해야 합니다.
예외는 HOLD로 전파하고 재호출은 외부 판단을 기다립니다. Observed 여섯 필드는 변경하지 않습니다.

실제 프레임 소비에는 `hand_cycle.wait_for_hand_ready(stream, detector, gate, workflow_valid,
frame_sink=...)`를 wait_for_hand 연결점에서 사용합니다. STOP/오류를 프레임마다 확인하고
정상 READY 또는 중단 시 스트림을 닫습니다. reset_hand_detector에는 detector.reset을 연결합니다.
카메라 재개/촬영 전환·스트림 소유권은 실제 연결부에서 확인해야 합니다.

이번 변경은 B 함수와 단위 검사만입니다. 실제 D Backend check/Controller 이동/Qt 표시와의
adapter 연결 및 실제 장치 안전·손 검출·복귀 시험은 아직 수행하지 않았습니다.

## 상태 오버레이·동일 View 차분 (2026-10-06)

`visualization.freeze_overlay_states(current_blocks, expected_blocks, version_context)`에
Backend가 제공한 이번 묶음 직전 Current와 **현재 Step 완료 후 Expected**를 넣어 복사합니다.
None은 미수신이며 빈 목록으로 바꾸지 않습니다. 이 snapshot을 한 묶음 내내 재사용합니다.
`render_state_overlay(rgb, snapshot, projection, stopped=..., projection_valid=...)`는
실제 RGB 위에 Current(분홍)/Expected(초록)를 반투명으로 함께 표시하고 새 목표는 굵게 표시합니다.
2026-10-10 수정: 윗면뿐 아니라 층 높이를 가진 입체의 옆면까지 투영합니다.
기본 투명도는 alpha=0.15이며, 동일 Current/Expected 배치는 분홍색으로 한 번만 그립니다.
면은 카메라 깊이 순서로 합성하고 뒤를 향한 면은 그리지 않습니다.
projection은 실제 camera_to_board, rgb_intrinsics, grid_origin_m(0번 stud 중심),
stud_pitch_m, top_heights_m을 메모리로 받습니다. 그림은 stud 점유 영역 안내이며 실물 경계 추정이 아닙니다.
첫 층 입체는 보드 기준 0에서 시작하고 이후 층은 이전 높이 기준으로 이어집니다.
선택 입력 stud_height_m이 있으면 스터드도 표시합니다(없으면 입체 몸체만 표시).
스터드 반경은 표시용 도식이며 실측 경계가 아닙니다. 실측 높이는 표시 연결부에서 전달합니다.
View/현재 pose/보정/해상도의 유효성은 표시 연결부가 확인해야 합니다. 이동·미수신·미보정·잘못된
투영은 오버레이를 숨기고 사유를 반환합니다. 투영용 임의 값이나 추가 JSON 파일은 생성하지 않습니다.
손 모니터의 frame_sink(rgb, depth, event, quality)는 조립 대기 중에도 매 프레임 표시를 연결할 수 있습니다.
실제 Qt/HMI 프레임 전송·각 관측점 live stream 연결·동시성은 D/HMI 합의 후 연결할 미완료 작업입니다.

`aligned_change_mask`는 같은 View의 이전/현재 실제 RGB와 검증된 정렬 homography,
실측 픽셀 임계값을 입력받고 정렬 유효 영역 내 변화 mask만 반환합니다. 다른 View/미확인 정렬은 거절합니다.
자동 정렬·완료 판정·verified_regions 산출에 사용하지 않습니다. 오버레이와 차분은 관측 근거가 아닙니다.
투영/정렬 수식 근거: [OpenCV projection](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html),
[OpenCV geometric transforms](https://docs.opencv.org/4.x/da/d54/group__imgproc__transform.html).
초기 보드 확인·STOP 재개·보류 재확인은 정상 손 진입 사이클과 별도 정책/연결이 필요합니다.

## 책임·계약·미완료

### 새 B 상태 관리 실행 기능 — 2026-10-08, 통신 명세 대기

사용자 요청으로 `inspection.VisionInspection`과 `main.inspect_cycle`을 추가했습니다.
이는 **기존 Day4 wire 계약을 교체하지 않는 내부 Python 실행 경로**입니다. 기존
`observe_cycle`/`infer`의 Observed callback은 유지되며 새 결과를 기존 D 수신부에
그대로 보내면 안 됩니다. 팀장 최종 Schema/Fixture에 맞춘 어댑터는 별도 연결입니다.

- `VisionInspection(current)`는 인계받은 실제 Current/revision으로 시작합니다. 예상
  모델에서 Current를 생성하거나 재시작 때 임의 초기화하지 않습니다. 한 인스턴스는
  한 Job에만 사용하고 Plan/요청/취소/확정 호출을 직렬화합니다.
- `load_plan(design, plan, base_current, geometry_reference=...)`는 기존 팀의 PLACE-only
  Plan을 검사해 기준 Current + 실제 배열 순서의 Step 효과로 예상 모델을 만듭니다.
  최종 효과와 승인 Design이 다르면 거부합니다. 층순으로 재정렬하거나 오배치를
  Expected에 반영하지 않습니다. 새 Plan은 B Current와 동일한 기준 revision/배치와
  새 plan_id가 필요하며 성공적으로 채택하면 이전 활성 검사를 취소합니다.
- `start(check_id, plan_id, step_id, geometry_reference=...)`는 D가 지정한 모델만
  선택합니다. 모델·기하 참조 누락/불일치와 이미 사용한 check를 거부하며 자동으로
  다음 Step을 선택하지 않습니다. `final_model`/`current`는 외부 수정이 불가능한 복사본입니다.
- `finish(observed, plan_id=..., step_id=..., geometry_reference=..., issues=...)`는 실제
  확인한 변경만 Current에 반영하고 배치가 바뀔 때만 revision을 증가시킵니다.
  가린 기록·이번 확인 블록·실제 확인 영역·미확인 영역·확인된 차이를 구분합니다.
  전체 검사를 통해 확인된 차이가 있으면 MISMATCH를 반환하면서 미확인도 보존합니다.
  이동의 물리적 동일성은 추정하지 않고 확인된 제거/추가를 반환합니다.
- `cancel(check_id)` 이후의 결과, 새 계획 이후 옛 결과, 중복 결과는 Current를
  변경하지 않습니다. 잘못된 요청·촬영 실패는 예외로 실패 경로에 전달해야 하며
  정상/빈 결과로 바꾸지 않습니다.

실제 촬영 연결은 기존 `observe_cycle`과 동일한 capture/정지/손 게이트를 사용하는
`inspect_cycle(session, gate, capture_view, manifest, weights, calibration, config,
detector_confidence, confirm_view=..., bundle_valid=..., view_sink=...)`입니다.
기존 내부 manifest에 `plan_id`, `step_id`, `geometry_reference`를 지정합니다.
검사 시작 시 B Current와 해당 Step 목표를 고정하고, 모든 View 종료 후 활성 요청을
재확인해 B Current 확정·전체 비교 결과를 반환합니다. 외부 D 전송은 호출하지 않습니다.

기하 참조 문자열은 내부 식별자일 뿐 실제 보정 검증을 대신하지 않습니다. 호출자는
실측 약 16mm 프로필·층별 기준·최신 V0/D1/D3 보정과 적용 config가 해당 참조에 맞는지
확인해야 합니다. 자유 시작점 이동은 승인된 Design/Plan에 이미 한 번 적용된 보드
좌표로 입력해야 합니다. 공통 모델 입력의 최종 봉투·프로필 참조 해석·revision 초기
인계/저장·취소 transport·PLACE/CURRENT 목적 경로는 팀장 명세 후 실제 D와 연결해야 합니다.

재현 검사: 프로젝트 루트와 perception/legacy 경로를 포함한 PYTHONPATH에서
`python3 -m pytest perception/perception_mvp/tests/test_inspection.py -q`.
시험 입력은 합성 배치이며 실제 Camera/Robot 성능·안전·신규 D 통합 증거가 아닙니다.

아래 기존 책임 설명은 **legacy Observed 경로**에 한정합니다. 새 내부 검사 경로에서는
B가 Current/revision과 Expected 비교를 수행하고 D는 공정 진행을 결정합니다.

Vision은 실제 Board 좌표를 반환하고 Backend만 Current 채택·Expected 비교·완료/다음 전달을 결정합니다.
가린 기존 아래층은 목록 누락만으로 삭제하지 않습니다. mismatch도 실제 관측을 그대로 반환합니다.
전체 footprint가 X/Y 0..23, layer 1..5를 만족해야 하며 임의 clipping은 하지 않습니다.
첫 블록을 기준으로 한 평행 이동은 `assembly_anchor.AssemblyAnchor`로 구현했습니다.
호출자는 전체 최종 Design과 명시적으로 대응시킨 기준 블록 index, 실제 확인한 첫 블록을
`from_first_block`에 전달하고, 반환된 기준점을 Job 동안 유지해야 합니다. 전체 목표의
footprint가 보드 밖이면 ValueError이며 잘라내거나 기준점을 자동 변경하지 않습니다.
`translate_design`은 원래 Design 좌표에 한 번만 적용합니다. Backend에서 이미 이동시킨
Expected에는 다시 적용하지 않습니다. `relative_observation`은 고정 첫 배치 기준의 내부
상대 좌표이며 음수도 허용합니다. 공통 Observed/Current는 실제 보드 좌표 그대로 유지합니다.
오버레이에 원래 Design 좌표를 줄 때만 `freeze_overlay_states(..., assembly_anchor=anchor)`를
사용합니다. 실제 Current는 이동하지 않고, 목표만 이동해 같은 카메라 화면에 투영됩니다.
실제 첫 블록 승인·Job별 기준점 보관·A/C/D 목표/Plan 갱신·HMI 연결은 아직 미연결입니다.
전체 목표 회전과 전용 HMI는 별도 협의 대상입니다.
2x2 대표 방향 0으로 전체 구조 방향을 추정하지 않습니다. 목표 이동/전체 조립 가능성은 Backend/Planner 책임입니다.
Observed 공통 여섯 필드는 유지합니다. 진단·전달판 별도 수신 경로/after=null 판단은 미합의·미구현입니다.
coverage 자동 산출·근접 좌표 동일 블록 연결·실제 D 수신부·Robot/View 이동 연결도 아직 별도 검증/구현이 필요합니다.

## 이번 검증과 다음 입력

빈 보드 실제 저장 데이터 진단 명령은 `python3 -m perception_mvp.empty_board_depth`입니다.
세 View의 측정 결과와 재실행 방법은 [Depth 기준 측정 기록](../recordings/empty_board_depth/DEPTH_BASELINE_REVIEW.md)을 확인합니다.
RGB 보정 기준과 Depth 높이 차이 및 D1 누락·이상값이 있어 높이 검증 통과로 표시하지 않았습니다.

2026-10-07 보류·재관측 변경 후 관련 테스트와 legacy 회귀 테스트를 실행해 99개가 통과했습니다.
검사 명령: `PYTHONPATH=/home/roh/C-2/perception:/home/roh/C-2/perception/legacy python3 -m pytest -q perception/perception_mvp/tests perception/legacy/tests` (C-2에서 실행).
상태 전환·실패 경로 검사는 합성 입력과 대체 연결 함수를 사용한 단위 검사입니다.
실제 인식/학습/카메라·Robot·Backend·HMI 통합 시험 PASS를 뜻하지 않습니다.
변경 Python 파일의 문법 검사도 통과했습니다. 저장소의 `docs/STATUS.md`가 삭제된 상태여서 복원하거나 수정하지 않았습니다.
필요 입력: 실제 RGB-D, 사람 검수 라벨/장면 목록, 블록·별도 손 모델, 실측 camera/geometry 설정, D/Controller 연결 함수.

API 근거: [Ultralytics segmentation](https://docs.ultralytics.com/tasks/segment/),
[학습](https://docs.ultralytics.com/modes/train/), [polygon 형식](https://docs.ultralytics.com/datasets/segment/),
[RealSense SDK 역투영](https://github.com/realsenseai/librealsense/blob/master/include/librealsense2/rsutil.h).
## 실행 중인 ROS 카메라에서 RGB-D 저장 (rosbag 없이)

Robot이 실제 정지하고 손을 치운 뒤 실행합니다. RealSense ROS 노드/rqt는 켜둡니다.
이 명령은 Robot을 움직이거나 카메라 SDK를 다시 열지 않고 ROS 토픽만 구독합니다.

```bash
source /opt/ros/jazzy/setup.bash
cd /home/roh/C-2/perception
python3 -m perception_mvp.ros_capture --view V0 --output recordings/assembly_01/step_00_empty/V0 --stopped-and-clear
```

실행 한 번에 한 세트를 저장하고 종료합니다. 지정 폴더 아래 UTC 시각 하위 폴더에
rgb.png/rgb.npy, depth_raw.png/depth_raw.npy, depth_aligned.png/depth_aligned.npy,
metadata.json을 저장합니다. Depth PNG는 회색 화면 캡처가 아닌 16-bit 거리값입니다.
V0/D 관측점·조립 단계가 바뀌면 view와 output을 해당 실제 단계로 변경합니다.
raw는 /camera/depth/image_rect_raw, aligned는 /camera/aligned_depth_to_color/image_raw,
RGB는 /camera/color/image_raw 및 각각 camera_info를 사용합니다. 토픽 이름이 다르면
--help의 topic 옵션으로 실제 이름을 지정합니다. 미수신/동기 불가/전체 zero Depth는 실패입니다.
동기 허용 50ms는 임시 수집 시험값이며 실제 프레임 시각 차이를 metadata에 기록합니다.
RealSense ROS의 16UC1 mm 단위만 지원합니다. 드라이버 필터 적용 여부는 별도 확인 필요입니다.
근거: [RealSense ROS Depth 단위](https://github.com/IntelRealSense/realsense-ros/issues/41).

pose/Board 보정 없이 촬영할 수 있지만, 이 저장 형식은 ros_rgbd_capture_v1/CAPTURE_ONLY입니다.
기존 strict load_frame/local_test measure에 곧바로 넣을 수 없습니다. 실제 pose/보정 문맥과
ROS CameraInfo 변환을 연결하기 전에는 Grid/층 검증용으로 사용했다고 표시하지 않습니다.
RGB PNG는 실제 라벨링/학습에 사용 가능합니다. 이 단독 수집은 자동 관측 Cycle/Backend 전달이 아닙니다.
수동 라벨링 기능이 추가되었습니다. 실제 RGB 준비 → polygon 작성 → YOLO 변환·기존 검사
연결 방법은 [라벨링 작업 순서](../LABELING.md)를 따릅니다. 자동 정답 생성 기능이 아닙니다.
