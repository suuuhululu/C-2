# Isaac Sim 후속 검토

> 2026-10-07 적용: [최종 MVP](10_FINAL_MVP.md)는 커스텀 의자 직접 결착·사람 지지·세 단계 종료입니다. Isaac Sim·2PC 설치를 새 선행 요건으로 추가하지 않습니다. 기존 전달 경로·cuboid 시뮬레이션 결과가 직접 결착·지지 안전·실제 완성상태 검증을 대신하지 않습니다. 아래 Day4 범위 설명은 기존 계획입니다.

Isaac Sim은 이전 계획의 확장 후보입니다. 최신 H12의 Day 4 필수 단계는 계약·Mock·실기 준비·부분통합·전체 시연이며 Sim 설치·2PC를 선행 조건으로 추가하지 않습니다. 세은의 과거 Sim 담당 기록은 후속 검토 후보로 보존하며 새 일정은 팀에서 확인합니다.

## 도입 시 확인

- Design / Current / Revised 미리보기, Robot motion, 물리 검증 중 목적을 구분합니다.
- PC GPU / VRAM / RAM / driver / SSD, 호환 검사, 설치할 release의 공식 요구 사항을 확인합니다.
- ROS2 Jazzy bridge·기존 Robot PC 영향·동일 형식 / 버전 / 좌표를 확인합니다.

설치 버전·요구 사양 숫자는 여기서 확정하지 않습니다. 이전 release·GPU 기준을 재확인 없이 적용하지 않습니다. 설치·환경 변경은 이번 작업 범위가 아닙니다.

## 검증 범위

| 구분 | 확인 | 의미 |
|---|---|---|
| 규칙 | 지원 블록·bounds·겹침·support·dependency | 정의된 조립 규칙 통과 / 실패 |
| 미리보기 | 같은 grid·Design / Current / Revised | 표시·배치 데이터 일관성 |
| 물리 / Robot | 치수·결합·접촉·모델·보정 | 실제 준비한 모델·검사 범위만 |

cuboid 표시·안정성을 LEGO 결합·실제 파지·안전 증거로 보지 않습니다. 미검사는 통과가 아닙니다. Day 4 수량 재고·실행 중 Robot 경로 검사를 필수로 추가하지 않습니다.

## 공식 자료

- [설치·다운로드](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/download.html)
- [요구 사양·Compatibility Checker](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html)
- [ROS 설치](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_ros.html)

Sim 없이 Fixture·규칙·Day 4 통합을 진행할 수 있습니다. 키워드 최초 생성은 Day 4 기능이며 Sim 이후로 미루지 않습니다.
