# 직접 결착 연구 개발 인계

2026-10-07. 개발 브랜치는 `work/suhyun-assembly-evidence`다.
사용자가 이 브랜치를 다른 PC에서 받아 이어서 개발하도록 게시를 요청했다.
main 병합이나 기존 ms-02 Day4 작업 폴더 교체는 이번 게시 범위가 아니다.

## 다른 PC에서 받기

ms-02의 `/home/ms-02/C_2`에는 미커밋 작업과 실행 중일 수 있는 Backend가 있다.
그 폴더에서 브랜치를 전환하거나 reset하지 않고 새 폴더에 받는다.

```bash
git clone --single-branch --branch work/suhyun-assembly-evidence \
  https://github.com/suuuhululu/C-2.git C-2-assembly
cd C-2-assembly
git status --short
```

새 폴더를 Codex 작업 프로젝트로 열고 `AGENTS.md`,
`docs/reference/AI_CODE_POLICY.md`, `docs/reference/UNIT_TEST_POLICY.md`,
이 문서와 [STATUS](STATUS.md)를 읽고 이어서 개발한다.
브랜치는 기존 기준 커밋 `6fb971c`에서 시작한 연구 변경이며 최신 main의
모든 후속 팀 변경이 병합된 상태는 아니다. 통합은 차이를 확인한 별도 작업이다.

## 목표와 현재 코드

최종 사용자 목표는 supply board에서 집어 assembly board에 직접 결착하는 것이다.
기존 Day4의 supply→place board 전달·사람 조립과 구분한다.
첫 제한 목표는 고정된 layer-1 2×2 기준 블록과 같은 격자 위치에
layer-2 목표 2×2를 결착하는 것이다. 첫 실기는 목표 블록을 이미 파지한 상태에서
시작하고, 이후 공급판 집기/운반을 연결한다.

이 브랜치에는 `app/assembly_*.py`의 증거·시도·완료·사람 확인·복구 제안·센서
정규화/현장 원문 변환과 `app/backend.py`의 연구 API가 들어 있다.
Backend는 단일 상태 Owner다. 연구 API는 **사용 전 FAKE Backend·driver 없음**을
요구하며 실제 motion driver 바인딩과 기존 HMI 명령을 차단한다.
실제 조회는 `scripts/assembly_sensor_bridge.py`를 사용하며 기본 실행은 안내만 한다.
별도 서버·새 State Manager·새 dependency는 추가하지 않았다.

이번 범위는 센서 조회→진단 Backend 연결까지다. 실제 블록 인식, 조립판→로봇
좌표 연결, ContactController, 직접 결착 MotionPlan은 미구현/미검증이다.
합성 Fixture의 좌표·시각·임계값·허용 플래그를 실기 값으로 쓰지 않는다.
ACK/robot idle/DRL LAST/그리퍼 폭만으로 정지·실행 종료·해제·결착을 확정하지 않는다.

## 다음 개발 우선순위

1. 현장 기존 Backend/Job/실행 프로세스와 최근 로그를 읽고 현재 상태를 확인한다.
2. 홍동님의 실제 캘리브레이션 코드/결과를 찾고 보정 범위를 확인한다.
   저장소 사본과 저장된 홍동 브랜치 참조에서는 아직 실제 파일을 찾지 못했다.
   파일 경로가 필요하면 사용자에게 경로만 요청한다.
3. 픽셀↔조립판 격자 보정과 조립판↔로봇 기준 좌표 변환을 구분한다.
   원점/축/단위/변환 방향/보정 당시 카메라·판 배치와 유효성을 확인한다.
4. 확인된 좌표·높이·자세·TCP↔파지 블록 오프셋으로 목표와 접근 위치를 계산하고,
   로봇에 송신하지 않는 검증부터 구현한다. 미측정 값이나 접근 여유를 추정하지 않는다.
5. 실제 접근/접촉/결착은 별도 현장 실행 지시와 검증된 조건으로 수행한다.
   place board 목적지만 바꾸거나 기존 의자 전달 시나리오를 계속하는 방식으로 대신하지 않는다.

## 현장 자료와 실제 검증

다음 자료는 ms-02에만 있는 ignored 산출물이며 Git clone에 포함되지 않는다.

- `/home/ms-02/C_2/logs/no_motion_20261007/`: RGB/Depth 6장면, 조회 원문과 사람 정답.
- `/home/ms-02/C_2/scripts/no_motion_check.py`: 기존 현장 읽기 전용 조회 도구.
  검토 hash와 실행 환경은 [연결 안내](D_ASSEMBLY_SENSOR_BRIDGE.md)에 있다.
  이 reader는 이번 브랜치의 새 파일이 아니며 clone만으로 제공되지 않는다.
- `/home/ms-02/C_2/logs/assembly_sensor_bridge_20261007_c4762d97_v2/live_02`:
  실제 무이동 조회→진단 Backend 연결 성공. 획득 창 0.430초, accepted=true,
  committed=false, HOLD/SAFETY_UNKNOWN, 물리 완료 false, 이동/개폐 명령 0회.
- `/home/ms-02/C_2/logs/backend_launch_20261007_a5ba9b37/`: 별도로 실행한 기존
  `app.real_workflow_hmi`의 기록. 사용자가 파랑 6점 1번의 place board 전달 성공을
  보고했다. 직접 결착 성공이 아니며 현재 실행 상태는 로그/프로세스로 다시 확인한다.
  과거 PID/check_id를 현재 값으로 재사용하지 않는다.

기존 HMI의 `place_empty`는 실제 집기·전달을, 마지막 Step 이전 `assembly`는
다음 전달을 시작할 수 있다. 현장 기존 앱·Job·로봇/Camera 노드를 임의 종료하거나
재시작하지 않는다. 과거 촬영 자료를 fresh 증거로 승격하지 않는다.

## 장치 없이 코드 확인

기존 Python/pytest 환경에서 실행한다. Qt 화면이나 로봇/Camera를 시작하지 않는다.

```bash
python3 -m pytest -p no:launch_testing -p no:launch_ros \
  tests/unit/test_assembly_sensor_readings.py tests/unit/test_assembly_sensor.py \
  tests/unit/test_assembly_recovery.py tests/unit/test_assembly_human.py \
  tests/unit/test_assembly_completion.py tests/unit/test_assembly_attempt.py \
  tests/unit/test_assembly_evidence.py tests/unit/test_completion.py \
  tests/unit/test_contracts.py tests/unit/test_backend.py tests/unit/test_snapshot_log.py -q
python3 -m scripts.assembly_sensor_bridge
```

ROS launch pytest plugin은 로컬 전역 환경과의 호환성 문제로 이 순수 Python 검사에서
명시적으로 제외했다. 테스트/assertion을 삭제한 것은 아니다. 직전 관련 검사 563개와
현장 연구 사본 375개, 기존 조회 도구 6개는 범위가 다르며 합산하지 않는다.
게시 전 검사 결과는 STATUS의 게시 준비 기록을 따른다.
실제 안전·접촉·결착, CI·사람 리뷰·main 병합 통과를 단위 검사로 주장하지 않는다.

## 이어서 작업할 Codex 지시

현재 사용자 목표는 직접 결착이며 다음 작업은 조립판 보정 자료 확인과 로봇 접근
목표 연결이다. 첫 응답에서 현재 실행 상태, 발견한 보정 범위, 첫 구현 단위를
설명하고 승인된 조사·최소 구현·송신 없는 검증을 진행한다.
실제 이동/개폐/접촉/삽입/reset은 명시적인 현장 실행 지시 후 수행한다.
한국어로 입력→계산→출력과 실제 이동이 발생하는 시점을 설명하며, D435i 사용 가능
여부와 자료 존재 여부를 반복 확인하지 않는다. 기존 작업과 원자료를 보존하고
변경 후 STATUS에 실제 검사·한계·다음 작업을 기록한다.
