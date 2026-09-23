# REAL HMI 통합 연결 수정 · 2026-09-22

> **9/22 통합·검증 기록:** 아래 명령과 수치는 당시 PC·브랜치 기준이다. 2026-09-23 `main`은 제어기 prefix와 하드웨어 관측을 후속 보완했다. 현재 실행은 [백엔드 실행 안내](../backend/README.md), [공정 패키지](../ws_cobot1/src/c2_process/README.md)를 먼저 확인한다.

기준 main `e949430` (PR #65·#66·#67 포함), 브랜치 `codex/hmi-real-integration-fixes`. HMI 담당 변경이며 공통 Action·공정·경로 계산 코드는 변경하지 않았다. INTERFACE_GUIDE, SYSTEM_STRUCTURE, INTERFACE_RECOMMENDATION과 HMI_REAL_EXECUTION_20260922의 기존 MEASURE → 원본 저장 → 스냅샷 → BIND → 경로 → 별도 실행 요청을 유지한다.

## 변경 사항

- `real_execution_config.validate_real_execution_config()`를 측정 요청 전과 최종 스냅샷 조립에서 공통 사용한다. 실행 설정 ID·모드·TCP/하중 일치, 도구 오프셋 일치, 접촉 오프셋 기록, 이동 프로파일 4종과 속도·가속도·완료 제한시간, 가공 방식·깊이/접촉 설정·이격거리, 정지 제한시간, 관절 범위의 정적 누락/형식 오류를 검사한다. 실제 동작 가능 판정과 최종 관절 검사는 공정 노드 책임이다.
- `C2_EXECUTION_PROFILE` / `--execution-profile` 또는 기존 측정 설정 내부 `execution_profile`을 그대로 사용한다. 작업자 JSON 업로드는 추가하지 않았다. 누락은 `preparation.start_error`와 화면에 표시하며 새 MEASURE를 보내지 않는다. 이미 접수된 동일 요청 조회는 유지한다.
- `absolute_top_verification_known`과 `absolute_top_verified`는 이번 Result 값으로 최상위와 `measurement_assumptions`를 모두 갱신한다. known=false/verified=false는 미확인 원본으로 보존하며, 필드 자체가 미전달이면 null이다. 템플릿의 true/false를 재사용하지 않는다. validity와 접촉 오프셋 근거는 별개로 보존한다.
- 실제 설치된 `PrepareWorkpiece.Result`에 두 bool 필드 중 하나라도 없으면 HMI에 계약 불일치를 표시하고 측정 전에 차단한다. 새 필드나 확인 결과를 HMI가 생성하지 않는다.
- ROS HMI 실행기가 SIM과 REAL 모두 경로 서버를 기동한다. REAL에는 `source_mode:=REAL`, `allow_real_execution:=true`, HMI와 동일한 `managed_data_dir`를 전달한다. `--external-path-node` 지정 시만 별도 기동한다. 경로 서버 기동은 로봇 모션을 실행하지 않는다.

## 한 PC 실행 구성

동일 커밋으로 c2_interfaces/c2_path/c2_process를 Jazzy에서 빌드·source하고 backend/frontend 의존성을 설치한다. 아래 시스템 배포 파일 경로와 domain은 실제 배포 환경에서 정한 값을 사용한다. 예시 자체가 실기 설정값을 승인하지 않는다.

모든 터미널에서 같은 설정을 사용한다:

```bash
export ROS_DOMAIN_ID=20
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export ROS_STATIC_PEERS=''
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
# 이전 셸의 ROS_LOCALHOST_ONLY 대신 위 discovery 설정을 일관되게 사용
unset ROS_LOCALHOST_ONLY
export C2_MONITOR_DATA="$(pwd)/ws_cobot_pjt/backend/monitor_data/real_process"
export C2_PREPARATION_CONFIG=/배포설정/측정설정.json
export C2_EXECUTION_PROFILE=/배포설정/실행설정.json
```

HMI와 경로 서버:

```bash
python3 ws_cobot_pjt/run_monitor.py --transport ros --mode REAL \
  --ros-domain-id "$ROS_DOMAIN_ID" \
  --preparation-config "$C2_PREPARATION_CONFIG" \
  --execution-profile "$C2_EXECUTION_PROFILE"
```

공정 노드는 별도 터미널에서 동일 domain·Jazzy·팀 overlay를 사용한다. 드라이버도 같은 domain을 사용하며 중복 실행하지 않는다. 기존 공정 CLI 연결은 다음과 같다:

```bash
ros2 run c2_process real_process_node \
  --preparation-backend-url http://127.0.0.1:8010 \
  --preparation-journal-path "$C2_MONITOR_DATA/preparation.sqlite3" \
  --execution-journal-path "$C2_MONITOR_DATA/execution.sqlite3" \
  --controller-prefix /dsr01/dsr_controller2
```

`controller-prefix` 하나로 측정·실행 service와 `<prefix>/control_authority` 토픽을 같이 결정한다.
공정 노드에 `__ns:=/dsr01` remap을 추가하지 않는다.

별도 경로 서버를 쓰는 경우 HMI에 `--external-path-node`를 추가하고 아래 명령을 빠뜨리지 않는다:

```bash
ros2 run c2_path path_planner_node --ros-args \
  -p source_mode:=REAL -p allow_real_execution:=true \
  -p managed_data_dir:="$C2_MONITOR_DATA"
```

이 구성은 한 PC 전용이다. 로봇 제어기 IP와 ROS 노드 간 DDS discovery는 다른 설정이다. 다중 PC에서는 LOCALHOST와 127.0.0.1을 그대로 사용할 수 없다.

## 최신 공통 계약과 남은 검증

PR #67의 공통 Result는 `absolute_top_verification_known`과 `absolute_top_verified`를 함께 전달한다. HMI도 두 값을 그대로 복사한다. known=false/verified=false를 검증된 false로 승격하지 않으며 known=false/verified=true는 거절한다. 이전 설치본은 측정 전에 차단하므로 같은 커밋의 c2_interfaces를 송수신 PC에서 재빌드·source해야 한다. schema_version 숫자만 같아도 ROS 타입이 다르면 호환되지 않는다.

PR #66의 경로 검사는 true/false를 강제하지 않고 원본 일치와 boolean 형식을 검사한다. 실제 생성 ROS Result를 변환해 HMI가 저장한 스냅샷으로 REAL 경로가 생성되는 것을 시험한다. 시험값은 합성 측정이며 실제 로봇으로 취득한 값이 아니다. HTTP BIND 왕복 시험은 대역이다.

배포 실행 프로파일은 기존 C2_EXECUTION_PROFILE로 공급하며 이 PR은 현장 속도·깊이·TCP·하중 값을 만들어 배포하지 않는다. 실제 DDS 왕복, 로봇 측정·조각·정지 시간·품질 검증은 별도로 남는다. 이번 변경은 HMI 소프트웨어 정지 경로를 수정하거나 안전등급 비상정지를 구현하지 않는다.

## 검증

검사 결과는 PR 본문에 기록한다. c2_interfaces Jazzy 빌드, 백엔드 전체, 경로·공정 회귀시험, TypeScript/Vite, 저장소 검사로 확인한다. CI/대역 시험은 실기 통합 완료의 증거가 아니다.

## 되돌리기

이 HMI 커밋을 되돌리면 기존 실행기로 복귀한다. REAL 경로 서버는 별도 기동 절차를 다시 적용해야 한다. 공통 Action 자체는 이 PR에서 수정하지 않으므로 PR #67의 타입 배포 상태와 구분한다.

## 최종 검증 결과

- c2_interfaces: Jazzy colcon 빌드 성공.
- 백엔드: 163 passed, 6 skipped (별도 활성화 DDS 시험).
- c2_path/c2_process: 1030 passed, 5 skipped (환경 의존 시험).
- TypeScript 검사·Vite 빌드·저장소 검사·Git hook 8개·Issue manager 27개·git diff --check 통과.
- 실제 로봇 구동 미수행.

## main 60a6862 후속: 공정 소비자와 정적 검사 정렬

HMI도 공정 validate_real_execution_profiles와 동일하게 모든 이동 프로파일의 pos_tol_mm을 양수로 요구한다. fixed_depth.depth_m은 0 이상을 허용하고, clearance_m은 숫자 또는 {stroke: 양수}를 원본 그대로 받는다. 추가 이동 프로파일도 공정과 같이 검사한다. 시험용 값은 배포 설정이 아니다.

양쪽 검사에 동일 설정을 전달하는 회귀시험과 실제 생성 Result → HMI 스냅샷 → 경로 생성 → REAL 공정 설정 매퍼 시험을 추가했다. 공정/경로/공통 타입 소스는 변경하지 않는다. 이 검사는 실제 로봇 이동이나 전체 DDS 왕복을 수행하지 않는다.

후속 검증: 백엔드 192 passed/6 skipped(DDS opt-in), 양쪽 정적 검사 회귀시험 29개 포함. 실제 생성 Result에서 REAL 경로 생성 및 공정 설정 매퍼 통과 확인. 저장소·Git hook 8개·Issue manager 27개·diff 검사 통과. 기준 60a6862, 작업 브랜치 codex/hmi-execution-config-alignment. 실기 구동 미수행.

## J6 승인 범위 변경 · 2026-09-22

기준 main 2a95eba. 사용자가 전달한 세은님의 승인 변경에 따라 최종 REAL profile의 joint_check_arguments.limits_deg[5]를 [-170.0, 170.0], j6_margin_deg를 0.0으로 반영한다. J1~J5와 나머지 설정은 입력 실행 프로파일에서 보존한다. SIM 프로파일에는 적용하지 않는다.

실측 스냅샷 조립은 입력의 깊은 복사에서 수행하며 기존 스냅샷을 수정하지 않는다. 변경된 내용은 기존 Storage.profile을 통해 새 ID·원본 바이트 SHA-256으로 등록하고, 그 참조를 BIND_SNAPSHOT에 전달한다. 기존 경로의 스냅샷/해시만 바꿔 재사용하지 않는다. 변경 이후에는 새 스냅샷으로 경로를 생성하고 미리보기·최종 관절검사를 다시 진행한다.

검증: 관련 HMI·실제 생성 Result→경로→공정 매퍼·준비/BIND 시험 35 passed, 2 skipped(DDS opt-in). J1~J5 보존, 입력 설정 불변, 이전 스냅샷 불변, 새 ID·해시 발급 및 BIND 참조를 확인했다. 저장소·diff 검사 통과. 실제 로봇 구동과 운영 스냅샷 발급은 미수행: 확인한 로컬 HMI 저장소에 실측 REAL 스냅샷이 없었다. 테스트 ID·해시를 운영 발급값으로 사용하지 않는다.
