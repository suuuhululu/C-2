# 9/18 Clay 수정본 보관과 새 구조로의 이관 검토

2026-09-19, 관련 [Issue #19](https://github.com/suuuhululu/C-2/issues/19)·[PR #20](https://github.com/suuuhululu/C-2/pull/20). main `23eec53`은 PR #16에서 기존 Clay 코드·실행 안내를 제거했고, PR #20 `db54a28`은 같은 파일 3개를 수정했다. 사용자 승인에 따라 최신 원본을 먼저 보관한 뒤 main의 제거 방향으로 충돌을 해결한다.

## 보존한 원본과 복구

| 항목 | 기록 |
| --- | --- |
| 최신 원본 커밋 | `db54a28cb995befd33bcca74e11a12a2f00837a7` |
| 보관 범위 | 당시 `clay_carving/`, `clay_hmi/`, `doc/clay_run.md` 전체 37개 파일. 9/18 추가 스크립트 5개 포함 |
| 편집 PC의 보관 위치 | C-2 밖의 `~/local_file/clay_archive_pr20_2026-09-19/`. 파일은 원래 상대 경로 유지 |
| 검증 | Git 원본과 복사본 37개 바이트 일치, 파일별 SHA-256 기록. 원본 커밋을 포함한 Git bundle도 별도 보관 |
| 공유한 보존 근거 | [파일별 크기·SHA-256 목록](evidence/clay_pr20_archive_manifest.json). 백업 소스와 bundle은 Git에 추가하지 않음 |

PR #16의 [기존 보관 기록](LEGACY_CLAY_ARCHIVE.md)은 `c414821` 기준 32개 파일이다. 이번 최신본은 그 이후의 수정·추가를 포함하므로 두 보관본을 구분한다. main을 병합한 새 커밋도 `db54a28` 이력을 유지한다. 다음 고정 링크에서 같은 원본을 확인할 수 있다.

- [최신 Clay 소스와 보조 스크립트](https://github.com/suuuhululu/C-2/tree/db54a28cb995befd33bcca74e11a12a2f00837a7/ws_cobot_pjt/ws_cobot1/src/clay_carving)
- [당시 실행 안내와 9/18 추가 옵션](https://github.com/suuuhululu/C-2/blob/db54a28cb995befd33bcca74e11a12a2f00837a7/ws_cobot_pjt/ws_cobot1/doc/clay_run.md)

복구·이관 시에는 별도 작업 공간에서 이 고정 커밋 또는 검증한 보관본을 읽는다. 현재 실행 폴더에 통째로 복원하거나 이전 장비 설정으로 실행하는 절차가 아니다. 이번 작업에서는 로봇·ROS·모의 가공을 실행하지 않았다.

## 문서와 실측 자료 보존

- [양초 실기 상세 기록](daily/2026-09-18-candle.md): 기존 PR #20의 좌표·송곳/드릴 육안 결과·물결무늬 실패·당시 후속 계획을 보존했다.
- [실기 시행착오 11건](LESSONS_ROBOT.md): 보고된 현상과 당시 수정안을 보존하고 현재 승인된 설정과 구분했다.
- [상태 원자료](evidence/clay_state_0918_candle.json): 원본 바이트 그대로 보존했다.
- [당시 workcell 후보값](evidence/workcell_candle_0918.yaml): 데이터 값은 유지하고 문서 경로·적용 범위 주석만 갱신했다. [미합의 항목과 해석 범위](evidence/CANDLE_0918_EVIDENCE.md)를 함께 읽는다.

팀 전체 개발 일지 [PR #18](https://github.com/suuuhululu/C-2/pull/18)의 `daily/2026-09-18.md`와 양초 상세 기록은 서로 다른 문서로 유지한다. 같은 날짜라는 이유로 어느 한 기록을 덮어쓰지 않는다. PR #18은 Notion·GitHub 종합 기록, 이 PR은 양초 실기 상세·실측 근거다.

## 재사용할 내용과 담당 경계

다음 표는 이관 검토 목록이며 구현 완료가 아니다. [인터페이스 안내](INTERFACE_GUIDE.md)·[디렉토리](SYSTEM_STRUCTURE.md)·[공통 계약](INTERFACE_RECOMMENDATION.md)의 노드 책임을 따른다.

| 보관한 파일·기능 | 이관을 검토할 위치 | 이관 전에 확인할 조건 |
| --- | --- | --- |
| `clay_scan2.py`의 물체·손끝 기하, 원 맞춤 | 고정 작업대상 등록·검증 자료, 승인된 `workcell.yaml` | 접촉부·자세·프레임·실측/추정값 구분. 매 작업 자동 스캔을 기본 공정에 추가하지 않음 |
| `force_probe.py`의 접촉 관측 | `c2_process`의 도구 보정·가공 조건 및 `robot_adapter.py` 경계 | 힘 프레임·유효 시각·판정 근거·완료·정지 조건. 임시 임계값 복사 금지 |
| `side_heart.py`의 곡면 기하와 실행 순서 | 기하는 `c2_path/map_3d.py`·경로 생성, 실행은 `c2_process/engraving.py` | 도구 끝 m·quaternion xyzw 경로와 실제 제어기 TCP 변환 분리. 하트 점 생성과 로봇 호출을 한 함수로 이관하지 않음 |
| `orbit_wave.py`의 회전 범위·드리프트 실패 사례 | `c2_path` 경로 검증, `c2_process` 준비·완료 검사 | J6·이음매·도구 오프셋·거짓 접촉 사례 재현. 수정본 실기 미검증 유지 |
| `goto_home2.py`의 접근·이탈 문제 | `tool_sequence.py` 또는 명시된 APPROACH/RETRACT 경로 | 물체·장착 도구·이동 영역을 검증한 프로파일, 자동 오류 복귀 금지 |
| `fk.py`의 읽기용 정운동학 | 별도 진단 도구 검토 | URDF·관절 단위·프레임·TCP 대조. 계산 자세를 장치의 실제 완료 피드백으로 대체하지 않음 |
| `scripts/README.md`, `clay_run.md` | 이 기록과 고정 커밋 링크 | 과거 실행 명령을 현재 시작 절차로 되살리지 않음 |

모니터는 위 보정·기하·모션을 중복 구현하지 않고 승인된 파일 ID·설정 스냅샷을 요청·표시한다. 재사용 코드는 별도 구현 PR에서 공통 타입·단위·실패/정지 시험과 함께 검토한다. 이번 문서 정리에서는 `/c2/*` 계약·버전이나 실행 설정을 변경하지 않았다.
