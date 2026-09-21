# HMI 공통 스냅샷·파일 통합 시험

2026-09-21. 기준 main: `be023a9` (PR #39 병합).
HMI 담당 범위에서 등록·전달·결과 미리보기를 구현했다.
공통 ROS 타입 v2, 경로 생성 계산, 공정·로봇 모션은 변경하지 않았다.

## 구현 범위와 계약 상태

- 스냅샷 JSON 등록·선택·원문 값 보존·실제 UUID/SHA-256 발급.
- 등록된 입력 이미지·스냅샷·GeneratePath 요청을 ZIP으로 내보내기.
- 경로·SVG·preview·검증 보고서·Result가 들어 있는 ZIP 가져오기.
- 기존 `c2-path-preview/1` 로더로 검증 후 두 미리보기 표시.
- 같은 입력·산출물 바이트의 공정팀 전달 ZIP 내보내기.
- 파일 교환은 실제 ROS 통신 시험과 별도다. 생성·실행을 자동 요청하지 않는다.
- 가져온 경로는 `origin=FILE_BUNDLE`, `test_only=true`, `execution_enabled=false`다.
  화면뿐 아니라 POST runs에서도 실행을 거절한다.

**등록 성공은 공정 설정의 승인·검증 완료가 아니다.**
등록 시 JSON 객체, schema_version=2, source_mode=SIMULATION, 명시된 실기 금지 필드를 검사한다.
workcell/tip_calibration/motion/stop/joint 설정은 임의 생성하거나 다른 키로 변환하지 않는다.
팀의 최종 공통 JSON 스키마와 측정 요청·결과 계약은 여전히 합의 대상이다.

파일 교환용 선택은 기존 ROS/MOCK 생성 프로필과 독립적으로 저장한다.
따라서 스냅샷을 선택해도 실행 중인 ROS 노드의 고정값 검증 구조를 바꾸지 않는다.
새 측정 기반 프로필을 경로 노드·HMI 표시로 연결하려면 홍동님 변경본과 함께 검토해야 한다.
현재 결과 가져오기는 surface 등 기존 PR #38/39 경로·preview 계약을 만족해야 한다.

## 한 PC에서 사용

기존 설치·실행은 [HMI 경로 통합 안내](HMI_PATH_INTEGRATION.md)를 따른다.
파일 교환 화면 자체는 MOCK/ROS 양쪽에서 사용한다.

1. 기존 실행 방법으로 HMI를 시작하고 **파일 통합 시험**으로 이동한다.
2. **스냅샷 JSON 등록**에서 팀이 전달한 SIM JSON을 등록한다. 1 MiB 이하.
3. 선택된 UUID·해시·JSON을 확인한다. 필요한 경우 **최종 저장 JSON 내려받기**를 사용한다.
4. 이미지를 첨부하고 너비·높이·U/V·회전을 지정한다. 작업 준비 화면의 이미지와 배치도 공유한다.
5. **입력 묶음 준비 → 입력 ZIP 내려받기**. 이 단계는 경로 생성 완료가 아니다.
6. 경로 생성 담당자가 같은 입력으로 계산하고 아래 결과 묶음을 준비한다.
7. **결과 ZIP 가져오기**. 입력·해시·ID·preview·보고서 연결을 검증한 뒤 등록한다.
8. 전개면·원기둥 미리보기와 미검사 항목을 확인한다.
9. **공정팀 전달 ZIP 내려받기**로 같은 파일을 전달한다. 공정 로더·모의 실행 연결은 공정팀 담당이다.

HMI는 서버의 임의 폴더를 직접 탐색하지 않는다.
사용자가 ZIP을 공통 작업 폴더로 내려받고 결과 ZIP을 선택한다.
ZIP 내부는 폴더 없는 평평한 파일 목록으로 정해 개인 PC 절대 경로를 전달하지 않는다.
압축 파일 32 MiB, 해제 총량 64 MiB, 최대 16개 파일 제한이다.
선택·가져오기는 생성/실행 중 또는 실행 상태 UNKNOWN일 때 차단한다.

## 스냅샷과 ID·해시

저장 시 UTF-8, 정렬된 키, 공백 없는 JSON으로 직렬화한다.
추가 필드와 값은 보존하지만 업로드 파일의 들여쓰기·키 순서는 그대로 보존하지 않는다.
**내려받은 최종 저장 바이트의 SHA-256**을 경로 생성·공정에서 사용한다.

- 같은 정규화 내용의 재등록은 같은 ID·해시를 반환한다.
- 내용이 바뀌면 새 ID·해시로 등록한다. 과거 파일은 수정하지 않는다.
- 자기 자신의 profile_snapshot_id/profile_sha256은 JSON 본문에 넣지 않는다.
  이 정보는 등록 응답·goal.json·manifest.json의 profile 항목으로 전달한다.
- 선택 ID는 integration_selection 테이블에 저장되어 재기동 뒤 유지된다.
- mode의 기본 프로필 생성과 파일 교환 프로필 선택은 별도다.

등록만으로 실측 여부·좌표 최신성·도구 보정 완전성이 확인되는 것은 아니다.
SIM용 합성값과 측정값의 출처 표기는 데이터 제공자가 명시해야 한다.

## HMI 파일 교환 v1

`c2-hmi-bundle/1`은 이번 HMI가 구현한 **파일 교환 규격 제안**이다.
ROS schema_version=2 및 미정인 공통 공정 JSON 형식과 별개다.
송신 담당자는 아래 규격을 확인하고 샘플 묶음으로 상호 검증해야 한다.

입력 ZIP:

```text
manifest.json
goal.json
snapshot.json
input.png 또는 input.jpg
```

결과 ZIP은 위 파일을 유지하고 다음을 추가한다.

```text
result.json
path.json
diagram.svg
preview.json
validation.json
```

manifest 구조 (각 꺾쇠 값은 실제 값으로 교체; 그대로 실행하는 샘플 아님):

```json
{
  "format": "c2-hmi-bundle/1",
  "source_mode": "SIMULATION",
  "purpose": "generation-result",
  "goal": {"file": "goal.json", "sha256": "<실제 파일 SHA-256>"},
  "result": {"file": "result.json", "sha256": "<실제 파일 SHA-256>"},
  "files": [
    {
      "asset_id": "<실제 파일 UUID>",
      "kind": "path",
      "file": "path.json",
      "sha256": "<실제 파일 SHA-256>",
      "mime": "application/json",
      "metadata": {"path_id": "<논리 경로 UUID>", "path_version": 1}
    }
  ]
}
```

위 files는 구조 설명용 한 항목이다. **결과에는 아래 6종을 각각 정확히 한 개씩 넣는다.**
입력 ZIP에는 image/profile 두 항목만 있으며 purpose=generation-input, result 항목은 없다.

| kind | 연결 ID | metadata | MIME |
| --- | --- | --- | --- |
| image | goal.asset_id | 입력 manifest의 객체 그대로 | image/png 또는 image/jpeg |
| profile | goal.profile_snapshot_id | 입력 manifest의 객체 그대로 | application/json |
| path | 별도 파일 UUID | path_id, path_version | application/json |
| svg | result.svg_asset_id | path_id | image/svg+xml |
| preview | result.preview_asset_id | path_id | application/json |
| validation | result.validation_report_id | path_id | application/json |

path_id는 논리 경로 ID이고 path 파일의 asset_id는 별도다.
입력 ZIP의 image/profile ID·해시·파일 바이트·metadata·MIME는 변경하지 않는다.
goal.json은 내보낸 GeneratePath 요청과 정확히 같아야 한다.
path/preview/report 안의 입력·스냅샷·요청·경로 ID 참조도 서로 일치해야 한다.
result.path_sha256은 path.json의 **실제 바이트 해시**다.
미리보기는 path의 같은 좌표·구간을 가리켜야 하며 임의로 분리 구간을 연결하지 않는다.

result.json은 현재 GeneratePath Result의 아래 필드만 모두 포함한다.

```text
success, error_code, message, path_id, path_version, path_sha256,
svg_asset_id, preview_asset_id, segment_count, cut_length_m,
validation_passed, validation_report_id
```

성공/validation_passed=true, error_code=NONE 결과만 미리보기로 등록한다.
실패 결과 묶음의 보관·표시는 후속 범위다. 실패를 성공으로 바꾸어 가져오면 안 된다.
통신의 Result에는 path_asset_id가 없으므로 파일 UUID는 manifest에서 전달한다.
해시는 파일 무결성을 대조하기 위한 것이며 작성자 인증·실기 승인 서명이 아니다.

## 등록과 실패 처리

1. ZIP 이름·중복·링크·크기·목록·해시 검사. 서버 경로로 압축을 풀지 않는다.
2. HMI가 내보낸 요청과 등록 입력 이미지/스냅샷 대조.
3. 별도 임시 저장소에서 기존 PathArtifactLoader로 의미·참조·표시 좌표 검증.
4. HMI DB 쓰기 트랜잭션에서 충돌 재확인, 신규 파일과 path_versions/결과 등록.
5. 중간 실패 시 새 파일 정리와 DB 롤백. 기존 파일을 덮어쓰지 않는다.

동일 결과 재전송은 기존 결과를 반환한다.
기존 요청/경로/asset ID의 내용·해시·메타데이터가 다르면 거절한다.
프로세스 강제 종료·전원 차단 시 새 파일의 잔여물이 남을 수 있다.
잔여물로 인한 충돌을 자동 덮어쓰지 않으며 운영 DB 복구·정리 도구는 이번 범위 밖이다.

기존 DB user_version=1은 유지한다. 파일 교환 선택만 위한 integration_selection 테이블을 추가한다.
기존 경로·실행 기록을 수정하지 않는다. 되돌릴 때 추가 테이블과 EXPORTED 기록은 보존 가능하다.
EXPORTED 요청은 파일 전달 상태이며 ROS/MOCK 생성 작업을 자동 재시작하지 않는다.

## HTTP API

POST에는 기존처럼 X-C2-Monitor: 1 헤더가 필요하다.
API 위치는 /api/operator 아래다.

| 요청 | 의미 |
| --- | --- |
| GET /integration/profiles | 등록 목록·선택 ID·공통 계약 검증 대기 상태 |
| POST /integration/profiles | multipart file: SIM JSON 등록 후 파일 교환용 선택 |
| POST /integration/profiles/{id}/select | 등록된 프로필 선택 |
| GET /assets/{id}/content | 최종 저장된 JSON 바이트 조회 |
| POST /integration/inputs | GeneratePath Goal 검증·EXPORTED 기록·다운로드 URL 반환 |
| GET /integration/inputs/{request_id} | 원본 입력 ZIP 다운로드 |
| POST /integration/results | multipart file: 결과 ZIP 검사·등록 |
| GET /integration/paths | 가져온 경로 목록 |
| GET /paths/{id}/versions/{version} | 기존 검증된 미리보기 조회 |
| GET /integration/paths/{id}/versions/{version}/bundle | 같은 입력과 결과의 ZIP 다운로드 |

## 담당별 남은 합의

- 시율: 양초 실측·TipCalibration의 실제 제공 필드, 단위/좌표계/근거, SIM·실측 구분.
- 홍동: 측정값을 허용하는 프로필 검증, workcell↔surface 변환, tools_config 필드 검증.
- 세은: 공통 스냅샷에서 실행 함수 입력을 만드는 로더, 런타임 취소·현재 상태 처리,
  동일 경로의 관절 검사·실행과 깊이 단일 적용.
- 수현: 합의된 스키마로 결과 로더/표시 갱신, 준비·측정 요청/결과 API가 확정된 뒤 화면 연결.

검증 근거는 [2026-09-21 기록](validation/2026-09-21-hmi-file-integration.md)을 따른다.
