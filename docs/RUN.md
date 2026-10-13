# 통합 실행·운영

먼저 [INSTALL](INSTALL.md)을 준비한다. 현재 모듈 경계는 [INTEGRATION](INTEGRATION.md)을 본다. 명령은 저장소 루트에서 실행한다.

## 장치 없는 통합 실행

```bash
source .venv/bin/activate
C_DESIGN_USE_LLM=0 python3 -m app.mvp_integration   --robot-root ./robot_control_integration   --c-mode offline --log-directory logs/mvp-integration
```

이 진입점의 로봇은 MOCK, B는 합성 관측이다. 기본 C 생성 함수를 사용하며 별도 `--design` 예제 파일은 필요 없다. DB 연결 설정이 있으면 먼저 제작자 로그인한다. DB 없는 독립 모의 실행은 DB를 호출하지 않는다.

1. 시작 후 C 답변란에 원하는 설계(예: `의자`)를 입력한다. 생성된 후보를 미리보기에서 확인한다.
2. C의 질문에 답해 승인·수정·취소한다. APPROVE 전에는 계획을 실행하지 않는다.
3. A 정상 계획이면 Step별 재평가·이동 후보·가상 D 진행과 합성 B 검사를 확인한다.
4. 계획 실패면 구체 사유를 보고 목표/Current를 보존해 보류하거나 후보 수정→재승인→재계산을 진행한다.
5. 최종 결과와 `logs/mvp-integration/<job_id>.jsonl`을 확인한다. 모의 Current/완료를 실물 조립으로 보고하지 않는다.

어느 설계든 자동 완성한다고 보장하지 않는다. 현재 입력이 막히면 NO_FEASIBLE_ORDER/INVALID 등의 결과로 보류한다. 검증·예제·회귀 검사 자료는 README의 GitHub 보존 링크에서 별도로 찾는다.

실제 LLM 후보 생성만 사용하면서 로봇을 MOCK으로 유지하려면 개인 LLM 키를 준비하고 `C_DESIGN_USE_LLM=1`, `--c-mode live`를 함께 사용한다. 실제 외부 API/음성 사용은 offline 실행과 다른 확인 범위다.

## DB·웹

별도로 준비한 PostgreSQL의 DB 접속 환경을 INSTALL대로 제공한다. 신규 테스트는 운영 DB와 구분한다. `init`은 schema/migration을 적용하며 운영 DB 백업과 대상 확인을 거친다. 기존 계정은 덮어쓰지 않는다.

```bash
python3 -m history init
# 필요한 경우에만 앱 계정을 생성한다. 비밀번호는 대화형으로 입력한다.
python3 -m history create-user USERNAME DISPLAY_NAME
python3 -m history.web --port 8765
```

웹은 `http://127.0.0.1:8765/`의 로컬 서버다. 외부 공개 서비스/HTTPS 배포는 이 구성의 확인 범위가 아니다. HMI와 웹에 같은 HISTORY_DATABASE_DSN을 제공한다.

HMI에서 제작자 로그인→새 Job 진행→최종 검사 결과→명시 저장을 사용한다. 웹에서 같은 계정의 MY DESIGNS를 확인하고 필요할 때 PUBLISH/UNPUBLISH한다. 저장은 자동 공개가 아니다. 방문자는 공개 도안만 조회한다. DB 설정·웹 서버·인증 실패를 빈 성공 결과로 감추지 않는다.

기존 실제 JSONL을 CLI로 가져오려면 `python3 -m history --help`의 ingest/source-root/contract와 소유권 연결 옵션을 사용한다. 이번 배포에는 `history.mock_record`나 Docker demo가 없으며 기본 명령으로 안내하지 않는다.

## 현장 REAL 시험

이 절의 명령은 실제 로봇·그리퍼·제스처에 연결한다. offline C도 REAL 로봇을 MOCK으로 바꾸지 않는다. READ_STATE/실물 준비 확인은 REAL 세션을 연결할 수 있어 단순 파일 검사와 다르다.

현장 운영자가 기존 driver/Camera 상태·중복 제어 여부·TCP/Tool·공급/조립판 교시·모델·작업공간과 정지 수단을 확인한다. 현재 포함 교시를 다른 배치에 그대로 적용하지 않는다. 준비 과정에서 자동 driver 재시작·제어권 요청·mode/controller 변경을 하지 않는다.

이미 준비된 ROS/driver 환경과 카메라 RGB topic `/camera/color/image_raw`, 제스처 모델을 적용한 뒤 현장 운영자가 직접 실행한다.

```bash
export C2_ROBOT_ROOT="$PWD/robot_control_integration"
export C_DESIGN_USE_LLM=1
python3 -m app.mvp_real_trial   --robot-root "$C2_ROBOT_ROOT" --execute --c-mode live   --contact-alignment-trial --log-directory logs/full-feature-real
```

API 없이 C offline을 사용할 때는 `C_DESIGN_USE_LLM=0`, `--c-mode offline`으로 바꾼다. **실제 Robot·제스처와 합성 B는 유지된다.** 이 창의 B 가짜 검사 결과를 실제 Camera로 확정한 Current로 표현하지 않는다.

`scripts/cad_trial_ms02.sh full-real` 계열은 기존 ms-02 환경용이다. 다른 PC에서는 위 직접 실행 방법을 사용한다. 이 스크립트의 prepare/real/stack 분기는 별도 입력과 예전 Fixture를 요구할 수 있으므로 이 축소 배포의 기본 사용 경로로 안내하지 않는다. `scripts/roboton2.launch.py`와 `robot_driver_setup.py`는 실제 bringup/TCP·Tool·mode 설정에 관여하므로 모듈 검사 명령으로 실행하지 않는다.

### 현재 현장 동작

- 공급 접근은 상승→BODY_BYPASS→SUPPLY_TRANSIT→해당 슬롯 상부→하강의 MoveL이다. 슬롯 마지막 접근은24mm/s·12mm/s²다.
- 파지 후 이송은 기존 MoveB를 사용하고 경유 완료와 마지막 목표 MoveL 완료를 구분한다. 경유 허용값과 최종 1mm·1° 확인은 같은 조건이 아니다.
- `--contact-alignment-trial` 결착은6mm/s·6mm/s²로 하강하고 XYZ 전체 반력40N 이상에서 정지 확인 후 개방한다. desired-force40N/힘 유지 명령은 아니다. 실제 완전 체결·미끄러짐은 현장 확인한다.
- 조립 grid x>11은 Base X −1mm를 실행 목표 사본에 더한다. 원본 교시·native35 파일을 덮어쓰지 않는다.
- 조립판 수직 상승→B 검사→다음 Step 공급 슬롯으로 이어진다. 먼저 이전 공급 슬롯으로 복귀하지 않는다.
- 공급 슬롯은 종류/색상별1→6→1로 순환한다. 현장 보충 확인과 공급 상태는 운영자가 확인해야 하며 순환 자체가 실제 보충 증거는 아니다.

### 사람 응답·정지·재개

제스처가 분류되지 않으면 현재 요청의 **손으로 받을 준비 완료 / 도움 준비 완료 / 조립 완료·검사 진행 / 정렬 확인 완료** 버튼을 사용한다. 영상/모델 자체 연결 실패를 무시하는 기능은 아니다. 버튼 답변은 HMI의 작업자 응답이며 B의 실제 조립 관측이 아니다.

사람 조립·준비 시간 초과를 자동 완료로 처리하지 않고 응답을 기다린다. 재개는 준비 응답을 대신하지 않는다. 개방 전 알려진 인계 체크포인트와 마지막 목표 근처의 알려진 블렌딩 timeout 등은 현재 상태가 허용할 때 현장 운영자가 재개한다. 명령 결과·정지·파지가 불명확한 상태를 로그 수정/강제 RESUME로 복구하지 않는다.

새 코드가 병합돼도 이미 실행 중인 창에는 자동 적용되지 않는다. 새 Job은 별도로 시작하며 기존 Job/Current/예약이 자동 복원되는 것은 아니다.

## 문제 확인

| 문제 | 확인할 내용 |
|---|---|
| Import/프로세스 시작 실패 | 가상환경·의존성·D root·ROS overlay·모델/Camera와 stderr |
| 계획 실패 | 공개 블록/사유·원시 결과, 승인 목표·Current 보존, C 수정/재승인 |
| 참조/예약/Current 불일치 | 같은 plan/Step/평가/예약 및 최신 revision. 임의 재발급 금지 |
| B 관측 불가/ERROR | 관측 상태와 합성/실제 provenance, 다시 검사 또는 보류 |
| 파지·이동·정지·체결 확인 실패 | 해당 단계의 실제 피드백/명령 결과. 도달이나 힘 하나로 완성 판정하지 않음 |
| DB/웹 실패 | 같은 DB·제작자·Job·저장 키, 명시 저장/조회 재시도. 물리 조립 반복 없음 |

JSONL과 실행 문서는 각 `--log-directory` 아래에 기록된다. 오래된 D 폴더를 C2_ROBOT_ROOT로 지정하면 최신 통합 코드가 실행되지 않는다. 운영 로그·개인 키·DB 데이터를 Git에 올리지 않는다.

## 이 배포 구성의 확인 결과

2026-10-13 CPU에서 실행용 파일만 있는 별도 사본으로 C offline의 `의자` 요청→미리보기 승인→A 계산→MOCK D→합성 B→HMI·JSONL의15 Step 완료/Current revision15를 확인했다. A 전체 계획→재평가→이동 후보의 실행 허용 false도 확인했다. DB/웹 모듈은 별도 psycopg 의존성을 준비한 뒤 import를 확인했다.

회귀 검사는 README의 GitHub 보존 기준에서 가져온 별도 검증 사본을 사용하며 실행용 main에는 포함하지 않는다. 실제 LLM/음성·Camera·Robot·40N 체결·PostgreSQL 저장/웹 DB 왕복은 이 확인에 포함하지 않았다. 다른 PC의 외부 모델/driver 전체 설치도 별도 확인 대상이다.
