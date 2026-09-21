# PrepareWorkpiece PR 전달 자료

## 인터페이스 식별

- Action 원문: `ws_cobot_pjt/ws_cobot1/src/c2_interfaces/action/PrepareWorkpiece.action`
- 인터페이스 최초 커밋: `2369c64be9097d6c1f851cca09f449aabad2c766`
- 타입: `c2_interfaces/action/PrepareWorkpiece`
- Action 이름: `/c2/prepare_workpiece`
- 서버 실행 파일: `c2_process real_preparation_node`
- 서버 구현: `c2_process.node:real_preparation_main`
- schema version: `2`

`2369c64`은 Action 원문을 처음 추가한 커밋이다. 후속 문서·샘플 커밋은 타입 원문을 변경하지 않는다.

## ID 발급과 중복 요청

| ID | 발급 주체 | 규칙 |
| --- | --- | --- |
| `request_id` | HMI/브라우저, BIND는 HMI 백엔드 | UUID v4. 통신 재전송은 같은 ID와 같은 Goal을 사용 |
| `preparation_id` | HMI 백엔드 | 한 준비 작업에 고정된 UUID v4 |
| `measurement_id` | HMI 백엔드 | 한 측정에 고정된 UUID v4 |
| `measurement_record_id` | HMI 백엔드 자산 저장소 | MEASURE Result 원본 저장 시 발급 |
| `profile_snapshot_id` | HMI 백엔드 자산 저장소 | 최종 불변 profile 저장 시 발급 |

같은 `request_id`와 같은 Goal은 저장 결과를 재생하며 새 모션을 시작하지 않는다. 같은 request ID에 다른 Goal은 `REQUEST_CONFLICT`다. 같은 preparation/measurement ID를 다른 request ID로 다시 측정하는 요청도 거절한다. 실제 재측정은 새 ID들을 사용한다.

## Feedback 의미

Action Feedback 필드는 `request_id`, `preparation_id`, `measurement_id`, `operation`, `stage`, `progress`, `completed_side_points`, `total_side_points`, `elapsed_s`, `message`다.

- MEASURE stage: `VALIDATING → ROBOT_CHECK → HOME_CHECK → HOME_MOVE(조건부) → HOME_RECHECK → TOP_TOUCH → SIDE_TOUCH → RETRACT → FIT → COMPLETE`
- BIND stage: `BINDING → COMPLETE`
- `progress`는 표시용 0..1이며 성공이나 정지 완료의 증거가 아니다.
- 이 Action Feedback에는 별도 `status`와 `sequence` 필드가 없다. 수신 순서는 ROS Feedback 도착 순서이며 재연결 후 연속 번호 복구를 보장하지 않는다. 최종 상태는 Result의 `outcome`으로 판단한다.
- 측정 내부 event의 `status`와 `sequence`는 제어 진단 기록이며 현재 Action Feedback 필드로 노출하지 않는다. HMI가 sequence를 필수로 요구하면 Action v3 변경 합의가 필요하다.

## Result 판정

- `geometry_ready=true`: 완전한 기하가 검증됐으며 경로 profile 변환에 사용할 수 있음. 부분·실패·정지·미검증 기하는 false.
- `validity=SIMULATED`: SIMULATION 결과. 실측 성공으로 표시 금지.
- `validity=FORCE_CONTACT_ESTIMATE`: REAL 접촉 측정과 절대 기하 조건을 통과한 결과.
- `validity=ESTIMATED`: 절대 윗면이 검증되지 않은 임시 결과. 현재 BIND 및 경로 생성 승인 불가.
- `validity=INCOMPLETE`: 실패·취소·통신 단절 등 불완전 결과.
- `partial=false`: 성공에 필요한 전체 접촉·계산·후퇴가 완료됨. 일부 접촉만 있거나 실패하면 true.
- Action 필드명은 `stop_confirmed`다. `stop_confirmation`이라는 별도 필드는 없다.
- `stop_confirmed=true`: 정지/비이동 확인 조건을 충족했음. 정지 요청 접수만으로 true가 되지 않으며 공정 stop latch 해제를 의미하지 않는다.
- MEASURE 성공: `outcome=SUCCEEDED`, `error_code=NONE`, `geometry_ready=true`, `partial=false`, `stop_confirmed=true`, `snapshot_bound=false`.
- BIND 성공: 위 조건과 함께 `snapshot_bound=true`. BIND는 로봇을 움직이지 않는다.

## 샘플

정확한 Action 필드 이름으로 작성한 샘플은 `ws_cobot_pjt/ws_cobot1/src/c2_process/test/fixtures/prepare_workpiece_action_samples/`에 있다.

- `success.json`
- `failure.json`
- `cancel.json`
- `timeout.json`
- `communication_lost.json`

샘플은 SIMULATION 계약 실행을 나타내며 실제 로봇 캡처가 아니다. `feedback` 배열은 실제 Action Feedback 필드만 포함하고, Result는 모든 필드를 포함한다.

## 저장과 다음 공정 연결

1. HMI 백엔드가 MEASURE Result 전체를 `prepare-workpiece-result/1` 불변 자산으로 저장한다.
2. 저장소가 `measurement_record_id`와 최종 파일 바이트의 SHA-256을 발급한다.
3. 조회는 `GET /api/operator/assets/{asset_id}/content`를 사용한다.
4. HMI가 측정값으로 profile snapshot을 만들고 ID/SHA-256을 발급한다.
5. HMI가 `BIND_SNAPSHOT`을 보내고 제어가 측정 기록·profile·ID·해시·기하를 대조한다.
6. BIND 성공 뒤 같은 profile snapshot ID/SHA-256으로 GeneratePath를 호출한다.
7. 생성된 path ID/version/SHA-256과 profile ID/SHA-256을 ExecuteProcess에 연결한다.
8. 제어는 등록된 측정, 경로/설정 무결성, 최종 IK·관절 검사를 통과한 경우에만 실행한다.

## Cancel과 실제 정지

Action 표준 CancelGoal을 사용한다. 실행 중 Goal의 cancel event를 설정하고 측정 어댑터가 `MoveStop`을 요청한다. 정지 요청 응답만으로 완료 처리하지 않는다. PR #50 기준으로 새 관측에서 IDLE/비이동 및 위치·자세·관절 안정이 설정 시간 동안 유지돼야 `stop_confirmed=true`다. 확인 실패나 시간 초과는 `UNKNOWN/STOP_UNCONFIRMED`다. 취소·STOPPED·UNKNOWN은 공정 내부 latch를 남기며 정상 상태 응답 한 번으로 자동 해제하지 않는다.

## 지원·검증 범위

- SIMULATION: MEASURE, BIND, ROS Action 왕복을 모의 장치로 지원.
- REAL: `real_preparation_node`에서 MEASURE를 지원하고 BIND는 무동작으로 처리. 이 진입점의 ExecuteProcess는 `NOT_READY`로 거절.
- REAL 관측: PR #48 제어권 JSON v1, 500 ms 만료, GetRobotState/CheckMotion 정지 판정을 연결.
- 미검증: 실제 HMI Action 왕복, 실제 드라이버 재시작 후 GRANT/LOSS·통신 단절, 실제 홈/접촉 측정, Cancel 후 실물 위치 안정, 실제 QSTOP, 제품 검사.
- 그리퍼 개폐와 드릴 ON/OFF 명령은 포함하지 않는다.

