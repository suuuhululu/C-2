# Slack 공유용 문안 · 고정 드릴 변경

아래는 복사해서 보낼 문안이다. Slack에 직접 발송하지 않았다.

---

팀 공유드립니다. main 301ea6e(PR #21 병합) 기준으로 9/19 고정 드릴 운영 변경과 문서를 정리했습니다. 현재 작업 브랜치이며 동료 검토·PR 병합 후 main에 적용됩니다.

• 공정 모듈은 node / state_machine / preconditions / robot_adapter / engraving / tool_calibration의 6개로 정리했습니다. gripper_adapter·tool_sequence는 만들지 않고 cleaning은 기존 feat 브랜치에 예비 보관합니다. 어댑터 frame 변경은 PR #23, engraving 이관은 PR #25, 보정 소스는 PR #27이며 모두 미병합입니다. 이 코드를 이번 브랜치에 중복 복사하지 않았습니다.

• 철사 고정 중 그리퍼 열기(DO2·open·반 열기)는 초기화·종료·오류 복구·정지·보정에서도 금지합니다. 집기·반납·청소는 현재 공정에서 제외합니다. 닫힘 관측만으로 드릴 고정 장착을 판단하지 않습니다.

• ROS 5개 통신 이름과 필드 구성은 유지합니다. 다만 이전 집기/반납 실행 의미와 혼용하지 않도록 schema_version=2, c2_interfaces=0.2.0으로 변경했습니다. 실행 단계는 PRECHECK → TOOL_CHECK → APPROACH → ENGRAVE → RETRACT → FINISH입니다. 모든 담당자는 타입·송수신 코드를 같은 커밋으로 빌드/source해야 합니다.

• tool_id=engraving_drill, frame_id=c2_base, TCP=GripperDA_v1(그리퍼 끝점)입니다. 어댑터의 기본 frame 변경은 PR #23에서 반영합니다. 도구 끝 경로는 툴 −Y=표면 안쪽 법선, 툴 +Z=원통 축 아래 기준입니다. 한 획 180° 이내·이음매 금지·J6 왕복 원칙을 기록했고, 세부 IK/왕복 순서와 J6 한계·여유값은 좌표/공정 담당 합의가 필요합니다.

• 장착 3점 전체 보정은 경로 생성 전에 새 설정 스냅샷으로 확정합니다. TOOL_CHECK는 기존 보정의 1점 확인입니다. 확인 실패 시 실행 중 값을 덮어쓰지 않고 중단 → 필요 시 재보정·새 경로·미리보기 확인으로 돌아갑니다. ±1 mm는 아직 제안값입니다.

• 연결 전 PR #25의 SUPPORTED_SCHEMA=(1,)·clearance_mm를 v2·clearance_m 기준과 맞춰 주세요. PR #27은 보정 산출물의 장착/TCP/설정 식별·해시 연결과 REAL 프로파일, 확인 후 이탈 실패·취소의 결과 전파를 검토해야 합니다. 함수 호출 성공만으로 전체 공정 실행을 허용하지 않습니다.

• 받침대 50 mm 변경은 기록했지만 윗면 z≈234.4 mm는 재측정 전이라 실행 설정에 넣지 않았습니다. 9/18 측정 evidence는 보존했습니다. 세은 3개/시율 3개 모듈 분담은 최종 확인 전 제안으로 표시했습니다.

HMI는 새 흐름을 가짜 데이터로 확인하며 실기·실제 보정·J6 검증 완료를 뜻하지 않습니다. 기존 DB 기록은 유지하고 v1 경로의 새 실행은 차단합니다. 다른 docs도 점검해 현재 지침을 갱신하고 과거 설계·도면에는 보관 표시를 추가했습니다.

[변경 브랜치](https://github.com/suuuhululu/C-2/tree/codex/fixed-drill-contract)
[운영·전환 결정](https://github.com/suuuhululu/C-2/blob/codex/fixed-drill-contract/ws_cobot_pjt/docs/C2_FIXED_DRILL_20260919.md)
[문서 점검 목록](https://github.com/suuuhululu/C-2/blob/codex/fixed-drill-contract/ws_cobot_pjt/docs/DOCS_AUDIT_20260919.md)
