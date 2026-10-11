# Adaptive Co-Assembly — Perception MVP 업무 계획

작성일: 2026-10-04  
담당: B — Perception / 노홍동  
상태: 카메라 배치 및 최종 인식 알고리즘 시험 후 확정 필요

## 1. 프로젝트 역할 분담

| 파트 | 역할 | 주요 산출물 |
|---|---|---|
| A — Planning & Replanning | 목표 설계, 조립 계획, 재계획 | `TargetDesign`, `AssemblyPlan`, `NextPart`, `AdaptedPlan` |
| B — Perception | 실제 조립·공급 상태 관찰 | `CurrentAssemblyState`, `SupplyBoardState` |
| C — Adaptation / AI Decision | 계획과 실제 상태의 차이 해석 | `Deviation`, `Decision`, `PlanChangeRequest` |
| D — Robot Execution / HRI | 로봇 실행, Qt HRI, 시스템 통합 | `RobotCommand`, `RobotResult` |

전체 흐름:

```text
A: 목표·계획 생성
→ B: 실제 상태 관찰
→ C: 계획과 현실의 차이 판단
→ A: 필요 시 재계획
→ D: 부품 공급 및 사람과 상호작용
→ B: 실제 조립 결과 재관찰
```

## 2. Perception 담당 범위

Perception은 카메라 영상에서 다음 정보를 추출한다.

- 부품 색상: Yellow / Blue
- 부품 규격: `2×2×1`, `2×3×1`
- Board상의 위치
- 블록 방향
- 필요 시 Assembly Board의 층수
- 인식 confidence
- 가림·미확인 상태

Perception은 다음을 결정하지 않는다.

- 조립 순서
- 사람의 의도
- deviation에 대한 최종 대응
- 로봇 joint angle 및 trajectory
- 로봇의 실제 실행 여부

## 3. 카메라 구성 권장안

현재 권장 구성은 다음과 같다.

| 카메라 | 관찰 대상 | 역할 |
|---|---|---|
| RealSense D435i | Assembly Board | RGB-D 기반 블록 색상·규격·`(x,y,z)`·방향 관찰 |
| Logitech 고정 웹캠 | Supply Board | cell 점유·부품 종류·2D 위치·방향 관찰 |

권장 이유:

- Assembly Board는 적층 높이와 조립 결과 검증이 필요하다.
- Supply Board는 평평하고 통제된 cell 환경으로 구성할 수 있다.
- Supply Board의 로봇 pick pose는 MVP에서 cell별 티칭값을 사용한다.
- Logitech은 Supply Board에서 `(x,y,θ)`와 part class를 관찰하는 데 사용한다.

이 배치는 다음 시험을 통과한 후 확정한다.

- RealSense 화각에 24×24 Assembly Board 전체가 들어오는가?
- 빈 Board, 1층, 2층, 3층의 Depth가 반복적으로 구분되는가?
- 조립 중 사람의 손이 빠진 뒤 Depth가 안정화되는가?
- Logitech으로 Supply Board cell과 네 part class를 구분할 수 있는가?

## 4. PC 및 연결 구성

MVP에서는 관제 PC 한 대에 두 카메라를 연결한다.

```text
관제 PC
├── RealSense D435i — Assembly Board
├── Logitech Webcam — Supply Board
├── Perception 모듈
├── Backend / HRI
└── ROS2 / M0609 통신
```

연결 원칙:

- RealSense는 USB 3.x 포트에 직접 연결한다.
- Logitech은 별도 USB 포트를 사용한다.
- 두 카메라를 저품질 USB 허브 하나에 연결하지 않는다.
- 장치는 serial number로 구분한다.
- MVP에서는 해상도와 FPS를 필요한 수준으로 제한한다.

## 5. 좌표계

### Assembly Board

```text
frame_id: assembly_board_frame
position: grid (x, y, z)
```

### Supply Board

```text
frame_id: supply_board_frame
cell_id: C1, C2, C3 ...
position: 필요 시 Board 기준 (x, y, θ)
```

팀과 확정할 사항:

- Board 원점
- x·y축 방향
- 0부터 또는 1부터 세는 방식
- 블록 기준점
- z-layer 정의
- 각도 단위와 0° 기준
- 시계/반시계 방향
- Camera–Board–Robot 좌표 변환

Assembly Board와 Supply Board 좌표계를 서로 혼용하지 않는다.

## 6. Perception 출력 계약

### CurrentAssemblyState

```text
CurrentAssemblyState
├── observation_id
├── observed_at
├── frame_id: assembly_board_frame
├── blocks[]
│   ├── part_class
│   ├── position: (x, y, z)
│   ├── orientation
│   └── confidence
└── unknown_regions / occluded_regions
```

### SupplyBoardState

```text
SupplyBoardState
├── observation_id
├── observed_at
├── frame_id: supply_board_frame
└── cells[]
    ├── cell_id
    ├── occupied
    ├── part_class
    ├── position / orientation
    └── confidence
```

`observation_id`는 위치가 아니라 한 번의 관찰 기록을 구분하는 ID다.

## 7. Supply Board에서 Perception과 Robot의 역할 경계

### Perception 담당

```text
part_class
x, y
orientation θ
confidence
frame_id
```

후보 기법:

- OpenCV `minAreaRect`
- PCA 기반 주축 계산
- YOLO OBB
- Instance Segmentation mask 장축 계산

### Robot Execution 담당

```text
Board 좌표 → Robot Base 좌표 변환
→ grasp pose 계산
→ 그리퍼 회전
→ 접근·하강·파지·인양
```

공동 작업:

- Camera–Board calibration
- Board–Robot Base calibration
- 허용 위치·각도 오차 결정
- 낮은 confidence일 때 실행 보류 정책

Perception은 로봇 joint angle이나 TCP trajectory를 생성하지 않는다.

## 8. MVP 개발 단계

### 1단계 — 범위와 Contract 확정

- 네 part class 확정
- 두 Board의 좌표계 정의
- `CurrentAssemblyState` schema 작성
- `SupplyBoardState` schema 작성
- Valid/Invalid fixture 작성
- confidence 및 `UNKNOWN` 의미 합의

완료 기준:

- 실제 카메라 없이 fixture로 C/D와 계약 테스트가 가능하다.

### 2단계 — 카메라 설치 및 기초 시험

RealSense:

- 빈 Assembly Board 촬영
- 동일 위치의 1층·2층·3층 촬영
- Depth 분포와 반복성 확인
- Board ROI 및 좌표 변환 시험

Logitech:

- 빈 Supply cell 촬영
- 네 part class 촬영
- 다양한 위치·방향·조명에서 촬영
- cell ROI와 Board 좌표 변환 시험

완료 기준:

- 두 카메라가 관제 PC에서 동시에 안정적으로 동작한다.
- 역할 교체안의 기술적 가능 여부가 결정된다.

### 3단계 — Supply Board 인식

MVP 기본 방식:

```text
고정 cell ROI
→ 점유 여부
→ Yellow / Blue
→ 2×2 / 2×3
→ 방향 및 confidence
```

- 로봇은 cell별 티칭 pose를 사용한다.
- Perception은 `NextPart`와 실제 cell 부품의 일치 여부를 반환한다.
- 불일치하거나 confidence가 낮으면 로봇 실행을 보류한다.

### 4단계 — Assembly Board 인식

```text
RealSense RGB
→ 부품 색상·규격·2D 위치·방향 검출

RealSense Depth
→ Board 대비 높이 계산
→ z-layer 계산

RGB + Depth
→ CurrentAssemblyState
```

- 손 또는 가림이 있으면 확정하지 않는다.
- 여러 프레임의 median으로 Depth noise를 줄인다.
- 낮은 confidence는 `UNKNOWN`으로 반환한다.

### 5단계 — 1PC 통합

```text
A: NextPart 결정
→ B: Supply Board에서 부품 확인
→ D: 티칭 pose로 부품 전달
→ 사람 조립
→ B: Assembly Board 재관찰
→ C: 정상 / ASK / CORRECT / REPLAN 판단
```

완료 기준:

- 한 번의 전체 사이클이 동일한 DTO 계약으로 연결된다.
- 로봇 전달 성공과 사람의 조립 성공을 구분한다.

### 6단계 — 실패 처리 및 안정화

필수 시험:

- Supply cell이 비어 있음
- 등록된 부품과 실제 부품이 다름
- 부품 방향이 허용 범위를 벗어남
- 손 가림
- 조명 변화
- Depth 누락
- 카메라 timeout
- 오래된 프레임
- 낮은 confidence

처리 원칙:

```text
확실함 → 상태 확정
불확실함 → UNKNOWN
가림 → 재촬영
Supply 불일치 → Robot 실행 보류
카메라 오류 → 명시적 실패
```

## 9. 데이터 수집 및 학습 방향

카메라와 작업별로 데이터를 분리한다.

```text
Supply Dataset
→ Logitech RGB
→ cell, occupied, part_class, orientation

Assembly Dataset
→ RealSense RGB + Depth
→ part_class, (x,y,z), orientation, confidence
```

권장 MVP 방식:

- Supply Board: 고정 ROI + 색상·윤곽·방향 분석부터 시작
- Assembly RGB: 규칙 기반 또는 기존 검출 모델 활용
- Assembly Depth: 기하 기반 높이·층 계산
- 성능이 부족한 부분에만 학습 모델 적용

연속된 유사 이미지 수백 장보다 다음 조건의 다양성이 중요하다.

- 위치
- 방향
- 조명
- 그림자
- Board 가장자리
- 손 가림
- 빈 cell
- 잘못 놓인 부품
- 적층 높이
- 정상 상태와 deviation

Train/Validation/Test는 연속 프레임이 아니라 서로 다른 촬영·조립 세션으로 분리한다.

## 10. MVP 제외 범위

- 랜덤 LEGO 더미 bin picking
- 자유로운 3D pick pose 생성
- 모든 LEGO 종류 인식
- 가려진 전체 구조의 완전한 3D 복원
- 여러 블록의 동시 변경
- 복잡한 geometry deviation
- 검증되지 않은 pose의 실제 로봇 실행

## 11. MVP 완료 기준

- RealSense로 Assembly Board의 1층·2층을 반복 구분
- Assembly Board의 색상·규격·`(x,y,z)`·방향 출력
- Logitech으로 Supply cell의 점유와 네 part class 확인
- Supply 블록의 `(x,y,θ)` 또는 cell·방향 출력
- `NextPart`와 실제 부품의 일치 여부 반환
- 낮은 confidence와 가림을 `UNKNOWN` 처리
- `CurrentAssemblyState` schema 통과
- `SupplyBoardState` schema 통과
- Fixture 기반 L1 테스트 통과
- 실제 카메라 L2 테스트 통과
- C/D와 L3 Contract 테스트 통과
- 한 번의 E2E Hero Scenario 성공

## 12. 최종 확정이 필요한 항목

1. RealSense와 Logitech의 최종 담당 Board
2. RealSense의 1층·2층 Depth 구분 성능
3. 최종 Perception 알고리즘
4. Board 원점·축·방향·z-layer 규칙
5. Supply Board의 RGB 기반 위치·각도 보정 범위
6. 관찰 트리거: HRI 버튼, 손 감지 또는 두 방식의 조합
7. confidence 임계값과 `UNKNOWN` 처리
8. 규칙 기반과 학습 기반 구현 범위

## 13. 권장 최종 흐름

```text
NextPart 결정
→ Supply Board에서 부품·방향 확인
→ 티칭 pose 기반 Robot Pick/Delivery
→ 사람 조립
→ Assembly Board RGB-D 관찰
→ CurrentAssemblyState 생성
→ Deviation 판단
→ 계속 진행 / ASK / CORRECT / REPLAN
```
