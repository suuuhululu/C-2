# HMI 상하 10mm 작업 영역 검증

- 날짜/작성: 2026-09-21 / Codex. 사람 검토·실기 확인 없음.
- 기준: 원격 main `19ef4c6bb2674dceb8acdf6d57f8ac80d34e1ab6` 재확인.
- 결과: `codex/hmi-work-area-limits`에서 이 기록을 포함하는 커밋. 아래 시험은 커밋 전 작업 트리에서 수행했으며, 기존 경로 생성 취소 변경을 보존했다.
- 범위: HMI 설정·HTTP snapshot·표시·MOCK 검증. 이번 작업에서 c2_path·ROS 타입·로봇 설정 변경 없음.
- 환경: Linux, backend/.venv Python 3.12, 번들 Node, 임시 DB. 로봇 비구동.

| 시나리오 | 결과 |
| --- | --- |
| 높이 150mm, 상하 10mm 제외 | 바닥 V·윗면 v 모두 10~140mm, 작업 높이 130mm |
| 높이 200mm | 현재 스냅샷 높이를 사용해 10~190mm 표시 |
| 상단 10mm·하단 20mm | 윗면 10~130mm ↔ 바닥 20~140mm, 역방향 변환 확인 |
| 현재 ROS 프로파일 85~130mm | 새 합의 기준과 불일치 판정. 원본 프로파일·해시는 변경하지 않음 |
| 범위 누락·역전·높이 초과 | 영역 미확인 반환, 임의 기본값 없음 |
| 설정 재등록 | 동일 ID·해시 재사용, 공통 경로 프로파일과 별도 자산 |
| MOCK 높이 200mm·작업 범위 40~180mm | 기존 고정 10~140mm를 사용하지 않고 프로파일 기준 생성·실패 진단 |
| 기존 생성 취소·경로 참조·파일 통합 | 선택 회귀 시험 통과 |

실행 결과:

- backend: `tests/test_work_area.py tests/test_monitor.py tests/test_generation_cancel.py tests/test_path_artifacts.py tests/test_file_integration.py` — **64 passed**, 22.02초. Starlette deprecation 경고 1건.
- 제한된 샌드박스에서 TestClient 초기화가 대기해 중단했다. 단일 사례 스택을 확인하고 샌드박스 밖에서
  새 시험 4개 및 위 전체 선택 시험을 임시 DB로 실행해 통과했다. 제품 서버·사용자 DB는 재시작하거나 변경하지 않았다.
- frontend: `tsc -b`, Node `tests/preview.test.mjs tests/work_area.test.mjs`, Vite build 통과.
- 저장소 검사: 문서·구문·링크 152개, hook 8개, issue manager 설정 및 시험 27개, `git diff --check` 통과.

미수행/남은 항목:

- 실제 브라우저 시각 검증·실기·이번 변경 후 ROS 통합 재시험은 수행하지 않았다.
- ROS 좌표 계산은 기존 고정 높이 범위를 유지한다. 요청별 스냅샷에 10~140mm를 반영하는 좌표 담당 변경이 필요하다.
- 단위 시험은 표시 좌표 변환과 모의 범위를 검증한 것이며 실제 CUT 보간·접근·이탈·관절 검증이 아니다.
- 적용/한계: [HMI 작업 영역 안내](../HMI_WORK_AREA.md). 프런트 빌드 후 백엔드 재시작·브라우저 새로고침 필요.
- 게시 상태는 이 변경을 포함한 PR에서 확인한다. 이 검증 기록은 병합·실기 승인을 뜻하지 않는다.
