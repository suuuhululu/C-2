# Round3 게시 스냅샷

이 소스는 2026-10-15 복원된 bundle 인계1288625239ecdf517ae1b78fa05226a9bd7f8a33 위에,
`PR55_round3_verified/runtime`의 서비스/그리퍼 변경과 PR55 B32157af를 모아 게시한 것이다.
인계 원본·기존 C-2-round3의 미커밋 변경·실행 runtime과 로컬 로그/비공개 환경은 그대로 보존했다.

GitHub round3 게시 전 확인 head는93ef967869065abb971e690aae44c3fe45e468bc다. 이 PC에는 Git 게시 인증이 없고
연결된 GitHub 앱도 tree 생성을403(Resource not accessible by integration)으로 거부했다. 원격 변경은 없었다.
이후 사용자가 이 PC에서suuuhululu의 GitHub HTTPS 인증을 완료했다. 두 브랜치를 같은 커밋으로 함께 게시한다. 로컬에서는 bundle의 원래
1288625 커밋을 그대로 부모로 보존하고 최신 변경을 추가한다. 따라서 인증 후 기존 round3 이력에 fast-forward
게시할 수 있다. round4는 로컬 최종 round3와 같은 커밋에서 복사한다. 원격 게시 성공과 로컬 준비를 구분한다.

## 현재 동작

빈 판 INITIAL→로그인/C 대화·미리보기·별도 승인→A 계획/재평가→D 단독 native 또는 실제 A 사람 인계 후보→
개방/HOME→실제 B STEP→별도 FINAL→사용자별 DB/웹 저장이다. 지원하지 않는 로봇 동작은 사람이 조립할 수 있도록
고정 place board에 놓고 HOME 복귀 후 HMI 완료·손 이탈을 확인한다. 손 제스처를 기다리는 경로는 아니다.
B 실패 체크박스는 원래 실패·Current/revision·미완료를 보존하며 B MATCH를 만들지 않는다.

| 항목 | 게시 값 |
|---|---|
| 공급/HOME 준비/전달판 개방 | 명령53mm, 실제40~80mm |
| 조립판 O/판 위 빈 패드 개방 | 명령47mm, 실제32~55mm |
| 빨강1×2의1점축 파지 | 명령20mm 닫힘, 실제10~40mm, grip 상태2 |
| I/P | I 반력50N/P 반력60N 정지, P 합력70N 이상 HOLD |
| 속도/가압 | 접촉3mm/s·일반 기존2배, 위치 하강+반력 STOP, compliance/desired_force 미사용 |

새 폭 설정은 모의 검증만 완료했다. 최근 실제 INITIAL 성공 후 인계50.3mm/과거 상한50mm 때문에 보류된
기록을 성공·현재 정지·연속 조립 완료로 바꾸지 않는다. HOME/STOP/writer 확인과 실패 후 보류는 유지한다.

## 환경과 실행

키·DSN·비밀번호·.env·가상환경·새 촬영/운영 로그·claim/cache 파일은 게시하지 않는다.
기존 tracked 모델/보정 근거는 삭제하지 않았다. 기존 PC의 ROS/Python 환경을 재사용할 때:

```bash
export C2_ROUND3_BASE_ROOT='/home/rokey/협동2/C-2-round3'
export C2_SERVICE_LOCAL_ENV='/home/rokey/협동2/PR55_round3_verified/runtime/.env.round3-service-local.bash'
bash scripts/round3_service.bash preview
```

preview는 장치 명령이 없다. HMI를 여는 것은 `bash scripts/round3_service.bash hmi`이며,
기존 HMI를 종료하고 현장 준비를 확인한 사용자가 시작한다. 새 빈 판 INITIAL은 실제 로봇 이동을 포함한다.
현재 제공된 실행 runtime은 계속 그 경로에서 사용할 수 있다. round4 브랜치 복사만으로 로봇 단독 실행 모드가 생기지 않는다.

다른 PC는 `C2_ROUND3_BASE_ROOT`를 로컬 Python/환경 파일을 준비한 디렉터리로 지정하고
`C2_ROUND3_ENV`, `C2_SERVICE_ENV`, `C2_SERVICE_LOCAL_ENV`로 비공개 파일 경로를 지정할 수 있다.
실제 실행 코드는 launcher의 checkout ROOT로 고정한다. C 모델3역할 기본값은gpt-6.1-sol이며 명시 환경값이 우선한다.
현재 서비스 C 대화는 텍스트 경로다. 음성/손 제스처가 연결됐다고 가정하지 않는다.

## 검증과 다음 작업

게시 복사본에서 service/HMI/launcher70 passed, native282 passed, B550 passed/외부 PR22 consumer1 skipped.
추가 launcher 기본 모델 수정 뒤 영향 검사7개도 통과했다. 세부 출력은
`docs/validation/round3_20261015/publish-*-tests.log`에 있다.
같은 파일의 앞선 그리퍼/범위 검사도 해당 디렉터리에 보존했으며 겹치는 테스트 수를 합산하지 않는다.
이번 게시에서는 실물 로봇/카메라/LLM API/새 실제 DB를 실행하지 않았다.

round4의 방향 정의·교시 행렬·비전 중심 결합·ABCD 변경/재사용 계획은
[round4 인계·설계](D_ROUND4_ROBOT_ONLY_HANDOFF_20261015.md)와
[새 채팅 프롬프트](ROUND4_NEW_CHAT_PROMPT.ko.txt)를 따른다. production 코드 변경은 새 채팅에서 단계별로 수행한다.
