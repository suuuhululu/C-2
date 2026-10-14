# B 비전 작업 인수인계 — 2026-10-13

## 작업 범위·금지사항

- 작업 위치: `/home/roh/C-2`. 먼저 `AGENTS.md`와 `git status` 확인.
- **B 조립판 비전만 수정**. A/C/D·백엔드·HMI 파일은 수정하지 않는다.
- 다른 병행 작업(특히 supply_vision·손 학습 자료)과 기존 미커밋 변경을 보존한다.
- Git add/commit/push/PR은 사용자 요청 전 금지. `git add .`, 전체 복원, force push 금지.
- 현재 **로봇·RealSense 미연결**. 저장 영상 시험과 실제 장치 검증을 구분한다.
- 설명·반복 시험을 줄이고 핵심 문제를 묶어서 수정한다. 완료 후 B 변경만 `docs/STATUS.md`에 기록.

## 목표

팀장님 요청 중 조립판 작업 진행 중: 종류·색상·XY·방향·층 인식 → 관측 가능한 전체 판 비교 → D INITIAL/STEP/FINAL에 결과 반환. B가 Current/revision/Expected/Difference를 확정하고 D는 중계한다. 가려진 아래층 확인 이력은 유지한다. 엄지척 완료 신호는 D 담당이며 추가 승인 단계를 만들지 않는다.

## 현재 구현과 핵심 파일

- `perception/perception_mvp/main.py`: 검사 관측 함수. 기본 STOPPED_CLEAR, 명시적 사람 조립 모드만 손 진입/이탈 대기.
- `ros_capture.py`, `rgbd_io.py`: 실제 정지 확인·활성 요청 조건 아래 최신 동기 RGB-D 1쌍 촬영, 요청 식별 저장. 수신과 추론 분리. 실제 D 함수 주입·장치 시험은 미완료.
- `opencv_live.py`, `integrated_view.py`, `depth_grid.py`: 몸체/스터드 표면 분리, 외곽·좌표·높이·층 계산. **현재 실제 영상의 주요 병목**.
- `region_evidence.py`: Depth 광선으로 빈 칸의 5층 공간이 비었음을 확인. 측정된 블록 영역도 별도로 생성. 미수신·가림을 빈 영역으로 처리하지 않는다.
- `assembly_replay.py`: 기존 RGB-D를 실제 모델로 재생하고 결과 PNG/JSON 저장. 합성 이미지 생성이 아니다.
- `config.yaml`: 아래 시험 설정. 보정 원자료를 임의 수정하지 않는다.

위 파일은 모두 `perception/perception_mvp/` 아래에 있다. 관련 테스트는 같은 경로의 `tests/`.

## 사용자 확정 설정 / 실측과 시험값 구분

- 보드 24×24, **스터드 간격 XY 16mm**. 최대 5층·40블록.
- 높이 0은 **보드의 스터드 없는 평면**. 보드 스터드 +4mm.
- 몸체 실측 평균 18.633mm. 사용자 채택 층 증가량 **18.625mm**.
- 시험 층 윗면 기준: **22 / 40.625 / 59.25 / 77.875 / 96.5mm**, 각 기준 **±2.5mm**. 보드 체결 1층 22mm 기준은 아직 실물 검증 필요.
- 관측 위치의 마지막 블록 **몸체 윗면에 스터드 4mm 한 번만** 더한다. 각 층마다 4mm를 더하지 않는다.
- 현재 설정 BODY_TOP_PLUS_STUD. 평면 보정 파일: `perception/calibration/assembly_runtime_pitch16_flat0_20261013.json`.
- Depth 범위(카메라 optical Z): V0 .443–.573m / D1 .334–.763m / D3 .397–.696m. 보정 기반 **시험값**, 실측 검증 전.
- 유효 Depth 최소 50픽셀·80%, 높이 분산 P95−P5 ≤5mm, 외곽 내부 지지 ≥55% 등은 시험 임계값. 통과시키려고 무작정 완화하지 않는다.
- 모델: `perception/models/block_v1_six_runs_20261010/blocks_yolo26s_best.pt`, confidence .25.

## 최신 실제 결과 — 완료로 보고하면 안 되는 부분

1. 실제 블록 저장 영상 6개, 검출 14개: 몸체/스터드 분리 **4개 성공**, **좌표·층 확정 0개**. 나머지는 표면 분리 실패 또는 외곽 추출 실패.
   - 최신 결과: `perception/recordings/assembly_replay_20261013_parallel_surface_refinement/report.json`
   - 외곽 내부 지지 33.8%, 47.1%, 41.4%로 55% 미달. 다른 1개는 RGB 4각 외곽 후보 자체가 없음.
   - 다음 우선 작업은 **실제 저장 영상의 외곽 추출 실패 원인 분석·최소 개선**. 기준만 낮추거나 좌표/층을 추정 확정하지 않는다.
2. 과거 빈 보드 영상의 칸 확인: V0 366/576, D1 269/576, D3 442/576. 진단상 합집합 556/576, **20칸 미확인**.
   - `perception/recordings/empty_column_review_20261013_detailed/report.json`
   - 서로 다른 과거 촬영이므로 하나의 INITIAL 검사 증거로 채택하지 않는다. 당시 pose·GT 정합성도 미검증.
3. 마지막 B 테스트 **365 passed, 1 skipped**. 건너뜀은 PR22 소비자 소스 부재 관련이며 실제 연결 성공을 뜻하지 않는다. 변경 후 관련 테스트 재실행 필수.

## 이어서 작업하는 방법

먼저 아래 문서와 최신 결과를 읽고 실패 영상 1~2개에 집중한다. 임계값·실측·계약 변경이 필요하면 사용자와 합의한다. 하드웨어 없이 가능한 개선만 진행하고, Camera→D/실제 공급판 집기/전체 MVP 성공은 주장하지 않는다.

- 상세 근거: `perception/docs/ASSEMBLY_REPLAY_20261013.md`
- 확인 영역: `perception/docs/REGION_EVIDENCE_20261013.md`

```bash
cd /home/roh/C-2
PYTHONPATH=.:perception python3 -m pytest perception/perception_mvp/tests -q
```

재생 명령은 `ASSEMBLY_REPLAY_20261013.md` 참고. 출력은 새 폴더로 저장하고 기존 결과·RGB·Depth 원자료는 보존한다. 자료 정리/Release 보존 작업과 실제 공급판 검증도 남아 있지만 이번 외곽 개선과 섞지 않는다.
