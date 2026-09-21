# M0609 제어권 관측 토픽 — 규격 초안 v1

기존 드라이버 내부의 GRANT/LOSS를 공정에서 읽도록 한다. 새 노드·제어권 요청·서보·그리퍼·드릴·모션 명령은 추가하지 않는다. 기존 드라이버 자체의 제어권 요청 로직은 수정하지 않는다. **기존 로직에 요청이 전혀 없다는 뜻은 아니다.**

수정 대상은 외부 드라이버의 실제 소스 4개 파일이다. 사용자가 승인한 직접 소스 PR에 이 파일들만 명시적으로 추적한다. `.gitignore`의 나머지 외부 소스 제외 규칙은 변경하지 않으며, 팀장님이 이 추적 범위를 검토한다. 현재 실행 중인 드라이버에 반영하려면 아래 재빌드·재시작이 필요하다. 실제 활성화는 아직 하지 않았다.

## 제공 인터페이스

| 항목 | 값 |
| --- | --- |
| 토픽 | `~/control_authority`; 기본 구성 `/dsr01/dsr_controller2/control_authority` |
| 타입 | `std_msgs/msg/String` — 아래 JSON v1 |
| 발행자 | 기존 `dsr_controller2` |
| 주기 | 100 ms, 10 Hz |
| QoS | Reliable, Volatile, KeepLast(1) |
| 연결 근거 | 실제 모니터링 데이터 콜백; 마지막 수신 후 500 ms 이내 |
| 제어권 근거 | 하드웨어 초기 콜백과 컨트롤러 콜백의 GRANT/LOSS 기록 |
| 수신 만료 | 공정에서 마지막 정상 패킷 수신 후 500 ms 초과 시 미확인 처리 |

이름/필드/500 ms 기준은 이 구현의 **연결 제안값**이다. 공정 구독부는 김세은 담당이며 공통 Action 정의를 변경하지 않는다. M0609 한 대의 현재 드라이버 구성을 대상으로 한다. 다중 로봇 공용 캐시로 사용하지 않는다.

| JSON 필드 | 자료형·단위 | 의미 |
| --- | --- | --- |
| `schema_version` | int, 1 | 메시지 구조 버전 |
| `source` | string | `CONTROLLER_ACCESS_CONTROL` |
| `driver_session` | string | 발행자 초기화 식별자. 변경 시 이전 패킷/관측 폐기 |
| `sequence` | uint64 | 해당 세션의 발행 순번 |
| `published_at_unix_ns` | int64, ns | 시스템 시계의 발행 시각. 제어권 변경 시각이 아님 |
| `active` | bool | 컨트롤러가 활성화된 상태 |
| `connected` | bool | 모니터링 데이터가 신선하고 단절 통보가 없는 상태 |
| `valid` | bool | 활성·연결·GRANT/LOSS 관측 근거가 모두 있음 |
| `has_control` | bool | 유효한 GRANT 보유. `valid=false`에서는 false로 발행하지만 LOSS 확정이 아닌 미확인 |
| `last_access_event` | int | 마지막 콜백: -1 미관측, 0 REQUEST, 1 DENY, 2 GRANT, 3 LOSS |
| `monitoring_age_ms` | int64, ms | 마지막 모니터링 데이터의 나이. -1은 미수신 |

좌표/힘 데이터가 아니므로 좌표계는 적용하지 않는다. 정지·현재 자세·TCP/하중 확인을 이 토픽으로 대신하지 않는다. REQUEST/DENY는 제어권 이전 요청에 대한 이벤트이므로 현재 보유권과 같지 않다. **`last_access_event==2`만 검사하지 않고 `active/connected/valid/has_control`을 사용한다.**

발행 타이머가 살아 있더라도 드라이버 모니터링이 끊기면 valid=false다. 단절 또는 만료 뒤 모니터링만 다시 들어왔다는 이유로 과거 GRANT를 되살리지 않는다. 새 GRANT/LOSS가 확인되어야 유효 상태가 된다. 이 관측 기능이 제어권을 다시 요청하지는 않는다.

## 세은님 수신 처리

- 위 QoS로 구독하고 schema/source/필드 타입·세션·순번을 확인한다. 세션 변경 시 이전 관측을 지운다.
- 같은 PC 구성에서 발행 시각과 현재 Unix 시각을 대조해 지연된 패킷을 거절한다. 음수 시간 차이나 500 ms 초과 지연은 미확인이다. 주기적인 수신 만료 판단에는 `time.monotonic()`을 사용한다.
- `active && connected && valid && has_control` 및 수신 신선도가 모두 만족할 때만 제어권을 통과시킨다. false/미수신/해석 실패/만료는 통과가 아니다.
- `evidence_provider(context)`의 `control_authority`에 `value`, `valid`, `source="CONTROLLER_ACCESS_CONTROL"`, `observed_at_monotonic_s`를 넣는다. 관측 시각은 실제 수신 기록을 사용하며, provider 호출 때마다 현재 시각으로 갱신하지 않는다. 전송 지연과 monitoring_age도 유효기간에서 차감한다.
- 드릴 OFF·철사/장착 확인은 별도의 운영자 확인 기록이다. 이 토픽은 그 값을 제공하거나 자동 true로 설정하지 않는다.
- 수신부·준비 Action/HMI 왕복 연결 및 실제 GRANT/LOSS 시험은 이번 변경의 빌드/단위 검사와 구분한다.

예시(시각은 설명용이며 재생하여 준비 검사에 사용하지 않는다):

```json
{"schema_version":1,"source":"CONTROLLER_ACCESS_CONTROL","driver_session":"example","sequence":10,"published_at_unix_ns":1789977600000000000,"active":true,"connected":true,"valid":true,"has_control":true,"last_access_event":2,"monitoring_age_ms":25}
```

- LOSS: `connected=true, valid=true, has_control=false, last_access_event=3`.
- 통신 단절: `connected=false, valid=false, has_control=false`. last_access_event는 마지막 GRANT 값 2가 남아 있을 수 있다.
- 드라이버 프로세스 종료: 새 메시지가 없으므로 공정이 수신 만료로 미확인 처리한다.

## 소스 전달·적용

이 PR은 아래 4개 파일을 명시적으로 Git에 등록한다. 한 번 추적된 파일은 `.gitignore` 제외 규칙과 무관하게 이후 C-2 커밋과 pull로 전달된다. 다른 외부 소스 전체가 등록되는 것은 아니다. `ws_dsr/src`에는 기존 cobot_rg2 저장소도 있으므로, 받기 전에 외부 저장소의 로컬 변경을 백업·대조한다. 새 설치에서는 C-2가 제공하는 4개 파일만으로 드라이버를 빌드할 수 없다. 외부 원본 전체를 별도 위치에 준비하고 C-2의 수정 파일을 대조·반영하는 최초 설치 절차를 팀장님과 맞춰야 한다. 이미 파일이 들어 있는 src에 무작정 git clone하거나 외부 Git 상태를 초기화하지 않는다.

- `ws_dsr/src/doosan-robot2/dsr_hardware2/src/dsr_hw_interface2.cpp`
- `ws_dsr/src/doosan-robot2/dsr_hardware2/include/dsr_hardware2/control_authority_observation.hpp` (신규)
- `ws_dsr/src/doosan-robot2/dsr_controller2/src/dsr_controller2.cpp`
- `ws_dsr/src/doosan-robot2/dsr_controller2/include/dsr_controller2/dsr_controller2.hpp`

기준: `ahnisinc/cobot_rg2` commit `4d5657f36a160eedb533ab1c975cd8a30c3e53b2`. 다른 버전의 외부 드라이버에 파일을 통째로 덮어쓰지 말고 변경분을 대조한다.

장비가 정지된 상태에서 브링업을 종료한 뒤 재빌드한다. 이 명령은 브링업을 자동 종료하거나 재실행하지 않는다.

```bash
cd ws_cobot_pjt/ws_dsr
source /opt/ros/jazzy/setup.bash
source install/setup.bash
colcon build --packages-select dsr_hardware2 dsr_controller2 --executor sequential --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF
source install/setup.bash
```

이후 기존 sodreal/브링업 절차로 재시작하고 관측만 확인한다.

```bash
ros2 topic echo /dsr01/dsr_controller2/control_authority std_msgs/msg/String --qos-reliability reliable --qos-durability volatile
```

되돌리기는 이 변경분을 되돌린 뒤 동일하게 재빌드한다. 원래 그리퍼/모션 제어 소스의 다른 현장 변경까지 초기화하지 않는다.

## 확인 결과

2026-09-21, 원본 commit `4d5657f36a160eedb533ab1c975cd8a30c3e53b2`의 설치 소스 기준:

- 초기 미관측, 초기 HW GRANT 계승, REQUEST/DENY, LOSS, 단절, 만료, 재연결, 미지원 이벤트의 C++ 검사 통과.
- 별도 빌드 디렉터리에서 Jazzy `dsr_hardware2`, `dsr_controller2` 빌드 성공.
- 빌드한 컨트롤러 라이브러리의 의존성/심볼 해석 확인.
- 실제 로컬 드라이버 소스 반영 완료. 실행 드라이버 재빌드·재시작, 실물 토픽 수신 및 공정 연결 시험은 미수행. 별도 디렉터리에서 수행한 빌드와 구분한다.

단위 검사 예시(수정 소스 기준):

```bash
g++ -std=c++17 -pthread -Iws_cobot_pjt/ws_dsr/src/doosan-robot2/dsr_hardware2/include tools/test_control_authority.cpp -o /tmp/c2-authority-test
/tmp/c2-authority-test
```
