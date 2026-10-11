# 진행 기록

## 2026-10-06 — 실행 중 ROS RGB·원본 Depth 파일 저장

- 사용자 요청으로 ros_capture.py 추가. 기존 실제 ROS RGB/raw Depth/aligned Depth와
  각각 camera_info를 구독해 한 세트 PNG/NPY/metadata로 저장. rosbag/SDK 재점유/pose 파일 불필요.
  Robot 정지·손 이탈은 사용자가 실제 확인. Robot 이동/자동 안전 판단/Backend 호출 없음.
- 원본 16UC1 값·패딩·엔디언 보존, RGB BGR 변환, 시각 근접 매칭(50ms 임시값),
  image/info 크기·frame 확인. raw와 aligned 별도 저장. 미수신·전체 zero·불일치 명시적 실패.
- ros_rgbd_capture_v1 CAPTURE_ONLY이며 pose/Board 보정 미수신을 null/한계로 기록.
  strict 기존 로더와 바로 호환된다고 주장하지 않음. 후속 실제 pose/보정/CameraInfo 연결 필요.
- 실제 검증: ROS Jazzy source 후 CLI 도움말·rclpy/Image/CameraInfo/모듈 import,
  compileall 종료 코드 0. 신규 실제 프레임 저장/Depth 수치 보존 실행은 미검증.
  합성 데이터/모델/시험 코드 추가 없음. 새 dependency 설치/C-2 변경 없음.

## 2026-10-06 — 관측점별 즉시 처리·상태 오버레이 요구 반영

- main.observe_cycle을 한 View 수집→즉시 YOLO/Depth/Grid→부분 통합/이전 상태 비교→
  다음 View 순서로 변경. V0와 반대 대각 두 점만 허용하며 순서/경로는 외부 선택.
  최종 통합 Observed 여섯 필드 유지, V0 복귀/다음 Step/Current 채택은 수행하지 않음.
- V0 처리 후 신선한 손 게이트를 종료. 이후 V0 감지를 계속한다고 가정하지 않고
  실제 Controller/연결부의 bundle_valid에 장면 유지·STOP·재진입 정책 확인을 요구.
  confirm_view는 실제 정지·안전·영상 안정 확인 연결점. 실패는 HOLD/예외 전달, 자동 복구 없음.
- visualization: Backend Current/현재 Step Expected snapshot 복사, 실제 RGB+보정으로
  반투명 점유 영역/범례/추가 목표 표시, 이동·미수신·잘못된 투영 숨김/사유 반환.
  동일 View 실제 RGB·외부 검증 정렬 homography의 차분 보조 함수 추가.
  monitor_hand frame_sink로 조립 대기 중 매 프레임 표시 연결 가능.
- 변경 5개(main, hand_cycle, visualization, README, 이 기록). 새 dependency/class/파일 없음.
  observe_cycle Python API 변경: collect_recordings 대신 capture_view와 confirm_view,
  bundle_valid 필요. 작업 폴더 내 호출자 없음 확인. D 통신/화면 DTO는 미확정 상태 유지.
- 실제 검사: 기존 runtime/visualization/observation pytest 42 passed, 종료 코드 0;
  compileall, AST/import/미수신 상태 보존, main 도움말, local preflight 종료 코드 0.
  기존 합성 L1은 회귀 확인일 뿐 신규 기능/실제 센서/안전 통과 증거가 아님.
  새 합성 데이터·모델·예시/테스트 코드 생성 없음.
- 미검증: 새 순차 사이클 정상/중단 실제 실행, 투영/차분 정확도, Camera/Robot/Backend/HMI L2~L4.
  실제 RGB-D/모델/보정 파일이 작업 폴더에서 발견되지 않아 신규 계산 성능 시험 불가.
  실제 live 표시·D 함수 연결·동시성 및 비V0 재진입 안전 정책은 미완료.
  초기 빈 보드/STOP 재개/보류 재확인 정책은 정상 사이클과 별도 합의 필요.
- C-2 파일 수정·Robot 이동·통신/PR 게시 없음. 다음은 실제 D 연결 함수/보정/상태 입력
  확인 후 장치 없는 계약 검사와 Camera 표시 시험, 안전 승인 후 실제 사이클 순서로 검증.

## 2026-10-06 — 기본 Python 사용자 설치·CPU 실행

- 사용자 최신 요청으로 가상환경 설치를 중단하고 /usr/bin/python3에서 사용하는
  /home/roh/.local/lib/python3.12/site-packages에 CPU용 패키지를 설치.
  명시적 사용자 승인으로 pip --user --break-system-packages 사용, 시스템 파일은 덮어쓰지 않음.
- torch 2.14.1+cpu, torchvision 0.29.1+cpu, ultralytics 8.4.173,
  pyrealsense2 2.58.4.10922, opencv-python 4.11.0.86 설치 완료. NumPy 1.26.4 유지.
  블록/손 predict에 CPU 명시, main train/evaluate 기본 장치 cpu.
- 실제 검증: CPU torch/CUDA build=None, YOLO/RealSense/torchvision/OpenCV/NumPy import 종료 코드 0.
  ROS Jazzy source 후 cv_bridge import 종료 코드 0, local_test preflight 다섯 패키지 모두 true.
- 전체 pip check는 종료 코드 1: openwakeword/tflite-runtime, types-seaborn/pandas-stubs,
  tables/blosc2, types-flask-migrate/flask-sqlalchemy, types-python-datemath/arrow,
  types-jsonschema/referencing 누락 및 SciPy/NumPy, types-seaborn/matplotlib,
  dask/importlib-metadata 버전 불일치. 자동으로 관련 없는 전체 패키지를 고치지 않음.
  기존 /usr/local SciPy 1.18.1과 NumPy 1.26.4 불일치는 실제 모델 시험에서 영향 확인 필요.
- requirements에 직접 사용 버전과 공식 CPU wheel index 기록, README 기본 Python 실행으로 갱신.
- 미검증: 실제 모델 학습/추론, 카메라 스트림/SDK 보정, ROS 전체/Robot/Backend 통합.
  이전 .venv는 보존하되 사용하지 않음. GPU/driver 변경·가짜 입력/모델 생성·C-2 수정 없음.

## 2026-10-06 — 실제 입력 단독 시험 도구

- 신규 perception_mvp/local_test.py: preflight/devices/capture/check-recording/infer-rgb/
  measure/watch-hand. HMI/check/순번/목표 없이 실제 수집·모델·측정·추적 시험.
- 실제 수집/YOLO/Depth/Grid/시각화/추적 함수를 재사용. multiview는 식별 검사와
  병합 계산을 분리하여 local/Backend 경로가 동일 알고리즘 사용, 통합 ID 검사 유지.
  hand_cycle.monitor_hand로 실제 감지 로그 공통화, main의 통합 문맥 유지.
- 로컬 capture는 식별 문맥을 생략하고 실제 RGB-D+pose 기록. 보정 ID 없어도 수집 가능,
  보정 전 infer-rgb 가능. Board 측정에는 실제 보정이 필수. LOCAL_ONLY 결과만 저장.
- 기존 운영 14개 파일 + 별도 단독 시험 도구 1개, README 실행/한계 설명 보완.
  예시/가짜 ID/가짜 모델/합성 데이터·테스트는 추가하거나 실행하지 않음.
- 실제 검증: 관련 compileall/import 및 단독 7개 명령 도움말 종료 코드 0;
  실제 환경 preflight에서 numpy/cv2/yaml 설치, ultralytics/pyrealsense2 미설치 확인.
  미입력 camera 설정의 capture가 ValueError/종료 코드 1로 중단됨 확인.
- 미검증: 실제 장치 촬영/SDK profile 목록/모델 mask/측정·통합·추적·손 감지 성능.
  필요한 실데이터/패키지/모델/pose/보정이 없으므로 PASS로 표시하지 않음.
- C-2 수정·설치·Robot 이동·Backend 전달·GitHub 게시 없음. 다음: 현장 환경에서
  devices 확인→실제 config/pose 입력→단독 capture/check-recording→모델/보정별 시험.

## 2026-10-06 — 누적 설계 조건·실제 처리 패키지 통합

- 운영 14개: README, requirements, config, dataset, contracts, rgbd_io,
  yolo_pipeline, depth_grid, multiview, state_tracking, backend_adapter,
  visualization, hand_cycle, main. 패키지 내부에 수집/저장/로딩과 저장 계산을 통합.
  기존 루트 구현·예시·데모·합성 시험은 삭제하지 않고 보존, 신규 운영 import에서 제외.
- 실제 라벨·장면 provenance·빈 라벨 사람 확인·polygon/클래스·분할 누출 검사;
  로컬 segmentation .pt로 train/evaluate/infer 명령. 원본 RGB를 사용하며 자동 다운로드 없음.
- 별도 hand 모델로 V0 ROI 관측, 손 선진입→연속 이탈 3초 초과→실측 영상 안정 조건.
  UNKNOWN/프레임 간격/재진입 시 HOLD. 관측 게이트 중단/오래된 입력은 최종 callback 차단.
  손 이탈은 완료·다음 전달 승인 아님. 자유 시작점/목표 이동/회전/HMI는 제안 유지.
- RealSense brown/inverse_brown 역투영 SDK 경로와 실제 mask/측정/UNKNOWN 시각화 추가.
  SDK·hand/YOLO 패키지는 lazy import. 보정 identity나 임의 HSV/좌표/모델 기본값 없음.
- 실제 검증: 문법/패키지 import/CLI 도움말 검사. dataset.path=null 및
  미입력 hand/camera 설정에서 명시적 ValueError/종료 코드 1 확인.
  새 합성 데이터/가짜 검출/시험 파일은 생성하거나 실행하지 않음.
- BLOCKER: 실제 RGB-D·라벨·장면 기록·블록/손 모델·실측값 미제공,
  ultralytics/pyrealsense2 미설치. 실제 학습/추론/손 감지/SDK·장치 시험 미수행.
- REQUIRED CHANGE: 실제 입력과 별도 손 모델 선정, Controller의 View 이동/정지/연속 감시 연결,
  verified_regions 자동 증거 모듈·전달판/after=null·실제 D callback/진단 수신 합의 및 연결.
  1대 카메라가 V0를 떠날 때 V0 손 감지를 계속한다고 가정하지 않음.
- AFFECTED INTERFACE: Observed 여섯 필드 유지, 내부 YAML/scene manifest/게이트 API 추가.
  REASON: 요청서의 실제 학습 도구 누락 보완 및 최신 손 관측 사이클 반영.
- 1,000줄 이상 통합/신규 변경으로 사람 리뷰 필요. PyYAML은 로컬 기존 패키지,
  새 framework/DB/Robot motion·의존성 설치·C-2 변경·외부 게시 없음.

## 2026-10-06 — 추가 설계 조건·OpenCV 색상 검수 단계

- 신규 perception_mvp/visualization.py, tests/test_visualization.py;
  main.py에 저장 RGB-D color-check CLI 추가, README에 설계 책임/합의 전 제안/데이터 순서 반영.
- HSV 설정은 명시적 입력, 원본/두 색상 mask/비교 이미지와 진단 JSON 저장.
  색상 마스크로 원본 YOLO 입력을 자르지 않음. instance·종류·층·정답 라벨은 자동 확정하지 않음.
- 자유 시작점·전체 목표 이동/회전·전용 HMI는 팀 합의 전 제안으로 유지.
  Vision Board 좌표/Observed 계약 유지, 목표 변경·시작점 자동 채택·Robot 동작 없음.
- 실제 검사: 전체 pytest 71 passed in 0.81s (최초 구현 검사).
  추가 경계 검사 후 전체 73 passed in 0.70s, compileall/color-check --help 종료 코드 0.
  순수 합성 RGB 색상/입력 오류/원본 보존/저장 CLI 검사이며 실제 조명/Camera 성능 검증은 아님.
- 실제 HSV 실측값·사람 검수 라벨·YOLO 학습/평가 도구/데이터·Camera 및 Backend 연결은 별도 진행.
  예시/데모/사용자 원자료 보존. 신규 dependency·패키지 설치·C-2 수정 없음.

## 2026-10-06 — 실제 촬영·저장 RGB-D 실행 진입점

- 신규 perception_mvp/main.py, tests/test_runtime.py; capture_rgbd.py의 선택적
  촬영 문맥과 perception_mvp/README.md 수정. 예시·데모는 운영 import에서 제외, 삭제하지 않음.
- capture: 명시적 REAL·외부 정지/이탈 확인·check/순번/보정 식별을 원본 RGB-D와 저장.
  infer: 촬영 문맥 검사→실제 infer_masks→기존 Depth/Grid/View/추적→Observed/diagnostics 파일.
  주입 callback에는 공통 Observed만 전달, Current 채택은 하지 않음.
- 실제 검사: 관련 pytest 49 passed in 1.23s, 종료 코드 0.
  최종 전체 pytest 63 passed in 0.63s, compileall 및 capture/infer --help 종료 코드 0.
  합성 센서 배열+YOLO 대역으로 계산 연결·식별 오류·coverage 부족·모델 누락·callback 실패·CLI 출력 검사.
  이 기록은 실제 카메라·학습 모델·Backend 통합 통과가 아님.
- BLOCKER: 현재 Python에서 ultralytics/pyrealsense2 미설치. 로컬 학습 weights/실측 config 미제공.
  aligned 왜곡 모델 none 이외는 미지원, coverage 자동 산출 및 전달판 판단/after=null 미구현.
- REQUIRED CHANGE: 모델/보정/SDK 확보, 실제 camera_info 확인 후 필요 왜곡 처리,
  실제 확인 영역 근거 모듈과 D 진단·전달판 수신 계약 연결.
- AFFECTED INTERFACE: 기존 Observed 여섯 필드 유지. capture의 추가 문맥은 로컬 기록 메타데이터.
  신규 CLI manifest는 내부 입력, 공통 Schema로 주장하지 않음.
- C-2 수정·패키지 설치·장치 접근·Robot 동작·GitHub 게시 없음.

## 2026-10-06 — 실제 Perception 연결 계산 단위

- 신규: perception_mvp/contracts.py, multiview.py, state_tracking.py,
  backend_adapter.py, tests/test_observation.py. 기존 depth_grid.py, saved_perception.py,
  tests/test_rgbd.py 및 두 README 수정. callback 예시/Fixture는 보존.
- 저장 RGB-D 측정→실측 center/anchor 변환→정규화 배치→View 통합→이전 채택 상태 비교→Observed 연결.
  네 클래스 번호/이름 일치 검사, 검출 0개여도 보정 검증, 공통 2x3 각도 변환 반영.
- 최초 시험에서 empty/occupied View 충돌 재현: 1 failed, 18 passed.
  확인 영역을 무효화하는 처리 수정 후 해당 실패 포함 전체 재검증.
- 이번 실제 검증: 전체 pytest **50 passed in 1.04s**, 종료 코드 0.
  여섯 수정/신규 실행 코드 py_compile 및 기존 저장 추론 CLI --help 종료 코드 0.
- 신규 파일 356줄 + 기존 연결/시험/문서 변경: 사람 리뷰 대상.
  새로운 framework/dependency/class 없음. 입력 검증·View 통합·상태 비교·전달은 독립 책임으로 분리.
- 미검증/미구현: 실제 YOLO/D435i/실측/Backend 소비·HMI,
  영상에서 verified_regions 자동 산출, 근접 좌표 연결·실제 촬영 순번/장면 안정 신호,
  학습·라벨 검사 도구. 보정·확인 영역·scene_stable을 추정하지 않음.
- 다음: YOLO 학습/라벨 검사 도구와 실제 샘플 확보; 검증한 coverage 입력·카메라/Backend 연결.
  C-2 파일·Git, Robot, 외부 게시·메시지 변경 없음.

## 2026-10-06 — 오전 B 제출 패키지

- CAPTURE_CONDITIONS.md, HANDOFF_REPORT.md 추가; README/시험 안내에 연결.
  촬영 안정 조건·미정 신호/수치·진단 반환 위치·Backend 소비 단계와 합성 자체 검사 구분.
- normal_match JSON의 2x2x1 확인. 시험 변경 2x6x1은 현재 없어서 기존 파일 변경 없이 보존.
- perception_backend_callback_examples_20261006.zip 생성: 19파일, 23,446 bytes.
  캐시 제외, ZIP CRC 확인. 원본 코드·JSON·문서만 포함.
- 이번 검증: 소스 callback pytest 14 passed in 0.03s;
  ZIP을 임시 폴더에 풀어 독립 실행한 pytest 14 passed in 0.06s,
  CLI 종료 코드 0. 문서 상대 링크·코드 fence·후행 공백 확인.
- 미검증: 실제 Backend 소비·HMI·카메라/보정/Robot; 사용자 직접 재검사·수현님 소비 확인이 다음 단계.
  C-2 수정·장치 이동·외부 전송 없음.

## 2026-10-06 — Backend 소비용 JSON 자료와 시험 안내

- perception_mvp/fixtures에 여섯 Observed JSON, 여섯 별도 진단 JSON,
  check 변경 순번 자료 JSON 추가. 기존 예시 코드에서 만든 값과 일치하는지 검사.
- BACKEND_TEST_GUIDE.md에 실제 check ID 치환·별도 진단 연결·사전 Current/목표·확인 결과 명시.
  예시값을 실제 Backend에 넣는 소비 검사는 수현님 연결부에서 수행하며 HMI 전송을 임의 구현하지 않음.
- 실제 검증: callback 관련 **14 passed in 0.06s**, 전체 **28 passed in 0.58s**, 종료 코드 0.
  JSON 자료와 소스 일치/수신, py_compile, 문서 링크·후행 공백 검사 확인.
- 사용자 직접 로컬 시험·실제 Backend Current 채택/비교/보류·HMI/카메라 검증은 아직 미수행.
- 전달 시 fixtures와 안내서도 포함해야 함. C-2 수정·외부 메시지·게시 없음.

## 2026-10-06 — check 변경 순번 예시 보완

- 예시 정책을 check별 0부터 시작, 관측 묶음 시작마다 +1로 명시.
  실행 전체 증가 방식이 아니며 공통 계약의 필수 카운터 정책으로 강제하지 않음.
- A/0, A/1 → 새 B/0, B/1 시작 및 A/1, B/0, A/0, B/1 역전 도착 설명 자료 추가.
- 다중 View는 묶음 check/seq 공유. 관측 시각은 진단용이며 최신 판정에서 제외.
- 실제 검증: 전체 pytest **27 passed in 0.52s**, 종료 코드 0.
  CLI의 7개 JSON(다섯 사례+아래층 보충+순번 자료) 파싱, py_compile, diff 공백 검사 종료 코드 0.
- 실제 촬영 카운터·닫힌 check 필터·Backend 소비 검사·장치 통합은 미구현/미검증.
  C-2 변경·외부 게시·메시지 전송 없음.

## 2026-10-06 — PR #6 반환 형식 정렬

- callback 예시·테스트·perception_mvp README 수정. Observed는 check_id,
  observation_seq, status, visible_blocks, verified_regions, reason 여섯 필드만 반환.
- brick_type=2x2x1, 영역=x/y/width/height/layer로 공통 계약 반영.
  추적·품질·View·전달판 정보는 vision_diagnostics로 분리(별도 진단 envelope는 제안).
- 다섯 기본 사례 유지 + 이전 아래층만 가린 OK 보충 사례 추가.
  확인된 빈 목표는 OK인 미배치 차이, 이번 목표 품질 부족은 UNOBSERVABLE,
  전달판 UNOBSERVABLE은 조립판 OK와 독립적으로 표현.
- 실제 검증: 전체 pytest **25 passed in 0.63s**, 종료 코드 0.
  여섯 예시 JSON roundtrip·로컬 callback 수신 확인과 py_compile 종료 코드 0.
  신규 수정 파일의 후행 공백 및 git diff --check 확인.
- 미검증: 실제 Backend validator/Current 소비 검사, 실제 촬영·추적·영역 판별.
  다음: Backend 담당이 여섯 필드 callback과 별도 진단 전달 제안을 확인하여 소비 검사.
- C-2는 읽기만 수행. GitHub 게시·외부 메시지·dependency 설치 없음.

## 2026-10-06 — 팀장 검토용 callback 예시

- perception_mvp 아래 callback_examples.py, README.md, tests/test_callback_examples.py 추가.
- 정상 일치/불일치, 확인된 빈 영역, 가림/Depth 부족, 전달판 UNOBSERVABLE의 합성 예시 준비.
- 합의 필드와 미정 표현을 분리. Expected는 Backend 시험 context에만 있으며 callback에 전달하지 않음.
- 예시 데이터와 출력 검증만 수행. 실제 영역 검사·추적 구현이나 Backend 계약 확정 아님.
- 실제 검증: 전체 pytest **23 passed in 10.19s**, 종료 코드 0.
  다섯 사례 JSON roundtrip과 주입한 로컬 callback 수신 확인, 종료 코드 0.
  예시 CLI·py_compile 종료 코드 0. 신규 dependency 설치 없음.
- 미검증: 실제 Backend callback·닫힌 check/최신 결과 선택·Current 채택, 실제 촬영/학습/인식.
- 다음: 팀장이 임시 좌표/영역/시각/추적 필드/순번 증가 예시를 확인한 뒤 계약에 맞춰 조정.
- 기존 사용자 파일과 C-2 파일·Git을 변경하지 않음. 작업 폴더 README/STATUS에만 기록.

## 2026-10-05 — RGB-D 첫 구현 단위

작업 경로: `/home/roh/Documents/ChatGPT/협동2`.
브랜치: `codex/rgbd-perception-base` (기존 저장소에 커밋 없음).
기존 문서·데모는 수정하지 않았고 C-2는 읽기 기준으로만 사용했습니다.

- 변경: RGB·원본/정렬 Depth 기록과 로딩, 선택적 RealSense 한 프레임 수집,
  선택적 YOLO segmentation 추론, 단일 View의 유효 Depth·Board 좌표·상면 높이·footprint/Grid 후보 검증.
- 입출력: 로컬 저장 형식과 내부 후보 형식만 구현. Backend 계약 확정 또는 연결 완료가 아닙니다.
- 실제 검증: `python3 -m pytest -q` → **14 passed in 0.49s**, 종료 코드 0.
  `python3 -m py_compile rgbd_io.py depth_grid.py saved_perception.py capture_rgbd.py` → 종료 코드 0.
  capture_rgbd.py/saved_perception.py `--help` → 종료 코드 0.
- 시험은 합성 TEST RGB-D/보정값이며 장치·실제 모델 검증으로 해석하지 않습니다.
- 환경: numpy 1.26.4, OpenCV 4.6.0 확인. ultralytics/pyrealsense2 없음. 설치하지 않았습니다.
- lint/type check: 기존 구성 없음. 새 도구를 도입하지 않았습니다.
- 규모: 실행 코드 약 300줄, 독립 책임별 네 파일 + pytest/README/STATUS.
  300줄 이상 전체 변경과 5개 이상 신규 파일은 사람 리뷰 대상입니다.
  추상 계층·framework·DB 추가 없이 저장/측정/추론/수집의 독립 시험을 위해 분리했습니다.
- 미검증: RealSense·YOLO 실제 API 실행, 실제 RGB-D/1~4층 판별, 장치 timeout,
  학습 성능, ROS·Backend L3, Robot 포함 Day 4 사이클. 사람 리뷰·게시·PR 없음.

다음 작업: 실제 저장 샘플과 보정값으로 단일 View 시험 → 사선 상면 분리 보완 →
다중 시점 통합/충돌 → 이전 채택 상태 비교/가림 → 전체 보드 품질 → 합의한 Backend adapter.
학습 실행 및 scene 기준 분할 도구도 후속 작업입니다.

BLOCKER: 실제 학습 weights·실측 Camera→Board/높이/치수·공통 좌표 계약이 없음.
REQUIRED CHANGE: 장치 담당의 RGB-D·pose·보정 자료 및 Backend 정상/부분/실패 예시 확인.
AFFECTED INTERFACE: Backend 변환, 촬영 요청·완료, 이전 채택 상태 수신.
REASON: 추정 보정값이나 검출 누락으로 정상 전체 상태를 확정할 수 없음.
