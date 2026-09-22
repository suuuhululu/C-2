> 9/22 HMI 작업 변경: [REAL 실행 연결 계약](HMI_REAL_EXECUTION_20260922.md). 아래의 REAL 측정 전용 설명은 이전 기준이며, 현재 작업 브랜치는 BIND·생성·실행 요청을 연결한다. 상대 PR과 실기 검증은 별도다.

# 이미지 한 장으로 진행하는 HMI 부분통합

기준 main `c29de08` (PR #61 반영), 작업 브랜치 `codex/hmi-partial-integration`.
이 문서는 앞서 만든 ZIP 등록·별도 모의 실행기 안내를 대체한다.
운영자는 PNG/JPEG를 선택하고 준비/측정 → 경로 생성 → 미리보기 확인 → 실행 → 공정 상태/완료를 확인한다. JSON 설정·원본 기록·스냅샷·ID/해시는 서버가 관리한다. ZIP은 운영 절차에 없다.

## 실행

최초 한 번 backend 가상환경에서 `pip install -r requirements-image.lock.txt`로 이미지 변환 의존성을 설치하고 기존 frontend 의존성을 설치한다.
저장소 루트에서:

```sh
python3 ws_cobot_pjt/run_monitor.py
```

기본 실행은 실제 이미지 계산과 모의 준비/공정이다. 이전 고정 그림 응답을 사용하는 호환 시험만 `--legacy-mock-image`로 선택한다.
서버만 실행할 경우 `C2_IMAGE_WORKFLOW=1`, `C2_MONITOR_MODE=SIMULATION`, `C2_MONITOR_TRANSPORT=mock`을 설정하고 원본 c2_path 패키지를 PYTHONPATH에 추가한다. run_monitor.py는 이를 자동 설정한다.

운영자 순서:
1. 작업 준비에서 PNG/JPEG를 첨부한다. 서버는 이미지 자산을 등록한다.
2. 사전 검사·양초 측정 요청을 누른다. 서버는 설정 JSON을 자동 등록·참조하고 준비 성공/BIND 후 현재 스냅샷을 공개한다.
3. 배치를 지정하고 경로 생성을 누른다. 원본 c2_path 계산기가 첨부 이미지를 변환한다.
4. 2D/3D 미리보기와 장착·도안 확인 후 시작 요청한다. 모의 실행에서는 드릴/로봇을 조작하지 않는다.
5. 기존 공정 관제·정지·실행 이력에서 결과를 확인한다. 설정/측정이 바뀌면 이전 경로는 실행할 수 없다.

## 수현–세은 공정 연결

같은 Jazzy 공통 타입을 빌드/source하고 준비/BIND와 실행 입력 로더를 가진 세은 공정 노드를 별도로 실행한다. 같은 관리 파일 저장소/기존 자산 API를 사용한다.

```sh
python3 ws_cobot_pjt/run_monitor.py --transport ros --mode SIMULATION --process-integration
```

이 옵션은 기존 PrepareWorkpiece(MEASURE/BIND_SNAPSHOT), GeneratePath, ExecuteProcess, StopProcess, ProcessState, ProcessEvent를 사용한다. 별도 메시지나 ZIP 전달 단계를 만들지 않는다. 기존 HTTP `/preparations`, `/path-generations`, `/runs`와 웹소켓 상태 전달을 유지한다.

HMI는 BOUND_ROS와 최신 상태·동일 스냅샷/경로·해시를 확인하고 ExecuteProcess를 전송한다. 상대가 NOT_READY/실패를 반환하면 실제 오류를 기록한다. UI에서 성공을 대신 생성하지 않는다. 실행 서버 미연결, OUT_OF_LIMITS, 실행 제한, MOCK 전용 경로, 재측정 후 이전 경로는 차단한다. 공정 검사 합격 여부는 공정 노드가 판단한다.

**현재 연결 범위:** main `c29de08`에는 HMI 자산 조회와 REAL 실행 설정 로더를 포함한 `real_process_node`가 추가됐다. 다만 현재 HMI REAL 흐름은 측정 결과 보관까지만 허용하고 BIND·GeneratePath·ExecuteProcess는 아직 연결하지 않는다. c2_path의 REAL /3도 미리보기 전용이다. 실제 연결 명령은 [9/22 공정 연결 안내](HMI_PROCESS_CONNECTION_20260922.md)를 따른다. 위 SIM 명령은 REAL 실행 완료를 의미하지 않는다.

## 변경 범위와 호환

- 운영자 메뉴에서 파일 통합 시험을 제거했다. 과거 파일 교환 API는 호환용으로 남아 있으며 기본 작업에서는 호출하지 않는다.
- 잘못 추가했던 partial-integration HTTP/화면/별도 상태 기계는 제거했다.
- ImageMockPeer는 실제 c2_path 계산만 추가하고 기존 MockPeer의 준비/실행/정지/이력 흐름을 재사용한다. REAL 실측 자료를 SIMULATION으로 바꾸지 않으며 모의 준비 결과는 SIMULATED로 기록한다.
- ROS 타입/schema_version=2는 변경하지 않았다. HTTP snapshot의 `path_generation.test_only_execution`은 현재 SIM 시험 연결에서 test_only 경로 요청을 허용하는지 표시한다. REAL에는 사용하지 않는다.
- `C2_IMAGE_WORKFLOW=1`로 실제 이미지 계산을 선택하고 `C2_ROS_EXECUTION_SIM=1`로 ROS SIM 공정 전송을 명시한다. run_monitor.py가 옵션에 맞게 설정한다.

## 검증

백엔드 전체 125개 통과/ROS 환경 조건 4개 건너뜀 후, 추가 공정 연결 시험까지 신규 3개 통과. 전체 결과 중 새 공정 연결 시험은 추가 수행했으며 ROS DDS/로봇 비구동이다.
- PNG 업로드 → 모의 측정 → 동적 /2 → 실제 이미지 계산 → 경로/미리보기 → 기존 실행 이력 완료.
- 재측정 이후 이전 경로 거절.
- main 공정 준비 handler의 MEASURE/BIND와 경로 계산을 사용하고, 전송 시험대역으로 ExecuteProcess 동일 경로 참조·상대 실패 표시 확인.
- TypeScript/Vite 빌드 통과.

검사 명령은 backend에서 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests`.
commit/push/PR/병합과 실제 DDS·실기는 수행하지 않았다.

브라우저 확인: 사용자 도안용.png(326×300)만 첨부 → 기존 준비/측정 완료 → 실제 이미지 계산 303구간 → 미리보기 확인 → 기존 공정 관제에서 76개 CUT 모의 판정 및 SUCCEEDED/FINISH/100% 완료. ZIP 등록/전달은 수행하지 않았다. 운영 화면 단계 표시도 이미지·설정 → 준비·측정 → 경로 생성 → 미리보기 → 실행 요청으로 통일했다.
