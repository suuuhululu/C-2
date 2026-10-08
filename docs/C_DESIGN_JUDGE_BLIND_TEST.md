# C Design Revised judge 모델 Blind Test

2026-10-08

## 목적

Revised Design judge(`app/c_design/llm.py`의 `judge_revised_design`) 모델을 정하기 위해 두 judge 모델의 판정을 사용자의 블라인드 평가와 비교했습니다. 결과에 따라 Stage 2 judge 기본 모델을 `gpt-4.1-mini`(`llm.DEFAULT_JUDGE_MODEL`)로 두고, 환경 변수 `OPENAI_JUDGE_MODEL`(`llm.JUDGE_MODEL_ENV`)로 되돌릴 수 있게 했습니다([계약 §8.13](C_DESIGN_CONTRACT.md)).

## 방법

- 대상: After 구조(설계 의도 단계 없이 Revised Design을 바로 생성) v2 Revised Design 10개.
- 익명화: 10개 Design을 익명 A~J로 표시했습니다.
- 사용자 평가: 사용자가 A~J를 블라인드로 보고 만족 / 살짝 불만족 / 불만족으로 평가했습니다.
- judge 비교: 같은 입력을 두 judge 모델(`gpt-4.1-mini`, `gpt-6.1-sol`)에 보냈습니다.
- 측정: 사용자 평가와 judge 판정의 일치율(strict / lenient), false negative·false positive, judge 호출 latency.

## 결과(원문)

사용자 평가: 만족 A, C, D, E, F, I, J / 살짝 불만족 B / 불만족 G, H.

gpt-4.1-mini: 10/10 SHOWCASE, strict 사용자 일치율 70%, lenient 80%, 평균 judge latency 4.9 s, false negative 0, false positive 2~3.

gpt-6.1-sol: strict 80%, lenient 90%, 평균 judge latency 20.5 s, false negative 0, false positive 1~2.

최종 사용자 결정: "Sol이 판정 정확도는 조금 더 높았지만, 현재 사용자가 직접 본 Design 품질은 충분했고, 약 15초 이상의 judge latency 차이를 고려해 Stage 2에서는 gpt-4.1-mini judge를 선택한다. 실물 테스트 후 필요 시 재검토한다."

Judge는 최종 물리 안전 판정기가 아니라 Design 품질 보조 필터이며, 이번 선택은 Stage 2 소프트웨어/시연 기준의 실용적 선택이다.

## 자료 위치

- `~/c_judge_blind`, `~/c_before_after_ab`: 사용자 로컬 실험 자료입니다. 이 저장소에 포함하지 않으며 저장소 테스트·검증 결과가 아닙니다.

## 적용 범위

- judge 모델만 바뀝니다. Design 생성·Initial·답변 해석·Initial 설명 모델은 `OPENAI_MODEL`(없으면 `llm.DEFAULT_MODEL`) 그대로이고, key는 `OPENAI_LLM_API_KEY` 그대로입니다.
- 위 결과는 소프트웨어 Design 10개에 대한 비교이며 실물 조립 결과가 아닙니다. 실물 테스트 후 재검토합니다.
