# 노랑4점 challenge 단계별 입력 프롬프트

각 블록 전체를 다음 메시지로 입력한다. 현재 1단계를 완료했으므로 다음 입력은 **2단계**다. 실물 단계의 코드만 준비된 경우에는 실제 시험 결과를 같은 단계에 이어서 전달한다. 사용자가 다음 단계를 입력하기 전에는 다음 기능을 자동 실행하지 않는다.

## 0단계 — 범위·시나리오·증거·단계 프롬프트

```text
작업 폴더는 /home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge, 브랜치는 codex/integration-challenge입니다. 먼저 AGENTS.md, docs/D_YELLOW4_CHALLENGE_STAGES_20261014.md, robot_control_integration/settings/yellow4_challenge_20261014/scenario.json 및 최신 STATUS/변경 내용을 읽고 기존 작업을 보존하세요. 노랑 2x2x1 한 블록만 대상으로 하고 다른 팀원의 checkout, Round2 기본 step/Plan/B Current는 변경하지 마세요. 기존 교시·보정·제어 데이터를 먼저 재사용하고 합성값을 실측값으로 표시하지 마세요. 이번 단계만 구현·검증하고 코드 준비와 실물 검증을 별도 기록하세요. 관련 검사 후 scenario 진행 기록과 docs/STATUS.md를 갱신하고, 실제 완료된 경우 다음 단계의 프롬프트 전체를 복사 가능한 형태로 제공하세요. 실물 결과가 아직 없으면 PREPARED_FOR_FIELD_TEST로 기록하고 사용자가 실행할 명령과 확인 항목을 먼저 제공하세요.

0단계를 적용하세요. 독립 결착·분리 시나리오, 단계별 입력/출력/완료 기준, 각 단계용 프롬프트를 작성하세요. 기존 edge-first preview가 접촉축 회전을 계산하는지 확인하고 장치 연결 없이 관련 검사를 실행하세요. 실제 접촉/결착/분리 완료는 false로 남기세요. 1단계부터 자동으로 구현하지 말고 다음 프롬프트를 제공하세요.
```

## 1단계 — 결착·분리 공통 접촉축 기하와 preview

```text
작업 폴더는 /home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge, 브랜치는 codex/integration-challenge입니다. 먼저 AGENTS.md, docs/D_YELLOW4_CHALLENGE_STAGES_20261014.md, robot_control_integration/settings/yellow4_challenge_20261014/scenario.json 및 최신 STATUS/변경 내용을 읽고 기존 작업을 보존하세요. 노랑 2x2x1 한 블록만 대상으로 하고 다른 팀원의 checkout, Round2 기본 step/Plan/B Current는 변경하지 마세요. 기존 교시·보정·제어 데이터를 먼저 재사용하고 합성값을 실측값으로 표시하지 마세요. 이번 단계만 구현·검증하고 코드 준비와 실물 검증을 별도 기록하세요. 관련 검사 후 scenario 진행 기록과 docs/STATUS.md를 갱신하고, 실제 완료된 경우 다음 단계의 프롬프트 전체를 복사 가능한 형태로 제공하세요. 실물 결과가 아직 없으면 PREPARED_FOR_FIELD_TEST로 기록하고 사용자가 실행할 명령과 확인 항목을 먼저 제공하세요.

1단계: 기존 app/edge_first_seating.py를 기반으로 결착·분리의 공통 접촉축 기하를 구현하세요. TCP–블록 파지 관계와 프레임이 명시된 접촉축을 입력받고, XYZ 원호와 SO(3) 자세를 함께 계산하세요. 결착은 기울임→착좌, 분리는 착좌→부분 해제 기울임의 별도 preview로 제공하되 동일 실제 축을 가정하거나 기존 궤적을 무조건 역재생하지 마세요. 축/각도/간격을 설정으로 받고 현재 합성 예제를 보존하세요. 팝업 또는 저장 가능한 경로 그림으로 접촉축·블록·TCP 원호·stud 위치를 비교할 수 있게 하고 이 단계에는 장치 명령을 넣지 마세요. 임의 방향 축, 좌표 변환, 양쪽 회전 부호, 접촉점 유지, 공급 파지 관계 변경, 원본 불변 테스트를 실행하세요. 다음은 2단계입니다.
```

## 2단계 — 기존 좌표 연결·실측 관계·관측 팝업

```text
작업 폴더는 /home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge, 브랜치는 codex/integration-challenge입니다. 먼저 AGENTS.md, docs/D_YELLOW4_CHALLENGE_STAGES_20261014.md, robot_control_integration/settings/yellow4_challenge_20261014/scenario.json 및 최신 STATUS/변경 내용을 읽고 기존 작업을 보존하세요. 노랑 2x2x1 한 블록만 대상으로 하고 다른 팀원의 checkout, Round2 기본 step/Plan/B Current는 변경하지 마세요. 기존 교시·보정·제어 데이터를 먼저 재사용하고 합성값을 실측값으로 표시하지 마세요. 이번 단계만 구현·검증하고 코드 준비와 실물 검증을 별도 기록하세요. 관련 검사 후 scenario 진행 기록과 docs/STATUS.md를 갱신하고, 실제 완료된 경우 다음 단계의 프롬프트 전체를 복사 가능한 형태로 제공하세요. 실물 결과가 아직 없으면 PREPARED_FOR_FIELD_TEST로 기록하고 사용자가 실행할 명령과 확인 항목을 먼저 제공하세요.

2단계: 기존 공급판 교시·조립판 격자/층 보정·TCP/tool·카메라 자료를 읽어 노랑4점 challenge 입력에 연결하고 관측 팝업과 실측 캡처를 준비하세요. 좌표 기반 중심 파지에 OpenCV 보조 및 검출/미검출 기록을 유지하세요. 기본5mm 파지와 사람 직접 결착 보완15mm를 별도 모드로 구분하고, 선택한 파지의 착좌 TCP·TCP–블록 상대 변환·접촉축/회전 방향·판 고정 조건을 출처와 함께 확인하세요. 기본 로봇에 +10mm를 적용하지 마세요. 사용자 +10mm 시험값은 실측 검증으로 표시하지 마세요. 확인된 자료를 즉시 사용하고 미확인 항목만 read-only 캡처/사용자 시험 절차로 남기세요. 픽셀 yaw와 실제 평면 roll/pitch를 구분하고 팝업에는 기준/접촉축/예상 경로/실제값을 표시하세요. 로봇을 자동 이동하지 말고 먼저 기존 로그/카메라 관측과 입력 정합성을 검사하세요. 다음은 3단계입니다.
```

## 3단계 — 조립판 상공 무접촉 원호·회전 시험

```text
작업 폴더는 /home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge, 브랜치는 codex/integration-challenge입니다. 먼저 AGENTS.md, docs/D_YELLOW4_CHALLENGE_STAGES_20261014.md, robot_control_integration/settings/yellow4_challenge_20261014/scenario.json 및 최신 STATUS/변경 내용을 읽고 기존 작업을 보존하세요. 노랑 2x2x1 한 블록만 대상으로 하고 다른 팀원의 checkout, Round2 기본 step/Plan/B Current는 변경하지 마세요. 기존 교시·보정·제어 데이터를 먼저 재사용하고 합성값을 실측값으로 표시하지 마세요. 이번 단계만 구현·검증하고 코드 준비와 실물 검증을 별도 기록하세요. 관련 검사 후 scenario 진행 기록과 docs/STATUS.md를 갱신하고, 실제 완료된 경우 다음 단계의 프롬프트 전체를 복사 가능한 형태로 제공하세요. 실물 결과가 아직 없으면 PREPARED_FOR_FIELD_TEST로 기록하고 사용자가 실행할 명령과 확인 항목을 먼저 제공하세요.

3단계: 조립판 위의 간섭 없는 높이에서 무접촉 접촉축 회전 시험 코드를 준비하세요. 기본5mm 파지와 사람 결착 보완15mm를 구분하고, 2단계의 선택된 블록–TCP 관계와 축을 함께 상공으로 평행 이동하여, 계산된 XYZ 원호+자세를 기존 제어 backend로 수행하는 경로를 만드세요. 새 로봇 제어 노드를 중복 생성하지 마세요. 기존 경유지는 MoveL과 관측점으로 연결하고 속도는 기존 사용자 설정을 읽되 접촉 회전 조건으로 자동 전용하지 마세요. 팝업/ROS 처리가 멈추지 않도록 하고 command와 actual TCP, SO(3) 오차, gripper 폭, raw wrench를 저장하세요. H/J/K 자세 복귀만으로 원호 검증을 대신하지 마세요. 사용자 실행용 preview/실물 명령을 제공하고 실물 결과 확인 후에만 3단계를 완료하세요. 다음은 4단계입니다.
```

## 4단계 — 최초 stud 걸림·부분 회전 결착 시험

```text
작업 폴더는 /home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge, 브랜치는 codex/integration-challenge입니다. 먼저 AGENTS.md, docs/D_YELLOW4_CHALLENGE_STAGES_20261014.md, robot_control_integration/settings/yellow4_challenge_20261014/scenario.json 및 최신 STATUS/변경 내용을 읽고 기존 작업을 보존하세요. 노랑 2x2x1 한 블록만 대상으로 하고 다른 팀원의 checkout, Round2 기본 step/Plan/B Current는 변경하지 마세요. 기존 교시·보정·제어 데이터를 먼저 재사용하고 합성값을 실측값으로 표시하지 마세요. 이번 단계만 구현·검증하고 코드 준비와 실물 검증을 별도 기록하세요. 관련 검사 후 scenario 진행 기록과 docs/STATUS.md를 갱신하고, 실제 완료된 경우 다음 단계의 프롬프트 전체를 복사 가능한 형태로 제공하세요. 실물 결과가 아직 없으면 PREPARED_FOR_FIELD_TEST로 기록하고 사용자가 실행할 명령과 확인 항목을 먼저 제공하세요.

4단계: 최초 stud 걸림→짧은 부분 회전 결착 시험을 연결하세요. 실제 확인된 공급 파지부터 시작하고 목표 근처에서 정렬 후 의도적 roll/pitch 기울임→접촉→stud 걸림 관찰→부분 원호 회전을 수행하게 하세요. 의도적 기울임 구간에서 기존 자동 수평 복귀/XY 보정이 접촉축을 밀지 않게 하세요. 초기 걸림 판정은 팝업에서 작업자 관찰을 기록하고 영상/반력/모멘트/실제 자세로 검증하세요. 45N을 걸림 기준으로 사용하지 마세요. 접촉점 이동, 블록 미끄러짐, 아래 구조/판 들림을 따로 기록하고 실제 관측에 따라 고정 접촉선 가설을 수정하세요. 검증 전 완전 눕힘/개방을 자동 연결하지 마세요. 시험 중단 뒤 자동 개방/재시도 없이 상태를 보존하세요. 다음은 5단계입니다.
```

## 5단계 — 완전 회전 결착·개방·결과 검사

```text
작업 폴더는 /home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge, 브랜치는 codex/integration-challenge입니다. 먼저 AGENTS.md, docs/D_YELLOW4_CHALLENGE_STAGES_20261014.md, robot_control_integration/settings/yellow4_challenge_20261014/scenario.json 및 최신 STATUS/변경 내용을 읽고 기존 작업을 보존하세요. 노랑 2x2x1 한 블록만 대상으로 하고 다른 팀원의 checkout, Round2 기본 step/Plan/B Current는 변경하지 마세요. 기존 교시·보정·제어 데이터를 먼저 재사용하고 합성값을 실측값으로 표시하지 마세요. 이번 단계만 구현·검증하고 코드 준비와 실물 검증을 별도 기록하세요. 관련 검사 후 scenario 진행 기록과 docs/STATUS.md를 갱신하고, 실제 완료된 경우 다음 단계의 프롬프트 전체를 복사 가능한 형태로 제공하세요. 실물 결과가 아직 없으면 PREPARED_FOR_FIELD_TEST로 기록하고 사용자가 실행할 명령과 확인 항목을 먼저 제공하세요.

5단계: 4단계에서 검증한 접촉축/방향/구간을 사용하여 완전 회전 결착과 개방 후 검사를 연결하세요. 공급판 최초 파지→정렬→걸림→XYZ 원호 회전→착좌 관측→개방을 노랑 한 블록에 연결하고, 필요하면 실제 개방 XY/자세 유지→상승→빈 그리퍼 닫기→수직 누름을 선택적으로 연결하세요. 누름은 raw 합력45N에서 중단하는 위치 하강이며 일정45N 유지가 아닙니다. 자동 접촉/착좌 판정은 검증된 로그에서만 채택하고 미확인은 UNKNOWN으로 기록하세요. 완료 자세, 놓은 블록의 실제 기울기/위치, 개방 후 유지 여부와 영상으로 결과를 확인하세요. 미결착을 명령 완료로 성공 처리하지 말고 실제 시험 결과를 기록하세요. 다음은 6단계입니다.
```

## 6단계 — 결착 블록 재파지·부분 회전 분리

```text
작업 폴더는 /home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge, 브랜치는 codex/integration-challenge입니다. 먼저 AGENTS.md, docs/D_YELLOW4_CHALLENGE_STAGES_20261014.md, robot_control_integration/settings/yellow4_challenge_20261014/scenario.json 및 최신 STATUS/변경 내용을 읽고 기존 작업을 보존하세요. 노랑 2x2x1 한 블록만 대상으로 하고 다른 팀원의 checkout, Round2 기본 step/Plan/B Current는 변경하지 마세요. 기존 교시·보정·제어 데이터를 먼저 재사용하고 합성값을 실측값으로 표시하지 마세요. 이번 단계만 구현·검증하고 코드 준비와 실물 검증을 별도 기록하세요. 관련 검사 후 scenario 진행 기록과 docs/STATUS.md를 갱신하고, 실제 완료된 경우 다음 단계의 프롬프트 전체를 복사 가능한 형태로 제공하세요. 실물 결과가 아직 없으면 PREPARED_FOR_FIELD_TEST로 기록하고 사용자가 실행할 명령과 확인 항목을 먼저 제공하세요.

6단계: 조립판에 완전히 결착된 노랑4점 한 블록을 재파지하여 부분 회전으로 떼는 독립 시험을 준비하세요. 조립판 고정과 파지 접근/높이/폭을 현재 관측에서 확인하고 공급판 TCP를 그대로 복사하지 마세요. 선택한 접촉축을 지점으로 반대편 stud 결합부터 해제하는 XYZ+roll/pitch 원호를 시험하되 결착 경로의 단순 역재생으로 가정하지 마세요. 팝업에 한쪽 해제/남은 결합/전체 해제/판 들림/파지 미끄러짐을 구분해서 표시하고 wrench의 힘·모멘트와 영상·실제 TCP를 저장하세요. 힘 저하 하나만으로 전체 분리/상승을 허용하지 마세요. 처음에는 부분 분리까지 검증하며 실제 결과 확인 후 완료를 기록하세요. 다음은 7단계입니다.
```

## 7단계 — 완전 분리·회수·결착/분리 시나리오 연결

```text
작업 폴더는 /home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge, 브랜치는 codex/integration-challenge입니다. 먼저 AGENTS.md, docs/D_YELLOW4_CHALLENGE_STAGES_20261014.md, robot_control_integration/settings/yellow4_challenge_20261014/scenario.json 및 최신 STATUS/변경 내용을 읽고 기존 작업을 보존하세요. 노랑 2x2x1 한 블록만 대상으로 하고 다른 팀원의 checkout, Round2 기본 step/Plan/B Current는 변경하지 마세요. 기존 교시·보정·제어 데이터를 먼저 재사용하고 합성값을 실측값으로 표시하지 마세요. 이번 단계만 구현·검증하고 코드 준비와 실물 검증을 별도 기록하세요. 관련 검사 후 scenario 진행 기록과 docs/STATUS.md를 갱신하고, 실제 완료된 경우 다음 단계의 프롬프트 전체를 복사 가능한 형태로 제공하세요. 실물 결과가 아직 없으면 PREPARED_FOR_FIELD_TEST로 기록하고 사용자가 실행할 명령과 확인 항목을 먼저 제공하세요.

7단계: 6단계에서 확인한 부분 분리에 이어 남은 stud 결합 해제→수직 이탈→회수 위치 이동→개방과 검사를 연결하세요. 목표 한 블록만 제거되고 조립판/아래 구조가 유지되는지 확인하세요. ALL_STUDS_RELEASED는 검증된 관측으로 판정하며 잔여 결합 상태에서 전체 인양을 진행하지 마세요. 결착→개방 후 검사→재파지→회전 분리→회수→빈 목표 검사 시나리오를 독립 launcher와 팝업으로 연결하고 횟수는 설정으로 받으세요. 단계마다 결과·실제 접촉 데이터·오차를 남기고 STOP/미확정 응답을 자동 재실행하지 마세요. 관련 회귀와 사용자 실물 결과를 기록하고 성공한 조건/실패 조건/미검증 조건을 구분해 보고하세요. 일반 Round2 통합/다른 블록 확대는 이번 단계에 포함하지 마세요.
```
