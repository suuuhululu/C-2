# 팀 ROS 개발 디렉토리

`c2_interfaces`·`c2_path`·`c2_process`의 개발 폴더를 합의한 [목표 구조](../../docs/SYSTEM_STRUCTURE.md)에 맞춰 준비했다. Git은 빈 디렉토리를 기록하지 않으므로 아직 소스가 없는 하위 폴더는 `.gitkeep`으로 보존한다. 실제 구현 파일이 들어오면 해당 `.gitkeep`을 제거할 수 있다.

**현재 추가된 것은 개발 폴더와 안내 문서다.** 세 폴더에는 아직 `package.xml`, 빌드 설정, 메시지 정의, 실행 노드가 없다. `colcon`에 등록되는 완성된 ROS 패키지나 실행 가능한 공정으로 취급하지 않는다. 기존 `clay_carving`·`clay_hmi`의 실행은 [기존 실행 안내](../doc/clay_run.md)를 따른다.

```text
src/
├── README.md
├── c2_interfaces/          # 공통 Action·Service·Topic 정의를 개발할 위치
│   ├── README.md
│   ├── action/
│   ├── srv/
│   └── msg/
├── c2_path/                # 좌표·경로 생성 노드를 개발할 위치
│   ├── README.md
│   ├── c2_path/
│   └── resource/
├── c2_process/             # 전체 공정 제어 노드를 개발할 위치
│   ├── README.md
│   ├── c2_process/
│   ├── config/
│   ├── launch/
│   └── resource/
├── clay_carving/           # 기존 구현
└── clay_hmi/               # 기존 구현
```

| 개발 위치 | 시작할 작업 |
| --- | --- |
| [c2_interfaces](c2_interfaces/README.md) | 명세의 필드·자료형 검토 후 공통 타입·패키지 빌드 설정 작성 |
| [c2_path](c2_path/README.md) | 이미지·설정 입력부터 경로·검증 결과까지 모의 입출력 연결 |
| [c2_process](c2_process/README.md) | 모의 장치로 공정 단계·완료·오류·정지 처리를 먼저 연결 |

시스템 모니터의 ROS 연결 모듈은 [backend/app](../../backend/README.md)에 개발한다. 별도 `c2_hmi`·그리퍼 패키지는 만들지 않는다. 전체 작업 규칙은 루트 [AGENTS.md](../../../AGENTS.md), 송수신 계약은 [인터페이스 명세](../../docs/INTERFACE_RECOMMENDATION.md)를 따른다.
