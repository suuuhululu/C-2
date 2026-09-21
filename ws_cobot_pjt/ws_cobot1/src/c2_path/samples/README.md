# 하트 샘플 경로 (test_only)

2026-09-19 확정된 2D·3D 알고리즘 조합을 그대로 적용해 만든 실행 경로 샘플이다.
손으로 계산한 이전 샘플과 달리 `c2_path/` 모듈이 실제로 생성한다.

패키지 루트(`c2_path/`)에서:

```bash
python3 build_samples.py                 # 샘플 3종 생성 (path_sha256 은 저장 후 계산해 result.json 에만)
python3 build_bundle_samples.py          # 파일 묶음 샘플 2종 (samples/bundles/, 아래 참고)
python3 -m unittest discover -s test -v  # 계약·안전·묶음·스냅샷 시험
```

> **두 종류의 샘플이 있다.** 이 문서의 `heart/`·`heart_pair/`·`heart_seam/` 는 **경로 알고리즘 검증용**이라
> ID 가 `path-heart-0001` 같은 읽기 쉬운 문자열이고 SVG·미리보기 파일이 없다. HMI 가져오기·통합 시험에는
> **`bundles/`** 를 쓴다. 실제 `GeneratePipeline` 을 돌린 결과이며 UUID·SHA-256·`manifest.json`·미리보기·SVG·
> 검증 보고서·`result.json` 이 실제 계약대로 들어 있다 (`bundles/heart_ok`, 실패 예시 `bundles/heart_seam_rejected`).
> 형식은 [`../BUNDLE_SPEC.md`](../BUNDLE_SPEC.md) 참고. `bundles/` 의 ID·해시는 HMI 발급값이 아닌 시험용이다.

## 경로 파일 형식 (2026-09-20, 로봇팀 형식으로 통일)

`path.json` 은 `c2_process/engraving.py`·`joint_check.py` 가 그대로 읽는 형식이다.

- `schema_version: 2` (engraving.py `SUPPORTED_SCHEMA=(2,)`, v1 은 거절됨)
- 최상위: `position_unit: "m"`, `orientation: "quaternion_xyzw"`, `frame_id: "c2_base"`, `tool_id`, `source_mode`
- waypoint: **`[x, y, z, qx, qy, qz, qw]`** — base(`c2_base`) 기준 드릴 끝 위치(m)와 정규화 quaternion.
  제어기 TCP(`GripperDA_v1`)로의 변환은 `robot_adapter.pose_to_posx` 가 한다.

```json
{"segment_id": "seg-0001", "kind": "APPROACH", "motion_profile_id": "candle_approach",
 "waypoints": [[0.4224, -0.0666, 0.179178, 1.0, 0.0, 0.0, 0.0], ...]}
```

이전 `{"position_m": {...}, "orientation_xyzw": {...}}` 형식은 engraving.py 가
`INVALID_INPUT`(7개 값 필요)으로 거절하므로 쓰지 않는다. c2_path 내부 계산은 dict 로 하고
`generate_path.build()` 가 내보내기 직전에 한 번 변환한다. `validate_path.validate()` 도
7개 값 형식이 아니면 `WAYPOINT_FORMAT` 으로 실패한다.

## 조각 모형 (원통 = 파라핀 양초)

| 값 | 내용 | 출처 |
| --- | --- | --- |
| 반지름 | 34.25 mm (지름 68.5±0.3) | 9/20 캘리퍼스 재측정 확정(시율님). 자로 잰 34.0mm 를 대체. 이전 R+드릴 돌출=133.8mm 는 옆면 터치 추정치일 뿐, "돌출 99.55mm"(9/20 실측)는 tool-드릴끝 TCP 길이라 c2_process 값이고 워크셀 반지름과 무관 |
| 전체 높이 | 150.0 mm | 시율님 실측 |
| 축 위치 (x, y) | 0.4218, 0.0001 m | 0919 실측 (`workcell_candle_0919.yaml`) |
| 바닥 z | 0.0834 m | 윗면 − 높이 (yaml `bottom_z_base_m`) |
| 윗면 z | 0.2334 m | 0919 손끝 수직 터치 실측 |
| 작업 가능 높이 | 바닥 기준 85~130 mm (= 윗면 아래 20~65 mm) | 시율님 확정 |
| 각도 기준 | 0° = base +X(로봇 반대편), 반시계 양수 | 시율님 9/20 |
| J5 안전 θ 범위 (`REACHABLE_ANGLE_DEG`) | −135°~135° (잠정치) | 시율님 9/20 J5 실측: θ=180°(−X)에서 J5=175°(±135° 한계 초과), θ=0°·±90° 는 정상, 사이는 미실측. 오늘 5° 간격 실측 후 갱신 예정 |
| 퇴화 조각 최소 길이 (`MIN_STROKE_LEN_M`) | 1 mm | 이음매 분할 등으로 생기는 점 2~3개짜리 거의 0mm 조각은 실제 절삭 의미가 없고 제어기가 동일점 movesx 를 거부할 수 있어 버린다 |
| 도안 원점 | u = 0 → θ = 0° (`U_ORIGIN_ANGLE_DEG`) | 권장안 69줄 "u 원점은 표면 설정에 정의" |
| 이음매 | ±180° = −X 면(로봇 쪽, J5 위험 구역) (`SEAM_ANGLE_DEG`) | 시율님 9/20. 전개면 u = ±πR 양 끝 |
| `frame_id` | `c2_base` | 팀장님 확정 (어댑터 반영 PR #23 병합됨) |
| `tool_id` | `engraving_drill` | 세은님 확정 |
| 도구 자세 | 툴 −Y = 표면 안쪽 법선, 툴 +Z = base −Z | 세은님 + 시율님 확정 |

## 샘플 3종

| 폴더 | 내용 | 무엇을 검증하나 |
| --- | --- | --- |
| `heart/` | 하트 1개. 폭 24mm, 윗면 아래 45mm, −Y 면(θ=−90°) | 시율님 9/18 드릴 하트와 **같은 조건** — 실기 결과와 직접 비교 가능 |
| `heart_pair/` | 하트 2개를 180° 떨어뜨림 | 획 정렬, 오프셋 원통 TRAVEL |
| `heart_seam/` | 하트를 이음매(180°, 로봇 쪽) 위에 놓음 | 이음매 분할. **J5 위험 구역이라 실기 금지** |

각 폴더에 `request.json` · `feedback.json` · `path.json` · `result.json` ·
`validation_report.json` 이 있다.

## 결과

| 샘플 | 획 | segment | CUT 길이 | TRAVEL 길이 | 검증 |
| --- | ---: | ---: | ---: | ---: | --- |
| heart | 1 | 4 | 72.7 mm | 0 mm | 통과 |
| heart_pair | 2 | 9 | 145.3 mm | 138.9 mm | 통과 |
| heart_seam | 1 → **2** (이음매 분할) | 7 | 72.7 mm | 277.8 mm | **실패 (예상됨 — `ANGLE_OUT_OF_RANGE`)** |

(반지름 34.25mm 갱신 후 수치. heart_seam 은 이음매(180°)가 J5 안전 범위(±135°) 밖이라
이제 의도적으로 실패한다 — 아래 "알려진 한계" 참고. 새 버그가 아니다.)

## 적용한 알고리즘 조합

**2D**: 형상·교차점 보존 → (하트는 정상 Bézier 라 재피팅 없음) → de Casteljau 적응형
샘플링 → NN → 2-opt → 2D 검증

- SVG subpath 연결관계를 보존한다. 하트는 닫힌 subpath 하나 = 획 하나다.
- 이미 정상적인 Bézier 이므로 **다시 피팅하지 않는다** (`refit_applied: false`).
  현 오차 0.05mm 기준으로 적응형 샘플링만 한다 → 간격 0.35~0.88mm (곡률 큰 곳이 촘촘).
- RDP·B-spline 은 쓰지 않는다.
- 2-opt 는 **방문 순서만** 바꾼다. 점열도 진행 방향도 그대로다
  (`direction_reversal_allowed: false` — 양방향 가공 품질 미확인).

**3D**: 원통 해석식 매핑 → seam·각도 분할 → 법선 자세 → 안전비용 NN·2-opt →
오프셋 원통 TRAVEL → 적응형 재샘플링 → segment 분할 → 전체 검증

- 정면 투영이 아니라 iso-parametric: `θ = U_ORIGIN_ANGLE_DEG + u/R`, `h = v`. 이음매로 끊긴 조각은
  [−180°, 180°] 로 옮겨 표현하므로 TRAVEL(θ 선형 보간)이 이음매(로봇 쪽)를 넘지 않는다.
- 쿼터니언 부호를 이어 붙인다. θ=180° 를 지날 때 `q`와 `−q`가 번갈아 나오는 문제가
  **실제로 있었다** (이전 파이프라인에서 인접 쌍 627개 중 8곳). 지금은 0곳.
- 안전비용 = 이동 호 길이 + 자세 변화 + 둘레 회전 + 이음매 근접. 가중치는
  `generate_path.COST_WEIGHTS` 에 있고 근거를 주석에 적었다.
- 작업 범위 초과·원통 관통·clearance 미달·설정 불일치는 **비용이 아니라 금지 조건**이다.

## 오프셋 원통 TRAVEL 이 왜 필요한가

`heart_pair` 의 180° 이동을 직선 현으로 이으면:

| 방식 | 축에서 최소 거리 | 표면 여유 |
| --- | ---: | ---: |
| 오프셋 원통 (채택) | 44.00 mm | **+10.00 mm** |
| 직선 현 (금지) | 0.00 mm | **−34.00 mm** ← 양초를 정통으로 관통 |

clearance 10mm 기준으로 각도차 **78.8°** 를 넘으면 직선 현은 반드시 관통한다.

## 알려진 한계

- `profile_snapshot_id`·`profile_sha256` 는 서버가 발급하는 값이 아니다 (`profile_sha256` 은 `matching_test_profile()` 의
  들여쓴 JSON 바이트의 해시, ID 는 `snap-candle-0919` 같은 문자열). HMI 발급 형식(UUID, compact JSON 바이트 해시)에 맞춘
  샘플은 `bundles/` 에 있다.
- `heart_seam` 은 하트 위·아래 꼭짓점이 정확히 180° 에 놓여 두 조각으로 나뉜다. 두 조각을 잇는
  TRAVEL 은 이음매를 넘지 않으려고 +X 쪽으로 **한 바퀴(360°)** 돈다 (277.8 mm, J6 도 한 바퀴).
  이음매 위 도안은 로봇 쪽 J5 위험 구역이라, 9/20 `REACHABLE_ANGLE_DEG`(잠정 ±135°) 반영 이후
  **`ANGLE_OUT_OF_RANGE` 로 검증 실패한다 — 예상된 동작이다, 회귀가 아니다.** heart_seam 은
  분할 로직·퇴화 조각 정리 확인용으로만 쓰고, 실기 가공 대상이 아니다.
- `REACHABLE_ANGLE_DEG` 는 9/20 시율님 J5 실측(θ=180°에서 J5=175°, ±135° 초과; 0°·±90° 는
  정상, 사이는 미실측) 기준 잠정치 −135°~135° 로 반영했다. 오늘 5° 간격 실측이 나오면 갱신한다.
- 이음매 분할로 생기는 퇴화 조각(점이 정확히 이음매 위에 찍혀 길이 거의 0)은 `MIN_STROKE_LEN_M`
  (1mm) 미만이면 버린다 (9/20 시율님 heart_seam 실기 관찰 — 제어기가 동일점 movesx 를 거부할 수
  있다). 단, 현재 코드/데이터로 재현되는 실제 사례는 못 찾았고, 합성 시험
  (`test_degenerate_seam_stub_is_dropped`)으로만 필터 동작을 확인했다 — 방어적으로 넣어둔 것이다.
- 구간별 완료 검증 조건(목표·허용 오차·확인 방식)은 아직 비어 있다. 실행 측 조건을
  받아야 채울 수 있다.
- `split_from_stroke_id` 등 분할 관계 필드는 아직 권장안에 없는 제안이다.
