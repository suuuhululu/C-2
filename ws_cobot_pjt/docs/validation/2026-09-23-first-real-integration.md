# 첫 REAL 통합 전 과정 완료 · 2026-09-23

- 작성: Codex가 공정/HMI 원장과 사용자 실기 보고로 정리. 현장 실행·육안 확인: 사용자. 동료 승인 미실시.
- 기준: main `8409fc6` + 담당자 PR #82의 병합 head `c64fc6d` 로컬 통합 + 이번 PR 수정.
- 시험 당시 미커밋 상태였다. 이 PR은 실행에 사용한 변경을 보존한다. 최종 커밋을 소급해 당시 커밋으로 표기하지 않는다.
- 장비: M0609, ROS 2 Jazzy, TCP GripperDA_v1, load ToolWeight_1, c2_base, schema_version=2. 철사 고정 드릴. 제어기 펌웨어/그리퍼 모델은 이 기록에서 별도 확인하지 않았다.
- 외부 드라이버 소스 확인 HEAD `4d5657f36a160eedb533ab1c975cd8a30c3e53b2`, 로컬 수정 있음. 설치 바이너리 전체 일치 검증 미수행.

| 시나리오 | 결과 | 근거 |
| --- | --- | --- |
| 윗면·옆면 8점 측정 및 BIND | 성공 | measurement.json, preparation.json |
| 이미지 기반 경로 생성 | 성공 | generation.json, path.json |
| PRECHECK·ENTRY·55구간 실행·FINISH | 성공 | execution-result.json, run.json, events.json |
| 실제 도면과 조각 형상 일치 | 미달/정량 평가 미수행 | 사용자 사진·육안 보고 |
| 반복성·비상정지·장애 주입 | 이번 사례에서 미수행 | 새 완료 주장 없음 |

[원본 결과·사진·샘플 실행법](../evidence/real_integration_20260923/README.md)

## 함께 수정한 코드

- 8점 측정값으로 seed·윗면 XY·실행 표면 초기값 갱신. 담당자 baseline/이동 복구/비접촉 힘 정책 통합.
- workcell_version을 경로 소비자 기준 1로 정렬. HMI 사전 식별 검사 공유 및 BIND 전 완성 프로파일 검증.
- ENTRY에 측정용 TCP 박스를 적용하던 문제 수정. 조각용 도구 끝 Z≥0.05 m, XY 경계/Z 상한 없음. 본경로·오프셋 적용 계획에도 검사.
- 측정용 trial_scene, 도구-양초 간격, IK·관절 검사와 그리퍼 금지 정책 유지. ROS Action/Service/Message 정의 변경 없음.
- 성공 원장과 사진을 단위시험 샘플로 제공. 형상 품질 합격으로 승격하지 않음.

## 검증과 배포

공정 비실기 시험+HMI 설정/스냅샷 시험 1139 passed, 2 skipped. ROS 서버 시험 3개 파일 제외.
backend 전체(작업영역 수정 전) 242 passed, 6 skipped. c2_path·c2_process Jazzy 빌드 성공.
추가 실기 샘플 검사는 별도 수행 결과를 PR에 기록한다.
실제 정지/품질을 모의시험 결과로 대체하지 않는다.

실행 중 배포하지 않는다. 대기·정지 상태에서 사용자가 HMI/공정 노드를 재기동한 후 새 측정·새 경로를 만든다.
문제가 있으면 이전 검토된 커밋/설정으로 되돌리되 새 측정과 미리보기 확인을 다시 수행한다. 기존 BIND 해시를 직접 고치지 않는다.
