# 데스크톱 드라이버 제어권 관측 반영

## 경로 구분

- C-2 Git/공정/HMI: `/home/rokey/cobot1` (main `08956e5`, 관측 패치는 PR #48에서 전달).
- 실제 드라이버 워크스페이스: `/home/rokey/ws_cobot_pjt/ws_dsr`.
- 외부 소스 Git: 위 `src`의 cobot_rg2 `4d5657f36a160eedb533ab1c975cd8a30c3e53b2`.
- C-2 안의 `ws_cobot_pjt/ws_dsr/install`은 없고, 실행 드라이버는 별도 워크스페이스의 install을 사용한다.

따라서 C-2 최상위에서 `cd ws_cobot_pjt/ws_dsr` 후 빌드한다는 다른 PC의 안내는 현재 데스크톱의 실행 위치와 다르다.
`sodreal` 별칭도 개인 설정이며 이 PC에서 존재하거나 같은 실행 명령이라고 가정하지 않는다.

## 승인 범위와 반영

사용자 승인에 따라 외부 실행 소스와 main 패치를 비교했다. 대상 3개 기존 파일에 별도 로컬 변경이 없고 버전도 패치 기준과 일치했다.
다음 4개 파일만 apply_patch로 반영했다. 결과는 C-2의 추적된 해당 파일과 바이트 단위로 일치한다.

- dsr_controller2/src/dsr_controller2.cpp
- dsr_controller2/include/dsr_controller2/dsr_controller2.hpp
- dsr_hardware2/src/dsr_hw_interface2.cpp
- dsr_hardware2/include/dsr_hardware2/control_authority_observation.hpp (추가)

그리퍼 joint_state_publisher, rokey/move.py·setup.py·grip_test.py 및 기존 비추적 파일은 보존했다.
수정 전 기존 3개 소스 백업: `/tmp/c2-authority-backup-S27hjG/driver-before.tar.gz`.
제어권 강제 요청·GRANT 조작·정지 해제·모션·그리퍼·드릴 명령은 추가하거나 실행하지 않았다.

## 빌드·검증과 배포 구분

실행 중인 라이브러리를 덮어쓰지 않기 위해 `/tmp/c2-authority-build-WwqHG1` 아래 별도 build/install/log를 사용했다.
기존 설치본은 dsr_common2/dsr_msgs2 등 의존성으로만 사용했다. 순차 빌드, 컴파일 병렬도 1, nice 15로 수행했다.
원래 install에 재빌드/설치하거나 브링업을 종료·재시작하지 않았다.

관측 C++ 단위검사: startup, grant, request/deny, loss, disconnect, stale, reconnect, unknown 통과.
별도 Release 빌드: dsr_hardware2/dsr_controller2 두 패키지 성공(약 1분 55초). 기존 드라이버 코드의 deprecated/unused/배열 복사 관련 컴파일러 경고가 있으며, 빌드 성공을 경고 해결이나 실기 안전 검증으로 간주하지 않는다.
실행 중인 드라이버에 새 publisher가 생기는 것은 **새 라이브러리로 안전하게 재기동한 이후**다. 소스 반영/별도 빌드만으로 살아 있는 프로세스가 교체되지는 않는다.
실제 토픽 발행·제어권 값·HMI 재준비 성공은 아직 검증하지 않았다. 이전 UNKNOWN 요청을 임의로 성공 처리하거나 삭제하지 않았다.

배포/재기동은 실제 정지와 현장 안전 확인 뒤 별도로 진행한다. 기존 드라이버를 정리하기 전 새 드라이버를 중복 실행하지 않는다.
원래 install은 그대로 보존되어 있다. 소스 되돌리기가 필요하면 위 3개 백업과 신규 헤더의 추가 여부를 기준으로 해당 변경만 되돌린다.
