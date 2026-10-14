# B 저장소 정리·보존·README 재현 기록

날짜: 2026-10-12 / 소스 c67d3721675d0b6bed30b29a22315bb47a96a9ab + 이번 정리 working tree.

## 변경 범위

- perception/README.md에 현재 진입점, 환경/설치 출처, 모델/보정 적용 조건, 표본 명령·예상 정상/실패 결과, B 상태 소유와 미연결을 정리했다. 과거 원문은 details 아래 보존하고 최신 상태로 적용하지 않는다.
- perception/samples/inspection_replay/sample.json과 perception_mvp/replay_inspection.py: 모델·Camera·Robot·LLM·DB 없는 합성 관측 재현. 기존 VisionInspection/connect_inspection을 사용하며 판정 알고리즘을 복제·변경하지 않는다.
- perception_mvp/tests/test_replay_inspection.py: 제출 표본 재현 및 실입력을 합성으로 잘못 표시하지 않는 검사.
- ASSET_INVENTORY_20261012.json: 자료의 경로·bytes·SHA256·추적 상태·HEAD 동일 여부. metadata.json에는 확인 가능한 View/촬영 시각/형식/범위만 추출했다. 촬영 조건이 기록되지 않은 파일은 알고 있다고 추정하지 않는다.
- 다른 팀 파일·D 문서·STATUS.md는 수정하지 않았다. 실측·보정·모델·관측 판정/임계값 변경 없음. 사용자의 미커밋 변경·모델 삭제 상태와 미추적 학습 자료는 그대로 보존했다.

## 조사 결과

자료 목록 617개: 로컬 미추적 95개, Git 추적이지만 현재 로컬 삭제 상태 1개. 조사 범위는 recordings/models/labeling/calibration/archives/datasets/runs/local_results의 현재 파일과 Git에서 삭제된 해당 경로다. 자동 Python/pytest 캐시는 제외했다.

| 폴더 | 존재 파일 수 | 존재 파일 bytes | 현재 Git 추적 존재 파일 |
|---|---:|---:|---:|
| recordings | 427 | 358118081 | 427 |
| models | 58 | 77360337 | 58 |
| labeling | 106 | 87781788 | 13 |
| calibration | 34 | 3923502 | 23 |

위 폴더 합계는 캐시 등도 포함한 최초 조사값이며, 캐시 제외한 파일별 manifest의 617개와 집계 범위가 다르다. 로컬 삭제된 과거 hand_yolo11n_trial_best.pt는 조사 커밋의 Git blob을 읽어 SHA를 기록했다. 복구/삭제 확정은 하지 않았다. HEAD와 다른 tracked working tree 내용은 matches_head=false로 구분한다.

현재 자료에 100MiB 초과 개별 파일이 있는지는 manifest bytes로 확인할 수 있다. 일반 Git에 남은 큰 자료를 삭제 커밋만 추가해도 과거 이력 크기는 줄지 않는다. 이번에는 이력 정리/force push를 하지 않는다.

## 실제 실행한 재현

1. README의 replay_inspection 명령: **SYNTHETIC replay: 7 checks PASS**, 종료 0. 출력은 /tmp/b-inspection-replay-20261012.json. 초기 빈 확인·STEP MATCH·무근거 FINAL UNOBSERVABLE·FINAL MATCH·색상 MISMATCH·없는 Plan ERROR·부분 INITIAL ERROR를 실제 B 코어로 처리했다.
2. 제출 표본 회귀 검사: **2 passed**, 종료 0. 실측 입력을 합성 입력으로 표시하면 거부하는 검사 포함.
3. local_test preflight: numpy/cv2/yaml/ultralytics/pyrealsense2 모두 존재. device_or_model_validation=not_performed.
4. README의 실제 RGB/ROI 공급판 재생: 종료 0. 출력 /tmp/b-supply-replay-review-20261012/20261012T111419481443Z, detections.json/preview.png 생성. yellow_2x3=12, blue_2x3=12, red_2x1=19, 총43개. LOCAL_DIAGNOSTIC_NOT_GROUND_TRUTH이고 정답 개수/정확도 통과를 뜻하지 않는다.
5. README의 B MVP/legacy/calibration/supply 및 로컬 소비자 입력 함수 대조 명령: **327 passed in 4.24s**, 종료 0. 새 표본 검사와 현재 working tree의 기존 B 검사를 포함한다. 이전 시험 수와 합산하지 않는다. README 현재 안내의 로컬 링크와 코드 fence 짝, 대상 diff 공백 검사를 확인했다.
6. 자료 617개를 다시 읽어 manifest SHA256과 대조: 불일치 0, 종료 0. 로컬 삭제 모델 1개는 조사 커밋의 Git blob과 비교했다. 이 검사는 Release 첨부본 재다운로드 검증과는 다르다.

ROS 실시간 창·카메라/로봇·외부 API·PostgreSQL·웹 왕복·새 PC 설치는 실행하지 않았다. 재현 결과 파일의 /tmp 경로는 임시 실행 산출물이고 원본 보존 위치가 아니다.

## GitHub 전체 보존의 미완료 항목

- 95개 미추적 자료는 현재 사용자가 로컬 전용으로 보관한 변경이다. 추가 게시 또는 검증된 GitHub Release 보존 방식에 대한 확인이 필요하다. 이번에 임의 add/commit/push하지 않았다.
- 이전 저장소 밖 보관 위치(예: Downloads/협동2/github_excluded/... 및 Documents/ChatGPT/협동2/board_calibration_trials_20261007)는 이번 manifest 범위 밖이다. GitHub 안의 전체 보존을 주장하려면 이 자료 목록/출처/해시도 추가 조사해야 한다.
- Git commit 링크를 기록한 것과 Release 첨부본을 실제 내려받아 SHA256을 검증한 것은 다르다. Release는 생성·첨부하지 않았으며 내려받기 검증도 미수행이다.
- 실행 자료와 원자료를 구분했지만 물리 이동·삭제를 하지 않았다. 전체 GitHub 보존이 확인되기 전 기존 자료 유지가 원칙이다.

## 제출할 PR 설명에 남길 내용

운영/역사적 경로 구분, Git 제외 설명 정합, 환경 확인 버전과 공식 출처, 합성 표본 7개 결과, 실제 RGB 재생의 비정답 진단 결과, 전체 보존 미완료 자료와 manifest를 포함한다. 실제 센서/층/완료 검증 또는 자료 전체 GitHub 보존 완료로 표시하지 않는다.
