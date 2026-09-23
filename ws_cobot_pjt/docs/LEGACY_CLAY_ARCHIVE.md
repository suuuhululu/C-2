# 기존 Clay 코드의 로컬 보관·제거 기록

2026-09-18 사용자 요청에 따라 기존 Clay 코드와 전용 실행 안내를 **C-2 저장소 밖에 먼저 복사하고 파일별 SHA-256 일치를 확인한 후** Git 관리 대상에서 제거했다. 새 `c2_process/robot_adapter.py`와 해당 시험은 유지했다.

| 항목 | 범위 |
| --- | --- |
| 원본 기준 | `c414821d23c3083a0b160efc8d523e1739e7dd1d` |
| 제거 경로 | `ws_cobot_pjt/ws_cobot1/src/clay_carving/`, `ws_cobot_pjt/ws_cobot1/src/clay_hmi/`, `ws_cobot_pjt/ws_cobot1/doc/clay_run.md` |
| 보관 위치 | 사용자 상위 프로젝트의 `local_file/clay_archive_2026-09-18/` (C-2 clone 밖) |
| 보관 내용 | 원래 상대 경로를 유지한 32개 파일, README, 파일별 바이트 수·SHA-256의 MANIFEST.json |
| 검증 | 32개 원본과 백업의 바이트 해시 일치. 현재 작업 트리의 해당 파일 제거 확인 |
| 기존 시험 기록 | 당시 보고를 포함한 실행 안내는 보관본과 아래 고정 커밋에서 확인 가능. 새 공정의 실기 검증 결과가 아님 |

이 변경은 현재 관리 대상에서 제거하는 변경이며 과거 Git 이력을 재작성하지 않는다. 백업은 저장소에 올리지 않는다. 다른 팀원이 과거 구현을 확인해야 하면 다음 고정 커밋 링크를 사용한다.

- [기존 clay_carving 소스](https://github.com/suuuhululu/C-2/tree/c414821d23c3083a0b160efc8d523e1739e7dd1d/ws_cobot_pjt/ws_cobot1/src/clay_carving)
- [기존 clay_hmi 소스](https://github.com/suuuhululu/C-2/tree/c414821d23c3083a0b160efc8d523e1739e7dd1d/ws_cobot_pjt/ws_cobot1/src/clay_hmi)
- [기존 실행 안내](https://github.com/suuuhululu/C-2/blob/c414821d23c3083a0b160efc8d523e1739e7dd1d/ws_cobot_pjt/ws_cobot1/doc/clay_run.md)

복구가 필요한 경우 별도 작업 브랜치에서 위 커밋의 세 경로를 복원하거나 로컬 보관본을 복사하고 관련 실행 안내·의존성을 함께 검토한다. 과거 장비 설정을 현재 승인된 값으로 자동 적용하지 않는다.

현재 개발 기준은 [인터페이스 안내](INTERFACE_GUIDE.md)와 [시스템 구조](SYSTEM_STRUCTURE.md)다. 이전 개발 일지의 Clay 설명은 당시의 기록으로 보존하며 현재 실행 구조로 사용하지 않는다. 삭제의 원격 게시·병합 여부는 해당 브랜치·PR의 상태로 판단한다.

## PR #20의 후속 수정본 · 2026-09-19

PR #16이 main에 병합된 뒤 PR #20에는 기존 Clay 파일 수정과 보조 스크립트 추가가 남아 있었다. `db54a28` 기준 최신 37개 파일을 별도로 보관·대조한 뒤 기존 코드 제거 방향으로 충돌을 해결했다. [9/18 수정본 보관·이관 검토](CLAY_0918_MIGRATION.md)에 원본 커밋·파일 해시·실측 문서·복구 근거를 남겼다. 위 32개 파일의 이전 보관본과 구분한다.
