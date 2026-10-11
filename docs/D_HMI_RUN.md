# C2 Qt HMI 실행 안내

수현의 C2_HMI_20261011 압축본에서 이식한 HMI입니다. 1차 통합에서 공통 layer 1~5와 B 검사 결과 계약을 적용했습니다. [검토·연결 범위](D_HMI_DB_ROUND1.md)를 먼저 확인하세요.

## 포함 범위

Qt 화면·블록 입체 투영·설계 대화·실행·검사·도움·완료·요청 표시, 기존 가짜 화면 사례, HMI Schema와 관련 검사만 포함합니다. `current.py`·`completion.py`·`contracts.py`는 기존 HMI가 import하는 배치 키·Current 및 입력 검증 때문에 기존 검증 코드를 사용하며 공통 layer 상한은 5층입니다. 화면 실행은 이 파일의 공정 채택·완료 알고리즘을 호출하지 않습니다.

아래 독립 화면 예시는 Backend 실행부, 실제/Fake Robot 제어기, ROS, Camera, C/A 모듈, 음성·LLM 호출, DB를 호출하지 않습니다. 현재 화면 예시에는 직접 조립/도움/DB/웹 상태도 있지만 표시용 Fixture이며 실제 기능 연결 성공을 의미하지 않습니다.

## 설치 및 실행

저장소 루트(requirements.txt와 app 폴더가 있는 위치)에서 실행합니다. 현재 검증 환경은 Ubuntu·Python 3.12.3·PyQt5 5.15.10입니다. 다른 컴퓨터의 OS·DPI·폰트·그래픽 환경은 아직 검증하지 않았습니다.

Ubuntu/Linux 또는 macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m app.hmi_mvp_demo
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m app.hmi_mvp_demo
```

실제 화면을 열 때 `QT_QPA_PLATFORM=offscreen` 설정을 해제합니다. Linux에서는 `env -u QT_QPA_PLATFORM python -m app.hmi_mvp_demo`로 실행할 수 있습니다. 한글이 깨지면 운영체제에 Noto Sans CJK KR 등 한글 글꼴을 설치하세요. Ubuntu의 Qt 플랫폼 플러그인이 실패하면 해당 시스템의 xcb/OpenGL GUI 라이브러리 설치가 필요할 수 있습니다.

기본 사례는 `draft_updated`입니다. 화면 상단 사례 선택으로 누적 Current·다음 목표·차이·가림·정지·완료 등을 비교할 수 있습니다. 창 기본 크기는 현재 코드대로 1200×900이며 작은 화면에서는 가용 화면 크기에 맞춥니다.

```bash
python -m app.hmi_mvp_demo --help
python -m app.hmi_mvp_demo --interactive
```

`--interactive`는 기존 신규 요청 버튼의 가짜 접수/거절만 시험합니다. 시작/정지/재개와 실제 공정 명령은 이 독립 예시에서 비활성입니다. 요청 접수는 실제 동작 완료가 아닙니다.

## 실제 Backend와 연결할 때

`app.qt_hmi.HmiWindow`를 생성하고 동일 프로세스의 연결 코드에서 `window.snapshot_received.emit(snapshot)`으로 최신 snapshot 전체를 전달합니다. 화면 명령은 `window.command_requested`, 확장 요청은 `window.mvp_request_requested` 신호입니다. 확장 응답은 `window.mvp_reply_received.emit(reply)`로 전달합니다. 정확한 필드는 `interfaces/schemas/hmi.schema.json`과 `app/hmi_contracts.py`·`app/hmi_mvp_contracts.py`, 예시는 `interfaces/fixtures/`를 확인하세요.

이 압축본에는 통신 서버나 별도 컴퓨터 간 연결이 없습니다. HMI와 Backend를 다른 컴퓨터에서 연결하려면 기존 환경에 맞는 통신 연결이 별도로 필요합니다. HMI는 Current/Expected·Step 완료·Robot 경로를 생성하지 않습니다.

## 장치 없는 검사

```bash
python -m pip install -r requirements-test.txt
python -m app.hmi_mvp_contracts
```

Linux/macOS:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/unit -q
```

Windows PowerShell:

```powershell
$env:QT_QPA_PLATFORM="offscreen"
python -m pytest tests/unit -q
Remove-Item Env:QT_QPA_PLATFORM
```

원본 압축본의 `PACKAGE_MANIFEST.json`·`verification/`은 패키지 생성 당시 증거이며 저장소 실행 파일에 포함하지 않습니다. 이번 통합 검증은 [HMI·DB 1차 통합](D_HMI_DB_ROUND1.md)을 따릅니다. 테스트는 합성 화면 검증이며 장치·실제 관측 검증이 아닙니다.

## 이번 포장 검증 결과

압축을 별도 임시 폴더에 풀고 원본 저장소 없이 실행했습니다. 기존 HMI 검사 202 passed, 실패/오류/skip 0, 종료 코드 0입니다. 가짜 화면 55개 사례를 offscreen으로 렌더링했고, 실행 도움말 및 Fixture 검사도 종료 코드 0입니다. 다른 PC와 실제 Backend·장치 연결은 검증하지 않았습니다. 원본 화면 코드의 배치/표시 특성은 그대로 보존했습니다.
