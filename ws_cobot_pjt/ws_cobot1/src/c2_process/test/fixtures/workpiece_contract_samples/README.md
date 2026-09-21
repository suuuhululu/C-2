# 측정 함수 반환 예시

2026-09-21 현재 측정 함수를 SIMULATION 백엔드로 실제 호출해 생성했다. ROS Action 왕복·실기 시험 결과가 아니다.

공통 입력은 `config/workpiece_simulation.json`, 호출은 `measure_workpiece(adapter, workcell, profiles, context, on_progress=None)`다.
각 JSON의 `result_excerpt`는 StepResult의 직렬화 발췌다. 생략한 진단 필드는 `omitted_from_excerpt`에 나열한다.
진행 콜백과 같은 이벤트들은 `result_excerpt.observed_state.events`, 측정 결과는 `result_excerpt.observed_state.measurement`다.

| 파일 | 주입 조건 | 결과 | 실제 정지 확인(모의) |
| --- | --- | --- | --- |
| success.json | 정상 8점과 마지막 후퇴 | SUCCEEDED | true |
| failure.json | 두 번째 점 접촉 탐색 실패 | FAILED / CONTACT_NOT_FOUND | true |
| cancel.json | 첫 번째 접촉 완료 직후 ctx.cancel.set() | STOPPED / CANCELLED | true |
| timeout.json | 첫 명령 후 시계가 제한 시간 초과 | FAILED / TIMEOUT | true |
| communication_unknown.json | 명령 결과 통신 단절 및 정지 미확인 | UNKNOWN / COMMUNICATION_LOST | false |

운영자가 드릴 OFF를 확인했다는 기록은 공정 수신부가 해당 준비 요청에 묶어 어댑터 readiness로 전달한다. 현재 단독 REAL 팩터리의 CLI 확인은 그 통합을 대신하지 않는다.
실물 CONTACT_REFERENCE의 SUCCEEDED는 절대 윗면 Z까지 유효하다는 뜻이 아니다. 현장 결과의 geometry_ready=false를 유지해야 한다.
