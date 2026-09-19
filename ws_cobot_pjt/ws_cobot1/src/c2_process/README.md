# c2_process · 고정 드릴 공정 제어 개발 위치

2026-09-19 기준 `robot_adapter.py`, `__init__.py`, 모의·실기 확인용 시험 소스가 존재한다. ROS 실행 노드·패키지 빌드 설정은 아직 없다. `process_controller_node` 하나가 공정 전체와 모션 명령을 소유하도록 구현한다. [목표 구조](../../../docs/SYSTEM_STRUCTURE.md)와 [실행·정지·상태 계약](../../../docs/INTERFACE_RECOMMENDATION.md)을 따른다.

| 구현 위치 | 담당 기능 |
| --- | --- |
| `c2_process/node.py` | 실행 Action·정지 Service, 상태·이벤트 Topic |
| `c2_process/state_machine.py` | 전체 순서와 성공·실패·정지 상태 전이 |
| `c2_process/preconditions.py` | 시작 조건·경로·설정·도구 검사 |
| `c2_process/robot_adapter.py` | 두산 인터페이스 호출·결과 확인·단위 변환 |
| `c2_process/engraving.py` | 확정 경로의 조각 실행·진행 보고 |
| `c2_process/tool_calibration.py` | 장착 3점 전체 보정·실행 전 기존 보정의 1점 확인 |
| `config/workcell.yaml` | 작업대·대상의 고정 좌표·형상·연결 설정 |
| `config/tools.yaml` | 고정 드릴·TCP·하중·가공·보정·열기 금지 정책 |
| `launch/process.launch.py` | 좌표·공정 노드 실행 구성 |

구현 시 `package.xml`·`setup.py`·`setup.cfg`, `c2_process/__init__.py`, `resource/c2_process`와 실제 모듈을 작성하고 launch·config의 설치를 포함한다. `__init__.py`와 로봇 어댑터를 제외한 위 빌드·실행 설정은 아직 없으며 `.gitkeep`은 디렉토리 보존용이다.

내부 모듈은 같은 디렉토리의 형제 파일이며 함수 결과로 연결한다. 목표 공정 모듈은 위 Python 6개다. 집기·반납·청소 모듈과 별도 그리퍼 노드는 만들지 않는다. cleaning은 담당 브랜치에 예비 보관하며 main 이관에서 제외한다. [운영 결정](../../../docs/C2_FIXED_DRILL_20260919.md), [설정 대기 목록](config/README.md)을 확인한다.

철사로 고정한 드릴은 사람이 철사를 제거하고 운영 절차를 변경하기 전까지 초기화·종료·오류·보정에서도 그리퍼 열기 금지다. 장착·닫힘 확인은 preconditions에서 출처·시각·신선도까지 검사한다. 보정값 변경은 새 스냅샷·경로 생성 전에 확정한다. 현장 좌표·속도·힘·TCP·I/O·파지 피드백은 확인된 값으로 채운다. 먼저 모의 장치로 정상·실패·정지 흐름을 검증한다. 실패·정지 미확인 뒤 다음 단계 진입, 자동 재시작, 오류 시 무조건 그리퍼 열기를 구현하지 않는다.

## 진행 중인 담당 PR

9/19 main `301ea6e` 재조회 기준 프레임 변경 [#23](https://github.com/suuuhululu/C-2/pull/23), 조각 이관 [#25](https://github.com/suuuhululu/C-2/pull/25), 보정 [#27](https://github.com/suuuhululu/C-2/pull/27)은 미병합이다. 코드 존재와 main 통합을 구분한다. [v2 연결 전 대조 사항](../../../docs/C2_FIXED_DRILL_20260919.md)을 먼저 확인하고 같은 계약으로 통합 시험한다.
