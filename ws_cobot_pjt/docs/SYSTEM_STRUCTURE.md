# 시스템 모니터·좌표 생성·고정 드릴 공정 구조

**2026-09-20 확인, main `72618aa`(PR #38 병합).** 현재 소스와 앞으로 통합할 기능을 분리한다. 공정 파일·함수·담당·구현 상태의 상세 원본은 [c2_process README](../ws_cobot1/src/c2_process/README.md)다. 9/19의 “공정 모듈 6개·robot_adapter만 존재” 표기는 최신 상태가 아니다.

팀 노드는 `monitor_gateway_node`, `path_planner_node`, `process_controller_node` 3개를 유지한다. 내부 파일을 나눠도 별도 ROS 통신을 추가하지 않는다. 로봇 모션은 공정 제어 하나가 소유한다. 드릴은 철사로 고정하며 **초기화·보정·오류·종료에도 그리퍼 열기 금지**, 자동 집기·반납·청소 제외다.

## 디렉토리·담당·현재 상태

| 위치 | 담당 | 코드와 역할 | 확인 상태 |
| --- | --- | --- | --- |
| `frontend/src/monitor/` | 이수현 | `Monitor.tsx` 화면·작업 흐름, `Previews.tsx`·`LivePathPreview.tsx` 미리보기, `api.ts` 서버 요청 | main 존재. 실물 공정·보정 후 경로 연결은 별도 구현 |
| `backend/app/` | 이수현 | `monitor.py` API, `monitor_service.py` 요청·결과 처리, `monitor_contract.py` 데이터 검증, `storage.py` 저장, `ros_bridge.py` ROS 연결, `mock_peer.py` 모의 상대 | main 존재. 모의 기능과 실제 산출물/로봇 연동 구분 |
| `ws_cobot1/src/c2_interfaces/` | 김세은·이수현·노홍동·이시율 공동 계약 검토 | GeneratePath·ExecuteProcess Action, StopProcess Service, ProcessState·ProcessEvent Topic 타입 | main 존재, 고정 드릴 v2. 새 보정 흐름 계약 확장은 미반영 |
| `ws_cobot1/src/c2_path/c2_path/` | 노홍동 | 아래 경로 생성 모듈 | main 존재. 현재 Action 서버는 SIMULATION/test_only |
| `ws_cobot1/src/c2_process/c2_process/` | 김세은·이시율 분담 | 아래 공정 모듈 | 어댑터·도구 보정·관절 검사·조각 소스 존재. main 공정 노드·패키지 빌드 설정 없음 |
| `ws_dsr/src/` | 공급자 드라이버, 이시율 실행환경 확인 | Doosan·그리퍼 드라이버 | 외부 원본·로컬 전용·Git 제외 |

### 노홍동: 기준 경로 생성

| 파일 | 역할 |
| --- | --- |
| `node.py` | `/c2/generate_path` ActionServer, 요청·진행·취소·결과 |
| `pipeline.py` | 이미지부터 검증 결과까지 내부 계산 순서 |
| `artifacts.py` | 입력·설정 조회, 경로·미리보기·검증 산출물 저장과 식별 |
| `image_to_svg.py` | 이미지에서 가공 중심선 SVG 생성 |
| `extract_2d.py` | SVG 중심선의 2D 획·점 추출 |
| `optimize_2d.py` | 2D 점·획 최적화 |
| `map_3d.py` | U/V 도안을 기준 원통의 3D 표면에 매핑 |
| `generate_path.py` | APPROACH/CUT/TRAVEL/RETRACT 등 구간과 자세 생성 |
| `validate_path.py` | 경로 구조·기하·작업 영역·이음매 규칙 검사 |
| `workcell.py` | 현재 시험 기준 형상·좌표·영역 상수. 공통 스냅샷 기반 설정 연결은 후속 검토 |

기준 모델의 중심과 실제 양초 중심이 다른 것 자체는 경로 생성 오류가 아니다. 현장 측정·보정은 공정 책임이다. 반면 경로 형식·단위·기준 모델·유효 영역·원본 대응은 좌표 담당이 제공해야 한다. 기하 검사 통과는 실제 관절·특이점·충돌 검사 통과를 뜻하지 않는다.

### 김세은: 공정 순서·통신·관절 검사

| 파일 | 역할 | 상태 |
| --- | --- | --- |
| `node.py` | 실행/정지 수신과 상태·이벤트 발행 | main 없음, 담당자 부분 통합 보고 |
| `state_machine.py` | 함수 호출 순서·운영자 확인 대기·성공/실패/정지 전이 | main 없음, 담당자 작업 보고. 새 보정 흐름 연결 예정 |
| `preconditions.py` | 시작 조건 확인, 보정 후 최종 경로 검사 호출·결과로 진행 여부 판단 | main 없음, 담당자 작업 보고 |
| `joint_check.py` | 보정된 경로의 IK·관절 범위·J6 검사 구현·보강 | main 존재. CUT 4점마다+마지막 점 검사, 전 경로·보간·특이점/충돌 범위 보강 필요 |
| `package.xml`, `setup.py`, `setup.cfg`, `resource/c2_process`, `launch/process.launch.py` | 패키지 설치·노드 실행·설정 로딩 | main 없음, 통합 시 구현 |

### 이시율: 모션·센서·보정

| 파일 | 역할 | 상태 |
| --- | --- | --- |
| `robot_adapter.py` | 로봇 관측·이동·접촉·정지·IK·TCP/단위 변환 | main 존재, 실기 개선 로컬 초안 별도 |
| `tool_calibration.py` | 장착 드릴 끝 보정·저장 보정 확인 | main 존재, 양초 위치 재측정과 구별 |
| `engraving.py` | 확정 경로의 접근·조각·이탈·진행 보고 | main 존재, 최종 검사 경로 그대로 실행하도록 보강 필요 |
| `workpiece_calibration.py` | 실제 양초 중심·축·기울기 등 측정 | 신규 파일 제안, 공통 구현 예정 |
| `prepared_path.py` | 실측 변환·깊이를 반영한 새 실행 경로 생성 | 로컬 깊이 적용 초안 존재, 위치/기울기·파일 연결 확장 예정 |
| `motion_guard.py`, `moving_contact.py` | 어댑터 내부 동작 판정·이동 중 접촉 판단 보조 | 로컬 초안. 채택/배치 검토, 별도 노드 아님 |
| `config/workcell.yaml`, `config/tools.yaml` | 형상·보정·도구·프로파일 설정, 다른 담당과 대조 | main 실행 YAML 없음 |

이시율의 기존 세 파일은 모두 유지하고 양초 측정·경로 준비 기능을 분리할 예정이다. 이미 추가된 `joint_check.py`는 김세은 담당이며 이시율의 추가 업무가 아니다. `__init__.py`·시험·패키지 설정까지 포함해 “정확히 6개 모듈”로 제한하지 않는다. 없는 파일을 빈 코드로 만들어 완료처럼 표시하지 않는다.

## 통합할 호출 순서

1. HMI/서버 → **ROS Action GeneratePath** → c2_path 계산 → 기준 경로 미리보기.
2. HMI/서버 → **ROS Action ExecuteProcess** → 김세은의 공정 제어.
3. 공정 제어 → **내부 함수** → 기본 준비·현재 로봇 위치·도구 보정 유효성 확인.
4. 공정 제어 → **내부 함수** → 이시율의 양초 측정. 드릴 OFF, 측정용 접근/후퇴도 사전 검사.
5. 공정 제어 → **내부 함수** → 실측 위치·자세·깊이·연결 이동을 반영한 새 경로 생성.
6. 공정 제어 → **내부 함수 `check_path_joints()`** → 최종 경로 검사·실행 허용 판단.
7. 공정 ↔ HMI → 보정 결과/최종 경로 표시·취소 가능한 드릴 ON 확인. **통신 필드·입력 절차 합의 필요.**
8. 공정 제어 → **내부 함수 `execute_path()`** → 검사한 동일 경로 실행·정상 이탈.
9. **Action 결과·상태/이벤트 Topic** → HMI 완료. StopProcess 접수와 실제 정지 확인 구분.

새 흐름은 사용자 요청에 따른 통합 목표이며 현재 계약 v2에 이미 구현된 흐름이 아니다. 기존의 장착 3점 보정은 도구 설정 준비로 남기고, 양초 교체/이동에 따른 측정은 실행 준비에서 수행한다. [인터페이스 안내](INTERFACE_GUIDE.md)에 변경 범위와 미합의 계약을 기록한다.

## 데이터·실행 원칙

- 경로: 도구 끝 기준 `c2_base`, m·quaternion xyzw, 관절 rad. 툴 −Y가 안쪽 법선, 툴 +Z가 원통 축 아래. 어댑터에서만 제어기 TCP로 변환한다.
- 기준 경로·실측 스냅샷·도구/설정·최종 경로·검사 결과를 한 실행 기록으로 연결한다. 각각의 ID·버전·해시를 보존하고 최종 미리보기·검사·실행은 같은 경로를 참조한다.
- APPROACH/RETRACT는 실제 경로 구간이다. 상태 기계와 조각기가 중복 실행하지 않는다. 정지·보호정지·통신 단절 뒤 무조건 후퇴/홈 명령을 내리지 않는다.
- 자세·위치·힘·보정값은 단위·좌표계·측정 시각·유효성을 함께 전달한다. 힘 로그만으로 물리적 홈 깊이를 확정하지 않는다.
- [9/19 운영 결정](C2_FIXED_DRILL_20260919.md)은 당시 이력을 보존한다. 새 실측으로 과거 evidence를 덮어쓰지 않는다. 이번 문서화는 실행 코드 변경이나 로봇 시험이 아니다.
