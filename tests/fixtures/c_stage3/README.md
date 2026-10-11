# C Stage 3 fixtures (Wave 2 Sol smoke envelopes)

Fable이 Stage 3 Wave 2 실 LLM smoke에서 얻은 C response envelope입니다(Fable 제공, 실행 조건은 Fable 기록 참고). 비밀값은 들어 있지 않습니다. 검사는 `tests/unit/c_design/test_stage3_contract.py`가 합니다.

| 파일 | 내용 |
|---|---|
| `initial_candidate_response.json` | `create_initial_design` 결과: Initial Candidate(version 1, daybed) |
| `review_approve_response.json` | 위 후보 `review_design_candidate(kind="initial")` APPROVE: 같은 후보, `review.round` 0 |
| `review_cancel_response.json` | 위 후보 검토 CANCEL: `status` CANCELLED, `error.code` USER_CANCEL, 같은 후보 |
| `review_modify_patch_response.json` | Initial 후보 검토 MODIFY "등받이를 더 높게": `scope` patch, 새 Candidate(version 1), `round` 1 |
| `review_modify_redesign_response.json` | Initial 후보 검토 MODIFY "완전히 다른 느낌으로": `scope` redesign, 새 Candidate(version 1), `round` 1 |
| `intervention_revise_input.json` | `run_intervention` 입력: Approved v1(= Initial 후보)·Current 13블록·Difference 1개·텍스트 답변 |
| `intervention_revise_response.json` | 위 입력의 REVISE 결과: Revised Candidate(version 2, Current 보존) |
| `review_revised_modify_patch_response.json` | Revised 후보 `review_design_candidate(kind="revised")` MODIFY "등받이를 더 넓게": 새 Revised Candidate(version 2, Current 보존), `round` 1 |

실제 출력이므로 블록 배치·문장은 실행마다 다릅니다. APPROVE·CANCEL 결과의 Design이 `initial_candidate_response`와 같다는 것과 `intervention_revise_input.design`이 그 Initial 후보라는 것은 테스트로 확인했습니다. 테스트는 계약(키·버전·보존·관계)만 검사하고 배치 값은 검사하지 않습니다.
