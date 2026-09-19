# 팀 ROS 개발 디렉토리

`c2_interfaces`·`c2_path`·`c2_process`의 개발 폴더를 합의한 [목표 구조](../../docs/SYSTEM_STRUCTURE.md)에 맞춰 준비했다. Git은 빈 디렉토리를 기록하지 않으므로 아직 소스가 없는 하위 폴더는 `.gitkeep`으로 보존한다. 실제 구현 파일이 들어오면 해당 `.gitkeep`을 제거할 수 있다.

**2026-09-19 확인:** `c2_interfaces`의 공통 타입 5개·패키지 빌드 설정을 구현하고 Jazzy에서 확인했다. `c2_process`에는 `robot_adapter.py`와 시험 소스가 있다. `c2_path`·`c2_process`의 노드·패키지 빌드 설정과 전체 공정 연동은 미구현이다. 기존 `clay_carving`·`clay_hmi`·전용 실행 문서는 사용자 요청으로 로컬 보관 후 제거했다. [보관·복구 기록](../../docs/LEGACY_CLAY_ARCHIVE.md), [시스템 아키텍처](../../docs/architecture/README.md).

```text
src/
├── README.md
├── c2_interfaces/          # 공통 Action·Service·Topic 타입 구현
│   ├── README.md
│   ├── package.xml
│   ├── CMakeLists.txt
│   ├── action/
│   ├── srv/
│   ├── msg/
│   └── test/
├── c2_path/                # 좌표·경로 생성 개발 위치
│   ├── README.md
│   ├── c2_path/
│   └── resource/
└── c2_process/             # 어댑터 소스 존재, 노드·빌드 설정 미구현
    ├── README.md
    ├── c2_process/         # __init__.py · robot_adapter.py
    ├── test/              # 모의 시험 · 별도 실기 확인 스크립트
    ├── config/
    ├── launch/
    └── resource/
```

| 개발 위치 | 시작할 작업 |
| --- | --- |
| [c2_interfaces](c2_interfaces/README.md) | 제공 타입을 빌드·source하고 각 담당 노드에서 의존성으로 사용 |
| [c2_path](c2_path/README.md) | 이미지·설정 입력부터 경로·검증 결과까지 모의 입출력 연결 |
| [c2_process](c2_process/README.md) | 모의 장치로 공정 단계·완료·오류·정지 처리를 먼저 연결 |

시스템 모니터의 ROS 연결 모듈은 [backend/app](../../backend/README.md)에 개발한다. 별도 `c2_hmi`·그리퍼 패키지는 만들지 않는다. 전체 작업 규칙은 루트 [AGENTS.md](../../../AGENTS.md), 송수신 계약은 [인터페이스 명세](../../docs/INTERFACE_RECOMMENDATION.md)를 따른다.
