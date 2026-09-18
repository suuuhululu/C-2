# c2_interfaces · 공통 통신 정의 개발 위치

개발 폴더만 준비된 상태다. 이 패키지는 실행 노드 없이 세 노드가 공유하는 통신 타입을 제공하도록 구현한다. 기준은 [인터페이스 권장안 v1](../../../docs/INTERFACE_RECOMMENDATION.md)이다.

| 디렉토리 | 구현할 파일 | 연결 |
| --- | --- | --- |
| `action/` | `GeneratePath.action` | 모니터 → 좌표·경로 생성 |
| `action/` | `ExecuteProcess.action` | 모니터 → 전체 공정 실행 |
| `srv/` | `StopProcess.srv` | 모니터 → 정지 접수 |
| `msg/` | `ProcessState.msg` | 공정 → 최신 상태 |
| `msg/` | `ProcessEvent.msg` | 공정 → 기록할 이벤트 |

타입 구현 시 루트에 `package.xml`·`CMakeLists.txt`를 작성하고 Jazzy에서 메시지 생성·타입 참조를 확인한다. 아직 이 파일들과 통신 타입은 구현되지 않았다. 빈 `.action`·`.srv`·`.msg` 파일을 완성된 타입 대신 두지 않는다.

필드·단위·버전·상태·오류·완료 의미는 명세와 일치시킨다. 다른 패키지에서 같은 타입을 복제하지 않는다. 계약을 바꾸면 영향받는 송수신자와 명세·검증을 함께 갱신한다.
