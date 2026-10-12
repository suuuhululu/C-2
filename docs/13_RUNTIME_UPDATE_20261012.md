# 현재 시험 코드 통합 업데이트 — 2026-10-12

## 기준과 보존

PR #24의 B 수정은 `codex/integration-round1`에 merge commit `8914320`으로 반영됐다. 이 업데이트는 그 이후의 `codex/current-runtime-update-20261012`에서 현재 ms-02 C/A/D·HMI·DB 시험 코드를 합친다. 원래 `/home/ms-02/C_2` 작업 브랜치와 외부 로봇 개발 폴더는 전환·덮어쓰지 않았다. 원본 소스와 웹 자산은 별도 ZIP으로 보존했다. 업데이트 PR 병합 전에는 integration 원격에 이 변경이 들어갔다고 해석하지 않는다.

최신 책임은 [10/11 기준](12_INTEGRATION_SYNC_20261011.md)과 [확정 인터페이스](handover/final_mvp_interface_20261008/README.md)를 유지한다.

| 담당 | 이번 업데이트 | 유지할 경계 |
|---|---|---|
| A / 세은 | 현재 공급 TCP·조립 TCP·경로 계산 보정 코드 보존, 세 계산 adapter 호출 연결 | Plan·도움·경로 계산; 결과는 실행 권한 없는 후보. `SEARCH_LIMIT` 해결은 아직 없음 |
| B / 홍동 | #24 생산자·INITIAL/FINAL 근거 보완 유지; 새 모의 진입점에서 실제 B 함수 호출 | Expected/Difference 비교와 Current/revision 확정은 B. D 재비교·revision 재발급 없음 |
| C / 시율 | 현재 설계 변경 요청·검사 문맥 전달 확장 보존 | Candidate → HMI Preview → C Review → APPROVE 후 A. MODIFY·STOP·옛 응답 검사 유지 |
| D / 수현 | 별도 로봇 프로세스, 진행부, 승인·재개·제스처·공급 슬롯 순환 코드 포함 | 실물 실행·정지 확인·Contact·인계·복구 판단 담당. 명령 성공만으로 조립 완료 처리 안 함 |
| HMI / 수현 | 한 화면의 설계·Current·Expected·실행·차이·도움·저장 표시, C 답변·재검사 연결 | B 결과를 표시하며 공간 판단 안 함. 미승인 설계를 승인 목표로 채택 안 함 |
| DB·웹 / 수현 | JSONL 개인 저장·로그인·웹 자산 코드 포함 | 조립 종료/저장/웹 반영 분리. 저장 실패로 로봇 재실행 안 함 |

## 진입점 선택

`app.mvp_integration`은 실제 A/B 계산 함수와 C 호출 경계, D 진행·Qt·JSONL, **MOCK Robot 및 합성 영상/제스처**를 연결한다. 실제 Camera/Robot 전체 통합 진입점이 아니다. DB는 별도 설정 시 연결한다.

`app.cad_real_trial`은 현재 실물 시험에 사용한 C→A→D 흐름이다. **B를 호출하지 않으며**, 실행한 목표를 누적 표시할 뿐 실제 Current·조립 완료·DB 저장을 확정하지 않는다. 승인 설계를 임의로 다른 샘플이나 층별 Plan으로 바꾸지 않는다.

`robot_control_integration/`에는 ZIP 밖에서 수정하며 사용하던 D 소스를 함께 보존했다. 내부 `app` 이름이 C-2와 겹치므로 이 디렉터리를 작업 위치로 하는 **별도 프로세스**에서 실행한다. 두 `app` 패키지를 같은 Python import 경로에 겹쳐 넣지 않는다.

기존 `real_workflow_hmi`/Day4 전달 시험은 별도 진입점이다. 최종 MVP의 B 결과 소비와 기존 Day4 공간 비교를 동시에 실행하지 않는다.

## 장치 없는 재현

저장소 루트에서 실행한다. `C_DESIGN_USE_LLM=0`은 외부 LLM 호출을 끈다. 아래 명령에는 REAL 실행 옵션이 없다.

```bash
C_DESIGN_USE_LLM=0 python3 -m app.mvp_integration \
  --robot-root "$PWD/robot_control_integration" \
  --design interfaces/fixtures/mvp_fake_design.json \
  --log-directory logs/mvp-integration
```

HMI 시작 → 합성 INITIAL → C 후보 미리보기 → C 답변 `좋아요` → A 계획 → MOCK D 실행/준비 신호 → B Step/Final 판정 순으로 확인한다. 실행 안내의 FAKE 표시를 실물 결과로 해석하지 않는다.

환경별 의존성: Qt는 `requirements.txt`, 검사 도구는 `requirements-test.txt`, PostgreSQL은 `requirements-history.txt`, B 영상은 `perception/` 각 요구 파일, 실제 D는 ROS2 Jazzy·Doosan DRCF2·RG2/Modbus·제스처 모델이 필요하다. 기존 측정·보정 자료를 재사용하며 환경 설정만으로 실물 검증이 끝나지 않는다. `jsonschema`와 참조 처리 의존성도 함께 설치된 환경에서 검증한다.

실제 음성 시험은 `scripts/c_models.env.example`을 먼저 읽고 모델 환경변수를 적용한다. API 키 세 개는 별도 비공개 환경에서 제공하며 저장소에 포함하지 않는다. C 소스 기본 모델과 환경에서 지정한 모델은 다를 수 있으므로 실행 환경의 `OPENAI_MODEL`을 확인한다. 시험 실행 절차는 [현재 C→A→D 안내](D_CAD_REAL_2X2_RUN_GUIDE.md), 전체 모의 흐름은 [MVP 안내](D_MVP_INTEGRATION_20261011.md)를 참고한다.

## 현재 로봇 설정의 의미

현재 소스는 집기 전 55mm / 닫기 명령 35mm / 체결 후 개방 48mm, 개방 피드백 44mm 초과, 공급판 파지 패드 하단 5mm, pre-contact 약 20mm, XY 허용 2mm, 35N 체결 시험 설정을 보존했다. 이 값은 현재 시험 설정이며 모든 블록·층의 체결 성공 증명이 아니다. 각 종류의 슬롯은 1~6 사용 후 1로 순환하고 항상 보충된다는 운영 전제를 따른다. 설계 최대 40블록은 별도 제한이다.

현재 C→A→D 로봇 단독 시험의 엄지척은 pre-contact 정렬·준비 확인, 편 손은 STOP 요청이다. 사람 인계용 제스처 코드는 별도 흐름이며 편 손 STOP과 그리퍼 개방을 혼동하지 않는다. 현장 settings 아래 과거 세션/프로필은 기존 시험 근거다. 새 실행 승인·최신 상태로 자동 재사용하지 않는다.

드라이버의 Release 빌드에서 버전 조회가 assert와 함께 제거되던 기존 수정은 `robot_control_integration/driver/`에 패치와 원본 commit/해시로 보존했다. 패치는 Doosan `31750d6` 기준이다. 해당 소스 확인 후 별도 DRCF2 빌드·환경 선택이 필요하며 이번 업데이트에서는 재빌드·재시작하지 않았다. `scripts/cad_trial_ms02.sh`와 `roboton2.launch.py`는 현재 ms-02 기존 경로를 사용하는 현장 실행 도구다. 다른 환경에서 그대로 실행하지 말고 ROS overlay·robot root·설정 경로를 확인한다.

## 통합 병목과 검증의 한계

1. **A 전체 계획 SEARCH_LIMIT:** C가 승인한 26블록·5층 설계에서 전체 순서 탐색이 한도에 도달했다. 설계 승인 실패나 재고 부족이 아니다. 세은이 현재 A 소스로 원시 반환·탐색 원인을 확인해야 한다. 임의 Plan으로 대체하지 않았다. 이 보류는 실행 중 재개 버튼으로 해결되지 않는다.
2. **D 정밀 체결:** 현재 native press 경로와 별도 XY·각도 탐색 기능이 자동으로 합쳐졌다고 볼 수 없다. 전체 팔 IK/충돌, 집기 오차, 층별 최종 Z·완전 체결과 개방/후퇴는 실물 검증이 남았다. 35N 도달만으로 완전 체결을 선언하지 않는다.
3. **B 실영상 연결:** 모의 생산자→D→HMI/JSONL 경로와 실제 Camera·보정·전체 실물 흐름은 별도다. INITIAL 일부 영역만 확인하거나 FINAL 새 근거가 없을 때 보류하는 #24 정책을 유지한다.
4. **DB/웹:** 이번 실행에서는 실제 PostgreSQL을 연결하지 않았다. DB가 없을 때 해당 검사는 건너뛴다. 현재 모의 DB 설정 경로는 시작 전 제작자 로그인 정책을 포함하며, 초기 논의의 저장 시 로그인 정책과 다른 부분은 팀 확인 대상이다.
5. **기존 음성 시험:** PR24 기준에서도 실패하는 구형 음성 Mock/Stage3 승인 전제의 검사가 남아 있다. 전체 pytest 통과를 주장하지 않는다. 외부 LLM/STT/TTS, 장치 연결 시험은 이번 검증에 포함하지 않는다.

실행한 검사 결과는 [STATUS](STATUS.md)의 2026-10-12 항목에 기록한다. 서로 중복되는 검사 수를 합쳐 고유 검사 수로 보고하지 않는다.
