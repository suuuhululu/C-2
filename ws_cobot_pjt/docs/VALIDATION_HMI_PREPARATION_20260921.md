# HMI 준비·측정 흐름 검증 · 2026-09-21

- 작성: Codex / 사람 검토·실기 확인: 미수행.
- 기준: main `829db40418adde65236fe856fca2c23e24f13f00`.
- 작업: `codex/hmi-preparation-flow`의 미커밋 변경. 이번 작업의 push·PR·병합 없음.
- 검토 자료: 제어팀 준비 Action 초안 `6a020c9`, 원격 공정 작업 브랜치 `a0ba607`.
- 시험 수준: 구문·프런트 빌드·HMI MOCK·기존 ROS 경로 Action 회귀. **준비 ROS 왕복·실기 시험 아님.**
- 환경: 현재 편집 PC, Python 3.12.3, Node 24.19.0, ROS 2 Jazzy.
- ROS 경로 시험은 기존 c2_interfaces v2 설치본(`/tmp/c2-cancel-install`)을 사용했다. 신규 타입/패키지 빌드는 없다.
- 적용 조건: MOCK SIM 설정의 c2_base·고정 드릴 참조. 실제 로봇·그리퍼·제어기 연결 및 모션 호출 없음.
- 데이터: 자동 시험은 pytest 임시 DB, 브라우저는 별도 `/tmp/c2-hmi-preparation-ui.*` DB. 사용자 운영 DB는 사용하지 않았다.

## 결과

| 시나리오 | 기대 결과 | 실제 결과 | 판정·근거 |
| --- | --- | --- | --- |
| 준비→8점→새 설정→경로→모의 실행 | 같은 준비/측정/설정/경로 참조 유지 | 완료·ID/해시·base 좌표 일치 | 통과, test_preparation 및 브라우저 |
| 확인 누락·잘못된 타입·설정/높이 불일치 | 접수 거절 | 422 또는 PROFILE_MISMATCH | 통과 |
| 같은 요청 재전송·입력 변경 | 기존 결과 재조회 / 충돌 거절 | 중복 준비 생성 없음 / REQUEST_CONFLICT | 통과 |
| 준비·생성·실행 동시 접수 | 양방향 차단 | BUSY | 통과 |
| 취소·시간 초과 | 최종 중단 근거 확인 후 종료 | STOPPED / FAILED·TIMEOUT 구분 | 통과 |
| 늦은 성공·정지 미확인·최종 응답 없음 | 다음 작업 차단 | UNKNOWN 유지 | 통과 |
| 준비 실패·REFERENCE_ONLY | 원본 보존, 기하 설정 비활성 | 이전 설정 유지·실행 차단 | 통과 |
| 새 측정·서버 재시작 | 이전 경로/준비 자동 재사용 금지 | PROFILE_MISMATCH / 재준비 필요 | 통과 |
| 원본 변조·저장 실패·연결 응답 불일치 | 실행/새 설정 활성화 차단 | HASH_MISMATCH / UNKNOWN | 통과 |
| 위/아래 좌표 기준 | 비대칭 범위도 정확히 변환 | 윗면 v=[10,130] → 바닥 V=[20,140]mm | 통과 |
| 진행 저장과 종료 저장 경쟁 | 최종 상태가 오래된 진행에 덮어써지지 않음 | 준비 저장 직렬화·재현 시험 통과 | 통과 |
| ROS 준비 요청 | 확정되지 않은 Action 호출 금지 | NOT_READY, 요청 미전송 | 통과 |
| 기존 ROS 이미지 생성·취소·시간 초과 | 기존 v2 동작 유지 | 경로 등록/진단/취소/실행 차단 유지 | 통과, localhost DDS |
| 점별 UI | 명시적 점 성공만 초록 표시 | 역순·전체 COMPLETE로 점 성공을 만들지 않음 | 통과, Node 시험 |
| 브라우저 새로고침 | 같은 준비 진행 복원 | 옆면 진행 복원 후 8점·최종 완료 확인 | 통과, 수동 UI 조작 |

최종 백엔드 회귀 **89개 통과**, 별도 ROS 경로·타입 시험 **13개 통과**,
프런트 로직 시험 **9개 통과**. TypeScript 검사·Vite 빌드 통과.
Starlette 테스트 도구의 anyio 별칭 폐기 예고 1건이 각 pytest 실행에 표시됐다.
저장소 구문·문서 링크, Git hook 8개, Issue 도구 27개 및 설정 검사, `git diff --check` 통과.

브라우저는 준비 확인→요청→8점 진행 중 새로고침→완료→샘플 경로 생성→두 확인→MOCK 실행 완료(100%, 17구간)를 확인했다.
이는 HMI 합성 응답 시험이며 제어팀의 내부 SIM 시험 363개를 재실행한 결과가 아니다.

## 재현 명령

backend 디렉토리에서:

```bash
env -u PYTHONPATH PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_preparation.py tests/test_monitor.py tests/test_generation_cancel.py \
  tests/test_work_area.py tests/test_file_integration.py tests/test_path_artifacts.py
```

Jazzy와 같은 저장소의 c2_interfaces 설치 환경을 source한 backend 셸에서:

```bash
C2_RUN_ROS_TESTS=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_ros_path_integration.py tests/test_ros_contract.py
```

ROS 시험 fixture가 도메인 174·LOCALHOST·Fast DDS·임시 저장소를 설정한다. 로봇 노드는 실행하지 않는다.
준비 Action의 ROS 시험을 실행하는 명령이 아니다.

frontend 디렉토리에서:

```bash
node --experimental-strip-types --test tests/preview.test.mjs tests/work_area.test.mjs tests/preparation.test.mjs
pnpm exec tsc -b
pnpm build
```

이번 환경에서는 번들 Node 실행 경로와 설치된 TypeScript/Vite 진입점을 사용했다.

## 남은 검증

- 준비 Action 이름·필드·버전과 상세 원본 전송·스냅샷 연결 응답을 합의한 뒤 HMI RosBridge/공정 수신부 동시 연결.
- 좌표팀의 요청별 실측 프로파일 지원 후 같은 경로로 ROS SIM 전체 왕복 검증.
- 실기 오프셋·TCP/하중·드릴 OFF 확인 전달·취소 후 정지·최종 관절 검사와 조각은 별도 현장 검증.
- 브라우저 운영자 ID는 기존 로컬 개발 사용자이며 실제 인증·확인 유효기간은 미확정.

[사용 방법·현재 구현과 미확정 계약](HMI_PREPARATION.md)
