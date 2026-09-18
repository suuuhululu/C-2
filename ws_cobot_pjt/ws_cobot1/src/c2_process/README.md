# c2_process · 전체 공정 제어 개발 위치

개발 폴더만 준비된 상태다. `process_controller_node` 하나가 공정 전체와 모션 명령을 소유하도록 구현한다. [목표 구조](../../../docs/SYSTEM_STRUCTURE.md)와 [실행·정지·상태 계약](../../../docs/INTERFACE_RECOMMENDATION.md)을 따른다.

| 구현 위치 | 담당 기능 |
| --- | --- |
| `c2_process/node.py` | 실행 Action·정지 Service, 상태·이벤트 Topic |
| `c2_process/state_machine.py` | 전체 순서와 성공·실패·정지 상태 전이 |
| `c2_process/preconditions.py` | 시작 조건·경로·설정·도구 검사 |
| `c2_process/robot_adapter.py` | 두산 인터페이스 호출·결과 확인·단위 변환 |
| `c2_process/gripper_adapter.py` | 고정 그리퍼 열기·닫기·파지·해제 확인 |
| `c2_process/tool_sequence.py` | 로봇팔과 그리퍼를 조합한 도구 집기·놓기 |
| `c2_process/engraving.py` | 확정 경로의 조각 실행·진행 보고 |
| `c2_process/cleaning.py` | 도구 청소·뭉침 제거·검증된 복귀 |
| `config/workcell.yaml` | 작업대·대상의 고정 좌표·형상·연결 설정 |
| `config/tools.yaml` | 도구별 보관·파지·TCP·하중·가공·청소 설정 |
| `launch/process.launch.py` | 좌표·공정 노드 실행 구성 |

구현 시 `package.xml`·`setup.py`·`setup.cfg`, `c2_process/__init__.py`, `resource/c2_process`와 실제 모듈을 작성하고 launch·config의 설치를 포함한다. 아직 이 파일들은 없으며 `.gitkeep`은 디렉토리 보존용이다.

내부 모듈은 같은 디렉토리의 형제 파일이며 함수 결과로 연결한다. 도구 집기·놓기는 `tool_sequence.py`, 그리퍼 자체 제어는 `gripper_adapter.py`가 담당한다. 별도 그리퍼 노드를 추가하지 않는다.

현장 좌표·속도·힘·TCP·I/O·파지 피드백은 확인된 값으로 채운다. 먼저 모의 장치로 정상·실패·정지 흐름을 검증한다. 실패·정지 미확인 뒤 다음 단계 진입, 자동 재시작, 오류 시 무조건 그리퍼 열기를 구현하지 않는다.
