> **9/22 구현 기록:** 당시 후속 수정은 [REAL HMI 통합 연결 수정](HMI_REAL_INTEGRATION_FIXES_20260922.md)에 있다. 2026-09-23 `main`의 실행 조건은 [현재 인터페이스](INTERFACE_GUIDE.md)와 [백엔드 실행 안내](../backend/README.md)를 따른다. 이 기록의 공통 Result 단절은 후속 PR #67 반영 전 상태다.

# HMI REAL 실기 시험 연결 변경 · 2026-09-22

기준 origin/main `c29de08`, 작업 브랜치 `codex/hmi-partial-integration`. 사용자 지시에 따라 신뢰도에 따른 일괄 거절을 HMI에서 제거한다. 아래는 HMI 구현과 다른 담당 PR의 연결 계약이며, 전체 실기 완료 기록이 아니다.

## 결정·범위

REAL 준비 → 측정 원본 저장 → 실행 설정과 실측 기하 조립 → BIND_SNAPSHOT → GeneratePath → 미리보기 → 별도 ExecuteProcess → 실제 상대 결과 표시. 운영자 입력은 PNG/JPEG다. ZIP 등록/교환은 운영 절차에 넣지 않는다.

HTTP GenerateInput/RunInput이 REAL과 SIMULATION을 받되 현재 게이트웨이 모드와 같아야 한다. 공통 ROS 타입과 schema_version=2는 그대로다. RosBridge의 MEASURE 전용 차단을 제거했다. ESTIMATED/FORCE_CONTACT_ESTIMATE 결과는 신뢰도 원문을 보존하며 BIND에 전달한다. VERIFIED로 바꾸지 않는다. BIND 거절/생성 실패/실행 검사 실패는 상대 결과 그대로 표시한다.

## 서버 설정 (운영자 업로드 아님)

기존 `C2_PREPARATION_CONFIG`는 측정 설정이다. 그 안의 `execution_profile` 객체에 담당자가 관리하는 REAL 경로·가공 설정을 넣거나, 별도 파일을 `C2_EXECUTION_PROFILE` / launcher `--execution-profile`로 지정한다. 별도 파일은 서버가 원본을 저장하고 준비 설정에 결합해 해시를 발급한다. 준비와 가공 설정이 같은 등록 자산에 연결된다. 파일명/contract 이름으로 승인 여부를 추측하지 않는다.

execution_profile은 공정 node.py의 REAL 실행 설정 배치를 사용한다:

- `schema_version=2`, `source_mode=REAL`, `frame_id=c2_base`, `gripper_open_allowed=false`
- `contract`: 경로 담당 PR이 지원하는 실제 이름을 그대로 사용. 최신 main 688c781의 `/4`는 calibration_status가 필수가 아니므로 HMI도 강제하지 않음. HMI에서 `/3` 등 특정 이름으로 강제하거나 미리보기 상태로 덮어쓰지 않는다.
- `test_only=false`, `real_execution_allowed=true`: 담당자가 공급하는 실행 후보 설정의 용도. 최종 검사 합격을 의미하지 않는다. 기존 파일의 값을 HMI가 자동 변경하지 않는다.
- workcell/tool/TCP/load/tools_config ID 및 version
- `surface`: kind, 축·u 원점·이음매·도달각 등 경로 설정. 반지름·높이·축 원점·작업 범위는 이번 측정으로 갱신.
- `execution_context`: source_mode, motion_profiles, tool_profile, stop_profile
- `joint_check_arguments`: limits_deg, j6_margin_deg
- `tip_calibration.offset_tool_m`: 측정 설정 workcell.tool_offset_m과 일치

현재 main의 workpiece_real_trial_0921.json은 측정 설정이며 이 실행 설정 전체를 포함하지 않는다. 없는 속도·깊이·관절 한계를 HMI가 생성하지 않는다. 담당 PR의 실행 설정을 배포 때 연결해야 한다. 설정 누락 시 측정 원본을 보관하고 구체적인 설정 오류를 표시한다.

## 스냅샷 조립·기록

측정 Result의 성공·geometry_ready·partial=false·stop_confirmed, 출처·시각·8점, 높이/바닥/작업 범위 일관성을 확인한다. PrepareWorkpiece의 work_v_range_m은 계약상 TOP/DOWN이며 바닥 기준 `[ (H-v_max)*1000, (H-v_min)*1000 ]`으로 한 번 변환한다. 측정 중심·반지름·높이·윗면·바닥을 workcell과 surface에 함께 반영한다.

`measurement_status`, `measurement_assumptions`, `contact_calibration`에 신뢰도와 오프셋 원본 설정을 남긴다. `absolute_top_verified`는 현재 Action 필드가 아니므로 결과에 없으면 null(미전달)이다. 미전달을 false나 VERIFIED로 추정하지 않는다. 측정 원본·입력 설정·최종 스냅샷은 ID/해시로 연결한다.

## 산출물·실행 전송

REAL 경로/미리보기/보고서의 모드, 경로 ID/버전/해시, 스냅샷 ID/해시, 도구 설정, 좌표 대응을 검사한다. 실행 후보의 path와 preview에는 `test_only=false`, `real_execution_allowed=true`가 일치해야 한다. 기존 /3의 nested real_preview도 읽되 원본은 수정하지 않는다. 이때 상대가 남긴 실행 제한을 화면에 표시한다.

BOUND_ROS, 현재 준비·설정 일치, 신선한 상태, ExecuteProcess 서버 준비를 확인하고 동일 경로를 전달한다. OUT_OF_LIMITS·상대 execution_blocked·미리보기 전용 파일·MOCK 전용 파일은 실행 요청으로 바꾸지 않는다. 세은/홍동 PR에서 실행 후보가 생성돼야 연결된다. HMI가 IK·간섭 검사를 대신 수행하거나 통과시켜 주지는 않는다. 취소 후 늦은 성공, 재측정, 연결 세션 변경에 의한 무효화는 유지한다.

## 담당 PR 반영 순서

1. 수현 HMI 변경 검토.
2. 홍동 REAL 실행 후보 산출물, 세은 ESTIMATED 조건 검사/BIND·실행 연결, 시율 실행 제어 PR을 같은 계약으로 대조.
3. 팀장 검토·승인 후 같은 커밋의 타입/노드를 빌드해 대역 시험 → 현장 실기 시험.

PR 승인/병합과 실기 실행은 이번 HMI 수정 작업에서 수행하지 않는다. 기존 연결 명령은 HMI_PROCESS_CONNECTION_20260922.md를 따르며, HMI 실행 전에 `C2_EXECUTION_PROFILE`을 실제 배포 설정 경로로 지정한다. 경로 노드는 홍동 PR의 실행용 설정으로 별도 기동한다.

## 전달할 Slack DM

세은님·홍동님·시율님, 수현 담당 HMI부터 REAL 준비 → BIND → 경로 생성 → 미리보기 → 실행 요청 흐름으로 수정하겠습니다. ESTIMATED라는 이유로 일괄 차단하지 않고 측정 신뢰도와 출처는 그대로 보존하겠습니다. 운영자는 PNG/JPEG만 입력하고 설정 JSON·스냅샷·해시는 시스템 내부에서 연결합니다.

지금은 실제 로봇으로 깊이·곡면 이동·접근·이탈을 확인하는 것이 급합니다. 초기 미리보기 단계의 제한 때문에 제어 시험 진입이 막히는 부분을 정리하려는 변경입니다. 제어권·정지·최신 상태·경로 무결성과 최종 동작 검사는 유지합니다.

각 담당 수정 PR이 올라오면 HMI와 입력·출력 계약을 대조해 검토·승인하고, 병합된 같은 기준으로 빌드한 뒤 통합·실기 시험을 진행하겠습니다. 실행용 가공 설정도 코드와 함께 포함해 주세요. 구현되지 않은 검사는 완료로 표시하지 말고 PR에 명시해 주세요.

## 검증 결과

- 백엔드 전체: 134 passed, 4 skipped (ROS 설치/실행 환경 조건). 대역 시험이며 실기 아님.
- ESTIMATED 상태 보존·BIND 성공/거절·REAL 생성 전송·REAL 실행 후보 전달·상대 검사 실패 표시·작업 범위/미리보기 제한·모드 불일치 확인.
- 실제 c2_path REAL 미리보기 산출물 읽기 및 실행 후보 산출물 형식 대역 검사 확인.
- TypeScript 검사, Vite 빌드, 저장소 검사, Git hook 8개, Issue manager 27개, 설정 형식·diff 검사 통과.
- 샌드박스 TestClient 이벤트 루프 대기는 로컬 대역 시험으로 재실행했다. 프런트 빌드와 백엔드 시험의 산출물 경합은 빌드 후 순차 시험으로 해소했다.
- 결과 커밋 없음: 작업 브랜치 미커밋 상태. push/PR/승인/병합, 실제 DDS 연결·로봇 구동 미수행.
