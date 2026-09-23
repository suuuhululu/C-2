# REAL entry 배포 정책 정적 검증 · 2026-09-23

- 시험명: REAL entry 정책 조기 검사와 실측 기하 분리
- 작성자: Codex 지원 작업
- 확인자: 팀 검토 필요
- 날짜: 2026-09-23
- 기준: `origin/main` `b9eb003`, 작업 브랜치 `codex/real-contract-fix` 미커밋 변경
- 시험 수준: Python 정적 검사·단위 시험·격리 ROS 빌드. 로봇 연결·ROS 서비스·모션·실기 미수행
- 적용 계약: 공개 ROS 타입 변경 없음. 배포 실행 프로파일의 `execution_context.entry_planning`을 HMI가 읽기 전용 사전 검사하고, 측정 후 불변 스냅샷의 `workcell.entry_planning`으로 복사

| 시나리오 | 기대 결과 | 실제 결과 | 판정 | 증거 |
| --- | --- | --- | --- | --- |
| 유효한 entry 정책 | 입력 JSON을 변경하지 않고 사전 검사 통과 | 통과, 원본과 깊은 복사 분리 확인 | 통과 | `test_same_fixed_depth_settings_pass_both_without_rewriting`, `test_current_confidence_overwrites_template` |
| entry 정책 누락 | 측정 요청 전 명확한 오류 | `entry_planning.enabled=true` 오류 | 통과 | `test_entry_policy_is_required_before_measurement` |
| 범위·양수·모션 프로파일 오류 | 측정 요청 전 거절, 입력 불변 | 각 오류 거절, 입력 불변 | 통과 | `test_invalid_entry_policy_is_rejected_without_rewriting` |
| 실행 프로파일의 임시 표면값 | 이번 측정 중심·반지름·높이로 대체 | 측정 `radius_m`, `height_m`, `axis_xy_m`, `bottom_z_m` 반영 | 통과 | `test_current_confidence_overwrites_template` |
| 공정 entry planner·REAL 설정 회귀 | 후보 검사·실패 차단·해시 고정·정책 이중 원본 불일치 차단·공정 순서 유지 | 관련 공정 시험 통과 | 통과 | `test_entry_planner.py`, `test_node.py` |
| 9/23 배포 실행 후보 | 7점 승인값은 후보 표면에만 기록하고 BIND가 새 측정 기하로 대체 | `real_execution_profile_20260923.json` 검사 통과, 후보 top 0.215929474 m와 entry TCP Z 0.300~0.330 m 확인 | 통과 | `validate_real_execution_config`, JSON 정합성 검사 |
| 측정 설정 부분 혼합 방지 | 담당자 코드·탐색 범위·복구 시험이 오기 전 기존 main 설정 유지 | 7점 중심 또는 중심 허용차만 단독 변경하면 각각 공정 시험 40건/32건 실패함을 확인하고 원복 | 통과 | 공정 전체 회귀 시험 |

## 실행 결과

- backend 전체 시험: `223 passed, 5 skipped`, 경고 1개(Starlette 지원 중단 예정 API). 이 중 REAL 설정·스냅샷 관련 선별 시험은 `72 passed`.
- 공정 패키지 전체 시험: `924 passed, 5 skipped`
- 경로 패키지 전체 시험: `234 passed`
- 격리 ROS 빌드: `c2_interfaces`, `c2_path`, `c2_process` 3개 성공
- `colcon test`: `c2_interfaces` 18건 통과. 시스템 Python에는 `scikit-image`가 없어 `c2_path` 수집이 중단됐으며 저장소 고정 가상환경의 별도 전체 시험 234건으로 확인했다. `c2_process`는 colcon 시험 등록이 없어 0건이며 위 pytest 전체 시험으로 확인했다.
- `python3 tools/check_repository.py`: 241개 파일의 텍스트·Python 구문·상대 문서 링크 통과
- `python3 tools/test_git_hooks.py`: 8개 통과
- `python3 tools/issue_manager.py`: 설정 형식 정상, 네트워크·변경 없음
- `python3 tools/test_issue_manager.py`: 27개 통과
- `git diff --check`: 통과

## 미확인 한계

- entry 이동·전체 메시 충돌·가공 품질은 실기 미검증이다.
- 배포 실행 후보의 entry 정책은 감독하 HOME과 7점 측정값으로 계산했으나 실제 entry 이동 승인값은 아니다. 새 8점 측정·BIND 후 읽기 전용 IK 검사와 `ENTRY_ONLY` 감독 시험이 필요하다.
- 2026-09-23 HOME 비접촉 정지 상태의 병진 외력은 리셋 전 약 3.83 N이었다. DRL `set_external_force_reset()` 실행 중 약 0.137 N으로 내려갔지만 DRL 종료 후 약 3.686 N으로 복귀했다. 현재 ROS 측정 노드에 지속되는 영점 보정은 확인되지 않았으므로 담당자 수정 커밋 전 8점 측정을 재실행하지 않는다.
- 담당자의 측정 수정은 아직 원격 커밋 SHA가 없고 8/8 결과 JSON·HOME 복귀·`/c2/prepare_workpiece` REAL Action도 미검증이다. 해당 커밋을 받은 뒤 측정 설정과 시험을 한 세트로 통합한다.
