# 최신 C 함수와 A–D–Qt 통합 시험

> 2026-10-07 적용: 현재 제품 목표는 [최종 MVP](10_FINAL_MVP.md)입니다. 아래는 기존 C 공개 함수·A PLACE 계획·D/Qt와 Fake/합성 입력의 연결 검사입니다. 커스텀 의자 대화와 사용자 확정 전체 경로·실제 직접 결착·사람 지지·최종 Vision·사용자별 웹 반영의 성공 증거로 확대하지 않습니다. 과거 기록과 현재 소스의 게시 상태도 구분합니다.

2026-10-06 로컬 준비. [C PR #11](https://github.com/suuuhululu/C-2/pull/11)은 main에 병합됐다. C 원본 head `4a0300e72ade26312a7889bd4829d3e2e75b4b61`, merge `f45e9f3afdea992256518d0686bf3eec7589dd9c`를 확인했다. 로컬에 없던 C 소스·문서·독립 검사·smoke scripts 29개를 head에서 바이트 그대로 가져왔다. C 알고리즘·모델·음성 구현은 수정하지 않았다.

A는 `f9b841c8f090b0b25c30ab27459781ad2017fd9e` 원본 `plan_from_current`, B는 `c75c80374b848a395fded62ad901020d06b92913` 합성 예시의 `deliver_example`을 사용한다. D는 로컬 `work/suhyun-hmi-backend-robot-db` HEAD `7af9daeb3812f9e87fb36f172293434fd827e42f` 기반 작업 파일이며 앞선 [D PR #12](https://github.com/suuuhululu/C-2/pull/12)에 이번 준비가 자동 포함되지는 않는다.

## 연결과 경계

- 텍스트 → 실제 C `create_initial_design(text, should_stop)` → D `on_initial_design` → 실제 A 계산 → D Design/Plan 동시 채택 → Qt 전체 목표 표시.
- RobotController/FakeRobotDriver 전달·복귀 → 합성 Observed를 B `deliver_example` callback으로 전달 → D Current/Expected 비교·Step 확인. 전달판 EMPTY는 시험 입력을 D `on_place`로 직접 전달한다. 실제 B 전달판 생산 callback이 아니다.
- 차이 → C `run_intervention(design, current blocks, differences, text_answers, on_question, should_stop)` → D `on_c_intervention` → 실제 A 재계획 → 새 Design/Plan 채택. C가 만든 질문 문자열을 Qt와 로그에 표시한다.
- D의 `{missing, unexpected, unobservable}`을 C의 `[{expected, actual}]`로 변환한다. 같은 x/y/layer에 유일하게 대응하는 값만 비교 쌍으로 묶는다. 다른 좌표·애매한 다중 값은 누락/추가를 각각 null과 함께 전달하며 물리 블록 이동·ID를 추정하지 않는다. 판별 불가를 의도 차이로 전달하지 않는다. 공통 Difference 저장 형식은 변경하지 않는다.
- C는 별도 thread에서 실행하고 Backend/Qt는 Qt thread의 signal 결과 처리로만 변경한다. request/job/version/revision·활성 상태가 달라졌으면 결과를 무시한다. STOP은 C `should_stop`에도 전달한다. 이미 전송한 HTTP 요청은 즉시 취소할 수 없으므로 C timeout/반환을 기다리며 새 C 호출과 재개를 중복 실행하지 않는다.
- 답변 없는 C 호출은 질문 미리보기로만 기록한다. 사용자 답변 한 개를 실제 C에 보내며, 응답 소진 시 UNCLEAR를 D에 반환한다. 두 번 불명확하면 D의 명시 선택을 기다린다. 자동 KEEP·자동 반복 호출은 없다.
- C FAILED/CANCELLED는 코드·사유를 유지해 보류한다. API 실패를 Mock 성공으로 대체하지 않는다. 사용자 취소는 현재 D에서 보류로 표시하며 별도 Job 취소 상태를 새로 확정하지 않았다.

## 키 없이 오프라인 시험

```bash
cd /home/ms-02/C_2
env -u QT_QPA_PLATFORM C_DESIGN_USE_LLM=0 python3 -m app.abd_input_hmi \
  --synthetic-b --c-mode offline --initial-text "의자 만들어줘" \
  --log-dir logs/c_ad_hmi_offline
```

실제 C 함수를 호출하지만 C의 기존 Mock 생성기를 사용한다. 저장 Initial/Revised JSON을 반환하는 이전 모드와 구분된다. 창만 열면 Job이 시작되지 않는다.

## 실제 gpt-4o 설계 생성 시험

[OpenAI 공식 안내](https://developers.openai.com/api/docs/quickstart)와 C `llm.py`를 확인했다. 키는 실행한 터미널의 환경변수에서 읽는다. 컴퓨터 전체 영구 설정은 필수가 아니며 현재 C는 `.env`를 자동 로드하지 않는다. 다른 터미널에는 이 설정이 자동 전달되지 않는다.

```bash
cd /home/ms-02/C_2
read -rsp "OpenAI API key: " OPENAI_API_KEY
echo
export OPENAI_API_KEY
export C_DESIGN_USE_LLM=1
export OPENAI_MODEL=gpt-4o
python3 -c 'import os; print("키 설정됨" if os.environ.get("OPENAI_API_KEY") else "키 없음")'
env -u QT_QPA_PLATFORM python3 -m app.abd_input_hmi \
  --synthetic-b --c-mode live --initial-text "의자 만들어줘" \
  --log-dir logs/c_ad_hmi_live
```

키를 화면·로그·JSON·소스에 적지 않는다. 이 명령의 HMI 시작은 실제 OpenAI 호출을 수행하므로 API 사용량이 발생한다. Robot은 여전히 FAKE다. `--c-mode live`는 키와 `C_DESIGN_USE_LLM=1`이 없으면 창을 열기 전에 오류로 종료한다. 설계 LLM 기본 모델은 C 코드의 gpt-4o-mini이며 이번에는 사용자 확인에 따라 OPENAI_MODEL로 gpt-4o를 선택한다. 실제 접근 권한·할당량은 해당 키/프로젝트에 달려 있으며 이번 오프라인 검사로 확인하지 않았다.

C PR #11의 음성 설정은 STT=whisper-1, TTS=tts-1이다. STT/LLM은 OPENAI_API_KEY, TTS는 OPENAI_TTS_API_KEY를 사용한다. 이 시험은 모든 공개 함수에 텍스트 인자를 주므로 음성·TTS 키·audio dependency가 필요 없다. 음성 모델 변경과 장치 연결은 이번 범위가 아니다.

## 화면에서 수행할 순서

1. HMI 시작을 누르고 C 호출/A 계산 후 전체 Design·현재 목표가 표시될 때까지 기다린다.
2. 터미널에 출력된 다음 입력이 `place_empty`이면 아래 한 줄을 입력한다. Fake 전달·복귀 후에는 `observe`를 입력한다. 매 Step마다 같은 순서를 반복한다. 슬롯 보충 대기면 HMI 해당 열 보충을 사용한다.

```json
{"event":"place_empty"}
{"event":"observe"}
```

위 두 줄은 각각 한 번씩 입력한다. 실제 블록을 확인하는 입력이 아닌 합성 시험 입력이다. 마지막 observe 전에는 전체 완료가 표시되면 안 된다.

3. 불일치 시험은 현재 목표 여섯 값을 복사한 뒤 원하는 실제 색상/좌표로 바꿔 `{"event":"observe","actual":{...}}`를 입력한다. 예전 저장 Design의 S09 목표가 (9,9), 2층, 노랑 6점/90°일 때 예시는 아래와 같다. LIVE 생성 배치·Step 수는 매번 다를 수 있으므로 이 예시 좌표를 무조건 입력하지 않는다.

```json
{"event":"observe","actual":{"brick_type":"2x3x1","color":"blue","x":9,"y":9,"layer":2,"orientation_deg":90}}
```

4. C 질문을 확인하고 터미널이 출력한 활성 `request_id`를 포함한 answer 한 줄을 사용한다. 첫 질문의 1번=KEEP, 2번=REVISE다. escalation 질문은 C가 표시하는 선택지 의미를 따른다. 예: `{"event":"answer","request_id":"출력된 ID","text":"2번"}`. UNCLEAR 뒤 ID가 바뀌면 새 ID를 사용한다. KEEP이 PLACE만으로 불가능하면 사람 정리 보류가 정상이다.

5. Revised도 A가 승인할 때만 전체 미리보기가 바뀐다. 새 전달판 EMPTY 전에는 다음 전달을 시작하지 않는다. 실제 Camera/Robot 성공으로 해석하지 않는다.

## 로컬 검증 기록

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/integration/test_c_function_hmi.py -q
QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q
```

새 연결 검사 **16 passed**. 전체 **1206 passed / 21 skipped**, 종료 코드 0. skips는 별도 DB 서비스/설정 관련이며 이번 C 연결 시험은 모두 실행했다. 실제 C main/designer/validator/LLM 코드와 A, D, Qt, B 예시 callback을 실행했고 HTTP 경계만 Fake로 바꾼 LIVE 경로 검사도 포함한다. 실제 키·네트워크·마이크·스피커·Camera·Robot은 사용하지 않았다. 린트/type check는 기존 미구성이며 새 도구를 설치하지 않았다.

정상 15 Step은 최종 관측 후에만 완료. HTTP Fake의 Initial/S09 색상 차이/Revised는 Current 9개·revision 9를 보존하고 실제 A Remaining 10 Step, 최종 19개·revision 19를 확인했다. KEEP은 WAIT_CORRECTION, 명시 취소·키 누락/401·지원하지 않는 최초 목표는 HOLD. UNCLEAR는 자동 진행 없이 명시 선택 대기. STOP/Current revision 변경 중 C 결과·중복 결과는 진행을 바꾸지 않았다. HMI 목표·질문·완료, snapshot 파일과 C_CALL_STARTED/C_CALL_RESULT/PLAN_RESULT/STEP_CONFIRMED 등의 JSONL을 확인했다.

결과는 로컬 검증 폴더 (`logs/c-live-preparation/`, 로컬 산출물)의 import-manifest.json·new-tests.xml·full-tests.xml·summary.json에 보관한다. 로그 폴더는 Git 제외이며 다른 clone에는 없다. 실행한 HMI Job의 JSONL/snapshot은 위 명령의 log-dir에 저장된다. 실제 gpt-4o API 접근·응답 품질, 음성, B 생산 관측, REAL Robot/STOP·재개, 전체 실기 시연은 미검증이다. 이번 변경은 GitHub 게시하지 않았다.

## 2026-10-06 — 마이크 STT·질문 TTS와 Fake Robot 시험

사용자 승인 범위는 마이크 입력 → C Design → 실제 A → D/Qt·Fake Robot → 차이의 질문 음성 → 마이크 답변이다. D 연결부에 명시적인 `--c-voice`를 추가했다. C PR #11의 `voice.listen/transcribe/speak`, `create_initial_design`, `run_intervention(text_answers=...)`와 A `plan_from_current`를 재사용하며 C 원본은 수정하지 않는다. 음성 없는 기존 실행은 그대로다.

Robot은 `FakeRobotDriver`로 고정하고 Camera는 연결하지 않는다. 합성 관측은 B PR #10의 `deliver_example`을 통과한다. 전달판 입력은 시험용 D `on_place`이며 B의 실제 전달판 생산 callback이 아니다. 음성 응답을 조립 완료 증거로 사용하지 않는다. 화면의 FAKE는 Robot 공정 모드이며 이 실행의 STT/TTS/LLM은 실제 API를 사용한다. 질문 음성은 **AI 생성 음성**이다.

### 키와 실행

현재 터미널에 키가 없다면 각각 입력한다. 입력 중 문자가 표시되지 않는 것이 정상이다. STT/설계에는 `OPENAI_API_KEY`, TTS에는 C 원본의 별도 `OPENAI_TTS_API_KEY`를 사용하며 서로 자동 대체하지 않는다. 키 값을 채팅·로그·소스에 붙이지 않는다.

```bash
cd /home/ms-02/C_2
read -rsp "STT/설계 API key: " OPENAI_API_KEY
echo
export OPENAI_API_KEY
read -rsp "TTS API key: " OPENAI_TTS_API_KEY
echo
export OPENAI_TTS_API_KEY
export C_DESIGN_USE_LLM=1
export OPENAI_MODEL=gpt-4o
export OPENAI_STT_MODEL=whisper-1
export OPENAI_TTS_MODEL=tts-1
export OPENAI_TTS_VOICE=alloy
env -u QT_QPA_PLATFORM python3 -m app.abd_input_hmi \
  --synthetic-b --c-mode live --c-voice \
  --log-dir logs/c_ad_voice_live
```

이미 두 환경변수가 설정되어 있다면 read 부분은 생략한다. ROS 설정·Robot 접속·실제 제어 프로세스는 이 시험에 필요 없다. C 모델 기본값을 유지하고 설계 LLM만 사용자 지정 gpt-4o로 설정한다. 공식 [STT 안내](https://developers.openai.com/api/docs/guides/speech-to-text)와 [TTS 안내](https://developers.openai.com/api/docs/guides/text-to-speech)를 확인했다. 실제 키별 모델 권한·할당량과 마이크/스피커는 사용자 환경에서 별도 확인해야 한다. `--c-mode offline --c-voice`도 음성 API는 LIVE이며 Design LLM만 Mock이다.

### 현장 입력 순서

1. HMI **시작**을 누른 뒤 녹음 안내가 나오면 8초 안에 “의자 만들어줘”라고 말한다. 발화 끝의 약 1초 무음을 감지하면 STT로 전달한다. 인식한 문장은 HMI 안내와 터미널·JSONL에 표시된다. `--initial-text`의 문장을 음성 입력 대신 사용하지 않는다.
2. C 후보와 실제 A 검증이 성공하면 전체 Design·현재 Step이 표시된다. 설계가 있어도 전달판 확인 입력 전에는 Fake 전달을 시작하지 않는다. 다음 입력 안내에 맞춰 아래 JSON 한 줄을 같은 터미널에 입력한다.

```json
{"event":"place_empty"}
```

3. Fake 전달·observe point 복귀 뒤 정상 조립 관측은 `observe`, 질문 음성을 시험할 색상 불일치는 `observe_wrong_color`를 입력한다. 한 Step에서 둘 중 하나만 선택한다.

```json
{"event":"observe"}
```

```json
{"event":"observe_wrong_color"}
```

`observe_wrong_color`는 현재 목표의 종류·좌표·층·방향을 유지하고 노랑↔파랑 색상만 바꾼 **합성 실제 배치**를 만든다. 원래 목표가 무엇인지 모르더라도 질문 경로를 시험할 수 있다. 원본 Design은 수정하지 않으며, D가 차이와 Current를 채택한다. 정상 Camera 관측이나 실제 오배치 증거가 아니다.

4. 화면과 같은 C 질문을 스피커로 재생한 뒤 답변 녹음 안내가 나온다. 첫 질문의 “1번”은 기존 목표 유지, “2번”은 현재 배치를 보존하는 수정 설계, “취소”는 보류다. 이후 escalation 질문은 들리는 선택지 의미를 따른다. 질문 재생 중 답변을 말하지 않는다. 이 모드에서는 터미널 `answer`를 섞지 않는다.
5. KEEP이 실제 색상 수정을 요구하면 사람 정리 보류가 정상이다. REVISE는 C 후보·최신 Current를 실제 A가 검증한 뒤에만 채택한다. 새 전달판 EMPTY 없이는 다음 Fake 전달을 시작하지 않는다. 정상 조립은 `place_empty` → Fake 전달 → `observe` 순서로 계속하며, 해당 공급열 보충 보류 때 기존 HMI 보충 버튼을 사용한다. 최종 observe 후에만 전체 완료다.

첫 UNCLEAR는 D가 발급한 새 요청 ID와 설명 질문으로 음성 응답을 한 번 더 받는다. 계속 불명확하면 녹음·질문을 자동 반복하지 않고 기존 KEEP/REVISE 버튼으로 명시 선택을 기다린다. 무음·STT/TTS 오류는 실패/사유를 유지해 HOLD하며 다음 전달이나 Mock 성공으로 바꾸지 않는다.

STOP/창 닫기/Current revision 변경은 늦은 결과의 채택과 후속 C/A 진행을 취소한다. C 원본의 이미 시작한 녹음·HTTP·재생을 즉시 중단하는 기능은 없으므로 반환까지 시간이 걸릴 수 있다. 이전 C 호출이 끝나기 전 시작·재개는 보류한다. 실제 Robot STOP·재개 시험이 아니다.

### 이번 로컬 검증

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  tests/integration/test_c_voice_hmi.py tests/integration/test_c_function_hmi.py \
  tests/integration/test_abd_input_hmi.py tests/integration/test_abd_callback.py \
  tests/integration/test_a_backend.py tests/unit/test_qt_hmi.py \
  tests/unit/test_hmi_current.py tests/unit/c_design planning_trial/test_planner.py -q
```

새 음성 연결 **16 passed**, 관련 기존 검사 포함 **581 passed**, 종료 코드 **0**. 녹음 PCM·음성 HTTP·스피커 경계와 설계 HTTP만 Fake로 대체하고 실제 C 음성 인코딩/디코딩·C 해석/검증·A·D·Qt·B 예시 callback을 호출했다. 검사 전체에서 실제 audio device/network 접근은 차단한다. 녹음 전 무호출, 재생 완료 후 응답 녹음, 정상 관측 후 완료, REVISE Current 보존·Remaining 14, KEEP 정리 대기·취소, 두 UNCLEAR 후 선택, 무음·장치·401/403·지원하지 않는 목표, STOP과 Current 변경 중 늦은 결과 무시를 확인했다. HMI 질문과 발화문 일치, Current/목표/표 표시, JSONL 및 snapshot, 키 값 미기록도 검사했다.

증거 색인 (`logs/c-voice-preparation/summary.json`, 로컬 산출물), Mock 음성 질문 화면 (`logs/c-voice-preparation/voice-question.png`, 로컬 산출물). 이 환경에는 API 키가 없고 실제 마이크·스피커·OpenAI API 호출은 실행하지 않았다. 마이크 품질·한국어 STT 정확도·TTS 청취·API 모델 권한·실제 Camera/Robot·운영 모니터는 미검증이다. GitHub 게시·커밋·PR·merge는 수행하지 않는다.


## 2026-10-06 — REAL 오배치 질문 음성 연결 (로컬)

사용자 요청으로 REAL `app.real_workflow_hmi --c-mode live --c-voice`에도 기존 CTextConnection의 intervention 경로를 연결했다. 초기 목표 STT뿐 아니라 오배치 Current/Difference → 실제 C 질문 → TTS → 답변 STT → KEEP/REVISE → 실제 A 재계획을 호출한다. 실제 API/음향·Robot 실행 경계는 Mock으로 검사했고 C 음성/의도/설계 알고리즘을 대신 구현하거나 수정하지 않았다.

REAL 입력은 현장 수동 확인이며 B 합성 callback 또는 실제 Camera를 통한 인식이 아니다. 재계획 후 기존 Current와 공급 순서를 보존하고 다음 실제 전달 전에 새 EMPTY 확인을 받는다. STOP/Current 변경 뒤 늦은 음성 결과·TTS 실패·두 UNCLEAR를 기존 D 정책대로 처리한다. 키 값은 JSONL에 넣지 않는다.

[최신 실행·키·단축 입력·사람 정리·STOP/재개 안내](D_BACKEND_RUN_ROBOT_PLAN.md#2026-10-06--real-정지재개와-오배치-질문-tts), 검사/Mock 화면 (`logs/real-stop-resume/summary.json`, 로컬 산출물). 실행 중인 이전 창에는 자동 적용되지 않으며 종료 후 Job 복원은 지원하지 않는다. 실제 장치/마이크/스피커/API 시험은 별도로 남아 있다.
