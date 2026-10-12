# Perception 알고리즘 논의 인수인계

작성일: 2026-10-03  
상태: **알고리즘 미확정 — 다음 논의에서 선택 필요**

## 1. 프로젝트와 MVP 범위

Adaptive Co-Assembly는 사람이 LEGO 의자를 조립하고, M0609 로봇이 필요한 부품을 Supply Board에서 전달하는 Human--Robot Collaborative Assembly 프로젝트다. 사람이 계획과 다르게 조립하면 시스템은 현재 상태와 사람의 의도를 확인하고, 남은 계획과 다음 공급 부품을 바꿔 협업을 이어간다.

현재 MVP는 다음으로 제한한다.

- 낮은 LEGO 의자
- 색상: Yellow, Blue
- 부품: `2×2×1`, `2×3×1` brick
- Assembly Board / Supply Board: 각각 24×24 stud
- 카메라: D435i
- 로봇: M0609 2점 그리퍼
- 로봇은 부품을 전달만 하며, 직접 LEGO를 체결하지 않음
- 초기 adaptation은 규칙 기반으로 전체 흐름을 연결하고, 이후 LLM 판단과 비교

## 2. 역할 분담

| 파트 | 담당 역할 | 핵심 산출물 |
|---|---|---|
| A — Planning & Replanning | 설계·계획·재계획 | `TargetDesign`, `AssemblyPlan`, `NextPart`, `AdaptedPlan` |
| B — Perception | 실제 조립 상태 관찰 | `CurrentAssemblyState` |
| C — Adaptation / AI Decision | 계획-현실 차이 해석·대응 결정 | `Deviation`, `Decision`, `PlanChangeRequest` |
| D — Robot Execution / HRI | 로봇 공급·Qt 상호작용·통합 | `RobotResult`, Pick/Delivery/Handover |

이 문서는 **B — Perception**의 현재 상태 인식 알고리즘을 결정하기 위한 자료다.

## 3. Perception의 책임과 출력

Perception은 조립 순서를 정하지 않는다. 조립 순서와 목표 구조는 A가 제공한다. Perception은 Assembly Board에서 실제로 무엇이 조립되어 있는지를 관찰해 C에 전달한다.

최소 출력은 다음과 같다.

```text
CurrentAssemblyState
├── observation_id       # 이번 관찰 기록의 ID
├── observed_at          # 관찰 시각
├── frame_id             # assembly_board_frame
├── blocks[]
│   ├── part_class       # 예: YELLOW_2x3x1
│   ├── position         # grid (x, y, z)
│   ├── orientation
│   └── confidence
└── occluded_regions / unknown_regions
```

`observation`은 블록 위치가 아니라 **한 시점의 관찰 기록**이다. 블록의 위치는 observation 안의 `position` 필드에 들어간다.

## 4. 현재 문제

Assembly Board를 위쪽 D435i로 관찰할 때 다음 문제가 있다.

- 높이와 층수(`z-layer`) 판단이 불안정할 수 있음
- 높은 블록이 아래쪽 또는 측면 블록을 가림
- 최종 구조만 보고 과거 조립 순서를 유일하게 복원할 수 없음
- 위쪽 단일 시점만으로 결합 관계·가려진 구조를 완전히 관찰하기 어려움

중요한 역할 경계:

```text
Planning(A): 조립 순서를 결정
Perception(B): 현재 조립 상태를 관찰
Adaptation(C): 계획과 현실의 차이를 판단
Robot/HRI(D): 다음 부품을 공급하고 사람에게 질문
```

따라서 카메라가 조립 순서를 스스로 정하는 것은 목표가 아니다.

## 5. 이미 논의한 기본안: RGB-D 변화 검출 + Grid 상태 추적

사람이 블록 하나를 조립할 때마다 전후 상태를 비교한다.

```text
직전 확정 상태 S(t-1)
→ 사람이 블록 조립
→ 손이 화면에서 사라진 뒤 RGB-D 관찰
→ 변화 ΔState 검출
→ 현재 확정 상태 S(t) 갱신
```

예:

```text
S(t-1): BLUE_2x2x1 at (4, 6, 1)
조립 후: YELLOW_2x3x1 at (4, 6, 2) 추가 관찰
ΔState: ADD YELLOW_2x3x1 at (4, 6, 2)
S(t): 기존 상태 + 새 블록
```

구성 요소:

1. Assembly Board 기준 좌표계 고정
2. RGB-D 정렬 및 보드 영역 추출
3. 보드 평면 제거
4. 높이 맵 또는 점유 grid 생성
5. 조립 전후 변화 검출
6. 색상·footprint(`2×2`, `2×3`)·z-layer 판정
7. 여러 프레임 median으로 depth noise 완화

장점: 제한된 부품 종류와 한 단계씩 조립하는 MVP에 적합하다.  
한계: 단일 위쪽 카메라의 가림과 하단 구조 관찰 한계는 남는다.

## 6. 다음 채팅방에서 비교·결정할 대안

### 선택지 A — RGB-D 변화 검출 + Grid 상태 추적

- 전후 관찰의 차이로 새 블록·제거·색상 변경을 검출
- 계획, 공급 이력, 사람 응답과 결합 가능
- MVP 기본 후보

### 선택지 B — 다중 시점 RGB-D 융합

```text
위쪽 D435i + 측면 카메라
→ 각 시점 Point Cloud 생성
→ assembly_board_frame으로 변환
→ Point Cloud Fusion
→ 가림 감소 및 층·측면 구조 확인
```

- 장점: 층수와 가림 문제를 가장 직접적으로 완화
- 단점: 카메라 추가, 보정, 동기화 필요
- 적용 방식: A의 변화 검출에 보조 관측을 추가하는 형태가 적절

### 선택지 C — CAD 기반 6D Pose Estimation

```text
RGB-D 장면 + 각 LEGO의 CAD/3D 모델
→ part class와 위치·방향(6D pose) 추정
```

- 후보 기법: Point Pair Feature, ICP refinement, template matching, 딥러닝 기반 6D pose
- 장점: 각 블록의 위치와 방향을 직접 추정
- 단점: 대칭 LEGO, 가림, CAD 준비, 데이터/튜닝 비용
- 판단: 연구 확장 후보이며 10일 MVP의 1순위는 아님

### 선택지 D — RGB Instance Segmentation

```text
RGB 영상
→ 블록별 mask 분리
→ Yellow/Blue 및 2×2/2×3 분류
→ Depth 또는 계획 제약으로 z-layer 보완
```

- 후보 기법: YOLO Segmentation, Mask R-CNN, SAM 계열
- 장점: 색상과 블록 개체 분리에 유리
- 단점: 위쪽 단일 RGB로는 층수와 가려진 블록 판정이 어려움
- 판단: 단독 해법보다 A 또는 B와 결합하는 보조 수단

### 선택지 E — Marker 기반 인식

- Assembly Board 모서리에 AprilTag/ArUco를 부착해 좌표계를 고정
- 필요 시 Supply Board cell에도 marker를 사용
- LEGO 자체 marker는 실험성과 조립성을 해칠 수 있으므로 신중히 결정

- 장점: 보드 좌표계 보정에는 매우 간단하고 안정적
- 단점: LEGO별 marker까지 쓰면 비전 연구 범위가 축소될 수 있음
- 판단: **보드 보정에는 권장**, 부품 식별용 marker는 팀 합의 필요

### 선택지 F — 행동 기록 결합 State Estimation

```text
Planning의 기대 상태
+ D의 실제 공급 이력
+ HRI 사람 응답
+ B의 비전 관찰
→ 현재 조립 상태의 confidence 갱신
```

- 후보 모델: 상태 머신, Bayesian Filter, HMM
- 장점: 가림·낮은 confidence 상황에서도 시스템 상태를 유지 가능
- 단점: 카메라 검증 없이 공급 이력만 신뢰하면 실제 조립 실패를 놓칠 수 있음
- 판단: 다른 비전 방법을 대체하기보다 결합하는 시스템 수준 방법

## 7. 권장 의사결정 방향

10일 MVP의 우선순위는 다음과 같다.

```text
1. Board marker 기반 좌표계 고정
2. 선택지 A: RGB-D 변화 검출 + Grid 상태 추적
3. 선택지 F: 계획·공급 이력·HRI 응답과 결합
4. 가림이 실제 blocker이면 선택지 B: 측면 카메라 추가
5. C/D는 MVP 안정화 후 확장 후보
```

즉, 권장 MVP 조합은 다음이다.

```text
Board AprilTag/ArUco 보정
+ 위쪽 D435i RGB-D
+ 조립 전후 상태 변화 검출
+ Planning/Robot/HRI 이력 기반 상태 추정
+ 낮은 confidence → 재촬영 또는 ASK
```

## 8. 다음 논의에서 결정할 질문

1. 위쪽 D435i 한 대로 MVP를 시작하고, 어느 조건에서 측면 카메라를 추가할 것인가?
2. 조립 완료 관찰의 트리거는 무엇인가?
   - HRI 버튼
   - 손 감지 후 안정 프레임
   - 둘의 조합
3. z-layer 판정에 사용할 brick 높이와 허용 오차는 얼마인가?
4. `confidence`가 어느 값 미만이면 재촬영 또는 `ASK`로 보낼 것인가?
5. Board marker만 사용할 것인가, Supply Board cell marker도 사용할 것인가?
6. 단일 블록 추가만 먼저 지원할 것인가, 제거·이동·색상 변경도 MVP에 포함할 것인가?
7. `UNKNOWN` 상태에서 사람에게 보여 줄 HRI 문구와 선택지는 무엇인가?

## 9. 참고 자료

- RealSense RGB-D 정렬 및 Point Cloud: <https://github.com/realsenseai/librealsense/wiki/Projection-in-RealSense-SDK-2.0>
- RealSense 다중 카메라 구성: <https://dev.intelrealsense.com/docs/multiple-depth-cameras-configuration%C2%A0>
- ROS2 tf2 좌표 변환: <https://github.com/ros2/ros2_documentation/blob/rolling/source/ROS-Framework/interfaces/About-Tf2/About-Tf2.rst>
- 6D Object Pose Estimation BOP Benchmark: <https://arxiv.org/abs/1808.08319>
- Fiducial Marker Pose Estimation 비교: <https://doi.org/10.1007/s10846-020-01307-9>
