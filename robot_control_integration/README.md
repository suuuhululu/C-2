# D 로봇 제어 소스 보존본

2026-10-12 현재 C→A→D 실물 시험에서 사용하던 외부 로봇 개발 폴더의 소스·설정·Fixture·검사를 보존했다. 원본은 별도 ZIP과 기존 폴더에 남아 있다. 이 폴더 추가 자체는 실제 통합 완료나 전체 블록 체결 검증을 뜻하지 않는다.

- `scripts/robot_integration_runtime.py`: 줄 단위 JSON 명령/이벤트 실행 경계. 기본 MOCK이며 REAL은 명시적으로 선택한다.
- `app/integration_runtime.py`: 이동·집기·Contact·인계·정지/재개·B 판정 응답 소비.
- `app/integration_gestures.py`: 로봇 단독 시험의 엄지척 준비·편 손 STOP.
- `settings/integration_native35/profile.reference.json`: 현재 35N 시험 기준.
- `settings/onsite_*`: 과거 단위 시험 설정·세션·검토 근거. 새 실행 승인으로 사용하지 않는다.
- `fixtures/`, `tests/`: 합성/기존 단위 시험 자료. 실제 관측이나 장치 실행 완료와 구분한다. 역사적 복구 검사는 명시적 READ_ONLY Fixture를 사용하며 일부 A 현장 검사는 별도 A 작업 위치가 필요하다.
- `driver/`: 기존 DRCF2 Release 버전 조회 수정 패치·원본 commit/해시. 빌드 산출물은 포함하지 않는다.

C-2의 `app`과 패키지 이름이 같으므로 별도 프로세스와 이 폴더 작업 위치를 사용한다. C-2에서 `app.robot_process.RobotProcess(robot_root, mode='MOCK')`로 연결한다. 실제 ROS 환경·측정·교시·모델은 각 환경에서 준비해야 한다.

전체 업데이트 기준·모의 재현·현재 병목은 [통합 안내](../docs/13_RUNTIME_UPDATE_20261012.md)를 따른다. 이 업데이트 과정에서 장치를 연결하거나 움직이지 않았다.
