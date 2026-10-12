# C Design-Change fixtures (Wave 1, 2026-10-12, integration de59b08)

Wave 2~5(정면 규칙·Design-Change 모드·Planning failure HRI)가 공통으로 쓰는 결정론적 입력. 현재 계약(`docs/C_DESIGN_CONTRACT.md` §3·§5, `app/c_design/validator.py`)으로만 작성했고 새 필드는 없다.

| 파일 | 내용 | 검증 |
|---|---|---|
| `approved_design.json` | Approved Design v1, 15블록: 다리 4(1층 2x3x1 파랑 90°) · 좌석 6(2층 2x3x1 노랑) · 등받이 4(3·4층, **작은 x 쪽 x=8~9**) · 크라운 1(5층). 정면 판정 가능(등받이 = low-x) | `validator.validate_design == []` |
| `current_prefix.json` | Approved의 prefix: 1층 다리 4개. Revised가 반드시 보존해야 하는 Current | `_check_current == []`, support 위반 없음 |
| `difference_scenario.json` | 기존 `run_intervention`용: 다리 하나가 y+1로 밀린 `current`와 그 `differences` 1개 | `check_intervention_input == []` |
| `design_change_request.json` | 직접 Design Change의 `reason` 문자열("등받이를 더 높여줘") | 현재 `run_design_change(reason: str)` 계약 |

제한: Mock Revised 생성기(`designer.mock_revised_candidate`)는 Mock 의자 전용이라 이 Design 위에서는 연결성 탈락만 낸다. Mock 모드에서 Revised Candidate까지 가야 하는 테스트는 Mock 의자를 쓰고, 이 fixture 위의 Revised 생성은 LLM 경로(Wave 2~5 smoke)에서만 확인한다.

생성 스크립트는 scratch(저장소 밖)이며 값은 손으로 고정했다. `tests/unit/c_design/test_design_change_characterization.py`가 위 검증을 매번 다시 실행한다.
