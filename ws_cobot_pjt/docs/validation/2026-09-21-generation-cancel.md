# 경로 생성 취소·복원 검증 · 2026-09-21

- 작성: Codex / 사람 검토·실기 확인 없음
- 기준: main `19ef4c6`; 결과: `codex/hmi-work-area-limits`에서 이 기록을 포함하는 커밋. 아래 시험은 커밋 전 작업 트리에서 수행했다.
- 수준: Python 단위·모의 HTTP·실제 Jazzy Action 송수신 / 로봇 비구동
- 환경: 현재 Linux PC, Python 3.12, ROS 2 Jazzy, backend/.venv, 임시 DB, LOCALHOST domain 174
- 공통 계약: GeneratePath v2 표준 취소 사용. c2_interfaces 변경 없음.
- 이전 전체면 HMI 표시 수정은 보존. c2_path의 기하 제한은 변경하지 않음.

| 시나리오 | 결과 |
| --- | --- |
| 비협조적 30초 계산 취소 | 5초 이내 자식 종료·회수, 잔여 자식/관리 산출물 없음, 반복 요청 가능 |
| 짧은 계산 기한 | TIMEOUT 반환, 자식 프로세스 종료·회수 |
| HTTP 생성·취소·취소 재전송 | CANCELING 후 FAILED/CANCELED, 경로 등록 없음, 다음 생성 성공 |
| 브라우저 재접속 데이터 | snapshot에 같은 요청 ID·진행/취소 상태 및 최종 결과 제공 |
| 중단 확인 응답 없음 | UNKNOWN 유지, 새로운 생성 409 BUSY |
| Goal 수락 전 취소 | handle 도착 후 취소 전달, 최종 CANCELED 수신 |
| 완료 이후 취소 | 이미 확정된 성공 결과 유지 |
| 실제 ROS 다량 획 최적화 취소 | OPTIMIZING_2D에서 취소, 5초 이내 CANCELED, path asset/path_versions 0건, 직선 재생성 성공 |
| 실제 ROS 서버 0.2초 제한 | TIMEOUT, 경로 ID·파일 등록 없음 |
| 기존 경로·파일 해시·실행 차단 | 기존 회귀 시험 통과 |

실행 검사:

- c2_interfaces + c2_path Jazzy colcon 빌드 성공 (`/tmp/c2-cancel-build`, `/tmp/c2-cancel-install`).
- c2_path unittest: 57개 통과.
- backend 선택 시험: 생성 취소, monitor, path_artifacts, file_integration, ros_path_integration, ros_contract. 최종 73개 통과(30.06초).
  중간 실행에서 Vite 빌드와 정적 파일 조회가 겹쳐 초기화 오류 2건이 발생했으며, 빌드 종료 후 전체 재실행에서 해소됐다.
- frontend: TypeScript 검사, 기존 preview 시험, Vite 빌드 통과.
- 로컬 공통: repository 검사, git hook 8개, issue manager 설정 검사 및 27개 시험, diff 공백 검사.

한계:
- 브라우저를 직접 조작한 시각 검증은 미수행. 새 연결이 사용할 HTTP snapshot으로 복원을 검증했다.
- 긴 계산 중단은 계산 프로세스에 적용한다. 마지막 산출물 저장이 이미 시작된 경우 정상 저장 결과를 유지한다.
- 중단 미확인 때는 운영자가 경로 노드와 모니터를 함께 재시작해야 한다. 자동 재시작·로봇 정지는 수행하지 않는다.
- 실기·전체면 변환·실측·공정 통합은 미검증. 빌드·통신 성공은 실기 승인 근거가 아니다.
- 적용 순서와 운영 방법: [사용 가이드](../HMI_GENERATION_CANCEL.md).
