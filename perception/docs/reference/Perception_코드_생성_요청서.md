# Perception 코드 생성 요청서

다음 요구사항을 기준으로 Assembly Board 관측 코드를 구현해주세요. 설계 설명이나 빈 skeleton만 작성하지 말고, 저장 RGB-D로 실행 가능한 핵심 처리와 정상·실패 테스트를 단계적으로 구현해주세요. 실제 카메라·학습 데이터·보정값이 없어서 실행할 수 없는 부분은 필요한 입력과 미검증 범위를 명확히 기록해주세요.

## 1. 작업 위치와 변경 범위

- 생성 위치: `/home/roh/Documents/ChatGPT/협동2/perception_mvp`
- `/home/roh/C-2`는 읽기·검토만 허용합니다. 명시적인 추가 요청 전에는 파일 생성·수정·이동·삭제·Git 변경을 하지 마세요.
- 참고: `/home/roh/C-2/AGENTS.md`, `README.md`, `docs/00_CURRENT_DECISIONS.md`, `docs/06_CONTRACT_DRAFT.md`, `docs/03_MEASUREMENT_GUIDE.md`, `docs/01_DAY_PLAN.md`
- 기존 사용자 파일을 보존하고 필요한 범위만 구현해주세요.
- 이번 요청은 Perception 코드 생성이며 Robot 이동, GitHub 게시, 외부 메시지 전송을 포함하지 않습니다.

## 2. 목표와 일정

### 작업 시작 전 필수 문서 검토

코드 생성 전에 `/home/roh/C-2`의 아래 파일을 실제로 읽고 지켜야 할 내용을 확인해주세요. 이 요청서의 요약만으로 검토를 대신하지 마세요.

1. `AGENTS.md`
2. `README.md` → `docs/00_CURRENT_DECISIONS.md` → `docs/STATUS.md`
3. `docs/01_DAY_PLAN.md`, `docs/02_TEAM_GUIDE.md`
4. `docs/06_CONTRACT_DRAFT.md`, `docs/03_MEASUREMENT_GUIDE.md`
5. `docs/reference/AI_CODE_POLICY.md`, `docs/reference/UNIT_TEST_POLICY.md`

읽은 뒤 역할 경계·입출력·작업 단위·검증·미확정 사항에 적용할 규칙을 짧게 정리하고 구현을 진행해주세요. 필요한 지침 파일은 끝까지 읽으세요. 사용자의 최신 명시적 결정이 이전 문서보다 우선하며, `docs/reference`의 과거 역할·DB·구조는 최신 계약으로 자동 적용하지 않습니다.

특히 다음을 지켜주세요.

- 작은 기능 단위로 구현·검증한 뒤 다음 기능으로 진행합니다.
- 예상 파일 수·코드 규모·필요성·계약 영향을 구현 전에 보고합니다. 아래 15개는 전체 작업의 목표 구성이지 한 번에 모두 구현하는 단위가 아닙니다.
- 확정 계약과 임시 내부 형식을 구분하고 근거 없는 보정값·fallback을 만들지 않습니다.
- 최소 dependency와 단순한 구조를 사용하며 실패를 정상 결과로 숨기지 않습니다.
- Fixture 기반 L1, 관련 Component/Contract 검증, 실제 장치 검증을 구분합니다.
- 실행한 검사와 미실행 항목을 분리해 보고합니다.
- C-2의 `STATUS.md` 기록 지침은 이번 읽기 전용 제한에 따라 작업 폴더의 README 진행 기록으로 대신합니다. C-2 Git·파일은 변경하지 않습니다.

### 구현 목표

목표는 사람의 실제 조립 상태를 RGB-D로 관측하여 Backend가 사용할 관측 결과를 만드는 것입니다. 일정은 **2026년 10월 8일 Day 4 MVP까지**입니다.

확정 알고리즘:

**YOLO Segmentation + D435i Depth/Grid 검증 + 다중 시점 관측 + 이전 조립 상태 추적**

```text
V0·D1~D4 RGB-D 촬영
→ YOLO mask·클래스 검출
→ Depth/Grid로 위치·크기·방향·높이·층 검증
→ 여러 시점의 동일 블록 결과 통합
→ 이전 확정 상태와 비교
→ 조립 상태·신뢰도·가림·오류 출력
```

Voxel 융합은 복잡한 3D 공간 표현이 필요할 때 추가할 확장 기능이며 이번 기본 구현에 포함하지 않습니다.

## 3. 확정된 장비·지원 범위

| 항목 | 내용 |
|---|---|
| Camera | RealSense D435i 1대, M0609 J6에 장착 |
| 관측점 | V0 중앙 상부, D1 북서, D2 북동, D3 남동, D4 남서 |
| 기본 촬영 방향 | 기본 자세에서 바닥을 향하는 수직 시선, 사선 관측 시 Robot 자세 변경 |
| Board | Assembly Board 24×24 stud |
| 블록 | Yellow/Blue × 2×2×1/2×3×1 brick |
| 최대 조립 높이 | 4층 |
| 환경 정보 | Ubuntu 24.04, Python 3.12.3, ROS2 Jazzy, NVIDIA 4060 — 실제 패키지·GPU 호환성은 확인 필요 |
| 관측 범위 | Assembly Board 전체; Supply Board 관측 제외 |

YOLO 클래스와 번호는 프로젝트 내에서 일관되게 사용해주세요.

```text
0: yellow_2x2
1: yellow_2x3
2: blue_2x2
3: blue_2x3
```

## 4. 묶어서 생성할 파일 구성

아래 **총 15개 파일**을 기본으로 구성해주세요. 실제 사용처가 없는 추상계층이나 파일을 늘리지 마세요. 데이터·라벨·모델·로그는 이 파일 수에 포함하지 않습니다.

```text
perception_mvp/
├── README.md
├── requirements.txt
├── config.yaml
├── dataset.yaml
├── contracts.py
├── rgbd_io.py
├── yolo_pipeline.py
├── depth_grid.py
├── multiview.py
├── state_tracking.py
├── backend_adapter.py
├── visualization.py
├── main.py
└── tests/
    ├── test_geometry.py
    └── test_observation.py
```

| 파일 | 묶을 기능 |
|---|---|
| `README.md` | 설치·촬영·라벨링·학습·평가·추론·미확정 사항 안내 |
| `requirements.txt` | 실제 사용한 최소 dependency; 환경 호환성 확인 후 버전 기록 |
| `config.yaml` | 경로·관측점·보정 입력·시험용 임계값 설정 |
| `dataset.yaml` | 네 클래스와 train/validation 경로 |
| `contracts.py` | 내부 RGB-D·검출·블록·관측 결과와 오류 표현 |
| `rgbd_io.py` | D435i 수집·정렬·메타데이터 저장 및 저장 RGB-D 로딩 |
| `yolo_pipeline.py` | 라벨 검사·Segmentation 학습·평가·mask 추론 |
| `depth_grid.py` | 유효 Depth·3D 역투영·Board 변환·Grid/layer/방향 검증 |
| `multiview.py` | 동일 블록 연결·중복 제거·시점 충돌 및 장면 안정성 처리 |
| `state_tracking.py` | 이전 상태와 비교·추가/이동/제거 후보·가림·아래층 유지 |
| `backend_adapter.py` | 내부 결과의 임시 직렬화·저장 또는 로컬 callback 전달 |
| `visualization.py` | RGB mask·클래스·Grid·layer·UNKNOWN 표시 및 진단 결과 |
| `main.py` | capture/check-labels/train/evaluate/infer 실행 진입점 |
| `tests/test_geometry.py` | 좌표 변환·높이·Grid·유효 Depth의 정상/경계/오류 시험 |
| `tests/test_observation.py` | 다중 시점 중복·충돌·상태 추적·실패 직렬화 시험 |

## 5. RGB-D 수집과 촬영 시점

수집 코드는 Robot을 움직이지 않고, 지정된 View에서 정지한 카메라의 데이터를 수집하도록 구성해주세요. Robot pose는 외부 입력 또는 메타데이터로 받습니다.

촬영 흐름은 다음 제안을 기준으로 연결 지점을 준비해주세요.

1. 작업 시작 시 빈 보드 관측.
2. Robot 부품 전달 후 사람이 조립.
3. HMI 조립 완료 신호와 사람 이탈 확인.
4. Robot 담당이 관측 자세로 이동하고 정지.
5. 각 View에서 안정 RGB-D 수집.
6. 동일한 정적 장면의 View 결과 통합.
7. 정상 또는 부분·실패 관측을 Backend에 전달.

HMI 신호, 손 제거 감지, Robot 정지 신호는 아직 계약 미정입니다. 실제 장치 신호를 구현했다고 가정하지 말고 명시적인 입력 경계를 두세요. HMI 버튼과 안정 프레임 기준은 제안 상태입니다.

저장할 데이터:

- RGB 이미지
- RGB에 정렬된 원본 Depth와 Depth scale
- Camera intrinsics·왜곡 처리 조건
- View ID, 촬영 시각 및 RGB/Depth 시각 관계
- Camera→Board 변환 또는 그 계산에 필요한 보정·Robot pose
- Calibration version, 캡처 batch 식별
- 촬영 조건·입력 오류

Viewer 캡처를 원본 Depth로 사용하지 마세요. RGB와 Depth 단위·크기·정렬 관계를 검사해주세요.

## 6. YOLO 데이터·라벨링·학습

- RGB에 보이는 블록별 instance mask와 네 클래스 정답을 라벨링합니다.
- Depth는 YOLO 학습 클래스 입력으로 합치지 않고 후처리 검증에 사용합니다.
- 층과 방향은 별도 클래스로 늘리지 않습니다.
- 실제 라벨링은 사람이 수행해야 하므로 코드 생성만으로 정답 라벨이 생겼다고 보고하지 마세요.
- V0·D1~D4, 네 클래스, 1~4층, 같은 색 접촉·적층, 반사·그림자·가림을 포함하도록 수집 가이드를 작성해주세요.
- 가려진 경계를 임의로 그리지 않도록 일관된 mask 라벨 규칙을 안내해주세요.
- 동일 조립 장면의 연속 프레임과 여러 View가 train/validation에 섞이지 않도록 장면 단위 분리 규칙을 제공해주세요.
- 라벨 클래스 번호·polygon 범위·최소 점 수·이미지 대응을 검사해주세요. 빈 보드의 정상 빈 라벨과 잘못 누락된 라벨을 구분할 수 있도록 기록해주세요.
- 모델 경로가 없으면 명시적으로 실패하고 임의 검출값을 실제 YOLO 결과로 반환하지 마세요.
- 모델 버전 선택과 실제 학습은 설치 환경·데이터 확인 후 수행하며 학습 결과를 검증해주세요.

## 7. Depth/Grid 및 다중 시점 요구사항

- mask 내부 유효 Depth를 추출하고 경계·누락·노이즈를 검사합니다.
- 카메라 거리 값을 층 높이로 바로 쓰지 말고 3D 역투영 후 Board 좌표의 Z를 사용합니다.
- 여러 점의 Board 기준 높이 통계로 layer를 계산합니다. 시험용 임계값은 설정에 표시해주세요.
- mask 모양은 시점과 가림에 따라 달라지므로 픽셀 면적만으로 블록 크기를 확정하지 않습니다.
- stud 간격·brick 높이·Board 축·anchor·허용 방향은 설정 입력으로 받습니다.
- 미보정 상태에서 물리 Grid나 layer를 정상값으로 출력하지 않습니다.
- 다중 시점 블록은 Board 위치·layer·footprint·클래스 일관성으로 연결하고 중복 집계하지 않습니다.
- YOLO 클래스와 Depth/Grid 근거가 충돌하면 한쪽을 임의 선택하지 않고 UNKNOWN과 사유를 기록합니다.
- 여러 View의 장면 안정성은 점검하되, 촬영 데이터만으로 검증할 수 없는 조건은 미확인으로 표시합니다.
- 모든 View에서 가려진 블록을 현재 영상으로 직접 확인했다고 표시하지 않습니다.

## 8. 이전 상태 추적

매 사이클 기존 블록을 포함한 전체 보드를 다시 관측합니다. 변화 영역을 우선 정밀 판정하되 이전 블록을 관측 대상에서 제외하지 않습니다.

- 같은 색 적층: YOLO로 보이는 블록을 인식하고 높이 변화·이전 확정 상태로 아래층 추적.
- 가림: 이전 블록이 안 보인다는 이유만으로 삭제하지 않고 OCCLUDED/UNKNOWN 유지.
- 제거: 실제 제거 근거가 충분할 때만 후보를 확정 가능한 것으로 보고.
- 추가·이동: 위치·층·크기·클래스를 비교하고 연결 모호성을 표시.
- 초기 상태: 이전 기록이 없는 숨겨진 블록의 종류·색상은 추측하지 않음.
- 실패·미채택 관측으로 확정 추적 상태를 덮어쓰지 않음.
- Backend의 채택 상태 수신 방식이 미정이므로 이전 확정 상태를 명시적 입력으로 받으며 자동 채택을 가정하지 않음.

## 9. 출력 데이터와 Backend 경계

전달할 내용은 정해져 있습니다.

| 구분 | 내용 |
|---|---|
| 관측 정보 | 관측 ID·촬영 시각·View·Calibration 정보 |
| 블록 정보 | 종류·색상·Grid 위치·층·방향 |
| 품질 | 항목별 confidence·가림·미확인 영역·근거 |
| 오류 | 촬영·보정·처리 실패와 사유 |

사용자의 알고리즘 출력 명칭은 `CurrentAssemblyState`이며 저장소에서는 Vision의 전달 결과를 `Observed`라고 부릅니다. 코드의 내부 결과는 이를 설명할 수 있게 만들고, 실제 DTO 이름·JSON 필드·callback·Topic은 확정 공통 계약으로 가장하지 마세요. Backend가 Current를 채택하는 책임을 유지합니다.

직접 관측, 다중 시점 확인, 이전 상태 추론의 근거를 구분해주세요. confidence는 YOLO 점수 하나를 좌표·층 신뢰도로 복제하지 않고 각 근거의 품질을 분리합니다. 전체 점수 산식은 시험 가능한 제안으로 표시합니다.

정상 빈 보드와 입력 실패는 구분해야 합니다. 둘 다 블록 목록이 비어 있어도 실패를 정상으로 직렬화하면 안 됩니다.

## 10. 미확정 사항의 구현 원칙

아직 확정되지 않은 항목:

- Backend 함수·Topic·Schema·정확한 필드명
- Board 축·anchor·layer 시작 번호·방향 규약
- Hand-Eye·Camera/Board 변환 실측값
- Robot pose·좌표 단위·회전 규약
- confidence·높이 오차·동일 블록 연결 허용 오차
- 안정 프레임 수·timeout·촬영 트리거
- 모델 버전·실제 학습 데이터 규모

미확정 값은 입력 설정과 시험값을 구분해주세요. Camera→Board 변환에 근거 없는 identity를 기본 적용하거나 임의 Robot 좌표를 만들지 마세요. 필요한 보정이 없으면 해당 기능은 명시적 오류를 반환하고, 제공된 합성 시험값으로 계산 자체는 검증할 수 있게 해주세요.

Backend 전송 adapter는 로컬 파일 출력 또는 호출 가능한 callback을 주입하는 최소 형태로 준비해주세요. 실제 ROS Topic·HTTP endpoint를 임의로 확정하지 마세요.

## 11. 작업 순서와 완료 기준

| 단계 | 작업 | 확인 결과 |
|---|---|---|
| Day 1: 10/5 | 계약 예시·설정·수집/로더·라벨 검사 준비 | 저장 RGB-D와 정상/오류 입력 확인 |
| Day 2: 10/6 | 라벨링·초기 YOLO 학습·Depth/Grid 계산 | 저장 장면에서 mask·클래스·Board 위치·층 확인 |
| Day 3: 10/7 | 다중 시점·추적·Backend adapter 연결 | 중복·충돌·가림·실패 의미 확인 |
| Day 4: 10/8 | 실제 조립 Cycle·반복 검증 | 정상/변경/UNKNOWN 및 전달·채택 경계 확인 |

한 번에 모든 파일의 빈 틀을 만드는 것으로 완료하지 마세요. 저장 RGB-D 입력에서 결과까지 작은 기능을 연결하고 관련 시험을 수행한 후 다음 단계로 진행해주세요.

필수 확인:

- 네 학습 클래스와 mask 추론 결과가 일관된 형식.
- 알려진 변환·높이·Grid 합성 사례의 정상/오류 계산 검증.
- 동일 블록 중복 집계 방지 및 모호한 연결 UNKNOWN 처리.
- 가려진 이전 블록 유지·제거 근거 부족 처리.
- 관측 실패와 정상 빈 보드 출력 구분.
- 저장 RGB-D로 Camera·Robot 없이 핵심 파이프라인 실행 가능.
- 하드웨어가 없어도 기하·추적 테스트는 실행 가능하도록 장치 import를 분리.
- README의 실행 방법과 실제 명령 일치.

실제로 수행한 시험·학습·장치 확인과 미수행 범위를 분리해 보고해주세요. Synthetic/Mock 성공을 실제 D435i 성능이나 Robot 검증으로 표시하지 마세요. 저장 입력에서 검증된 코드와 실제 인식 성능은 별개입니다.

## 12. 결과 보고

생성 파일과 역할, 실행 명령, 실제 검증 결과, 필요한 데이터·보정·계약, 다음 작업을 간결하게 정리해주세요. C-2 파일은 수정하지 않았는지도 확인해주세요. 실제 코드 생성은 이 요청서의 생성 위치에서 진행합니다.
