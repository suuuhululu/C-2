# 모션 전 거절 요청의 정비 복구

일반 UNKNOWN 해제나 로봇 안전 래치 해제 기능이 아니다. 기존 Action/HTTP 계약은 변경하지 않는다.
`backend/app/recover_preparation.py`는 HMI가 종료된 상태에서 한 요청만 검사하는 정비 명령이다.

## 허용 조건

- 운영자가 로봇 정지·다른 작업 없음 확인.
- 지정 요청이 UNKNOWN이고 원본 해시·Goal 식별자가 일치.
- REAL MEASURE 결과가 FAILED/NOT_READY이며 원인이 정확히 `정지 래치 또는 로봇 제어권 미확인`.
- 접촉 없음·기하/등록 완료 아님·BIND 없음·홈/측정 단계 진입 이력 없음. 이 메시지는 현재 공정 preconditions의 모션 전 첫 가드에서 반환된다.
- 현재 공정 REAL/IDLE/실행 ID 없음. 제어기 GetRobotState=STANDBY, CheckMotion=IDLE, 반복 관절 관측 안정. 설정의 기존 안정 시간·관절 오차를 사용한다.
- 제어권 토픽의 실제 값과 수신/발행 시각이 유효. 구독 발견은 최대 5초 기다리되 신선도 조건은 완화하지 않는다.

HMI의 `.server.lock`을 획득하지 못하면 거절한다. 드라이버/공정 노드는 종료하지 않는다. 기존 조회 서비스만 사용하며 정지·이동·제어권 요청·래치 해제는 호출하지 않는다.

원본 Result의 stop_confirmed=false를 true로 바꾸지 않는다. 요청은 INVALIDATED/UNCONFIRMED로 전환하며 이전 레코드와 복구 관측을 불변 `preparation_recovery` 자산으로 보존한다. 새 요청에서 공정 사전검사를 다시 받아야 한다.

## 이번 적용 기록 · 2026-09-21

- 대상 요청: `9393191a-8724-4c53-b8e9-9407546eb888`.
- 최초 조회는 ROS 구독 발견 전에 끝나 복구를 거절했고 DB를 변경하지 않았다. 발견 대기를 추가한 뒤 같은 안전 조건으로 재검증했다.
- 복구 근거 자산: `7a6c6762-1a0f-442e-b835-d5daa231577a`.
- HMI만 정상 종료·동일 REAL 설정/domain 20으로 재기동. 드라이버·공정 유지, 실제 측정 요청 0건.
- 재기동 후 CONNECTED, 공정 IDLE, active_run=null, blocks_work=false, 이전 요청 INVALIDATED 확인.
- 단위검사 7개 통과: 원본 보존/감사 기록, 홈 단계·접촉·다른 오류·다른 ID·BIND·해시 불일치 거절.

실행은 정비 담당자가 기존 HMI DB와 대상 요청을 명시하고 사용자 정지 확인 후 수행한다. 운영 중 DB 직접 편집이나 새 DB로 바꿔 UNKNOWN을 회피하지 않는다.

```bash
# backend 디렉터리, Jazzy/드라이버 메시지/c2_interfaces source, HMI 종료 후
.venv/bin/python -m app.recover_preparation \
  --data-dir /기존/HMI/데이터 \
  --request-id 대상요청UUID \
  --operator-confirmed-stopped
```
