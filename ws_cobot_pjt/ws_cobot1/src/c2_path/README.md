# c2_path · 좌표·경로 생성

2026-09-20. `path_planner_node`가 호출할 계산 모듈(이미지 → SVG → 2D → 3D → 실행 경로 → 검증)과 샘플·시험을 구현했다. **`node.py`(GeneratePath Action 서버)는 아직 없다** — 팀 규칙상 빈 스텁을 두지 않는다. 입력·출력은 [GeneratePath 계약](../../../docs/INTERFACE_RECOMMENDATION.md), 파일 역할은 [목표 구조](../../../docs/SYSTEM_STRUCTURE.md)를 따른다. 검증 범위와 한계는 [검증 기록](../../../docs/validation/2026-09-20-c2-path.md).

| 구현 위치 | 담당 기능 | 상태 |
| --- | --- | --- |
| `c2_path/node.py` | GeneratePath Action 수신, 진행·결과·취소 처리 | 미구현 |
| `c2_path/image_to_svg.py` | 입력 이미지(PNG/JPEG) → 중심선 SVG (Otsu → 세선화 → 골격 그래프 → 베지어 근사) | 구현 |
| `c2_path/extract_2d.py` | SVG → 2D 좌표(mm), 크기·배치·회전 적용, 적응형 샘플링 | 구현 |
| `c2_path/optimize_2d.py` | 획 방문 순서 최적화(NN + 2-opt, 형상·진행 방향 보존) | 구현 |
| `c2_path/map_3d.py` | 원통 iso-parametric 매핑, 이음매·획당 180° 분할, 도구 자세 | 구현 |
| `c2_path/generate_path.py` | 안전비용 정렬, 오프셋 원통 TRAVEL, APPROACH/CUT/RETRACT 구간, path.json | 구현 |
| `c2_path/validate_path.py` | 실행 경로 검증 (형식·설정·표면·높이·간격·180°·이음매·관통·자세) | 구현 |
| `c2_path/workcell.py` | 워크셀·도구 상수, 원통 기하 | 구현 (test_only 값, 아래 "미확정값" 참고) |

## 계약·기준

- 경로 파일: `schema_version` 2, `frame_id` `c2_base`, `tool_id` `engraving_drill`, waypoint `[x, y, z, qx, qy, qz, qw]`(base 기준 드릴 끝, m + 정규화 quaternion). `c2_process/engraving.py`·`joint_check.py`(PR #34)와 같은 형식이며 두 코드로 직접 교차 확인했다(아래 검증 참고).
- 도구 자세: 툴 −Y = 표면 안쪽 법선, 툴 +Z = base −Z.
- 각도: 0° = base +X(로봇 반대편), 반시계 양수. 도안 원점 u=0 → 0°. 이음매 ±180°(−X, 로봇 쪽). 획·TRAVEL 모두 이음매를 넘지 않고(분할), 획당 둘레 180° 이내.

## 미확정값 (이 PR로 확정되지 않음)

- **반지름**: 자로 잰 34 mm를 쓴다. 옆면 접촉 실측으로는 `반지름+드릴 돌출=133.8mm` 합만 확정되고 반지름을 독립적으로 분리할 수 없다(보정 3점이 x ±14mm 범위에만 있어 측정 잡음 0.3mm로도 반지름 추정이 34~57mm까지 흔들림). 캘리퍼스로 지름을 직접 재기 전까지는 34mm를 쓴다.
- **이음매 각도**: 이 PR은 ±180°(−X, 로봇 쪽)를 가정한다. 병합된 [`workcell_candle_0919.yaml`](../../../docs/evidence/workcell_candle_0919.yaml)(PR #32)에는 아직 `seam_angle_deg: 0`으로 남아 있어 **문서와 이 PR의 가정이 다르다**. 이음매 위치가 최종 확정되면 `workcell.py`의 `SEAM_ANGLE_DEG`(현재 180.0)만 바꾸면 되고, yaml도 같이 갱신해야 한다.
- 워크셀 축·바닥/윗면 z는 [`workcell_candle_0919.yaml`](../../../docs/evidence/workcell_candle_0919.yaml)과 같다(PR #32, 병합됨).
- `profile_snapshot_id`("snap-candle-0919")·`profile_sha256`(0으로 채움)은 서버가 발급하는 값이 아니라 샘플용 문자열이다.
- J6/J5·IK는 이 패키지가 검사하지 않는다(`not_checked: J6_RANGE`). 공정 준비의 `joint_check.check_path_joints`(PR #34)가 담당한다. J5 안전 θ 범위가 정해지면 `workcell.REACHABLE_ANGLE_DEG`(현재 −180~180, 전 범위)에 반영한다.

## 시험·샘플

패키지 루트에서:

```bash
python3 -m unittest discover -s test -v   # 43개
python3 build_samples.py                  # samples/ 의 하트 샘플 3종 재생성
```

로봇·ROS·네트워크를 쓰지 않는다. 샘플 설명은 [samples/README.md](samples/README.md). 이 노드에서 로봇을 움직이지 않으며, 필수 검증이 구현되지 않은 항목은 통과로 보고하지 않는다.
