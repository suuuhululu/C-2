# C Stage3에 맞춘 A·D 통합 변경

2026-10-11 수현 요청: 이미 통합 브랜치에 병합된 C PR #23을 기준으로 A·D를 맞춥니다. B가 Current·current_revision·Expected·공간 비교를 확정하고 D가 실행·진행·최종 종료·HMI/DB를 담당하는 [10/8 계약](handover/final_mvp_interface_20261008/README.md)을 유지합니다.

## 확정한 입력과 표시

- Design은 `{design_version, blocks}`입니다. 여섯 배치 필드, 24×24 stud, 정수 layer 1~5, 실행 후보 1~40블록입니다. HMI의 기존 빈 설계 표시 fixture는 실행 승인을 뜻하지 않으며 그대로 표시할 수 있습니다.
- 노랑·파랑은 `2x2x1`, `2x3x1`; 빨강은 `1x2x1`만 허용합니다. 노랑/파랑 2점과 빨강 4점/6점은 거절합니다.
- 2점 방향 0°는 X1/Y2, 90°는 X2/Y1입니다. A의 지지·중첩·경계 검사는 유지합니다.
- FAKE 공급은 기존 네 열에 빨강 2점 열을 추가한 다섯 열입니다. 각 열의 여섯 슬롯과 보충 확인을 사용합니다. 기존 네 열 설정도 읽을 수 있지만 빨강 요청은 장치 호출 전에 `UNCONFIGURED_SUPPLY_COLUMN`으로 거절합니다.
- REAL은 기존 측정된 네 열과 실행 범위를 유지합니다. 빨강 공급 pose·파지·직접 결착은 측정/검증 전 실행할 수 없습니다.

## D 호출 순서

1. 최초 요청을 식별하고 C `create_initial_design`을 worker에서 호출합니다.
2. `response.design`을 후보로 보관합니다. 이 시점에는 Approved와 Backend 채택 Design을 바꾸거나 A를 호출하지 않습니다.
3. Qt가 후보 화면을 갱신한 뒤 `preview_ready(request_id)`를 보냅니다.
4. 그 후보·metadata로 `review_design_candidate(kind="initial")`를 호출합니다.
5. MODIFY는 새 후보를 표시하고 같은 버전으로 다시 검토합니다. UNCLEAR는 텍스트 모드에서 새 검토 요청 ID로 답변을 기다립니다. 음성 검토에서 C의 재질문 후에도 불명확하면 D는 HOLD합니다. CANCEL/FAILED도 실행을 보류합니다.
6. APPROVE가 표시된 후보와 정확히 같을 때만 `approved_design`을 채택하고 A에 요청합니다. A 계획 검증/채택이 끝나야 `context.design`에 들어갑니다. 후보·사용자 승인·Backend 채택을 구분합니다.
7. 차이가 생기면 기존 승인 목표와 B가 확정한 Current/Difference를 C `run_intervention`에 전달합니다. KEEP은 기존 목표를 유지하고 기존 정리/재계획 절차를 따릅니다.
8. REVISE는 후보입니다. `kind="revised"`로 Preview→Review→APPROVE를 다시 거친 뒤 A Replan을 요청합니다. `previous_design`, `current`, `differences`, `design_metadata`를 함께 전달합니다.
9. 최초 후보는 v1, 새 Revised 후보는 승인 버전+1입니다. 같은 후보군의 MODIFY는 그 버전을 유지하며 검토 횟수는 metadata.review.round에 남습니다.

생성과 검토의 요청 ID, Job, B revision을 D에서 함께 확인합니다. 닫힌/중복/이전 후보 승인과 Current 변경 후 응답을 채택하지 않습니다. STOP은 C의 취소 Event를 설정하고 지연 결과를 무시합니다. 메타데이터를 여섯 배치 필드 안에 섞지 않습니다.

## 실행과 한계

```bash
# Qt 표시·실제 A 계산·C Mock·B 합성 관측·Robot FAKE
C_DESIGN_USE_LLM=0 QT_QPA_PLATFORM=offscreen python3 -m app.abd_input_hmi --synthetic-b --c-mode offline
```

후보가 표시되면 터미널에 출력된 `event=answer`의 새 request_id를 사용합니다. 명확한 승인 예시는 `좋아요`, `이대로 진행해주세요`입니다. MODIFY 후에도 다시 승인해야 합니다.

LIVE 음성은 `--c-mode live --c-voice`, `C_DESIGN_USE_LLM=1`이며 C가 TTS→beep→STT 전체를 소유합니다. LLM은 `OPENAI_LLM_API_KEY`, STT는 `OPENAI_API_KEY`, TTS는 `OPENAI_TTS_API_KEY`를 현재 터미널에 별도로 주입합니다. 키는 GitHub/로그/채팅에 넣지 않습니다. offline C Mock은 실제 음성을 열지 않으므로 음성 옵션과 혼용하지 않습니다. C의 무응답·의도 재질문 정책을 그대로 사용하며 HMI STOP으로 닫을 수 있습니다. TTS/STT 오류는 D의 진행 콜백 경계에서 보류하고 A/Robot 요청을 만들지 않습니다.

이 화면 시험은 B 합성 관측을 사용하는 기존 Day4 FAKE 경로입니다. 최신 B 생산자→D 검사 결과는 별도 [B Consumer](D_HMI_DB_ROUND1.md) 경로이며 이 둘을 중복 실행하지 않습니다. 이번 작업은 실제 Vision/Robot/마이크/LLM 네트워크 시험이나 REAL 음성 실행기 이행을 완료했다고 주장하지 않습니다. C handoff의 과거 “Expected는 D 관리” 표현보다 위 10/8 B 소유 계약이 우선합니다.

## 검증

실제 실행 결과는 [검증 보고서](../reports/c_stage3_ad_alignment_20261011/validation.md)에 기록합니다. C 자체 테스트와 D 호출 경계, 후보 수정/승인, 늦은 결과, 빨강 5층, 40/41 수량, Fake 공급 보충, HMI 표시/Schema를 구분해서 검사합니다. 기존 PC의 REAL 측정 파일 절대경로가 없는 테스트는 장치 검증 PASS로 집계하지 않습니다.
