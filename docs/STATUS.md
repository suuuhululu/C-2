# 현재 진행 상황

## 2026-10-15 round3 게시·round4 분기 준비

- 사용자 요청으로 별도 게시 복사본에 bundle1288625 인계와 최신 verified/runtime을 합쳤다. 원본 작업본/실행 runtime의 파일·미커밋 상태는 보존했다. 로컬 env/키/DSN/운영 로그/claim/cache는 제외했다. 로컬 round4는 최종 round3와 같은 커밋에서 분기하며 로봇 단독 production 코드는 아직 바꾸지 않는다.
- 원격 확인 head93ef967이며 CLI 인증 부재/GitHub 앱403으로 원격 게시를 대기한다. 사용자가 이 PC의 Git 인증 준비 후 알리기로 했다. 원격 ref는 변경하지 않았다. 로컬 인계1288625를 부모로 보존한 최신 커밋/round4 복사본을 준비하며 인증 후 fast-forward 게시한다.
- 일반 Git checkout에서도 같은 진입점을 사용하도록3개 launcher의 환경 기준 위치를 보완했다. C2_ROUND3_BASE_ROOT/C2_SERVICE_LOCAL_ENV로 비공개 환경을 지정하고 실제 코드 ROOT/cwd는 checkout에 고정한다. 모델 기본값3역할gpt-6.1-sol을 보존한다.
- 게시 복사본에서 service/HMI/launcher70 passed, native282 passed, B550 passed/외부 PR22 consumer1 skipped이며 새 실물/실제DB/LLM API 호출은0이다. 마지막 기본 모델 변경 뒤 launcher7 passed로 재확인했다. 근거 docs/validation/round3_20261015, 실행 docs/D_ROUND3_PUBLISHED_RUNTIME_20261015.md.
- round4는 기존에 없는1/3점축·모든 파지90도·조립2×2/2×3목표0도와90도TCP 교시, 공급/조립 J6 분리, RGB-D 중앙값/블록 중심↔TCP 및 비누적 변환, 빨강0도=X2/Y1·90도=X1/Y2 새 의미와 과거 기록 호환, 지원 판정/단독 capability·자동 결착·실제 B STEP/FINAL·저장까지 검토한다. 상세 docs/D_ROUND4_ROBOT_ONLY_HANDOFF_20261015.md와 새 채팅 요청문을 준비했다.

## 2026-10-15 위치별 그리퍼 개방과 빨강 1점축 파지 범위

- 사용자 최신 요청으로 활성 runtime의 공급/HOME 준비 개방과 place board 전달 개방은53mm·실제 폭40~80mm, 조립판 O 및 조립판 위 가압 후 빈 패드 개방은47mm·32~55mm로 연결했다. 이미 열린 상태를 확인하는 구간은 해당 범위를 사용하며 불필요한 개방 명령을 추가하지 않았다. 빨강1×2의1점축 파지는 전체5슬롯에20mm 닫힘·실제 폭10~40mm를 적용했다. 파지 감지 상태2/기존 정지·장치·3표본 확인은 유지한다.
- 실제 Job69f17f49의 INITIAL은 성공했고 S01 파랑2×3 전달판 개방 명령47mm에 실제50.3mm였다. 공용 개방 함수는 설정 상한을110mm로 바꿔 통과시켰지만 새 인계 연결은44~50mm를 다시 검사해 HANDOVER_RELEASE_NOT_VERIFIED로 HOME 전에 보류했다. 공용 함수가 명시된 상한을 보존하도록 바꾸고 전달판 마지막 확인도 같은40~80mm 설정을 사용한다. 마지막 거부 시 실측 상태와 범위를 기록한다. 과거 실패 결과는 보존했다.
- 전달판 인계는 손 제스처 없이 HMI의 전달판 비움·손 이탈 확인→내려놓기/개방→상승/HOME→사람 조립 완료·손 이탈→실제 B 검사 순서다. 제스처 미감지에 따른 자동 대체 실행은 추가하지 않았다. 힘/속도/교시/공급 RGB-D 범위·B Current/revision/판정·자동 복구 정책은 변경하지 않았다.
- 검증: 기존 관련 native171 passed, 서비스/승인/HMI/5층129 passed·실제 DB 환경2 skipped. 추가 경계/표시 최종45 passed이며, 공용 함수의 미지정 legacy 범위 보존 후 영향 범위31 passed(슬롯/파지/전달),44 passed(bridge)를 재검사했다. 조립판 하한32mm 수정 뒤 seating61 passed다. 겹치는 검사는 합산하지 않는다. 25개 실제 파생 설정(빨강5개 포함), CLI preview/문법/배포 무결성을 확인했다. 근거는 상위evidence/gripper-context-policy에 보존했다. HISTORY_TEST_DSN 없는2건은 실제 DB 검증으로 표시하지 않는다.
- 전달판50.3mm와40/80mm 경계 허용,80.1mm는 후퇴/HOME 전에 보류, 조립판32/55mm 허용·31.9/55.1mm 차단, 빨강10/40mm 허용·범위 밖/NaN/파지 감지 없음 차단은 모의 피드백 검증이다. 에이전트 장치 연결/물리 명령0이며 새 설정의 실물 성공은 미확인이다. 기존 HMI를 닫고 새 작업으로 시작해야 변경된 코드/config 해시를 사용한다.

## 2026-10-15 로봇 단독 불가 Step의 place board 인계

- 사용자의 명시 지시로 A의 전체 계획에 HUMAN_ASSEMBLY를 허용했다. 기존 x축 native 단독 제약 때문에 90도2×3에서 NO_FEASIBLE_ORDER가 발생했으며, 실제 최신 Job e712bb15의 빈 판 INITIAL은 성공했다. C/A footprint와 지지는 일치했고, 해당90도 블록은 빈 주변에서도 x 파지 후보0/y 후보가 존재했다. 이 문제를 B 카메라 실패로 해석하지 않는다.
- 로봇 단독 범위는 기존 native ROBOT_GRIP/x/NONE이다. 다른 도움/전략이 필요하면 해당 Step을 actual A HUMAN_ASSEMBLY 재평가·전달판 motion으로 계산한다. ROBOT_GRIP 동작을 임의로 manual로 재표기하지 않는다. A의 기하적 PATH_BLOCKED/NO_FEASIBLE_METHOD/UNSUPPORTED_METHOD도 장치 명령 전에만 actual A manual 후보를 요청한다. 상태/상관 ID/Current/정지·설정 오류나 이미 시작한 로봇 실패는 인계로 우회하지 않는다.
- 기존 공급 RGB-D/교시/25슬롯 바인딩을 재사용해 집고, 기존 D runner의 공급 경유점·BODY_BYPASS·PLACE_BOARD·전달판 접근/개방/후퇴를 사용한다. 이미 집은 manual 블록 전용 handover-held 진입점을 제한적으로 추가했고 기존 assemble-held의 단독 로봇 제한은 유지했다. 전달판 route/높이는 actual A motion과 D profile을 대조하고 native force/compliance를 사용하지 않는다. 직접 조립 I50/P60·70N 보류/접촉3mm/s는 유지한다.
- HMI에서 전달판 비움/손 이탈 체크 → 최신 HOME 상태를 재조회해 A binding 재생성 → D 인계/47mm 개방·후퇴·HOME·정지/writer 해제 → 사람 조립 완료/손 이탈 체크 → 실제 B STEP 순서다. 두 체크는 매번 기본 해제다. 목표 좌표/층/방향과 필요한 아래 블록 지지를 표시한다. 사람 완료 신호는 B MATCH/Current 채택이 아니며 B 실패 후 작업자 시험 확인도 별도로 유지한다. 전부 실제 STEP MATCH인 경우 별도 FINAL을 수행하고 DB/웹에 실제 B 완료 여부를 반영한다.
- 실제 저장 승인 설계를 장치 없이 다시 계산해21블록/37블록 모두 A READY였다. 최초 A 선택은 각각 robot15/manual6, robot25/manual12다.21블록의 가상 상태·예상 prefix로 모든 Step의 D binding까지 계산하면 native5/manual16이다. 이 자료는 명시적 offline fixture이고 실제 B Current/실물 조립 성공이 아니다. 슬롯 재사용 전 REFILL 확인도 유지한다.
- 변경 후 새 서비스/HMI/실제 D runner 모의 인계37 passed, 관련 native280 passed, 실제 분리 _test DB/HTTP4 passed를 확인했다. 직접 조립/인계·사람 미확인·B 실패·STOP/HOME/writer 실패·잘못된 phase와 인계 후 실제 B/FINAL·개인 웹 완료 구분을 검사했다. 넓은 서비스/기존5층 회귀는83 passed/1 HMI fixture failed였고, 실제 STEP_READY에 있는 supply_slot을 fixture에도 보완한 뒤 HMI를 포함한 최종37개를 다시 통과했다. 문법/preview/체크박스 화면도 확인했다. 새 실물 인계/연속 조립 검증은 미실시이며 에이전트 장치 명령0이다.
- 근거 evidence/place-board-handover/, 운영 안내 ROUND3_SERVICE.ko.txt. 기존 전체 HMI를 닫고 scripts/round3_service.bash hmi로 새 작업을 연다. 음성 기능은 이번 인계 변경에 포함하지 않았다.

## 2026-10-15 C GPT-6.1 로컬 설정·첨부 키 파일 연결

- 사용자 요청으로 전체 통합 HMI의 로컬 환경에 OPENAI_MODEL/OPENAI_AUX_MODEL/OPENAI_JUDGE_MODEL=gpt-6.1-sol을 명시했다. 설계 생성·대화 해석·검토 모두 같은 모델을 사용한다. 실제 C 코드는 OPENAI_MODEL을 읽으므로 OPENAI_LLM_MODEL을 새로 만들지 않았다.
- 첨부한 외부 키 파일을 환경에서 읽어 OPENAI_LLM_API_KEY로 전달한다. 키 값은 소스/manifest/문서/로그로 복사하지 않았다. 로컬 환경 파일은 Git 제외·권한600이며 전체 HMI launcher가 읽는다. 기존 HMI는 종료/재실행해야 반영된다.
- shell 문법, 키 로드 여부, 세 환경변수와 mock HTTP 경계에서 실제 구성된 요청의 model=gpt-6.1-sol을 확인했다. 실제 API 호출/장치 명령0이며 인증·과금/응답 성공은 검증하지 않았다. 공식 모델 페이지 https://developers.openai.com/api/docs/models/gpt-6.1-sol 를 확인했다.

## 2026-10-15 빈 판 C·A·B·D·HMI·DB·웹 연결 / I50·P60·70N 보류

- 사용자의 최신 지시로 새 `scripts/round3_service.bash hmi` 진입점을 준비했다. 빈 판 INITIAL → 사용자 로그인/C 실제 설계 대화·미리보기·별도 승인 → 실제 A 전체 계획·매 Step 재평가/motion → 등록 native D 단발 → 빈 그리퍼 개방/HOME → 실제 B STEP → 별도 FINAL → 인증된 사용자 DB/웹 저장을 연결한다. HMI를 열기만 하면 장치 명령이 없다. 기존 고정5층/3-Step 시험과 구분하며 C 대체 Mock으로 REAL 실행하지 않는다. 실행 시 C API 키가 없으면 터미널에서 숨김 입력한다.
- A의 선택을 D의 실제 교시/슬롯/config 해시에 바인딩한다. 현 native 실행 지원은 ROBOT_GRIP/x·NONE 또는 단일 HOLD이며 다른 동작으로 바꿔 실행하지 않는다. 25개 등록 슬롯의 설정 binding을 장치 없이 확인했고 실물 성공/정밀도 증거는 아니다. 매 Step 시작 전 명시 확인, I/O/P/U와 지지 안내를 유지한다. 정상 native 종료 뒤 개방·HOME 후 B를 검사한다. 최초 집기 경유점과 교시·오프셋·그리퍼/RGB-D 원자료는 보존했다.
- 새 C 후보는 별도 미리보기 승인을 거치고 A가 남은 Step만 재계획한다. B 실패를 넘기는 체크박스는 매번 해제 상태다. B 판정·Current·revision과 원래 실패를 보존하며 작업자 계획 기준은 별도로 기록한다. 이 기준과 B Current가 다른 상태의 새 Plan은 B 계약상 보류될 수 있다. B 전체 STEP MATCH와 별도 FINAL MATCH 없이 완료 이벤트를 생성하지 않는다. 미확인 시험도 DB/개인 웹에 저장하되 완료로 표시하지 않는다. DB 성공 뒤 웹 실패는 저장 영수증을 재사용해 웹 확인만 재시도하며 로봇 동작을 반복하지 않는다.
- PR55 추가 검토 32157af433a6f3cd07e2a56b32a5867c6f0bd096의 B10파일과 INITIAL coverage 인계3파일을 이전 해시와 대조한 뒤 반영했다. INITIAL 미확인 최대60열·빈 공간0 Depth 결손 최대1% 기준이며 미확인 열은 빈칸으로 만들지 않고 해당 Plan/Step을 PLAN_REGION_UNVERIFIED로 차단한다. 새 B connection은 저장 실제3View verified_regions를 public INITIAL transaction으로 재채택해 제한을 보존한다. 작업자 빈 판 확인은 실제 B INITIAL 성공으로 바꾸지 않는다.
- 새 B의 동일 과거 빈 판 영상 재분석은 88→5 미확인열/2440→2855층칸으로 INITIAL OK였으나 신규 촬영/실물 PASS가 아니다. 이전8블록 영상은66 미확인열로 계속 UNOBSERVABLE다. B 검토 소스와 동일 해시/로그를 보존했다(B550 passed/1 외부 PR22 skipped, Docker550/1 skipped). 과거 촬영은 실행용으로 재사용하지 않는다.
- 추가했던 P 컴플라이언스/native desired-force 경로를 제거했다. 기존35N 접촉 실험은 보존한다. 최신 실행 설정은 I 반력 정지50N/P 반력 정지60N/P raw XYZ 합력70N 이상 오류·HOLD/접촉3mm/s, 일반 이동 기존2배, O47mm/피드백44~50mm다. 60N 일정 힘 유지나70N 실제 상한을 보장하는 제어가 아니며 조회/STOP 지연으로 힘이 더 올라갈 수 있다. 한계 초과·STOP/HOME/writer/로봇 오류의 자동 해제·상승·복귀·재실행은 없다.
- HMI의 '이번 단계 예상 구조'가 직전 B 결과에 머물던 오류를 수정했다. 현재 Step까지 계획 prefix를 독립 표시하고 계획 기준임을 명시한다. B Current가 비어 있어도 예상 구조를 갱신하며 Current를 채우지 않는다. 실행 중 변경 감지 검사는 유지하므로 새 코드 적용 뒤 기존 HMI를 완전히 닫고 새 시험본을 사용한다. 사용자가 실행 중 적용 연기를 요청한 동안 공유 제어/B 소스를 보존했고, 해당 실행이 HOLD/종료된 뒤 반영했다.
- 현장 최신 9c08d518 시험은 P3mm/s/60N 기준에서 최초 표본69.626N, 정지 후 상승 직전 약97.53N이었다. 컨트롤러9015 External_Force는98.558N>global-normal96N을 기록했고 LIFT move_line이 실패했다. 후속 move_stop도 실패해 실제 정지는 미확인이다. 카메라나 native 힘 제어의 실패로 해석하지 않는다. 이후70N 오류/HOLD 설정으로 바꿨으며 새 물리 검증은 시행하지 않았다. TP 현재 보호/정지 상태와 수동 복구는 현장에서 확인한다.
- 변경 후 검증: 관련 native284 passed, 전체 round3 통합181 passed/4 DB 환경 skipped, 새 서비스/C·A 재계획/HMI 별도24 passed, 실제 분리 _test PostgreSQL+웹25 passed(실제 서비스 생성 이력의 B 완료/수동 확인 구분 포함). HMI 예상2단계/Current 불변 스크린샷·문법·preview도 확인했다. 실 C API/신규 INITIAL/연속 실물/FINAL은 미검증이며 에이전트 장치 명령0이다. 근거 `evidence/no-compliance-service-integration/`, 안내 `ROUND3_SERVICE.ko.txt`, 최신 무결성은 배포 manifest/verify.py다.

## 2026-10-15 PR55 ROI 추가 통합·5층 P 목표65N / 합력 차단100N

- PR55 `791369f83f518f5b3d0e9664219b06636e27994a`의 B 변경9파일을 검토본 해시와 대조한 뒤 현재 runtime에만 반영했다. V0/D1/D3별 ROI 로드·crop 추론/원본 mask 복원·ROI 밖 제외/경계 UNKNOWN·상부 빈 공간 증거 변경이다. 기존 공급 깊이 처리 지연 수정·교시·설정·실행 로그는 보존했다. 기존 C-2-round3 checkout은 이번 작업에서 수정하지 않았다.
- 5층 시험의 P만 기존 위치 하강/반력 정지에서 ABS native 힘 제어 목표65N·raw XYZ 합력 차단100N으로 분리했다. I45N·일반 이동2배·접촉 접근12mm/s·O47mm/피드백44~50mm·공급 RGB-D 허용값은 유지했다. 기존 contact runner의 강성·전환0.2초·유지3초·3mm 힘 제어 구간을 재사용하며, 시작점부터 총12mm 한도다. 기존35N 정렬/검색 시험과 C 승인3-Step의 가압 설정은 변경하지 않았다.
- P 정상 종료에는 힘 해제·STOP·컴플라이언스 해제 ACK/정지 확인이 필요하다. 정확히65N 도달했다는 별도 완료 인증은 추가하지 않았다. 100N은 PC 조회 중단 기준이며 실제 힘 상한/컨트롤러 보호 해제를 뜻하지 않는다. P 오류 후 자동 상승/HOME·재실행·오류 리셋은 없다. HMI/preview에65N 목표와100N 차단을 구분해 표시하고 source freeze에 해당 D/B 코드와 ROI3개를 포함했다.
- 장치 없는 검증: B534 passed/1 외부 PR22 Consumer skipped, native 제어313 passed. HMI·INITIAL/STEP/FINAL·승인·5층·wrapper 검증 결과는 `evidence/roi-force-65-amendment/integration-tests.log`에 기록했다. Fake-transport contact CLI 테스트의 lock은 테스트 폴더로 격리해 실제 writer와 충돌하지 않게 했다. 에이전트의 물리 명령0이다.
- 담당 검토의 과거 실제 INITIAL 영상 재분석은 이전4개/1910셀에서 최신5개/1796셀로 바뀌었으나 둘 다 UNOBSERVABLE/initial_scope_unverified다. 정답 라벨이 없어 인식 정확도 개선·악화를 단정하지 않는다. ROI 파일 로드 성공을 INITIAL 성공으로 취급하지 않는다.
- 현장 후속 실패 `f361ad59-033e-4e9f-9d3d-d7bba98456b5`: P 접근 완료 시 Fz39.03N, compliance ACK 직전 컨트롤러3501(`RC_ERROR_SYSTEM_EXTERNER_JOINT_VALUE`), 이후1903 `MOTION_HOLD rejected eConfigDesiredForce`가 기록됐다.65N 명령의3초 응답 시간 초과로 HOLD했고,65N 유지/상승/HOME 성공은 확인되지 않았다. cleanup STOP/force release/compliance release ACK는 있으나 명령 상태가 불확실해 stopped=null을 유지했다. 실제 정지·현장 오류 해제는 별도 확인 대상이다. 이 경로가 다시 발생하면 힘 명령 전에 상태를 조회해 오류를 기록하도록 보완했으며, 시간 초과를 늘리거나 자동 재전송하지 않는다.
- 다음 현장 확인: 펜던트3501 원인/제어 가능 상태 확인 → 새 HMI/새 시험본 → 첫 층 P의 실제65N 응답·100N guard·힘 해제·상승/HOME 확인.5층 실물 성공/실제 B MATCH/별도 FINAL은 미완료다.

## 2026-10-15 사용자 우선 수정: 공통 수평10mm·P 가압70N

- 실행 Job `54932678-de97-4ae5-8adc-7b2e942ab26f`는 T2 CYCLE_COMPLETED/released/press_done 후 빈 그리퍼 개방·실제 HOME 도착/정지 영수증을 남겼다. 두 번째 T1 노랑2×2 슬롯4 공급 관측에서 deltaXYZ=[4.408816,-5.408747,5.936021]mm·수평6.978mm>5mm로 집기 전에 중단했다. 높이는7mm 이내였다. 서비스 최종 STOP/HOME=false는 전체 실패 결과로 보존하며 앞선 T2 HOME 영수증과 구분한다. 후속 실제 읽기 CheckMotion0/success=true다.
- 사용자의 명시 지시로 RGB-D20슬롯 전체 수평거리10mm, T1/T2/T3 모두 P 가압 반력 정지70N으로 변경했다. I는T2 55N/나머지45N, 가압12mm/s·최대12mm·그 외 깊이/높이/편차·일반 속도/그리퍼·기존 정지 검사를 유지한다. 선택은 `execution-t2-x1p5-fast2-xy10-20261015`이며 `xy5`는 수평5mm 복구용 설정만 선택한다. 과거 세트와 원본은 보존했다.70N은 일정 힘 명령이나 완전 결착 보장이 아니다.
- 정지 상태에서 RGB-D20장을 읽기 저장했다(`t1-stop-review-54932678`). 관측 자세 차0.013923mm/0.000050도·촬영 전후 자세 동일이다. 실제 패킷 재생에서 수평5mm는0/20 통과, 수평10mm는18/20 통과했다. 나머지2장은 높이7.935~7.936mm>기존7mm라 계속 거부되며 높이 기준을 추가 완화하지 않았다.18개 허용 표본 수평6.880~7.458mm, 중앙 deltaXYZ=[4.354968,-5.724334,5.948575]mm다. 기준점 채택/교시 변경·물리 명령0이다.
- 관련 native224 passed(1.89초), 서비스/HMI/승인·별도 DB/웹43 passed(22.16초), 합계267 passed/skip0이다. 두 가압 기준56.25/70의 미도달/정지·I55 유지, 현재 전체 세트 해시와3개 무장치 preview를 확인했다. 근거 `xy10-p70-native-tests.log`, `xy10-p70-service-tests.log`, `xy10-p70-validation.json`이다. 새10mm/P70 실물 재시험은 하지 않았다. 사용자 요청을 우선해 B 별도 통합본은 현재 HMI에 적용하지 않았다. 새3-Step HMI는 사전8블록·공급·빈 HOME을 준비한 새 시험에서 실행하며 완료된 T2를 현재 배치에서 반복하지 않는다.

## 2026-10-15 3-Step 개별 실물 시험 HMI · 판+X1.5mm · 일반 이동2배

- 사용자가 대상을 T2 파랑2×3 슬롯3으로 정정하고, 공급 집기가 아닌 조립판 결착 위치를 판+X로1.5mm만 이동하도록 최종 지정했다. 채택된 `operator_assembly_board_by_studs.json`의2×3/0도 X축 수평 방향으로 변환해 Base deltaXY=[1.4999937915852044,-0.004315692973631374]mm를 T2 착지·가압 기준에 한 번 적용한다. 기존 `retarget_assembly_reference`로 패드 관계를 유지하고 원본 교시/공급RGB-D/집기Z·회전은 보존했다. 반복 prepare가 누적되지 않음을 검사했다.
- 일반 직선 이동만2배로 선택했다. 상승/일반 하강12→24mm/s, 운반120→240mm/s이며 결착I/가압P는12mm/s, 가속도/각속도/힘·그리퍼는 유지한다. 앞서 선택한 공통 깊이518~542mm·수평5mm·높이 최소5mm(기존7mm 유지)·깊이편차4mm도 유지한다. 새 전체 세트 `reports/restore-20261015/execution-t2-x1p5-fast2-xy5-20261015`와 T2 XY1 선택용 짝을 만들고 최종XY5를 선택했다. 원본·이전 세트는 보존한다.
- `--round3-camera-free-trial --round3-three-step-trial`은 C 별도 승인과 실제 A 전체 순서T2→T1→T3를 세 native 설정/해시에 묶는 제한된 실물 시험이다. 각 Step 전 실물 팝업 ENTER 확인, T3 별도 지지 준비/해제 확인을 받는다. 정상 CYCLE_COMPLETED/released/press_done 뒤 실제 빈 닫힌 패드(폭≤12mm·상태2·정지) 확인→기존 개방 피드백 확인→기존 InspectionMotion의 검토된 HOME/FK/3표본 도착 확인을 사용한다. 각 Step 후 HOME이며 다음 실행은 별도 확인을 기다린다. 실패/취소/HOME 미확인 시 다음 Step/자동 복구·반복은 없다. HOME 관절 속도는 기존 값을 유지했다.
- B Current·revision·완료는 변경하지 않는다. HMI의 D 시험 실행 수와 시험 예상 배치를 B 확인0/3과 구분하며, 정상3개 종료도 HOLD/B 확인 필요로 남긴다. 첫 A Step 상세 승인 계약과 전체 A 순서/native 매핑을 검사하는 시험이며 후속 실제 B STEP/FINAL·각 Step 최신 B Current 기반 재계획 연결 완료를 의미하지 않는다. DB/웹은 미확인 시험 이력으로 기록한다. 사용자의 최신 지시로 B/PR55 별도 연결은 뒤로 미룬다.
- 최종 native 관련221 passed(1.79초), C/A 승인·HMI/프로세스·중단·실제 별도 시험 DB/HTTP 관련43 passed(21.64초), 합계264 passed/skip0이다. 두 세트의25슬롯 binding/전체 해시·각3개 무장치 preview·기존 설정 대조·문법/공백 검사를 확인했다. 세 native 전체 해시 변경/순서 변조·취소·HOME 누락 거부, 표시용 예상 배치의 Current 불변을 검사했다. 근거 `three-step-native-tests.log`, `three-step-service-tests.log`, `three-step-configuration-validation.json`이다. 새 오프셋·속도·3-Step 개방/HOME의 실물 검증은 하지 않았으며 에이전트 물리 명령0이다.
- `sixpart.bash hmi`는 이제3-Step HMI, `hmi1`은 기존 단발 HMI다. 기존 창을 종료하고 이미 추가된 블록을 제거해 사전8블록/공급 세 슬롯·빈 HOME을 준비한 새 시험에서만 실행한다. HMI 실행 자체는 C 승인이 아니며, 승인 뒤에도 각 실물 Step 팝업 확인을 받는다.

## 2026-10-15 RGB-D 20슬롯 공통 깊이518~542mm · 수평/높이 최소5mm · 편차4mm

- 사용자가 T2 외 슬롯도 깊이 범위를 넓혀 통일하고 다른 허용값도 조정하도록 요청한 뒤, 수평·높이 최소5mm와 깊이 편차4mm를 명시 선택했다. 기존 슬롯별 깊이는520~539mm에 걸쳐 있어 모든 현재 범위를 포함하는 공통518~542mm로 정했다. 앞선 T2 전용518~527mm 설정을 보존하고 새 전체 세트 `reports/restore-20261015/execution-all-depth518-542-xy5-20261015`를 선택했다. 실제 적용은 새 HMI·새 C 승인부터다.
- RGBD_XY 20슬롯의 `depth_range_mm=[518,542]`, `max_shift_mm=5`, `max_height_error_mm=max(기존값,5)`, `max_depth_spread_mm=4`를 적용했다. T1 노랑2×2 슬롯4의 기존 높이7mm는 유지한다. 수평은 전체 XY 거리이며 깊이 편차는 블록 내부3×3 패치의 최대−최소다. 기준 표면·교시·집기Z/회전·영상 시각310ms/동기50ms 등 기존값·힘·속도·그리퍼·조립판 보정 정책은 바꾸지 않았다. 넓은 깊이 범위 안에서도 별도 변위·블록 내부 패치 검사를 유지한다.
- TEACHING_ONLY 5슬롯은 깊이 보정을 쓰지 않으므로 모드/교시를 유지하고 허용값을 새로 만들지 않았다. 25개 슬롯 모두 조건부 실행 대상이라는 계약을 유지한다. `xy1` 선택용 짝 세트도 만들었으며 이 명령은 T2 수평만1mm로 되돌리고 다른 슬롯과 새 공통 깊이/높이/편차는 유지한다. 두 선택을 실제 파일로 확인한 뒤 최종 `xy5`를 선택했다. 원본과 이전 세트·시험 로그는 보존했다.
- 최종 설정 후 depth/profile 관련78 passed(0.45초), 두 세트의 각25개 실제 설정 binding·전체 출처/산출물 해시, 각3개 native 무장치 preview를 확인했다. 슬롯별 합성 경계는 각 세트260개(합계520개): 깊이518/542 허용·517/543 거부, 패치 편차4 허용·5 거부, 해당 수평/높이 경계 허용·0.001mm 초과 차단을 확인했다. 경계별 기준점을 구성한 합성 검사이며 실제 카메라 측정이나 실물 성능 검증이 아니다. 다른 native 설정은 경로/registry 해시 외에 동일하고 원본 교시·집기Z가 유지된다. 근거 `all-tolerances-spread4-tests.log`, `all-tolerances-spread4-validation.json`, 새 세트의 `validation.json`이다.
- 이번 작업의 실제 로봇/그리퍼/STOP 명령0이며 새 허용값의 실물 시험·B Current/완료 갱신은 하지 않았다. T2 단발 후 HOLD와 실제 B 확인 요구, 남은 Step binding 미완성 범위는 그대로다.

## 2026-10-15 T2 슬롯3 원시 깊이 허용 범위518~527mm

- 최신 사용자 실행 Job `a0214308-0840-4e51-b8c3-19e8c06251a1`의 승인 문서/native 설정에 I55N·P56.25N·O47mm/실폭44~50mm가 적용된 것을 확인했다. 공급 관측의 블록 내부3×3 깊이가 모두520mm로 기존521~527mm를 벗어나 `SUPPLY_DEPTH_SURFACE_UNAVAILABLE`로 중단했다. 영상98.369322ms/skew0·중심 인식 성공이며 집기 하강/파지 전이다. 새 반력 기준의 실물 적용 성공이나 B Current/완료로 해석하지 않는다.
- 사용자의 명시적 요청으로 T2 파랑2×3 슬롯3만 원시 깊이 하한521→518mm로 변경했다. 새 전체 세트 `reports/restore-20261015/execution-t2-xy5-height5-depth518-20261015`를 선택하고 수평1mm 선택용 짝 세트도 같은 깊이 범위로 만들었다. 원본/기존 설정·기록을 보존했으며 registry의 해당 depth 해시와 변경 근거를 갱신했다. 수평거리5mm·높이차5mm·깊이편차2mm·310ms/50ms·기준점/교시/집기Z·I55/P56.25/O47과 다른 슬롯을 유지했다. 깊이 범위 통과 뒤에도 별도 수평/높이 검사를 거친다.
- 관련 depth/profile 검사78 passed(0.43초), 두 세트의 각3개 native preview(장치 연결/물리 명령0), 25슬롯의 출처/산출물 해시·설정 비교를 확인했다. 모의 범위 경계518/527mm 허용·517/528mm 거부 및520mm 허용을 확인했고, 다른 native 설정은 세트 경로/registry 해시 외에 동일하다. `xy1`/`xy5` 선택을 확인한 뒤 최종XY5로 선택했다. 근거는 `depth518-tests.log`, `depth518-validation.json`, 각 세트의 `validation.json`이다. 새 깊이 범위의 실물 재시험은 하지 않았다.
- 추가 읽기 전용 촬영은 `ROBOT_NOT_STOPPED`로 영상 수집 전에 중단됐다. 후속 별도 읽기의 CheckMotion0/success=true와 구분해 기록하며 실패 실행의 STOP 영수증이나 HOME 확인으로 대체하지 않는다. 이번 작업의 팔/그리퍼/STOP 쓰기0이다. 다음 새 HMI·새 승인부터 적용하며 자동 HOME/재시도/Current 변경은 없다.

## 2026-10-15 T2 I 하강55N · P 가압56.25N 분리와 웹 재기동

- 사용자 화면의 `APPROVED_STEP_EXECUTED_B_CONFIRMATION_REQUIRED`는 B 제외 단발 실행을 마친 뒤 실제 B 확인을 기다리는 의도된 HOLD다. 최신 Job `f5d27562-038c-4dd8-a015-6e1f4d652348`/native `1792050815862668885`는 T2 `FIXED_STEP_EXECUTED`·CYCLE_COMPLETED/released/press_done=true·binding 일치다. 실제 O 명령47mm/폭48.4mm로 새44~50mm 조건이 통과했다. I는 기존45N에서 `FORCE_STOPPED_BEFORE_VERIFIED_SEATING`, P는 합력45.069858N에서 STOP ACK/정지를 확인했다. P 시작Z66.128494/12mm 하강 한도Z54.128494 대비 정지Z54.136219mm로 한도 끝 부근이다. 이 결과를 완전 결착/B Current/FINAL 완료로 표시하지 않는다.
- 사용자가 P 가압 기준25% 증가와 하강 반력55N을 명시 요청했다. T2만 `seating_force_stop_n=55`(I), `press_force_stop_n=56.25`(45×1.25, P)를 연결했다. 기존 공용 공급 기준 `force_stop_n=45`는 그대로 두어 공급부45N/그리퍼40N 검사를 완화하지 않았다. T1/T3는 I/P45N을 유지한다. O47mm/실폭44~50mm·집기/교시/수평5mm·속도·P 하강12mm/12mm/s·상승·정지/장치 검사는 유지했다.
- P는 정하중 명령이 아닌 위치 하강 중 raw 합력으로 정지하는 기존 방식이다.56.25N은 정지 기준이며 실제 가압력이 정확히25% 증가한다는 보장은 없다.12mm 한도가 먼저 오면 기존 `MAX_TRAVEL_REACHED_WITHOUT_FORCE_THRESHOLD`로 보고하며 거리 확대나 자동 추가 가압을 하지 않는다. 새 승인 문서의 D profile/현장 설정도 I55/P56.25를 기록하고 native config 해시로 검증한다. 기존 HMI·승인/실행 ID를 재사용하지 않으며 같은 T2가 남은 현재 배치에서 재실행하지 않는다.
- 관련 native114 passed(1.53초), 실제 DB/로컬 HTTP와 명시적 가짜 D의 승인·해시/저장 통합26 passed(19.66초), 합계140 passed/skip0다. 새 native3개 preview/AST/공백 검사를 확인했다. T2 설정에서 두 개의 단계별 반력 필드 외의 값이 이전47mm 설정과 동일하고 T1/T3는 동일함을 대조했다. 모의 가압50N의 한도 종료·57N의56.25N 정지와 I55N 정지, 기존45N 경로를 검사했다. 실물 새 I55/P56.25는 아직 시행하지 않았고 에이전트 로봇/그리퍼/STOP 쓰기0이다. 근거 `press56-tests.log`, `press56-approved-step-tests.log`, `press56-validation.json`.
- 화면의 시험 이력 재시도 ConnectionRefusedError는 로컬8767 웹이 종료된 별도 문제였다. 포트 미청취(errno111)를 확인하고 기존 웹만127.0.0.1:8767에 재기동했다. 카메라/로봇/DB 재기동 없이 최신 Job의 해당 계정 웹 조회를 실제 확인했고 assembly=NOT_RECORDED/storage=PENDING이다. HMI의 시험 이력 반영 재시도는 웹 조회만 하며 물리 동작을 반복하지 않는다.

## 2026-10-15 6부분 시험 첫 T2 native 완료 확인 · O 개방47mm/실폭44~50mm 수정

- 사용자 완료 보고 후 Job `c301edec-880a-4d4f-992d-89f45fcd1f44`, execution `0cdf37c2-77f9-4461-bd24-d0c6d4fa6586`, native `1792049805614665684` 원본을 확인했다. C 별도 APPROVE→실제 A 첫 S01/T2→파랑2×3 슬롯3 RGB-D 보정[-0.091731,-4.634372]mm→파지/이송→native I/O/P/U로 `CYCLE_COMPLETED`, released/press_done=true, `FIXED_STEP_EXECUTED`/종료0·service binding 일치다. 조립판 위 상승 후 HOLD이며 전체 조립/B 확인 완료로 승격하지 않는다.
- native 압력 단계의 STOP ACK/정지 확인은 true다. 서비스 최종 `actual_stop_verified=false`는 별도 최종 STOP 영수증 미연결 상태로 보존했다. 후속 실제 읽기는 robot_state1/CheckMotion0·관절[9.694836,21.113264,64.584244,0.308492,94.620430,11.860610]/모두success=true이며 HOME은 아니다. 에이전트 이동/그리퍼/STOP 쓰기0이다.
- 해당 제작자 계정으로 로컬 웹 로그인·Job summary 조회를 실제 수행해 DB/웹 시험 이력 접근과 설계1개를 확인했다. assembly=NOT_RECORDED/storage=PENDING으로 정식 FINAL 저장이 아닌 미확인 시험 이력이다. B Current/completed 갱신·별도 FINAL·T1/T3 실물 실행은 하지 않았다. 근거는 `reports/restore-20261015/sixpart-first-native-completed.json`이다.
- 사용자가 O 개방값48mm 이하 누락을 지적했고 최신 지시로 명령47mm/실제 폭44~50mm를 지정했다. 완료된 원본 실행의 O는 공용 `open_mm=60`을 사용했고 실제61.2mm였다. CAD 참조의 release48은 native 설정에 전달되지 않아 적용되지 않았다. 원본 실행/교시/프로파일·로그는 바꾸지 않았다.
- native `round2_three_step_trial.prepare`의 T1/T2/T3 설정에 O 전용 `release_width_mm=47`/`release_feedback_range_mm=[44,50]`를 연결했다. `held_xy_seating_trial.release`는 이 전용 설정을 검증해47mm를 명령하고 실제44~50mm·정지·gripper_status0의 안정3표본 뒤에만 반환한다. 상한50mm 초과는 STOP/오류로 후속 상승·4mm 빈 패드 닫기·P를 차단하며 자동 재닫기를 하지 않는다. 44mm 미만은 기존10초 확인 창에서 성공 처리하지 않으며 시간 초과 시 STOP한다. 기존 장치/힘/시각 guard와 공급/HOME `open_mm=60`을 보존했고 전용 필드 없는 과거 관측 시험의 동작은 유지했다.
- 새 승인 문서의 frame/D profile에도 실제 native의47mm/44~50mm를 반영해 기존 참고48mm와 실행 값의 차이를 제거했다. config 해시가 바뀌므로 이전 HMI/승인 문서/실행 ID를 재사용하지 않는다. 같은 현재 배치에서 완료된 T2를 다시 실행하지 않는다.
- O 실제 키 경로의 정상47mm·이상61.2mm 모의, 경계44/50mm 허용·43.9/50.1mm 거부, 잘못된 설정 무명령, 기존 공급 열림/동작 보존을 포함한 관련 native111 passed(1.39초)다. 새 native3개 preview는 장치0이며 이전 설정과 차이가 O 전용 두 필드뿐임을 확인했다. 실제 DB/HTTP와 명시적 가짜 D의 승인 문서/해시/정지/이력·웹 통합26 passed(19.30초), 합계137 passed/skip0이며 AST/공백 검사도 통과했다. 실제47mm O 재시험/완전 결착·B 비교는 아직 미검증이다.

## 2026-10-15 T2 정지 관측·누적 보정 점검 · 사용자 요청 수평5mm/복구 선택

- 사용자가 두 번째 HOLD 뒤 로봇을 움직이지 않는 관측 진단을 요청했다. 기존 `capture_supply_depth_reference.Reader`의 네 읽기 서비스만 사용해 T2 관측 위치에서 RGB/정렬Depth/CameraInfo20장을 저장했다. 관측 자세 차이0.024323mm/0.000041°·촬영 전후 TCP 차이0이며 TCP/Tool은 GripperDA_v4/ToolWeight0다. 실제 이동/STOP/그리퍼 명령·카메라 재시작0이다.
- 20/20장 인식·유효 깊이 성공, 수평 차이4.497567~4.591519mm/중앙 deltaXYZ[-0.110961,-4.537888,+1.849629]mm다. 중앙 대비 수평 변동 최대0.059194mm·깊이522~523mm·기존 깊이/편차 검사 통과다. 원래 짝 기준과 영상 중심이 대략v+7.968px 차이이며 카메라 K/D/크기/frame과 저장된 TCP-camera 행렬은 동일하다. 실제 장착/블록·판 위치가 그대로인지는 독립 확인하지 않아 특정 물리 원인이나 실측 정확도를 단정하지 않는다. T1/T3 한 장의 참고 비교도 차이가 있었지만 해당 기준을 채택하거나 다른 슬롯을 변경하지 않았다.
- 사용자가 블록 재배치 가능성과 보정 누적을 점검하고 수평 허용값5mm 시험 및 문제 시 복구를 요청했다. bind/execute의 deepcopy, rgbd_target의 새 vector, center_target의 교시 복사/보정 후보 직접 반환을 확인했다. 매 목표는 원래 교시+(이번 관측 표면−고정 기준)이며 이전 delta를 누적하거나 교시/프로파일에 저장하지 않는다. 반복 동일/이동/원점 복귀/역방향5mm 관측에서도 같은 절대 목표와 원본 불변을 새 회귀로 확인했다.
- 원본 portable 및 높이5mm·수평1mm 세트를 보존하고 `reports/restore-20261015/execution-t2-xy5-height5-20261015`에 T2 슬롯3 수평 거리 상한만1→5mm로 변경했다. registry 대응 해시·변경 근거를 갱신하고 다른 슬롯/집기Z·회전·힘·속도·그리퍼·ROI·깊이·310ms/50ms·조립XY 정책을 유지했다. 전체 XY 거리5mm이며 축마다5mm가 아니다. 수정된 값은 실제 집기 XY 보정에 적용된다. 다음 C 승인 문서가 새 설정 해시에 묶이며 과거 실행 ID를 재사용하지 않는다.
- 관련 합성103 passed(0.60초), 새 전체 설정 native3개 preview와 출처/산출물 해시 검사가 통과했다. 이번 실촬영20장을 당시 시각/실제 CameraInfo/현재 TCP로 장치 없이 재생해 이전XY1은20/20거절, 새XY5는20/20허용·같은 목표 재호출 중복 보정 없음·집기Z/회전 불변을 확인했다. 실시간 새 실행 허가/파지·결착 성공으로 해석하지 않는다. 근거는 `t2-stationary-review/analysis.json`, `xy5-offline-validation.json`, `t2-no-accumulation-review.json`, `t2-xy5-tests.log`다.
- `sixpart.bash xy1`은 다음 새 HMI의 수평1mm·높이5mm 설정만 선택하고 움직이지 않으며 `xy5`는 수평5mm를 선택한다. 두 선택을 실제 실행·파일 검증했고 최종 선택은XY5다. 정상/문제 때 자동 동작·복구·재시도/Current 변경을 추가하지 않았다. 현재 로봇은 공급 관측 위치이며 새 HMI를 실행하기 전에 기존 창 종료·빈 HOME 확인이 필요하다. 다음 사용자 명시 HOME→새 HMI 준비/C 별도 승인→T2 단발 시험, 종료 후 HOLD와 실제 상태 확인이다. 새 허용값으로 로봇/그리퍼를 아직 재실행하지 않았다.

## 2026-10-15 T2 공급 관측 중단 진단 · 사용자 요청 높이 허용값 조정

- 사용자 실행 Job `0caa30a7-d658-4fc0-ad32-b60906b3f421`에서 C APPROVE→실제 A 첫 S01/T2→native 관측 이동까지 진행했다. native `1792048452546239717`은 공급 관측 도착 후 파랑2×3 슬롯3의 스터드 중심 인식에 성공했으나 `SUPPLY_DEPTH_DISPLACEMENT_OUT_OF_BOUND`로 중단했다. 패킷142.258ms/skew0이며 RGB-D 수신·ROI 이탈 오류가 아니다. 원시 깊이521~527mm/편차2mm와 블록 내부3×3 patch 검사를 통과한 뒤 로봇Base 기준점 대비 변위 검사에서 실패했다. 기존 로그에는 실제 deltaXYZ가 없어 수평/높이/비정상수치 중 원인을 확정하지 않는다.
- 마지막 native 관측 표본은 motion_status0/속도0/그리퍼 폭52mm였고 집기 하강·그리퍼 명령 전이다. native 최종 result가 없어 서비스 결과는 실패/HOLD·actual_stop_verified=false·Current/completed 갱신 없음이다. 첫 사후 조회는 서비스 대기10초 후 종료124였으며, 기존 loopback DDS URI를 명시한 후속 실제 조회는 GetRobotState1/CheckMotion0/GetCurrentPosj≈[0,0,90,0,90,0]·모두success=true로 HOME 관절/동작정지를 확인했다. 후속 단발 읽기를 과거 실패 실행의 STOP 영수증으로 대체하지 않는다. 에이전트 이동/그리퍼/카메라 재기동0이다.
- 최신 사용자 명시 요청으로 T2 슬롯3의 관측 높이 허용값2→5mm를 별도 로컬 전체 세트 `reports/restore-20261015/execution-t2-height5-20261015`에 적용했다. 원본 portable의 모든 바이트를 보존했고 새 세트는 해당 depth 필드와 registry의 대응 artifact 해시/변경 근거만 갱신했다. 수평 상한1mm, 깊이521~527mm·편차2mm·310ms/50ms, 기준점·교시·집기Z/회전·힘·속도·조립XY 정책은 그대로다. `sixpart.bash`가 새 세트로 새 HMI를 열며 기존 실행 ID/승인 문서는 재사용하지 않는다. 사용자 요청의 시험 허용 변경이며 정확도 검증 또는 이번 실패 원인 해결로 표시하지 않는다.
- depth_center 실패 문자열에 finite/deltaXYZ/실제수평거리·높이차/각허용값을 추가했다. 기존 오류 코드·거부/보류 경로를 유지하고 값을 대체하거나 자동 재실행하지 않는다. 관련 합성 검사86 passed(0.54초), native3개 preview 종료0/장치 연결0을 확인했다. 높이±5mm 허용·±5.001mm 거부·기본2mm 유지·수평1mm 초과 차단과 기존 집기Z/회전 불변을 검사했다. 새 설정 실물 시험은 아직 시행하지 않았다. 다음은 사용자 실제 상태 조회→검토된 경로로 빈 HOME 확인→새 HMI의 C 별도 승인→단발 실행이다.
- 후속 사용자 실행 Job `2bb4599d-4a66-4cca-9040-3140ade4a5e6`/native `1792049066887795270`의 새 프로파일 해시 적용과 C APPROVE/A T2 바인딩을 확인했다. 공급 관측 도착·슬롯3 중심 인식 성공 후 같은 변위 검사로 HOLD: deltaXYZ=[-0.100005,-4.565083,+1.827949]mm, 수평4.566mm>1mm이며 높이1.828mm≤5mm다. 즉 이번 중단은 높이가 아닌 수평 변위다. 패킷92.274ms/skew0, 집기 하강/그리퍼 명령0, 서비스 actual_stop_verified=false/Current 미갱신이다. 사용자가 보낸 `NOT_CONFIRMED_BY_B`는 결과 전달 로그이며 이 D 오류의 원인이 아니다. 후속 읽기 CheckMotion0/success=true 확인, 추가 허용값 변경·자동 재실행/로봇 쓰기0. 원시 로그와 별도 `t2-height5-second-failure.json`을 보존했다.

## 2026-10-15 B 실시간 카메라 제외 · 6부분 통합과 D 실물 단발 시험 준비

- 사용자가 A/C/D/HMI/DB/웹을 먼저 연결하고 D는 실물로 실행하도록 요청했다. 포맷 후 새 PC이며 기존 DB/웹 환경은 없다고 확인했다. 요청한 round2 원격 브랜치를 비교용 `reference/integration-round2`로 fetch했고 SHA는 `5652b694fa08a10339e3e5ddadf5cb6dca6d5876`이다. round2의 REAL D/합성 B/로그인·개인 이력 연결을 참고했으며 전체 merge·브랜치 전환·push는 하지 않았다. A RELEASE_PRESS 0.5.2와 B 층 허용값 등 다른 변경은 가져오지 않았다.
- `--round3-camera-free-trial` 선택 모드를 추가했다. portable scenario의 사전8블록을 `SYNTHETIC_SCENARIO_NOT_B_OBSERVATION`이라는 명시적 시험 기준으로 기존 B 계약에 공급하며, 실제 INITIAL archive나 촬영 시각을 만들지 않는다. 실제 C 검토/승인→A 계획/재평가/모션→첫 T2 native 대응과 일회 실행을 사용한다. 원래 `--round3-approved-step`의 실제 INITIAL 요구·300초/해시 검사와 live-inspection 경계는 유지한다.
- 이 시험의 native 문서·service binding에 `SIXPART_REAL_D_SINGLE_STEP`·실물 조립 미확인·시험 기준 출처 해시를 기록한다. HMI는 시험 기준 구조와 B 실관측 없음을 표시한다. T2 실행 후 HOLD, completed/Current 갱신 없음, 새 START/RESUME/REINSPECT로 반복 실행 없음이다. 다음 T1/T3 연결과 P09 지지 차이는 계속 후속 범위다. 25슬롯 portable 세트·교시·동작/힘/영상 기준을 바꾸지 않았다. D의 공급 RGB-D는 유지하며 이 모드의 읽기 전용 D 프로세스는 별도 제스처 카메라를 열지 않는다.
- D 단발 결과 후 인증된 제작자에게 시험 Job을 DB 적재하고 웹에서 미완료 설계/이력을 조회한다. 정식 FINAL 저장 영수증은 발급하지 않으며 완료 저장 조건을 완화하지 않았다. DB 반영 후 웹 실패 재시도는 웹 조회만 수행한다. 다른 사용자·진행 중 중복 요청은 거절하며 물리 동작을 다시 실행하지 않는다.
- 프로젝트 `.venv`에 기존 요구사항 psycopg/binary3.3.6만 설치했다. 로컬 시험용 PostgreSQL17 이미지를 받고 Compose 프로젝트 `c2-round3-sixpart-20261015`의 새 볼륨/DB `c2_round3_sixpart_test`를 시작했다. 127.0.0.1:55439에만 노출하며 기존 볼륨/계정은 수정하지 않았다. 앱은 `.env.sixpart-local.bash`(600)에 접속 정보·전용 시험 계정을 보관한다. 비밀값은 출력/게시하지 않았다. 웹은 127.0.0.1:8767에서 기동했고 HTTP200·스키마·시험 롤백 후 사용자1/Job0을 확인했다.
- 관련 승인/native/live/저장 회귀는 실제 별도 DB/로컬 HTTP와 명시적 가짜 D를 사용해40 passed1skipped(37.04초)다. skip은 기존 5층 재생 로그 부재1건이며 해당 로그를 만들기 위한 무관한 전체 시험을 추가하지 않았다. 새 6부분 사례는 실제 C/A·로그인/DB/HTTP·소유자 격리·웹 재시도에서 D launch1회/미완료 유지 확인을 포함한다. HMI 계약167 passed, 기존 native 관측 이동/ROS adapter48 passed, 합계255 passed1skipped다. 후속 HMI 문구/레이아웃 수정 후 해당 UI2개를 재실행해 통과했고 1400×1000 합성 화면을 직접 검토했다. HOME wrapper도 정상/실패2개 명시 fixture와 기본 무동작 preview를 확인했다.
- 로컬 `reports/restore-20261015/sixpart.bash`는 preview/home/web/hmi를 각각 명시적으로 실행한다. HOME은 이전 사용자 확인 경로·기존 InspectionMotion과 기존23deg/s·1mm/1°·실장치 guard를 사용하며, 실패 시 자동 재이동하지 않는다. HOME 성공 확인 후 HMI를 열어 전용 시험 계정 로그인→준비 체크→C 미리보기/별도 승인→첫 T2 파랑2×3 슬롯3→(13,11,L2,0°)를 실행하도록 준비했다. 에이전트의 실제 로봇/그리퍼 명령0이며 실제 HOME/T2/결착 성공·새 B INITIAL/STEP/FINAL·전체 서비스 완성은 아직 검증하지 않았다.

## 2026-10-15 새 PC 별도 작업본 복원·Python/DRCF2 파일 확인 — 장치 미연결

- 사용자 요청에 따라 `/home/rokey/협동2/C-2-round3`에 인계 bundle을 독립 clone했다. 브랜치는 `codex/integration-round3`, HEAD는 `1288625239ecdf517ae1b78fa05226a9bd7f8a33`이며 bundle 검증과 소스 2,070개 해시 대조가 통과했다. 기존 작업본·Downloads 원본은 수정하지 않았고 commit/push/PR/merge는 수행하지 않았다.
- `.venv`는 Python 3.12.3의 `--system-site-packages --without-pip`으로 만들었다. 로컬 전용 `.env.round3-local.bash`에서 `PYTHONNOUSERSITE=1`을 적용해 사용자 영역 NumPy 2.5.4와 시스템 SciPy의 충돌을 피한다. NumPy 1.26.4·SciPy 1.11.4·pymodbus 3.6.9·ROS Python/메시지·cv_bridge·Qt import와 GetCurrentPosj/MoveStop 타입 지원을 확인했다. 패키지 설치·시스템 Python 변경은 없다.
- `C2_ROS_WS`와 `C2_DRIVER_ROOT`는 기존 `/home/rokey/cobot2_ws`를 선택한다. 동봉 소스와 Doosan 1,352개·onrobot 78개·bringup 14개 파일이 일치한다. 두 설치 라이브러리는 실제 빌드 산출물과 Build ID/코드 영역이 일치하고 컴파일 기록은 `DRCF_VERSION=2`다. 선택된 package prefix와 공유 라이브러리 의존성도 확인했다. 설치 시 RPATH 변경으로 파일 전체 해시는 빌드 디렉터리와 다르며 과거 PC의 바이너리 해시를 재사용하지 않았다. 재빌드는 하지 않았다.
- 이 PC의 `READY.json`은 없으며 원본 READY를 복사하거나 새 실물 승인 기록을 만들지 않았다. 실행 중 드라이버의 실제 로드 경로·서비스 가용성·현장 정지/제어권·HOME은 미확인이다. ROS 노드 생성·서비스 호출·Robot/Camera/Gripper 연결과 물리 명령은 모두 0이다.
- portable 25슬롯 validate, INITIAL preview(V0→D1→D3), 서비스 preflight가 각각 종료0으로 통과했다. 20 RGBD_XY+5 TEACHING_ONLY, 후보11블록, T2→T1→T3와 T3 추가 지지 차이가 유지된다. 합성 prefix는 B Current가 아니며 사용자 승인은 false다. 사용자 터미널의 동일 검사 출력도 같은 결과다.
- 동봉 손 모델을 `robot_control_integration/logs/handover/stage02/hand_landmarker.task`로 복원하고 원본 해시 일치를 확인했다. 모델은 실행하지 않았다. 전용 환경의 MediaPipe·psycopg는 미설치이며 제스처/DB/웹 검증은 후속 범위다. 근거는 로컬 `reports/restore-20261015/`에 저장했다.
- 후속 사용자 제공 ROS 목록에서 `get_current_posj`/`move_stop`이 각각 `dsr_msgs2/srv/GetCurrentPosj`/`MoveStop`으로 발견됐다. 서비스 존재 확인이며 응답 시간·실제 STOP·과거 실패 원인 해결의 증거는 아니다. `/dsr01/dsr_rokey_basic_py`도 보이며 로컬 `rokey_cobot2/basic/jog_complete.py`가 같은 노드명으로 이동/그리퍼 버튼이 있는 `Pos 설정` 창을 만든다. 실제 프로세스 정체와 드라이버 로드 경로는 아직 미확인이고 자동 종료·재기동하지 않았다. 원본 출력과 검토 JSON은 로컬 reports에 보존했다.
- 후속 사용자 단발 조회는 GetRobotState=`3/STATE_SAFE_OFF`, CheckMotion=`0`, GetCurrentPosj=`[3.79983544,18.40449905,40.56082916,-3.10641146,121.00118256,0.39996752]`이며 세 응답 모두 success=true다. 이번 조회에서 응답 시간 초과는 재현되지 않았으나 실제 응답 시간은 측정하지 않았다. INITIAL 중 실패 원인 해결·STOP 경로·HOME·B Current 확보의 증거는 아니다. 사용자에게 현재 무동작 진단에서는 서보를 다시 켜지 않고 SAFE_OFF를 유지하도록 안내했다. 원본 값은 `reports/restore-20261015/user-readonly-state.json`에 기록했다.
- 이후 사용자 요청으로 이 PC의 환경 source→roboton2(camera=false, rviz=false)와 별도 10fps/Infra OFF 카메라 기동 명령을 안내했고, 사용자가 기동했다고 보고했다. 로컬 드라이버 초기화는 제어권 요청과 Servo ON을 시도하므로 서보 OFF 유지용 명령이 아님을 먼저 설명했다. 에이전트가 장치를 직접 기동하거나 안전 상태를 해제하지 않았다.
- 재기동 후 사용자 터미널의 rg 미설치로 목록 필터가 중단돼 grep으로 바꿨다. 후속 출력에서 두 필수 서비스와 GetRobotState=`1/STATE_STANDBY, success=true`를 확인했다. 재기동 후 동작 상태·관절·TCP/Tool·카메라 전송은 아직 결과 대기다. 원본 SAFE_OFF 조회와 새 STANDBY 보고는 별도 JSON으로 보존하며 STOP 경로·HOME·B Current 검증으로 승격하지 않는다.
- 남은 읽기 검사를 짧은 한 줄로 실행할 수 있도록 로컬 `reports/restore-20261015/check-readonly.bash`를 준비했다. CheckMotion/GetCurrentPosj/GetCurrentTcp/GetCurrentTool 네 조회와 동봉 verify_rgbd.py만 수행하고, 실행마다 별도 결과 폴더를 만들며 실패 시 중단한다. bash/내장 Python 구문과 고정 조회 대상을 확인했다.
- 사용자 실행 결과 `live-readonly.9rpgjC`의 원시 파일을 직접 검토했다. CheckMotion=0·관절 조회 성공·TCP GripperDA_v4·Tool ToolWeight0가 확인됐다. RGB239/정렬Depth240/양쪽Info239개, 모두1280×720·camera_color_optical_frame, 약29.9785Hz, 나이44.018~60.358ms·대응packet skew0ms이며 각 토픽의 발견된 발행자는1개다. 이번8초 전송은 기존250ms/50ms 기준 이내이며 인식/보정/조립 성공이나 실제 STOP 검증은 아니다. 인계의10fps와 현재30fps를 구분하고 설정 변경·재기동은 하지 않았다. 정리와 원본 해시는 해당 폴더 review.json에 기록했다.
- 현재 카메라 profile/Infra1·2/USB 연결 정보를 읽는 `reports/restore-20261015/check-camera-config.bash`의 사용자 실행 결과를 원시 파일로 확인했다. `camera-config.v2tDlx`는 RGB1280×720×30/Depth848×480×30, Infra1·2=false, D435i USB3.2다. 이전 PC의10fps 전송 근거와 이 PC의30fps·8초 전송 근거를 구분해 보존하며 현재 설정을 유지한다. 이번 확인에서 카메라 매개변수 변경·재기동은 없다.
- `reports/restore-20261015/check-runtime.bash`의 사용자 실행 `runtime-check.lPGjfU`를 원시 파일로 확인했다. 실제 로봇0·자동 모드1이고 로컬 dsr01 driver PID100392 한 개의 controller/hardware 매핑 경로·inode·검증 해시가 모두 일치한다. 두 B 모델 파일도 존재한다. 이 결과를 다른 PC의 제어권이나 실제 STOP 시험 완료로 해석하지 않는다.
- 유일한 실패는 B 이미지 미등록이다. 저장된 Docker 오류는 `No such image: c2-b-vision:pr48-20261014`이며 daemon 접근 실패가 아니다. 검사 도구가 stdout의 빈 줄 때문에 stderr를 화면에 보여주지 못하던 부분을 수정하고 bash/내장 Python 구문을 다시 확인했다. 동봉 이미지 tar.gz의 크기1,116,825,274바이트와 SHA256을 manifest에 재대조해 일치했다(`vision-archive-recheck.json`). 다음은 사용자 터미널에서 docker load 후 같은 검사로 image ID를 대조하는 것이다. 이 기록 시점에는 이미지 load·컨테이너 기동·드라이버 재시작·INITIAL/조립·live 연속 옵션·MoveStop을 실행하지 않았다.
- 사용자 docker load 후 `runtime-check.Y12HOc`의 원시 summary에서 image ID가 인계값과 일치하고 여섯 파일/실행 환경 항목이 모두 true임을 확인했다. 정지 응답·실제 B 관측 성공으로 승격하지 않는다.
- 사용자가 실제 이동을 허용했고, 빈 그리퍼·손 이탈·HOME/V0/D1/D3 경로 검토·사전8블록 준비를 모두 확인했다. 직접 사용자 확인은 로컬 `operator-readiness.json`에 기록했으며 C 후보 승인과 구분한다. 같은 현장 준비를 재승인받지 않고 STOP 경로 확인 후 INITIAL로 이어간다.
- 현재 환경에서 INITIAL/live integration19개와 native inspection/ROS adapter48개, 총67개 기존 모의 검사가 통과했다. 첫 native 명령은 환경 source의 cd로 대상 경로를 찾지 못해0개였고 C2_ROBOT_ROOT로 이동한 재실행에서48개가 통과했다. 장치 연결0이다. 새 STOP helper도 명시 fixture4개로 정상1회/움직임과FK불일치시0회/STOP실패시재시도0회를 확인했다.
- 로컬 `check-before-initial.bash`는 네트워크 없는 임시 B 컨테이너에서 두 모델을 먼저 로딩하고, 동일 INITIAL open_motion/InspectionMotion 경로로 읽기 표본3개·V0/D1/D3 FK 일치·STOP1회와 기존3표본 정지 피드백을 검사한다. 기존0.5초 피드백/서비스와1mm·1°/정지 기준을 유지하며 이동·그리퍼·힘·모드 변경은 호출하지 않는다. 기본 check-stop.py preview는 장치 연결0으로 확인했다. 실제 B 모델 로딩·STOP 시험은 사용자 실행 결과 대기이며 INITIAL/조립을 자동 실행하지 않는다.
- 사용자 실행 `preinitial.Bf5kmd`는 모델 로딩 뒤 보조 검사에서 멈췄다. 에이전트가 블록 모델을 detect로 잘못 제한한 것이 원인이며, 실제 B는 `yolo_pipeline.load_segmentation_model`로 segment를 요구한다. checkpoint를 실행하지 않고 pickle opcode로 SegmentationModel/Segment26/task=segment를 확인했고 파일 해시도 원본과 일치한다. 보조 검사는 기존 B의 엄격한 segmentation loader와 손 detect loader를 그대로 사용하도록 수정했다. 모델·클래스·판정 임계값·B production은 변경하지 않았다.
- 위 실패에는 stop-result.json이 없고 shell이 로봇 단계 전에 종료돼 실제 STOP/이동/그리퍼 명령0이다. 실패 로그와 검토 JSON은 보존했다. YOLO_CONFIG_DIR는 기존 실행 스크립트와 같은 /tmp로 맞춰 없는 하위 경로 경고를 피했다. 수정 후 bash/Python 구문·loader 호출 대조와 B 관련 선택 모의9개 통과(467 deselected)를 확인했다. 실제 수정 보조 검사·STOP 시험은 사용자 재실행 결과 대기다.
- 사용자 재실행 `preinitial.XqpU54`의 원시 로그에서 손 detect/블록 segment 5종 모델 로딩과 `STOP_SERVICE_AND_FEEDBACK_VERIFIED`를 확인했다. 실제 정지 상태에서 기존 native STOP1회와 3표본 정지 피드백·writer 해제가 통과했으며 이동/그리퍼 명령0, Current=null, home_return_verified=false다. 조회 표본은 HOME 관절값 부근·속도0·CheckMotion0·STANDBY1·자동1·DRL3·빈 패드52mm이고 전체 표본 조회 시간0.107~0.131초다. V0/D1/D3 FK 위치 오차0.411/0.287/0.830mm·회전0.170/0.039/0.084°로 기존1mm/1° 이내다. 정지 중 STOP 검사이며 이동 중 정지 시험이나 과거 HAND_RECEPTION 시간 초과 원인 해결의 증거로 승격하지 않는다.
- 이미 확인받은 현장 준비 조건으로 INITIAL만 한 번 수행하는 로컬 `reports/restore-20261015/run-initial.bash`를 준비하고 bash 구문·diff 공백을 검사했다. 기존 production CLI와 확인 플래그를 사용하며 V0→D1→D3 관측 성공 후 HOME으로 복귀한다. 에이전트는 이 파일을 실행하지 않았고 실제 새 INITIAL/B Current·HOME 복귀는 사용자 실행 결과 대기다. 조립·후속 Step·live 연속 실행·자동 재시도는 포함하지 않는다.
- 사용자 INITIAL `f6053e6f-edcc-4a41-9f72-967ef4e7a738`의 result/events/B response 원본을 확인했다. V0 도착0.398mm/0.170°·정지 확인 후 `fresh synchronized V0 hand RGB/Depth unavailable; check topics/clocks`로 HOLD다. Current=null, home_return_verified=false, actual_stop_verified=true, writer_released=true, 조립/그리퍼 명령0이다. 실패 종료 표본은 V0·속도0·CheckMotion0·STANDBY1·그리퍼0/52mm·조회0.114초다. 이전 PC의 STOP 부재와 구분하며 이번 성공 STOP을 현재 시각의 지속 정지 보증이나 INITIAL 성공으로 해석하지 않는다.
- 원인 확정 전에 재실행/자동 HOME/카메라 재기동/임계값 변경을 하지 않는다. 로컬 `check-b-camera.bash`와 metadata 전용 수신기를 준비해 호스트와 동일 B 실행 wrapper의 컨테이너에서 각각8초 수신·RGB RELIABLE/BEST_EFFORT 차이·정렬/원본 Depth·CameraInfo·발행자 QoS·시각/영상 나이·RGB/Depth skew를 비교한다. 로봇 client·모델 추론·B Current 생성은 없으며 bash/Python 구문·diff 공백을 확인했다. 실제 비교 결과는 사용자 실행 대기다.
- 사용자 비교 `b-camera.UX1yAu` 원본에서 호스트 raw Depth481/raw Info480개(Depth 나이11.814~18.754ms), RGB 두 QoS·정렬Depth·관련Info는0개를 확인했다. 컨테이너는7개 수신 모두0이고 발행자 목록도 모두 비었다. 양쪽 domain20·CycloneDDS·실제 시계이며, RGB 수신 자체가 없어 RGB/Depth 시각 차이로 원인을 확정할 수 없다. 앞선 정상 RGB-D 전송 근거와 현재 결손을 구분한다. 사용자가 준 기동 로그는 RGB/Depth30fps 시작과 HARDWARE_CLOCK 경고이며 현재 RGB 중단의 확정 원인은 아니다. 비교·원본 해시는 해당 review.json에 기록했다.
- 이 PC의 .bashrc는 CYCLONEDDS_URI로 lo 전용 설정을 선택하지만 기존 B wrapper는 해당 환경/파일을 전달하지 않았다. scripts/c2_b_docker.sh에서 file:// 설정을 읽기 전용 mount하고 URI를 전달하도록 수정했다. 파일 누락/읽기 불가 시 컨테이너 실행 전에 실패하며 inline URI와 미설정 동작을 보존한다. fake Docker4개와 기존 INITIAL/live integration19개, 총23 passed/종료0이며 bash 구문·diff 공백 통과, 실제 컨테이너/ROS 연결0이다. 임계값·로봇 제어·카메라 설정·이미지는 변경하지 않았다.
- 다음은 수정 wrapper로 같은 무동작 비교를 사용자 실행하여 DDS 발견·RGB 수신을 확인하는 것이다. 로컬 검사에 현재 카메라 parameter dump 조회를 추가했다. 컨테이너 발견 회복과 호스트 RGB/정렬Depth 중단 원인은 아직 실측 대기이며 INITIAL/카메라를 자동 재실행·재기동하지 않는다.
- 사용자 비교 `b-camera.jLa8qu`에서 수정 후 컨테이너가 모든 카메라 발행자를 발견하고 raw Depth481/raw Info480개를 수신했다. 컨테이너 raw Depth 나이11.776~14.987ms로 DDS 설정 전달 후 실제 발견·수신 회복을 확인했다. 호스트도 raw481/Info480이며 RGB 두 QoS·정렬Depth·관련Info는 양쪽 모두0이다. parameter dump는 enable_color/depth/sync/rgbd와align_depth=true, Infra1/2=false, RGB1280×720×30·Depth848×480×30, use_sim_time=false다. RGB/정렬Depth 전송과 INITIAL은 여전히 미통과다.
- 다음 장치 조작은 사용자가 기존 카메라 터미널을 직접 종료하고 인계에서 전송을 확인한10fps·Infra OFF 설정으로 카메라만1회 기동한 뒤 같은 무동작 비교를 수행하는 것이다. 로컬 `start-camera-10fps.bash`는 기존 /camera가 보이면 중복 기동을 거부하며 자동 재시작/반복은 없다. bash 구문·diff 공백을 검사했고 에이전트가 이 파일이나 실제 카메라를 실행하지 않았다. 로봇 드라이버·교시·그리퍼·B 임계값·alias는 변경하지 않았다. 30fps 중단의 상세 원인과10fps 전송 회복 여부는 아직 미확정이다.
- 후속 사용자 비교 `b-camera.DXCzpD`에서 호스트 RGB239/정렬Depth240, 컨테이너 RGB240/정렬Depth240개와 원본Depth·3종Info 수신을 확인했다. 양쪽 모두 각 발행자1개·기존형식/해상도/frame·수신 전 시각 없음, 전체 영상 나이43.429~56.162ms·RGB/Depth 최근접skew0ms로 기존250ms/50ms 이내다. 손 수신기의 RELIABLE RGB도 양쪽239/240개로 실제 수신됐다. 원본·해시와 검토 항목은 해당 review.json에 기록했다. 실제 B 모델 추론·8블록 INITIAL 채택 성공으로 승격하지 않는다.
- 이번 실제 parameter dump는 RGB1280×720×30·Depth848×480×30, Infra1/2=false·정렬/sync/rgbd=true다. 안내한10fps 기동의 실행 여부를 추정하거나10fps 성공으로 기록하지 않으며, 현재30fps 전송이 통과했으므로 추가 설정 변경/재기동은 하지 않는다. 기존 승인된 현장 준비 조건으로 사용자가 `run-initial.bash`를1회 실행해 세 View/B Current/HOME/정지/writer 결과를 확인하는 다음 단계를 안내한다. 재시도/조립 자동 실행은 없다.
- 사용자 INITIAL `a9c88d28-666c-4236-ae76-48c0e1ff1ca2` 원시 result/events/failure를 확인했다. V0 도착0.412mm/0.170° 확인 후 세 영상/CameraInfo 촬영 수신 시간 초과로 HOLD이며 Current=null·HOME=false·actual_stop_verified=true·writer_released=true·조립/그리퍼0이다. 마지막 정지 조회0.114초·STANDBY1·빈52mm다. D1/D3 성공 또는 INITIAL 채택으로 표시하지 않는다.
- capture_inspection_view가 매 콜백 사이에 동기식 제어 상태 조회를 수행하는 구조에서, 6개 토픽을 한 콜백씩 받는 모의 executor와60ms 조회 지연으로 촬영 시간 초과를 재현했다. 기존 손 수신기와 같이 촬영 수신도 전용 thread에서 계속 처리하고 최신 bounded queue·CameraInfo 사본을 lock으로 선택하도록 수정했다. 상태/취소/정지 확인은 기존 순서로 유지하며 마지막 조회 후 영상 나이를 다시 확인한다. timeout15초·나이250ms·skew50ms·로봇 제어 기준을 변경하지 않았다. receiver 오류/취소/만료는 실패로 정리하고 Current를 만들지 않는다.
- 수정 전 회귀 재현 로그는 capture-before-fix-tests.log이며, 수정 후 촬영 관련41 passed, B 전체478 passed1skipped(기존 PR22 consumer 미제공), root INITIAL/live/wrapper23 passed로 해당 범위 모두 종료0이다. 촬영41개는 B 전체에 포함되므로 합산하지 않는다. 실제 ROS/카메라/로봇/컨테이너 실행0이며 실물 수신/전체 INITIAL 회복은 아직 미확인이다. 변경은 수신 처리와 관련 테스트에 한정했다.
- 사용자가 담당자에게 B 제외 A/C/D/HMI/DB/웹앱 우선 통합 가능 여부를 검토 요청 중이라고 알렸다. 카메라 실시간 인식을 대기하지 않는 소프트웨어 통합은 기존 runbook의 L1~L3 병행 범위로 안내한다. B 소유 Current/revision/MATCH/FINAL 경계는 명시적 시험 자료로 유지하고 D 모의 실행·별도 시험 DB/웹을 실제 실물 완료와 구분해야 한다. 이 질문만으로 6부분 전체 신규 구현·DB 설치·운영 데이터 저장을 시작하지 않았고, 추가 INITIAL 실물 재실행도 안내하지 않았다.

## 2026-10-15 다른 PC·새 채팅 인계와 INITIAL 실패 보존

- 사용자 요청으로 현재 round3 서비스 연결 변경을 대상 브랜치에 로컬 커밋하고, 독립 Git bundle·실행 설정 원본/휴대본·외부 런타임·검증 근거·새 채팅 인계문을 ZIP으로 전달한다. 원격 push/PR/merge는 요청 범위에 포함하지 않았다. 다른 PC의 경로 지정용 `scripts/round3_environment.example.bash`와 [인계 안내](D_ROUND3_HANDOFF_20261015.md)를 추가했다. 기존 공급판·motion 수치·B 최신성/정지 임계값은 변경하지 않았다.
- 실제 INITIAL run `fc31b465-45e3-45aa-abb1-485da99ac420`, check `42c3d345-e916-4693-be6c-75ce87d5508c`는 V0 도착 확인 후 `HAND_RECEPTION` 중 `aux_control/get_current_posj` 응답 시간 초과로 HOLD 종료했다. `stop_error=SERVICE_UNAVAILABLE: motion/move_stop`, Current=null, actual_stop_verified/home_return_verified=false, writer_released=true, 조립/그리퍼 명령0이다. 프로세스 종료를 실제 정지로 해석하지 않는다. 실제 정지 확인과 상태 조회·STOP 서비스 진단을 다음 장치 작업의 선행 조건으로 남겼다. 이 요청에서 추가 로봇/그리퍼 명령을 보내지 않았다.
- 결과·이벤트 원본은 기존 logs 폴더와 인계 압축본 evidence에 보존한다. 성공 INITIAL/조립/B STEP/FINAL·실제 DB·웹 인수 완료가 아니다. 이번 전달 검증의 명령·결과는 상위 `reports/round3_handoff_20261015`와 압축본 manifest에 기록한다.
- 커밋 전 재검사: 서비스/B801 passed1skipped, native108 passed, 저장 관측/A/변경 replay32 passed, MVP5 passed로 유효 대상 총946 passed1skipped다. 최초 MVP5건은 C2_ROBOT_ROOT 미지정으로 skip됐고 해당 경로를 지정해5건만 재실행·통과했다. skip1건은 기존 PR22 consumer 미제공이다. Python AST/JSON, bash 구문, 문서 링크/코드펜스, diff 공백, portable/원본25슬롯 실행 수치 일치, INITIAL preview와 서비스 preflight를 확인했다. 이번 검사는 장치/DB/외부 API에 연결하지 않았다.

## 2026-10-15 서비스 장비 재연결 — 로봇 읽기 조회

- 후속 카메라 출력(사용자 제공)은 RGB80/정렬Depth81/양쪽Info80개, 모두1280×720/camera_color_optical_frame, 약9.99Hz, 수신 시 나이120.33~195.48ms, 대응 packet skew0ms다. 이 8초 전송 검사는 통과이며 조립 인식·보정 정확도 확인은 아니다. B Docker import/설정·두 모델 파일 존재도 실제 기존 image에서 확인했다. 카메라 장치에 새 연결을 열거나 로봇 명령을 보내지 않았다.
- INITIAL 사전 읽기에서 V0/D1/D3의 교시 joint→실제 FK와 교시 TCP 차이가 각각0.411/0.287/0.830mm, 회전0.170/0.039/0.084°로 기존1mm/1° 이내다. 현재 V0 차이0.386mm/0.170°, 실제 driver로 읽은3표본은 속도0/동작0/그리퍼0, 조회0.108~0.132초였다. 실제 읽기 경로만 허용했으며 Move/STOP/그리퍼 쓰기0. `preinitial-045539176496.json`에 보존했다. 실제 이동 경로/현장 손 이탈/빈 그리퍼·8블록 준비는 별도 현장 확인이다.
- 첫 사전 조회는 안내의 `PYTHONPATH=.:perception`이 ROS import 경로를 덮어써 rclpy 누락으로 장치 연결 전에 HOLD였다. 실물 INITIAL 명령을 `PYTHONPATH=".:perception${PYTHONPATH:+:$PYTHONPATH}"`로 정정한 뒤 위 실제 읽기 통과를 확인했다. 설치·환경 파일 변경은 없으며 실패 기록 `preinitial-045442498666.json`도 보존했다. 300초 초기 관측 채택 창에 대비해 `logs/round3-service-guide/design.candidate.json`의11블록 검토 후보를 C validator로 검사·준비했고 사용자 승인은 하지 않았다.
- round3 launch `camera:=false rviz:=false`와 사용자 노드 목록을 확인하고, 기존 ROS/DRCF2 환경에서 실제 조회 서비스 9종과 RG2 register 267/268을 읽었다. robot_system0, robot_state1, robot_mode1, motion_status0, drl_state3, TCP GripperDA_v4/Tool ToolWeight0, TCP 속도0 응답이다. RG2 status0/폭52.0mm/grip_detected=false이며 실제 빈 그리퍼·현장 준비를 자동 확정하지 않는다.
- 현재 관절 `[3.7999,18.3037,40.5009,-3.1014,121.0003,0.4000]`은 HOME이 아닌 기존 V0 교시에 가깝다. 로봇 이동/그리퍼 쓰기/모드·TCP 변경 명령0. 단발 조회이며 지속 정지·카메라 촬영·INITIAL/B 채택·조립 성공 근거가 아니다. 카메라는 아직 연결 확인 전이다.
- 원시 조회 기록: 상위 로컬 `reports/round3_service_hardware_20261015/connection-045138471178.json`. 다음은 기존 검증된 10fps·Infra1/2 OFF 카메라 기동과 RGB/정렬Depth/Info 읽기 확인이다.

## 2026-10-15 장치 대기 중 0~9단계 검토와 선행 개발

- 사용자 요청으로 장치 작업을 보류하고 0~9단계를 [실행 가이드의 장치 대기 검토표](D_ROUND3_SERVICE_INTEGRATION_RUNBOOK.md)에 정리했다. 이전 실물 검증 없이 확정 계약/fixture로 개발할 수 있으며, 실제 Current·파지/결착·정지·경로 성능은 장치 증거가 필요하다는 경계를 유지한다. 작업 전 변경과 미추적 파일 사본은 상위 로컬 `reports/round3_offline_service_20261015`에 보존했다. HEAD `93ef967`, 로컬 round3에서 작업하며 commit/push/merge는 하지 않았다.
- 우선 4/7단계의 `LiveInspectionObserver`를 추가했다. 기존 Docker 관측과 round3 D driver로 STEP/FINAL을 관측하고, B가 비교·Current를 소유한다. `--round3-approved-step --round3-live-inspection`에서 native 종료·binding 일치 후 B STEP를 요청한다. MATCH만 한 Step 완료, MISMATCH는 실제 Current를 C에 전달, UNOBSERVABLE/ERROR/STOP은 진행을 보류한다. B 재검사는 새 check_id로 관측만 하며 native를 반복하지 않는다. 다음 d.prepare_step은 `REMAINING_NATIVE_STEP_BINDING_REQUIRED`로 보류하여 닫힌 reader로 명령하지 않는다. 기본 단발 실행은 그대로다.
- 실제 관측 출처 `REAL_CAMERA_STEP_FINAL`을 D 내부 HMI 검증/표시에 추가했다. 공통 ABCD 검사 DTO, ROS 서비스, DB schema/API는 변경하지 않았다. 관측 종료 뒤 HOME/정지 확인·driver/writer 정리를 마친 후 B 결과가 확정된다. 관측 중 취소는 기존 실제 STOP 확인을 중계하고, retired native 뒤 정지는 새 조회/STOP 경로를 사용한다. 실제 정지가 확인되지 않으면 STOPPED를 만들지 않는다.
- **남은 D 인계:** 현재 native는 조립판 위에서 빈 패드를 닫고 끝나지만 관측 이동은 열린 빈 그리퍼/HOME을 전제로 한다. 관측 시작에 기존 `InspectionMotion.confirm(..., allow_move=False)`의 읽기 전용 HOME 확인을 추가했다. 전제가 다르면 View 이동·촬영 전에 실패한다. 자동 개방/새 복귀 경로/그리퍼 상태 완화는 추가하지 않았다. 기존 release/press/수직 상승과 open_empty_pad·검토된 복귀 경로를 잇는 개발·실물 확인이 남아 있어 새 live 옵션을 정상적인 실물 연속 서비스로 안내하지 않는다.
- 5단계의 `app.round3_service_preflight`를 추가했다. 실제 C 후보 검사·A whole/Step 재평가·native preview로 T2→T1→T3와 공급 프로파일을 확인한다. 합성 Expected prefix임을 명시하고 사용자 승인·B Current·실행 권한을 만들지 않는다. 25개 모두 실행 대상이며 현재 scenario와 연결된 세 슬롯을 구분한다. A T3 판단 NONE과 native P09 수동 지지 차이를 `additional_native_support_required=true`로 기록했다. 남은 prefix/소비 슬롯/지원/프로세스 반복 binding과 수정 후 native 재개는 후속 개발이며 장치 없이 fixture로 선행할 수 있다.
- 8단계는 DB 저장 성공 영수증과 사용자를 보존하고 웹 실패 뒤 웹 확인만 재시도하도록 수정했다. 다른 사용자·진행 중 중복을 차단하며 DB 실패는 저장부터 재시도한다. 저장 재처리가 물리 완료·조립 실행을 바꾸지 않는다. 이력 완료 판정에도 FINAL MATCH의 unobservable 잔여를 차단하여 저장 전제를 진행부와 일치시켰다. 현재 실행 환경에 psycopg/명시적 시험 DSN이 없어 실제 DB/웹 통합은 실행하지 않았으며 설치·운영 DB 추정 연결도 하지 않았다.
- 검증: 새 관측/INITIAL/승인 Step·기존 HMI/진행/이력/저장·B 전체 **801 passed, 1 skipped**, native 관측/motion/ROS adapter **108 passed**, 기존 저장 관측 ABCD/설계 변경/A replay·MVP 통합 **37 passed**. 총 **946 passed, 1 skipped**, 각 종료0. skip은 기존 PR22 consumer 미제공이다. 모든 D·카메라·저장 경계의 대체 입력은 명시적인 fixture이며 실제 장치 성공 증거가 아니다. 최초 새 HMI 출처 검증 실패를 로컬 enum/표시에 연결했고, psycopg 없는 단위 환경은 저장 경계를 명시적으로 대체하여 검사했다.
- 9단계의 정상·차이·관측 불가·오류·취소·별도 FINAL·변경 승인·저장/웹 실패를 관련 회귀로 확인했다. 실제 8블록 INITIAL, native→B 인계, 남은 실물 조립·변경 후 재개·별도 FINAL·계정별 DB/웹까지의 인수 시험은 남아 있다. 사용자가 이미 INITIAL preview를 통과했으므로 장치 재개 때는 연결·읽기 조회 후 실제 INITIAL 한 번부터 이어간다. 이번에는 로봇/그리퍼/카메라/실제 ROS 장치/LLM API/DB 연결을 실행하지 않았다.

## 2026-10-15 Round3 최신 로봇 제어 기반 INITIAL 실행기 연결

- 기준은 로컬·원격 `codex/integration-round3`의 `93ef967869065abb971e690aae44c3fe45e468bc`다. 작업 시작 시 기존 README/STATUS 수정과 실행 가이드를 보존하고 상위 로컬 `reports/round3_initial_integration_20261015/preexisting.patch`, `preexisting-status.txt`에 기록했다. round2 작업본·원자료는 수정하지 않았다.
- `app.round3_initial_inspection`에 INITIAL 전용 preview/run을 추가했다. 실제 B `connect_inspection`→Docker 관측→D 관측점 이동/정지·pose hook→B Current 확정→저장 archive와 Current 대조→HOME 복귀 확인→B 작업자/ROS 정리·writer 해제 순서다. 조립·그리퍼 명령은 실행하지 않는다. 성공 상태는 `INITIAL_CAPTURED_HOME_RETURNED`이며 `initial_capture_directory`를 기존 `--round3-approved-step`에 전달한다.
- round2의 로컬 `DockerBObserver`, Docker 관측 진입점/실행 스크립트, `InspectionMotion`, 실제 HOME/V0/D1/D3 교시를 필요한 범위만 재사용했다. round2 작업본 HEAD `e868bba`는 원격보다 18커밋 뒤이며 미커밋 파일도 있어 전체 병합하지 않았다. View·속도/가속도·도착 허용값·보정/모델 경로의 동일성을 비교 기록으로 확인했다.
- [PR #55](https://github.com/suuuhululu/C-2/pull/55) `04a382157b60a7697c0c4570478bda37211e5e1c`의 필요한 INITIAL V0→D1→D3 순서를 반영했다. PR 전체 merge/cherry-pick, stud_layer 진단·높이 임계값 변경은 하지 않았다. B Current/revision/비교 및 공통 ABCD 계약은 유지한다.
- 정지 판정은 기존 round3 `REAL_STILLNESS_TOLERANCES`를 도착 확인과 촬영 전 조회에 동일하게 적용한다. 새 허용값을 만들지 않았으며 round2의 정확한 속도0 조건을 가져오지 않았다. D3의 실제 원인을 확정하거나 실물 실패가 해결됐다고 표시하지 않는다. 영상 최신성도 기존 B의 250ms/skew50ms를 유지하고 round2의 5000ms/200ms override를 제외했다.
- 취소/오류는 HOLD와 실제 STOP 확인 경로로 종료한다. 닫힌 요청·다른 check/view·중복 writer를 차단하고 B worker가 끝나기 전 driver를 닫지 않는다. Ctrl+C는 취소 Event를 닫는다. HOME 또는 archive 검증 실패 시 이미 B가 확인한 Current를 유지한다. 도착 표본은 `events.jsonl`, 촬영 전 정지 불일치는 `inspection-state-failures`에 실제 속도·상태·오차와 함께 기록한다. 실제 STOP 미확인은 성공으로 표시하지 않는다.
- round3의 `AssemblyMotionRos`, 기본 제어 설정, 세 사이클 native, portable 공급 profile/scenario가 HEAD와 바이트 동일함을 확인했다. 원래 공급판 RGB-D/교시·집기·결착·힘·속도를 변경하지 않았다. 출처 hash와 비교 결과는 상위 로컬 `reports/round3_initial_integration_20261015`에 보존했다.
- 이번 실행 검사: 새 INITIAL 계약/프로세스·정상/관측 불가·오래된 ID·D3 정지 실패·HOME 실패·취소·archive 불일치·writer/ROS 정리 **12 passed**; native 관측 이동/기존 motion·ROS adapter **106 passed**; B 전체 **475 passed, 1 skipped**(기존 PR22 consumer 미제공); 기존 round3 승인 Step/고정 HMI/저장 관측/변경/A replay **58 passed**. 총 **651 passed, 1 skipped**, 각 종료0. D·카메라 데이터는 명시적 fixture이며 실제 장치 증거가 아니다.
- INITIAL preview는 `PREVIEW_NO_DEVICE_CONNECTION`, V0/D1/D3, device_connections0/physical_commands0이다. 실제 native 모듈의 lazy import도 장치 없이 확인했다. 현재 Docker 이미지의 존재·ID만 조회했으며 새 container 관측·실제 ROS 연결·카메라·로봇 이동·그리퍼·외부 C API·DB는 실행하지 않았다. 별도 lint/type checker는 미구성이다.
- [실행 가이드 1~3단계](D_ROUND3_SERVICE_INTEGRATION_RUNBOOK.md)에 preview, 현장 INITIAL 명령, 결과 파일과 다음 승인 Step 전달 방법을 추가했다. 다음 현장 작업은 무동작 preview 확인→교시 경로/빈 그리퍼/배치 확인→INITIAL 한 번이다. 실제 8블록 Current·HOME·제어권 해제 후 300초 이내 기존 C 승인/A 첫 Step 경로를 진행한다. 이후 실제 B STEP/FINAL·연속 실행·사용자 저장은 후속 작은 작업이다. commit/push/PR/merge는 수행하지 않았다.

## 2026-10-15 Round3 순서별 실행·최종 통합 안내 (이전 문서 작업 시점)

- 현재 `codex/integration-round3` HEAD `93ef967`, 작업 시작 시 clean을 확인했다. 이전 서비스 연결 및 portable 프로파일 패키징이 이 커밋에 포함돼 있다. 이 문서 작업은 실행 코드·교시·프로파일 수치를 변경하지 않는다.
- [최종 통합 실행 가이드](D_ROUND3_SERVICE_INTEGRATION_RUNBOOK.md)를 추가했다. 0단계 무동작 검사→INITIAL 실행기 연결→실제 초기 관측→C 승인/A/D 한 Step→B STEP와 연속 실행→나머지 대상·중간 변경→FINAL→사용자 저장→전체 인수의 순서와 통과/보류 기준을 기록했다. 한 단계의 증거를 확인한 뒤 다음 조작을 안내한다.
- 첫 명령 `organize_supply_profile.py validate`는 `PYTHONPATH=.:perception`이 필요하다. 처음 경로를 생략한 실행은 `supply_vision` import 실패, 위 경로로 25슬롯/20 RGB-D/5교시 검사 통과. portable native 전체 preview도 3개 case/physical_commands0 통과. validate는 기존 validation.json을 기록하며 실제 장치에 연결하지 않는다.
- #55는 현재 OPEN, round2 대상, SHA `04a382157b60a7697c0c4570478bda37211e5e1c`로 재확인했다. round3의 INITIAL 실물 실행기는 아직 없고, 기존 `c2_integration_round2`의 CameraRealTrial/DockerBObserver/InspectionMotion 등은 이식 검토 후보로만 표시했다. 기존 round2 `one` 시험을 사전 8블록 위에 실행하도록 안내하지 않았다. 다음 개발 목표는 조립 없이 INITIAL 저장·HOME 복귀·writer 해제를 확인하는 실행기다.
- 실제 INITIAL/로봇/카메라/DB/외부 C API 실행은 하지 않았다. 문서 링크·코드 블록·입력/출력·Git diff를 검사하며 소프트웨어 검사를 실물 검증으로 표시하지 않는다. commit/push/PR/merge는 이번 작업 범위에 포함하지 않는다.

## 2026-10-15 — 공급판 RGB-D 중심 → 로봇 XY 보정 연결

- 요청 범위: OpenCV 스터드 중심과 정렬 Depth를 로봇 Base 좌표로 변환하고, 교시 당시 기준 표면 중심과의 상대 변위 XY만 파지 목표에 반영한다. Z/회전/힘/속도/기존 T1·full-real 기본 동작과 B 상태 소유는 유지한다.
- 새 `app/supply_stud/depth_center.py`와 `LiveVision` 연결에 RGB/정렬 Depth/CameraInfo 수신·시각/해상도/frame 검사·블록 내부 깊이 패치·CameraInfo 역투영·TCP–카메라 변환·슬롯/교시 기준 바인딩·변위/높이/교시 범위·정지/자세/이동 직전 유효시간 검사를 추가했다. 1280×720→640×360+상하60 여백 처리 후 검출 좌표를 원본으로 역변환하며 Depth 자체는 원본 좌표에서 읽는다.
- 명시한 `vision.depth_center_profile` 또는 native/독립 공급판 CLI의 `--supply-depth-profile`만 활성화한다. 활성 경로에서 누락·인식 실패·자료 만료·보정 범위 초과는 파지 전 중단하며 교시 위치로 조용히 대체하지 않는다. 실제 프로파일은 합성 replay에서 거부한다. 기존 기본 설정·교시·보정 원자료는 바꾸지 않았다.
- 실제 검증: native 관련 7파일 **156 passed, 종료0(2.05초)**, 기존 HMI T1 **10 passed, 종료0(0.59초)**. RGB-D 합성 정상/실패, 1280 역변환, 회전된 카메라 좌표, receiver→목표→가상 파지, 보정 필수 경로의 fallback 차단·만료·자세 변경, 미검증 프로파일의 장치 접근 전 차단을 포함한다. compileall·diff 공백·템플릿 JSON·문서 링크 검사 통과. 별도 lint/type check는 미구성이다. 최초 native pytest는 공유 perception 경로 누락으로 수집 실패했고 `PYTHONPATH="$PWD:$PWD/../perception"` 지정 후 위 전체 native 검사를 실행했다.
- BLOCKER: 실제 공급판용 카메라–TCP 보정과 교시 기준 표면 중심·1280 변환 영상의 슬롯 영역 검증이 없다. 기존 PROVISIONAL/표시용 보정으로 대체하지 않았고 템플릿은 미검증·실행 불가다. REQUIRED CHANGE: 로봇 PC의 실측 자료로 별도 프로파일/layout을 준비하고 정지 관측→중심 좌표→제한된 실물 파지 순서로 검증. AFFECTED INTERFACE: D 내부 선택적 공급판 RGB-D 입력/XY 보정이며 공통 ABCD 계약은 변경하지 않는다. REASON: 픽셀/표면 위치와 실제 TCP 파지 위치는 동일하지 않다.
- 실제 Robot/ROS/카메라/외부 API/DB는 실행하지 않았다. [프로파일·실행·한계 안내](D_ROUND3_SUPPLY_DEPTH_CENTER.md). 이후 사용자 요청으로 관련 코드/설정 템플릿/시험/문서와 앞선 시뮬레이션 기록을 `codex/integration-round3`에 commit/push한다. main 병합은 하지 않는다. 실측자료 폴더는 게시 대상에서 제외한다. 축소 영상 중심 검출의 정확도 한계를 문서에 명시했으며 원본 영상 직접 중심 검출은 미반영이다.

## 2026-10-15 — B·D 카메라 연계 예상 흐름의 장치 없는 시뮬레이션

- 사용자 요청으로 기존 저장 관측 ABCD·설계 변경 replay와 B의 모의 ROS 촬영/관측자/실제 연결 바인딩 검사를 재실행했다. 실행 코드·카메라 연결 구조는 변경하지 않았다.
- 검증: `tests/integration/test_round3_abcd_saved_observations.py`, `test_round3_design_change_replay.py`, `perception/perception_mvp/tests/test_ros_inspection_capture.py`, `test_camera_inspection_observer.py`, `test_real_connection.py` 총 **74 passed, 종료 0, 116.36초**. 실행 자료는 `/tmp/round3-camera-flow-20261015`에 임시 보관한다.
- 정상 두 Step은 각각 D 가상 실행 후 B MATCH를 거쳐 진행하고 별도 FINAL MATCH를 확인했다. 불일치/관측 불가/자료 누락 보류, C 승인 뒤 남은 블록 재계획, STOP·늦은 결과 차단을 확인했다. B 촬영의 오래된 영상/이동 중/취소 조건은 모의 ROS로 확인했다.
- 미검증: 실제 ROS 발행·B/D 동시 구독·QoS 호환·카메라 장치 충돌·OpenCV 집기 보정/yaw·실제 가압/결착·음성/DB. D 가상 실행은 합성 pickup/alignment이고 B 통합 입력은 저장 관측이다. 실제 B 촬영 경로를 HMI에 연결한 통합 시험이나 물리 시뮬레이터 실행은 아니다. 다음 작업은 실제 이동·정지/촬영 연결 및 로봇 PC의 토픽 수신 조건 확인이다.

## 2026-10-15 — 중간 설계 변경/조립 차이 → C 승인 → A 재계획 → D 가상 재개

- 사용자 요청으로 변경/차이 대응 replay를 commit하고 원격 `codex/integration-round3`에 게시한다. main은 병합하지 않는다. 기존 T1/full-real/ABCD 저장 관측의 기본 동작은 유지한다.
- `design_change_replay=true`인 합성·MOCK·offline 모드에만 사용자 설계 변경과 B 불일치 후 C 의도 대화를 허용한다. 첫 B MATCH 후에는 변경 요청을 기다리는 경계를 제공한다. 진행 중 변경 요청도 그 경계에서 처리한다.
- C의 실제 대화/검증/버전 증가/별도 승인을 호출하되 새 후보 생성은 버전·사유·Current가 일치하는 저장 후보 provider를 사용한다. optional revised_generator는 offline text에만 허용하고 일반 C 함수의 기본 동작은 유지한다.
- 새 후보 승인 전 A 재계획/추가 D 실행을 하지 않는다. 승인 후 B Current를 기준으로 새 plan_id/execution_id를 사용해 미조립 한 Step만 실행한다. Current 삭제 후보·후보/측정 누락·구버전 저장 관측은 보류한다. RESUME로 예전 파지를 반복하지 않는다.
- 첫 Step 종료 후 C 승인 대기에서 STOP 검증이 누락되던 MOCK 경계를 수정했다. 합성 정지/이전 상태/마지막 execution_id가 일치할 때만 채택한다. 실제 장치의 정지 조건은 변경하지 않았다.
- 검증: 사용자 변경/불일치 재계획·승인 전 STOP·자료 오류·provider 격리 11 passed, 기존 C 단위 118 passed, T1/통합2/통신 25 passed, 저장 관측 ABCD 12 passed, 기존 full-real 선택 5 passed(27 deselected). 실제 로봇/ROS/카메라/마이크/외부 API/DB는 실행하지 않았다.
- [시나리오·실행·로그 안내](D_ROUND3_DESIGN_CHANGE_REPLAY.md). 고정 합성 후보/관측 기반 연결 검증이며 자유 설계 생성·실제 인식·결착 성공 검증이 아니다.

## 2026-10-15 — ABCD 저장 관측 연결: D 가상 결과 → B 비교 → 다음 Step

- 사용자 요청으로 round3에 구현한 저장 관측 연결을 commit하고 원격 `codex/integration-round3`에 게시한다. main은 병합하지 않는다. T1 고정 실물 시험·full-real·통합 2단계 단독 replay를 유지한다.
- 저장 관측 설정이 있을 때 D의 한 Step 가상 결과를 B STEP 요청에 연결한다. B MATCH 후에만 완료 Step을 기록하고 A의 다음 단계 재평가/모션→D 실행으로 진행한다. 마지막 Step 이후 별도 FINAL 저장 관측 MATCH가 있어야 합성 흐름 COMPLETE가 된다.
- MISMATCH는 관측된 B Current를 채택하되 HOLD에 머물고 자동 C 재계획을 하지 않는다. UNOBSERVABLE/ERROR도 HOLD. 자료 없음·순서·대상 오류를 자동 가상 scene으로 대체하지 않는다.
- Step별 합성 측정 목록을 정확한 블록으로 선택한다. 이 모드에만 연속 MOCK 실행을 허용하고 execution_id 재사용은 막는다. D 종료 표본을 다음 A 계산의 시작 상태로 전달한다.
- B 대기 중 STOP과 늦은 결과·중복 D 종료를 처리한다. 저장 관측 순서와 다른 장면을 만들 수 있는 재개·재검사·설계 변경은 이 모드에서 차단한다. REAL은 기존 차단을 유지한다.
- 실제 C 검토/승인(최초 후보는 fixture), 실제 A 계산, 실제 B 비교, native round2 MOCK runner를 호출하는 두 Step 저장 관측 예제와 통합 검사를 추가했다. 정상, 첫째/둘째/FINAL 불일치·관측 불가, 자료 오류, B 대기 중 STOP을 검증했다. 기존 T1/통합2/통신 25 passed, full-real 선택 5 passed, 27 deselected.
- 실제 로봇/ROS/카메라/음성 API/DB 미실행. 저장 관측·정렬·반력은 합성이며 실제 인식·결착·물리적 완성 판정이 아니다. [실행과 로그 안내](D_ROUND3_ABCD_SAVED_REPLAY.md).

## 2026-10-15 — 통합 2단계: 실제 A 한 Step → round2 MOCK 연결

- 로컬 `codex/integration-round3`에서 작업. 기존 T1 고정 실물 시험과 full-real 실행은 유지한다. 사용자 요청으로 이번 변경을 commit하고 원격 `codex/integration-round3`에 게시한다. main 병합은 하지 않는다.
- `app.mvp_integration --round3-step-replay <합성 JSON>`에서 실제 A whole/assess/motion 결과를 기존 EXECUTE 채널로 전달하고 새 MOCK 전용 연결이 `prepare_round2_step/run_round2_step` 및 기존 제어 세션/runner를 호출한다.
- 지원 범위는 필요한 패드 자료가 있는 무도움 로봇 놓기·누르기 한 Step이다. 패드/provider 누락·블록 불일치는 이동 전 보류. REAL/RESUME/두 번째 실행 차단. 실제 OpenCV/yaw/접촉 대신 명시적 합성 provider와 StepReplayDriver를 사용한다.
- 결과는 HMI HOLD. 가상 파지 성공의 슬롯 소비 외에 B Current·단계 완료·최종 저장은 갱신하지 않는다. STOP은 세션 취소와 가상 정지를 수행하며 이후 명령·늦은 성공 채택을 막는다.
- 검증: 실제 A→native stdio 정상·자료 누락·STOP·REAL 차단과 기존 T1/통신 검사 25 passed. 관련 native round2/정렬/원본 RELEASE_PRESS 회귀 121 passed, 1388 deselected. 구문/diff 검사 통과. 기존 full-real UI/실행 문서 선택 검사 5 passed, 27 deselected.
- 실제 장치·ROS·카메라·음성 API·DB 미실행. 합성 입력은 교시/보정/힘의 실물 증거가 아니다. [구조·실행·미검증 범위](D_ROUND3_A_STEP_REPLAY.md).

## 2026-10-15 — Round3 HMI → T1 고정 로봇 시험 연결

- 기준: 원격 `codex/integration-round2`의 `5652b694`; 로컬 `codex/integration-round3` 생성. 기존 미추적 실측자료는 변경하지 않았다. commit/push/PR은 수행하지 않았다.
- `full-real --round3-fixed-step`에서 HMI 로그인(기존 DB 설정 시)·준비 확인·시작 버튼 → 기존 round2 현장 시험의 T1 단독 실행 → 종료 결과·기록 경로 표시를 연결했다. native CLI에 `--only-step T1`을 추가했으며 T2/T3는 실행하지 않는다.
- OpenCV 공급 검출/선택적 XY 보정, 영상 yaw 자동 조정, 윗면 반력45N 누르기는 기존 현장 시험 함수를 재사용한다. 보정 자료 미검증 시 교시 좌표 유지, 실제 모서리 지정/팝업 조작과 기존 삽입·힘·정지 조건을 유지한다.
- STOP/창 종료는 기존 시험 프로세스의 SIGINT→driver.stop/정리를 사용한다. 강제 kill·자동 재개 없음. 프로세스 종료를 실제 정지 검증으로 표시하지 않는다.
- 시험 종료 후 HOLD이며 B Current·최종 조립 완료·저장은 갱신하지 않는다. C 음성 설계와 A의 임의 Step을 새 제어에 연결하는 작업은 후속 범위다. 설명/실행 방법: [고정 HMI 안내](D_ROUND3_FIXED_HMI.md).
- 검증: 새 HMI/프로세스/중단/결과 검증 및 단일 T1 합성 재생, 기존 공급 좌표·선택한 기존 HMI/프로세스 회귀 검사 43 passed, 16 deselected(기존 실패 포함 전체 검사 결과는 아래 별도 기록). 관련 native round2/정렬/공급 검사 120 passed, 1389 deselected. 합성 T1 재생은 physical_commands=0, image_yaw_replayed=false이며 실제 yaw/접촉 물리 검증이 아니다.
- 기존 full-real adapter + robot process 검사: 33 passed, 5 failed. 실패5건은 수정 전 두 HMI 모듈을 원격 round2 원본으로 로드한 비교에서도 동일 재현됐다(비교 선택 6건 중 5 failed, 1 passed). 테스트 설계가 현재 C의 최소 지지 규칙을 위반해 INVALID_INPUT으로 거부됨. 기존 실패를 숨기거나 테스트/규칙을 완화하지 않았다.
- 미검증: 실제 Robot/ROS/Camera/음성 API/DB 로그인·실물 정지·결착·현장 팝업 조작. 자동 CI/lint/type 도구는 추가하지 않았다.

## 2026-10-14 — B INITIAL 관측을 V0 단독으로 변경

- INITIAL 생산자의 관측 순서와 사이클 순서 검증을 V0 단독으로 변경했다. STEP·FINAL은 V0→D1→D3를 유지한다. 관측 근거가 부족한 INITIAL 보류, 기존 보정·Depth/Grid·Current/revision·STOP/취소 조건은 유지한다. D 파일은 변경하지 않았다.
- 검증: `PYTHONPATH=.:perception python3 -m pytest -q perception/perception_mvp/tests` → 484 passed, 1 skipped(PR22 소비자 코드 미제공), 종료 0. V0 단독 INITIAL 촬영·전달·저장과 근거 부족 보류, STEP·FINAL 단독 관측 거절을 확인했다. 실제 통합 PC·로봇 이동 재시험과 Git 게시는 미실행이다.
## 2026-10-14 — A 놓기·가압 판단을 조립 방식 분류로 축소

- 사용자 최종 확인: A는 기존 그리퍼 접근 불가 + 바로 아래층 밑면 결합점 전체 존재일 때 놓기·가압 방식이 필요하다고 반환한다. D가 실측 파지·TCP·해제 높이·개방/후퇴/닫기/가압·실제 운반 경로를 담당한다. 원본 ZIP·교시·이전 검토 기록은 보존한다.
- 전체 계획과 Step 재평가에 `mode=ROBOT_GRIP, assembly_strategy=RELEASE_PRESS`를 추가했다. 기존 접근 가능은 일반 조립, 부분 지지의 접근 불가는 사람 조립이며 아래 블록 HOLD/PRESS 정책은 유지한다. 기존 사람 조립 선택도 새 정책으로 재평가한다. full-support 배치를 그리퍼 막힘만으로 순서 불가라고 가지치기하지 않는다. 부분 지지만 가능한 Design의 기존 순서 불가 증명은 유지한다.
- D 인계 자료: 일반 로봇·RELEASE_PRESS·부분 지지 사람 조립·HOLD·PRESS_AND_HOLD·RELEASE_PRESS/HOLD의 6사례를 실제 A 함수로 생성했다. `planning_trial/fixtures/round2_strategy.examples.json`에 사례별 3 API의 전체 request/result를 생략 없이 저장하고, generator와 계약/참조/재계산 검사를 추가했다. 예시는 검토용 SYNTHETIC이며 실제 D 교시나 C 승인 Design이 아니다.
- AFFECTED INTERFACE: 계산 초안 0.5.2의 새 Action 필드와 gripper.release_strategy=RELEASE_PRESS. 기존 mode 두 분류를 유지한다. 일반 삽입용 StepMotion은 해당 분류를 UNSUPPORTED_METHOD로 반환하며 놓기·가압 경로를 생성하지 않는다. [반환/소비 계약](A_ROUND2_RELEASE_PRESS_CANDIDATE_20261014.md). D/HMI 소비자 연결은 미구현이며 0.5.1 소비자의 버전/전략 해석을 맞춰야 한다.
- 수현 첨부의 원래 파랑2×3 (13,11,L2) 배치는 6/6점 지지 + 접근 불가로 RELEASE_PRESS/NONE을 반환한다. 변경된 시험 배치는 일반 ROBOT_GRIP/NONE이다. 실측15mm·해제 높이 프로파일 없이 JSON 입력을 재계산했으며 첨부 코드는 실행하지 않았다. 모든 execution_allowed=false, B Current/revision/완료 책임 유지.
- 실제 검증: A planning_trial + Workflow/PR30 전달 검사 **544 passed, failures/errors/skipped 0, 종료0**. 추가 D 모의 통합은 **28 passed / 8 failed**, 변경 전 b0d22e5에서 해당 8개를 재현해 실패 node ID와 원인이 동일함을 확인했다(기존 C 최소4점 규칙에 부적합한 2~3점 지지 fixture, 새 실패0). 통합 전체 PASS로 표시하지 않는다. 새 분류/전체 인계 예시 30검사 포함, API 예제 실행 34/34 PASS, AST 11파일·fixture JSON·git diff --check 확인. JUnit/첨부 배치 재계산은 reports에 로컬 보관한다. 실제 Robot/ROS/Camera/MoveIt/외부 API/DB 실행, D 실제 전략 소비, 실물 결착 품질은 미검증. [PR #50](https://github.com/suuuhululu/C-2/pull/50)을 gimseeun 계정으로 `codex/integration-round2` 대상으로 게시했다. 최신 대상 cf8031d를 feature branch에 합쳐 STATUS 충돌의 양쪽 기록을 보존했고, A/Workflow 검사는 다시 544 passed다. PR 병합·D 실제 연결은 별도다.


## 2026-10-14 — B 비전: 층 기준·허용 오차·V0/D1·D3 역할 분리 (`work/hongdong-vision-round1-v2`)

- 변경(B-only, perception/): 층 기준을 측정 윗면 평면 + 스터드 4mm(TOP_PLANE_PLUS_STUD)로 변경했다. 층 허용 오차는 ±2.5mm→±5mm(층 간격 18.625mm, 2×허용<간격 유지), 깊이 범위 min_depth는 V0 0.441·D1 0.332·D3 0.395로 2mm 낮췄다(캘리브레이션 무변경).
- UNKNOWN은 후보 단위로 처리한다. 후보 하나가 실패해도 그 후보만 제외하고 시점 전체를 무효화하지 않는다. V0의 UNKNOWN은 MATCH를 막고(비교는 UNOBSERVABLE), D1/D3의 UNKNOWN은 막지 않는다.
- 역할 분리(view_roles.py): 층·블록·점유 footprint는 V0만 결정하고, D1/D3는 빈 칸 증거와 같은 층 교차 확인만 담당한다. opencv_live의 윗면 선택을 보강했다.
- 테스트: `cd perception && python -m pytest perception_mvp/tests` 450 passed, 1 skipped(합성 데이터 단위 테스트). 새 테스트 7파일, 기존 테스트의 옛 import(rgbd_io, saved_perception) 수정, perception/conftest.py 추가(저장소 루트를 경로에 추가, 백엔드 파일 무변경).
- 미검증: 실제 YOLO·카메라·로봇, D/A/C 연동, 공급 비전. D1/D3 윗면 선택은 저장 촬영본에서 아직 실패하며 층은 V0만 사용한다. D가 UNOBSERVABLE을 받았을 때의 동작은 확인하지 못했다.
- 추가(2026-10-14, 실카메라 V0 시험 뒤): 1층은 측정 윗면 6~25mm(2~5층 ±5mm 유지, 규칙은 depth_grid.py `layer_band_index` 한 곳). V0 실측에서 판이 보정 기준보다 약 5mm 낮게 읽혀(−4.5~−5.3mm) 1층이 L?로 나와, 캡처마다 판 평면을 맞춰 높이를 보정한다(`board_baseline`, depth_grid.py). 평면이 불안하면(점 부족·기울기 3° 초과·편차 5mm 초과·보정 15mm 초과) 보정하지 않고 UNKNOWN이다. 쌓은 블럭은 첫 윗면 선택이 `top_surface_not_board_parallel`로 실패할 때만 영역을 3/5/7/9px 줄여 재시도한다(최소 점 150개, 2x1은 75개). 첫 시도에 성공하던 블럭 결과는 같다.
- 실카메라 V0 저장 캡처를 실제 YOLO 모델로 재생: 1층 노랑·파랑 L1(20.4/20.8mm), 파랑 2x2 2층 L2(40.2mm, 위치·층 사용자 확인). 빨강 2x1 2층은 윗면 점이 53개뿐이라 L?(같은 장면에서 프레임마다 판정이 달라 6장 중 1장 통과). 여러 프레임 중앙값은 시험했으나 효과가 불분명해 도입하지 않았다. 팀 통합·D/A/C 연결 시험은 아니다.
- 추가 미검증·한계: 중심부 재시도 기준값은 캡처 한 장에서 정한 시험값이고 단위 테스트가 없다. 바닥 보정은 판 위 블럭이 많이 덮으면(약 40%) 평면이 약 1.5mm 끌릴 수 있는 시험 방법이다. README와 docs 두 문서에 현재 ±5mm·1층 6~25mm를 반영했다(과거 재생 기록 본문은 유지).
- 팀장 확인 필요(추가): 1층 6~25mm, 보드 바닥 보정 방식.
- 팀장 확인 필요: V0만 층 결정, D1/D3 UNKNOWN 비차단, 허용 오차 ±5mm, 윗면 선택 완화.

## 2026-10-13 — 3D 오버레이 가독성 조정

- 사용자 실카메라 피드백으로 면 기본 불투명도 15%→8%(배경 92%), Expected의 3픽셀 초록 경계선을 모든 면 1픽셀로 변경했다. 블록 면 색상과 상태 비교 로직은 유지한다. 표시 관련 회귀 36 passed, 종료 0; 대상 diff --check 통과. 실제 화면 가독성은 재실행 후 사용자 확인 필요. Git 게시/장치 명령 없음.

## 2026-10-13 — 3D 오버레이 면에 블록 색상 적용

- 관련 visualization/live-overlay/round1 검사 59 passed, 1 skipped(D 소비자 경로 미제공), 종료 0. 대상 diff --check 통과. 실제 카메라 화면 색 확인은 재실행 후 필요.

- 사용자 요청으로 visualization의 반투명 입체 면·스터드 색을 각 블록의 color(yellow/blue/red)로 변경했다. Expected는 설계 색, Current/이전 상태는 실제 확정 색을 유지한다. 비교 상태는 기존 분홍/초록 경계·굵기·범례로 구분한다. 공통 비교/Observed·D 코드는 변경 없음. 15% 불투명도와 투영 조건 유지.
- 세 색 면 색상과 실제 파랑/목표 노랑 불일치 보존 회귀를 추가. 실제 RGB 테스트의 합성 상태는 기존 노랑 예시이며 실제 Design 생산자 입력으로 대체돼야 설계별 색을 표시한다. 실기 검증/목표 색으로 실제 관측 보정/로봇 명령/Git 게시 없음.

## 2026-10-13 — 실제 ROS 영상 3D 오버레이 단독 시험 모드

- 첫 신규 검사에서 3개 높이만 준 fixture가 기존 투영의 4/5층 형식과 맞지 않아 1 failed/54 passed. helper도 4/5개 기준을 명시하도록 수정하고 fixture를 해당 형식으로 정정한 뒤 재검사했다. 기존 투영 조건은 완화하지 않았다.

- live_view에 --live-overlay-test를 추가. 실제 /camera/color/image_raw·RGB CameraInfo와 선택 View 보정으로 시험용 2×2 1~3층 상태를 투영한다. 모델 추론·B Current 확정·Observed/Robot 출력·c 저장은 비활성이다. 상태는 SYNTHETIC, 높이는 기존 시험 설정임을 화면에 표시한다. 실제 정지 s 뒤 b=비교 전/a=합성 확정 후로 auto 모드 전환을 확인한다. m/관측점 전환은 숨김·시험 단계 초기화, 실제 Robot 이동 명령 없음.
- 실제 RGB 해상도/내부 파라미터·왜곡·수신 최신성을 검사하며 기준면은 기존 stud plane에서 평평한 보드면으로 4mm 변환한다. 이는 시험 투영이며 실제 Depth 높이/좌표 정확도 통과를 뜻하지 않는다. 기존 외부 작업 변경은 보존.
- 관련 live-overlay/live-view/visualization 검사 55 passed, 종료 0; 대상 diff --check 통과. 실제 카메라 창은 사용자의 재실행 후 확인 필요. Git 게시/장치 이동 없음.

## 2026-10-13 — 팀 production 좌표 경로 RGB외곽으로 통일

- DIRECT_STUD_TOP의 measure_candidate에 실제RGB 전달, 기존rgb_top_quad 공간근거검사를사용하고 CameraInfo ray→측정높이평면→보드XY로변환. process_saved가원본RGB를전달. RGB누락UNKNOWN, Depth-only자동fallback금지. legacy계산은명시기존입력만유지. 다른팀/원자료/index보존.
- 신규정상좌표·층/스터드중복가산없음/RGB누락보류회귀포함 관련22검사통과, 종료0. 실제V0 3층기록 원본RGB/Depth/26s production시험은height_not_in_measured_layer UNKNOWN, 종료0. broader검사47통과·1실패는기존test_runtime의saved_perception import부재이며숨기거나제외수정하지않았다. 실제D/장치연결미검증.

## 2026-10-13 — RGB외곽/Depth높이 공간근거 분리

- 사용자 승인으로 외곽내부Depth밀도55%를최소50점/4구역각12점/양축분포50%시험검사로대체. production DIRECT_TOP도같은함수적용, 기존마스크/포함/기하/층조건유지. 편중/중앙/가림/부족거부회귀추가. 다른팀/원자료/index유지.
- 실제6장 재생 종료0: 1개grid[9,13]·H54.775mm 출력, layer 미확정(3층 기준과4.475mm 차이). 나머지13개 평면/Depth 보류. 좌표GT/실기/D 연결 미검증. spatial_top 결과 보존. 추가 회전/가림 회귀 포함 관련60검사 통과, 종료0.

## 2026-10-13 — 외곽 실패 조건 확인(판정 변경 전)

- 기존converged_top 결과/코드검토: V0 통과plane의RGB4점후보는존재, 마스크85%/점포함80%통과, 내부37.58%로55%조건실패. 직접스터드점의면적점유와전체RGB외곽검사의의미차이확인. 실제스터드GT판별은미검증.
- 판정조건변경은하지않음. RGB외곽/Depth높이증거분리와새공간근거검사적용방향확인필요. 문서diff검사, 새모델/장치시험없음. 다른팀/원자료/index유지.

## 2026-10-13 — 직접 윗면 평면 수렴 개선

- 3회 제한을 최대20회 수렴 검사로 교체, 판정 임계값 유지. 관련39검사 통과, 실제6장재생 종료0. V0 3층기록1개는17회에윗면추출통과했으나 외곽보류, 평면11/Depth2/외곽1보류·좌표층확정0개. 원자료/다른팀/기준/index 보존. 실제 성공으로보고하지 않음. converged_top 결과보존.

## 2026-10-13 — 직접 윗면 Depth 실패 수치 확인

- 사용자 선택으로 DIRECT_STUD_TOP 유지. top_surface_points에 중간 평면 후보 지지/높이/기울기 진단 추가, 반환값/판정조건 유지. 관련38검사 통과·실제6장재생 종료0. 확정0개 유지.
- 후보지지 대부분7.5~24.6%로25% 미달, 일부V0 중간후보25.3/37.5%도 최종평면 조건 실패. 중간높이를 정상으로 반환하지 않는다. 결과 direct_top_diagnostics에 보존, 원자료/다른팀/index 변경 없음. 보정자세/실측Depth확인 미완료.

## 2026-10-13 — 윗면 높이 직접 측정으로 기본 방식 통일

- 사용자 승인으로 DIRECT_STUD_TOP 설정, live/replay/production에서 측정 top에 블록4mm 가산 제거. 두면 분리 필수조건 제거, 지지된 최고 평면 선택·단일 outlier 거부. 보드datum/층 기준·원자료/D 코드/index는 유지. 기존 명시 BODY 방식은 호환 경로다.
- 실제6장14검출 재생 종료0이나 좌표·층 확정0개: 평면/Depth 지지 검사가 계속 보류. DIRECT_TOP_REFINED 결과를 이전결과와 구분. 방식전환을 정확도 해결/팀 전체 시험 성공으로 보고하지 않는다. 장치GT·보정 반복성 미검증.

## 2026-10-13 — 저장 RGB-D 외곽 후보 보완·재시험

- B opencv_live의 RGB contour에 convex hull 후보를 추가하고 작은 외곽 notch/부족한 Depth 거부 검사를 추가. 원본/임계값/다른 팀 파일/Git index 유지. 최초 tuple/list 오류 수정 후 관련51검사 통과(종료0).
- 실제6장/14검출 재생 종료0, 표면 분리4개·좌표/층 확정0개로 기존 대비 실영상 개선 없음. convex_outline_fixed 결과와 오류 실행 기록을 구분 보존. 외곽 지지 부족 및 표면 분리10개 실패가 계속되어 정확도 완료로 보고하지 않는다. 자세 반복성·보드 기준면 실물 확인이 필요하며 임의 보정/기준 완화는 하지 않았다.

## 2026-10-13 — 팀 전체 실물 시험용 B 실제 ROS 연결 진입점

- connect_real_inspection으로 실제 ROS capture_inspection_view→make_inspection_observer→기존 비동기 B 판정/결과 큐를 결선했다. Controller 정지/pose/활성/연속성 callback은 실제 주입 필수. 표본 fallback·로봇 명령·D 파일 수정 없음. 실제 모델 파일/보정 ID 확인, 기존 자동 촬영/사이클 저장 경로 유지.
- 관련 real_connection/camera_observer/ros_capture/team_connection/round1 검사 63 passed·1 skipped, 종료0. 실제 장치 미연결·D 주입/소유 스레드 전달은 현장 확인 필요. ROUND1_REAL_HANDOFF.md에 실제 호출과 완료 기준 전달. 실제 좌표·층 0개 병목은 해결됐다고 보고하지 않는다. Git 게시 없음.

## 2026-10-13 — B 1차 표본 연결 시험 우선 준비

- 실제 영상 정확도 개선은 후속으로 분리. 명시적 SYNTHETIC_NOT_CAMERA 표본 observer를 D의 기존 connect_inspection에 주입할 수 있게 추가하고 ROUND1_SAMPLE_QUICKSTART.md에 실행·큐·Plan·취소 연결 방법을 기록했다. 자동 Camera fallback, D 파일 변경, Git 게시 없음.
- 실제 재생 7 checks PASS, 관련 replay/team_connection/round1 검사 35 passed·1 skipped, 종료0. 전체 검사 시 365 passed·1 skipped·1 failed: 기존 legacy saved_perception의 패키지 import 경로 충돌(test_runtime)이 남아 있으며 전체 통과로 보고하지 않는다. 최초 전체 실행의 수집 오류도 경로 문제였으며 관련 범위 명령을 안내했다.
- 실제 Camera/Robot 미연결. 좌표·층 확정/실제 D 대기·STOP·큐 수신 공동 시험은 미검증. 표본 통과를 실물 성공으로 취급하지 않는다.

## 2026-10-12 — B 보조 클래스 투표 코드·사이클 연결

- class_vote.py에 metric 중심/높이 기반 보수적 연결, View당 1표, 유효 CANDIDATE 표·UNKNOWN 기권, 2대1/일치/단일표 채택, 동률·모호성·기하 충돌 보류 및 근거 로그 구현. Losing View 검출을 winner 검출로 조작하지 않는다. 기존 빈 영역 충돌 검사 유지.
- main.observe_cycle→build_observed→merge_views에 선택적 class_vote_policy 연결. 공통 Observed 여섯 필드, D 코드, 기존 Current/revision/아래층/취소 정책 유지. 사용자 미커밋 변경은 보존했다.
- 실제 연결 허용오차 미채택으로 기본 실행은 기존 판정 유지. 단순 layer UNKNOWN이지만 클래스 유효인 별도 후보 생산, live_view 최종 투표 표시·replay 경로 적용 및 저장 GT 성능 비교는 미완료. 이를 운영 활성화/정확도 개선 완료로 보고하지 않는다. 상세: perception/docs/AUXILIARY_CLASS_VOTE.md.
- 신규 합성 검사 6개 포함 MVP 전체 276 passed, 1 skipped(D 소비자 경로 미설정), 종료 0. 동일 묶음·부분 View·기권·동률·충돌·연쇄 모호성 검사. 관련 diff --check 통과. 실물/장치 시험 및 Git 게시 없음.

## 2026-10-12 — 3D 비교 모드 자동 전환

- 검증: 최초 회귀 4 failed/266 passed/1 skipped는 auto 단계 검사보다 기존 숨김 사유 검사가 먼저 처리돼야 하는 문제였다. 검사 순서를 수정하고 재실행: 270 passed, 1 skipped(D 수신부 경로 미제공), 종료 0. 대상 diff --check 통과. 실제 장치/팀 화면 검증은 미수행.

- connect_inspection에 선택 display_sink를 연결하고 요청 OBSERVING/확정 CONFIRMED/미확인 UNOBSERVABLE 상태를 제공. 화면 auto 기본 모드는 관측 시 Current/Expected, MATCH/MISMATCH 확정 후 이전/현재 Current, 미확인에는 목표 비교 유지로 동작한다. 새 요청/계획·취소·오류·종료에서 sink에 None 전달. D wire/Observed 변경 없음.
- 실제 화면 소유 스레드 enqueue·비교 RGB/projection 결선은 별도 필요. STOP/이동·손·frame/View 검사는 기존 표시 함수가 유지하며 Robot 권한을 생성하지 않는다. 현재 실측 높이 미확정 문제는 이 변경으로 해결됐다고 표시하지 않는다. Git 게시/장치 명령 없음.

## 2026-10-12 — 비교 구간 3D 상태 표시 연결

- B inspection은 비교 전 Current를 내부 결과에 보존하고 connection은 읽기 전용 comparison_display_state로 이전/현재 Current·Expected·검사 문맥을 제공. 공통 Observed와 D wire 봉투는 유지. 새 검사/계획·취소·종료·처리 오류는 이전 표시를 무효화한다.
- visualization에 target/changes 모드를 추가하고 live_view의 선택 comparison-overlay 입력으로 호출. 실제 비교 frame/View·정지·V0 손 조건·평평한 보드 높이 기준·유효 projection을 요구하며 누락/불일치는 숨김. 15% 3D 안내이며 현재/예상과 이전/현재 상태 범례를 구분한다.
- 신규 검사 포함 B MVP 265 passed, 1 skipped(D 소비자 미지정), 종료 0. 실제 팀 화면 생산자/비교 RGB·보드 평면 기준 변환/층 높이·D 연결은 여전히 필요. 기존 명령만으로 자동 표시 완료라 주장하지 않는다. 기존 사용자 미커밋 변경 보존, D 코드·장치 명령·Git 게시 없음.
## 2026-10-13 — C Robot-only design rule: support min(4, studs)·사용자 제약 우선·Current 충돌 HRI (`work/siyul-c-robot-rule`, base ebeeef2)

- 변경(C-only, A/B/D production 무변경): `app/c_design/validator.py` support hard rule을 "바로 아래 한 층과 고유 stud ≥ min(4, 블록 stud 수)"(2x2x1 4/4·2x3x1 ≥4/6·1x2x1 2/2, 중복 금지, layer 1 제외)로 강화하고 `validate_design`·`validate_revised`·`current_support_violations`가 같은 함수를 쓰므로 Initial·Revised·Difference REVISE·Direct Design Change·Review MODIFY·Planning Failure 재설계 전 경로와 입력·Current 판정에 동일 적용(production 2-stud 예외 없음). `llm.py` 규칙 줄·self-check·build hint를 블록별 규칙으로, Initial 기본 선호 문단과 Revised 우선순위(Current 보존 > 규칙 > 사용자 명시 요구 > 품질/expressive > facing)를 추가. `dialogue.py` 규칙 기반 `extract_constraints`(N층 이하·낮게·간단하게·블록 적게/N개·넓게/작게) + 해석 LLM 선택 키 `constraints`, `llm.stated_limits` 컨텍스트로 전달(기존 fake 시그니처 호환). 제한 시 `+6` 블록 하한·judge richer 재생성·5층 안내 해제, family 무작위 선택에서 키 큰 family 제외. `main.py` Current 충돌(요청 상한 < Current 최대층/블록 수, 조립 블록 제거 요구)을 생성·ACK 전에 감지해 기존 질문 루프로 1회 재선택(KEEP/REVISE(clamp)/UNCLEAR/CANCEL), Review MODIFY는 clamp+고지. `designer.py` Mock Revised가 다리 1칸 y·대각 이동에서도 4-stud bridge(72경우 10→20 성공), LLM 후보에 `user_constraint`(max_layer/max_blocks) 거부. metadata `user_constraints`·`constraint_clamp` 추가. 새 hri/status/error 값·공개 API 변경 없음.
- 테스트: 신규 `test_robot_rule_characterization.py`(Wave 1 pin → 수용 테스트), `test_user_constraints.py`(53), `test_constraint_conflict.py`(32), 72경우 Mock 표. historical Sol fixture(`tests/fixtures/c_stage3/*`, 2026-10-11, 2x3x1 3-stud 4블록)는 원본 보존·기록 검사에만 당시 기준 필터, production 되먹임은 재배치 사본. **D 소유 테스트 2건(`test_five_layer_pipeline` thirty_blocks, `test_mvp_supply_cycle` 40블록)은 합성 Design 생성식만 새 규칙에 맞게 수정**(사용자 결정, D production unchanged, synthetic test input only).
- 실제 검증(2026-10-13): C unit 1190 passed, C integration 139 passed, A planning_trial 458 passed(무변경), D 호환 13파일 121 P·82 S·22 F·11 E(실패·오류 node ID 33건이 ebeeef2 기준선과 동일, 새 실패 0), 루트 전체 40 F·16 E node ID 56건 기준선 동일(새 실패 0; passed는 신규 테스트로 증가), compileall·`git diff --check` 0. 실제 gpt-6.1-sol 텍스트 smoke 21회(scripts/c_stage3_integration_smoke.py text + 충돌 driver; 저장소 밖 출력): FAILED 0, 새 Candidate 27개 모두 validator PASS·support ≥ min(4, studs), "3층까지만" 3/3 ≤3층, Revised "3층 이하로 간단하게" 3/3 ≤3층·블록 감소·Current 보존, 무제한 4~5층·Revised 36~40블록(expressive 기본 유지), "간단하고 낮고 넓게" 3·4·4층 13~27블록, "블록 적게·작은" 17~21블록, Current 4층 + "3층 이하" 3/3 충돌 질문(REVISE→4층 clamp·보존·APPROVE / KEEP / UNCLEAR). 독립 리뷰(Opus A structural, Opus B HRI)는 `C_DESIGN_PROGRESS.md` 2026-10-13 행 참조.
- 미검증: 실제 마이크·TTS·HMI·로봇·카메라·DB, D 경유 실제 음성 E2E, 해석 LLM의 `constraints` 키 충족률, "낮게·넓게"(soft) 정량 평가.
- 다음 작업·AFFECTED INTERFACE: [C_DESIGN_ROBOT_RULE_HANDOFF.md](C_DESIGN_ROBOT_RULE_HANDOFF.md) — A 검증 기준 2 유지 안내, 공유 문서(06/09/00) 병기 제안, D의 metadata 새 키 pass-through 확인, 이전 2-stud Approved/Current 재생 시 INVALID_INPUT/escalation, 제약의 요청 단위 한계(세션 유지는 D inspection_context 합의 필요), Current 블록 수 = 상한 clamp 시 운영 문구. PR 생성·병합은 별도 요청.
## 2026-10-13 — REAL 슬롯1~5·외부 DRCF2·roboton2 후속 PR

- PR #39가 병합된 `codex/integration-round1 @ 115271e` 기준으로 현장 수정만 반영했다. full-real은 종류/색상별1→2→3→4→5→1 순환하며 빈 슬롯6 준비·실행 문서 생성·기존 문서 재개를 거부한다. 사용자 전제는1~5번 항상 보충·6번 항상 비어 있음이다. 집기 성공 확인/중복 소비 보호, MOCK/레거시 기본6슬롯, 공통 계약·기존 교시·A 좌표 모델과 PR36의40N/공급 MoveL/loaded MoveB는 유지한다.
- runtime guard는 `C2_DRIVER_ROOT`의 외부 DRCF2 경로를 읽고 실제 dsr01에 두 라이브러리가 모두 로드됐는지 검사한다. roboton2의 ms-02 고정 경로를 제거하고 C2_ROBOT_ROOT/checkout 기본 경로·Camera/RViz 옵션을 연결했다. 기존 TCP/Tool 선택 및 mode 복원 절차를 사용한다. [다른 PC 안내](D_ROBOT_TRIAL_OTHER_PC_20261013.md)를 갱신했다.
- 최신 기준의 장치/네트워크 차단 D 오프라인 **1,157 passed**, 종료0 (53.49초). 슬롯/드라이버 설정/실제 A/D 문서→MOCK/영역 보정/통합 시나리오 **66 passed**, 종료0 (247.64초). 슬롯1,2,3,4,5,1,2 예약·6번 차단·기존 재검사/재개/인계·PR39의 사람 PRESS 규칙을 함께 확인했다.

## 2026-10-13 — round2 REAL 슬롯1~5·외부 DRCF2·roboton2 후속 PR

- [round1 PR #41](https://github.com/suuuhululu/C-2/pull/41)의 변경을 PR #40이 병합된 `codex/integration-round2 @ 8818518`에 적용했다. 코드 충돌은 없으며 round1 PR은 별도로 유지한다. full-real은 종류/색상별1→2→3→4→5→1 순환하며 빈 슬롯6 준비·실행 문서 생성·기존 문서 재개를 거부한다. 사용자 전제는1~5번 항상 보충·6번 항상 비어 있음이다. 집기 성공 확인/중복 소비 보호, MOCK/레거시 기본6슬롯, 공통 계약·기존 교시·A 좌표 모델과 PR36의40N/공급 MoveL/loaded MoveB는 유지한다.
- runtime guard는 `C2_DRIVER_ROOT`의 외부 DRCF2 경로를 읽고 실제 dsr01에 두 라이브러리가 모두 로드됐는지 검사한다. roboton2의 ms-02 고정 경로를 제거하고 C2_ROBOT_ROOT/checkout 기본 경로·Camera/RViz 옵션을 연결했다. 기존 TCP/Tool 선택 및 mode 복원 절차를 사용한다. [다른 PC 안내](D_ROBOT_TRIAL_OTHER_PC_20261013.md)를 갱신했다.
- round2 별도 작업 공간에서 재실행: 장치/네트워크 차단 D 오프라인 **1,157 passed**, 종료0 (54.09초). 슬롯/드라이버 설정/실제 A/D 문서→MOCK/영역 보정/통합 시나리오 **66 passed**, 종료0 (256.91초). 슬롯1,2,3,4,5,1,2 예약·6번 차단·기존 재검사/재개/인계·PR40의 사람 PRESS 규칙을 함께 확인했다.
- roboton2 기본/env 경로 해석 및 `--show-args`, Python AST·가이드 Bash13블록 문법·diff 검사 통과. PR 검증 중 실제 장치 기동/이동·카메라·외부 API·DB 연결은 수행하지 않았다. PC 전용 alias/실행 스크립트·API 키·모델·드라이버 바이너리·개인 DB 데이터는 게시 범위에서 제외했다. 실물 결착 품질과 사람이 필요한 지지/재개 판단은 별도 검증 대상이다.

## 2026-10-13 — A PRESS를 아래 블록의 두 결착 조건에 연결

- 사용자 결정: 아래 블록 L과 자기 아래층의 결착이 4점 미만이고, 이번 목표 U와 L의 결착도 4점 미만인 `HOLD` 대상이 있을 때만 중심 위치로 사람 `PRESS`를 추가 판단한다. 보드 위 1층 L은 제외한다. U의 중심이 아래층 전체 접촉점 지지 영역 밖이면 `PRESS_AND_HOLD`, 안이나 경계면 `HOLD`다. `human_press_policy=NONE`은 추가 눌러주기를 끈다.
- 기존 `contacts().weak_supports`를 재사용해 공통 A의 `human_press_assessment()`만 수정했다. 보드에 4점 결착된 1층 2×2 위에 2층 2×2가 2점 결합하는 사례와, 4점 결착된 2층 L 위의 부분 결합은 로봇 접근 가능 시 `ROBOT_GRIP/NONE`이다. 기본 최소 2점 지지·겹침·삽입·그리퍼 접근 검사는 유지한다. API 0.5.1·공통 필드·기존 PRESS enum·D 실행/제스처·교시·힘 설정은 변경하지 않았다.
- 실제 검증: 관련 pytest **548 passed / failures 0 / errors 0 / skipped 0 / 종료0**. A 전체 465개, Workflow/PR30 전달 49개, 모의 통합 34개다. 회귀 검사에서 변경 전 안정된 L의 부분 접촉 2사례에 불필요한 PRESS가 발생함을 확인했고, 변경 후 두 결착 임계값·중심 경계·다중 L 지지·눌러주기 해제 정책을 검사했다. 전체 계획→직전 재평가→이동 후보와 REAL 문서 검증→MOCK D 실행에서 해당 2×2 배치의 도움 요청 없이 Robot 결착 및 기존 도움 단계 STOP/RESUME를 확인했다.
- 재현: 저장소 루트에서 `C2_ROBOT_ROOT="$PWD/robot_control_integration" QT_QPA_PLATFORM=offscreen python3 -m pytest -q planning_trial tests/unit/test_mvp_workflow.py tests/unit/test_mvp_pr30_relay.py tests/integration/test_mvp_scenarios.py tests/integration/test_mvp_full_real_adapter.py --junitxml=reports/press-lower-attachment-tests.xml`. JUnit은 로컬 reports에 보관한다(Git 제외). 변경 Python 5개 AST 문법·README 정책 링크·git diff --check도 통과했다. lint/type 설정은 미구성이다.
- 기준 `codex/integration-round1@ebeeef2`와 `codex/integration-round2@ebeeef2`는 동일하며 두 브랜치 대상으로 각각 PR을 준비한다. 작업 브랜치는 `codex/press-lower-attachment-rule`이다. 실제 Robot·ROS·Camera·Isaac·외부 API·DB는 실행하지 않았다. 새 판단에서 Robot 결착으로 바뀌는 단계의 실물 결과는 미검증이며, PR 사람 리뷰와 통합 후 현장 재시험이 필요하다. 기존 사용자 작업 폴더와 보존 fixture는 변경하지 않았다.

## 2026-10-13 — PR #36: 공급 MoveL·결착40N·영역 보정·확인 버튼

- full-real 공급 접근은 상승→BODY_BYPASS→SUPPLY_TRANSIT→현재 Step 슬롯 상부의 단독 MoveL로 바꿨다. loaded MoveB는 유지한다. 마지막 슬롯 정렬24mm/s·12mm/s², 기존 집기·결착 하강 구조를 유지하며 이전 슬롯 복귀를 제거한다.
- Robot 결착의 XYZ 전체 반력 임계값을40N으로 적용했다. desired-force/힘 유지 명령은 없다. 조립 Grid x>11의 Base X −1mm는 기존6점/2×2 회전 보정에 한 번 합산한다. 공급 교시 원자료는 변경하지 않았다.
- 인계/도움/조립 완료/정렬 요청에 HMI 확인 버튼을 제공하고 알려진 정지 체크포인트에서 수동 재개한다. 오래된 요청·미확인 개방 명령을 반복하지 않는다. [시나리오](reviews/robot-resume-scenarios-20261013.md).
- 실제 최종 검사: D 오프라인1,139 passed·기존 외부 A 자료 수집 skip1·종료0. Workflow/Robot 프로세스/실제 A/D REAL 문서→MOCK/화면 버튼/보정179 passed·종료0. PR checkout의 공급1→6→1·화면 버튼·경계 보정24 passed·종료0. D9파일 byte 일치·앱 변경5메서드 AST 일치, 가이드 bash12블록 문법 확인. [검증 기록](reviews/robot-trial-followup-verification-20261013.json).
- [다른 PC 실행 가이드](D_ROBOT_TRIAL_OTHER_PC_20261013.md)에 브랜치 받기·환경/모델 준비·장치 없는 검사·REAL 명령·속도/힘/움직임 정보를 기록했다. DRCF2 바이너리·손 모델·API 키는 Git에 포함하지 않는다. 기존 C callback 차이/로컬 개발 브랜치·사용자 변경은 보존한다. 사용자 요청으로 [PR #36](https://github.com/suuuhululu/C-2/pull/36)을 `codex/integration-round1` 대상으로 게시했다. head는 `codex/robot-trial-fixes-20261013`이며 병합은 수행하지 않았다.
- 실제 Robot/ROS/Camera/외부 API/DB·다른 PC 설치는 미수행. MoveB/최종 MoveL의 제어기 미도달 물리 원인, 새40N의 완전 결착/미끄러짐은 현장 재검증 대상이다. 기존 프로세스의 실시간 변경·Job 복원은 제공하지 않는다. lint/type 설정은 미구성이다.

## 2026-10-13 — 손/엄지척 인식 실패의 확인 버튼·재개 점검 (로컬)

- 사용자 최종 결정: 인식이 실패하면 버튼으로 확인. full-real 화면에 인계/도움 준비/조립 완료/정렬 확인 버튼을 추가했다. 엄지척 시간 초과는 같은 요청을 유지하며 버튼을 기다린다. 현재 요청 ID에 묶인 HMI 답변이며 중복·이전 요청 클릭을 반복 실행하지 않는다. 버튼은 조립 완료 판정 또는 카메라 감지값을 위조하지 않는다.
- `HANDOVER_READINESS_LOST` 개방 전 오류는 현재 파지/정지 위치에서 인계 대기로 처리한다. 수동 정지·알려진 이동 timeout·마지막 목표 근처의 블렌딩 timeout에 재개 체크포인트를 추가했다. 인계/픽업/과거 경유점을 반복하지 않는다. 미확인 파지/개방 결과·실제 정지 미확인은 별도 상태 확인이 필요하다. [전체 시나리오 점검](reviews/robot-resume-scenarios-20261013.md).
- 최종 실제 검증: D 오프라인 1,126 passed·기존 수집 skip 1·종료0. Workflow/Robot 로컬 프로세스/실제 A/D REAL 문서→MOCK/화면 버튼 클릭 77 passed·종료0. 새 회귀는 손/엄지척 센서 확인 없이 버튼 진행, 엄지척 timeout 후 같은 요청 유지, 인계 개방 1회, 수동 재개 동일 Step·예약·픽업 반복 없음, 정지 확인/불명확한 결과 차단을 포함한다. [검증 기록](/home/ms-02/C_2/logs/handover-resume-20261013/verification.json).
- D 실제 실행 소스와 검토 checkout 6개 관련 파일은 동일하며 HMI/main·REAL 생성자/버튼·Workflow Robot 이벤트 메서드를 AST 대조했다. 기존 C callback/metadata 차이는 보존했다. 기존 lint/type 설정은 미구성이다. 실물 Robot·카메라 시험은 미수행, 실행 중인 구 창에는 실시간 적용되지 않는다. 새 commit/push/PR 없음.

## 2026-10-13 — round1 Robot 시험 경로 통합

- 최근 현장 시험의 전체힘35N 정지/정지 후 개방, 연속 운반, 완화된 정지 허용오차, 슬롯 순환/중복 소비 방지, 승인 후 수정 질문 반복 방지, 슬롯2 펌웨어 최소 반경 오류의 재현·명령 전 검사를 통합했다.
- PR #30의 C 구현은 보존하고 D에서 설계 metadata·구조화 planning_failure를 전달한다. HMI에 REAL Robot + SYNTHETIC B 시험 표시를 명시하며 기존 REAL 단일 전달/수동 시험 제한은 유지한다. A는 D가 제공한 Step 조립 자세와 빈 복귀 경로 선택만 반영한다.
- 추가 지시에 따라2×2 회전 때 Base X −1.5mm, 손바닥 인계 의미 유지, 하강 전 손 감지 시 새 인계 대기, 확인된 보류의 재개를 반영했다.
- D 오프라인1064 passed/1 skipped, 통합 앱231 passed, A/HMI 계약257 passed, 2×2 회전12 passed, 각각 종료0. 외부 A 참고 경로가 없는 레거시 검사만 건너뛰었고 실제 장치 동작은 실행하지 않았다.
- 실행 방법·교시 원자료·실물 검증 한계·2×2 회전/인계 정지 원인은 [REAL 시험 안내](D_FULL_FEATURE_REAL_TRIAL_20261012.md)에 기록했다. 실제 Robot/Camera/완성 조립 성공을 주장하지 않는다.

## 2026-10-12 — 손 모델 기본 경로 최신화

- 사용자 요청으로 perception_mvp/config.yaml의 기본 손 weights, live_view.save_hand_roi 및 supply_roi의 V0 손 ROI 설정 생성 경로, README 손 실행 예시를 models/hand_yolo11n_added_20261012/weights/best.pt로 변경했다. 기존 저장된 V0 hand_config.json은 이미 같은 경로다. 블록 모델·시험 임계값·기존 모델·사용자 미완료 변경은 보존한다.
- 최초 저장소 루트 pytest는 perception_mvp import 경로 누락으로 수집 실패(2). 올바른 perception 작업 위치에서 polygon_roi/live_view 검사 32 passed 종료0, 변경 Python 문법·git diff --check 종료0. 새 ROI 생성 경로 회귀 검사를 포함한다. 실제 카메라/손 사이클 실행·독립 성능 검증은 미수행이다.

## 2026-10-12 — V0 손 프레임 끊김 시험값 지정

- 사용자 명시 승인으로 assembly_board_roi/V0/20261012T004735740339Z/hand_config.json의 max_frame_gap_seconds를 1.0초로 설정했다. 상태는 TRIAL_VALUES_UNVALIDATED이며 확인 주기가 아닌 연속 처리 프레임 간격의 허용 한도다. 손 재진입 초기화·손 이탈 연속 3초 초과 조건·나머지 설정과 코드는 변경하지 않았다.
- JSON/적용값/exit_seconds 유지 검사와 git diff --check 종료0. 실제 CPU 처리 간격·카메라 손 재진입·끊김 시험은 미수행이며 현장 시험 후 조정한다.

## 2026-10-12 — V0 손 설정 현장 시험값 적용

- 사용자 승인으로 저장된 assembly_board_roi/V0/20261012T004735740339Z/hand_config.json에 최신 추가 학습 weights/best.pt와 confidence=0.25, min_valid_depth_fraction=0.8, stable_mean_difference=3.0, stable_seconds=1.0을 적용했다. 현장 미검증 시험값이며 실제 ROI/해상도/exit_seconds=3.0은 보존했다. 전역 설정·손 사이클 코드·사용자 미완료 변경은 변경하지 않았다.
- max_frame_gap_seconds는 실제 프레임 처리 간격 미측정으로 null을 유지한다. 이 파일로 전체 손 사이클 실행은 아직 불가하며 프레임 간격 실측·설정이 필요하다. JSON/모델 경로·적용값 및 유지값 검사 종료0, git diff --check 종료0. 실제 Camera·Depth 품질·안정성·손 사이클은 미검증이다.

## 2026-10-12 — 정지 관측 구간 수신·RGB-D 1쌍/1회 분석

- 사용자 최종 결정에 따라 integrated live_view는 이동/정지 미확인에서 영상·CameraInfo 구독 없음. 정지 시 구독 시작, 새 동기화 RGB-D 1쌍 선택 후 구독/수신 스레드를 종료하고 기존 HSV/YOLO/DepthGrid 1회 분석. 결과는 고정 표시하며 r 명시 재관측 또는 m→View 선택→s 새 정지 확인으로만 갱신한다. 이전 View 프레임·CameraInfo는 재사용하지 않는다.
- V0 정지 후 손 진입/이탈·엄격한 >3초/안정 조건은 연속 수신으로 확인. 손 조건 충족 프레임보다 새로운 RGB-D로 블록을 관측하며 진단 옵션도 손 조건을 우회하지 않는다. D1/D3는 손 추론 없음. 기존 수동 s는 정지·안정화의 로컬 확인이며 Controller 실결선/안전 승인이 아니다. raw Depth는 저장 보조로 동일 구간에 수신하며 분석에는 aligned Depth를 사용한다.
- main.py의 confirm_view→capture_view→분석 hook 경로는 기존 구조를 유지했고 실제 Controller/D 수신 구현을 추가하지 않았다. D production·모델/기하 알고리즘·다수결·층/높이 기준은 변경하지 않았다. setup/hand-detect-only 등 별도 진단 모드는 본 integrated 관측 정책과 구분한다.
- B MVP 검사 224 passed, 1 skipped(D 소비자 경로 미설정), 종료 0; py_compile 및 대상 diff --check 확인. 이동 차단·V0 새 프레임/손 필요·D1/D3 손 불필요·완료 중복 차단 검사 포함. 실제 ROS 구독 lifecycle/카메라·Robot 시연은 미검증. 저장 hand_config의 confidence/Depth 품질/안정/프레임 간격이 null인 상태라 실제 V0 자동 게이트는 보류된다. 설정을 임의 생성하지 않았다. 기존 사용자 변경·삭제 자료는 그대로 보존. Git 게시 없음.

## 2026-10-12 — ROS 수신과 통합 화면 추론 분리

- 사용자 화면의 loop 약 2~4초/수신 age 지연에 대해 live_view를 별도 SingleThreadedExecutor 수신 스레드로 변경. 잠금·최근 10개 bounded 버퍼에서 RGB/Depth/CameraInfo 스냅샷을 복사해 추론하므로 콜백과 추론이 동일 deque를 동시 순회하지 않는다. View 전환은 프레임 버퍼를 비우며 종료 시 executor/thread 정리한다.
- matched 묶음 경과시간은 처리 시각이 아닌 해당 RGB/Depth의 실제 로컬 수신 시각으로 계산. 진단 수신 age는 추론 후 최신 버퍼로 갱신한다. 50ms/250ms 기준과 Robot·손 권한은 변경하지 않음. 동일 Python torch.cuda.is_available() False; CPU 유지, 자동 CUDA fallback/의존성 변경 없음.
- B MVP 검사 216 passed, 1 skipped(D 수신부 경로 미제공), 종료 0. snapshot 불변·bounded 버퍼 신규 검사와 기존 검사 포함. py_compile 및 대상 diff --check 통과. 실제 ROS 수신/실시간 성능·카메라 timestamp 경고 원인은 재실행 후 확인 필요. D 코드 변경·Git 게시·장치 명령 없음.

## 2026-10-12 — RGB/Depth 동기화 수치 진단

- live_view에 최신 RGB와 큐 내 가장 가까운 aligned Depth header 차이(dt), RGB/Depth callback 수신 경과, 마지막 새 matched pair 경과, 처리 loop 시간을 표시/2초 주기 터미널 출력하도록 추가했다. 헤더 시각과 monotonic 시각을 직접 빼지 않는다. 기존 50ms/250ms 임계값·손/정지/Robot 권한은 변경 없음.
- 관련 표시/live_view/integrated_view 검사 47 passed, 종료 0; 대상 diff --check 통과. 현재 사용자 실행기의 실시간 수치는 재실행 후 확인해야 하며 수신 지연을 카메라 장애로 단정하지 않는다. 로컬 ROS header 진단은 별도 6초 제한 실행; 실제 사용자 ROS 환경과 다를 수 있다. 기존 사용자 변경 보존, Git 게시/장치 이동 없음.

## 2026-10-12 — 통합 화면 측정 입력 누락 구분

- live_view의 GEOMETRY 표시를 calibration_missing / aligned_depth_not_received / aligned_camera_info_not_received / rgb_depth_not_fresh_or_synchronized / stop_not_confirmed / v0_hand_gate_not_ready로 구분했다. 기존 입력 차단 의미는 유지하며 블록이 검출되지 않아도 입력 사유를 표시한다. 다른 사용자의 미커밋 수정은 보존.
- 관련 geometry_display/live_view/integrated_view 검사 45 passed, 종료 0; 대상 diff --check 통과. 로컬 ROS topic info 및 aligned Depth/CameraInfo header echo는 각각 8초 제한 동안 출력 없이 종료 124. 이는 카메라 미발행 확정이 아니며 현재 프로세스의 실제 입력은 재시작 화면에서 확인해야 한다. 장치 이동/카메라 재시작/Git 게시 없음.

## 2026-10-12 — 통합 화면 Depth/Grid 로컬 측정 표시 연결

- 기존 사용자 ROI/손 관련 미커밋 변경을 보존하고 live_view/integrated_view에 --diagnostic-geometry를 추가했다. 명시적 로컬 진단에서는 손 게이트 미설정이어도 실제 정지 확인·동기화·CameraInfo가 있을 때 기존 Depth/Grid 계산에 전달한다. 기본 경로의 손 허용 조건은 유지하며 손 상태/사이클/Robot 권한은 변경하지 않는다.
- 진단 화면은 계산된 Grid와 Board pose 기준 H:mm, 미확인 사유를 표시한다. 실측 층 기준이 없는 경우 layer는 미확인으로 유지한다. 기존 진단 상면 보고서가 AI polygon 미검토·기준면 미채택이므로 운영 층 설정으로 자동 채택하지 않았다.
- 신규 표시/게이트 검사 5개 포함 B MVP 검사 207 passed, 1 skipped(D 소비자 경로 미설정), 종료 0. 최초 개별 검사 명령은 없는 test_hand_cycle.py 경로로 종료 4; 전체 MVP 범위로 바로잡아 재검사했다. 대상 diff --check 통과. 실제 ROS 화면/정답 좌표·층·장치 시험은 미수행. 코드 존재를 실기 정확도 확인으로 표시하지 않는다. Git 게시 없음.

## 2026-10-12 — 세 View ROI의 통합 블록 화면 연결

- 사용자 요청으로 live_view --roi-root를 추가했다. 시작 시 V0/D1/D3 최신 저장 ROI의 목적/View/해상도/단순 다각형을 검증하고 현재 View의 ROI를 process_frame에 전달한다. HSV 후보는 ROI 내부만 사용하고 YOLO 입력 crop의 원본 RGB는 보존한다. 밖의 검출은 제외하며 경계 걸친 mask는 표시 영역만 제한하고 geometry 판정을 보류한다. 수동 View 전환 시 같은 조회 경계로 ROI가 바뀐다. 손 설정/보정/Backend·Controller 경로는 변경하지 않는다.
- 실제 검증: 저장된 세 실제 ROI 로드(각 1280×720) 종료 0, 전체 perception_mvp+legacy 219 passed, 1 skipped 종료 0, compileall/git diff --check 종료 0. ROI 밖 후보 제외·경계 geometry 차단·해상도 불일치 차단 검사를 추가했다. 실제 ROS 통합 화면은 사용자 다음 시험이다. 이 연결은 live_view 블록 진단 화면이며 팀 관측 producer 연결·손 안정화/층 기준 완성은 아니다.

## 2026-10-12 — 오목 다각형 ROI 지원

- 사용자 요청으로 supply/assembly 공통 선택기의 볼록 다각형 제한을 제거했다. 기존 hand_cycle에 공유 검증 함수를 두어 3개 이상 정수점의 오목 영역을 원형 그대로 보존하고 교차/겹침/반복점/면적 없는 영역은 저장 전에 거부한다. V0 손 감지의 볼록 교차 연산을 실제 ROI 픽셀과 손 박스의 겹침 검사로 변경해 오목하게 제외한 영역을 Depth·안정화·손 판정 모두에서 제외한다. D1/D3 손 감지 없음·기존 ROI/사용자 모델/라벨 변경은 유지한다.
- 실제 검증: perception_mvp+legacy 216 passed, 1 skipped 종료 0. 오목 6점 저장·역순 허용·교차/중복/겹침 거부·오목 제외 영역의 손/Depth/차분 제외 및 내부 손 검사를 포함한다. compileall/git diff --check 종료 0. 실행 중인 선택기는 재시작해야 새 코드가 적용된다. 실제 GUI 선택은 사용자 다음 작업이며 Robot 동작 없음.

## 2026-10-12 — B 손 사진 추가 라벨링·시험 학습 완료

- 사용자 첨부 14개 중 clipboard와 10-03-58 PNG가 픽셀 동일함을 검사해 중복 1개를 제외했다. 원본 13장 복사와 손 Detection AI 육안 박스 26개를 기존 hand_dataset/images/train·labels/train에 추가했다. 기존 16장과 합쳐 29장·손 53개이며 기존 보류 4장은 제외했다. 원본·기존 모델·기존 ZIP은 보존한다. source/SHA256/박스/중복 정보는 provenance_20261012.json, 새 라벨 미리보기는 previews/added_20261012_contact_1.jpg~4.jpg에 있다.
- CPU 첫 실행은 종료 143으로 중단(원인 미확정), batch2 재시도는 느려 담당 에이전트가 중단(130)하고 무료 Colab T4로 전환했다. 중간 폴더와 로그는 완료 모델로 취급하지 않는다. 10/10 손 best.pt 초기값으로 29장·60epoch·imgsz640·batch8·seed42·Ultralytics8.4.173 추가 학습을 완료했다. Colab 노트는 다른 변경과 저장 충돌이 표시돼 강제 덮어쓰지 않고 신규 스크립트와 학습 출력·결과를 로컬 보존했다.
- 전체 결과 ZIP 19,850,417 bytes 및 weights/best.pt·last.pt·CSV·곡선·추론 미리보기를 perception/models/hand_yolo11n_added_20261012/에 저장했다. ZIP 무결성 검사 종료0, 데이터 29쌍·정규화 박스53개 검사 종료0, 13장 새 라벨 시각 확인, 문법·diff 검사 종료0, CPU best 모델 로드 task=detect/names={0:hand}·CSV60행·새 실제 PNG 추론(손2개) 검사 종료0이다. 원본 AI 라벨은 사람 검수 미완료다.
- 최종 학습 내 평가 P=0.956/R=1.000/mAP50=0.994/mAP50-95=0.847이다. train/val 동일 29장이고 독립 평가가 아니므로 실제 정확도·일반화 개선 증거로 주장하지 않는다. 실제 V0 손 진입·이탈/3초·새 사람/조명·Backend·Robot 시험은 미수행이다. 운영 설정·안전·계약은 변경하지 않았다. 다음은 사람 라벨 검수와 별도 세션의 손 없는/가림/경계손 포함 독립 시험이다.

## 2026-10-12 — 대각 관측점 ROI 저장 구분

- 사용자 D1 ROI 요청으로 기존 선택기에 --view V0/D1/D3를 추가하고 assembly_roi.json에 View를 기록한다. V0만 hand_config.json을 생성하며 D1/D3에는 손 설정을 생성하지 않는다. 저장된 기존 데이터·로봇 제어·보정은 변경하지 않는다.
- 관련 polygon ROI 검사 3 passed 종료 0, compileall/git diff --check 종료 0. 실제 D1/D3 선택은 사용자 장치에서 수행할 단계이며 블록 추론에 대한 ROI 연결은 이번 변경에 포함하지 않는다.

## 2026-10-12 — V0 어셈블리 보드 다각형 손 ROI

- 기존 supply_roi 선택기를 --board assembly로 재사용해 별도 assembly_roi.json/hand_config.json을 저장한다. 손 감지는 다각형 내부의 Depth 유효율·영상 차분 및 손 박스와 다각형 교차를 사용하며 기존 사각형 설정 호환을 유지한다. D1/D3 손 감지 및 3초 초과 조건·로봇 제어·보정값은 변경하지 않는다. ROI 외 손 감지 임계값은 미확정 그대로다.
- 실제 검증: 전체 perception_mvp+legacy 209 passed, 1 skipped 종료 0. 신규 검사는 assembly 저장 및 사각 경계 안/다각형 밖의 손·Depth 누락·영상 변화 제외, 내부 손 검출을 포함한다. compileall/git diff --check 종료 0. 실제 ROS 선택/손 시험은 사용자 장치에서 다음 진행한다. commit/push 없음.

## 2026-10-12 — 서플라이 ROI 저장 RGB의 기존 모델 시험

- 승인된 ROI와 실제 저장 RGB에 HSV 후보→원본 RGB 후보 범위 crop→YOLO26s CPU segmentation을 적용하는 supply_test.py를 추가했다. 원본 crop 내 반사 영역은 지우지 않으며 ROI와 겹치는 검출을 표시/기록한다. 로봇 좌표/집기/EMPTY 판단/실시간 연결은 없다.
- 실제 사진 추론 종료 0: yellow_2x3 12, blue_2x3 12, red_2x1 19로 43개 검출. 실제 배치 36개와 다르며 2x2 분류 실패 및 중복/오검출이 있어 공급판 적용 정확도 통과가 아니다. 결과는 perception/recordings/supply_board_test/20261012T003652858704Z. confidence 0.25는 시험값이다.
- 기존 perception_mvp+legacy 검사 207 passed, 1 skipped 종료 0; compileall/git diff --check 종료 0. 이 검사는 새 CLI의 전체 정확도 검증을 뜻하지 않는다. 다음은 공급판 실제 RGB 라벨 검수·학습 데이터 보강 및 별도 평가다. commit/push 없음.

## 2026-10-12 — 서플라이 보드 다각형 ROI 선택

- 사용자 요청으로 supply_roi.py에 실제 ROS raw RGB 정지 화면의 모서리 클릭·취소점(u)·Enter 저장을 추가했다. 조립 보드 손 ROI와 분리하며 별도 시각 폴더에 픽셀 다각형·해상도·프레임 출처·원본/확인 이미지를 보존한다. 로봇 이동·YOLO·공통 계약 변경은 없으며 ROI의 실제 추론 연결과 robot 좌표 보정은 포함하지 않는다.
- 실제 검증: 저장 좌표/해상도·파일 생성·폴더 중복 방지·영역 밖/교차 다각형 거부 검사 종료 0, compileall 및 git diff --check 종료 0. 실제 ROS 수신·GUI 클릭은 사용자 장치에서 미검증이며 다음 단계다. 사용자 제공 Supply posx/posj는 이동 명령으로 실행하지 않았다.

## 2026-10-11 — 홍동 B 최종 MVP 발표 초안

- 사용자 요청으로 docs/presentation/B/홍동_B_최종MVP_발표준비.md에 제출 안내의 9개 항목·한 장 요약·정상/실패 예시·현재/목표 구성·B 추가 항목·대본/시연/질문을 작성했다. 원본 이미지 후보 링크와 의미를 연결하고 미선정 자료·본인 확인 항목을 표시했다. 로컬 저장 위치는 작업 편의이며 팀장 지정 위치는 Drive라는 점을 명시했다.
- 현재 HEAD 8f75e5a의 소스/설정과 활성 16mm 보정·View별 5점 최대 오차(V0 1.286/D1 1.771/D3 1.461mm, 기준 2mm), 저장 Depth 진단을 확인했다. 과거 17mm·평면 pass·Depth 진단을 최신 전체 층/물리 결착 검증으로 확대하지 않았다. 손/높이 설정 null, 블록 보드 ROI·HSV 자동 사이클·3D 실시간 결선 미확인을 구분했다.
- 실제 최신 B MVP/legacy/calibration/supply 및 로컬 DB/HMI 입력 함수 대조 247 passed, 13.48초, 종료 0. 근거/명령은 발표 폴더 evidence/test_result.md에 기록. 전체 저장소·장치·DB 적재 시험은 실행하지 않았다. 문서 링크·블록·diff를 검사했다. 코드/설정 변경·장치 이동·Git 게시·Drive 업로드/DM 없음.
- 다음: 본인 선택 이유/정답/제스처 담당 검토, 이미지 시각 QA·원본 자료 묶음, D/Controller 실제 결선·시연 설정과 독립 성능 근거 확인 후 제출.

## 2026-10-12 — C Wave 6 후속: 자연어 수용 표현 APPROVE 보강 + Full Voice HRI E2E harness (`work/siyul-c-remaining`)

- Review 보강(`8d6edfd`): `dialogue.parse_review_response`가 "나쁘지 않아"·"괜찮아"·"이 정도면 됐어" 등 수용 표현을 APPROVE로, 구체적 변경 요구가 섞이면 MODIFY 우선으로 해석(Intervention·Design-Change·Planning failure parser 불변). `SYSTEM_PROMPT_REVIEW`에 같은 의미 추가. 실제 mic 발화 "음... 나쁘진 않은 것 같아"가 UNCLEAR였던 사례. 테스트 `tests/unit/c_design/test_review_acceptance.py`; C 그룹 1134 passed.
- Harness: `scripts/c_full_voice_hri_e2e.py`(한 번의 lifecycle: Initial → 직접 Design Change → Difference → Planning failure → A Replan, 실제 mic/STT/TTS/Sol, Robot·Camera·DB 없음, 결과 디렉터리에 events.jsonl·envelope 8개·preview PNG 4장·summary.json). 오프라인 검증 `tests/integration/test_c_full_voice_hri_harness.py`. 실행 안내는 handoff §11. 실제 mic 실행은 사용자가 수행(자동 시작 안 함).

## 2026-10-12 — C Wave 6: 최종 회귀·실제 음성·계약 문서 정리 (`work/siyul-c-remaining`, base de59b08)

- 변경: 테스트·문서만(C production diff 0). `tests/unit/c_design/test_final_c_contract.py`(세 모드 intent 최종 표, planning failure 라우팅 10 조합, version chain v1→v2→MODIFY v2/round 1→APPROVE v2→다음 REVISE v3, metadata 유지, schema/validator 상수 불변). CONTRACT·handoff의 "세 함수" 표현을 네 공개 함수(`create_initial_design`·`review_design_candidate`·`run_intervention`·`run_design_change`)로 정정, handoff 시그니처를 코드와 일치시키고 §10 "남은 통합 항목" 추가.
- 검증: C 그룹(`tests/unit/c_design` 1024 + Stage3 lifecycle/failures/runner_preview/plan_failure + Wave2 relay + relay scenarios) **1096 passed, 0 xfailed, 0 failed**. C 관련 integration 152 passed. D 호환 그룹은 Wave 3 handoff의 D 테스트 1건만 실패(D-owned expectation mismatch, C runtime 정상). compileall·pyflakes(변경 파일) clean, `git diff --check` 0, commit 범위에 키·개인 경로·scratch 경로·debug print 없음.
- 실제 음성(mic, gpt-6.1-sol, 실제 STT/TTS, Robot 0회) 2회: Planning failure 질문 TTS → 실제 STT 전사 → (주변 무관 발화를 aux LLM이 REVISE로 해석) → Sol Revised Candidate v2(34블록·28블록, validator PASS, Current 보존, facing PASS) → Preview PNG → 검토 질문 TTS까지 실제 동작. 그러나 조작자가 목표 발화("응, 수정해줘"/"좋아, 이대로 해")를 하지 않아 **APPROVE·A Replan 구간은 음성으로 미완료**(검토 UNCLEAR → HOLD, 무한 loop·자동 승인·Robot 없음). 텍스트 모드 Sol 2회는 Wave 5에서 APPROVE·replan까지 완료.
- 판정: C 내부 결함 0, 테스트 green, facing·planning failure HRI·validator/schema/version/metadata 검증 완료. 단 실제 음성 lifecycle의 APPROVE 구간 미완료로 Wave 6 기준 `C_NOT_READY`(조작자 참여 mic 1회로 전환 가능). 관찰된 위험: 무관한 배경 발화를 aux LLM이 REVISE로 읽어 Sol 생성이 시작될 수 있음(정책 변경은 별도 승인 대상).

## 2026-10-12 — C Wave 5: Planning failure → C 수정 대화 → Candidate → Preview → APPROVE → A Replan 연결 검증 (`work/siyul-c-remaining`)

- 변경: 테스트·스크립트·문서만. `scripts/c_stage3_integration_smoke.py`에 `--scenario plan-failure`(`--blocked-block`)와 D 역할 trace(`plan_failure`/`replan`, `candidate_phase` PREVIEW→REVIEW 가드, stale APPROVE 거절, robot/replan 호출 횟수) 추가. `tests/integration/test_c_stage3_plan_failure.py`(시나리오 1 REVISE→Preview→APPROVE→replan ×2(blocked block 유무), 2 KEEP→HOLD, 3 UNCLEAR 재질문, 4 SEARCH_LIMIT 거절, 5 생성 실패 시 Approved 유지, 6 PREVIEW_READY 전 review 거절·stale APPROVE 거절, 7 STOP/late result). A는 실제 `handle_whole_plan`(read-only, FAKE 설정). C production 변경 없음.
- 검증: 실제 gpt-6.1-sol 텍스트 모드 2회(blocked block 없음/있음) — NO_FEASIBLE_ORDER → C 자연어 질문 → REVISE → Candidate v2(validator PASS·Current 보존) → Preview PNG → review APPROVE → Approved v2 → replan 결과 기록(수치는 Wave 5 보고). 회귀 수치는 Wave 5 보고 참조. Robot/Camera/DB 미실행.
- 미검증·한계: Revised Candidate(38블록)의 replan은 A `SEARCH_LIMIT`로 끝남(A fallback 정책 필요, D/A handoff). 실제 mic/TTS smoke 결과는 Wave 5 보고에 별도 기록. D 테스트 1건 실패는 Wave 3 handoff 그대로.

## 2026-10-12 — C Wave 4: A Planning failure → C Design-Change HRI/TTS (`work/siyul-c-remaining`)

- 변경: `app/c_design/{main,dialogue,llm,validator}.py`. `run_design_change(..., planning_failure=None)`(선택 인자, `inspection_context`와 분리)·`review_design_candidate(..., planning_failure=None)`. `validator.check_planning_failure`(형식), `main.REDESIGN_FAILURE_CODES = ("NO_FEASIBLE_ORDER",)`로 `redesign_required` true + 허용 코드일 때만 질문, 아니면 질문·TTS 없이 `FAILED / PLANNING_FAILURE_NOT_REDESIGN`. `dialogue.build_plan_failure_question`(코드·detail 미노출, 막힌 블록은 위치·층만), `llm.planning_failure_change_request`(생성 메시지용 짧은 요약)·`planning_failure_summary`(LLM 해석 payload 별도 키). Design-Change 질문은 한글 문장 reason만 읽음(`str(errors)` 차단). Design-Change parser는 앞머리 예/아니요를 떼고(표에 세지 않음) "기존설계"를 KEEP에 추가. 기존 `ask()`/`next_reply()`/TTS/STT 흐름 재사용, 새 public 함수·enum·schema 없음. CONTRACT §4.6·§10, handoff §3c(D 라우팅·KEEP→HOLD·A blocked block).
- 검증: 신규 `tests/unit/c_design/test_plan_failure.py`(라우팅·형식·질문·intent·REVISE v2/Current/facing/metadata·KEEP·voice mock). Wave 1 xfail(`test_plan_failure_question_should_not_read_machine_codes`) → PASS, known xfail 0. 회귀 수치는 Wave 4 보고 참조. 실제 LLM/TTS/STT/Robot 미실행.
- 미검증·handoff: D `mvp_workflow`는 아직 `SEARCH_LIMIT`도 C로 보내고 KEEP이면 같은 Design을 재계획함(D 수정 필요). A `WholePlanResult`에 막힌 블록 없음(A 제안). D 테스트 1건 실패는 Wave 3 handoff 그대로.

## 2026-10-12 — C Wave 2: canonical facing(정면 +X·등받이 low-x)을 생성 prompt 공통 적용 (`work/siyul-c-remaining`)

- 변경: `app/c_design/llm.py`만. `_FACING_RULE` 상수 하나를 `SYSTEM_PROMPT_INITIAL`(`_BUILD_HINTS` 뒤)·`SYSTEM_PROMPT_REVISED`(`_EXPRESSIVE_HINTS` 앞)가 공유하고, `_REVISED_PRIORITIES`에 "Current가 허용하는 범위에서 facing 유지, Current를 옮기거나 돌리지 않고 Current가 다른 방향을 고정하면 그 방향을 따른다" 한 줄 추가(Difference·Design-Change 두 Revised 메시지 변형이 공유). validator·schema·designer·dialogue·main 변경 없음. CONTRACT §8.8·§8.9 facing 행 추가. 테스트 `tests/unit/c_design/test_facing_prompt.py`.
- 검증(gpt-6.1-sol 실제, 텍스트 모드, production retry): Initial 5/5 facing PASS·validator PASS(loveseat·안락의자×2·park bench·평상형 긴 의자). Initial MODIFY 3/3 validator PASS·v1 유지·round 1(facing PASS 2, UNDEFINED 1 = 팔걸이 추가로 helper 중심 휴리스틱이 중립, 이미지상 등받이 low-x). Difference REVISE 3/3 Current 보존·v2·validator PASS(PASS 1, UNDEFINED 1 = 같은 helper 한계, 거울 fixture는 FOLLOWS_CURRENT). 직접 Design Change 3/3 REVISE·v2·Current 보존·facing PASS. C 그룹 1017 passed / 1 xfailed(Wave 4용). 결과 PNG·envelope는 scratch(저장소 밖).
- 미검증·한계: 이번 요청("편안한 침대 같은 느낌의 의자")에서는 등받이 없는 family가 나오지 않아 "불필요한 등받이 추가 없음"은 규칙 문구로만 보장. STT/TTS·Robot 미실행. D 테스트 1건 실패는 Wave 3 handoff 그대로.

## 2026-10-12 — C Wave 3: 직접 Design Change intent 분리·REVISE Candidate 생성 복구 (`work/siyul-c-remaining`, base de59b08)

- 변경: `app/c_design/{dialogue,llm,main,designer,validator}.py`. `run_design_change`가 Intervention과 별도 질문·규칙 표·LLM 프롬프트(`SYSTEM_PROMPT_DESIGN_CHANGE_ANSWER`)·입력 검사(`validator.check_design_change_input`, 규칙 동일)·Revised 메시지(`change_request`)를 쓰고 `on_progress`를 받는다. "수정할게요" → REVISE, "그대로 갈게"·"바꾸지 마" → KEEP. REVISE가 빈 differences 때문에 escalation/FAILED로 끝나던 결함(de59b08) 수정. Difference Intervention 표·프롬프트·호출 인자는 변경 없음. CONTRACT §4.6, D handoff §3b 추가.
- 검증: Wave 1 characterization xfail 3 → PASS, Wave 4용 xfail 1 유지. 신규 `tests/unit/c_design/test_design_change.py`. C 그룹·D MVP 테스트 결과는 Wave 3 보고 참조. 실제 LLM/STT/TTS/Robot 미실행.
- 미검증·handoff: D `tests/unit/test_mvp_workflow.py::test_inspection_context_keeps_expected_and_unknown_regions_for_c`는 규칙 KEEP으로 LLM 대체가 안 불려 실패(D 수정 필요, handoff 표). MVP Review `design_metadata` 미전달은 D 범위. Facing rule·Planning failure HRI는 다음 Wave.


## 2026-10-12 — ms-02 현재 시험 소스와 PR24 이후 통합 업데이트

- 기준: PR #24 merge `8914320`; 별도 `codex/current-runtime-update-20261012`. 원래 실행 폴더의 브랜치 전환/덮어쓰기 없음. 원본 544개 파일을 보존 ZIP과 SHA256으로 재확인했으며 변경 0개. 웹 자산은 별도 백업. 게시·PR 상태는 실제 GitHub 결과를 기준으로 확인한다.
- 현재 A 계산 보정·C 설계 변경 문맥·D 진행/Robot 별도 프로세스·한 화면 HMI·개인 DB/웹 소스를 포함. 외부 D 소스를 `robot_control_integration/`에 함께 보존하고 기존 DRCF2 소스 수정은 패치/해시로 포함. #24 B 파일과 최신 Stage3/Current relay/5층/40블록 기준 유지.
- 이번 합침에서 발견한 HMI FINAL 검증, 합성 관측 5층 범위, 공급 슬롯 1~6 순환/표시, 웹 정적 자산 누락·한글 경로 시험을 정리. 현재 지원 블록 모의 실행 시험을 갱신하고 실제 체결 미확정 검사는 유지.
- PR24 관련 재검사 **699 passed**, 종료 0. B+기존 callback 예제 별도 검사 **261 passed**, 종료 0. Robot 주요 실행/Contact/제스처/STOP 검사 **364 passed**, 종료 0.
- 새 통합/HMI/저장/웹/모의 C→A→D 검사 **155 passed, 18 skipped**, 종료 0. UI/진행/슬롯/프로세스/드라이버 단위 검사 **220 passed, 6 skipped**, 종료 0. 추가 병합 경계 검사 **81 passed**, 종료 0. 서로 중복되는 검사이므로 합계를 고유 검사 수로 사용하지 않는다.
- 넓은 범위 재검사: **2697 passed, 51 skipped, 2 failed, 11 errors**, 종료 1. 같은 구형 음성 시험을 PR24 원본에서 별도 재현: **70 passed, 2 failed, 11 errors**, 종료 1. Initial 승인/녹음 이벤트·LLM key Mock 전제가 현재 Stage3와 맞지 않는 `test_real_voice_workflow`, `test_real_voice_replan`, `test_real_stop_resume` 실패이며 전체 통과로 보고하지 않는다. 테스트 삭제·skip 추가·판정 완화로 숨기지 않았다.
- D 보존본 전체 단위 검사 **916 passed, 1 skipped**, 종료 0. 처음에는 기존 로컬 logs 의존으로 복구 검사 17개가 오류였고, 역사적 READ_ONLY 표본을 명시적 Fixture로 분리해 재검사했다. 실행 승인이나 최신 실물 상태로 사용하지 않는다. B/A 현장 경로가 필요한 기존 조건 검사 1개는 건너뜀.
- 1024×768 및 1500×1000 Qt offscreen 화면에서 Design/Current/Expected/Step 네 패널이 한 화면 안에 들어가는지 확인. 실제 모니터·WM/DPI는 별도.
- 실제 Robot/Camera/LLM/STT/TTS/PostgreSQL 연결·드라이버 재빌드/재시작은 이번 검증에 포함하지 않았다. DB DSN 없는 검사는 기존 조건으로 건너뜀. A `SEARCH_LIMIT`, D 정밀 체결/XY 탐색 연결, B 실영상·실물 전체 통합, DB 시작/저장 시 로그인 정책은 [업데이트 안내](13_RUNTIME_UPDATE_20261012.md)의 후속 항목.

## 2026-10-11 — B INITIAL/FINAL 관측 근거 보완（PR24 리뷰）

- B inspection.py와 기존 round1 테스트만 수정. 첫 Current 확정은 24×24, layer 1~5 전체의 verified_regions 근거가 필요하며 일부 빈 영역만으로 Current=[]를 초기화하지 않는다. 부족하면 INITIAL_STATE_UNAVAILABLE로 반환하고 Current 미확인 및 Plan 채택 차단을 유지한다. 초기 단계에는 보존 가능한 아래층 확정 이력이 없으므로 전체 범위를 요구한다.
- FINAL의 verified_regions가 없으면 과거 Current의 MATCH/MISMATCH를 재사용하지 않고 UNOBSERVABLE로 보류한다. 기존 same-layer evidence 검사상 visible_blocks만 있고 verified_regions가 없는 입력은 여전히 오류다. 근거 없는 FINAL은 Current/revision 유지. 새 유효 근거가 있는 FINAL은 기존 비교 및 아래층 가림 이력 유지 정책을 따른다.
- 수정 전 신규 핵심 검사: 2 failed / 1 passed로 두 결함 재현. 수정 후 B MVP/legacy/calibration/supply 검사 246 passed, 1 skipped(실제 PR22 Consumer 소스 경로 미제공), 종료 0. 정상 INITIAL·FINAL, 부분/빈 INITIAL, 근거 없는 FINAL 및 과거 불일치 재사용 차단, fresh MISMATCH, layer5 아래층 유지, 취소·늦은 결과 검사 포함. 대상 diff --check 통과. app/ 변경 없음.
- 기본 전체 pytest는 수집 중 psycopg 미설치 및 test_hmi_remaining import 경로 누락으로 중단(오류 2); 전체 통과로 보고하지 않는다. 실제 Camera/Controller/D 수신 연결은 미검증. Git commit/push/PR 갱신 미수행. 기존 사용자의 perception/.gitignore 변경과 자산은 이번 수정에 포함하지 않았다.

## 2026-10-11 — 원래 C-2 작업 폴더 PR24 수정본으로 갱신

- 기존 work/hongdong-vision-round1의 262ae61에서 PR24 수정본 2058d80으로 fast-forward. 원격 최신 여부를 추가 fetch한 작업은 아니며, realign 작업 폴더와 같은 기준 커밋으로 맞췄다.
- 이전 미커밋 변경·미추적 파일은 stash와 /home/roh/Documents/ChatGPT/협동2/C2_before_update_eVmIvWWW/local_changes.tar.gz에 보존했다. 모델·촬영·보정 자료는 이동/삭제하지 않았다. 기존 A/C/D 로컬 변경은 재적용하지 않았다.
- B 설정 확인값과 INITIAL/FINAL 재현 테스트만 이어받았다. 재현 테스트는 보완 전 단계이며 아직 전체 검사 통과를 주장하지 않는다. app/planning_trial/interfaces는 2058d80과 diff 없음. 설정 관련 live_view/runtime 검사 43 passed. GitHub 게시 없음.

## 2026-10-11 — 홍동 B 제출 코드 최신 integration 기준 정렬

- 사용자 승인 범위: fetch·별도 로컬 작업 브랜치 구성·B 수정/검증. 최신 명시 지시로
  D 파트 수정/추가는 제외했다. 이후 사용자 명시 승인으로 기존 PR #24의
  commit·일반 push·본문 갱신을 진행한다. force push와 PR 병합은 승인 범위 밖이다.
- 원격 `codex/integration-round1` HEAD `02137d8`을 확인하고 managed worktree의
  `codex/b-round1-realign`에서 작업한다. 기존 `work/hongdong-vision-round1`과
  원래 작업 폴더의 미커밋 변경·원자료는 보존한다.
- PR #24 head `262ae61`에서 `perception/`와 B 설계 제안서만 옮겼다.
  이전 PR에 섞인 D 핵심 코드·A/C·Robot 설정은 옮기지 않았다.
  `app/`, `tests/`, `interfaces/`, `planning_trial/`의 tracked 파일은 `02137d8`과 차이 없음.
  최신 Preview→C Review·B Current/revision relay·빨강/5층/40블록·stale/STOP을 유지한다.
- 별도 공간에 추가했던 D 수신부·호환 bridge·D 연결 시험 3개는 B 제출 범위에서 제외하고
  `/tmp/c2-d-review-preserved-N09hR5/`에 복구 가능하게 보관했다. 원래 로컬 파일도 보존한다.
  최신 D에 없는 구형 bridge를 production에 추가하지 않는다. B 호환 시험은 명시된 Qt
  계약 대역으로 B 진입/queue 전달을 검사하도록 정리하고 D 실연결 시험과 구분한다.
- 최종 관련 검사 **692 passed**, 실패/오류/skip 0, 종료 0. B 검사/보정/공급판/호환,
  실제 최신 DB/HMI 입력 검증 함수 대조, 기존 최신 A/C/D Stage3·relay·STOP/stale 및
  공통 블록 계약·5층 회귀·Planner 검사를 실행했다. Qt offscreen·합성 관측·FAKE Robot이다.
  첫 실행은 HMI 검증 파일 경로 오류와 빠진 구형 bridge로 2 failed/701 passed였다.
  D 추가 시제품을 포함했던 중간 706 passed는 최종 B-only 제출 검증 수치로 쓰지 않는다.
- 미검증: 실제 Camera/Controller 관측 callable, 최신 D 전체 공정과 B 결과 bind,
  실시간 HMI/DB 서버·Robot/5층 실측. D 연결 요구는 B의
  `perception/docs/D_INSPECTION_CONNECTION.md`에 인계하며 D 파일은 수정하지 않는다.
  게시 준비: B-only snapshot 커밋 `061da09`에 PR #24 기존 head `262ae61`을
  병합하여 두 이력을 보존한다. 충돌 파일은 검증한 B snapshot과 최신 integration D를
  유지하는 방향으로 해결했다. 병합 후 관련 검사를 재실행해 **692 passed**, 종료 0을 확인했다.
  게시 결과: 병합 커밋 `f9b8912`를 기존 `work/hongdong-vision-round1`에 일반 push했고
  PR #24 본문과 기준 SHA를 갱신했다. GitHub에서 base `02137d8`, Draft/open,
  mergeable=true·clean과 변경 106개(B 코드·설계 제안서·B 작업 기록만)를 확인했다.
  PR merge·force push·Issue 댓글은 하지 않았다. 다음: 사람 리뷰·D 결선 확인·공동 시험.
  이 작업은 전체 팀 연결 완료나 실제 장치 검증을 의미하지 않는다.

## 2026-10-11 C Stage3 기준 A·D 연결 정합

- C PR #23이 반영된 1차 통합 코드를 기준으로 A·D 및 공통 Schema를 맞췄습니다. 노랑/파랑 4·6점, 빨강 2점, 0°/90° 방향, 1~5층·최대 40블록과 FAKE 공급 5열을 지원합니다. B 소유 Current·revision·Expected·비교 계약은 유지합니다.
- Candidate → Qt Preview 완료 → C Review → MODIFY 재표시 / APPROVE → A 계획 → Backend 채택 순서입니다. Revised도 다시 승인하며 동일 후보군 수정은 버전을 올리지 않습니다. C가 음성 입출력 전체를 담당하고 D가 요청/Job/Current revision 및 STOP 이후 늦은 결과를 검사합니다.
- 관련 회귀 **504 passed, 4 warnings**, 신규 연결 경계 **22 passed**입니다. 전체 검사 **2243 passed, 31 failed, 11 errors, 34 skipped**이며 전체 PASS가 아닙니다. 남은 REAL 실패·오류 42개의 node ID는 수정 전 같은 기준 코드에서도 동일합니다. 외부 측정 자료와 원본 절대경로가 없는 환경입니다.
- 실제 마이크/LLM, 최신 B 생산자, Camera/Robot 및 REAL 빨강 공급은 미검증입니다. REAL은 검증된 기존 네 열만 사용하며 빨강을 실행 전에 거절합니다. 실물 pose를 임의 생성하지 않습니다.
- 기존 Draft PR #22에 반영하며 병합은 하지 않습니다. [변경 안내](D_C_STAGE3_AD_ALIGNMENT.md)와 [검증 보고서](../reports/c_stage3_ad_alignment_20261011/validation.md)를 참고해 B 연결 확인 → FAKE 공동 통합 → 장치 측정/REAL 검증 순서로 진행합니다.


## 2026-10-11 수현 HMI·DB 1차 통합 제출

- 최신 기준: 10/8 B 소유 Current·revision·Expected·비교, D 실행·진행·최종 종료. 공통 정수 layer 1~5.
- HMI·DB ZIP 소스 선택 반영, 4→5층 정합, B 검사/완료 표시 충돌 거절, PostgreSQL 개인 이력과 실행 안내 포함.
- 관련 회귀 1,159 passed(실제 DB 시험 포함), 별도 DB 33 passed, 이력 Docker 이미지 빌드 통과. 탐색적 전체 시험은 기존 PC 절대경로와 C 실패로 PASS가 아닙니다.
- 최신 실제 B→D·HMI 요청 수신·로그인 owner·웹·Robot/Camera 실기는 미완료/미검증. Draft PR로 리뷰합니다. 상세 범위·실행 환경·차단 사항은 [검토 기록](D_HMI_DB_ROUND1.md)을 따릅니다.



## 1차 통합 5층·인터페이스 정합 점검 — 2026-10-11

- 대상은 사용자 생성 `codex/integration-round1`이며 시작 SHA는 main과 같은 `afd75d0b0943d85b44248ea563e89f860921e1dd`다. 기존 `fix/common-five-layer-support`의 `27907c8` 변경을 별도 작업본에 재사용했다. C/A/D MAX_LAYER, 블록/관측 영역 Schema, HMI·합성 관측·수동 Current 확인을 1~5층으로 맞춘다. 원격 반영은 해당 PR의 병합 상태로 구분한다.
- 공통 계약의 block_id/parent_version 요구·무응답 자동 취소 표현을 실제 C·D 계약에 맞췄다. 팀 가이드·C 구조의 미확정 지지 표현과 A/D 인계의 현재 5층 invalid 설명을 정리했다. [1차 통합 인터페이스 점검](11_ROUND1_INTERFACE_AUDIT.md)에 기준·수정 사항·별도 브랜치 차이·담당별 연결 과제를 기록했다. 과거 시험·원본 Fixture·측정값·참고자료는 보존한다.
- 기존 5층 연결 시험에 C/A/D/Schema 상한 일치와 B 합성 callback의 5층 관측 채택·가린 아래층 보존·6층 입력 거절 후 상태 보존·중복 무효화를 추가했다. 새 production 모듈·class·framework·실행 dependency는 없다.
- 실제 관련 검사 **678 passed**, 실패·오류·skip **0**, 종료 코드 **0**. C validator·A planner·D contracts/current/replan·HMI/Qt·A/D·A/B/D 합성 callback·C 저장 응답·5층/30블록·Schema/HMI 참조·팀 인계 및 B 예시 검사를 포함한다. Qt는 offscreen, Robot은 Fake, B는 합성 입력이다. 로그와 JUnit은 ignored `logs/round1-interface/tests.log`·`tests.xml`이다. 기존 RefResolver deprecation 경고 2건이 남는다.
- 환경은 Python 3.12.3·pytest 7.4.4·기존 PyQt5다. 초기 관련 검사에서 `referencing` 미설치로 Schema 시험 1건만 실패(312 passed)했고, 이전 5층 검증에서 사용한 jsonschema 4.26.0과 해당 의존성을 `/tmp/c2-round1-schema-test-deps`에만 준비해 재검사했다. 저장소 dependency·ROS 환경은 바꾸지 않았다. LLM/음향 key·HISTORY_TEST_DSN은 child process에서 unset했고 pytest plugin 자동 로드를 끈 장치 없는 시험이다.
- 전체 저장소 시험은 이번에 실행하지 않았다. 아래 2026-10-07 기록의 기존 전체 실패·장치 자료 경로·C HTTP Fake 정합 문제를 해결했다고 주장하지 않는다. 실제 Camera/Robot·LLM/음향·DB/웹은 이번 시험 범위 밖이다. lint/type/CI는 미구성이다.
- 문서·정적 검증: 기존 5층 변경을 포함한 변경 파일 **34개**, 상대 링크 **245개**, JSON 예시 코드 블록 **25개**(보존된 JSON Lines 블록 1개 포함)를 검사했다. 새 누락 링크·새 잘못된 anchor **0**, 변경 Python/JSON 파싱·`git diff --check` 통과. ignored 과거 로그를 가리키는 기존 누락 링크 **23개**는 보존했다. reference 원문 변경 **0**. 결과는 ignored `logs/round1-interface/static-checks.json`이다.
- 남은 BLOCKER: A API 0.5 문서의 B Current/revision Owner 표현과 현행 D 단일 상태 Owner 차이, A 재평가/경로 wire와 D 최종 Schema 미연결, B 실제 촬영 생산자/최종 확인 미제출. 설계 확정 이벤트·좌표 단위/frame 변환·직접 결착/정지·사용자–Job/웹 연결도 담당 PR로 검증해야 한다. 이 점검을 전체 인터페이스 통합 완료나 실물 5층 성공으로 표시하지 않는다.

관련 검사 실행 명령:

```sh
env -u OPENAI_LLM_API_KEY -u OPENAI_API_KEY -u OPENAI_TTS_API_KEY -u HISTORY_TEST_DSN \
  QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  PYTHONPATH=/tmp/c2-round1-schema-test-deps \
  python3 -m pytest planning_trial/test_planner.py \
  tests/unit/test_contracts.py tests/unit/test_hmi_current.py tests/unit/test_qt_hmi.py \
  tests/unit/test_current.py tests/unit/test_replan.py tests/unit/test_hmi_contracts.py \
  tests/unit/test_planner_results.py tests/unit/test_team_handoff.py \
  tests/unit/c_design/test_validator.py tests/integration/test_a_backend.py \
  tests/integration/test_abd_callback.py tests/integration/test_c_saved_results_hmi.py \
  tests/integration/test_five_layer_pipeline.py \
  tests/integration/perception_backend_callback_examples/tests/test_callback_examples.py \
  -q --junitxml=logs/round1-interface/tests.xml
```

## 공통 5층 지원 — 2026-10-07

- **기준/작업 위치:** 원격 main `afd75d0b0943d85b44248ea563e89f860921e1dd`(PR #17 병합)을 확인하고 독립 clone의 `fix/common-five-layer-support`에서 수정했습니다. 완료 시 원격 main도 동일했습니다. 로컬 `work/suhyun-assembly-evidence`/`62b7ffd`의 기존 Backend 연구 코드와 작업 상태는 보존했습니다. 저장소 AGENTS와 관련 정책·계약을 읽었으며 저장소/관련 작업본에 `.agents/skills`는 없었습니다. 검증 단계에서는 commit/push/PR/merge를 하지 않았으며, 이후 사용자 승인으로 이 변경의 commit/push·draft PR 게시를 진행합니다. 병합은 하지 않습니다.
- **변경:** A `MAX_LAYER`·오류 문구, D 블록/관측 영역 검사·`supported_scope`, Day4 Schema를 1~5층으로 통일했습니다. HMI Schema는 Day4 정의를 참조하므로 같은 범위를 적용합니다. 합성 관측과 수동 Current 확인도 D의 층 상수를 사용합니다. 여섯 배치 필드·PLACE·지지 2 stud·24×24 좌표·판 footprint·Plan/Current 최신성 의미는 유지합니다.
- **30블록:** C 생성 상한 30을 유지하고 C 검증→실제 A→D 채택→Qt→합성 관측/FakeRobot 완료를 확인했습니다. A/D에 새 수량 제한은 추가하지 않았습니다. REAL 수동 시험의 네 공급열×여섯 슬롯(최대 24 Step) 제한은 유지하며 실제 직접 결착·Vision 판별 범위를 확장했다고 주장하지 않습니다.
- **검사 변경:** 기존 5층 범위 초과 시험은 6층으로 옮겼습니다. 보관 C 응답과 A 첨부 자료·해시는 보존하고 A의 승인된 두 변경만 제외해 원본 해시를 대조합니다. 새 연결 검사는 1~5층 정상, 30블록, 부분 Current 보존/Remaining, 6층 거절/미채택, 지지 부족/판 밖 좌표, Schema 및 수동 확인 입력을 다룹니다. Qt 기존 4층 가장자리 검사를 유지하고 5층 조건을 추가했습니다.
- **관련 L1/L3:** `planning_trial/test_planner.py`, unit의 contracts/hmi_current/qt_hmi/current/replan/hmi_contracts/planner_results/c_design validator, integration의 a_backend/abd_callback/c_saved_results_hmi/five_layer_pipeline를 실행해 **645 passed**, 종료 코드 **0**입니다. 5층 가장자리와 30블록 완료 PNG를 실제로 열어 표시를 확인했습니다. Qt offscreen·Robot/관측/LLM/음향은 Fake 또는 미연결이며 실제 장치 검증이 아닙니다.
- **전체 비교:** 변경 전 main은 **1405 passed, 41 failed, 24 skipped, 11 errors**, 변경 후 최종은 **1444 passed, 41 failed, 24 skipped, 11 errors**, 각각 종료 코드 **1**입니다. 실패·오류 52건의 node ID 집합은 동일하며 새 실패 0건입니다. 24 skip은 별도 실제 DB DSN 미설정입니다. 전체 PASS로 표시하지 않습니다.
- **분리한 기존 제한:** C LLM의 `OPENAI_LLM_API_KEY`와 D 시험의 `OPENAI_API_KEY` 설정이 다릅니다. 해당 값 대신 시험 프로세스의 명시적 더미와 HTTP Fake만 사용한 10개 비교 검사도 전/후 각각 **3 passed, 7 failed, 1 teardown error**로 동일했습니다. 키 문제 뒤에는 최근 C metadata/judge 호출과 기존 D Fake의 호출 횟수 기대(1/2회)·대기 조건 불일치도 남습니다. Robot 관련 시험은 `/home/ms-02/C_2/...` 설정·외부 원본/측정 자료가 이 편집 PC에 없어 실패합니다. 별도 문제의 코드·장치/계정 설정은 수정하지 않았습니다.
- **시험 환경:** 편집 Python 3.12.10 / pytest 9.1.1 / Qt offscreen. ROS `launch_testing`과 pytest 충돌로 이번 명령에서만 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`을 사용했습니다. 기존 Schema 시험에 필요한 jsonschema 4.26.0을 `/tmp/c2-five-layer-test-deps`에만 준비하고 기존 ROS 환경 site-packages와 함께 PYTHONPATH로 지정했습니다. 저장소 dependency/framework 추가는 없습니다. 일반 검사는 OPENAI 세 key와 `HISTORY_TEST_DSN`을 child process에서 unset했고 실제 비밀값·LLM/Robot/ROS 제어를 사용하지 않았습니다.
- **최종 확인/후속:** 변경 Python/JSON 파싱, Markdown 새 누락 상대 파일 링크 0, `git diff --check` 통과. lint/type/CI 미구성. 사람 리뷰와 실제 5층 Vision/직접 결착·30블록 실행 환경 검증, D LLM Fake 갱신과 외부 Robot 자료 경로 정합성이 후속입니다. 이전 시험 기록은 아래에 그대로 보존합니다.
- **문서 전체 재점검:** 저장소 Markdown·작업 지침·Schema와 층 관련 코드/시험을 검색해 callback 예시 README의 현재 계약 누락을 1~5층으로 고쳤습니다. C/D 진행 기록에는 현재 범위 안내를 추가하고 과거의 4층 계약·시험 결과를 보존했습니다. 기존 1~4층 Fixture·고정 예시·Qt 회귀 시험·A 원본 해시 비교는 당시 자료 또는 유효한 하위 범위 사례입니다. Day1~4는 일정, 공급열/시작 슬롯 1~4와 REAL 최대 24 Step은 장치 시험 한계, Schema의 width/height 최대 24는 판 크기이므로 층 상한 변경 대상이 아닙니다. 실제 Vision/직접 결착의 5층 성능은 미검증입니다.

전체 실행 명령(원격·실기 연결 없음):

```sh
env -u OPENAI_LLM_API_KEY -u OPENAI_API_KEY -u OPENAI_TTS_API_KEY -u HISTORY_TEST_DSN \
  QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  PYTHONPATH=/tmp/c2-five-layer-test-deps:/Users/suhyun/miniforge3/envs/ros2_jazzy/lib/python3.12/site-packages \
  python3 -m pytest tests planning_trial/test_planner.py -q
```


## 최종 MVP 문서 이행 — 2026-10-07

사용자 요청으로 GitHub main `95259bd`의 Markdown/docs를 커스텀 의자 최종 MVP에 맞춰 정렬합니다. [최종 MVP](10_FINAL_MVP.md)에 설계 대화·사용자 확정 → 조립 순서/경로 → Backend/HMI → 로봇 공급판 집기·조립판 직접 결착·필요 시 사람 지지 → 세 단계 종료를 정의했습니다. 목표는 개발 과정에서 수정될 수 있습니다.

- 1단계는 해당 계획에 필요한 모든 블록 사용 종료, 2단계는 Vision 완성상태 확인과 Backend 최종 조립 판정/종료, 3단계는 사용자별 현재 설계·조립 기록 DB 저장과 웹앱 반영입니다. 명령 완료·마지막 블록 사용·JSONL만으로 세 단계 완료를 처리하지 않습니다.
- [첨부 연구 설계](suhyun_individual_research_topic.md)를 제품 적용 안내와 함께 포함했습니다. 지지 프로토콜을 반영하고 원문 D1~D13·접촉/복구·필드·역할 제안은 연구 설계와 팀/장치 합의 상태로 구분합니다.
- README·최신 결정·AGENTS·계약/팀 가이드·개발 단계·측정·실행·DB·C/A/B 연결/시험 안내를 정렬했습니다. 기존 전달형 Day4 계약·코드 명령·시험 수치·측정 원자료는 보존하며 [reference 적용 안내](reference/README.md)를 추가했습니다. GitHub에 없는 로컬 final_docs/발표 초안·미완료 코드 변경은 포함하지 않습니다.
- **현재 구현:** C Design/HRI·A PLACE Plan·D/Qt/기존 전달·B 합성 callback과 독립 PostgreSQL 이력/계정 코드가 게시되어 있습니다. 이 문서 작업에서 앱을 다시 시험하지 않았으며 아래 이전 시험 수치는 당시 대상의 기록입니다.
- **남은 구현/합의:** 직접 결착 좌표·경로/접촉 인계·지원 제스처/준비·최종 Vision 계약·사용자–Job 소유자/세션/웹 반영·Qt/웹 분담. 계정표는 있지만 jobs에 사용자 소유자 연결이 없고 사용자별 웹 화면도 없습니다. 기존 전달/Mock·DB 검사는 최종 서비스 전체 검증이 아닙니다.
- **이번 검증:** 변경 Markdown 29개를 포함한 문서 38개의 상대 링크 298개·표 123개·fenced 코드 블록 128개(JSON 예시 36개)를 검사했습니다. 신규 링크/앵커·표·JSON/코드 블록 오류 0, 종료 코드 0입니다. Git 제외 로컬 logs 산출물을 가리키는 기존 미존재 링크 28개는 게시 원자료의 한계로 보존했습니다(D_ABD_SYNTHETIC_CALLBACK_TEST·D_A_PLANNER_HANDOFF·D_BACKEND_RUN_ROBOT_PLAN·STATUS). diff 공백 검사 종료 코드 0, 기존 reference 원문 8개·첨부 원문 본문·측정/개발/시험 기록 본문 보존을 확인했습니다. 코드·Schema·장치 설정은 변경하지 않았고 앱·실제 DB·웹·Camera/Robot 검사는 수행하지 않았습니다. 기존 CI/lint/type는 미구성이며 새 도구를 도입하지 않았습니다.
- 지정 `/home/ms-02/C_2`의 개발 브랜치·미완료 변경을 보존하고 최신 main 기반 별도 `docs/final-mvp-chair` 작업 공간에서 문서만 commit/push/PR을 준비합니다. merge·장치 실행은 요청 범위가 아닙니다.

## 이전 개발·시험 기록의 범위

아래는 각 기록 날짜의 구현·검증 결과입니다. 새 제품 목표의 구현·통합 완료율이나 이번 문서 PR의 재검사 결과로 사용하지 않습니다.

## A파트 — 지지 합의 문구 정리·Day3 재검사 (2026-10-07)

- 2026-10-06 세은의 동의와 수현의 회신에 맞춰 A/C의 지지 조건을 바로 아래층과 겹치는 고유 stud 총 2개 이상으로 문서·C 주석에 통일했습니다. 아래 블록 개수와 무관하고 중복 stud를 합산하지 않으며, layer=1은 제외합니다. Day4 기하 검사 기준이며 실제 체결·물리 안정성 검증이나 프로젝트 전체의 영구 기준은 아닙니다.
- 새 수정은 현재 결정·공통 계약·C/B 연결 합의·C 계약·C validator의 설명·이 진행 기록입니다. A/C 함수·조건·상수·입출력·로봇 설정은 변경하지 않습니다. 사용자가 이번 문서 PR에 한해 별도 브랜치를 허용했습니다. 최신 main에서 문구 수정만 준비하며, 고정 A 브랜치의 기존 자료·이력은 유지합니다.
- 수정 전 main `6fb971cad619de398b1c47e7d669912cdb470fad`에서 A 독립 **112 passed**, A–D **24 passed**, C 함수→A/D·Qt **16 passed**, C 공개 Mock 재현 **17 checks PASS**를 확인했습니다. 사용자가 같은 명령을 직접 실행한 로그도 모두 종료 코드 0입니다. 사용자 직접 실행과 에이전트 검사 로그는 별도 경로·Job으로 보존합니다.
- 문구 수정 후 C validator 기존 검사 **52 passed**·종료 코드 0, diff 공백·Markdown 코드 블록·새 문서 링크와 변경 범위를 확인했습니다. validator의 실행 AST는 주석/docstring을 제외하고 main과 동일하며 A 계산·재현 파일·README는 변경하지 않았습니다.
- 직접 실행 사례: Initial 15 PLACE → D Current 4개·revision 5 → Revised v2의 11 PLACE 채택. Current 보존·중복 PLACE 제외·선행 조건·최종 목표 일치를 확인했습니다. C는 Mock 또는 HTTP Fake, 관측은 fixture, Robot은 Fake, Qt 검사는 offscreen입니다. 실제 LLM·음성·Camera·Robot·사람 조립은 이번 결과에 포함하지 않습니다.
- 이번 PR은 문서 5개와 C validator 설명만 변경합니다. 재현 스크립트·README·A 과거 진행 기록은 포함하지 않습니다. 기존 재현 코드는 고정 A 브랜치 `work/seeun-planning`의 `319a275`에 그대로 보존하며, 새 알고리즘·dependency·class·SIM/REAL 계산 분리는 추가하지 않습니다.
- 공유 압축 파일은 사용자 직접 실행 로그·입출력·해당 Job JSONL·검증 기록과 실행 명령을 별도로 제공합니다. 생성 산출물은 원격 소스에 커밋하지 않습니다. 다음 작업은 실제 C 출력과 같은 기준의 D Current, 실물 조립 순서 및 최종 목표 대조입니다. 문구 정리의 main 반영은 수현 리뷰·승인 후 별도로 확인합니다.

## 수현 누적 D 수정 PR 게시 준비 (2026-10-06)

- 사용자 요청으로 Robot 시험 진입점/설정·수동/합성 HMI·잘못 놓음 표시·A–B–D callback·C 저장 Design·블록 비율의 누적 수정과 검사를 PR로 준비했다. 별도 DB/컨테이너·발표/제출 초안·미완료 공통 문서는 제외한다. [게시 범위와 검증](D_BACKEND_PROGRESS.md#2026-10-06--누적-d-수정-pr-게시-준비).
- PR #9/B PR #10 병합 후 최신 main `7c51549`를 기준으로 게시본을 만들고 실제 A/B 원본과 main의 C 코드·공통 문서를 보존했다. 독립 게시본의 전체 검사 **1045 passed**, 종료 코드 0. Robot 검사는 이 호스트의 검증된 원본/측정 자료 경로에 의존하며 다른 PC에서의 전체 실행은 그 자료가 필요하다. C 저장 응답은 저장소 Fixture 경로로 실행할 수 있다.
- 로컬 지정 브랜치/HEAD/기존 미커밋 변경과 기존 원격 브랜치는 유지하며, 최신 main에서 만든 게시용 원격 브랜치 `work/suhyun-day4-integration-updates`에 후속 수정만 게시한다. 사람 검토용 초안 PR이며 실제 C 함수/B 인식/Camera/Robot STOP·재개/전체 장치 시연 통과를 주장하지 않는다. GitHub CI는 미확인, main 병합과 장치 명령은 실행하지 않는다. logs/PNG·원자료는 Git 제외/원래 위치에 보존한다.


## HMI 블록 높이·돌기 비율 수정 (2026-10-06)

- 사용자 요청에 따라 [표시 코드](../app/hmi_board.py)의 납작한 층 높이를 LDraw 기본 brick 비율(가로20:몸체 높이24)과 동일 축척의 투영으로 수정하고 돌기 지름/높이를 표시했다. 높이 비율은 BoardView의 표시 인자로 변경 가능하다. 전체판·확대의 범위에 모든 몸체 모서리와 돌기 높이를 포함한다. 현재 Step/전달 블록은 위에서 보는 시점을 유지한다. Design/좌표/층/Current/완료 계산·Robot 보정은 변경하지 않았다.
- 기존 Qt 검사에 표시 비율/설정·판 가장자리 4층/좁은 창·원본 유지 **6개**를 추가했다. 관련 **40 passed**, 전체 **852 passed, 11 skipped**, 각각 종료 코드 0. 11개 skip은 기존 history PostgreSQL 통합의 HISTORY_TEST_DSN 미설정이며 이번 HMI 범위는 모두 검사했다. offscreen Qt의 C Initial/Revised 그림·전체 창과 경계 사례를 확인했다. [수정 후 미리보기](../logs/hmi-brick-proportion/board-after.png), [표시 변경 기록](D_BACKEND_PROGRESS.md#2026-10-06--hmi-블록-비율-수정). 실제 장치 동작/실물 치수 검증은 수행하지 않았다.
- 이번 파일은 표시 코드/기존 Qt 검사/진행 기록/STATUS 네 개다. 새 dependency/class/framework 없음, 공통 계약/Backend/A/B/C 산출물/Robot 경로 설정/기존 변경을 보존했다. lint/type 미구성이다. 지정 브랜치 유지, GitHub 게시/PR/merge 없음. 기존 FAKE 창을 닫고 동일 명령으로 다시 실행하면 새 표시가 적용된다.

## 사용자 제공 C 저장 Design 응답 → 실제 A/D·Qt 통합 (2026-10-06)

- C Initial/Revised 두 Downloads 원본을 동일 바이트의 Fixture로 보관했다. 생성 커밋/실제 C 함수는 미제공이다. 기존 [합성 입력 화면 실행부](../app/abd_input_hmi.py)에 파일 옵션과 실제 배치/저장 Revised 입력만 추가하고 실제 A `plan_from_current`, 기존 D 채택/재계획, B 원본 `deliver_example`, Controller/FakeRobot, snapshot/Qt/JSONL을 사용했다. 관측은 D 작성 합성 프레임, 전달판은 시험 입력이며 B production 구현으로 표시하지 않는다. [파일·입력·실행 안내](D_A_PLANNER_HANDOFF.md#사용자가-제공한-c-저장-응답으로-adqt-시험-2026-10-06).
- Initial v1은 15 Step/전체 Current 15개·revision 15로 완료했다. 부분 Current 0/4/8개에서 Remaining 15/11/7을 실제 A로 계산했다. S09 (9,9) 2층 노랑 6점/90°를 파랑으로 관측하면 Current 9개/revision 9·8/15·의도 확인 대기다. 저장 Revised v2는 이를 보존하고 4블록을 추가해 전체 19블록·Remaining 10 Step을 채택한다. 새 EMPTY/관측을 Step마다 입력해 Current 19개/revision 19·10/10 완료를 확인했다. Robot 성공만으로 Current/Step은 변경되지 않는다.
- 실제 x=7인 배치에 같은 Revised를 넣으면 A NEEDS_CORRECTION·사람 정리 대기다. Current/기존 Design을 보존하고 추가 전달하지 않았다. 조기/중복 Revised·STOP 뒤 늦은 응답·지원 밖 색상/Boolean 좌표도 진행하지 않는다. C 저장 질문/전체 응답은 HMI/JSONL에 보존한다. Revised는 해당 색상 차이용 저장 응답이며 임의의 불일치에 자동 적용하지 않는다.
- 신규 검사 **13개**, 관련 **182 passed**, 최종 전체 **805 passed**, 각각 종료 코드 0. [산출물 색인](../logs/c-saved-results-final/summary.json)에 JUnit·Job JSONL·snapshot JSON·화면 PNG·소스 SHA를 남겼다. native Qt는 파일 로드/창 열기/EOF 종료만 확인했고 START 이후 화면/진행은 offscreen Qt로 검사했다. 초기/재계획/보류 그림도 확인했다. 다수 관측 배치를 한 표에 표시하면 열이 좁아지는 기존 HMI 표시 한계는 남아 있으며 이번에 UI를 재설계하지 않았다. lint/type check 미구성이다.
- 이번 파일 6개: 기존 실행부/연결 안내/이 STATUS 3개, 새 C 원본 Fixture 2개와 새 통합 검사 1개. application 236줄, 신규 class/dependency/framework/DB 없음. 300줄 변경량 검토 신호는 원본 JSON 보관과 정상/재계획/보류 검증에 따른 것이며 공통 계약·Schema·Backend 핵심·A/B 원본·Robot 설정은 보존했다. 지정 브랜치/HEAD 유지, commit/push/PR/merge/장치 실행 없음. 실제 C의 최신 Current 기반 응답 생성, B 실제 관측/전달판·촬영 판별, 실제 Robot/STOP·재개 연결은 미검증이다.
- 마무리 검사: 시작 파일 118개 중 이번 기존 파일 3개 외 115개와 Downloads 원본 두 개를 동일 해시로 보존했다. Python AST·JSON 원본 바이트/구문·공백·문서 코드 블록·로컬 링크 110개·git diff --check 종료 코드 0. [보존 검사 기록](../logs/c-saved-results-final/preservation-audit.json)을 남겼다. 원본/팀원 코드/장치 설정을 덮어쓰거나 이전 미완료 변경을 되돌리지 않았다.

## A–B–D 합성 입력 Qt 화면 시험 준비 (2026-10-06)

- 사용자 승인 범위: 실제 HMI 창에서 정상·불일치·가림·전달판 보류를 확인할 시험 준비. [abd_input_hmi.py](../app/abd_input_hmi.py)를 추가해 기존 Backend/Qt·실제 A plan_from_current·B 원본 deliver_example·Controller/Fake driver를 연결했다. 시작으로 Design/Plan 채택, 터미널 place_empty로 Fake 전달, 복귀 뒤 observe로 합성 관측을 한 번씩 공급한다. 실행/입력/화면 확인 순서는 [화면 시험 안내](D_ABD_SYNTHETIC_CALLBACK_TEST.md#합성-입력을-넣으며-qt-화면-확인하기-2026-10-06)에 있다.
- 정상 3-Step 마지막 Fake 전달 뒤에는 2/3 대기, 마지막 observe 후에만 3/3 완료다. 불일치/빈 영역은 실제 합성 Current 또는 미배치 차이를 유지하며 의도 대기, 이번 목표 가림은 기존 Current 유지/보류, 아래층만 가림은 이번 목표 완료를 허용한다. 전달판 판단 불가는 새 after=null check에서 별도로 넣고 EMPTY 전 추가 집기 없음을 확인한다. 가림 사전 Current와 추가 위치의 D 합성 프레임은 source/이벤트로 표시한다. Fake STOP/재개 및 옛 check 거절을 확인했다.
- 신규 연결 검사 **17개**, 관련 검사 **59 passed**, 최종 전체 **792 passed**, 종료 코드 0. 실제 CLI의 명시 모드/입력 오류·보류/EOF 종료와 DISPLAY=:0 native 창 열기/EOF 종료를 확인했다. native 실행은 시작 버튼/Job/전달 없이 끝났으며 화면 상태는 offscreen Qt/PNG로 확인했다. [산출물 색인](../logs/abd-hmi-final/summary.json), Job JSONL·snapshot JSON·화면 PNG·JUnit을 logs에 남긴다. 첫 테스트 속성명 오류와 전달판 캡처 파일 덮어쓰기 문제를 수정했고, 추가 마지막 Step 검사에서 D 작성 3층 합성 프레임의 visible/verified 층 불일치를 찾아 그 프레임을 고쳤다. Consumer/assertion을 변경하지 않고 영향 검사를 재실행했다.
- 이번 파일은 신규 진입점/검사와 기존 안내/STATUS 네 개다. 실행 파일 198줄·신규 class 1개이며 약 500줄 규모의 검토 이유는 대화형 callback 연결과 외부 결과 검증이다. application 핵심/Schema/Fixture/A/B 원본/장치 설정/기존 변경은 보존했고 새 dependency/framework/DB/통신은 없다. C Mock·B 합성 자료·Robot FAKE다. B 생산 코드/실제 Camera·Robot/실제 C·실제 STOP/재개 통과를 의미하지 않으며 GitHub 게시/PR/merge/장치 실행 없음.
- 마무리 검사: 신규 Python AST·공백·문서 코드 블록·로컬 링크 115개·산출물 JSON·git diff --check, 종료 코드 0. 시작 파일 116개 중 이번 두 문서만 갱신되고 나머지 114개를 동일 해시로 보존했다. 새 파일은 위 실행부/검사 두 개뿐이다(`/tmp/c2-abd-hmi-audit.json`). lint/type는 미구성이며 새 검사 도구를 설치하지 않았다.

## B production callback 후속 연결 착수 확인 (2026-10-06)

- 사용자가 집중 검사 **166 passed**를 직접 재현한 뒤 다음 단계 진행을 요청했다. 원격 PR 목록과 PR #10 head 전체 파일 트리를 다시 조회했으나 `c75c80374b848a395fded62ad901020d06b92913` 그대로이며 B 제공 범위는 합성 예시 18개다. 실제 관측 생산 코드/등록 callback/별도 전달판 전달 함수는 아직 없다.
- 사용자 확인: 추가 B 구현은 아직 없으며 현재 커밋에 올라온 코드가 전부다. 실제 생산자 연결은 B 구현 제공 후 이어간다.
- D의 vision 요청(check_id/after, after=null 포함), on_observation, on_place 및 실패/지연 확인 지점을 [후속 연결 기록](D_ABD_SYNTHETIC_CALLBACK_TEST.md#후속-production-callback-연결-착수-확인-2026-10-06)에 정리했다. BLOCKER: 실제 B 실행 코드 위치 미제공. REQUIRED CHANGE: 홍동의 실제 구현 PR/커밋 또는 로컬 경로 제공 후 해당 생산 함수를 기존 D 경계와 연결. AFFECTED INTERFACE: B 촬영 요청/Observed callback/전달판 결과. REASON: 현재 PR은 JSON 저장·callback 합성 예시이며 실제 인식 생산 모듈이 아니다.
- 이번 변경은 이 STATUS와 기존 검사 기록 두 문서만이다. application/Schema/Fixture/팀원 코드/브랜치/기존 미완료 변경을 보존했고 새 통신·B 알고리즘·장치 실행·Git 게시/병합은 수행하지 않았다. 문서 링크·코드 블록·공백·diff와 파일 보존을 확인했다. 새 pytest 실행은 없으며 직전 합성 166/775 통과를 production 연결 완료로 재사용하지 않는다.

## A–B–D 합성 JSON callback 통합 검사 (2026-10-06)

- [B PR #10](https://github.com/suuuhululu/C-2/pull/10) head `c75c80374b848a395fded62ad901020d06b92913`의 변경 18개를 원본대로 가져왔다. 실제 인식 코드가 아닌 합성 JSON/로컬 callback 예시다. [PR #9](https://github.com/suuuhululu/C-2/pull/9) head `a825e2d6b7440a4ab77fb5c02540484e04dd3acc`와 대조해 A·planning_connection·Current·completion·replan이 동일함을 확인하고 이후 로컬 REAL/HMI 변경을 보존했다. 개발 브랜치와 HEAD `7af9daeb3812f9e87fb36f172293434fd827e42f`는 유지했다.
- 실제 A `plan_from_current(design,current)` → D status/plan/errors 채택·보류 → FakeRobot 성공 → B 원본 `deliver_example()` callback → D Current/Expected/Step → snapshot·Qt offscreen·JSONL을 연결했다. 저장 Plan 주입, C 실제 함수, 실제 카메라/Robot 호출은 없다. B에 없는 별도 진단 전달 함수/ROS/HTTP를 구현하지 않았다. 전달판 state/reason은 검사 내부 최소 변환으로 기존 on_place에 전달했고 전체 진단 제안을 공통 필수 계약으로 확정하지 않았다.
- 정상 일치·불일치 실제 Current 채택/의도 대기·확인된 빈 영역·이번 목표 가림·아래층만 가림·전달판 UNOBSERVABLE·부분 Current/Mock Revised 실제 A 재계획·닫힌/역순/중복 check/seq를 검사했다. after=null 전달판 요청과 새 EMPTY 필요성을 확인했고 마지막 전달만으로는 2/3 대기, 마지막 관측 확인 후에만 3/3 완료다. 자세한 입력·결과·명령·커밋·제한은 [통합 검사 기록](D_ABD_SYNTHETIC_CALLBACK_TEST.md)에 있다.
- 최종 집중 **166 passed**, 종료 코드 0 (신규 A–B–D 16 + B 원본 14 + 기존 A–D 24 + A 독립 112). 전체 **775 passed**, 종료 코드 0. B CLI 7묶음 출력/종료 코드 0. 첫 검사 준비 오류 두 건은 실제 A 층 정렬과 Fake tuple 접근을 수정해 재검사했다. [결과/소스 해시 색인](../logs/abd-callback-final/summary.json), 사례별 result.json·Job JSONL·HMI PNG와 JUnit을 logs에 남겼다. logs는 Git 제외다.
- 이번 작성분은 신규 통합 검사/기록과 이 STATUS 세 파일이며 B 원본 18개를 별도로 구분한다. application·공통 계약·Schema·팀원 원본·장치 설정은 수정하지 않았다. lint/type 미구성, 새 dependency/framework/DB/class 없음. B production callback/별도 전달판 수신 경로·실제 보정/촬영 안정 조건·Robot 정지/촬영 신호·C 실제 함수 연결은 blocker다. 합성 callback 통과를 인식 성능·Camera/Robot 통합 통과로 표시하지 않는다. commit/push/새 PR/merge/장치 실행 없음.
- 마무리 확인: B 원본 18개를 고정 커밋 원격 내용과 바이트 대조했다. 시작 시 기존 파일 96개 중 STATUS만 갱신했고 나머지 95개를 동일 해시로 보존했다(`/tmp/c2-b-callback-audit.json`). 이번 작성 Python AST·공백·Markdown 코드 블록·문서 로컬 링크 102개·산출물 JSON·git diff --check 검사 종료 코드 0. 실제 Qt 화면에서 노랑 목표/파랑 관측 불일치와 전달판 판단 불가/사유 표시를 시각 점검했다.

## 잘못 놓음 수동 입력·좌표 비교·확인 전 완료 방지 검수 (2026-10-06)

- 사용자 요청: 잘못 놓았다는 터미널 신고를 남기고 HMI에 현장 좌표와 목표를 비교. 시험 좌표 **(9,5)**, 적용 검수는 **S03/목표 (7,5), 파랑 4점·1층·0°**. 마지막 조립 확인 전에 완료가 표시되는지도 검수했다. C 때문에 입력/표시가 막히는 것은 아니며, 실제 배치 제공은 B 또는 현장 입력, 목표 생성/수정은 C, Current/Difference/표시는 D 책임이다. 목표 변경/정리 후 재개·Robot MOVE까지 범위를 확대하지 않았다.
- 변경: 기존 REAL 진입점의 assembly `confirmed:false`를 수동 불일치 신고로 로그·HOLD 처리한다. 좌표가 없는 신고는 Current/관측/Step을 변경하지 않는다. actual 여섯 필드가 있으면 기존 조립 유지와 목표 영역 확인을 전제로 수동 Observed를 만들고 기존 Backend 계산으로 실제 Current/차이를 반영한다. Expected/전체 Design/미확인 Step을 목표 기준으로 유지한다. C/HRI 실제 미연결을 유지하고 자동 KEEP/추가 전달/완료하지 않는다.
- HMI: 선택 표시 필드 reported_placement를 snapshot·Consumer·Schema에 명시했고 REAL 수동 MISMATCH 및 해당 Observed에 포함된 배치만 허용한다. Qt는 그 블록을 현장 입력 열에 보여주고, 목표 채움과 실제 입력의 빨간 테두리를 그린다. Actual/목표 좌표·층·색상·방향이 비교되며 물리 블록 대응/기하/완료를 Qt가 계산하지 않는다. Camera 미연결 표시를 유지한다. [실행·제한 안내](D_BACKEND_RUN_ROBOT_PLAN.md)에 입력과 새 실행 필요 조건을 갱신했다.
- 실제 검사: 최종 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` → **745 passed**, 종료 코드 0. 관련 REAL 파일은 38개 검사(기존 18 + 신규 20). 첫/두 번째/세 번째 Step의 좌표 없는 신고와 실제 배치 신고, Current 유지/실제 채택·revision·고정 기준·Step 미완료·차이·다음 집기 없음·중복/옛 결과 거절·JSONL/Schema/화면을 확인했다. 같은 위치 색상 불일치, 잘못된 Boolean·필드/범위·이전 블록 겹침·목표와 같은 actual·정상 확인에 actual·표시 출처 불일치·로그 실패도 검사했다.
- **마지막 확인 전 완료 검수:** 세 번째 전달·복귀 성공만으로는 Qt **WAIT_ASSEMBLY/사람 조립 관측 대기·2/3**, Current revision 2 유지, JOB_COMPLETED 없음. (9,5) 신고 뒤 **HOLD·2/3**, 실제 Current revision 3·위치 (9,5) 채택/목표 (7,5) 유지, 완료 이벤트/다음 전달 없음. 정상 마지막 확인을 별도로 입력한 경우에만 COMPLETE·3/3이다. 검사 assertion을 삭제/완화하지 않았다. [확인 전 화면](/tmp/c2-s03-before-confirmation.png), [신고 후 화면](/tmp/c2-s03-misplaced-preview.png), `/tmp/c2-s03-misplaced-65t4o8vb/result.json`과 같은 폴더의 stdout/Job/모의 driver 로그, 종료 코드 0. 실제 A·Qt·모의 QProcess이며 장치 호출/실행은 없다.
- 범위 **9개 기존 파일**: real_workflow_hmi·snapshot·hmi_contracts·hmi Schema·Qt·BoardView·해당 통합 검사·이 STATUS·실행 안내. 약 350줄 규모 검토 신호이며 신규 파일/class/dependency/framework/DB 없음. 수신 검증과 신고 결과 처리는 책임별로 분리(45줄 receive/18줄 report), 실행 모듈 188줄. 검사 파일 407줄은 실제 계약/외부 결과를 검증하는 테스트로 정책의 Test Code Exception에 해당하며 application 분할/추상 계층을 추가하지 않았다. Backend/Current/Expected/A/Robot 제어·경로·설정은 변경하지 않았다. 사용자 입력 오류를 줄이려고 활성 ID·actual 여섯 필드가 있는 한 줄 양식을 출력하며 실제 좌표로 바꾸어 입력하도록 명시했다.
- 활성 REAL 창은 소스 수정으로 자동 갱신되지 않는다. 사용자 현재 Job/Robot/창을 중단·재시작하지 않았으며, 소모 슬롯이나 이전 check를 새 Job에 재사용하는 지시를 하지 않았다. 새 코드에서 같은 Job을 이어받는 종료 후 복구는 미지원이다. 현재 사용자가 진행 중인 세 번째 REAL 실행의 오류 처리 성공으로 이번 모의 검수를 표시하지 않는다. 아직 Camera/B 실제 인식·수정 후 재관측/재개·C/HRI 의도/목표 변경·REAL STOP/재개는 미연결/미검증이다. 다음 단위에는 실제 관측/현재 상태를 공급하는 홍동 반환 또는 명시 수동 재관측 입력과 정리 후 진행 규칙을 검토해야 한다. commit/push/PR/merge/실제 Robot 동작 없음.
- 마무리 검사: 해당 Python/JSON 구문·공백·문서 링크 101개·코드 블록·git diff --check, 종료 코드 0. 시작 해시와 비교해 위 9개만 변경되고 범위 밖 기존 87개 및 원본 제어/설정/A를 보존했으며 신규 파일은 없다(`/tmp/c2-misplaced-report-audit.json`). lint/type는 미구성이고 새 검사 도구를 설치하지 않았다.

## REAL 3 Step 현장 수동 확인 진입점 구현·독립 검증 (2026-10-06)

- 사용자 답변: **3개 블록을 한 번 조립/총 3회 전달**, 슬롯 모두 충전, 색상/슬롯 임의 선택 허용, 다음 전달 전 현장 조립/전달판 확인은 터미널 입력. 재현 가능한 첫 시험으로 **파랑 4점 공급 슬롯 1→2→3**을 사용한다. 사용자가 노랑 2번 및 파랑 5번 전달·observe 복귀를 확인한 것과 이번 신규 세 슬롯의 실제 시험을 구분한다.
- 변경: [진입점](../app/real_workflow_hmi.py)에서 가짜 C 3블록 → 실제 세은 A → 기존 Backend → 같은 REAL Qt 화면 → 기존 한 블록 CLI를 연결했다. START는 Design/Plan 채택·전체 목표/현재 Step/0/3 표시까지만 한다. 최초 `place_empty` 수동 입력이 첫 실제 이동을 시작하고, 복귀 후 각 `assembly` 수동 입력이 Current/Step을 확인한다. 첫/두 번째 확인 뒤 다음 실제 전달, 세 번째는 누적 Current/Design 대조와 수동 확인 3/3으로 끝난다. Robot 성공만으로 조립 완료하지 않는다.
- 관측 경계: 홍동 Camera/B는 미연결이다. 수동 확인은 **기존 조립 유지 + 현재 목표 일치 + 전달판 비움 + 손/장애물 여유**의 운영자 확인이며, `MANUAL_FIELD_CONFIRMATION`과 REAL 현장 수동/Camera 미연결 표시를 남긴다. 정상 매 Step HMI 확인 버튼을 추가하지 않았다. 실제 차이/불확실은 true를 보내지 않고 보류한다. 수동 입력을 Camera의 실제 반환/독립 안전 판별로 표시하지 않는다.
- Controller는 집기 확인 때만 슬롯을 한 번 소모하고 실행마다 증거를 초기화한다. 서로 다른 실행 ID, observe 복귀/종료 후 다음 실행, 설정 고정, 최대 3회, 실패 후 추가 집기/재개/두 번째 Job 차단을 유지한다. 실제 STOP/재개는 미검증으로 비활성화한다. Robot 경로·pose·TCP/tool·속도·원본 측정·설정 JSON·A 원본은 변경하지 않았다.
- 신규 검사 **18 passed**, 최종 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` → **725 passed**, 각각 종료 코드 0. 정상 실제 A 3 PLACE·같은 REAL 화면의 3블록/3회·슬롯 1/2/3·실행 ID·수동 전 Current 불변·revision 1/2/3·전체 완료·JSONL을 확인했다. 시작 전/실행 중/옛 check/중복/미확인 입력, 유효하지 않은 C/A 기하 결과, 이전 실행 result·4번째 전달, 집기/놓기/복귀 증거 재사용, driver 실패/비정상 종료/설정 변경/로그 기록 실패에서 추가 집기 차단을 검사했다. 초기 중복 거절 메시지와 같은 색 기존 블록의 이동 모호성 실패를 실제 재현 후 수정했으며 assertion을 완화하지 않았다. 수동 Observed는 운영자가 유지 확인한 누적 Current와 현재 목표를 함께 기록해 이동 여부를 추정하지 않는다.
- 실제 진입점 `main`/stdin reader/Qt 버튼/queued 입력/실제 A/Backend/모의 QProcess로도 3회 전체를 실행했다. `/tmp/c2-real-three-main-smoke/result.json`, 해당 `logs/`의 Job/모의 driver JSONL, [S01 화면](/tmp/c2-real-three-step-preview.png), [완료 화면](/tmp/c2-real-three-complete-preview.png), 종료 코드 0. ROS/Robot 이동/Camera 호출 없음. 기존 파랑 공급열로 슬롯 1/2/3 각각 **18 명령·15 이동 요청·집기 1회·동일 observe 종점**의 계획 생성만 확인했다(`/tmp/c2-real-three-offline-plan.json`, 종료 코드 0). IK/FK·충돌/실제 놓임 검사로 확대하지 않는다. 실제 장치 조회는 사용자 실행 시 기존 CLI가 수행한다.
- 범위 **11개 파일**: 신규 `app/real_workflow_hmi.py`, `interfaces/fixtures/c_three_blue4.json`, `tests/integration/test_real_workflow_hmi.py`; 기존 Backend·단일 시험 Controller·snapshot·HMI Consumer/Schema·Qt 6개; 이 STATUS/실행 안내 2개. 신규 실행 모듈 147줄·검사 253줄·기존 확장과 문서 포함 약 600줄 규모이며 새 구체 실행 클래스 1개·검사 spy 1개, dependency/framework/DB/추상 계층 없음. 10파일/300줄 검토 신호를 사전 보고했고 단일 시험 재사용보다 이 연결이 필요한 이유는 Design/A/진행/슬롯/생산자·Consumer·Schema를 함께 검증해야 하기 때문이다. 기존 477줄 Backend는 작은 mode 분기만 확장했으며 무관한 분할/리팩터링하지 않았다. 사람 리뷰를 자체 검사로 대체하지 않는다.
- 작업 시작 파일 해시 대조에서 위 범위 밖 기존 파일은 보존됐다. 지정 수현 브랜치 유지, commit/push/PR/merge/실제 이동 없음. lint/type 설정은 미구성이며 새 도구를 설치하지 않았다. 실행 방법은 [REAL 3 Step 안내](D_BACKEND_RUN_ROBOT_PLAN.md#real-3-step-가짜-c--실제-a--backendhmi--현장-수동-확인-2026-10-06)다. 아직 실제 3회 전달/현장 조립, Camera 시야/촬영/EMPTY/Observed, 실제 C/음성/HRI, REAL STOP/재개·실패 복구는 검증하지 않았다. 다음 제공물은 홍동의 실제 촬영/Observed/전달판 반환과 현장 세 슬롯 시험 로그이며 공통 필드를 다시 작성하라는 요청이 아니다.
- 마무리: 이번 Python AST·JSON 구문·11파일 공백·관련 문서 링크 96개·코드 블록 균형·`git diff --check`를 확인했다. 원본 A/Planner adapter/Robot 실행부·노랑/파랑 설정은 시작 해시와 같고 범위 밖 기존 파일 보존 및 신규 파일 3개만 확인했다. 감사 기록 `/tmp/c2-real-three-change-audit.json`, 종료 코드 0. `/tmp`와 logs는 로컬 시험 산출물이며 GitHub 게시물이 아니다.

## 3 Step 실제 전달 통합 시험 준비 — 실기 실행 전 (2026-10-06)

아래는 사용자 답변을 받기 전 준비 기록이며, 답변 반영/현재 실행 진입점은 위 절을 따른다.

사용자가 가짜 C Design을 3개로 늘리고 실제 공정을 반복하는 시험과 실행 명령을 요청했다. 현재 REAL 진입점은 단일 전달만 허용하므로 반복 실행 명령을 제공하거나 장치를 실행하지 않았다. 총 3회/9회 의미, 사용할 4점 색상·준비된 공급 슬롯, 실제 관측 미연결 상태에서 전달판 비움·사람 조립 확인 방법을 질문했다. 해당 답변과 REAL 3 Step 연결 검증이 필요하다.

독립 준비로 파랑 4점 3개짜리 **초안** C 응답을 실제 A에 넣어 READY/3 PLACE를 확인했다. 색상은 아직 실기 확정값이 아니다. 실제 A + 기존 D + Fake Robot/관측으로 전달 3회·Current revision 3·진행 3/3·COMPLETE를 확인했다. `/tmp/c2-three-step-real-preparation/draft_c_response.json`, `draft_a_result.json`, `fake_three_step_check.json` 및 `/tmp/c2-three-step-fake-check-iigxm2fh`의 Job 로그, 종료 코드 0. Robot/Camera 동작 없음, 실제 3회 전달·조립 성공 아님. 실행 코드·A 원본·Robot 경로·설정은 수정하지 않았고 GitHub 게시/커밋 없음.

## 수동 입력 정지·재개 누락 및 REAL 전달 대상 표시 수정 (2026-10-06)

- 사용자 재현: FAKE 수동 입력 창은 STOP 요청을 출력만 해 `STOP_PENDING`에 머물렀고 재개가 비활성화됐다. `step_input_hmi.py`에 장치 없는 모의 정지/복귀 응답을 Qt timer로 연결하고 새 Planner 요청 ID를 추적한다. 같은 Job·키워드/후보 Design/채택 Plan·Current를 유지하며 재개한다. 정지 중 입력은 계속 거절한다. 공통 Backend 정지/실행 완료 검사와 실제 Robot 제어는 바꾸지 않았다.
- REAL 화면: 해당 창은 별도 단일 전달 시험이므로 다른 FAKE 창의 Design/Plan을 받지 않는다. 단일 시험 Controller의 `transfer_target={brick_type,color,slot}`를 Backend snapshot → HMI Consumer/Schema → Qt로 전달해 **파랑 4점 5번의 그림/종류/색상/공급 슬롯/고정 전달판 목적지**를 표시한다. 진행 메시지가 바뀌어도 대상 안내를 유지한다. 조립 Design/좌표/층/방향은 미채택, Current/조립 완료는 그대로다. 이 필드는 REAL 단일 전달의 선택적 표시 정보이며 공통 Robot goal/result·팀 조립 계약을 바꾸지 않는다.
- 검사: 수정 전 시작 직후·키워드 후·Design 후·Plan 후 STOP 회귀 4개에서 같은 HOLD 오류를 재현했다. 수정 후 각 단계 반복 STOP/재개·새 요청 ID·Plan 계속 입력·재집기 없음이 통과했다. 실제 main/stdin/Qt 버튼으로도 후보 저장 → 정지 → 재개 → Plan 채택/3개 목표/0/3/종료를 확인했다. `/tmp/c2-step-input-stop-main-result.json`, `/tmp/c2-step-input-stop-main-logs/607c3284-9325-440a-aca8-23ded27b6216.jsonl`, 종료 코드 0.
- 전달 대상 검사 5개 추가: 조회 전/준비/전달 중/끝난 뒤 동일 5번 대상과 파란 그림 실제 렌더링, 조립 배치/완료 미생성, FAKE로 전환 시 전달 그림 제거, 슬롯/색상/배치 필드/모드 오류 거절. 관련 두 파일 **28 passed**, 최종 전체 **679 passed**, 각각 종료 코드 0. 전체 수치는 다른 동시 작업의 검사 증가가 포함된 현재 저장소 결과이며 이번 신규 회귀는 9개다. Schema 검사는 설치된 jsonschema의 로컬 참조 resolver를 사용했다. 미설치 referencing 및 공통 Schema URN/상대 URI 매핑 문제를 검사 코드에서 해결했고 dependency/검사 기준을 추가·완화하지 않았다.
- 수정 화면 `/tmp/c2-real-transfer-target-preview.png`는 모의 프로세스로 렌더링했다. ROS 이동/조회 없이 표시만 검증했으며 실제 파랑 성공·STOP/재개 성공을 주장하지 않는다. 사용자가 실행 중인 REAL 프로세스는 중단/재시작하지 않았다. 새 코드는 기존 실행 창에 자동 반영되지 않으므로 전달/복귀 종료 후 다시 열어 확인한다. 창 열기는 조회만 하며 표시 확인을 위해 START를 다시 누를 필요가 없다.
- 범위 11개: 수동 입력/검사 2개, 표시용 Board·Qt·단일 시험 Controller·snapshot·HMI Consumer/Schema·REAL 검사 7개, 이 STATUS/실행 안내 2개. 표시는 필드 생산자와 Consumer·Schema·그림까지 함께 검사해야 해 여러 파일을 건드렸으나 새 class/dependency/framework/DB/Robot 경로는 없다. 기존 Backend·trial·블록/슬롯 설정·다른 작업을 보존한다. GitHub 게시/커밋 없음. 실제 Design/Plan 기반 Robot 전달·Camera/사람 조립·REAL STOP/재개는 이번에 연결하지 않았다.
- 마무리 검사: 이번 Python/JSON 구문·공백·관련 상대 링크 88개·코드 블록·`git diff --check` 확인, 지정 브랜치 유지. 실제 trial 실행 코드와 파랑 슬롯 설정은 작업 시작 해시와 동일하다. Backend에는 다른 동시 작업의 변경이 감지돼 원본 해시 동일 주장에서는 제외하고 되돌리거나 수정하지 않았다.

## 터미널 단계 입력 FAKE HMI (2026-10-06)

사용자가 시작 후 가짜 음성 키워드 → 그 키워드의 Design Fixture → 해당 Design의 Plan Fixture를 직접 넣어 단계별 확인하도록 요청했다. 신규 [step_input_hmi.py](../app/step_input_hmi.py)는 기존 Qt/Backend/JSONL을 재사용하고 stdin JSON을 Qt thread로 전달한다. 필수 `--fake-inputs` 모드이며 ROS/실제 Robot/LLM/Planner를 호출하지 않는다. 실제 생성/경로 계산으로 표시하지 않으며 Plan은 사람 조립 순서다. REAL 한 블록 시험 창은 별도 실행한다.

- 입력: 시작 → `keyword.text` → `design.file/key` → `plan.file/key`. 후보 Design만으로는 미리보기/목표를 채택하지 않는다. 유효한 Plan과 함께 채택한 뒤 전체 Design·S01 목표·0/3을 표시하고 첫 전달판 확인 결과를 기다린다. 자동 관측/Robot 전달/완료 없음, Current revision 0 유지.
- [신규 검사](../tests/unit/test_step_input_hmi.py) 8개: 정상 채택/후보 미표시/화면 갱신, 시작 전·순서 오류·없는 파일·잘못된 Plan·중복 후보·닫힌 요청 거절, 실제 stdin reader thread의 잘못된 JSON/비객체 거절과 Qt 전달. REAL HMI 검사와 함께 **19 passed**, 종료 코드 0. 초기 화면 assertion 실패는 Qt queued signal 처리 전에 검사했기 때문이며 이벤트 처리 후 동일 assertion으로 확인했다. 화면 안내도 queued snapshot의 질문/사유 영역에서 유지한다.
- 최종 전체 `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` → **558 passed**, 종료 코드 0. 실제 `main`/stdin pipe/Qt 시작 버튼/이벤트 루프로 세 입력을 처리해 Design 3개·S01·0/3·HOLD(전달판 관측 대기)·Ctrl+D 종료를 확인했다. `/tmp/c2-step-input-main-result.json` 및 `/tmp/c2-step-input-main-logs/ba053157-c74d-41b5-865e-c76006c557b5.jsonl`에 기록했다. 첫 임시 실행 검사는 존재하지 않는 WAIT_PLACE 상태를 기대해 실패했으며 기존 HOLD/WAIT_PLACE_EMPTY 의미를 확인한 뒤 실행을 다시 검사했다. 제품 상태 계약은 바꾸지 않았다. 1920×1080 논리 화면 기준 반폭 offscreen 미리보기 `/tmp/c2-step-input-hmi-960.png`도 확인했다. 실제 모니터·장치 증거는 아니다.
- 실행 방법과 세 JSON 입력은 [실행 안내](D_BACKEND_RUN_ROBOT_PLAN.md#시작-후-터미널에서-가짜-키워드designplan-입력)에 기록했다. 이 추가 단위는 실행/검사 2개와 관련 기록만 수정한다. 새 dependency/framework/DB/Robot 경로 없음. 아래 REAL HMI 변경과 함께 이번 작업 파일은 총 15개다. 실제 팀 생성 결과·촬영·자동 전달·조립 검증은 연결하지 않았다.
- 마무리: 이번 파일 15개의 Python/JSON 구문·관련 문서 상대 링크 102개/코드 블록·`git diff --check`, 원본 제어/측정 SHA 일치를 확인했다. 초기 해시 대상 77개 중 이번 기존 파일 10개 및 다른 작업 변경 9개를 제외한 58개가 보존됐다. 지정 브랜치/HEAD `7af9dae` 유지, 커밋/게시/Robot 이동 없음. lint/type check 미구성이다. 수동 입력의 처리 객체와 Qt signal bridge 두 클래스는 입력 순서 처리와 GUI thread 전달에 필요한 구체 클래스이며 별도 추상 계층이 아니다. REAL Controller와 함께 신규 클래스 3개·큰 Backend 파일은 정책의 사람 리뷰 신호로 기록한다.

## 실제 한 블록 HMI 연결·파랑 4점 5번 첫 시험 준비 (2026-10-06)

사용자가 노랑 4점 2번의 실제 픽앤플레이스와 observe 복귀를 확인했고 HMI 연결을 요청했다. 다음 대상으로 **파랑 4점 5번**을 선택하고 미실기 좌표도 바로 시험하며 배우겠다고 명시했다. 이 최신 지시에 따라 파랑 1/6번 측정 끝점과 기존 보간/경유 코드를 사용한 **첫 실기 시험 설정**을 준비했다. 파랑 5번이 이미 검증됐다고 기록하지 않는다. HMI 첫 실제 실행은 아직 사용자가 누르지 않았으며 에이전트는 조회만 수행했다.

### 변경과 연결 경계

- 신규 [real_trial_hmi.py](../app/real_trial_hmi.py): 기존 Qt 창·Backend에 단일 시험 Controller/QProcess를 연결한다. 창 열기는 실제 조회만 실행, 조회/현재 실제 observe FK 확인 뒤 준비 확인·시작으로 한 블록만 실행한다. Qt thread에서 ROS 이동을 동기 대기하지 않는다. 활성 프로세스 중 창 종료로 이동을 끊지 않는다. STOP/재개 버튼은 미실기 검증 상태를 명시하고 비활성화한다.
- Backend·snapshot: REAL은 명시 `single_trial=True`와 같은 REAL Controller 바인딩으로만 허용. 기존 goal/result 3필드 유지, 한 Job/실행 UUID·중복 START/늦은 결과/추가 전달 차단. 슬롯은 Controller가 driver의 집기 이벤트로 갱신하며 Backend/Qt가 계산하지 않는다. 전달 뒤 HOLD(조립 미확인), Current/revision·조립 진행 0 유지. Planner/Design/Observed Fake를 REAL에 연결하지 않는다.
- HMI Schema/Consumer·Qt: REAL 표시와 제한된 단일 시험의 버튼/0진행 규칙을 추가했다. 예전 Fake 전체 조립 snapshot의 mode만 REAL로 바꾸는 입력은 계속 거절한다. 준비/작동/집기·놓기·복귀/오류를 같은 화면/JSONL에 표시한다. Plan/Design은 미채택으로 표시하고 카메라/조립 완료를 만들지 않는다.
- [robot_trial_blue5.json](../interfaces/robot_trial_blue5.json): 자료의 `blue_4.start/end`를 그대로 복사하고 측정 파일 경로/해시를 고정. `pick_line`은 해당 공급열만 지정하며 노랑 값으로 대체하지 않는다. 5번 XYZ는 `[-580.9066,91.1324,-10.2376]`, 자세는 원본 Slerp로 계산한다. 잘못 복사된 blue posj는 사용하지 않고 기존 IK 해 분기의 IK/FK 검사로 진행 여부를 정한다. 원본 파일/TCP/tool/속도/고정 전달 위치/HOME·observe 값은 유지했다. 공급열 변경은 사용자 요청에 따른 새 실기 시험이며 경로 충돌/집기 성공을 조회만으로 보증하지 않는다.
- 입력 설정은 조회 당시 복사본과 START 시 파일을 대조해 실행 중 변경을 반영하지 않는다. HMI START는 **이번 대상 블록 준비·전달판 비움의 사람 확인** 의미이며 이때 실행 복사본에 해당 flag를 기록한다. 자동 조회나 Fake가 물리 확인을 대신하지 않는다. 단일 실행 후 START를 다시 허용하지 않으며 재개/앱 종료 후 이어하기는 없다.

### 실제 검증

- 노랑 4점 2번 실기: [사용자 실행 로그](../logs/robot_trials/5969d3bf-047e-4011-b725-0c3dc20f2c82.jsonl)의 집기 확인/다음 슬롯3·놓기·복귀·success=true와 현장 사용자 확인을 대조했다. 관측 Actual FK `[400.9931,8.6160,315.1089,175.1950,-179.5748,175.6306]`·대기/이동 없음·빈 그리퍼 기록이다. 사용자 출력은 쉘 프롬프트로 정상 복귀했으며 직접 종료 코드는 제공되지 않았다. 전체 조립/STOP/재개 통과로 확대하지 않는다.
- 파랑 5번 실제 **무이동** CLI: 현재 실제 observe 시작 검사·**40점 IK/FK·15개 ROS 이동 메시지 변환** 성공, 종료 코드 0. 로그 `/tmp/c2-blue5-check-logs/0d3f6b58-d114-4979-82c5-401b240672af.jsonl`. 파랑 경로 충돌/실제 집기·놓임은 미검증이다.
- 실제 QProcess↔ROS/RG2 조회↔Backend↔Qt: offscreen HMI로 같은 파랑 설정을 연결했다. 자식 인자는 `--check --require-observe-start`, Job=null·실행/이동 없음·REAL 표시·시작 활성·정지 비활성 확인, 종료 코드 0. `/tmp/c2-blue5-real-hmi-preview/result.json` 및 해당 driver JSONL에 `ROBOT_CHECK_COMPLETE`까지 있고 `ROBOT_TRIAL_STARTED`는 없다. [화면](/tmp/c2-blue5-real-hmi.png)을 시각 점검했다.
- 신규 모의 프로세스/Backend/Qt 검사 11개: 조회/실행 분리, 단일 START·같은 goal/ID, 집기 1회/다음 슬롯, 실패/증거 누락/비정상 종료/잘못된 로그·보류/재시도 없음, 설정 변경/다른 공급열 거절, 중복 pick/result·늦은 결과, 활성 실행 중 창 유지, 정지/재개 요청 차단을 확인했다. 관련 기존 검사와 파랑 측정/해시 3개 보완 포함 **146 passed**, 종료 코드 0. 과거 Fake FULL→REAL 입력 검사도 유지했다. 신규 테스트 helper 이름이 pytest의 module setup으로 인식된 오류와 제한 REAL 버튼 표/공개 BoardView 속성 대조를 수정 후 재검사했다. assertion을 삭제하거나 약화하지 않았다.
- 최종 전체 `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` → **550 passed**, 종료 코드 0. 이전 중간 전체는 525개였고 다른 작업의 검사 보완 25개가 함께 반영된 현재 저장소 수치다. 관련 146개 결과와 구분한다. lint/type check/CI 미구성, 새 dependency/framework/DB 없음. 실제 STOP/재개·긴 이동 중 HMI STOP·Camera/홍동 EMPTY/관측·사람 조립·전체 Design 채택 연결은 다음 별도 단위다. Backend/driver 로그 실패 뒤 추가 실행은 차단하지만 이미 실행 중인 독립 CLI의 정지/복구는 현재 HMI가 제공하지 않는다. 이를 완성된 Day4 REAL Controller로 표시하지 않는다.

### 이번 파일·범위와 다음

이번 파일은 신규 실행부/파랑 설정/검사 3개, 기존 Backend·snapshot·HMI Consumer/Schema·Qt·trial·trial 검사 7개, 이 STATUS·실행 안내·설계 3개로 **13개**다. 파랑 첫 시험 요청으로 최초 계획의 11개에서 설정/측정 검사 범위가 늘었다. 실행 파일 신규 클래스는 실제 QProcess Controller 1개뿐이며 Factory/추상 driver 계층은 없다. 기존 Backend 규모 검토/사람 리뷰 요구는 유지한다. 사용자 설정/실기 원본·측정 파일/실패 기록을 보존하고 GitHub 게시/커밋/PR/merge는 하지 않는다.

동시에 `app/contracts.py`, `app/fake_demo.py`, `app/replan.py`, `tests/unit/test_replan.py`, `tests/unit/test_qt_hmi.py`, `interfaces/schemas/day4.schema.json`, `docs/D_BACKEND_PROGRESS.md`, `docs/06_CONTRACT_DRAFT.md`, `docs/09_C_B_BACKEND_HANDOFF.md`에 다른 작업의 변경이 감지됐다. 에이전트는 이 9개를 수정하지 않았고 이번 파일 목록/검증 범위에서 별도로 구분한다. 그 변경을 되돌리거나 수현 HMI 변경으로 표시하지 않는다.

다음은 아래 실행 안내대로 HMI에서 파랑 5번 한 번을 시험하고 실제 놓임/observe 복귀 결과를 기록하는 것이다. 자동 다음 전달·정상 매 Step 확인 버튼·DB·실제 STOP/재개 시험은 추가하지 않았다. 홍동에게 필요한 제공물은 실제 촬영/전달판/Observed 생산자이며 기존 공통 필드 재작성 요청은 아니다.

## Robot 6단계 첫 실행 실패 — ROS float64 타입 수정 (2026-10-06)

사용자가 현장 설정의 `empty_place_and_slot=true`를 저장하고 단일 전달을 실행했다. 사전 IK/FK 37점 검사는 성공했으나 첫 HOME 요청의 ROS C 변환기에서 `PyFloat_Check(field)` assertion으로 프로세스가 abort됐다. **한 블록 전달/observe 복귀는 성공하지 않았으며 실제 재실행은 아직 하지 않았다.**

- 원인: JSON의 `joint_speed=20`, `joint_acc=20`이 Python int로 원본 `movej`에 전달됐다. 원본 CLI는 argparse float였으나 새 설정 연결부가 이 차이를 처리하지 않았다. 설치된 `_move_joint_s.c` 85행은 `vel`의 Python float 검사이며 `acc`도 같은 조건이다. 원본 제어·TCP·pose·속도 값의 문제가 아닌 새 입력 경계의 타입 오류다.
- 수정: [robot_trial.py](../app/robot_trial.py)에서 유효한 수치 설정과 observe pose를 float로 정규화했다. slot/식별/boolean은 그대로다. [회귀 검사](../tests/unit/test_robot_trial.py)는 정수 JSON 입력의 값 동일·ROS 실수 타입 변환·원본 입력 보존을 검사한다. 사용자가 바꾼 설정 JSON·기존 실기 원본은 수정하지 않았다.
- 실제 API 변환 검사: 원본 `RowRobot.movej/line` 호출을 같은 설정/목표로 재사용하고, 실제 `dsr_msgs2` Request와 `rclpy.serialize_message`로 **15개 이동 요청**을 직렬화했다. 이 검사에는 노드/클라이언트/이동 송신이 없다. `--check`와 실행 전 사전 검사에 포함하고 `ROBOT_REQUEST_CHECK` 이벤트로 기록한다. 기존 IK/FK 조회만으로는 이 오류를 찾지 못했던 검증 공백을 보완했다.
- 실제 결과: 관련 순수 검사 **105 passed**, 전체 offscreen 회귀 **511 passed**, 각각 종료 코드 0. 수정 후 실제 `--check` **37점 IK/FK·15개 메시지 변환 통과**, 종료 코드 0, [조회 로그](/tmp/c2-robot-ros-numeric-check-logs/26b78048-569d-42ca-aaa3-f1f3fdb2c09b.jsonl). 신규 이동/개폐/STOP 명령 없음. 실패 이후 조회는 robot_state=1·check_motion=0이다. 조회/직렬화 성공을 장치 전달 성공으로 표시하지 않는다.
- 실패 원자료: 사용자 조회 로그 `logs/robot_trials/90e51355-a0ba-48e2-9f5c-5e2d4e0a7b83.jsonl`, 실행 로그 `logs/robot_trials/efe81e4b-2329-42ca-b6c8-f69d7ca024a1.jsonl` 보존. 실행 로그는 첫 `ROBOT_TRIAL_COMMAND`(HOME)에서 끝난다. C assertion의 프로세스 abort는 Python 예외/STOP/finally를 실행하지 않아 최종 실패 result가 기록되지 않았다. 이를 정상 종료/정지 확인으로 채우지 않았다.
- 범위: 실행 파일·검사와 직접 관련 기록/실행 안내 4개만 변경. 설정 파일의 사용자 확인 변경을 보존하며 GitHub 게시/Robot 재실행 없음. 다음은 현장에서 같은 단일 전달을 재실행하고 실제 놓임/observe 복귀를 확인하는 6단계다. 7단계 실제 STOP/재개·촬영·HMI REAL binding은 여전히 미검증이다.

## Robot 5단계 — 실제 한 블록 시험 준비·무이동 연결 검사 (2026-10-06)

사용자가 Robot **6단계까지 승인**했다. 이번에는 5단계의 단일 시험 실행부와 실제 ROS/RG2 조회를 검증했다. **6단계 실제 전달은 현장 전달판 비움·2번 슬롯 블록·기존 속도/경로 확인 답변을 기다리며 아직 움직이지 않았다.** HMI는 기존 FAKE 연결이다.

- 파일: [robot_trial.py](../app/robot_trial.py), [robot_trial.json](../interfaces/robot_trial.json), [test_robot_trial.py](../tests/unit/test_robot_trial.py) 신규. 이 STATUS·[설계](D_ROBOT_CONTROLLER_DESIGN.md)·[실행 안내](D_BACKEND_RUN_ROBOT_PLAN.md)·[수현 기록](D_BACKEND_PROGRESS.md)만 갱신했다. 기존 Controller/Backend/Qt·공통 Schema·다른 담당/미커밋 자료는 수정하지 않았다.
- 입력/출력: 명시 REAL·검증 원본 경로/해시·슬롯 2·기존 속도/TCP/tool·사용자 observe posj/posx·현장 확인 → 기본 오프라인 계획 / `--check` 조회 / `--execute` 한 블록 전달과 HOME→observe 복귀 / 기존 3필드 result·독립 시험 JSONL. 전달 완료를 조립 Current/Step 완료로 기록하지 않는다. 공급 소모는 상승 후 grip 유지 확인 때 한 번 기록하며 기존 Job/Controller 공급에 연결하지 않았다.
- 재사용/조정: 원본 `--start-block 2`는 2~6번 연속 실행이다. 해당 슬롯 명령만 선택하고 원본 HOME 복귀와 사용자 검증 observe 경로를 연결했다. 원본 pose/TCP/tool/속도/궤적/보간 코드를 바꾸지 않았다. 설정 해시 입력의 초기 오타는 장치 생성 전 차단됐고 원본 실제 SHA-256으로 정정했다. ROS interface 조회 최초 실패는 기존 workspace 환경을 읽어 해결했다. 설치/build/driver 수정 없음.
- L1/Fake 검사: 신규 시험 입력·모드/설정 누락·소스 변경·한 슬롯 제한·정상 명령/속도·상승 후 집기 확인·미감지 집기·놓기/복귀 timeout·보류/재시도 없음·조회 시 이동/개폐 없음·JSONL 식별/로그 실패 차단 **25개**. 최종 전체 `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` → **510 passed**, 종료 코드 0. 기존 485개 포함. 새 클래스는 검사 spy 2개뿐이며 실행 코드의 새 클래스/추상 계층/dependency 0개. lint/type check/CI는 미구성이다.
- 실제 장치 조회: running real M0609/RG2 노드/서비스, robot_state=1(대기), check_motion=0, robot_mode=1, TCP=`GripperDA_v4`, tool=`ToolWeight0`, RG2 status=0/폭 62.1mm 확인. 이름 조회는 TCP 오프셋 측정을 대신하지 않으며 현장 사용자가 TCP/tool 변경 없음을 확인했다.
- 실제 무이동 `--check`: 기존 경로 **37개 표본점 IK/FK**, 사용자 observe 관절의 FK와 제공 posx 일치 확인, 종료 코드 0. [조회 로그](/tmp/c2-robot-stage5-check-logs/8a29e914-22ca-4d22-befa-b62dfb586db3.jsonl). **이동/그리퍼 개폐 없음**, 충돌/시야/전달 성공 증거로 확대하지 않는다.
- 현장 제공물: 노랑 4점 **2번**, 기존 배치 유지, onsite 감시/비상정지 가능 사람·TCP/tool 동일, 제공 observe 좌표와 기존 전달 경로→HOME→observe posj 복귀 검증을 사용자가 확인했다. 실행 직전 빈 전달판/해당 블록·기존 속도(20°/s·40/80mm/s) 확인만 남아 설정의 `empty_place_and_slot=false`로 차단한다.
- 규모/보존: 신규 실행 206줄·검사 251줄·설정 33줄과 직접 관련 문서 4개, 총 7개 파일만 이번 단위다. 기존 전체 시스템을 REAL로 바꾸는 대안은 Fake Vision으로 여러 실제 전달이 나갈 수 있어 단일 시험 경계를 사용했다. 문서 로컬 링크 113개·코드 블록·신규 파일 공백/구문·`git diff --check` 확인, 종료 코드 0. 작업 전 해시 74개 중 문서 4개 외 70개(실기 원본 4개 포함)가 그대로다. 지정 브랜치/HEAD `7af9dae` 유지. GitHub 게시/커밋/PR/merge 없음. 자체 검사는 사람 코드 리뷰를 대신하지 않는다.
- 남은 확인: 6단계 실제 한 번 전달 후 현장 블록 놓임/observe 복귀 확인. 7단계 실제 STOP/재개·이전 요청 종료·블록 상태, 긴 이동 중 HMI STOP, 네 공급열 전체, Camera/홍동 촬영/EMPTY·실제 Backend/HMI binding은 미구현/미검증이다. `move_stop` ACK·프로세스 종료를 실제 정지/재개 허용으로 바꾸지 않는다.

## Robot 4단계 — Controller ↔ Backend·JSONL·Qt Fake 연결 (2026-10-06)

사용자가 Robot 4단계까지 승인해 3단계를 독립 검증한 뒤 4단계를 연결했다. **현재 HMI 시작/정지/재개/보충은 Backend를 통해 Fake Controller/driver로 전달된다. 실제 Robot/ROS/Camera 연결/동작은 없다.**

### 이번 3·4단계 파일과 입출력

- 실행 파일: [robot_controller.py](../app/robot_controller.py), [fake_robot_driver.py](../app/fake_robot_driver.py), [backend.py](../app/backend.py), [fake_demo.py](../app/fake_demo.py), [snapshot.py](../app/snapshot.py). 기존 goal/result 3필드·stop/resume 요청과 공통 HMI Schema 유지. Qt 코드는 수정하지 않았고 기존 버튼/표시 소비 경계를 사용한다.
- 검사: [test_robot_controller.py](../tests/unit/test_robot_controller.py), [test_qt_hmi.py](../tests/unit/test_qt_hmi.py) 보완, [test_robot_backend.py](../tests/unit/test_robot_backend.py) 신규. 다른 담당/기존 검사는 변경하지 않았다.
- 문서: 이 STATUS, [설계](D_ROBOT_CONTROLLER_DESIGN.md), [실행/단계 안내](D_BACKEND_RUN_ROBOT_PLAN.md), [수현 기록](D_BACKEND_PROGRESS.md). 지정 브랜치 유지. 기존 11개 파일 변경과 신규 검사 1개만 이번 단위에 해당한다. 다른 미커밋 변경/실기 자료와 이전 진행 기록은 보존한다.

### 실제 검증 결과

- 3단계 독립 검사 당시 **58 passed** 뒤 연결 경계/잘못된 준비 증거 검사를 추가했다. 최종 `python3 -m pytest -q tests/unit/test_robot_controller.py tests/unit/test_robot_backend.py` → **79 passed**(독립 60개·연결 19개), 종료 코드 0. 장치·ROS·LLM·Qt 없는 검사다.
- `QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/unit/test_qt_hmi.py` → **20 passed**, 종료 코드 0. 기존 HRI/KEEP/REVISE/UNCLEAR 시나리오도 새 Controller에 연결한 상태로 검사했다.
- 최종 전체 `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` → **485 passed**, 종료 코드 0. 기존 팀 연결 소비 검사 17개 포함. lint/type check/CI 미구성, 신규 도구 설치/검사 완화 없음.
- 정상: 3 Step 실제 채택 Current/누적 가림 유지·전체 Design 완료, 슬롯 순서·단일 최종 결과·Job JSONL의 실행/Step 식별·설정 전체 기록을 확인했다. 전달 성공 때는 Current/Step 진행이 증가하지 않으며 새 EMPTY와 조립 관측 확인 뒤에만 다음 전달이 나온다.
- 경계/실패: OCCUPIED/UNOBSERVABLE·색상 차이·닫힌 check·중복/늦은 결과, 공급 보충과 이전 Job 명령 거절, STOP 3상황·증거 누락, 집기/놓기/복귀 실패·timeout·호출 예외, 오류 후 STOP/별도 준비·빈 그리퍼 확인/새 START, 집기·놓기·복귀 로그 실패 시 다음 이동 차단과 STOP 유지, 잘못된 설정/REAL/파일 변경 시 현재 Job 고정을 확인했다.
- Qt 미리보기: offscreen 960×900 창을 실제 렌더링하고 `/tmp/c2-robot-stage4-hmi.png`를 시각 확인했다. 첫 전달 뒤 사람 조립 관측 대기, 진행 0/3·노랑 4점 다음 슬롯 2를 함께 표시한다. 실제 모니터/사람 조립/장치 증거가 아니다. CLI 도움말에서 새 옵션도 확인했다.
- 마무리 검사: 관련 문서의 로컬 링크 97개·코드 블록·JSON 예시, Python 구문·공백·문서의 독립 실행 예를 확인했다. 지정 브랜치/HEAD `7af9dae` 유지, 작업 전 해시 대상 중 이번 11개 변경 외 55개 파일과 추가 tracked 참고 문서 3개·실기 원본/기록 4개가 보존됐다. `git diff --check` 종료 코드 0. 초기 보존 검사에서 한글 Git 경로 인용을 신규 파일로 잘못 비교한 부분은 NUL 구분 경로/HEAD 대조로 수정했다. 저장소 코드/원자료 변경 없이 검증 방식만 바로잡았다.

### 연결 중 조정

1. 정지에서 들고 있음/놓았음이 확인되면 늦은 집기 callback 없이도 해당 슬롯을 한 번 소모한다. 모순된 미집기/불명확 증거는 재집기에 사용하지 않는다.
2. Fake driver가 다음 집기 요청의 상태를 새 미집기로 구분한다. 이전 Step의 놓았음이 다음 Step의 STOP 판정을 대신하지 않는다.
3. 복귀만 요청의 반복 STOP/재개도 새 ID를 사용하고 공급 효과가 없다. 오류 후 STOP 중복이 새 미확인 요청을 남겨 정리 확인을 막지 않는다.
4. 닫힌 Fake Vision/HRI 타이머는 모의 실제 배치/질문도 바꾸지 않는다. 로그 실패 뒤에는 다음 driver 이동을 발행하지 않는다.
5. 설정과 3 Step Fixture 경로·모의 지연은 실행 인자로 주입한다. START마다 읽고 활성 Job/RESUME에서는 설정 복사본을 유지한다. 정상 START는 초기 조립판/전달판 비움·공급판 채움의 명시 확인이다. 오류 정리 확인만으로 Current/슬롯을 초기화하지 않는다.

### 규모·미검증·다음

두 승인 단위의 누적 실행 코드 변화 약 350줄·검사 보완 약 530줄과 직접 관련 문서다. 신규 검사 파일 1개, 신규 클래스/추상 계층/dependency 0개. 누적 규모와 Backend 436줄은 AI 코드 정책의 사람 리뷰 대상이다. 최소 정상/Fake driver 구조를 유지하면서 독립/인접/Qt 검사에 필요한 결과만 검사했으며 자체 검사로 사람 리뷰를 대신하지 않는다.

실제 driver·Robot pose/TCP/속도·안전·Camera/홍동/팀 생산자 연결·장치 시연은 미구현/미검증이다. GUI 오류 상태의 자동 정리는 없고 별도 준비 증거 입력은 현재 독립/Fake 시험 API다. 5단계에서 그 생산자를 연결한다. 추가 GitHub 게시/커밋/PR/merge 없음. 다음은 별도 승인 후 **Robot 5단계 실제 adapter 준비(장치 움직임 없음)**이며 검증된 네 공급열/observe point/복귀 경로, pick/놓기/정지·이전 실행 종료·준비/빈 그리퍼 확인 API, 홍동의 실제 촬영/전달판 반환이 필요하다. 기존 계약 필드 재작성 요청은 아니다.

## Robot 3단계 — Fake 실패·STOP/재개 독립 검증 (2026-10-06)

사용자의 4단계까지 승인 중 3단계를 먼저 진행했다. Controller/Fake driver/기존 Controller 검사와 이 기록만 변경했다. 장치/ROS/Qt 없는 독립 검사 `python3 -m pytest -q tests/unit/test_robot_controller.py` → **58 passed**, 종료 코드 0.

- 집기 전·들고 있음·놓았음의 STOP 뒤 새 실행 ID로 각각 집기/전달/복귀부터 재개한다. 요청 ACK만으로 재개하지 않고 정지·이전 실행 종료·블록 상태 세 증거를 모두 요구한다. 모순된 미집기 증거/UNKNOWN/증거 누락은 보류한다.
- 집기·놓기·복귀 실패/timeout/driver 호출 예외는 실패 결과 한 번과 보류다. 자동 재시도 없음. 확인된 슬롯 소모를 유지하며 일반 재개로 오류를 해제하지 않는다. 오류 정리 후 새 Job 경로는 이어지는 4단계에서 연결한다.
- 추가 조정: 집기 callback이 늦어도 정지 확인에서 실제로 들고 있음/놓았음이 확인되면 슬롯을 한 번 소모한다. 복귀만 재개하던 요청을 다시 STOP/재개해도 새 집기/슬롯 소모가 없다. 이전 실행/정지 결과는 새 실행을 완료하지 않는다.
- 4단계 연결·HMI/로그·설정 식별은 아직 이 검사에 포함하지 않았다. 실제 정지/그리퍼 증거·장치 안전을 검증한 결과가 아니다. 기존 실기 원본·브랜치 유지, 추가 GitHub 게시 없음.

## Robot 2단계 — Fake 정상 전달·슬롯·외부 설정 (2026-10-06)

사용자의 2단계 승인 범위만 구현했다. 기존 브랜치 `work/suhyun-hmi-backend-robot-db`와 다른 미커밋/자료 파일을 유지한다. 신규 파일은 [robot_controller.py](../app/robot_controller.py), [fake_robot_driver.py](../app/fake_robot_driver.py), [robot.json](../interfaces/fixtures/robot.json), [test_robot_controller.py](../tests/unit/test_robot_controller.py)다. 진행 문서는 이 STATUS, [Robot 설계](D_ROBOT_CONTROLLER_DESIGN.md), [실행/단계 안내](D_BACKEND_RUN_ROBOT_PLAN.md), [수현 진행 기록](D_BACKEND_PROGRESS.md)만 갱신했다. 아래 이전/다른 담당 기록은 보존한다.

- 입력/출력: 기존 `execution_id, brick_type, color` goal → 수락 여부/사유 → 모의 집기/놓기/observe point 도착·정지 확인 → 기존 `execution_id, success, reason` 최종 결과 1회. Controller가 조립 완료·Current·기하를 계산하지 않는다.
- 정상/경계 검사: 네 열의 정상 전달, 집기 명령만으로 슬롯 미소모, 집어 올림 확인에만 1회 소모, 복귀 확인 전 성공 없음, 활성/종료 ID 중복·동시 실행·ID 충돌·잘못된 ID·역순·이전 실행의 늦은 확인, 각 열 1~6 소모 후 보충 대기/해당 열만 1번 복원, 기존 3 Step Plan Fixture의 열별 순서를 확인했다. 반복 집기·추가 소모·이중 최종 결과 없음.
- 가변 설정 검사: 지정 파일을 읽고 Fake 공급/전달/관측 위치 이름·슬롯 수를 주입한다. 기본 6, 축소 Fake 검사 1~6 허용. 네 열/지원값/필수값/명시 FAKE를 검사하고 누락·REAL·지원 외 값·잘못된 goal·파일 오류는 그대로 거절한다. 생성 뒤 외부 dict/반환 snapshot 변경이 실행 설정/슬롯을 바꾸지 않는다. 실제 pose/TCP/속도 설정을 생성하지 않았다. Job별 설정 주입/로그는 4단계 대상이다.
- 실제 실행: `python3 -m pytest -q tests/unit/test_robot_controller.py` → **41 passed**, 종료 코드 0. `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` → **438 passed**, 종료 코드 0. 전체에는 기존 팀 연결 소비 검사 17개와 Qt offscreen 11개가 포함된다. Fake Controller 독립 검사는 장치·ROS·LLM·Qt 없이 실행했다. lint/type check는 미구성이며 새 검사 도구를 설치하지 않았다.
- 규모/이유: 실행 코드 약 145줄, 검사 약 240줄, 설정 13줄과 관련 진행 문서만 추가/갱신했다. 신규 클래스 2개·dependency 0개·추상 계층 0개. 300줄 검토 신호는 정상/오류 입력·중복/소모/보충 외부 결과를 확인하는 검사까지 포함한 규모이며, Controller와 명시적 모의 driver의 두 책임만 분리했다. 사람 리뷰는 아직 받지 않았다.
- 미구현/미연결: 실행 실패/timeout·STOP/재개는 Robot 3단계, 새 Controller의 Backend/HMI/로그 연결은 4단계다. 기존 HMI는 이전 QTimer Fake를 사용하고 공급 슬롯은 여전히 미확인이다. 실제 장치·Camera·팀 생산자 연결·사람 조립 시험 없음. 추가 GitHub 게시/커밋/merge 없음.
- 다음: 승인 후 Robot **3단계 Fake 실패·STOP/재개**. 미집기/들고 있음/놓았음의 동작 차이와 정지·이전 실행 종료·블록 상태 확인 부족 시 보류를 검사한다. Fake 검사에 팀원의 계약 재작성은 필요 없다. 실제 연결에는 검증된 네 공급열/observe point/driver 증거와 홍동의 촬영·전달판 실제 반환이 필요하다.

## Robot 0·1단계 — 기존 제어 점검·경계/가변 설정 설계 (2026-10-06)

사용자가 Robot 1단계까지 진행을 승인했고, observe point·협업 설정·Day4 이후 확장 값이 변경 가능해야 한다고 추가 지시했다. 이번 수정은 [Robot 점검/Controller 설계](D_ROBOT_CONTROLLER_DESIGN.md) 신규 문서, [실행/단계 안내](D_BACKEND_RUN_ROBOT_PLAN.md), [수현 진행 기록](D_BACKEND_PROGRESS.md), 이 STATUS다. 신규 Controller/Fake driver/설정 loader/ROS 코드 구현·실기 원본 변경·장치 실행·추가 GitHub 게시는 수행하지 않았다.

- 0단계: 노랑 4점 원본 두 스크립트와 JSON/TXT 실기 기록을 읽었다. 기록상 2~6번 자동 전달/마지막 HOME 복귀와 1번 이전 수동 전달을 구분했다. 과거 설정 13개(TCP/tool·HOME·속도·높이·그리퍼)를 코드와 기록으로 정적 대조했다. 한 블록별 observe point 복귀, 나머지 세 조합, 실제 STOP/재개·집기/놓기 증거는 미검증이다. `--check`도 장치 통신을 사용하므로 실행하지 않았다.
- 1단계: 기존 robot.deliver/stop/resume payload와 callback 의미를 유지했다. Controller의 단일 실행·중복 차단·실제 집어 올림 확인에만 슬롯 1회 소모·보충·STOP 3상황/복귀만 재개·실패 보류를 설계했다. ROS transport와 실제 증거 API는 미확정이며 설계만으로 공통 Schema를 늘리지 않았다.
- 추가 설정 요구: 새 Controller는 외부 설정을 검사해 전달받는다. observe point/pose·동작 값·공급·연결 이름/주소·지원 규격을 분리하고, 활성 Job은 시작 때 검증한 설정을 유지하며 변경 값은 다음 Job에 적용한다. Day4의 PLACE/지원 범위 기본과 실행 중 보정 변경 제외를 유지한다. 이후 새 기능은 설정 값뿐 아니라 담당 기능/공통 계약/검사도 바꿔야 한다. 현재 전체 Python이 이미 가변화됐다고 표시하지 않는다.
- 현재 연결 차이: 공급 snapshot은 null/보충 actions 미연결, SUPPLY_REFILLED는 Controller 미연결 응답, Robot fault 후 HOLD에서 START 경로는 아직 없다. 4단계에서 보충/초기화/오류 정리 후 새 시작·설정 로그 연결을 검토한다. 이번 설계 요청에 코드 수정을 섞지 않았다.
- 실제 검증: 기존 Backend/snapshot/log **33 passed**, 종료 코드 0. 문서 상대 링크/anchor **21개**, JSON 예시 **4개**, 기존 Robot 요청 payload **3종**과 정지 확인 flag **3개** 정적 대조 통과. 상세 `/tmp/c2-robot-stage01-validation.json`. 문서/원본 보존 검사와 기존 구현 검사이며 Controller/Fake driver/장치 성공 결과가 아니다. lint/type check 미구성, 새 검사 도구 설치 없음.
- 지정 로컬 브랜치와 미커밋 자료/실기 원본·설정·측정 기록을 보존했다. 다음 승인 단위는 **2단계 Fake 정상 전달·슬롯·설정 주입 검사**다. 원격에서 독립 진행 가능하다. Real 연결에는 검증된 observe point/네 공급열 설정·실제 pick/놓기/정지·실행 종료 증거가 필요하다. 공통 계약을 팀원에게 다시 작성해 달라는 요청이 아니다.


## C / B 연결 합의 문서 게시 준비 (2026-10-06)

- 사용자 요청으로 C/B DM 이후 합의 내용을 09_C_B_BACKEND_HANDOFF.md에 추가하고 현재 결정·팀 가이드·공통 계약·README에서 연결했습니다. 확정 조건과 지지 수치·관측 묶음 순번 범위·전달판 반환 envelope 등 확인 대상을 구분합니다.
- 최신 main 7dffb50 기반 문서 변경만 리뷰 브랜치로 게시합니다. 수현의 로컬 개발 브랜치 work/suhyun-hmi-backend-robot-db와 기존 미커밋 코드·발표 자료·reference는 보존합니다. 다른 팀원의 C 브랜치·production 코드는 변경하지 않습니다.
- 실제 로컬 확인: 2026-10-06 수현 checkout에서 tests/unit/test_team_handoff.py의 소비 검사 17개 통과, 종료 코드 0. 2026-10-05 전체 283개 통과는 당시 기록입니다. 코드·Fixture·테스트는 현재 별도 로컬 미커밋 개발 상태이며 이번 문서 PR에 포함하지 않습니다. 이 문서 게시를 GitHub CI·실제 B/C 연결·Camera/Robot·다음 전달 gate 검증으로 표시하지 않습니다.
- 다음 확인: B 실제 반환/순번/전달판 예시, C 수정 반환 예시, A/C 지지 후보 규칙. 이후 해당 개발 단계에서 완료·전달 gate 및 실제 모듈 연결을 검증합니다.

## 2026-10-11 A 1차 통합 계약 정합 (최신 사용자 확인 반영)

- 수현의 최신 확인에 따라 10/8 계약을 우선합니다. B가 Current·revision·Expected·비교를 확정하고 D는 전달·실행·진행·최종 종료를 담당합니다. PR #20 초안의 D 소유 변경은 철회했습니다.
- A의 정수 layer 범위는 1~5, 범위 밖 재현 입력은 6으로 맞춥니다. A는 받은 B revision을 복사하며 `current_provenance=B_CONFIRMED_D_RELAYED`를 유지합니다.
- 층 확장 구분을 위해 API `assembly-ad-calculation-draft/0.5.1`, bundle `a-b-d-planning-bundle-draft/0.1.1`를 사용합니다. 구형 0.5 요청은 거절합니다. 원본 v4 Schema·보정·측정값은 보존합니다.
- `execution_allowed=false`, `DRAFT_NOT_FROZEN`을 유지합니다. 최신 변경 후 A CPU 단위·회귀 시험 351개 통과, API 계약 검사 34/34 통과(2026-10-11, agent 실행). 실제 D 수신·B/C 장치·Robot·Isaac·DB 전체 공정은 미검증입니다.


## A파트 — Isaac·MoveIt 경로 정리와 기존 연결 보존, 로컬 반영본 (2026-10-10)

- 사용자 요청 범위는 게시 전 준비입니다. `work/seeun-planning`의 `319a2755676f2432e3bf3dfdbcd7b22c4d68b17d`를 가져와 최신 A와 필요한 SIM 소스를 파일별로 반영했습니다. 이 절은 게시 전 로컬 준비 기록입니다. 게시 상태는 브랜치 이력에서 확인합니다.
- A는 기존 `planning_trial/` 한 곳을 사용합니다. 기존 C→A 확인 스크립트·테스트·샘플과 C 앱은 보존했습니다. `planner.py`의 기존 API 기본 동작은 유지하며 층 혼합·조립 후보 API·빨강 1×2 확장은 별도로 연결합니다. 원본 A와 입력·로봇 자산은 별도 fixture 및 SHA256으로 보존합니다.
- `isaac_sim/` 안으로 필요한 충돌 검사·입력·로봇 USD/mesh·ROS 소스를 모았습니다. Isaac 설치 경로는 `ISAAC_SIM_ROOT`, ROS 설정은 `ROS_SETUP_PATH`로 받습니다. 실행기는 자기 폴더의 빌드 결과를 사용하며 USD는 상대 참조, 실행용 URDF의 로컬 URI는 빌드 시 생성합니다.
- 실제 신규 검증: A/SIM CPU 테스트 365개 통과, 공백·한글을 포함한 다른 폴더에서도 같은 테스트와 chair 12 Step/red 1 Step 후보 생성 통과. FCL 원본/정리본의 17 mesh 형상·제외 목록·8개 관절 상태 결과 일치. 이동한 USD 의존 layer 10개 모두 해석, 누락 0개. MoveIt/model ROS 패키지 2개를 로컬에서 Release 빌드했습니다.
- 기존 확인 스크립트 4개로 Initial/Revised/C 공유 fixture/C→A→D 재계획 검증 통과. C/D는 기존 시험과 같은 팀 commit `101d9d85efe8bdf7cf82bef2a199f4919e1e6c84`를 별도로 사용했습니다. 이 A 브랜치의 C 뼈대에는 `create_initial_design`이 없어 그 자체의 전체 연결은 확인할 수 없습니다. 이를 고치기 위해 다른 담당자의 코드를 합치거나 스크립트를 완화하지 않았습니다.
- 정리본의 Isaac 재생은 수행하지 않았습니다. 기존 12블록 mock 조립 및 빨강 첫 슬롯의 SIM 기록은 이전 버전 검증입니다. 전달판 대기 좌표에서 먼저 여는 최신 변경, 실물 보정·중력 낙하·정밀 해제·물리 체결·힘 제어·실제 사람 도움·B 관측은 신규 검증 완료로 표시하지 않습니다.
- 실행 안내: [isaac_sim/README.txt](../isaac_sim/README.txt). 파일별 근거와 상세 검증은 `isaac_sim/review/` 및 로컬 `runtime_reports/`에 보관합니다. 다음 단계는 정리본의 SIM 재생 확인과 사용자가 요청할 때 웹 게시입니다.

## A파트 — C 공개 수정 함수·D Current 기반 채택 시험 공유 (2026-10-06)

- 고정 A 브랜치에 `planning_trial/check_c_a_d_revised.py`와 README 재현 절차를 추가했습니다. 계산 코드·공통 계약·D/C 운영 코드는 변경하지 않았습니다.
- 팀 main `101d9d85efe8bdf7cf82bef2a199f4919e1e6c84`에서 C 공개 Initial/Revised 함수와 D를 가져와, 이 A checkout의 기존 `plan_from_current()`를 호출합니다. 저장된 C 응답을 성공 결과로 대신 넣지 않습니다. C 생성기는 Mock, 관측은 fixture, Robot은 Fake입니다.
- Initial 15 PLACE를 D가 채택한 뒤 네 Step의 관측 fixture로 D Current revision=4를 만듭니다. 다리 하나를 (9,9,1)→(8,9,1)로 옮긴 관측 후 revision=5를 만들고, 실제 C REVISE v2 → 같은 Current의 A 11 PLACE → D 채택까지 확인했습니다.
- D Difference에 포함된 이동 전후 다리와 확인된 빈 다음 Step을 시험에서 명시적으로 연결합니다. 일반적인 D–C 차이 변환·여러 블록의 대응 추정·가림 해석을 새로 구현하거나 확정하지 않았습니다.
- 사용자가 직접 터미널 실행해 **PASS (17 checks)**·종료 코드 0을 확인하고 공유한 기록이 있습니다. 게시 준비 checkout에서도 같은 runner를 재실행해 17개 검사를 통과했습니다. 후자는 사용자 직접 실행 증거와 다른 Job으로 기록하고 공유 압축 파일에 혼입하지 않습니다.
- 검사 범위: Current 보존·수정 Design v2·base_current_revision=5·새 Plan ID·기존 4개 중복 PLACE 제외·Remaining 11개·D가 실제 A 결과 채택·C 응답/Plan 결과 JSONL 기록. HMI snapshot 계약을 생성하며 Qt 창을 직접 표시하는 시험은 아닙니다.
- 소스 변경은 runner·README·이 기록 3개입니다. 기존 단일 계산 코드의 SHA256 `0f96d24b8fad195185b68c9c520976b3c97d91aa179fcd91382426772f2e7835`를 유지합니다. 신규 dependency·class·시뮬레이션/REAL 분리는 없습니다.
- 사용자 직접 실행 로그·입출력 JSON·검증 결과·해당 Job JSONL·재현 안내는 새 공유 압축 파일로 별도 준비하고 기존 첨부는 보존합니다. 원격 소스에는 생성 산출물을 커밋하지 않습니다.
- 미검증: 실제 LLM/STT/TTS·B callback/촬영·실제 Robot/체결·여러 차이의 자동 변환·이번 수정 이후 남은 11개 전체 사이클. 이번 시험은 명시한 사례의 C 공개 함수→A→D 소프트웨어 연결 증거이며 일반 변환 기능·실제 장치 완료로 보고하지 않습니다. main 병합·PR 생성은 이번 작업 범위가 아닙니다.

## A파트 — C Mock·공유 fixture 재현 실행 파일 게시 (2026-10-06)

- 기존 고정 브랜치 `work/seeun-planning`에 [실행 안내](../planning_trial/README.md)와 재현용 실행 파일 4개를 추가했습니다. A 계산 코드 `planner.py`와 공통 입출력은 변경하지 않았습니다.
- `check_c_initial.py`: C 공개 Initial 성공 응답의 Design → A, `check_c_revised.py`: C 공개 Revised 성공 응답의 Design + 같은 Current → A, `check_c_fixtures.py`: C가 공유한 JSON fixture → A, `run_fake_cases.py`: 저장된 Initial 응답으로 네 가지 A 반환 사례를 실행합니다.
- 최초 Initial 기록은 C `3e18f04`, Revised·fixture 기록은 C `9de685b`였습니다. 게시 준비 checkout에서는 **네 실행 모두 `9de685b6b135d3a46968fabc9031befb02f91301`로 다시 실행**했습니다. C source checkout 경로를 인자로 받으며 README에 별도 checkout과 해당 커밋 고정 방법을 적었습니다. 특정 PC의 임시 경로를 팀 재현 지침으로 사용하지 않습니다.
- C Initial/Revised 실행에서 기존 Mock provider를 명시적으로 선택합니다. shell의 LLM 설정과 관계없이 이 재현은 외부 LLM을 호출하지 않습니다. A는 샘플/실제 연결에 같은 `plan_from_current()`를 사용하며 시뮬레이션/REAL 구현을 분리하지 않습니다.
- 게시 준비 실제 실행: Initial **READY·15 PLACE**, 부분 Current 4개를 제외한 **READY·11 PLACE**, 목표와 다른 색상 **NEEDS_CORRECTION**, 5층 입력 **INVALID**, C REVISE·Design v2 후 **READY·11 PLACE**. 각 실행 종료 코드 0과 검증 JSON의 통과 결과를 확인했습니다.
- C 공유 fixture 12개 사례 PASS: 최초 8 PLACE·부분 2개 보존 후 6 PLACE·전체 조립 0 PLACE·수정 Current 4개 보존 후 4 PLACE·목표와 다른 배치 보류·중복 점유 INVALID. `support_violation` fixture는 보존 불일치가 먼저 반환되므로 이 사례로 지지 오류 사유 반환을 증명하지 않습니다. Difference fixture는 참고·원본 해시 기록만 하며 A 계산 입력으로 사용하지 않습니다.
- `python3 -m pytest planning_trial/test_planner.py -q` → **112 passed**, 종료 코드 0. 변경 후 네 실행 파일도 모두 실제로 실행했습니다. A 소스 SHA256은 `0f96d24b8fad195185b68c9c520976b3c97d91aa179fcd91382426772f2e7835`로 이전 공유 계산 코드와 같습니다.
- 사용자 직접 실행 기록(Initial·네 가지 A 사례·Revised)과 이번 게시 준비 실행을 구분합니다. 원래 로그·산출물·첨부 압축 파일은 사용자 로컬에 보존했습니다. 소스에는 결과 생성 경로·기대값·로그 수집·압축 방법을 포함하며, 결과 JSON/로그는 실행 시 생성해 별도 공유합니다. fixture runner에 대한 사용자 직접 실행은 이번 기록에서 완료로 주장하지 않습니다.
- 이번 게시 범위는 실행 파일 4개·README·이 기록 **6개 파일**입니다. 변경량 300줄 초과는 기존에 준비한 독립 실행 4종을 팀이 재현하도록 공유하는 규모이며, 신규 계산 구현·class·dependency·추상 계층은 없습니다. 실행 파일마다 실제 입력·출력·검사·실패 경로를 표시했습니다.
- 미검증/다음 작업: D Consumer의 최신 A 출력 수용·최초/재계획 채택·화면/JSONL 반영·실제 LLM/음성·Camera/Robot/실물 조립. Current는 명시한 revision을 붙인 샘플이며 D의 실제 관측 채택이 아닙니다. 소스 게시를 공동 연결 체크박스 완료로 보고하지 않습니다. main 병합·PR 생성은 이번 작업 범위가 아닙니다.

## A파트 — Current 연결·결과 반환 형식 적용 (2026-10-06)

- 수현의 답변에 맞춰 `plan_from_current(design, current)`를 추가했습니다. Current는 `current_revision / blocks`, 반환은 `status / plan / errors`입니다. 실제 배치 채택과 결과 최신성 확인은 Backend 책임입니다.
- 기존 단일 `build_plan`을 호출하며 최초와 재계획 구현을 분리하지 않았습니다. revision을 그대로 Plan에 복사하고 이미 조립된 목표 배치는 PLACE에서 제외합니다.
- READY는 검증된 Plan·빈 errors, NEEDS_CORRECTION과 INVALID는 plan=null·사유·문제 배치이며 특정할 수 없는 배치는 block=null입니다. 처음 발견한 오류 하나를 반환합니다. 예외 문구를 분석하지 않도록 ValueError 하위 PlanningError 하나에 분기·배치 정보를 담았습니다.
- Current 누락을 빈 보드로 추측하지 않습니다. 목표에 보존되지 않은 실제 배치·삽입 방해·현재 지지 부족은 사람 정리가 필요하다고 반환하고 자동 MOVE/REMOVE는 생성하지 않습니다. malformed 입력·겹치는 Current·목표 또는 Plan 검증 실패는 INVALID입니다.
- 바로 아래층과 중복을 제외한 총 2 stud 이상 지지는 수현의 2026-10-06 회신에서 A/C 통일에 동의한 기준입니다. 공통 문서의 후보 표기 갱신은 별도입니다.
- [Current 샘플](../planning_trial/sample_current_state.json)을 합의된 바깥 구조로 바꿨습니다. revision=7과 블록 배치는 가상 시험 자료이며 실제 관측 증거가 아닙니다. [연결 예시](../planning_trial/handoff_examples.json)는 정상·부분 조립·전체 일치·사람 정리 필요·invalid 입력과 테스트 기대값입니다.
- 실제 게시 준비 checkout 검증: `python3 -m pytest planning_trial/test_planner.py -q` → **112 passed**, 종료 코드 0. 기존 최초 12 Step·재계획 9 Step의 내용과 입력 revision 유지도 확인했습니다.
- 수정 범위는 planning 파일 5개와 이 기록입니다. 신규 dependency·framework·모드 분리는 없습니다. 기존 테스트 파일 400줄 초과는 정상/invalid/경계/반환 검증의 길이이며 테스트를 약화하거나 분할용 구조를 추가하지 않았습니다.
- 미검증/다음 작업: D의 기존 reason/conflicts 수신부 조정 후 실제 C/D 함수 호출 연결, Camera·HMI·Robot·실물 조립·통합 CI. 독립 샘플 검증을 실제 모듈 통합 성공으로 표시하지 않습니다. 기존 최초 계획 CLI는 호환성을 위해 Plan만 저장하며 Backend는 새 연결 함수 반환을 사용합니다.

## A파트 — 최초 Plan·보존＋추가 Replan 공유 (2026-10-06)

- 세은의 고정 작업 브랜치 `work/seeun-planning`에서 기존 main(7dffb50) 이력을 보존하며 [계획 코드와 실행 안내](../planning_trial/README.md)를 공유합니다. main 병합·다른 파트 구현 변경은 이번 작업 범위가 아닙니다.
- 기존 로컬에서 개발·검증한 단일 계산 구현을 `planning_trial/`에 게시합니다. 최초·재계획 모두 `build_plan(design, current_blocks, current_revision)`을 사용하며 `base_current_revision`은 입력 revision을 복사합니다. 이 인자 구성은 내부 계산 API이며 실제 Backend Current 전체 구조와 실패 envelope를 확정한 것은 아닙니다.
- 규격·색상·좌표·층·방향 및 수량으로 실제 배치를 대조하고, 보존되지 않는 배치를 오류로 처리합니다. 남은 PLACE만 생성하며 자동 MOVE/REMOVE·재고 수량 검사·물리 안정성 시뮬레이션·Robot 실행을 추가하지 않았습니다.
- 현재 블록을 시작 배치로 두고 단계별 선행 관계·겹침·지지·목표 일치를 검사합니다. 위에서 수직 삽입한다는 단순 footprint 가정의 가림 검사이며 실제 손/그리퍼 경로 검증은 아닙니다. 2 stud 이상 지지는 세은이 적용하기로 선택한 기준이고 A/C 공통 계약 반영은 확인 중입니다.
- 게시 전 실제 독립 검증: `python3 -m pytest planning_trial/test_planner.py -q` → **89 passed**, 종료 코드 0. 저장된 최초 Plan 12 Step과 보존 3개＋남은 Plan 9 Step을 공통 validator로 재검사했습니다.
- [Current 샘플](../planning_trial/sample_current_state.json)은 가상 자료입니다. 바깥 필드는 Backend 확정 Schema가 아니고, [재계획 예시](../planning_trial/sample_replan.json)의 revision=7도 시험용 값입니다. 의자 사진을 복원한 GT·실제 관측·실물 검증 결과로 사용하지 않습니다.
- 규모 설명: 기존 작성 자료 8개(계산 코드 268줄, 테스트 437줄, README 1개, JSON 샘플 5개)를 같은 경로로 공유하고 이 진행 기록을 추가합니다. 테스트와 JSON의 길이는 독립 검증·재현용입니다. 신규 class·dependency·framework·계산 모드 분리는 없습니다. 공통 app 패키지로의 이동·API 확정은 연결 시 별도 확인합니다.
- 미검증/다음 작업: C/D 실제 모듈·Current 구조·최종 status/plan/errors·진행 중 부품 처리·HMI·Robot·실물 조립·통합 CI는 미검증입니다. 수현의 실제 Current 및 실패 반환 규약과 생산자/소비자 예시로 연결 검증해야 합니다. 새 lint/type-check/CI 도구는 도입하지 않았습니다.

## 최신 작업 — Day4 결정 계약과 팀원 준수 사항 (2026-10-05)

- 사용자 요청으로 현재 대화의 결정을 공통 docs에 반영. PLACE·좌표 / 각도·before / after·관측 check·verified_regions·가림 이력·최소 ID / 버전·HRI·Replan·슬롯·STOP 3방향 재개·Qt·JSONL을 정리했습니다.
- 채택 Design의 전체 미리보기를 Qt 한 화면에 포함하고 기존 여섯 snapshot 묶음에 전체 Design 표시 데이터를 추가하도록 명시했습니다. 홍동의 observe point / 전달판 판별은 수정 가능한 제안으로 분리했습니다.
- 기존 C 필드 / 의도명 차이를 이행 표로 남겼습니다. C production skeleton·기존 진행률·실제 장치 설정·reference 원본은 변경하지 않았습니다.
- GitHub 최신 main(4b4f193) 기준 별도 docs/day4-confirmed-interfaces 브랜치에서 문서 10개만 변경합니다. 다른 로컬 브랜치의 미커밋 문서·final_docs·발표 자료는 포함하지 않습니다.
- 현재 계약은 문서상 결정입니다. 공통 실행 Schema·callback / Action / Qt 연결·실제 Robot 정지 / 재개·Camera 인식·전체 Day4 시연은 이번 작업에서 구현하거나 검증하지 않았습니다. 별도 자료 폴더의 과거 독립 시험을 이 저장소의 시험 통과로 표시하지 않습니다.
- 실제 문서 정적 검증: 변경 Markdown 10개, 상대 링크 25개 존재, JSON 예시 5개 파싱, 정상 3 Step 예시의 footprint / 범위 / 지지 / 선행 관계·Design / Plan 연결 확인, 문서만 변경한 범위·git diff --check 통과. README의 존재하지 않는 AGENT.md 안내 링크 제거. 로컬 상세 결과: /tmp/day4_docs_validation.json.
- 실행 앱·Camera·Robot 시험은 수행하지 않았습니다. 다음 작업은 담당별 Fixture와 공통 형식 이행·Mock 연결이며 실제 장치 시험은 별도로 기록합니다.

아래는 이전 작업 당시 기록입니다. 오래된 웹 HMI·미정 좌표 / 식별·원격 게시 전 설명은 현재 결정으로 적용하지 않습니다.


## 최신 작업 — AI 개입 범위와 검증 보고 규칙 (2026-10-05)

- 사용자 제공 노마드 코더 영상의 설명·영어 자동 생성 자막을 확인하고 AGENTS.md에 간결한 답변, 가정 확인, 최소 수정, 기존 자동 검사 활용, 검증 증거 후 완료 보고를 반영.
- 질문/검토와 파일 변경 요청을 구분하고 요청 밖 정리·리팩터링·추상계층·dependency 추가, 실패 은폐, 테스트 약화, 사용자 변경의 혼입을 제한. 승인된 범위는 반복 확인 없이 끝까지 진행.
- 맥락에 필요한 문서만 읽도록 안내를 조정. 기존 역할·목표·구현 경계 보존. 별도 자료 폴더의 최신 계약 결정을 이 저장소의 공통 계약으로 임의 승격하지 않음.
- 별도 로컬 `협동2_프로젝트` 자료 폴더에도 AGENTS.md를 작성해 해당 작업 위치의 새 대화에 지침을 제공. 이미 열린 다른 대화의 자동 재로딩은 미검증.
- 실제 확인: 자료 폴더 53줄/9,168 bytes, 저장소 72줄/10,747 bytes. 상대 링크 4개 존재·외부 출처 링크 3개 표기, 코드 블록·후행 공백·기존 구현 경계 보존 확인 통과. 외부 출처는 영상·공식 문서 조회로 확인. 로컬 상세 결과: `/tmp/c2_agents_validation.json`.
- 실행 코드·Schema·Robot 설정 변경 없음. 앱 테스트·장치 시험·새 lint/CI 설치 없음. 문서 확인을 시스템 통과로 보고하지 않음. 다음 작업은 이번 변경만 담은 새 PR 생성과 사람 리뷰.

아래는 이전 작업 당시 기록이며 현재 원격 상태·구현 완료 여부의 신규 확인 결과가 아닙니다.

갱신: 2026-10-04. **최신 결정 반영·협업 문서·로컬 PR 준비 단계입니다. 앱 구현·장치 시험은 미완료입니다.**

| 항목 | 상태 | 다음 작업 |
|---|---|---|
| 역할·Day 4 범위 | 역할 사용자 재확인·최신 TBD 범위 반영 | 담당별 계약·Fixture 확인 |
| 환경 | Python 3.12.3 로컬 확인, Ubuntu 24.04 / Docker 29.8.2 / NVIDIA 4060 / Jazzy / M0609 / D435i / RG2 사용자 확인 | 실제 OS·Docker·GPU driver·ROS·펌웨어·장치 확인 |
| Design / Plan / Observed | Owner·의미 정리, 정확한 Schema 미정 | 생산자·소비자가 정상 / invalid 예시 확인 |
| Current / Expected·완료 | Backend Owner·전달 / 조립 완료 분리 | 정상 대기 / 실제 차이·최신성 규칙 합의 |
| HMI / 저장 | 웹 HMI API·파일 로그 방향 | framework·API·파일 형식 확인 |
| 공급·Robot | 종류 / 색상별 1~6 순서·고정 전달 | 보충 신호·실패 시 번호·STOP / 취소 시험 |
| 좌표·GT | 과거 기록·원본 pose 보존 | 공통 grid·layer·방향·판별 범위·실측 확인 |
| 일정 | H12의 Day 1~4 개발 단계 | 실제 날짜·가용 시간·시험 횟수 합의 |
| Day 4 / 최종 버전 | 공통 코드 + 검증 태그 운영 제안 | 팀 합의·시연 검증 후 태그 생성 |
| Git / PR | 빈 원격 확인·최소 기반과 문서 변경 준비 | 사용자 변경 검토 후 게시·Draft PR |
| 실행 코드·테스트·CI | 이 저장소에 없음 | 계약 합의 후 작은 기능별 구현·검증 |
| C Design (시율) | `app/c_design/` docstring skeleton·문서, 진행률 0% — [C_DESIGN_PROGRESS.md](C_DESIGN_PROGRESS.md) | C Contract |
| Isaac Sim | 후속 검토 후보 | Day 4 결과·목적·PC 사양 확인 |

## 이번 문서 작업

- README·현재 결정·역할·일정·측정·Sim·Git·에이전트 안내·PR 템플릿을 최신 결정으로 정렬.
- `06_CONTRACT_DRAFT.md`와 팀원 작업 Issue 템플릿 추가. 필드·정책 초안은 확정된 계약과 구분.
- `docs/reference/` 8개 원본과 기존 pose 배열 보존. 사진·Depth·실행 코드 추가 없음.
- 기존 파일 대비 10개 수정·2개 추가. 문서 간 과거 역할·일정의 충돌을 함께 수정하기 위한 범위이며 runtime 구조·dependency 변경 없음.
- 로컬 기반 브랜치 `bootstrap/pr-base`, 변경 브랜치 `docs/latest-decisions-collaboration`로 최초 PR 비교를 준비. 원격 게시·PR 생성·태그 생성은 후속 단계.

## 사용자 검토 반영

2026-10-04: Ubuntu 24.04 / Docker 29.8.2 / NVIDIA 4060과 역할 분담 확인을 반영했습니다. 실제 문서 폴더와 향후 코드 구조 제안을 Git 가이드에서 구분합니다. 앱 폴더·공통 Schema·Docker 실행 구성은 아직 생성·확정하지 않았습니다.

## 실제 확인과 미검증

- `python3 --version`: Python 3.12.3.
- 원격 조회: GitHub size=0·브랜치 없음, 로컬 커밋 없음 확인 후 기반 준비.
- 문서 정적 확인 통과: 현재 Markdown 13개·상대 링크 16개·표 15개·코드 블록 7개. 참고 원본 8개 해시 일치·pose 기록 일치. 외부 링크의 접근성과 앱 동작은 이 검사 범위 밖.
- Git 공백 검사: 현재 문서 통과. 전체 최초 추가에는 참고 원본 2개 파일의 기존 후행 공백 17줄이 경고로 남으며 원본 보존을 위해 수정하지 않음.
- 미검증: 앱·Schema·pytest / CI·D435i 인식·ROS Action·Robot 전달 / STOP / 취소·HMI·전체 시연. 문서 검토를 시스템 성공으로 표시하지 않음.

## 다음 구현 전에 확인할 사항

1. 시율·세은·홍동·수현: 동일 Design / 상태의 필드·기하·grid·layer·방향·정상 / invalid Fixture.
2. 세은·수현: Step 목표 / 효과·제거 / 재배치·Robot 전달 필요 여부.
3. 홍동·수현: 관측 품질·가림·정상 조립 대기 / 차이·callback / Topic 관계.
4. 시율·수현: 모델·구조화 출력·질문 / STT·비정상 응답·식별 / 버전.
5. 수현: 공급 보충 / 실패 처리·실제 driver·고정 좌표·STOP / 재개·HMI API / 로그.

내부 문서·PR 준비는 진행할 수 있습니다. 공유 필드·물리 판별·실측 값은 담당자 확인이 필요하며 이번 작업에서 임의 확정하지 않습니다.

## 작업·trial 기록 양식

작업: 날짜 / 담당 / 작은 목표 / 변경 파일 / 입력·출력 계약 / 실행한 검증 / 실제 결과 / 미검증 / blocker / 다음 작업.

trial 항목 제안: trial_id, scenario_id, mode, 입력 관측·촬영 시각, Design / Plan / Calibration 버전, 비교 Step·Difference, 질문·응답, 채택 결과, Robot 실행·전달 결과, 검증 범위·성공 / 실패 사유·소요 시간·증거 파일. 정확한 영문 필드명은 계약 확인 후 정하며 실패 trial도 기록합니다.

## 2026-10-06 — 실제 A Planner 연결 검증

세은의 a_manual_execution.tar.gz를 읽고 원격 work/seeun-planning의 f9b841c8f090b0b25c30ab27459781ad2017fd9e에서 planning_trial을 수정 없이 가져왔다. Planner 소스 SHA-256이 첨부 실행 기록과 일치한다. C의 첨부 Mock Initial/Revised 응답을 받아 실제 A 함수를 D에 연결했다. Initial 성공 응답은 on_initial_design으로 받으며, design이 있는 planner 요청은 run_planning_request로 실행한다. C에 Current blocks 목록을 전달하는 helper와 성공 HRI 응답 연결도 준비했다. 실제 C/LLM/음성 함수는 호출하지 않았다.

빈 Current READY 15 Step, 부분 Current READY 11 Step, 색상 차이 NEEDS_CORRECTION, 5층 INVALID를 A 실제 함수로 재현해 D 채택/보류·Qt·JSONL을 확인했다. 네 관측 Step의 Current revision=4로 재계획하면 11 Step이며 base_current_revision=4다. 첨부 묶음 Current의 revision=1 사례와 구분한다. 이동된 Current를 유지하는 C Mock Revised v2와 실제 A의 11 Step을 채택해 FakeRobot·관측으로 전체 완료했고, 별도 정상 15 Step도 전체 완료했다. 전달 성공만으로 Step/Current를 완료하지 않는다. Revised에서 누적 공급 6개 이후 보충 대기·명시 보충·새 EMPTY를 유지했다.

첫 Plan 채택 전 사람 정리 재관측의 이전 미연결 제한을 해소했다. D 내부 check의 plan_id/step_id를 둘 다 null로 허용하고 가짜 Plan/Step을 발급하지 않는다. Vision 외부 callback 필드는 바꾸지 않았다. 이 문맥은 Current 채택만 가능하고 조립 Step 완료 증거가 될 수 없다. 단위·통합 검사를 추가했다. startup의 실제 빈 보드 관측 자동 연결은 이번 범위가 아니다.

최종 코드 변경 후 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` → **707 passed**, 종료 코드 0. A 독립 검사 **112 passed**, 새 실제 A/D 연결 검사 **24 passed**, 각각 종료 코드 0. Qt는 offscreen, Robot/Observed는 Fake이며 실제 장치 성공이 아니다. [실행 결과 JSON](../logs/a-backend-connection-guy8gbim/results.json)과 같은 폴더의 시나리오별 Job JSONL을 보존했다. logs는 로컬 산출물로 원격 clone에 없다. lint/type는 미구성이고 새 dependency를 설치하지 않았다.

[연결 안내](D_A_PLANNER_HANDOFF.md)에 호출법·범위·남은 작업을 갱신했다. 기존 3-Step FakeDemo는 별도 독립 시험용으로 유지한다. C 실제 호출의 다른 인자·Difference 변환·음성/질문·취소 Workflow, B 실제 callback·촬영, 실제 Robot driver/pose/STOP/재개는 남아 있다. 자동 복구·DB·MOVE/REMOVE·미검증 pose를 추가하지 않았다. 로컬 작업 브랜치와 기존 미커밋 변경을 보존하고 이번 PR에서 연결 코드와 검증 기록을 게시한다. main 병합은 하지 않는다.


이번 게시에는 A–D 통합이 사용하는 Fake Robot Controller·driver와 관련 검사도 포함한다. 별도 작업의 REAL 장치 시험·터미널 수동 입력 HMI·발표 자료·팀 공통 문서 변경은 포함하지 않는다. 707개는 로컬 전체 검사이며, 게시 파일과 최신 main을 합친 독립 검사 결과는 PR에 별도로 기록한다.


PR 게시 대상과 최신 main을 합친 독립 파일 트리에서 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` 실행: **884 passed**, 종료 코드 0. main의 C 검사도 포함하며, 별도 REAL 장치 시험·수동 입력 HMI 검사는 이번 게시 범위에서 제외한다. 실제 Camera/Robot 시험은 수행하지 않았다.

## 2026-10-06 — 독립 DB 이력·계정·의미별 조회 PR

사용자 요청으로 기존 DB 병행 개발을 별도 PR로 준비했다. 기존 Day4 공정은 Job별 JSONL을 유지하고, 별도 명령 컨테이너가 PostgreSQL에 적재·조회한다. 공정 Backend·Qt·A/B/C·Robot·Camera 소스와 공통 계약은 이번 PR에서 변경하지 않는다. 실행 방법과 출력 의미는 [DB 이력 안내](D_DB_HISTORY.md)를 따른다.

- 저장표는 jobs/events/artifacts/sources/users 5개다. 원본 JSONL 문자열과 JSONB, 채택 Design/Plan/고정 기준 Current를 보관한다. 동일 원본/행 재적재는 건너뛰고 변경 원본·채택 자료 충돌·입력 오류는 파일 트랜잭션을 rollback한다. 줄바꿈 전 마지막 행은 보류한다.
- 계정 생성·목록·비밀번호 확인, designs/currents/plans/hri 조회와 JSON 보고서를 포함한다. 비밀번호는 계정별 salt와 scrypt 해시로 저장하며 일반 반환에서 해시를 제외한다. 사용자 지정 다섯 계정은 기존 로컬 시험 DB에만 있고 PR에 비밀번호·계정 seed·DB 자료는 포함하지 않는다. 새 설치는 init 후 create-user로 계정을 만든다.
- 조회는 적재된 이력이다. 마지막 채택 Plan을 실시간 active 상태로 해석하지 않으며 누락 문맥은 null/빈 배열로 둔다. HMI 로그인 세션·개인 도안 소유자·QR/얼굴인식·DB 상태 자동 복원은 미연결이다. 전달 성공을 사람 조립 완료로 처리하지 않는다.
- 로그 Schema는 기존 봉투와 소비 결과를 구조화하고 공통 Schema를 참조한다. Python 적재부는 기존 Consumer 검사를 재사용한다. Docker 빌드 제외 설정에 공통 Schema 경로를 포함해 이미지 복사를 확인했다. 신규 실행 의존성은 별도 history 환경의 psycopg[binary]==3.3.6이며 ORM·웹 서버·추상계층은 없다.

게시 기준은 main f45e9f3이다. 기존 지정 checkout을 전환하지 않고 별도 Git worktree에서 DB 파일만 구성해 검증했다.

- 게시 트리 전체 tests 및 planning_trial/test_planner.py: **1241 passed**, 종료 코드 **0**. Qt offscreen·별도 실제 PostgreSQL c2_history_test DSN을 사용했다. 로컬 미게시 HMI 변경은 이 검사 대상에 섞지 않았다.
- 해당 게시 이미지의 실제 DB 명령 **23개**: 성공 경로 22개는 종료 **0**, 없는 입력 파일 실패 경로 1개는 예상 종료 **1**. 정상 FAKE Job 24행·Revised FAKE Job 30행의 원문, 네 조회와 보고서 일치, 재적재 inserted=0/skipped=24·30, 기록 없는 Job의 빈 배열, 공개 계정 목록을 확인했다.
- 컨테이너 시험 직전 기존 이벤트·채택 자료와 다섯 계정 전체 값을 시험 후 대조해 보존을 확인했다. init은 자료를 지우지 않았고 볼륨 삭제·운영 DB 사용·계정 초기화는 하지 않았다. 실제 장치 실행은 없다.
- DB 관련 단위·실제 PostgreSQL 검사만 실행한 결과도 **102 passed**, 종료 코드 **0**이다. 게시 결과는 별도 후속 기록에 남긴다. 증거는 Git에서 제외되는 로컬 logs/history_reports/pytest-pr-publication-full.txt·pytest-pr-publication.txt·pr-container-validation.json이다. 새 clone은 안내의 재현 순서로 생성한다. 기존 lint/type check·CI는 미구성이며 실제 Camera/Robot·C API·전체 장치 통합과 사람 리뷰는 미검증이다.


## 2026-10-07 — 미게시 HMI·음성·Robot 실행 코드의 기본 버전 PR

- 사용자 요청으로 현재 로컬 기본 실행 코드를 PR로 보존하고 팀장 계정 병합을 준비했다. 최신 main `a459e13`에서 별도 worktree를 만들어 미게시 Backend/Qt·C 함수/STT/TTS·네 공급열·명시 사전 이동·STOP/probe/확인된 기록 재개와 관련 검사/Schema/Fixture만 옮겼다. 기존 main의 C/A/B/DB·최신 팀 계약·CODEOWNERS를 유지했다. 로컬 발표/제출 초안과 새 사람 전달 0단계는 이 PR에서 제외하고 원본/백업에 보존했다.
- 게시 트리 검사 `env -u HISTORY_TEST_DSN QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q`: **1371 passed, 24 skipped**, 실패/오류 0, 종료 0. 24개는 별도 실제 DB DSN 필요 검사다. Robot/Camera/음향/외부 API는 실행하지 않았다. Python/JSON 파싱·diff 공백 확인. CI/lint/type 추가 없음. 기존 실기 STOP/재개·현재→HOME 경로·음성/Camera 연결의 현장 미검증 상태는 유지한다.
- 팀원 리뷰가 어려운 상황에서 사용자가 팀장 권한 병합을 명시적으로 요청했다. PR에 동료 리뷰 미수행과 사용자 승인 사유를 기록하며 자기 Approve나 가짜 사람 리뷰를 발행하지 않는다. 기존 보호 규칙은 변경하지 않는다. [기본 버전·백업·복구 방법](D_RUNTIME_BASELINE.md)을 확인한다. 실제 병합과 태그는 GitHub PR/커밋 상태로 구분한다.

## 2026-10-12 — 서플라이 OpenCV 색상 후보 → YOLO 순서 수정

- 사용자 명시 지시에 따라 supply_vision/main.py를 RGB → 슬롯 ROI 내 OpenCV HSV 노랑/파랑/빨강 후보 → 후보 영역 원본 RGB의 일반 YOLO 종류 구분 → 원본 픽셀 좌표 복원 → 윗면/중심 추정 순서로 수정했다. Depth/OBB/Robot 명령을 추가하지 않았으며 기존 assembly·손 작업의 미완료 변경을 보존했다.
- 색상 후보가 없으면 YOLO를 호출하지 않는다. 마스크/오버레이를 모델 입력으로 쓰지 않으며 HSV와 YOLO 색상 불일치는 UNKNOWN으로 보류한다. 기존 HSV/minimum_area 설정을 재사용하고 새 dependency/공통 계약/자동 병합/재시도를 추가하지 않았다. README에 색상 누락 시 YOLO 누락과 crop 입력 평가 필요를 기록했다.
- 신규 회귀 검사로 색상 없는 영상의 YOLO 미호출, 원본 crop 입력, 전체 영상 좌표 복원, 색상 불일치 보류를 확인했다. 기존 중심 연결 검사도 crop 기준으로 수정하고 실제 중심 결과를 확인한다. supply 검사 **22 passed**, 전체 supply/perception_mvp/legacy **246 passed, 1 skipped**, 각각 종료 0. compileall·git diff --check 종료 0. 실제 YOLO 모델/ROS/RealSense/파지 검증은 수행하지 않았다. skip은 기존 검사의 환경 조건으로 미검증이며 PASS로 계산하지 않는다.
- 다음: 원본 RGB 라벨링·일반 detection 학습, 실제 HSV 후보 누락 및 crop 종류 구분 평가, 윗면 중심 오차와 D 연결 검증. commit/push/PR 없음.

## 2026-10-12 — 공급판 RGB 윗면 polygon 라벨 검수 초안

- 사용자 요청으로 오늘 supply_board_roi/20261012T002844481743Z/rgb.png의 36개 블록에 윗면만을 목표로 polygon 초안을 작성했다. 원본을 시각 확인해 모서리를 지정하고 OpenCV로 표시했으며 자동 추출/YOLO/생성 이미지 결과가 아니다. 옆면 포함을 피하는 라벨링 예시이며 경계의 pixel 정확도는 사람 검수 전 미확정이다.
- perception/labeling/supply_top_review_20261012/에 전체 미리보기, 확대 미리보기, polygon JSON, 재현 draw_draft.py를 저장했다. JSON reviewed=false, status=UNREVIEWED_NOT_TRAINING_GT로 구분하며 학습 dataset으로 자동 적재하지 않았다. 원본 RGB와 운영 코드는 변경하지 않았다.
- 실제 확인: 재현 스크립트 종료 0, PNG 저장 확인, 확대 이미지를 열어 36개 외곽 표시를 확인했다. 실제 자동 윗면 분리·정답 검수·중심 오차·학습·Robot 검증은 수행하지 않았다. 다음은 사용자 경계 검수와 나머지 사진의 일관된 윗면 polygon 라벨링이다.

## 2026-10-12 — X-AnyLabeling OBB 라벨링 작업 준비

- 사용자 요청으로 Roboflow 작업을 중단하고 X-AnyLabeling을 준비했다. 공식 GitHub latest release 조회 결과 v4.1.0 및 Linux CPU 배포 파일을 확인했다. 실행 파일 다운로드 권한 요청이 사용자 거절로 종료되어 설치/실행하지 않았다. 재요청·우회 설치 없음.
- perception/labeling/supply_obb/에 원본 RGB 작업 복사본 13장, 출처 manifest, 다섯 클래스 목록, annotations 폴더와 안내를 준비했다. 기존 RGB/Roboflow 라벨/운영 환경은 변경하지 않았다. 원본 복사 결과와 기존 파일 충돌 검사를 확인했다. 실제 GUI/OBB 라벨/내보내기/학습은 미수행이다.
- 다음: 공식 Linux CPU 실행 파일 설치/GUI 실행 → 윗면 수동 OBB 라벨링·검수. 공급 실행기의 OBB 추론 전환은 별도 구현 필요. 자동 라벨을 정답으로 생성하지 않았다.

## 2026-10-12 — X-AnyLabeling 공식 CPU 실행 파일 다운로드

- 사용자가 다운로드를 명시적으로 재요청하여 공식 v4.1.0 Linux CPU 실행 파일을 /home/roh/Documents/ChatGPT/협동2/tools/xanylabeling/에 저장했다. curl 종료 0, 크기 414057936 bytes와 GitHub release asset SHA256 8c4c624d453b4b7e93b2d342867e901601822632d07bebba17b8405c9fff70bf 일치를 확인했고 실행 권한을 부여했다.
- 기존 Python/ROS 패키지는 변경하지 않았다. GUI 실행/호환성/라벨링은 아직 미검증이다. 다음은 실행 파일로 GUI를 열고 supply_obb/images를 선택해 수동 윗면 OBB 작업을 시작하는 것이다.


## 2026-10-12 웹앱·DB PR — HMI 제외

사용자 최신 요청으로 웹앱과 DB만 `codex/integration-round1`의 `02137d8` 기준 별도 작업 공간에서 선택 반영했다. `DB 개발용`·`웹앱`의 최신 대화에 따른 제작자별 도안 관리, 버전별 선택 공개/해제, 로그인 없이 공개 모형/제작자/층별 설계도 조회를 제공한다. 기존 계정/JSONL/Job 소유권·개인 저장 코드를 재사용하고 공개 테이블 migration 002를 추가했다. 계정 원문·비밀번호·DSN·실제 로그/DB 데이터는 포함하지 않는다.

기존 8개 단위/DB/웹 검사 파일 **159 passed**, 실패/오류/skip 0, 종료 0(26.29초). 별도 `c2_hmi_web_pr_20261012_test` PostgreSQL과 로컬 HTTP를 사용했다. 첫 실행은 한글 file URL 경로를 디코딩하지 않은 테스트 1 failed/158 passed였고 테스트 경로 해석 수정 후 전부 재실행했다. Node SVG/UI·층 선택·입력 보존 및 JS 구문 검사 종료 0. 검사 산출물은 별도 PR 작업 폴더 `logs/hmi-history-web-pr/`에 보관하며 과거 채팅의 통과 수치를 재사용하지 않았다.

Qt HMI/HMI 로그인 결선/새 D 통합 실행기/A/B/C/로봇·장치 설정은 변경/게시하지 않는다. 원래 `/home/ms-02/C_2`의 지정 브랜치·미커밋 변경은 보존했다. 이번 PR에서 실제 브라우저 수동 화면·외부 서비스 배포·Robot/Camera/음성/API·전체 사람 조립은 시험하지 않았다. 실행·기능 경계는 [웹 안내](D_WEB_HISTORY_RUN.md)를 따른다.


## 2026-10-12 CPU 검사 공간 — GPU A 변경과 de59b08 호환성

GPU 현재 A snapshot92파일을 CPU deliverables/GPU_A_수정본_CPU보관_20261012에 SHA 검증 보관. de59b08 기반 별도 branch에서 기존7/신규3 코드·시험·입력 파일 적용 충돌0. 수정 전 관련470 PASS, 수정 후530 PASS/1 FAIL(A 자체439 PASS). 실패1건은 기본 의자의 예전 NO_FEASIBLE_ORDER 기대이며 현재 사람 직접 조립2단계 계획 COMPLETED가 요구한 동작이다. 실패 fixture를 robot-only로 만드는 별도 제안1 PASS, 원본 시험/GPU에는 아직 적용하지 않음. 물리/ROS 실행·remote/GPU 변경·commit/push/merge 없음. 상세와 XML은 위 보관 폴더 compatibility에 있음.


## 2026-10-12 — A 완성 순서 탐색·사람 도움 정책 PR 준비

- de59b08의 codex/integration-round1을 base로 GPU 수정 A 주요 7파일 SHA와 같은 코드의 PR 변경을 준비했다. 완성 탐색 지연 평가·subset 중복 제거, 아래층 삽입 선행 조건, robot-only 필요 순서 충돌 사유, 새 기본 finish_layers=true, 사용자 승인에 따른 사람 손 접근 공간 검사 제외와 HUMAN_ACCESS_NOT_CHECKED 표시를 포함한다. 지지·두 손·로봇 접근·목표 장애물 검사와 execution_allowed=false는 유지한다. 기존 v4·원본 입력·A/D 공개 함수 경계를 유지한다.
- C 기본 의자 실패를 기대하던 예전 MVP 시험은 ROBOT_GRIP-only 입력으로 실패→C 전달/무실행을 계속 검사하도록 정리하고, 사람 직접 조립 2단계를 포함한 15단계 완성 후보 시험을 추가했다. 관련 A/MVP/C/CAD 순수 계산 검사 532 PASS(8.99초), 실패/오류 0, 종료 0이다. 이전 CPU 호환성 기록의 530 PASS/1 FAIL은 이 시험 정합 변경 전 결과다.
- 다양한 CPU 입력 175/175 예상 동작 확인: 정상 165개 완성 후보 및 3,351단계 재평가, 부적합/허용 방식 불가 10개 거절. GPU 대표 12/12 완성 후보 및 325단계 재평가, 도움 배정 CPU와 일치. 범위는 중복되므로 합산하지 않는다. 전체 정상 반환 단계의 사람 도움 273/3,351=8.15%(직접 조립107, 로봇 조립 중 도움166). CPU 10사례와 GPU 표본2사례는 완성 계획 확보 후 추가 도움 최적화만 한도에서 종료했다.
- GPU whole API 단일 실측: 20블록 혼합5층0.0947초/6점밀집5층0.1120초/4점밀집1층14.7722초, 40블록은 각각0.3137/1.5119/46.0593초. 개별 CPU 최장83.36초. MoveIt·IK·장치 이동 시간은 제외이며 미래 입력의 상한을 보장하지 않는다. 정책·재현은 [계획 정책](A_ORDER_SEARCH_POLICY_20261012.md), 러너는 planning_trial/check_diverse_designs.py에 있다.
- 전체 소프트웨어 묶음은 CPU의 psycopg 미설치로 수집 단계에서 중단됐으며 전체 통과로 표시하지 않는다. DB 및 RobotProcess를 제외한 확장 검사 2,599 PASS / 31 FAIL / 11 ERROR(156.82초). 실패/오류42개는 CPU에 없는 GPU 절대 경로(robot_trial_blue5.json 33개, yellow4_row_to_place.py 9개)를 읽다가 발생했다. 수정하지 않은 de59b08에서 같은42개를 재실행하여 node ID·오류 메시지 일치를 확인했다. 이번 변경으로 새롭게 관측한 실패는 없으나 전체 범위가 모두 통과한 것은 아니다.
- GPU 작업 코드·D 실행 설정·ROS/controller/TCP/그리퍼/힘·API 실물 실행은 변경하지 않았다. CPU 코드/시험/문서와 GPU logs 증거만 준비했다. 물리 조립·Isaac 계약 정렬·실물 D 사람 조립 분기는 미검증/후속 범위다. PR 준비 상태는 게시/병합 완료가 아니다.


## 2026-10-12 — 후속 사용자 요청: 탐색 상태 제한 제거

- 사용자 요청으로 PR #28을 닫고 후속 검증 중이다. 최종 검증 뒤 같은 번호로 수정·재개한다. 현재 A에서 최초 완성 탐색/도움 최소화의 max_states 중단을 제거했다. 새로운 whole_request 기본 context에는 필드가 없고, 기존 양의 정수/null은 호환용으로 수용하되 탐색 중단에 사용하지 않는다. 원본 v4·보존 입력은 유지한다.
- 30초는 추가 도움 최적화의 소프트 기준이다. 그 전에 최적성을 증명하면 일찍 반환한다. 기준 시점에 완성 계획이 있으면 확보한 계획 중 가장 좋은 것을 optimal=false로 반환하고, 아직 완성 순서가 없으면 탐색을 계속해 처음 확보한 완성 순서를 반환한다. 초기 탐색이나 개별 검사·최종 검증/API 변환은 더 걸릴 수 있어 응답 시간 상한이 아니다. 불가 증명은 NO_FEASIBLE_ORDER로 유지하고 부분 계획/가짜 완성을 반환하지 않는다.
- 관련 A/MVP/A-Backend/C 계약/CAD 준비 순수 검사542 PASS, 실패/오류0(10.47초). 신규 회귀는 10,000 초과의 최초 가능성 탐색과 추가 도움 탐색, 30초 후 첫 완성 반환, 기존 완성 후보 보존/개선, 완성 없이 시간 경과 시 계속 탐색, 불가 사유, 구형 max_states 입력 및 필드 생략·null의 실제 API/재평가 연결을 확인한다. 합성 subset 그래프 시험을 실물 조립 증거로 취급하지 않는다.
- 지지·두 손·로봇 접근·목표 장애물·완성 후보 재검사와 execution_allowed=false는 유지한다. GPU SSH 인증 만료로 GPU 작업 폴더는 이번 변경을 적용하지 않았다. CPU의 PR 기능 브랜치에 공통 A 변경을 검증하며 실제 ROS/장치/Isaac/MoveIt 실행은 없다. 다양한175입력 재시험과 추가 연결 검증 결과는 후속 완료 기록에 남긴다.


후속 완료 검증: 다양한 CPU175/175 예상 동작 확인(정상165/거절10), 3,351단계 재평가 통과. 추가 HMI·연결91 PASS, API샘플 러너도 현재 정책으로 정렬해34/34 PASS를 확인했다. 20/40 밀집1층 whole API30.2099/30.5314초, 전체 집합486.29초, 이번 개별 최장30.5314초. 실제20블록 입력에서도12,753상태까지 탐색하며 완성 후보를 반환했다. 도움273/3,351=8.15%로 동일했다. raw 결과·XML·현재소스 hash는 CPU deliverables/A_탐색상태제한제거_20261012에 보존한다. 이 결과는 GPU 최신 수정본·장치 실기·전체 root 검사100% PASS가 아니다. 검증된 후속 변경을 PR #28의 같은 브랜치에 게시하고 재개하는 범위만 승인받았으며 main/integration 병합은 별도다.

## 2026-10-12 — 서플라이 YOLO OBB 채택 반영

- 사용자 요청에 따라 supply_vision의 모델 입력을 task=obb로 전환했다. OpenCV 색상 후보 → 원본 RGB crop OBB 추론 → 전체 RGB 중심/모서리 복원 → 슬롯 후보·중심·영상 회전 방향 반환이다. detect/segment 모델을 거부한다. Depth/자동 로봇 실행/기존 assembly 변경은 없고 기존 손·설정·모델 삭제 등 다른 작업을 보존했다.
- obb_geometry.py는 xywhr 중심을 그대로 사용하고 원본 crop offset을 복원한다. 너비/높이가 뒤바뀐 예측을 긴 축 기준으로 정규화하며 직사각형 영상 각도는 [0,180) degree, 정사각 2x2는 90도 동등 축으로 표시한다. 영상 +u 기준 시계방향(v 아래)이며 Robot wrist 각도가 아니다. 파지할 두 변의 중점과 대각선 십자 표시를 유지한다. 모서리 순서/각도 필드는 로컬 인계 문서에 명시했다.
- README·BACKEND_HANDOFF·config_TEMPLATE와 crop 회귀 검사를 갱신했다. 이제 surface 설정은 HSV 범위/minimum_area만 사용하며 이전 quad 추정 설정은 필요 없다. 이전 top_surface.py는 과거 시험/검사 근거로 보존하지만 실행 경로에서 호출하지 않는다. 공통 Service/Schema를 변경하지 않았다.
- 실제 검증: supply 검사 **31 passed**, 전체 supply/perception_mvp/legacy **304 passed, 1 skipped**, 각각 종료 0. 모델 결과 adapter/중심/회전/width-height 교환/2x2 동등성/잘못된 모델 거부/색상 우선/crop 원본 좌표 복원을 합성·대체 추론으로 검사했다. compileall·git diff --check 종료 0. 기존 skip은 제공되지 않은 PR22 Consumer 검사이며 실제 D 계약 검증으로 표시하지 않는다. lint/type 미구성.
- 미검증: 학습된 실제 OBB 모델·실제 RealSense/ROS 수신·중심/각도 오차·D 변환/Service·파지. OBB는 직사각형 예측이므로 원근 사다리꼴 윗면과 정확한 중심이 일치한다고 보장하지 않는다. 라벨 검수/독립 장면 및 실제 crop 평가가 필요하다. 최신 D 빨강 1x2x1과 기존 로컬 별칭 red_2x1/2x1x1 매핑은 연결 시 합의 필요하다. 다음: OBB 라벨링 마무리·학습 → 실제 중심/각도 평가 → D 픽셀/각도 보정 연결. commit/push/PR 없음.

## 2026-10-13 — B 조립판 검사 시작 조건 보완

### 후속 — 평면 기반 body/stud 재수집 및 비평행 거부

- 허용기울기를인정하면서고정수평band로잘라내던단계를관측된body평면의residual band로최대3회재수집하도록수정했다. body/stud각각의최소점수·10도기울기·±0.75mm band·joint25%·RGB외곽55%·층±2.5mm는유지한다. 같은XY에서약4mm간격인지추가검사해중앙값만맞는비평행patch를거부한다. 보정원본/층·거리값을변경하지않았다.
- 같은실제6장/26s모델/14검출에서분리통과3→4,몸체스터드보류11→10,외곽보류3→4,좌표·층확정0이다. 최신 parallel_surface_refinement 및이전/중간결과를별도보존했다. 외곽지지33.8/47.1/41.4%의부족및D1추가분리검출의4점외곽없음을확인했다.단계진행증가를전체성공으로표시하지않는다.
- B회귀365 passed,1 skipped(18.12초),종료0. skip은PR22 Consumer미제공이다. 허용기울기표면재수집/10도초과/비평행거부와기존실패경로를검증했다. 실제좌표·층·외곽/GT정확도/보정자세정합/Controller/D연결은미완료다. 다른팀코드/Git게시없음.

### 후속 — 장치 없는 확인 영역 생산 로직/실제 저장 Depth 진단

- BODY_TOP_PLUS_STUD measurement의성공candidate footprint/layer만 positive확인영역으로생성했다. 아래층/주변empty를추정하지않는다. 빈공간은3D grid column ray-box 교차로관측Depth가뒤쪽까지도달할때만생성한다. 원본Depth0/거리범위밖/객체mask/앞쪽가림/clip/지원부족은미확인이다. 실제config flat0의6.5~99mm공간이며현재블록계약의시험기하모델이지안전/센서GT가아니다. 생산자와저장영상bundle에연결하고근거를기록했다. 공통Observed6필드는유지한다.
- 기존실제빈보드3장/실제모델에서 검출mask0을 확인한 뒤 현재보정으로 진단계산했다. V0 366/D1 269/D3 442 columns, 진단합집합556/576이며20칸미확인이다. 개별missing/range/clip원인을파일에기록했다. 과거자세/현재보정불일치가능성과서로다른시각을명시하고실제D INITIAL은채택하지않았다. 원본/앞선결과를보존하고empty_column_review_20261013_detailed 및 docs/REGION_EVIDENCE_20261013.md에기록했다.
- B회귀362 passed,1 skipped(18.06초),종료0. skip은PR22 Consumer미제공이다. 초기상태충분/부족,레이가림/누락/범위밖/객체/clip,positive관측층한정,belowhistory보존,저장→판정연결을합성으로검증했다. 실물block 좌표·층확정은여전히0개,표면/외곽추출·실제보정정합·전체coverage·Controller/D주입은미완료다. 실제장치/다른팀코드/Git게시없음.

### 후속 — 장치 없이 실제 저장자료 표면 추출 개선/재검증

- 사용자 요청으로 기존 실제6장에 대한 실패단계 분석을 진행했다. 분리 이후 body만25%를 요구하고 외곽 증거도body만 사용하는 구조를 확인해, 윗면 지지는 확인된body+studs로 검사하고 높이/역투영은body만 사용하는 방식으로 수정했다. 기존25%/55%/최소점수·기울기·4mm 간격/층 허용 오차는 낮추지 않았다. 표면/외곽 단계별 실패 진단을 내부records에 추가했다.
- 같은26s모델/6장 실제재생에서 분리 통과1→3개, 분리 보류13→11개, RGB외곽 보류1→3개이며 좌표·층 확정은여전히0개다. 외곽 내부표면 증거32.1%/44.9%/41.2%로55% 기준 미달을 확인했다. 단계 진행 개선을 전체 판정 성공으로 표시하지 않는다. 원본/첫 결과/중간 결과/최신 outline_diagnostics 결과를 별도 보존하고 docs/ASSEMBLY_REPLAY_20261013.md에 기록했다.
- 수정 후 B회귀340 passed,1 skipped (2.55초), 종료0. skip은 PR22 Consumer미제공이다. 새 회귀는body/stud joint지원과body만 높이사용, joint지원부족 거부, outline에stud증거 전달을 확인했다. 실제Robot/Camera연결/GT정확도/verified_regions/D공동시험은 미완료이며 다른 팀 코드/commit/push 없음.

### 후속 — 실시간 검증 준비/대기

- 사용자 요청에 따라 미완료 사항은 이후 요청 시 정리할 수 있도록 기록을 유지한다. 현재 실행 환경의 ROS topic list는 제한시간 내 정상 결과를 얻지 못했고 네트워크 읽기 접근도 허용되지 않아 실시간 Camera 시험을 진행하지 않았다. 이것을 카메라 고장/노드 중지의 증거로 단정하지 않는다. Robot 명령/Camera 재시작/기준값 완화는 실행하지 않았다.
- 다음 입력은 실제 V0/D1/D3 보정 자세에서 정지 후 새로 촬영한 빈 보드와 노랑2x2 한 개1층 RGB-D다. 사용자가 실제 stop/빈 보드/블록 배치를 확인해야 하며 기존 시험 결과를 새 촬영의 검증으로 표시하지 않는다. 현재 BODY_TOP_PLUS_STUD 실물 판정 보류/확인 영역 생성/Camera→D 연결 미완료 상태를 유지한다.

### 후속 — 실제 저장RGB-D6장/학습모델 재생

- assembly_replay로 실제 원본RGB/Depth/CameraInfo와 현재26s segment 모델 및 integrated_view 설정을 재사용했다. 3View각2장/검출14개 중 좌표·층 확정0, 몸체/스터드 구분 보류13, RGB 윗면 외곽 보류1이다. 실행 종료0을 판정 성공으로 표시하지 않는다. 원본metadata/보정/임계값은 바꾸지 않았다. output report/실제처리 PNG와 docs/ASSEMBLY_REPLAY_20261013.md에 입력/결과를 기록했다.
- V0첫 영상의 유효Depth2984/마스크3004에도4mm 표면 pair body support 최대21.2%로25% 시험 조건에 못 미쳤다. V03층 기록은 표면 분리 이후 외곽 추출에서 실패한다. 당시 자세/현재 보정 반복성·GT는 미검증이며 다른 View 원인을 이 결과로 단정하지 않는다. 다음은 현재 실제 자세의 빈 보드/1층 데이터로 기준면·표면 추출을 확인하는 작업이다.
- B 회귀338 passed, 1 skipped, 종료0. skip은 PR22 Consumer 미제공이다. 새 replay 단위 검사는 대체 모델/메시지로 보고/오류/덮어쓰기 금지만 검증하며 위 실제6장 결과와 구분한다. Robot/Controller/D 실제 연결/새 촬영/Git 게시 없음.

### 후속 — 위치별 최상층 몸체 측정 후 스터드4mm 한 번 추가

- 사용자 요청에 따라 default Geometry/live_view에 BODY_TOP_PLUS_STUD를 적용했다. 각 instance의 높은 몸체/스터드4mm 표면 쌍을 확인해 몸체만 측정하고4mm를 한 번 추가한다. 기존 층 기준표는 변경하지 않으며 board reference 이동4mm와 분리한다. 몸체/스터드 구분이 안 되면 body_stud_surfaces_unverified로 보류한다. 기존 명시적 legacy 설정 호출은 유지하며 JSON override는 block_stud_height_mm를 명시해야 적용된다.
- 표면 쌍 추출의±0.75mm band/최소50점(생산자는 설정)/기울기10도는 시험값이다. 단일 평면을 몸체라고 가정하거나 스터드 표면에 다시4mm를 추가하지 않는다. body 높이와 추가량을 내부 결과에 기록하고 두 경로의 높이 품질 검사는 선택된 몸체에 적용한다. 부분 가림/작은 스터드 표면에서 관측불가가 늘 수 있어 실물 평가가 필요하다.
- 실제 B 검사336 passed, 1 skipped (1.98초), 종료0.1~5층/다른 위치 높이/최상층만4mm/단일·잘못된 표면 간격 거부/production body→layer 및 화면의 board4mm+block4mm 중복 방지를 합성 데이터로 확인했다. skip은 PR22 Consumer 미제공이다. 실제 카메라 정확도/verified_regions/D 연결은 미검증이다. 다른 팀 코드·원본 보정/Git 게시 없음.

### 후속 — 높이 분산 시험값5mm와 실제 설정 형식 검사

- 층 허용오차±2.5mm의 전체 폭5mm를 높이 P95-P5 품질 제한의 시험 초기값으로 적용했다. 실측 sensor 잡음 검증으로 표시하지 않는다. 기존 production 검사와 기본 통합 화면의 윗면 검사에 동일 limit을 연결하되 production 유효 mask와 화면 추출 윗면의 검사 대상 차이는 문서에 명시했다. 잘못된 값/높이 누락은 실패,5mm 경계는 허용,5.1mm는 보류한다. 단위 변환의 경계 float 반올림만 machine-epsilon으로 처리한다.
- 실제 B 검사327 passed, 1 skipped, 종료0. default Geometry는 validate_config를 통과하며 null은 없다. skip은 PR22 Consumer 미제공이다. 실제 보드 부착 기준/Depth 오차/표면 추출/확인 영역/Controller→B→D 공동 시험은 여전히 미검증이다. 직접USB camera3값은 ROS에 쓰이지 않아 null 유지한다. 다른 팀 코드/commit/push 없음.

### 후속 — 보정 기반 관측점별 Depth 범위

- 사용자 요청으로 기존3개 Camera-to-Board 보정에서 flat-board0~99mm(5층96.5mm+2.5mm), nominal24x24 board 경계의8개 모서리를 역변환해 카메라 optical Z 최소/최대를 계산했다. 시험용Z 여유5mm와 바깥 방향mm 반올림을 적용한 V0 443~573mm/D1 334~763mm/D3 397~696mm를 config depth_ranges_m에 설정했다. Z 여유는 센서 정확도/층 오차의 검증값이 아니다. Euclidean 카메라 거리와 구분한다.
- depth_grid.process_saved는 실제 metadata View별 제한을 사용하며 설정된 View 누락을 공통 범위로 숨기지 않는다. 기존 직접 함수용 global min/max는 합집합 호환값이다. 기본 통합 화면도 View별 제한을 적용한다. 명시적 layer-reference override에는 depth_ranges_m도 제공해야 동일 제한이 적용된다. 보정 원본/Robot/D 파일은 수정하지 않았다.
- B 검사319 passed, 1 skipped (2.18초), 종료0; diff check 종료0. 계산 모서리/실제 설정의 바깥 경계/누락 View 거부/기존 global호환/저장 및 통합 화면의 거리 밖 Depth 거부를 검사했다. skip은 PR22 Consumer 미제공이다. 실제 빈 보드/5층 Depth 검증은 미실행이고 calibration_derived_trial_not_depth_validated로 표시한다. Geometry 높이 분산 null/실제 확인 영역/Controller→B→D 연결은 별도 남아 있다. Git 게시 없음.

### 후속 — 기존 손/Geometry 자료의 기본 실행 설정 연결

- 저장된 V0 손 profile의 ROI/polygon/해상도/시험 quality·안정값을 config.yaml에 반영했다. 기본 live_view는 --hand-config 없이 이를 읽고 상대 모델 경로를 perception 기준으로 해석한다. 기존 별도 profile/D1·D3 비활성은 유지한다. 새 ROI 저장 때 다른 ROI의 시험 quality를 승계하지 않도록 기존 미설정 정책을 유지했다.
- runtime 보정ID를 연결하고24x24/16mm 피치의 명목 보드 경계/블록 크기, 공통 footprint 기반 중심 격자/anchor offsets를 반영했다. 기존 integrated/grid_anchor의 임계값을 temporary_test로 재사용했다. 실제 몸체 실측/새 센서 정확도 검증으로 표시하지 않는다. Depth 거리 하한·상한·높이 분산3개 및 직접USB camera 설정은 근거 없이 채우지 않았다. 전체 판 확인 영역 생성도 별도 필요하다.
- 실제 B 검사314 passed, 1 skipped, 종료0. skip은 PR22 Consumer 미제공이다. 초기 검사에서 새 ROI가 기존 trial profile을 승계하는 문제를 발견해 두 ROI 저장 경로를 수정 후 전체 범위를 재실행했다. 실제 장치/Controller/D 주입 시험은 미실행이다. 다른 팀 코드 변경/Git 게시 없음.

### 후속 — 사용자 요청 층 허용 오차 ±2.5mm

- config.yaml height_tolerance_m를0.0025로 축소했다. 층 증가량18.625mm와 기준 높이는 유지한다. 기본 live_view 설정에도 동일 적용하며 명시적 --layer-reference는 기존대로 우선한다. README 현재값을 갱신했다. 앞선 ±5mm 기록은 이전 시험값이다.
- 관련 층 설정/통합 화면 합성 검사14 passed, 종료0. ±2.5mm 경계는 허용하고 ±2.6mm는 층 미확정으로 남기는 회귀를 확인했다. 보드 부착1층 기준 및 센서 오차의 실제 검증은 별도이며 다른 팀 코드/Git 게시 없음.

### 후속 — 사용자 채택 평균 증가량 기반 시험용 층 기준

- 사용자 제공 블록 단독 1층 약22mm·5층96.5mm에서 (96.5-22)/4=18.625mm/층을 채택했다. config.yaml top_heights_m는 [0.022,0.040625,0.05925,0.077875,0.0965], height_tolerance_m는 시험용0.005로 설정했다. 1층22mm는 보드 부착 실측이 아닌 임시 절편이며 trial_average_unvalidated_board_baseline으로 명시한다. 근거 없는 전체 Geometry 값은 채우지 않았다.
- live_view는 --layer-reference가 없을 때 config의 층 기준을 읽는다. 기존 stud-top0 보정의 높이에4mm를 더해 flat-board0 기준 높이로 분류/표시하며 원래 stud-top 높이로 윗면 역투영 계산을 유지한다. 명시적 JSON override는 유지한다. 16mm는 XY 스터드 간격이며 층 간격으로 쓰지 않는다. 평균 기준5층/허용 구간 밖 미확정/기준면 차이를 회귀 검사했다.
- 이전 작업의 board_pose_bundle 및 파생 assembly_runtime_pitch16_flat0_20261013.json은 기존 V0/D1/D3 pose를 metre Camera-to-Board 변환으로 변환하고4mm datum 이동을 명시한다. 원본 보정은 보존했다. 실측 층 GT나 로봇 좌표 보정이 아니다.
- 현재 B 검사304 passed, 1 skipped (2.09초), 종료0. skip은 PR22 Consumer 소스 미제공이다. 실제 보드 부착1층 기준·Depth 반복 오차·Camera→D 공동 시험은 미검증이다. 설정을 validated로 승격하지 않았다. 다른 팀 파일 수정/Git 게시 없음.

### 후속 — V0 손 영상 ROS 수신 연결

- ros_capture.stream_ros_hand로 카메라 PC의 raw RGB/aligned Depth를 수신하는 V0 전용 generator를 구현했다. 실제 V0 정지와 활성 요청 조건을 요구하며 별도 ROS Context/Executor/수신 스레드에서 제한된 큐의 최신 동기화 묶음만 손 판정에 제공한다. 대기 중 손 추론과 ROS 수신을 분리했고 반복/오래된 프레임으로 안정 시간을 늘리지 않는다. 기존 wait_for_hand_ready가 준비 완료/실패 때 generator를 닫는다. make_inspection_observer의 hand_stream=None과 실제 is_stopped(View) hook으로 선택한다. 기존 명시적 stream 호출은 유지한다.
- 실제 검증: perception_mvp/tests 297 passed, 1 skipped (1.64초), 종료0; diff check 종료0. ROS 대체 메시지의 별도 수신 스레드·정상 종료·STOP·이동 중 무구독·반복/오래된 프레임 실패와 request 활성 조건 연결을 검사했다. skip은 PR22 Consumer 소스 미제공이다. 현재 저장된 V0 손 ROI/모델 파일은 존재하지만 TRIAL_VALUES_UNVALIDATED이며 실물 검증 완료가 아니다.
- 실제 Camera/Controller 및 D 주입은 미검증이다. 확인 영역 생성은 실제 빈 공간/가림 근거와 보정 입력이 필요하며 ROI를 전체 확인으로 승격하지 않았다. config.yaml의 Geometry/층별 top_heights 미입력 및 보드 flat0mm와 기존 stud-top 보정의 정합은 남아 있다. 실제 장치/공동 시험 결과로 표시하지 않는다. A/C/D 파일·실측값·층 기준 변경/commit/push 없음.

### 후속 — ROS 촬영 파일의 검사 입력 호환

### 후속 — 정지 후 ROS 단발 촬영 callable

- ros_capture.capture_inspection_view를 실제 ROS 단발 수신 callable로 추가했다. REAL/V0·D1·D3, 실제 Controller pose/정지 hook, 요청 활성 상태를 요구한다. B 전용 ROS Context/Executor에서 RGB RELIABLE depth1과 Depth/CameraInfo sensor_data로 수신하고 요청 후 프레임·50ms 동기화·250ms 신선도를 확인해 한 묶음을 저장한다. 수신 종료 후 확인 영역 함수로 전달하며 미제공은 확인 영역 없음이다. D Context 종료/Robot 명령/재시작/ROI의 확인 영역 승격은 없다. 실제 PC 간 ROS 시계 동기화가 필요하다.
- 관련 합성 ROS 수신·저장/live/observer/시작조건/runtime 검사89 passed, 종료0. 정상 단발 저장·수신 종료 순서·취소 전/수신 중/확인 영역 처리 중·이동 중 구독 금지·오래된 프레임 시간 초과·근거 없는 확인 영역 거부를 확인했다. 실제 RealSense/Controller/Camera→D 및 Geometry/층 설정은 미검증/미연결이다. 다음: V0 손 수신 ROS 연결 및 실제 확인 영역 생성/보정 입력 준비. Git 게시 없음.

- 기존 rgbd_io.save_capture에 선택적 검사 context(scene/실제 pose/calibration/check/sequence)를 추가했다. 기존 context 없는 진단 저장은 유지한다. 실제 ROS K/D를 역투영 입력 필드로 기록해 load_frame 형식과 연결했다. 잘못된 context·미지원 왜곡 모델·비동기 프레임을 거부하며 기존 파일 덮어쓰기를 금지한다. verified_regions/Geometry/층 기준을 임의 생성하지 않았다. D/Controller 코드는 변경하지 않았다.
- 검증: ROS 합성 메시지 신규6개 및 기존 live/runtime 관련 검사 합계54 passed (2.07초), 종료0. 실제 RealSense/ROS 수신 시험은 미실행이며 실제 capture_view 주입·영역 확인 근거·층 보정값은 여전히 필요하다. 이 변경은 저장 연결부이지 전체 Camera→D 연결 완료가 아니다. Git 게시 없음.

- 팀 요청에 따라 D가 엄지척 또는 로봇 작업 완료 후 요청하는 make_inspection_observer의 STEP 기본을 STOPPED_CLEAR로 수정했다. INITIAL/FINAL도 동일하다. 실제 정지·손 없음·영상 안정 확인은 유지하며 새 손 진입/이탈 3초를 재요구하지 않는다. 독립 HUMAN_ASSEMBLY 명시 호출과 로컬 live_view는 유지한다. 엄지척 인식/Robot 명령/D 파일은 수정하지 않았다.
- 관련 시작 조건·카메라 observer·INITIAL/FINAL 판정·팀 callback 검사: 60 passed, 1 skipped (3.61초), 종료 0. 실제 장치 검증과 구분한다. 실제 촬영 함수 주입·확인 영역 근거·실측 Geometry/5층 기준은 아직 필요하며 정상 전체 판 확인을 임의 생성하지 않았다. 다음: D 실제 촬영/정지 hook 및 실측 설정을 제공받아 Camera→B→D 공동 시험. Git 게시 없음.

## 2026-10-12 — 서플라이 요청 함수 연결부·RGB replay 추가

- 사용자가 현 시점 구현 가능한 작업을 요청했고 D의 Service 이름/타입은 아직 미정이라고 확인했다. 공통 ROS 타입/Service를 임의 추가하지 않고 supply_vision/request_session.py에 SupplyRequestSession의 submit/observe/cancel/expire를 구현했다. 명시적 TEST/REAL 모드, config 복사 고정, 단일 활성 요청, session 내 요청 ID 재사용 금지, 요청 이후/현재 이하 프레임, 추론 중 취소/만료 결과 폐기와 오류 원인 유지가 있다. mode가 REAL이어도 LOCAL_ONLY 결과이며 Robot 실행권한이 아니다.
- 기존 단발 ROS 진단 실행도 동일 session으로 요청/결과를 처리한다. replay.py는 원본 저장 RGB·실제 OBB 모델·실측 config·TEST 요청으로 ROS 없이 인식 결과 JSON을 저장한다. 원본/기존 출력 덮어쓰기 없음. request_TEMPLATE에 mode 미입력을 명시하고 README·BACKEND_HANDOFF에 호출 예시/오류 경계/transport 미연결을 기록했다.
- 실제 검증: supply 단위 검사 **43 passed**, 전체 supply/perception_mvp/legacy **325 passed, 1 skipped**, 각각 종료 0. 단위의 모델/clock/process는 합성·대체 연결이며 실제 D 통신 증거가 아니다. compileall·replay --help·git diff --check 종료 0. 기존 skip은 미제공 Consumer 소스 검사다. lint/type 미구성.
- 미검증: 실제 학습된 supply OBB 모델이 현재 모델 경로에서 확인되지 않음, 실제 RGB replay 추론/RealSense/ROS 수신·Service·Robot. 슬롯 ROI/HSV/관측·보정 설정은 실제값 필요. Service 타입/취소·응답 오류 형식/worker 연결은 D 합의 후 추가한다. 영상 callback이 STOP executor를 막지 않도록 실제 연결은 별도 검증한다. 새 클래스는 요청 취소가 추론 완료 결과를 무효화하는 독립 책임 때문에 1개로 제한했다. 신규 dependency/로봇 명령/자동 재실행/공통 계약 변경 없음. 사용자 미완료 변경을 보존했고 commit/push/PR 없음.

## 2026-10-13 — 공급판 윗면 세그멘테이션 Colab T4 학습 준비·연결 보류

- 사용자 ZIP은 train 6/valid 2, 5클래스, polygon 216/72개이며 ZIP CRC·클래스·유효 좌표/면적·이미지/라벨 대응·동일 decode 이미지 중복 검사를 통과했다. ZIP SHA256 a08e0240798435f15558e5404f3a33be0ae5f627fbc5315e487441f525315a30. 검증 사진은 정배치/회전 각 1장이다. 같은 촬영 환경의 소규모 시험으로 독립 성능/중심/파지 검증이 아니다.
- 초기 CPU 실행은 사용자 Colab 정정 직후 Ctrl-C로 종료 130, CSV 기준 4epoch만 보존했다. 완료 모델로 채택하지 않는다. 이후 학습 스크립트는 T4 GPU 검사와 device=0만 허용하도록 수정했다. 원본·데이터·부분 기록을 삭제하지 않았다.
- 원본 ZIP을 포함한 /home/roh/Documents/ChatGPT/협동2/supply_seg_training_20261013/C2_supply_top_YOLO26s_seg_T4_20261013.ipynb를 준비하고 Colab에 업로드했다. 노트 https://colab.research.google.com/drive/1Ox0Aa2_X8N0clmE8eWt7EFxk0dRvVz4b . 실제 GPU:Tesla T4와 CUDA:0 확인, 데이터 검사 성공, 학습 초기화 출력 확인. epoch 시작 전 런타임 재연결이 발생했고 완료는 없다.
- T4를 유지한 채 Colab 2025.10 런타임으로 전환을 시도했으나 활성 세션 수 제한이 나타났다. 이전 동일 노트 GPU 세션 종료가 자동 승인 검토에 거절됨(세션 종료 명시 승인 부족과 런타임 손실 위험). 종료 허용을 사용자에게 요청했고 우회 실행하지 않았다. 현재 실제 T4 학습 완료·결과 다운로드는 미수행이다.
- 최대60epoch/patience15/imgsz640/batch4/mask_ratio2/seed42/Ultralytics8.4.173의 YOLO26s-seg 시험이다. 기본 온라인 증강은 유지하되 mosaic/mixup/copy_paste는 0이다. data_local.yaml은 잘못된 상대경로와 없는 test 경로를 로컬 복사에서만 정리했다. 공식 초기 가중치 SHA256 3da1d83e31caec96f9300eb4064f4f62882c133c7c264d63dfe61a7c197837a4 확인. 노트 JSON·코드 컴파일 검사 종료0, 라벨 미리보기 직접 확인. 운영 supply 코드 OBB→segment 전환·실제 D/Robot는 이번 학습 범위에서 수행하지 않았다.

2026-10-13 후속: 사용자가 이전 동일 서플라이 GPU 세션 종료를 명시 승인했다. 해당 세션만 종료하고 Colab 2025.10/T4에서 다시 실행해 **60epoch 완료 및 TRAINING_COMPLETED/RESULT_ZIP** 출력을 확인했다. Python3.12.12/torch2.8.0+cu126/Ultralytics8.4.173, YOLO26s-seg, GPU Tesla T4다. 검증 mask mAP50=0.9800403, mAP50-95=0.5100232, box mAP50=0.9874194, mAP50-95=0.7604046. 2장 검증의 시험 지표이며 실제 중심·파지 정확도/독립 일반화 검증이 아니다. 모델/곡선/요약과 결과 ZIP은 Colab에서 생성됐지만 로컬 결과 ZIP 다운로드는 아직 확인하지 못했다. 관측 요약은 저장소 밖 supply_seg_training_20261013/COLAB_OBSERVED_SUMMARY.json에 보존했다. 다음은 모델 결과 로컬 보존·마스크 검수·supply OBB 실행기 segment 전환·D 인계 계약 확인이다.


## 2026-10-13 서플라이 윗면 segmentation 전환 (로컬 검사)

- 사용자 요청: 학습한 YOLO26s-seg를 서플라이 인식에 반영. main.py의 OBB adapter를 segment boxes+원본 크기 masks로 전환하고 OpenCV HSV 색상 후보 선행을 유지했다. seg_geometry.py는 윗면 마스크 네 모서리의 대각선 교점·변 중점·영상 긴 축 방향을 계산한다. 잘림/분리/네 모서리 추정 실패는 UNKNOWN/HOLD. 기존 요청 수명·픽셀 출력·로봇 실행 경계 유지.
- 실제 검사: supply tests 49 passed; supply+perception_mvp+legacy 회귀 393 passed, 1 skipped (이후 미사용 색상 검증 중복 함수 정리 후 supply 49 passed 재검사). git diff --check 정상. lint/type check 미구성.
- 모델: 기존 Colab 60 epoch 완료 출력은 남아 있으나 재연결한 새 런타임에서 best.pt 존재 False. 이전 로컬 CPU best는 중단된 결과여서 사용하지 않는다. 모델 다운로드·실제 모델 재현은 아직 미완료이며 T4 복구 학습을 진행한다.
- 미검증: 실제 RGB 윗면 중심/각도 오차, HSV 후보 및 crop 모델 성능, D 픽셀→로봇 보정·서비스·실제 파지. 실측 슬롯/보정 없는 template은 실행 설정이 아니다.

- 2026-10-13 T4 복구 학습: 사용자 원본 ZIP 업로드 완료 후 60 epoch 재완료. Colab recovery 노트 13NRfYjUhL7-0qiMsyCxVVTihEy29NLcr. best SHA256 4a55859c59fc77eb32f8270e7d0b123809efc6589b6f337729148f2165c5d486, mask mAP50=0.9800403/mAP50-95=0.5100232. Colab 파일 존재 확인. 기본 다운로드·파일 패널·직접 링크로 로컬 전달을 시도했으나 로컬 파일 미확인이며 이후 브라우저 연결이 끊겼다. 완료 모델의 로컬 반영·실제 모델 재현은 아직 미완료. 학습 재실행 대신 현 런타임 best.pt 다운로드를 우선해야 한다.


## 2026-10-13 서플라이 D 명명·예약 슬롯 정합

- 사용자 지시대로 서플라이 요청/config/응답을 view_id=SUPPLY_VIEW로 변경. 빨강 D 타입 1x2x1을 학습 라벨 red_2x1로 명시 매핑하고 이전 2x1x1 별칭은 거부. slot_id={color}_{brick_type}_{번호2자리} 출력 및 요청 예약 슬롯 검증/후보 제한 추가. Service는 여전히 로컬 초안이며 타입·운영 timeout·보정은 미확정. 기존 D 교시점·TCP·높이·로봇 실행 코드는 변경하지 않음.
- 학습 모델 로컬 저장 확인: /home/roh/Documents/ChatGPT/협동2/supply_seg_training_20261013/completed_T4/weights/best.pt, SHA256 4a55859c59fc77eb32f8270e7d0b123809efc6589b6f337729148f2165c5d486. 실제 이미지 2장 전체 추론은 수행했으나 단일 블록 HSV crop 추론은 모두 no_detection/HOLD. 이 문제는 별도 후속 인식 작업이며 이번 D 계약 변경으로 해결됐다고 표시하지 않는다.
- 실제 검증: 서플라이 관련 pytest 55 passed, git diff --check 정상. 실제 D Service/관측 이동/보정·파지 미검증.


## 2026-10-13 기존 공급 ROI 슬롯 방향 연결 및 모델 입력 수정

- 사용자 확정 오른쪽→왼쪽 1~6을 모든 종류의 세로줄에 적용. 기존 20261012T002844481743Z ROI를 보존하여 저장 영상의 노랑·파랑 24개 슬롯 시험 영역 구성. 빨강 두 행 중 D 대상 행은 사용자가 로봇팀 확인 필요라고 응답하여 제외.
- HSV 색상 후보 선행 유지 후 YOLO는 학습 시와 같은 전체 원본 영상을 한 번 추론하고 후보와 색상 대조. 작은 crop 미검출 경로 제거. 실제 완료 모델 저장 영상 replay 결과 CANDIDATES, 예약 blue_2x3x1_01 중심 후보 반환. 슬롯별 결과 {'CENTER_CANDIDATE': 13, 'multiple_detections': 11}. 이는 실제 중심 정확도/파지 성공 검증이 아니다.
- 시험 설정/결과/이미지는 외부 completed_T4 폴더에 저장. 임계값 및 슬롯 경계는 저장 영상의 시험용이며 최신 카메라/보정 검증 미완료. 실제 Service 및 D 보정 미연결. 관련 테스트 55 passed.

- 2026-10-13 요청 대상만 중심 계산하도록 범위 축소: 종류·색상+D 예약 slot_id 하나로 HSV 설정/슬롯 진단/기하 계산 제한. 전체 원본 YOLO 추론 문맥 유지하되 다른 슬롯의 중심은 계산하지 않고 반환하지 않는다. 다른 슬롯 중복은 요청 결과에 영향 없음. 요청 슬롯 내부 복수 검출 판정은 유지. 관련 pytest 55 passed, git diff --check 정상. 이번 범위 변경 후 실제 카메라/파지는 미검증.

- 2026-10-13 사용자 첨부 supply_top_yolo26s_seg_best.pt로 전체 블록 진단 실행. 기존 infer_color_candidates/geometry_from_mask 호출, 저장 원본 rgb.png, conf=.25, OpenCV class-agnostic NMS IoU=.5로 47개 예측을 36개 외곽으로 정리(동일 위치 중첩 예측 11개). 외곽 36개/중심 후보 33개, 네 모서리 조건 실패 3개는 보류. imagegen/수동 중심/라벨 GT로 중심 생성하지 않음. 실제 파지 미검증. 외부 all_blocks_model_test에 실행 스크립트·JSON·이미지 보존. 운영 요청 슬롯 제한은 유지.


## 2026-10-13 현재 B 브랜치 보존 커밋

- 사용자 요청으로 현 브랜치 코드·설정·테스트·인계 문서를 commit/push한다. 별도 worktree 및 pull/merge는 하지 않는다. 신규 공급 모델 .pt와 assembly replay/empty column 시험 산출물은 ignore로 로컬 보존. 기존 손 모델 추적 제거 변경을 포함한다.
- 실제 검사: 공급+perception_mvp+legacy pytest 443 passed, 1 skipped; git diff --check 정상. 이는 실제 팀 연결/로봇 파지 검증 완료를 뜻하지 않는다.

- 2026-10-13 사용자 요청: 이전 공급 OBB 코드/테스트와 로컬 학습 준비 스크립트 3개를 원격 브랜치 최신 트리에서 제거. 외부 unused_code_backup_20261013에 로컬 보존. 현재 모델 종류 거부 검증은 test_segmentation으로 이동. 관련 pytest 53 passed, diff 검사 정상. 무관한 미커밋 변경 보존. 과거 Git 이력은 다시 쓰지 않는다.


## 2026-10-13 D 회신 기반 공급 측정·취소 타입 초안

- 1차는 관측·정지→요청→영상 측정 응답 확인, 보정 이동/슬롯 소모/집기 성공 처리 제외에 합의. interface_draft에 SupplyMeasure.srv/SupplyCancel.srv와 측정 6개·취소 3개 구조 예시 작성. 패키지 c2_perception_interfaces, 상태 매핑·재취소 규칙은 제안으로 D 확인 필요. 실제 ROS 패키지/서버/클라이언트는 미구현.
- D 실물 운영 슬롯 1~5만 요청하며 6 교시 자료 유지. 빨강 행/4점 닫힘 축은 확인 필요. 가상 좌표 예시는 실제 측정·보정 자료가 아님.
- 실제 검사: srv 필드와 JSON 예시의 정확한 필드·형·배열 길이·ID/geometry validity 정합 검사 9개 예시 정상, 공급 pytest 53 passed, diff 검사 정상. ROS 타입 생성/실제 통신/카메라·로봇 검증 미실시.

- 2026-10-13 RUN_GUIDE.md 작성: 저장소 루트 기준 상대 경로로 모델/config 준비·저장 RGB replay·ROS RGB 단독 시험·D Python 함수 호출 안내. TEMPLATE 미확정 값과 실제 연결 미완료를 명시. CLI --help, 경로/코드펜스/개인 절대 경로 미포함 확인. 실제 카메라·D 연결 실행은 이번 문서 작업에서 하지 않음.

- 2026-10-13 RUN_GUIDE 최신화: 팀장님 PC에서 첨부 모델을 저장소 상대 경로 models/supply_top_yolo26s_seg_20261013/best.pt로 배치하는 방법, SHA256 확인, 함께 전달할 저장 RGB/ROI 및 값이 채워진 local 설정·요청 추가. 개인 절대 경로 없음과 코드펜스 정합 확인. 코드·모델 및 실제 시험 동작 변경 없음.

## 2026-10-12 A 안내·자료 분류 정리 (기준 integration 1b820405)

- 루트 README에서 현재 A 안내를 직접 연결하고, 기본 Planner·확장 세 API·SIM 경계를 구분했다.
- Python/jsonschema/pytest 설치와 ensurepip 없는 환경의 독립 venv 대안, 예제 입력·명령·정상/실패 결과, 동일 계획 자료의 B/D 공유를 안내했다. Current/revision은 B 확정·D 중계 기준이다.
- [A 분류·보존 안내](A_MATERIALS_AND_PRESERVATION.md)와 [253파일 SHA 목록](A_PRESERVATION_MANIFEST_20261012.json)을 추가했다. 외부 원본·실측·Fixture·시험 기록은 기존 경로/바이트 유지, 과거 A README 457줄은 원문 그대로 보존했다.
- 새 clone·독립 최소 가상환경에서 기본12블록 Plan·잘못된 revision 반환·API34/34, A pytest448 passed/1 skipped를 확인했다. SciPy 독립 비교1검사는 최소환경 미설치로 제외됐다. 범위가 겹치는 수치는 합산하지 않는다.
- [실제 명령·결과와 미검증](A_DOCUMENTATION_VERIFICATION_20261012.md)을 기록했다. 기준 Isaac0.5 불일치는 별도 기능 변경 eb78ad7과 분리하며 이번 PR에는 기능 변경을 포함하지 않는다.
- 파일 이동/삭제·계산/계약/보정 수정·새 dependency 도입·전역 설치·Git 이력 재작성·Robot/ROS/Isaac 실행·제어권 변경을 수행하지 않았다. 사람 리뷰·실제 연결·실기 검증은 남아 있다.
- GitHub에서 직접 받은 새 clone(0e6248f)에서도 API34/34, A448 passed/1 skipped, 보존253/253 SHA·상대 링크44개를 확인했다. 로컬 clone과 원격 clone의 수치는 합산하지 않는다.


## 2026-10-12 A 손 수 상한 제거·실패 진단 보완

- 사용자 요청으로 최대 2손 제한을 계산·후검사·현재 0.5.1 계약에서 함께 제거했다. 필요한 동작/손 수, 지지/겹침/삽입/로봇 접근 검사는 유지한다.
- D 현재 원본에서 승인 24블록 실패를 재현했으며, 제한 제거 후 같은 설계/Current로 CPU 약 0.82초·GPU 약 0.47초에 전체 계획 생성. 3손 단계 3개를 포함한다.
- CPU A/C 전달 검사 480개, GPU A 검사 458개 통과(합산하지 않음). 실패는 기존 block/reason으로 구체화하고 실제 물리 미판정 범위를 표시했다.
- [입력 복원 근거·변경·검증·적용 위치](A_HAND_COUNT_POLICY_20261012.md). D 작업 폴더/로봇/제어권은 변경하지 않았다. `codex/a-plan-failure-diagnostics-20261012`를 통합 브랜치 대상으로 리뷰하며 병합·배포·실기 검증은 별도다.
- 2026-10-13 제출 전 통합 `7b1a5ff`에 충돌 없이 정렬했다. 관련 검사479 PASS / 1 FAIL(A458 PASS, Workflow21 PASS / 1 FAIL). C의 `test_inspection_context_keeps_expected_and_unknown_regions_for_c`는 변경 없는 통합 사본에서도 같은 IndexError로 실패했으며 이번 패치에서 수정/제외하지 않았다. 기존480 PASS는 이전 통합 기준 결과다.
- PR #34(`gimseeun`) 게시 중 통합에 PR #33이 반영돼 `f247132`로 갱신됐다. 최신 통합을 일반 merge로 반영하고 양쪽 Workflow 검사를 보존해 충돌 해결. A/Workflow/PR30 전달 검사501 PASS / 0 FAIL(19.16초). 이전 기준 실패 검사도 PR #33의 입력 정렬 후 통과한다. 최종 범위는 원래13파일이며 실물/제어권 변경은 없다.


## 2026-10-13 09:39 REAL 후속 — D 빈 복귀·힘 검사 범위 수정

- 이전 Step의 공급 슬롯으로 복귀하던 연속 이송을 제거했다. 결착 후 조립 위치 위로 상승/검사하고 다음 Step의 최신 선택 슬롯으로 경유 접근한다.
- 사용자 요청대로 `full-real`의 비결착 단계에서 앱의 35N 합력/Fz 검사를 해제했다. 결착의 전체 반력35N STOP·정지 확인·개방과 장치/피드백 검사는 유지한다.
- 실제 검사: D 오프라인1,076 passed·외부 A 자료 collection skip1, A/D REAL 문서+MOCK21 passed, Workflow/슬롯43 passed. 실제 Robot/ROS/카메라/외부 API/DB 미실행. 물리 부드러움/충돌/결착 성공은 재시험 필요.
- 원격 A PR34 반영(`ca3101a`) 확인, 로컬 A는 자동 동기화하지 않았다. 로컬 D 실행 소스/검토 복사본만 수정했으며 commit/push/PR/merge·브랜치 전환 없음. 상세는 `docs/D_FULL_FEATURE_REAL_TRIAL_20261012.md` 최신 절 참조.


## 2026-10-13 S06 블렌딩 경유 기준 확대 — 후속 PR 반영

- 요청: 블렌딩 도중의 과도한 판정을 완화하고 공급 슬롯6을 포함해 진행. contact-alignment 시험의 경유10mm/5°, 경로80mm, timeout 최솟값45초를 적용했다. 도달/정지 확인 후 즉시 진행하며 고정45초 대기를 넣지 않았다.
- MoveB가 목표 근처에서 멈추면 원래 최종 목표까지 MoveL 한 번으로 마친 후1mm/1° 도착을 확인한다. 교시·속도/가속도·블렌딩 반경40·결착 XYZ 반력35N 조건은 유지한다. 최종 미도달은 실패/보류이며 집기로 넘기지 않는다. 구 실행의 `resume_allowed=False`를 터미널/로그 편집으로 바꾸는 복구 기능은 추가하지 않았다.
- 실제 검증: D 오프라인1,106 passed/collection skip1, 최신 로컬 A/D REAL 문서→MOCK21 passed, 모두 종료0. 기록된 S06의 기존 timeout 재현/새 정책 도착,4점/6점×노랑/파랑×로봇/사람 인계에서1→2→3→4→5→6→1(56가상Step), 정상/실패 경로를 검사했다. Python/실행 명령 구문과 D 소스 복사본 일치도 확인했다. 외부A onsite 자료 부재1건 제외.
- 실물/실행 중 프로세스 미검증. 사용자 요청으로 후속 PR 게시 대상에 포함한다. 실물 검증·병합은 별도이며 로컬 고정 개발 브랜치를 유지한다. [검증 기록](reviews/robot-blend-slot6-verification-20261013.json), [실행 안내](D_FULL_FEATURE_REAL_TRIAL_20261012.md).

### 2026-10-14 Round2 세 분기·각도 자동 반복·하드코딩 점검
- 일반 step 준비/실행 API와 preview 진입점을 추가. ROBOT_FASTENING, HUMAN_SUPPORT_PLACE_BOARD, HUMAN_FASTENING_ROBOT_COMPLEMENT/FALLBACK 분리. 원본 plan/profile 및 B 완료 소유 보존.
- 기존 board calibration의 층별 평행 방향을 실제 모서리 근처에서 투영. 중심 일치 없이 yaw 비교. held integrated 기본 자동 yaw, 새 영상 모서리 추적, 포함 경계±0.50°, 반복 횟수 상한 없음. 실제 등록 평면 provider가 있을 때만 자동 RPY로 표기; HJK는 기준 복귀 시험.
- 사용자 +10mm 시험을 최초 공급 파지/안착에 함께 적용하고 빈 패드 접촉은 유지. 실측15mm 검증으로 표시하지 않음.
- 목표11,11 로그·복귀 속도/힘 중복값 수정, OpenCV 슬롯별 임계값 우선, Round2 이동 속도 profile 설정, 닫힌 빈 패드 status2 동작 보완. 런타임 경로 상대경로 지원.
- native 전체 단위테스트1346개 통과(2026-10-14 현재 작업본). PR 복사본에서 다시 검증 예정. 장치 모션 미실행. 기존 StepRuntime HMI 자동 호출 연결과 실제 윗면 producer/높은 파지 실물 검증은 완료 주장하지 않음. 상세: D_ROUND2_ROBOT_CONTROL_AUDIT_20261014.md.

- PR 복사본 검증: native 전체+관련 비전1498개, 등록 기하/파지 계획29개 통과(합계1527개). 실제 device command 없음. 일반/held preview 정상, source/JSON 및 diff 확인. 4층 채택 실측 선택·축 힘35N 불일치·미검증 패드 datum 승격도 점검해 수정.

- 검토용 Draft PR #46 게시: https://github.com/suuuhululu/C-2/pull/46 ; base=codex/integration-round2, head=codex/round2-robot-control-20261014. merge하지 않았으며 기존 작업 checkout/다른 변경은 보존했다.

### 2026-10-14 로컬 웹 목록 새로고침·대용량 상세 조회 수정

- `b0d22e5` 기준 별도 웹 checkout의 `codex/web-design-refresh-20261014`에서 수정. 직접 로그인과 세션 복원의 보기 차이를 해소하고, GALLERY / MY DESIGNS 선택을 탭의 sessionStorage에 유지한다. 목록 조회 중에는 로딩 상태를 표시하며 오류는 빈 정상 목록으로 감추지 않는다.
- 개인 상세에 소유자 인증을 유지하는 `/api/jobs/{id}/summary`를 추가했다. 전체 이력으로 설계·검사·완료·저장 근거를 계산하되 화면 timeline은 최근 100개와 전체 건수를 반환한다. 기존 전체 상세 API와 EXPORT JSON은 전체 기록을 유지한다. 항목 JSON은 펼칠 때 생성한다.
- 실제 기존 작업의 디자인 버전1·2·3, 이벤트62,185개를 읽기 조회로 확인했다. 전체 timeline JSON164,373,310바이트에서 summary 응답866,536바이트로 줄었으며, 이 환경의 summary DB 조회·직렬화6.9초를 측정했다. 고빈도 camera/motion 로그가 많아 서버의 전체 이력 읽기 비용은 남아 있다.
- 별도 `c2_history_web_test` DB에서 기존 HTTP/개인 이력 검사와 새 summary 범위·소유자 격리 검사를 실행해22 passed, skip0. 실제 app.js를 실행하는 DOM 대역의 새 보기 복원/소유v1–v3 Publish 활성/summary 조회/전체 export/오류/lazy JSON 검사와 기존 SVG 검사, JS/Python 문법·diff 검사를 통과했다.
- 실제 로그인된 브라우저에서 페이지 새로고침 후 MY DESIGNS의v1·v2·v3 카드와 로딩 안내를 확인하고, v3 상세의 Publish 버튼 활성화를 확인했다. 실제 게시 버튼은 누르지 않았다.
- 로컬 서버에 적용했다. 기존 원본 로그·계정·Job·DB 이벤트·게시 상태는 보존했다. GitHub push/PR/merge, Robot/ROS/카메라 동작, 실제 디자인 게시·삭제는 수행하지 않았다. 이벤트 선별 적재 정책은 이번 조회 수정에 포함하지 않았다.

### 2026-10-14 원본 보존·선별 DB 적재·도안 중심 웹 (위 초기 수정의 후속)

- 통합 대상 `codex/integration-round2`의 최신 `e868bba`를 일반 merge로 반영했다. 사용자 지시에 따라 웹은 로그를 불러오지 않고 도안·제작자·최종 채택 설계의 완료/저장/공개 상태만 조회한다. EXPORT DESIGN JSON은 선택 버전의 Design만 내보내며 전체 이력 API를 호출하지 않는다.
- 신규 source는 `operational-v1`을 기본으로 일반 ROBOT_CAMERA_CANDIDATE/ROBOT_MOTION_SAMPLE만 제외한다. 신호 후보·명시적 오류/실패·사유·알 수 없는 이벤트는 보존한다. 기존 source의 all 정책·업무 기록·소유권·영수증·공개 상태는 유지한다.
- 원본은 별도 SHA-256 파일명 스냅샷으로 보존하고, 미완결 꼬리까지 bytes를 유지한다. 선별 전 모든 완결 행을 검사하며 prefix 해시로 제외한 행의 수정·잘림도 거절한다. 003 migration은 source 보관/선별 메타데이터만 추가한다. Docker /records 읽기 전용은 유지하고 /reports/original_logs에 보관한다.
- 최신 통합 반영 후 관련 Python/실제 별도 PostgreSQL 검사233 passed, 외부 Robot 자료/5층 MOCK 산출물 미준비4 skipped, 실패0. DOM/설계 export·SVG 검사와 JS/Python 문법·diff 확인 통과. Docker에서 실제 읽기 전용 입력·쓰기 가능한 별도 보관·선별 적재와 원본 bytes 유지도 확인했다.
- 기존 원본62,186행을 분리 시험 DB의 rollback 범위에서 적재해7,294건 선택, Design v1/v2/v3·제스처 후보·마지막 CAMERA_FAILED 보존을 확인했다. 원본64,575,350bytes 사본과 운영 DB 백업은 로컬에 별도 보관하고 Git에 포함하지 않았다. 운영 DB events62,185/jobs1/users1/artifacts9/영수증1/공개0이 유지됨을 확인했다.
- 같은 로컬 DB에서 도안 library 조회0.047초, summary 조회0.649초/응답11,159bytes를 한 번 측정했다. 서버 DB 조회 기준이며 전체 사용자 응답 시간 상한이나 성능 보장은 아니다. 전체 이력·원본은 운영 CLI/API와 별도 파일로 유지한다. [정책·실행·한계](D_HISTORY_SELECTION.md).
- 로컬 웹 서버에 적용했다. 실제 게시·삭제·Robot/ROS/장치 동작은 실행하지 않았다. 사용자 요청에 따라 위 변경을 integration-round2 대상 PR로 게시하며 병합은 사람 리뷰 대상이다.
- [PR #49](https://github.com/suuuhululu/C-2/pull/49) 게시 완료: base=`codex/integration-round2`, head=`codex/web-design-refresh-20261014`. 현재 OPEN이며 병합하지 않았다.


## 2026-10-14 D 현장 후속·세 사이클·영상 XY

- 접촉 반력과 일반 이동의 힘 검사를 분리하고 None 비교 오류를 수정했다. 명시 target_only_motion 설정에서 좌표·자세·IK/FK 정밀도 차단을 사용하지 않으며 영상 신선도와 기존 STOP/장치 피드백을 유지한다.
- T1 슬롯4/(9,9,L2) → T2 슬롯3/(13,11,L2) → T3 슬롯5/(15,14,L3) 세 사이클 진입점과 포터블 wrapper를 제공한다. T2 중앙 파지·완전 결착·닫힌 패드 교시를 사용하며 이전 +10mm를 추가하지 않는다. 약8mm는 사용자 추정이다.
- 영상 모서리·목표 변으로 dX/dY를 계산해 X/I에 전달한다. 파지 보상으로 TCP가 이동해도 블록 목표·실측 패드 목표는 유지한다. A 원본 RELEASE_PRESS/도움 정보를 보존하는 로봇 실행 분기와 빈 패드 다음 Step 전이를 연결했다.
- 게시 사본의 외부 연결 차단 native 1,509 PASS, 영상 XY/가상 격자49 PASS, 합성3Step THREE_CYCLES_COMPLETED/물리명령0. 범위는 합산하지 않는다. 최신 교시·영상XY·공중놓기 실물과 방출 후 재관측은 미검증이며 상공해제 높이는 미정이다.
- [현장 수정·검증](D_ROUND2_ROBOT_FIELD_FIXES_20261014.md), [세 사이클 명령](D_ROUND2_THREE_STEP_TRIAL_20261014.md). 서비스의 A–D 전달 수정은 별도 PR이며 B Current·revision·완료 소유를 유지한다.


## 2026-10-15 로봇 PC Round3 준비 점검 (실물 T1 미실행)

- `codex/integration-round3` / `bda07e5`를 별도 작업본으로 준비하고 기존 미커밋 교시·설정은 보존했다. main 병합·강제 초기화·push·설치·드라이버 재빌드는 하지 않았다.
- 실제 환경: `/home/rokey/cobot2_ws`, 기존 `robot_control_integration_20261010/runtime/drcf2`, `c2_integration_round1/.venv`의 Python 3.12.3. 필수 import 및 DRCF2 두 라이브러리의 기존 READY 해시·동적 의존성을 확인했다.
- 이번 실행: 공급판 합성 검사 63 passed, T1 제어 검사 80 passed, HMI 고정 T1 모의 검사 10 passed. native T1 preview/replay 통과. replay는 SYNTHETIC/MOCK·physical_commands=0이며 물리 정확도·결착을 검증하지 않는다.
- 기존 round2 로봇/그리퍼 드라이버를 발견해 중복 실행하지 않았다. 읽기 조회상 TCP=GripperDA_v4/Tool=ToolWeight0, HOME 근처이나 실제 빈 그리퍼·현장 준비 완료는 미확인이다. 로봇/그리퍼 동작·모드 변경 명령은 보내지 않았다.
- 카메라 D435i는 USB2.1 연결이다. 1280x720x30 요청은 거부 후 640x480x15로 복귀했고 실제640x480 메시지를 확인했다. 지원 설정1280x720x15에서도 프레임 손상과8초간 RGB/정렬Depth/CameraInfo 미수신으로 요구 해상도 전송은 통과하지 못했다. 점검용 카메라는 정상 종료, 기존 로봇 드라이버는 유지했다.
- 이 작업 폴더에서 발견한 RGB-D 프로파일은 미검증 템플릿뿐이다. 이를 지정한 preview는 SUPPLY_DEPTH_CALIBRATION_NOT_VERIFIED로 거부됐다. 기존2D등록·미완성 측정을3D보정으로 승격하지 않았다.
- BLOCKER: 카메라 연결/프레임 정상화, 검증된 camera→TCP 변환, T1 슬롯4 교시 기준 표면중심, 변환640x480영상 ROI/크기조건·깊이/오차/XY 허용범위와 설정 바인딩. 회전·Z·힘·속도는 변경하지 않았다.
- 실제 native/HMI T1, 파지·결착, B 실제 조립 확인, 최종 DB 저장은 미실행이다. 다음은 USB3 연결 확인과 실측자료 확보 후 profile preview → 사용자 직접 native T1 → 결과검토 → HMI T1 순서다. `--start-zone home`은 HOME 이동 명령이 아니다.
- 로컬 증거·환경설정·터미널별 재개 명령: [점검 보고서](</home/rokey/Documents/ChatGPT/로봇제어 개발/reports/round3_robot_pc_20261015/RESULT_AND_NEXT_STEPS.ko.txt>).


### 2026-10-15 후속: roboton/realsense/roboton2 비교 및 카메라 결론 정정

- USB2.1에서도 RGB1280x720x10/Depth848x480x10/Infra1·2 OFF 설정으로 실제 RGB·정렬Depth·양쪽CameraInfo가1280x720, 약9.994Hz로20초간정상수신됐다. RGB200/Depth201/각Info200개, 대응packet 최대시각차0ms, 관측나이약120~144ms. 앞선30/15fps실패만으로USB3변경을필수전제로한판단은정정한다.
- 개별 `realsense` 함수는 Infra1/2를 명시적으로 끄지 않아 실제IR640x480x15 두 스트림이 추가 기동됐고, 프레임손상과8초간RGB-D/Info미수신이 발생했다. IR OFF 조합에서는 시험 중 손상 경고 없이 수신됐다.
- 현재 `roboton2` alias는 round2 현장수정본을 가리킨다. 내부bringup의camera=false가같은launch context에남아바깥카메라조건도false가됨을장치실행없이재현했다. 마지막CLI camera=true가무시되는문제는아니다. 통합카메라Node는실제로건너뛰어진다.
- round3@bda07e5의통합launch는위10fps별도Node가없고설치bringup의30fps설정에의존하므로alias와동일경로로취급하지않는다.
- 비교는기존로봇드라이버유지상태에서카메라만단독실행했다. alias/launch원본수정과로봇·그리퍼동작없음. 시험카메라정상종료. 기동시hash_map/rcutils/typesupport오류는별도미해결이며장시간안정성이나실보정정확도검증은아니다.
- 실측RGB-D프로파일과슬롯기준표면중심등은여전히미준비이며실물T1은실행하지않았다. 근거: [alias·카메라 비교](</home/rokey/Documents/ChatGPT/로봇제어 개발/reports/round3_robot_pc_20261015/ALIAS_CAMERA_REVIEW.ko.txt>).


### 2026-10-15 슬롯4 기준 표면 원자료 기록 준비

- 사용자는 기존 Calibration_Tutorial 보정으로 실제 좌표 이동 정확도를 검증했다고 확인했다. 이를 기존 외부 보정 검증 근거로 채택하고, 체커보드 재측정 대신 슬롯 기준점 측정으로 진행한다. 당시 TCP/현재 TCP 및 장착 바인딩은 별도 확인 중이다.
- `scripts/capture_supply_depth_reference.py`를 추가했다. capture는 허용된 조회 서비스4종과 RGB-D/CameraInfo만 사용하며 로봇·그리퍼 동작/기동/TCP변경을 하지 않는다. 실제 관측 자세·TCP/Tool·정지·메시지 크기/frame/시각을 검사하고 원본과 변환영상을 새 폴더에 기록한다. analyze는 실제 ROI와 저장 파일로 표면점 후보를 계산한다. 기존 교시XYZ를 표면중심으로 대체하지 않으며 reference_accepted=false를 유지한다.
- 새 합성 검사7개와 기존 RGB-D 검사34개, 총41 passed. 실제 원자료 capture 및 실물 T1은 미실행. 현재 ROS에는 camera만 확인돼 로봇 드라이버는 작업자가 준비해야 한다.
- 기존 보정행렬/교시/현장 설정은 변경하지 않았다. 새 동작 pose·속도·힘을 만들지 않았다. 기록문턱0.5mm/0.5deg는 측정자세확인용이며 실제 파지 합격허용오차가 아니다.
- 로그/터미널별안내: [슬롯4 기록](</home/rokey/Documents/ChatGPT/로봇제어 개발/reports/round3_robot_pc_20261015/SLOT4_REFERENCE_CAPTURE.ko.txt>).


### 2026-10-15 TCP v1→v4 변환 및 기준 촬영 첫 시도

- 사용자 확인: 기존 실물 좌표 이동 검증 시 TCP는GripperDA_v1(Z208mm), 현재는GripperDA_v4(Z228mm)이며 회전0/0/0과 Z이외 조건이 같다. 기존행렬 앞에TCP좌표 Translation(0,0,-20mm)을곱해 별도v4용파생행렬을만들었다. 원본해시동일, 로봇TCP정의/파지Z/관측pose변경없음.
- 합성 좌표계 변환 일관성 검사의 최대오차1.42e-14mm. 이는대수검사이며새실물검증주장이아니다. 파생자료와근거는로컬reports/round3_robot_pc_20261015/calibration에보존했다.
- 사용자가실행한capture의precheck: 현재BaseTCP[-518.242,195.492,47.420,...], 기준관측자세차이409.119mm/1.253deg. 조건에따라촬영중단, physical_commands=0. 이오류는20mm TCP차이와별개다. 실패원자료는logs/supply-depth-reference/20261015T074530에보존했다.
- 기록도구중단안내에실제/기준자세와차이를추가했다. 관련합성검사7passed. 실제RGB-D기준촬영/ROI/슬롯표면Base좌표채택/실물T1은여전히미완료다.


### 2026-10-15 슬롯4 수동 교시 의미 확인

- 사용자는 현재 GripperDA_v4 TCP 자세가 노랑2×2 슬롯4를 파지하기 위해 그리퍼를 닫기 직전 자세임을 확인했다. 이를 실제 센서 precheck와 연결한 별도 pre-close 교시 기록으로 보존했다. 실제 파지 성공이나 표면 중심 확인으로 해석하지 않는다.
- 기록: reports/round3_robot_pc_20261015/slot4-teaching/yellow_2x2x1_04.preclose.json (저장소 상위 로컬 reports). 출처는 logs/supply-depth-reference/20261015T074903/precheck.json이다. 원본과 기존 실행 설정은 보존했고 runtime_config_changed=false다.
- 다음은 블록의 기준 위치·방향을 유지한 채 기존 관측 자세에서 RGB-D를 기록하는 단계다. 표면 중심 분석/프로파일 작성 때 이 새 pre-close 기록과 묶고 기존 INTERPOLATED pickup을 조용히 대신 사용하지 않는다. 최종 실행에는 교시값과 표면 기준점을 함께 연결해야 한다.
- 그리퍼 닫기·로봇 이동 명령은 보내지 않았다.


### 2026-10-15 기준 표면 촬영·품질 확인 및 배치 확인 정정

- 사용자가관측자세에서촬영한5장(20261015T075833)은RGB/정렬Depth/CameraInfo동기0ms와촬영전후정지조건을충족했다. 변환640x480영상에서맨위노랑2x2오른쪽부터4번째ROI[255,91,300,135]를확인해같은스터드검출과3x3패치로표면후보를계산했다. 새pre-close교시파일을명시적으로바인딩하는analyze옵션을추가해기존보간pickup이자동재사용되지않게했다. 실행설정은변경하지않았다.
- 초기5장깊이532~537mm, 계산표면Z범위약4.97mm. 추가읽기전용20장촬영은로봇·그리퍼명령없이완료됐으나10장에패치깊이0이있어엄격분석이INVALID_DEPTH_PATCH로중단됐다. 전체20장의실패내역을surface-quality-audit.json에보존했다. 나머지10장깊이525~529mm는진단값이며실패프레임을버리고합격처리하지않았다.
- 사용자는처음블록유지라고확인했다가살짝건드렸을가능성을보고했다. 최신확인에따라원5장및추가20장을이전파지교시의기준점으로채택하지않는다. 원본이미지·메타데이터·기존교시자료는보존하고파생자료상태를NOT_ADOPTABLE_POSSIBLE_BLOCK_MOVEMENT로갱신했다.
- 새teach-pickup은수동으로맞춘노랑2x2슬롯4의닫기직전TCP를조회만해별도기록한다. 관측높이/공급판범위밖/TCP불일치면거부하고, 실제파지성공이나표면중심으로승격하지않는다. capture --pickup-record는새기록을촬영설정사본에만바인딩한다. runtime변경없음.
- 관련합성검사43passed(reference-pair-tests.log). 다음은새pre-close교시→블록유지→관측자세촬영의한쌍취득과깊이품질확인이다. 외부보정v1→v4변환은보존한다. 기준점채택/실물T1/B확인/DB저장은미실행이다.


### 2026-10-15 새 슬롯4 측정 묶음 pair-20261015T080359

- 새pre-close교시와관측20장연결이일치하고사용자가이번블록위치·방향유지를확인했다. 파지TCP는[-519.361084,196.431503,49.384441,1.379895,178.199310,1.312952]이다.
- 20장모두스터드검출/3x3패치비영검사통과. 깊이529~532mm, 패치최대편차2mm. 계산표면Base중앙값[-530.369055,203.071033,100.153308]mm, 변동폭XYZ[0.295434,0.956890,2.985623]mm. TCP파지점과표면점은구분한다.
- 각관측나이140.475~294.790ms/packet시각차0ms, 촬영전후pose차0.001052mm/0.000201deg. 제외프레임없음. 원자료/분석은해당pair폴더에보존했다.
- 사용자는기존허용기준이없다고확인했다. 현시점20장의변동을허용기준으로대체하지않는다. 독립상대XY변위검증과공정허용기준검토가다음단계다.
- 비활성프로파일/슬롯4전용ROI초안을상위reports/round3_robot_pc_20261015/slot4-profile-draft-pair080359에만저장했다. 허용값4종은null, independently_verified=false이며load_profile거부를확인했다. 실행설정/원본보정/속도·힘·회전변경없음.
- 사용자가직접실행한MoveLine의vel[30,30]/acc[60,60]은T1기본설정으로반영하지않았다. 이번agent동작은저장파일분석뿐이다. 실제T1/파지·결착/B확인/DB저장은미실행이다.


### 2026-10-15 validation-01 수동 파지 교시 비교

- 사용자가저장한검증파지교시는기준대비Base XYZ [+2.523804,+0.033249,-1.373463]mm, 실제회전차0.229962deg이다. TCP/Tool은일치한다.
- 계획한동일높이XY검증과달리Z도변해원자료와pickup-comparison.json을보존하고순수XY검증점채택을보류했다. 서로다른파지간의공정허용오차를새로확정한것은아니다. RGB-D검증촬영은아직없다.
- 다음은블록을더옮기지않고기준파지Z/방향을유지해수동정렬한뒤새폴더에기록하는단계다. 로봇·그리퍼명령과실행설정변경없음.


### 2026-10-15 독립 검증점1 관측 비교

- validation-01-height-matched-02의수동교시변위XYZ[+2.674561,-0.280029,-0.129997]mm/회전차0.203894deg에대해RGB-D변위XYZ[+1.599257,+1.043245,-1.933472]mm. XY차이1.705090mm로실측됐고합격기준없음/수동정렬재현성미정이므로통과확정하지않았다.
- 저장20장모두검출·비영패치검사통과하나Depth527~537mm/패치최대편차4mm/표면Z범위약9.94mm. 추가읽기전용라이브20packet의처리후관측나이는138.89~164.06ms/만료0/표면패치오류2건. 카메라설정은조회만했다. emitter켜짐, Infra꺼짐, temporal/spatial/hole-filling꺼짐을확인했다.
- 감도분해를위한고정Depth계산에서도XY차이약1.18mm가남았으나이는진단전용이며실Depth대체나명령으로사용하지않았다. 깊이·수동정렬·외부보정의영향을한원인으로단정하지않는다.
- 기존보정재학습/허용범위확대/불량프레임제외합격처리/실행설정변경없음. 프로파일비활성유지. 결과는해당validation폴더의relative-displacement-validation.json 및VALIDATION_RESULT.ko.txt에보존했다. 실제T1/파지·결착/B판정/DB저장은미실행이다.


### 2026-10-15 사용자 교육용 수용 및 native T1 준비

- 사용자는 교육용프로젝트에서이번약1.71mm XY차이를수용하고진행하도록명시했다. 정밀검증표시를승격하지않고independently_verified=false와실측오차·수용근거를기록한별도교육용프로파일을준비했다. --educational-depth-demo 명시옵션은슬롯4고정T1에만허용되며기본실행과다른step에는적용되지않는다.
- 품질거부한계는실측40장근거의Depth527~538mm/패치편차4mm/높이차7mm/XY보정3mm다. XY정확도오차1.705mm와보정상한은구분한다. 0깊이·시각·frame·구성바인딩·범위초과검사는유지했다. 진단불량을교시좌표로대체하거나자동재시도하지않는다.
- 새pre-close교시와실영상T1전용ROI를별도scenario에연결했다. 기존기본설정·교시원본·조립판/패드기준·속도·힘·가속도변경없음. 교육용로그에는verification_basis와수용오차를남긴다.
- 관련검사173passed, 기존HMI모의검사10passed. 장치없는native preview1cycle통과. 저장실측40packet오프라인검사통과/파지Z·회전보존. 이번agent실물동작명령0.
- 설정·근거·실행안내: robot_control_integration/settings/round3_educational_t1_20261015. 실제native T1은빈그리퍼HOME과사전8블록준비후사용자가직접실행한다. --start-zone home은HOME이동이아니다. 새교육용HMI연결은native실물결과확인후진행한다. 실제파지·결착/B실조립확인/DB저장은미실행이다.

## 2026-10-15 교육용 T1 RGB-D 구독 초기화 오류 수정

- 현장 중단 원인: LiveVision의 Depth/CameraInfo 콜백에 builtin deque.append를 직접 전달하여 Jazzy rclpy의 inspect.signature 검사에서 ValueError 발생. 두 콜백을 한 인자 Python lambda로 감쌌다. 좌표/교시/속도/힘/보정 허용값은 변경하지 않았다.
- 기존 실패 기록 logs/round3-t1-educational/1792020460302561358/events.jsonl 및 1792020480987337920/events.jsonl 보존. 둘 다 THREE_STEP_BEGIN만 있고 해당 생성 실패는 supply.execute/held.transfer 이전에 발생한다.
- 검증: inspect.signature 및 실제 콜백 전달 재현 검사 추가. 관련 depth/three-step 단위 검사 53 passed (reports/round3_robot_pc_20261015/rgbd-callback-regression.log). 최초 검사는 perception import 경로 미지정으로 수집 실패했으며 올바른 PYTHONPATH로 재실행했다.
- 장치 읽기 전용 확인: 실제 LiveVision 생성과 RGB/정렬Depth/CameraInfo 구독 성공, 세 스트림 모두 1280x720, camera_color_optical_frame, 동일 stamp 수신. reports/round3_robot_pc_20261015/rgbd-callback-live-readonly.json. 구독만 수행했으며 로봇/그리퍼 명령 0.
- 미검증: 수정 후 실제 T1 파지/이송/결착, B 실제 확인, DB 저장. 다음은 사용자 빈 HOME/사전배치 확인 후 기존 native T1 명령 직접 재실행. --start-zone home은 HOME 이동 명령이 아니다.

## 2026-10-15 시작 그리퍼 열림 기준 50mm
- 사용자 지시에 따라 supply 실행 시작 및 read-only check의 open_ready 기준을 정확히 50mm 이상으로 변경. 49.9mm 거부/50·55·60mm 허용 경계 검사 포함 관련 86 passed (reports/round3_robot_pc_20261015/start-open-50mm-regression.log). 기존 자동 열기/놓기 명령 폭 60mm, 파지 폭·힘·속도는 유지. 장치 동작 없이 검증.

## 2026-10-15 native T1 표면 Depth 누락 중단
- 사용자 실행 logs/round3-t1-educational/1792020581120128613: HOME→공급 관측 이동 5 MOVE_REQUEST 후 START_OBSERVATION_REACHED/BLOCK_BEGIN에서 종료. 파지 하강/그리퍼 닫기/이송 완료 기록 없음. 실패 packet의 raw depth는 당시 저장되지 않아 해당 packet의 구체적 위반은 단정하지 않는다.
- 현재 자세 읽기 전용 재확인: 기존 관측 자세와 0.003mm 차이. logs/supply-depth-reference/depth-failure-1792020581120128613에 신규 RGB-D 20장 보존. 슬롯4 인식 20/20, Depth zero 포함 8/20, 범위 위반 9/20, patch편차 위반 8/20, 기존표면검사 통과 11/20 (중복 집계). surface-failure-audit.json에 전부 기록. 장치 동작 0, 기준점/허용범위 변경 없음.
- 오류 메시지에 zero_pixels/min/max/spread/허용범위를 추가하여 다음 실패 원인을 구분. 0값 보간/교시 fallback/자동재시도 추가 없음. 시작 50mm 변경 포함 관련 87 passed (reports/round3_robot_pc_20261015/surface-failure-regression.log).
- 실제 파지/결착/B확인/DB저장 미검증. 카메라 Depth 누락 개선/관측 재확인이 필요하며 현재 관측 자세에서 --start-zone home으로 바로 재실행하지 않는다.

## 2026-10-15 사용자 Depth 진단 자료 20261015T083259
- logs/depth-diagnosis/20261015T083259/observation 신규20장 분석. 인식20/20, 표면검사14/20, zero1/20, zero없는 범위초과5/20(525~526mm로현재하한527미달), 편차초과1/20. 최대기록age294.951584ms,skew0. surface-quality-audit.json 저장. 허용범위/카메라설정 변경/장치동작 없음. USB D435i 480M 연결 유지.
- 앞선 안내 ros2 param dump --output-dir는 해당 Jazzy CLI에서 미지원. ros2 param dump /camera stdout을 camera.yaml로 저장하여 수정. RGB1280x720x10,Depth848x480x10,IR1/2false,emitter1/laser150 확인. Depth0와 좁은깊이범위 이탈을 구분하며 USB대역폭만으로 원인 단정하지 않음.

## 2026-10-15 승인된 교육용 T1 깊이 범위 525~538mm
- 사용자 명시 승인에 따라 교육용 프로파일 하한527→525mm만 확장. 상한538mm/패치편차4mm/표면높이차7mm/XY보정3mm/Depth0거부/시각·frame·pose검사 유지. 원본 프로파일·수용기록·안내문은 reports/round3_robot_pc_20261015/depth-lower-bound-525-before에 보존. 교육용수용기록/안내문 갱신, independently_verified=false 유지.
- 추가실측20장 오프라인 비교525하한19/20통과,Depth0한장거부. 관련검사87passed (depth-525-regression.log), 변경프로파일 native preview 통과 physical_commands=0/1cycle (depth-525-preview.log). 로봇/그리퍼 동작 없음.
- 다음: 현재 관측 자세 유지 후 읽기 전용20장 확인. 유효 Depth 확보 후 사용자가 기존 현장경로로 빈 HOME 복귀, native T1 직접 재시도. 실파지/결착/B확인/최종DB는 여전히 미검증.

## 2026-10-15 T1 조립 상공 자동 yaw 중 FEEDBACK_TOO_OLD
- 실행1792021004130705049: 상태조회 query_duration_s=0.5140925109881209로 guard 0.5초 초과. ABORT reason FEEDBACK_TOO_OLD, stop requested/acknowledged/stillness_verified 모두true. 마지막 motion_status0, gripper_status2(파지보고). 삽입/결착 성공 아님.
- XY 대상변 미선택 화면 후 번호 선택 시 기존 약0도 수렴과 달리 YAW_REQUEST 약-89~-85도 발생하고 +0.5도 반복. 선택한 목표변과 manual TOP edge의 대응은 사용자 확인 필요. 번호별축은 target_edge_index%2와 보드X/Y로 연결되며 해당 대응 자체를 코드결함으로 단정하지 않음. 자동 yaw는 기존코드에서누적2도제한 미적용인 점 확인, 임의 설정 변경하지 않음.
- 현재읽기전용 AssemblyMotionRos _sample_once20회: 0.013313~0.052041초,0.5초초과0,모두정지,최종gripper_status2. 로그 logs/depth-diagnosis/20261015T083259/feedback-latency-readonly.json. 호출화이트리스트10개조회/FK계산과그리퍼레지스터읽기만수행, physical_commands0. 기존실행의UI/부하조건과동일하지않아단발지연의최종원인은미확정.
- feedback최신성기준/교시/높이/힘/속도변경없음. 다음은 사용자목표변번호와E클릭변방향확인 및 파지중장치복구절차확정. 현재상태에서T1재실행/HOME명령/그리퍼개방안내없음.

## 2026-10-15 SPACE 저장 자료에서 목표 변 방향 안내 정정
- assembly-observation-1792021689571627095.json 실제 투영의 outline UV 확인: edge1 y731~736(화면아래),edge3 y578~582(화면위). 이전 응답의 화면위=1 단정은 잘못된 안내였으며 사용자에게 명시 정정. 번호는 보드꼭짓점 순서로 정의돼 화면방향 고정이 아님. 기존수렴yaw는평행도만검사하므로반대물리변1/3을구분하지못함.
- 저장manualTOP점은[737.20,657.76],[878.23,653.35]. 저장자료가정높이계산: edge1 XY[-8.424,-15.863]mm, edge3[-8.317,+15.937]mm. 두후보모두실행한값아님. xyz변경/보정합격표시없음. 저장당시headerage0.897480374s, timestamp_verified=false, depthpaired=false. 최신후보아닌오프라인진단으로만사용. xy-edge-identity-review.json 보존.
- 다음사용자조작은3번으로대상변변경(기존점초기화),E로실제동일몸체윗면변두끝점재선택,최신저장검토. E두번째클릭이자동yaw재개가능함을안내. X/I/O/P는현단계진행하지않음. 장치명령0.

## 2026-10-15 최신 SPACE 및 실제 TOP 변 식별 검토
- assembly-observation-1792021870833650667: timestamp_verified=true/headerage0.173s, yaw-0.2395deg, RGBDpairedfalse. 사용자가3선택후화면dX-8.48,dY+15.85로위쪽목표변후보전환확인.
- 실제overlay 시각검토: held몸체맨위가로변은원본영상대략(718,533)→(818,530). 저장manual점은(736.12,656.71)→(880.95,653.92)로아래쪽가로선에위치하며동일물리TOP위쪽변과불일치. 클릭시점오선택/추적이탈원인은미확정. 이XY18mm를실측검증된보정으로채택하지않고X진행보류. 다음E재선택은맨위빨간긴가로선양끝(비스듬한오른쪽변이시작되기전)명확히안내. 장치명령0.

## 2026-10-15 작업자 실물 식별로 TOP 변 해석 정정
- 사용자가 사진맨위블록은이미조립된아래층블록이며기존선택선이그리퍼파지블록의윗면위쪽변임을명시확인. 직전시각검토에서맨위블록을파지블록으로오인했던해석을취소. 기존manual점유지,3번목표윗변대응사용. 추가좌표/높이/회전교시변경없음. X는기존교육용시각XY후보약[-8.48,+15.85]mm(가정높이기반,18mm가량)이며공급판보정3mm/실측잔차1.71mm와별개,정밀도검증으로표시하지않음. 사용자직접X1회후영상/로그확인,삽입I는그뒤안내.

## 2026-10-15 사용자 요청: 조립판 XY만 전체 고정 시나리오에서 제거
- 최종 지시 "아니 조립판 XY만 빼줘" 반영. round2_three_step_trial.prepare의 T1/T2/T3 모두 assembly_xy_correction_enabled=false/vision_xy_alignment=false. 공급 RGB-D 중심보정/교육용525~538mm 프로파일은 그대로 유지. 고정HMI T1도 동일native경로이므로 조립XY비활성. HMI의교육용공급프로파일연결/실물검증을새로완료했다고표시하지않음.
- held popup X는이동없이비활성기록만남김. 시각/좌표XY헬퍼는false설정시거부. I의X선행요구제거,기존autoYaw인경우fresh+stable±0.5도검사유지. target_only모드의I삽입도현재XY/회전그대로Z만변경하여숨은XY맞춤없음. 기존공급/목표교시·높이·힘·속도·yaw방식유지. 다른독립legacyXY시험도구의명시실험은별도기본동작유지.
- 실제로X가보낸명령: 실행1792021495111988214 delta[-8.496914788,+15.987023915]mm,목표[430.8497954,69.5771728,53.6360207,...]. height_assumed=true,depth_reason VALID_DEPTH_AT_BOTH_ENDPOINTS_REQUIRED,projection_independently_verified=false. 이후추적상실. 사용자가이상동작/의도위치차이를보고했고ESC정지+블록제거확인. 미검증18mm가정기반보정을실행하도록안내한판단오류를사용자에게인정. 삽입/파지성공/결착/B/DB완료로해석하지않음.
- 투영 불일치진단: 기존조립T_tcp_camera와공급실측변환의이동성분차[-10.836,-12.879,+48.642]mm. 물리이동오차그자체로단정하지않음. 변환후보는원본scenario에연결하지않았고,최종XY제거지시에따라임시caseoverride코드제거. 후보3파일은reports/round3_robot_pc_20261015/assembly-xy-disabled에미채택자료로보존. 기존yaw투영보정교체하지않음.
- 최종검증: 관련unit158passed(assembly-xy-disabled-regression.log),고정HMI모의10passed(assembly-xy-disabled-hmi-regression.log). native3cycle replay T1/T2/T3완료/SYNTHETIC/physical_commands0,XYdisabled3건/보정실행0건. 교육용nativepreview 공급depthprofile있음+조립XYfalse/physical_commands0. 관련로그상위reports/round3_robot_pc_20261015 및 logs/round3-no-assembly-xy-replay,logs/round3-t1-preview-no-assembly-xy.
- 검사중기존legacyXY헬퍼시험은명시enabled=true환경으로분리해의미유지. 루트HMI와nativeunit을단일pytest로수집시app패키지충돌이있어각환경에서분리실행. native합성replay의기존xy_target호출도비활성경로에맞춰제거후전체관련검사를재실행.
- 안내 RUN_GUIDE.ko.txt갱신: 조립판1~4/X사용없음,E(yaw)→I→O→P→U. 실물재시험은아직시행하지않음. 다음사용자준비는슬롯4복원/빈그리퍼HOME(시작폭50이상)/손제거,새native실행. 블록제거를HOME완료나파지상태정상으로가정하지않음.

## 2026-10-15 조립XY제거후 native 고정T1 한사이클 실행 기록
- 사용자상승·종료보고. logs/round3-t1-educational/1792022485750917572/result.json REAL/LIVE_D_RUNTIME/FIXED_STEP_EXECUTED/completed_steps[T1]. assembly_completion=false/current_update=false 유지. native-t1-review.json에결과분류저장.
- 조립XYdisabled1건/시각·좌표XY실행0건, 공급RGB-D 보정 및 파지피드백 기록 있음. I결과 FORCE_STOPPED_BEFORE_VERIFIED_SEATING; 사용자O입력에의한release확인기록후 P FORCE_THRESHOLD_REACHED_STOP_VERIFIED, U상승·정지기록, cycle released=true/press_done=true/CYCLE_COMPLETED. 힘기준정지를실제결착성공으로채택하지않음.
- 실제결착은현재작업자에게의도한6점블록아래쪽4자리/들뜸·기울어짐여부확인질문진행중. B실제조립확인/최종DB저장없음. 다음조건: 실결착확인후HMI동일T1시험준비. T2자동진행없음.

## 2026-10-15 native T1 실제 결착 작업자 확인
- 사용자 "의도한 위치에 정상 결착됨" 확인. native-t1-review.json을 NATIVE_T1_EXECUTED_OPERATOR_CONFIRMED_SEATED/physical_seating_operator_confirmed=true로갱신. runtime원본result불변. 교육용조건의실파지/이송/삽입시도/놓기/누르기/상승한사이클과작업자실결착확인까지기록. B실제확인/Current갱신/DB저장false유지. 다음HMI동일T1연결에필요한명시native옵션전달구현·모의검사중.

## 2026-10-15 native 성공 조건의 HMI 고정T1 전달 준비
- HMI명령에 --fixed-trial-scenario/--supply-depth-profile/--educational-depth-demo 추가. 고정T1에서만허용,교육용옵션은명시프로파일필수. FullFeatureRealTrial→FixedStepProcess→native --scenario/--supply-depth-profile/--educational-depth-demo 전달. 기존default와 --only-step T1/단일writer/STOP/HOLD/B미채택/DB미시작계약유지. 기존공급교시파일수정없음.
- focused HMI모의검사13passed(hmi-fixed-profile-focused.log),로그인/준비확인·START→정확한프로파일전달·중복START/RESUME거부·STOP·HOLD검사포함. CLI잘못조합은Qt/장치연결전거부. 실물HMI START하지않음. HMI_T1_RUN_GUIDE.ko.txt작성.
- 추가일반공정회귀49중43passed/6failed(hmi-educational-profile-forwarding.log). 5실패는현재지지4stud규칙과불일치하는기존fixture INVALID_INPUT,1실패는__new__fixture의design_change_replay누락. 변경전HEAD app3모듈을메모리에만로드해대표3검사에서도동일실패재현(hmi-baseline-failures-check.log). 작업폴더되돌리기/검사약화없음,이번고정T1밖기존실패수정하지않음. 전체공정회귀PASS나ABCD전체통합완료로표시하지않음.
- 다음사용자준비: native T1결착2x2만제거하여기존8블록복원,공급슬롯4준비,빈그리퍼HOME/50mm이상,카메라·드라이버유지. 위새옵션명시한HMI를사용자실행후준비체크→START가실제T1시작. E(yaw)→I→O→P→U,조립XY는OFF/공급RGBD는ON. 실물HMI결과후실결착과로그를다시확인.

## 2026-10-15 HMI 고정T1 실물 한사이클 및 작업자 정상결착 확인
- HMI job5df8bf06-9555-44de-9ce7-5e68c0fcd2fa/fixed-trial/1792023131659776973/result.json FIXED_STEP_EXECUTED/REAL/LIVE_D_RUNTIME/completed_steps[T1]. CYCLE_COMPLETED/released=true/press_done=true/최종상승기록. 사용자 "아까랑 똑같이 잘 끝났음!!" 확인. hmi-t1-review.json에작업자정상결착확인과기계로그를분리저장.
- 공급RGBD XY적용[-0.505086496,-1.048506114]mm,교육용수용 OPERATOR_ACCEPTED_EDUCATIONAL_T1. 조립XYdisabled1/보정실행0. I FORCE_STOPPED_BEFORE_VERIFIED_SEATING,P FORCE_THRESHOLD_REACHED_STOP_VERIFIED이며실제결착은작업자확인근거. 힘정지만으로실제결착완료라표시하지않음.
- native와HMI각1회고정T1의실파지·이송·조립·놓기·누르기·상승 및작업자정상결착확인까지이번검증범위완료. fixed-t1-native-and-hmi-summary.json을상위reports/round3_robot_pc_20261015에저장. HMI HOLD는B최종판정/Current갱신/DB저장으로자동진행하지않는고정시험의설계상상태이며미확인필드는유지.
- B실제조립확인=false,최종DB저장=false,정밀보정독립검증=false,ABCD전체통합완료=false. T2자동시작/재개/자동재시험없음. 다음은결착물과로그보존,이번HMI창종료가능. T2/실제B확인/DB연결은별도후속범위.

## 2026-10-15 고정T1 시험 정리 완료
- 사용자 HMI창닫음 및 결착물복구완료보고. 최종summary의operator_cleanup에기록. 로봇HOME재확인/공급상태/카메라·드라이버종료여부는추가가정하지않음. native/HMI고정T1실행과작업자정상결착확인까지이번검증범위종료. 장치동작없이기록만갱신. 다음물리시험은별도준비상태확인후진행.

## 2026-10-15 후속T2 공급RGB-D 보정 기준 측정 준비
- 사용자T1정리후그리퍼열림/HOME복귀보고및다음요청. T2는파랑2x3슬롯3→(13,11,L2,0°). 최초기존교시단독시험선택후사용자가공급판보정진행및전체교시계산저장가능여부질문으로방향수정. T2프로파일은없으며T1노랑슬롯4프로파일재사용/타슬롯검증완료표시하지않음.
- 측정recorder에 --step T2지원(기본T1호환). 기존T2교시bundle에서정확한blue_2x3x1_03아이덴티티/TCPTool/pose를불러와teach-pickup/capture/analyze에반영. T2 snapshot은t2-config.json,slotid동적기록,T1파일명유지. Reference설정선택은T1/T2만허용. 로봇/그리퍼쓰기API추가없음.
- 관련검사64passed(t2-reference-recorder-regression.log). T2새preclose기록이T1slot4에묶일수없음검사포함. 실제새자료미측정/프로파일미채택/실물T2미실행.
- 현재native --only-step은T1한정인것확인. 측정전T2자동실행안내없음. 공급RGB-D보정없는기존경로는1280x720영상과640x480layout처리정합성도추가확인필요. T2측정후실행경로와검사를준비할예정.
- 전체다른슬롯은새프레임에서표면중심/XY후보를계산할수있어도1개블록으로파지Z/회전/조립/누름전체교시를확정불가. 직접측정/계산후보/실물검증을구분해저장. 다음사용자작업은기존수동경로로파랑2x3슬롯3닫기직전정렬후 --step T2 teach-pickup기록,블록배치유지하여관측촬영연결.

## 2026-10-15 사용자 후속 방향: T1/T2/T3 공통 RGB-D 프로파일
- 사용자T2보정이T1과유사하면T3까지측정해전체RGB-D기준으로사용희망. 공통카메라/TCP변환을공유하면서슬롯별실측기준중심·교시·ROI를별도references로보존하는통합프로파일방향으로정리. 단일평균XY를전슬롯에적용하거나미측정슬롯을검증완료로승격하지않음.
- 신규기준생성직후delta≈0은정확도검증아님. 슬롯별독립변위검증의실측대계산오차/방향일관성을비교해야공통적용범위를평가할수있음. 세슬롯만검증한경우해당세슬롯범위이며다른슬롯의실측참조는추가등록필요. Depth허용범위는슬롯위치/높이에따라별도실측후기록.
- 현재T1만native/HMI정상결착확인,T2/T3새보정자료미확보. 다음은T2닫기직전교시기록과배치유지관측촬영. 실제동작자동실행없음.

## 2026-10-15 T2 신규 파지 원자료 T2-pair-20261015T093321
- 사용자teach-pickup완료,blue_2x3x1_03/GripperDA_v4/ToolWeight0및3회동일자세확인. 새TCP[-456.0434265,10.6312437,47.9238319,8.0096474,179.7055054,8.3067703]. 기존T2 Z50.5542755대비-2.6304436mm이며회전도다름. 실행교시변경하지않고원자료만보존,record-review.json에차이기록.
- 후속RGBD관측촬영은현재블록배치유지와기존관측자세0.5mm/0.5deg범위에서만수행. 이파지자료를새runtime으로채택하기전기존T2landing/pad의그립관계와높이차를해결해야함. 카메라/그리퍼자동동작없음.

## 2026-10-15 T2 기준 RGB-D20장 분석 완료(미채택후보)
- T2-pair-20261015T093321/observation: 사용자가운데파랑2x3슬롯3및교시→촬영배치유지확인. ROI[311,245,367,321],동일v4derivedmatrix로analyze완료.20/20인식/Depth양수,패치524~525mm,최대편차1mm,표면Base중앙[-458.2070967,17.76205985,102.03319034]mm,표면변동XYZ[0.0960724,0.0816975,1.0019116]mm. 최대age299.578541ms/skew0,촬영전후pose동일. surface-candidate.json/surface-quality-audit.json보존,reference_accepted=false.
- T1교육용Depth525~538mm를T2로자동전용하지않음. T2기준생성자료만으로T1대비정확도/공통보정유효성확인불가. 기존파지좌표와표면중심의직접차이도파지기하영향을받으므로보정정확도잔차로단정하지않음. 다음은T2블록작은평행변위후동일측정Z/자세의교시+관측독립검증. 기존T2runtime높이/회전/landing/pad는미변경이며새측정pose와의차이해결전실행채택없음.

## 2026-10-15 T2 validation-01 파지 기록 진단
- 새pose[-455.8390808,7.5730915,48.6454086,5.4452844,178.1812134,5.1830091],기준대비deltaXYZ[0.2043457,-3.0581522,+0.7215767]mm,XY3.0649718mm,SO3회전차1.6240938deg. 동일높이/자세가아니므로순수XY검증합격으로채택하지않음. validation-pose-review.json에진단용표시.
- 추가RGBD촬영으로독립적인품질·변위진단은진행하되공통프로파일완료/실행허용치확장없음. 사용자기존수동경로관측복귀후--stepT2capture20장예정. 원자료보존/장치명령0.

## 2026-10-15 T2 RGB-D 변위 진단 결과와 T3 기록 준비
- T2 validation-01: 20/20 인식·유효 Depth, 523~524mm/패치 최대 편차1mm, 최대age298.426551ms/skew0, 촬영pose차0.0042mm/0.00083deg. 사용자 교시→촬영 블록 불변 확인.
- RGB-D deltaXYZ[-0.2556172,-2.7823361,+1.9262575]mm, 교시deltaXYZ[+0.2043457,-3.0581522,+0.7215767]mm, XY차[-0.4599629,+0.2758161]mm/크기0.5363212mm. 높이차0.7216mm/자세차1.6241deg 영향이 남아 교육용 진단으로 분류. 순수XY 정밀검증 합격이나runtime채택 아님. T1잔차1.70509mm와 구분 기록.
- 사용자 희망의 T3용 --step T3(노랑2x3슬롯5)를 읽기 전용 recorder에 추가. 관련65passed(t3-reference-recorder-regression.log), T1/T2호환·기존자료보존. T3미측정/공통profile미적용/실물T2·T3미실행. 진척은 reports/round3_robot_pc_20261015/supply-rgbd-three-reference-progress.json에 저장. 다음은T3닫기직전수동교시기록.

## 2026-10-15 T3 첫 파지 원자료 기록
- T3-pair-20261015T094504/pickup: yellow_2x3x1_05/GripperDA_v4/ToolWeight0 확인. 새pose[-581.6342773,139.9174805,47.2786140,5.8804960,178.2922211,5.5131855], 기존 보간pickup Z49.8143832 대비-2.5357691mm. record-review.json에 XYZ/실회전차2.8602deg 기록. 실행교시 불변, 실파지/결착 미검증. 다음은 블록배치 유지 및 기존 공급 관측자세로 사용자 수동이동 후 T3 capture20장. 장치명령0.

## 2026-10-15 T3 기준20장 분석 및 세슬롯 공통후보 자료 보존
- T3-pair-20261015T094504/observation: 노랑2x3맨왼쪽슬롯5와교시→촬영배치유지사용자확인. 실제영상ROI[198,134,245,192]로분석(기존ROI[161,99,217,175]는현재영상과불일치,원본설정미변경). 20/20인식·유효Depth,528~531mm,patch최대편차1mm,표면Base중앙[-592.2821686,143.0490622,98.4359085]mm,XYZ범위[0.4520970,0.4321975,2.0041126]mm. 최대age299.785787ms/skew0,촬영pose차0.00617mm/0.00105deg. surface-quality-audit.json 저장.
- settings/round3_supply_rgbd_20261015/reference-bundle.candidate.json에 T1/T2/T3세슬롯별교시·표면중심·ROI·Depth관측범위·자료hash와공통T_tcp_camera를저장. 실행프로파일과다른candidate schema로의도치않은적용방지. 모든execution_approved/independently_verified=false,미측정슬롯검증없음. T2잔차의높이·자세차영향유지,T3독립변위검증미완료. 기존성공T1프로파일불변.
- 다음T3약2mm평행변위후기준Z47.278614/A5.880496/B178.292221/C5.513186을유지한새교시→배치유지관측검증. 실제동작자동실행없음.

## 2026-10-15 T3 validation-01 기록 실패 후 보존·재조회
- 사용자FileExistsError보고. validation-01/pickup에는pickup.json없이teaching-error.json의READ_SERVICE_TIMEOUT:motion/check_motion만존재. 오류폴더보존/삭제·덮어쓰기없음. 후속단일Reader조회에서도READ_SERVICE_UNAVAILABLE발생,기존driver/camera실행및ROS서비스목록확인후CLI CheckMotion실응답status0/successtrue확인. 재시작/드라이버재빌드/설치없음.
- 사용자기존teach-pickup요청범위의읽기전용재기록을새validation-02/pickup에수행성공. 장치쓰기0/runtime설정미변경. validation-pose-review.json에기준대비차이보존. 다음사용자관측복귀후이새폴더로capture진행.

## 2026-10-15 T3 validation-02 RGB-D 변위 진단 완료
- 20/20인식·유효Depth,526~529mm/patch최대편차1mm,최대age288.548336ms/skew0,촬영pose차0.00572mm/0.00041deg. RGBD deltaXYZ[+0.1857017,-2.1501657,+0.4384815]mm,수동교시deltaXYZ[+0.1932373,-3.2186279,+0.9154091]mm,XY잔차[-0.0075356,+1.0684622]mm/크기1.0684888mm. 높이0.9154mm/회전0.38385deg차영향유지. 사용자이번교시→촬영배치불변확인질문진행중.
- T1 1.70509/T2 0.536321/T3 1.068489mm로측정세트비교가능. 공통reference-bundle.candidate.json과progress갱신. 평균상수오프셋으로전슬롯치환없음,실행profile/교시미변경,미측정슬롯인증없음.
- 실행채택전남은사항: T2기준새Z47.9238 vs기존50.5543/T3새47.2786 vs기존49.8144 및회전차는기존landing/pad의그립관계에영향. 카메라XY측정성공만으로새파지6pose를기존조립교시에조용히연결하지않음. 현재reference후보는실행용아님.

## 2026-10-15 전체 재교시 대신 25슬롯 모델 후보·관측 우선 방식 구현
- 사용자 명시 동의에 따라 scripts/model_supply_rgbd_slots.py 추가. 현재 5종×5슬롯/오른쪽1~왼쪽5 템플릿만 사용, 과거24슬롯 모델 미전용. T1/T2/T3 현재 영상 중심으로 초기 ROI 정렬 후 첫 프레임의 시각 중심들에서 공통 열 간격/줄별 원점을 중앙값으로 추정. 실측 외곽 치수와 CameraInfo/Depth의 정면 근사 크기도 비교. 수동 그리퍼 교시나 Base 실행좌표를 모델로 확정하지 않음.
- 별도 candidate schema/실행허용false/미측정pickup_pose_candidate=null. --model-layout으로 고정된 모델 재사용, 새 촬영으로 자동 재맞춤 금지. TCP/Tool/관측자세/내외부 카메라 변환 바인딩 검사. 깊이0/가림/검출 실패를 빈 슬롯이나 교시 대체로 처리하지 않음. 기존 실행 T1 프로파일/실행 교시/높이/회전/힘/속도 불변, 조립XY OFF 유지.
- 원자료 T3 observation의 첫1장 모델 생성/나머지19장 대조: logs/supply-slot-model/20261015-model-05 (25후보,20슬롯 관측 일치/5슬롯 검토). 첫 프레임의 인식24중심에서 행 모델을 맞춘 반복성 결과로 독립 정밀검증 아님. 중간 model-01~04 자료 보존, 첫 시도 geometry JSON키 오류 수정 후 재실행.
- 기존 Realsense/DRCF2 프로세스 유지, 재시작/중복실행/장치쓰기 없음. 읽기전용 capture20장: logs/supply-slot-model/20261015-fresh-01/capture. 관측자세 차이 사실상0,수집 성공. 새 촬영에 고정 모델 적용 결과는 fresh-02-audit에 보존. RGB1280x720/정렬Depth16UC1/color optical frame/수집age300ms/skew50ms 검사 유지. 3px/4mm/외곽크기비율0.7~1.3은 관측 검토 임시 기준이며 실행 허용치 아님.
- 관련 unit63passed(reports/round3_robot_pc_20261015/supply-slot-model-regression.log). 3anchor퇴화/ROI범위/패킷시각·frame·해상도/한블록변위의모델왜곡/고정모델TCP·변환·슬롯binding 검사. 실파지/결착/B/DB 검사 아님.
- 이전 사용자 T3 검증 배치불변 확인을 진단/progress/reference 후보에 반영. 변경 전 JSON은 reports/round3_robot_pc_20261015/t3-placement-confirmation-before 보존, profile_approved/independently_verified=false 유지.
- 안내: reports/round3_robot_pc_20261015/SUPPLY_SLOT_MODEL_GUIDE.ko.txt. 다음: 새 관측의 예외 슬롯별 ROI/깊이0/배열 인식을 먼저 진단하고, 남는 물리 대응 오차만 수동 추가측정. T2/T3 신규파지 Z/회전과 기존결착·누름교시 관계는 실행 채택 전 별도 확인 필요. 전체슬롯 실파지/ABCD실물통합 완료 아님.
- 새 촬영 최종 관측 결과: fresh-02-audit는25후보 중19슬롯 관측 일치/6슬롯 검토. 노랑2x2슬롯1·빨강1x2슬롯1은각1/19배열실패,노랑2x2슬롯2·3/노랑2x3슬롯3·4는깊이0. 현재수동재교시필요확정0개. 고정layout이원본과JSON동일함/25개execution_allowed=false·pickup_pose_candidate=null 검증. summary는 reports/round3_robot_pc_20261015/supply-slot-model-summary.json.
- 중심3x3 Depth진단: 노랑2x2슬롯2의19장171픽셀 중152개0,슬롯3은2개0;노랑2x3슬롯3은45개0,슬롯4는30개0. 원자료와 center-depth-zero-diagnosis.json 보존. 허용치확장/깊이메우기/교시대체없음. 다음우선순위는노랑2x2슬롯2 깊이유효성문제의추가관측검토.

## 2026-10-15 관측 자세 사용자 확인 후 읽기전용 재촬영
- recheck-20261015T101247/capture20장,기존관측pose차0.000mm/0.000deg/TCPTool일치/정지확인. 고정model-05그대로19장대조:18슬롯일치/7슬롯검토. 로봇·그리퍼쓰기0/카메라설정변경0/중복driver실행없음.
- 노랑2x2슬롯2는RGB배열19/19인식,유효중심Depth0/19. 첫프레임외곽내부(경계5x5침식)유효Depth22.9%,다른여러슬롯은95%이상. 한프레임진단이며표면Z대체나평면보정에사용하지않음. interior-depth-diagnosis.json/summary.json보존. ROI나교시오류로확정하지않고광학관측품질문제로우선분류,직사광/반사원인은작업자현장확인필요.
- 추가교시요구없음. 다음은블록·카메라·로봇배치유지하에해당블록조명·반사·가림을확인하고조명조건변경여부를기록한후재촬영. 임의필터깊이메우기/레이저·노출변경/실파지/B/DB없음.

## 2026-10-15 반사 없음 보고 후 원본Depth 비교 및 PC부하 진단
- 사용자 슬롯표시내반사없음보고. raw-vs-aligned-20261015-01에정지/관측pose/TCP확인후RGB/정렬Depth/원본Depth/양CameraInfo/정렬extrinsics20쌍읽기전용저장. 원본848x480/정렬1280x720,최대수집age296.285ms/시각차0. 장치쓰기/설정변경/재시작0. 초기diagnostic inline환경PYTHONPATH에서ROS경로가빠진문제를상속경로보존으로수정,드라이버설치/빌드없음.
- 설치된Extrinsics.msg의column-major/미터규약대로실측raw유효점3D를RGB로재투영해대조. 노랑2x2슬롯2는20중정렬중심3x3완전유효1장,원본유효점의RGB중심3px이내공급없음14장. 가장가까운원본유효점재투영거리0.91~25.50px. 파랑2x3슬롯3은정렬중심20/20유효,raw3px내유효점20/20. T1노랑2x2슬롯4도이번중심patch9/20만완전유효라과거성공을항상깊이유효함으로표시하지않음. 원본Depth부터국소결측이있어단순정렬실패/PC지연만으로확정불가. 탐색영역용가정깊이510/530/550mm는좌표/Depth대체에사용하지않음. raw-aligned-comparison.json 보존.
- 사용자100HzOverrun질문:현재PCi5-8265U4코어8논리/메모리7.6GiB,5초vmstatCPUidle53~56%,관측시available약3.2GiB/Swap4GiB점유. 순간전체CPU포화확인없음,swap점유만으로현재메모리압박단정하지않음. controller시작로그FIFO_RT설정Operation_not_permitted확인(일반TS정책). 로그6건Overrun:시작직후최대151.883ms,그외10.875~39.910ms. 부하/스케줄링기여가능성과Depth국소결측을분리. reports/round3_robot_pc_20261015/pc-load-and-depth-diagnosis.json 보존. 커널/권한/governor/camera옵션/100Hz임의변경없음.
- 실제controller프로세스/proc/812198/limits의Max_realtime_priority=0/0확인. FIFO설정권한실패의실제제약근거이며실행중권한/한도변경없음. Max_locked_memory약1.026GB이며unlimited라고가정하지않음.

## 2026-10-15 노랑2x2슬롯2 기존교시·실파지기록 확인
- 현재공급자료 확인: fixtures/teaching_sources/operator_supply.json에는노랑2x2슬롯1/3/6직접교시만있고슬롯2없음. app/robot_teaching.supply_teaching은슬롯1/3XYZ선형·회전Slerp보간. 현재계산후보[-391.6268921,196.1028748,51.5454865,-74.7571976,176.1995179,-73.3136861],실행채택/실파지검증아님. 현재default logs/teaching-20261012/supply.json없어fixturefallback사용.
- 과거성공: docs/STATUS의2026-10-06노랑4점2번픽앤플레이스/observe복귀작업자확인있음. 해당5969d3bf원시jsonl은이번PC검색에서찾지못함. 별도협동2/isaac_preview/handoff/robot_cycles/yellow4_row_success_2026-10-04.json에는2~6번작업자완료확인있음(독립명령로그없음). 당시원본스크립트의슬롯2XYZ[-388.215,215.959,-5.0896]는현재값과달라현재배치그대로의성공증거로재사용불가.
- reports/round3_robot_pc_20261015/yellow-2x2-slot2-teaching-record-review.json에출처hash/구분보존. 로봇그리퍼0/실행설정미변경. 다음권장:누락슬롯2만명시바인딩하여현재닫기직전자세를읽기전용기록. 기존T1/T2/T3recorder는slot2미지원이므로T1명령재사용금지. 지금실파지·결착·B·DB완료없음.

## 2026-10-15 사용자 슬롯2 도착 후 읽기전용 자세 기록
- recorder teach-pickup에 --slot-id 추가. 현재25슬롯목록과대조하여명시적대상만허용,1~5범위밖거부. T1/T2/T3호환및 --step상호배타, capture/analyze에는미지원. T1조립목표를물려받지않는최소측정config사용. 기존runtime교시/장치쓰기API변경없음. 관련65passed(explicit-slot-teaching-regression.log),T1슬롯4오바인딩거부/슬롯6거부포함.
- 사용자현재슬롯2도착보고범위에서3회정지/TCPGripperDA_v4/ToolWeight0및공급판범위확인후manual-yellow-2x2-slot2-20261015T102557/pickup에원시pose와후보기록. XYZ[-389.8049622,194.6276550,48.5505142],ZYZ[167.7047729,-177.7196198,167.3773956]. 기존보간대비deltaXYZ[+1.8219299,-1.4752197,-2.9949722]mm/실회전차3.8113247deg. record-review.json보존.
- 도착보고만으로정확한닫기직전중앙정렬완료를단정하지않고pickup.json을MANUAL_SLOT_POSE_RECORDED_PRE_CLOSE_CONFIRMATION_PENDING/확인null로분류. 최초도구출력원본은pickup.before-confirmation-note.json에보존. 실행설정미채택/물리파지성공false/RGBD기준미검증/B·DBfalse. 다음은작업자닫기직전자세확인후슬롯2교시기반시험설정검토. 현재그리퍼닫기/이동명령없음.

## 2026-10-15 슬롯2 닫기직전 수동교시 작업자 확인
- 사용자 "닫기직전" 명시확인. manual-yellow-2x2-slot2-20261015T102557/pickup/pickup.json의교시후보를작업자확인닫기직전기록으로분류,확인전사본보존. 실파지false/RGBD기준미채택/runtime설정미변경유지.
- 기존T1성공파지목표35mm/설정힘40N을원본설정·이벤트와대조. 다음사용자작업은현재정지자세/손제거후기존제어화면에서그리퍼만동일조건닫기,아직상승·이송없음. 에이전트는개폐·이동명령0. 닫힘보고후실제grip피드백을읽기전용확인예정.

## 2026-10-15 슬롯2 수동닫힘 후 파지피드백 조회
- 사용자닫힘보고후Reader의정지/TCPTool/현재pose조회및RG2 Modbus258~275읽기만수행. 5회status2(grip감지true/busyfalse/기타비트0),실제폭40.6mm/offset0. 교시대비pose차0.000mm/0.000deg. grip-feedback-readonly.json보존,에이전트장치쓰기0.
- 파지신호확인과실제블록들기성공은구분. 아직상승/실물보유/결착/B/DB미확인. 다음작업자는기존수동조작으로Base+Z만블록이공급판에서떨어지는만큼올려보유확인,XY·회전자세·기존속도·힘유지. 자동상승/관측복귀/조립없음.

## 2026-10-15 슬롯2 수동상승 실제들기 확인
- 사용자 "들림" 확인. 상승후읽기조회5회RG2status2/폭40.6mm유지,로봇정지/TCPTool동일. 원래닫기직전대비deltaXYZ[-2.2221985,+0.0901031,+74.6661224]mm/실회전차0.2536675deg. 순수Z변위라고표시하지않음. lift-feedback-readonly.json보존,에이전트장치쓰기0.
- physical_grasp_verified=true의범위는이번수동파지·실제들기1회작업자확인+유지된그립신호. 재현성/자동접근/이송/결착/공급RGBD기준/B/DB는미검증. 닫기직전원본pose불변,상승pose로교시덮어쓰기없음. metadata확인전사본보존.
- 다음작업자는동일슬롯2원위치에기존수동절차로내려놓고안착후그리퍼개방하여배치복원. 공중개방/자동복귀/자동다음시험없음. 복원확인전관측촬영·HOME자동명령없음.

## 2026-10-15 슬롯2 열림 확인 및 관측 복귀 대기
- 사용자열림보고후읽기조회3회status0/폭52.0mm/busyfalse/파지감지false. 현재TCP[-388.8684998,193.4604950,48.4002113,167.7324677,-177.7233276,167.3249969],기록대비deltaXYZ[+0.9364624,-1.1671600,-0.1503029]mm/실회전0.0801649deg. 원교시와XY약1.50mm다르며배치정확복원·불변이라고단정하지않음.
- open-feedback-readonly.json보존,닫기직전교시불변/에이전트쓰기0. 다음은빈그리퍼수직이탈후기존수동경로관측복귀,촬영으로슬롯2배치대조. 낮은현재위치에서관측점으로대각직선이동명령안내없음. 새자동파지/결착/B/DB미검증.

## 2026-10-15 슬롯2 수동시험 후 관측복귀·배치 영상 확인
- 사용자관측복귀보고후읽기전용capture20장:slot2-restored-20261015T103522. 기존관측pose차0.000mm/0.000deg,그리퍼status0/폭52.0mm. 고정model-05재사용/분석프로세스OpenCV·BLAS스레드1로제한(장치설정아님),19장대조21슬롯일치/4검토. 에이전트장치쓰기0.
- 슬롯2이번인식19/19/유효중심깊이19/19. 복원전recheck중앙UV[388.465655,108.839604]→[390.019540,110.144115],delta[1.553886,1.304512]processing_px. 시각적으로해당위치의블록존재확인이나정확원배치불변아님. 기존수동닫기직전교시와이번RGBD를동일배치대응쌍으로채택하지않음. 미세재배치후깊이유효성이달라졌다는관측이며PC성능원인제거증명아님.
- 잔여검토:노랑2x2슬롯1/3/4(각19중1깊이불량),빨강1x2슬롯1(14/19인식). 모두기존직접교시기록있고노랑슬롯4는이번T1수동/실기근거도별도로존재. 현재신규재교시요구0,기존기록보존하며관측불안정과실행검증을구분. restoration-review.json보존. 기존T1성공runtime/교시·높이·힘·속도·조립XY_OFF불변,B/DB미진행.

## 2026-10-15 슬롯2 교시좌표 단일 재접근 시험 준비(실행 미시행)
- 사용자 진행 요청. scripts/slot2_pickup_trial.py 추가,기존 supply.execute의trial_row+hold_at_pickup재사용. 정확한yellow_2x2x1_02/작업자닫기직전확인·수동들기기록/TCPTool바인딩필수. 공급RGBD/영상XY/조립XY없음,자동실패fallback아님. 1개닫기후holding정지,상승·놓기·조립없음. preview기본/--execute+손제거·슬롯준비flags모두필수,공통writer lock/sourcehash검사/기존중단경로유지.
- 기존T1속도12/120·가속48·회전6/3·닫기35·힘40N·중단45N 및수동교시6pose그대로. 새단일시험은target_only_motion=false로수치정지/IK-FK/도달검사를활성,기존T1전역config/runner/높이/힘/교시는변경없음. 관측pose0.5mm/0.5deg및빈그리퍼>=50필수,home명령/시작자동개방없음.
- unit55passed(slot2-reapproach-regression.log),preview무연결통과. 실제read-only-check-20261015T104249는정지3회/폭52/힘피드백/TCPTool및4endpoint IK-FK모두통과,physical_commands0. 초기endpoint진단도0.00464~0.00490mm/0.00059deg이하. 경로충돌/실제자동접근·파지재현을완료했다고표시하지않음.
- SLOT2_REAPPROACH_GUIDE.ko.txt에일반터미널사용자직접실행명령/예상움직임/로그/중단/종료후holding상태와다음보고정리. 복원블록XY약1.5mm변화가능성을명시,자동좌표보정없음. 실제run미실행/B·DBfalse/전체통합완료아님.

## 2026-10-15 슬롯2 자동 재접근·파지 1회 작업자 정확파지 확인
- 사용자 "파지 정확히 잘됨". run1792028718726814565/result는 APPROACH_GRIP_SIGNAL_HOLDING_NO_LIFT_TEST,events3이동/닫기1회/status2/폭40.6/정지확인. 원문rawresult·events불변,operator-review.json에작업자실물정확파지확인·로그hash별도기록. 독립읽기조회도원래교시pose동일/TCPTool정상/3회status2폭40.6유지. 에이전트장치쓰기0.
- 실행은공급RGBD·XY보정미적용의명시교시모드,속도12/120·가속48·회전6/3·닫기35·힘40유지. 종료후저위치holding상태이며자동상승·놓기·조립없음. 과거수동들기1회와이번자동접근파지1회를구분,자동들기/반복재현성/결착/B/DB미검증.
- slot-policies.candidate.json의slot2공급전용단일시험근거만갱신(이전사본상위reports보존),전체시나리오실행·조립grasp관계승인아님. 다음은현재공급판위치에서작업자그리퍼개방후수직이탈·기존수동경로관측복귀. 자동복귀/재시험없음.

## 2026-10-15 슬롯2 단일 시험 정리 완료
- 사용자복귀보고후읽기조회:기존관측pose거리0.000mm/실회전0.0000067deg,정지/TCPTool정상,그리퍼status0/폭52mm. cleanup-readonly.json에CLEANUP_CONFIRMED,operator-review의cleanup_pending=false. 에이전트개폐/이동0.
- 슬롯2단일교시닫기직전기록·수동들기1회·자동재접근정확파지1회작업자확인·빈관측복귀까지정리. 공급RGBD검증/자동상승/결착/전슬롯반복재현/B/DB는미검증. 기존T1native/HMI성공기록과구분. 다음은남은관측예외의기존직접교시/실파지근거대조,새전체재교시나T1재시험을자동추가하지않음.

## 2026-10-15 남은 예외 슬롯1/3·빨강1 기존 실파지 근거 대조
- 세슬롯모두operator_supply직접교시/작업자정렬확인자료있음. 교시당시status0/폭44.9/physical_commands0이며이자료자체는실파지성공증거아님.
- 노랑2x2슬롯1:reports/round2_d_evaluation_20261014/evidence/events.jsonl의BLOCK_BEGIN6pose가현재직접교시와완전동일. GRIP_FEEDBACKstatus2/폭40.4,HELD_VERTICAL_LIFT·이송·상공holding로그있음. 이후누름FORCE_NORM_STOP_LIMIT_REACHED중단과공급파지를구분. round2_entry_collision실행도동일공급파지이후조립진입오류이며전체성공아님.
- 노랑2x2슬롯3:c2_integration_round1/logs/full-feature-real-slots1to5/c5413...의f39f.../91d29...두실행은현재직접교시6pose일치,REAL/LIVE_D_RUNTIME. PICKUP_CLOSE status2/폭40.4 및이송종료grip2/endpoint_verified로그확인. B는SYNTHETIC,physical_assembly_verified=false이므로실제B/결착/전체통합완료근거로미사용. archive원본사본hash동일하여중복횟수제외.
- 빨강1x2슬롯1:직접교시는있으나이번조회범위에서동일좌표실파지로그미발견. 실제성공으로승격하지않음. 새교시보다기존좌표로단일접근·파지시험준비우선권장. 노랑1/3재교시·중복파지시험은우선생략,현재배치/새RGBD정밀검증보증아님.
- reports/round3_robot_pc_20261015/remaining-slots-teaching-grasp-review.json에출처/해시/범위기록. 장치동작0/실행설정변경0,새빨강시험미준비·미실행. 다음은빨강슬롯1기존교시/해당종류파지설정의단일시험준비이며현재관측자세유지.

## 2026-10-15 빨강 1x2 슬롯1 단일 교시 파지 시험 준비
- 사용자 진행 지시에 따라 기존 slot2_pickup_trial에 명시 red_1x2x1_01 선택만 추가. 원본 operator_supply의 직접교시 정체성/TCPTool/작업자확인/read-only영수증을 검증, 슬롯1 6pose 그대로 사용. 기존 빨강 닫기20mm와 T1 힘40N/속도·가속/중단45N 유지. 슬롯5 후보의90도회전·XY이동 미사용, 원자료execution_allowed=false불변·실파지검증으로승격없음. 공급RGBD/조립XY없음.
- 기본yellow슬롯2 인터페이스·검증 유지. red선택은 별도 --confirm-red-slot1-ready 및손제거flag필수, 공통writer lock/실행전sourcehash/중단·hold경로재사용. red전용로그분리. 자동상승/놓기/조립/복구없음.
- 관련단위62passed (red-slot1-regression.log), preview무연결통과. 실장치read-only 1792029501261072146/precheck.json: 관측자세정지3회/status0폭52/TCPGripperDA_v4/ToolWeight0,4endpoint IKFK최대0.004891mm/0.000590deg,physical_commands0. 경로충돌여유/빨강실파지/들기/결착/B/DB미검증.
- RED_SLOT1_PICKUP_GUIDE.ko.txt에사용자직접실행명령·사전배치·이동3회/닫기1회·종료시낮은위치holding·다음실물확인안내. 에이전트실제run미실행. 다음은작업자단일시험실행및실제패드정렬·파지상태보고.

## 2026-10-15 빨강 슬롯1 재교시 기록 확인
- manual-red-slot1-20261015T110138/pickup/pickup.json: 슬롯1/TCPGripperDA_v4/ToolWeight0 및원시pose샘플hash확인,3회좌표동일. 새XYZ[-329.113129,-54.518528,49.283184],회전[167.260941,-178.444489,167.412262]. 기존교시대비위치 6.166mm/실회전 0.375deg. teaching-review.json 별도기록,원본보존/실행설정미반영/실파지미검증/에이전트장치동작0. 다음작업자기존빨강닫기20mm·힘40N으로수동닫기후정지,상승전확인.

## 2026-10-15 빨강 슬롯1 수동 닫기 후 읽기 확인
- 사용자닫힘보고. closed-readonly-1792029757420482177.json: 3회모두gripper_status2/폭39.9mm/정지,새교시pose차0.00120mm/0.000115deg이하. 장치쓰기0. 닫기명령설정값20mm와실측폭39.9mm를구분하며폭만으로정확파지판정하지않음. 다음작업자양패드의빨강블록중앙접촉및주변비접촉육안확인후수직들기단계. 실물정확파지/들기/결착/B/DB미검증.

## 2026-10-15 빨강 슬롯1 2点面 교시 수동 들기 확인
- 사용자2점축파지기준/정확파지/들림보고. lift-readonly-1792029861562990397.json: {"stopped": true, "rise_base_z_mm": 22.991741180419922, "xy_drift_mm": 0.9383912897546505, "rotation_change_deg": 0.20657911038817578, "gripper_status": 2, "gripper_width_mm": 39.9}. 3회읽기조회,에이전트장치동작0。연속들기궤적미관측/자동재접근미검증/실행설정미반영/원본교시불변。작업자수동들기와조회시holding근거만기록,결착/B/DB미검증。다음작업자원위치수동복원·개방후관측복귀。

## 2026-10-15 빨강 슬롯1 새 교시 재접근 준비 및 관측 복귀 확인
- 사용자원위치내림/개방/복귀보고후조회. logs/supply-red-slot1-trial/1792030098504025905/precheck.json: 기존관측자세정지/빈그리퍼status0폭51.5/TCPTool정상/새교시4endpoint IKFK통과,physical_commands0. 경로충돌여유·새교시자동접근파지는미검증.
- 기존slot2 runner의red전용경로에새수동교시schema지원추가,별도manual-grasp-review의작업자정렬·정확파지·수동들기·2점축확인및원본/근거hash필수. 실행전검토파일도재확인. 기존직접교시/노랑슬롯2경로유지. 새6pose그대로·20mm/40N·기존속도힘유지,공급RGBD/조립XY없음. 원자료physical_grasp_verified=false불변,검토는별도manual-grasp-review.json에단일수동시험범위만기록.
- 관련67passed(red-slot1-reteaching-regression.log),무동작검사통과. 새교시경로를명시한RED_SLOT1_RETAUGHT_PICKUP_GUIDE.ko.txt작성. 실제run은사용자직접실행안내만,에이전트이동/개폐0. 다음새교시자동접근·닫기후holding정지상태와작업자실파지확인. 자동상승/조립/B/DB검증아님.

## 2026-10-15 빨강 슬롯1 새2점축 교시 자동재접근 정확파지1회
- 사용자잘잡음확인。run1792030144985357132/result APPROACH_GRIP_SIGNAL_HOLDING_NO_LIFT_TEST,원본교시hash/새6pose일치。operator-review.json에작업자확인과원시result/events해시별도저장,원본불변。읽기3회 {"stopped": true, "pose_error_mm_deg": [0.0011951696744528445, 0.00011411908360342733], "gripper_status": 2, "gripper_width_mm": 39.9}. 에이전트이동/개폐0。공급RGBD/조립XY미적용。수동들기1회와이번자동접근닫기1회구분,자동들기/반복정밀도/결착/B/DB미검증。다음작업자현재공급위치에서개방·수직이탈·관측복귀,cleanup_pending=true。

## 2026-10-15 빨강 슬롯1 새 교시 단일 파지 시험 정리
- 사용자개방·관측복귀보고후읽기3회: {"stopped": true, "observation_error_mm_deg": [0.0013520666960485292, 0.00024487637971535035], "gripper_status": 0, "gripper_width_mm": 51.7}. CLEANUP_CONFIRMED; cleanup-readonly-1792030294335302830.json 저장,별도operator-review cleanup_pending=False. 에이전트이동/개폐0,원시실행로그·교시원본불변。
- 빨강2점면기준새수동교시→수동파지·들기1회→새교시자동재접근·정확파지1회→개방·관측복귀까지근거분리。전역시나리오·RGBD프로파일미변경. 공급RGBD보정/전체25슬롯정밀도/결착/B/DB미검증. 다음후보정책에예외교시·실파지근거반영및미검증범위구분.

- 빨강슬롯1새교시·자동접근파지1회·복귀근거를 slot-policies.candidate.json에반영,변경전후보는상위reports에별도보존. 실행승인/RGBD채택/자동실패fallback은25개모두false유지. 다음장치없는검사는25슬롯관측후보와측정기준연결정합성,미측정슬롯후보유지.

## 2026-10-15 빨강 정리 후 25슬롯 관측·측정기준 연결 검사
- post-red-reconcile-20261015T111258: 관측pose정지에서RGBD20장촬영(장치동작0),기존model-05 ROI고정재사용·재적합없음. 19평가프레임중20슬롯관측일관/5슬롯검토:노랑2x2의1(깊이10/19),2(1/19),3(15/19),노랑2x3의3(16/19),빨강1x2의1(인식14/19·모델중심차). 관측변동을재교시필요/실파지실패로판정하지않음.
- reference-reconciliation.json에25슬롯각각관측표면후보/교시근거/짝지은기준연결. 기준3개와원본파일hash/행렬/표면중앙값/슬롯/TCP정합확인,불일치0. 직접측정교시13슬롯·없는12슬롯구분,미측정파지좌표는생성·채택하지않음. 전체runtime/RGBD채택/fallback false,기존실행설정불변.
- slot-policies.candidate.json 최신관측수치·연결보고경로만반영,이전사본상위reports보존. 노랑2x3슬롯3을추가깊이검토대상분류,새교시보다기존실파지이력조회우선. REFERENCE_RECONCILIATION.ko.txt에25행상태표·제한·다음단계기록. 관측20개일관은실파지/결착/B/DB/전체통합완료아님.

- 추가노랑2x3슬롯3조회: 기존직접교시와완전동일PICKUP_LOWER의실행3건발견,3건모두BLEND_COMPLETE시grip2/폭40.6/endpoint_verified확인. 별도yellow-2x3-slot3-history-review.json에세실행각각증거구분,실행별파지·이송증거를구분. REAL_D_SYNTHETIC_B_OPERATOR_TRIAL,실물B/결착근거아님. 추가수동교시우선불필요,후보정책참조갱신/실행설정불변.

## 2026-10-15 교육용 공급 프로파일 초안 작성
- 사용자초안요청에따라 robot_control_integration/settings/round3_supply_rgbd_20261015/draft-20261015T111950/profile.draft.json 및layout.snapshot.json/PROFILE_REVIEW.ko.txt/validation.json작성. RGBD관측후보20·명시교시전용예외5,직접측정교시13·없는12구분. ROI/관측표면후보/교시·실파지·짝지은기준출처해시연결,없는파지좌표·전슬롯허용값null유지.
- 기존T1한정교육오차를전슬롯으로확장하지않음,공급RGBD실패시자동교시전환없음. 기존각슬롯회전/Z·힘·속도보존,빨강새2점축교시출처사용/슬롯5회전이식없음,조립XYfalse.
- 25유일슬롯/20·5/누락12/근거해시/새빨강pose정합검사통과,실행loader는schema불일치로거절확인. 별도신규draft schema이며실행로더·기존설정수정없음. 장치동작0/실물시험미실행/B·DB·전체통합완료아님. 다음초안검토후제한슬롯실행프로파일을별도준비.

## 2026-10-15 첫 실행용 공급 RGBD 슬롯4 프로파일 준비
- 사용자진행/실행용프로파일·슬롯선정질문에따라기존교육용RGBD근거있는노랑2x2슬롯4선택. slot4-execution-20261015/config.json: 기존슬롯4짝교시·표면기준·교육T1한정허용값그대로/최신25슬롯후보기준채택아님. 회전/Z·힘·속도불변,공급RGBD접근닫기후hold정지한정/자동상승·조립XY·조립동작없음. 전역25슬롯config불변.
- scripts/supply_rgbd_single_trial.py추가: preview기본무연결/check실시간조회전용/run명시execute+slot4준비+손제거,공통writerlock/근거hash/기존depth로더범위검사/preflight/기존supply.execute(trial_row,hold_at_pickup)재사용. start_zone=supply고정,홈이동없음. LiveVision에무동작검사용show_window=false만추가,기존run영상ESC중단유지.
- 저장최신20영상기존프로파일보정재생20/20통과(실시간검사아님). 관련106passed(slot4-rgbd-execution-regression.log). 실제readonly1792031051887270108: 빈그리퍼폭 51.7mm/정지/TCPTool정상,실시간보정 [1.0174396223551412, 0.524348460389291]mm/깊이532.0mm,보정후endpoint IKFK통과/physical_commands0. 허용값확대없음/실제파지run에이전트미실행.
- RUN_GUIDE.ko.txt에일반터미널직접실행/슬롯4배치/3이동닫기1회/holding종료/로그/다음단계기록. 다음작업자단일실행및실파지확인. 전체25슬롯보정·결착/B/DB미검증.

## 2026-10-15 슬롯4 RGB-D 보정 접근·정확파지 단일시험 작업자확인
- 사용자정확파지보고. run1792031150121333215: RGBD READY/center_assist_applied=true/fallback_reason=null,XY [0.9514035700007071, 1.2443317058278467]mm실제명령반영. 원래Z/회전불변,닫기35mm·힘40N유지. result RGBD_APPROACH_GRIP_SIGNAL_HOLDING_NO_LIFT_TEST/정지/status2폭40.4.
- 독립읽기3회 {"stopped": true, "commanded_target_error_mm_deg": [0.0015242687866802525, 0.00013369494537889698], "gripper_status": 2, "gripper_width_mm": 40.4}. 원시result/events불변,operator-review.json에작업자확인·해시·적용범위별도저장. 에이전트이동/개폐0,cleanup_pending=true.
- 교육용고정슬롯4 RGBD보정접근·파지1회성공범위만확인,자동상승/결착/전체25슬롯정밀도/실제B/최종DB미검증. 다음작업자현재공급위치에서그리퍼개방후수직이탈·관측복귀.

## 2026-10-15 슬롯4 RGB-D 단일 파지 시험 정리 완료
- 사용자개방·관측복귀확인후읽기3회:기존관측point거리0.002190mm/회전0.000276deg/정지/그리퍼status0·52mm. cleanup-readonly-1792031300789147102.json 및trial-summary.json의source_files에실제경로연결. cleanup_confirmed=true/별도operator-review cleanup_pending=false. 원시result/events보존·에이전트이동개폐0.
- trial-summary.json에소프트웨어106통과/저장영상20·실시간조회/실제RGBD보정XY[0.95140357,1.24433171]파지1회/작업자확인/복귀분리. 보고서상위reports/SLOT4_RGBD_TRIAL_SUMMARY.ko.txt작성. 이번자동상승/반복정밀도/결착/B/DB미검증,이전native/HMIT1결착과별도.
- 후보정책에슬롯4기존교육용범위성공근거만연결/이전정책백업보존,전역runtime설정변경없음/25슬롯실행승인·RGBD채택·자동fallback false유지. 다음권장T2파랑2x3슬롯3기준높이·자세와허용범위검토후별도프로파일준비,다음물리시험미시작.

## 2026-10-15 교육용 공급 최소 시험 목록
- 사용자최소시험목록요청. reports/round3_robot_pc_20261015/MINIMUM_SUPPLY_TEST_PLAN.ko.txt 및minimum-supply-test-plan.json작성. 완료슬롯4RGBD/노랑슬롯2교시/빨강슬롯1새2점축교시/기존native-HMIT1결착재시험생략.
- 추가실물기본1회=T2파랑2x3슬롯3(2x3·3점면·다른행대표),기준높이자세정합·슬롯한정허용값·무동작검사통과전실행없음. T3노랑2x3슬롯5는구체적위치오차잔류시만조건부/기본생략. 파랑2x2별도실물시험기본추가없음,미검증슬롯을완료로승격하지않음.
- 25개일괄영상·기준검토/예외5명시/미측정교시12후보유지,전체재교시요구아님. 대표교육검증과전체정밀도·반복성·결착/B/DB구분. 장치동작0/실행설정변경0. 다음T2무동작기준정합검사·개별프로파일준비.

## 2026-10-15 T2 실행 준비: 기존2점축 및 기준불일치 확인
- 사용자진행지시. reference_config(T2)는파랑2x3슬롯3/span2/닫기35mm/힘40N,기존실행교시[-459.112274,11.112536,50.554276,9.841970,179.121948,10.311336]. 최소시험계획의3점면대표설명을2점축유지로정정·이전JSON보존. 축/파지설정변경없음.
- 기존RGBD짝측정과기존실행교시는위치4.070467mm/실회전0.608683deg차,측정Z가2.630444mm낮음. 별도변위검증도Z0.721577mm/자세1.624094deg차로진단범위. 임의보정/기준혼합/새높이채택없음.
- logs/supply-depth-reference/T2-runtime-matched-20261015T113333: 기존교시4endpoint IKFK/관측정지/빈52mm무동작검사통과,새20장촬영·슬롯3인식/깊이검토 20/20; 관측깊이범위[523.0, 523.0]mm. 장치동작0. profile.pending.json은execution_allowed=false/허용값null,실행용준비미완료사유명시.
- NEXT_MEASUREMENT.ko.txt에기존T2 Z/회전유지·XY현재블록중앙수동정렬후teach-pickup기록안내. 한슬롯기준연결측정필요/전체재교시요구아님. 다음새교시일치검사·블록위치유지짝촬영후슬롯한정교육허용범위검토. 자동파지/조립/B/DB미실행.

## 2026-10-15 T2 재기록 확인: 높이·자세 불일치 유지
- 사용자기록보고후T2-runtime-matched-20261015T113333/pickup 확인: 슬롯/TCPTool/hash정상,3회pose동일. 새pose [-453.08966064453125, 9.289710998535156, 48.208892822265625, 0.40635234117507935, 177.58763122558594, 0.4011799693107605]; 기존실행대비Z -2.3453826904296875mm/실회전 1.6246506687731952deg. 기존높이·회전일치로표시하지않음. 측정값원본보존/실행설정미변경/실파지미검증/장치동작0.
- teaching-review.json에정합검토결과기록. 반복교시요청또는새공급전용교시채택을임의결정하지않고사용자의도확인필요. 다음블록위치유지및기준선택확인후짝촬영연결.

## 2026-10-15 T2 높이·자세 보정 명령 준비
- 사용자평균요청후이동명령안내로지시변경,평균자료미생성/기존설정불변. 읽기조회정지·빈그리퍼52mm/TCPTool정상. 현재[-453.088226,9.289664,48.205864,0.405994,177.587219,0.400821]에서XY동일·기존Z/ZYZ목표[50.554276,9.841970,179.121948,10.311336]로의MoveLine명령안내준비. 실제Z+2.348412mm/실회전1.625044deg,기존속도12/6·가속48/3유지.
- z-attitude-correction-precheck-1792031940186478641.json에조회·목표IKFK오차0.004722mm/0.000436deg기록,장치동작0. 경로중간충돌여유검증아님. 사용자직접이동후성공응답·새pose기록필요,관측짝촬영/실파지미검증.

## 2026-10-15 T2 높이·자세 보정 도착 및 교시 별도 저장
- 사용자이동완료후조회: correction-arrival-readonly-1792032018241655222.json,기존Z오차0.000069mm/실회전오차0.000122deg/정지·빈52mm확인. 에이전트명령은조회만/실제이동은사용자수행. 평균적용없음.
- pickup-height-matched/pickup.json 별도read-only기록,기존pickup원본보존·전역실행설정불변. hash/3회pose동일/기존높이·회전일치검사통과. profile.pending은짝관측·교정후패드중앙작업자확인·T2한정허용범위대기,execution_allowed=false.
- 다음기존2점축패드중앙정렬이유지됐는지작업자확인후닫지않고수직이탈·기존경로관측복귀,블록위치방향유지짝촬영. 실파지·새RGBD기준승인으로표시하지않음.

## 2026-10-15 T2 높이·자세 일치 교시/관측 연결 및 실행 프로파일 준비
- 사용자교정후중앙맞음·관측복귀확인. observation-height-matched20장저장,기존관측점차0.007mm수준. 19장유효/1장영상나이300.07479ms로엄격거부,기준완화없음. 깊이패치523~525mm/최대편차1mm/기준XYZ변동XY0.093218mm·Z1.001129mm. 새로운surface-quality-candidate.json은측정후보이며독립정밀도검증아님.
- T2-slot3-execution-20261015에새2점축높이일치교시와짝표면기준/별도ROI/허용범위제안/실행config준비. 제안XY1mm·표면높이차2mm·깊이521~527·패치2mm는T2제안시험경계(미승인),T1범위자동전용아님. --accept-t2-educational-profile명시옵션없이는check/run연결전거부. 원본profile operator_accepted=false보존·실행cfg에명시선택기록.
- depth_center로더에T2공급한정정확slot/pose·span2·T2scope·explicitflag·조립XYfalse/자동상승false바인딩추가,T1기존범위검사유지. 단일runner T2선택/slot3준비flag·전용로그·기존hold제어재사용,교육확인근거문자열T1/T2구분. 관련108passed(장치없는합성fixture),저장19장제안범위통과/오래된1장거부,실장치경유점·빈52mm무동작통과。
- RUN_GUIDE.ko.txt에선택의미·먼저check직접실행·결과확인후별도run안내. 실제T2실시간교육옵션선택/물리파지아직미실행,전역시나리오변경0·에이전트장치동작0. 다음작업자제안범위명시선택후실시간무동작검사결과확인.

## 2026-10-15 T2 사용자 명시 선택 후 실시간 무동작 검사 통과
- 사용자통과보고 및 logs/supply-rgbd-T2-slot3-trial/1792032585285241080/live-check.json 확인. READ_ONLY_RGBD_READY/physical_commands0,실행snapshot operator_accepted_t2_educational_profile=true로T2한정제안범위명시선택확인. 보정XY[0.021601494646972697, 0.10821001449746959]mm/깊이524.0mm/보정경유점IKFK통과.
- 다음사용자단일run명령안내,공급보정접근·닫기후hold정지/기존2점축닫기35·힘40N유지/자동상승·조립없음. 실제T2물리시험은아직미실행,전역설정변경0/에이전트장치동작0.

## 2026-10-15 T2 실행 전 신선도 중단 진단·처리 순서 수정
- 사용자SUPPLY_DEPTH_FRESH_SYNCHRONIZED_PACKET_REQUIRED보고. run1792032615502602493은TRIAL_START/START_OBSERVATION_REACHED/BLOCK_BEGIN만있고이동·닫기전중단(기존예외STOP요청경로수행). 원로그시각상세없어단일원인확정은불가,계산전GUI표시/PNG저장을불필요지연으로확인.
- 단일runner에OpenCV1thread·depth증거defer·이동전중복표시제거,종료·정지finally에PNG/JSONflush. ESC감시유지,기존기타실행은defer기본false유지. 패킷별나이/skew/인식시간/pose조회시간기록및실패시진단저장. 300ms/50ms·공간·힘·속도기준불변,오래된영상거부지속. 합성정상/오래됨/실패/증거지연저장검사포함114passed.
- 첫실제조회시별도FK서비스timeout발생,사용자로봇재연결보고후새driverPID909788/카메라712101 각1개·ROSdomain20확인. 에이전트재시작/설치없음. 재연결후check1792032960843084158통과,gui-readonly-1792032992581798158도이동없이통과:패킷198.786967ms/skew0/인식31.74648ms/pose조회25.14935ms.
- reports/T2-freshness-diagnosis-and-fix.json에범위·제한·로그기록. 실제파지재시도는미실행,다음사용자한줄run명령안내. 에이전트이동·개폐0/원교시·기준·프로파일한계불변.

## 2026-10-15 사용자 요청 T2 영상 신선도 310ms 적용
- 사용자기준늘림/310명시지시. T2profile max_packet_age_ms=310추가·승인자료amendment/manifest해시일치갱신,이전3개설정상위reports백업보존. 신선도선택·rgbd_target최종검사·이동전만료계산공통값적용. T1등필드없는기존profile은300ms유지,토픽skew50ms·공간/힘/속도기준불변.
- 직전실패1792033060803653046은모든ages301.647878ms/skew0,인식30.837675ms·pose조회21.095642ms,이동/닫기전중단. 처리예산100ms필터개발시도는사용자310명시지시에따라적용하지않음. 기존증거defer최적화유지.
- 관련118passed(T2-310ms-regression.log),301.647878ms/309.999999ms허용·311ms거부·기본300ms와skew50ms거부유지검사. 실제설정load/근거hash검사도통과. 새물리시험미실행/에이전트장치동작0. 다음사용자같은단일T2run명령재실행후파지상태확인.

## 2026-10-15 T2 교육용 RGB-D 보정 단일 파지 성공 작업자 확인
- 사용자파지잘함. run1792033310942237285: RGBD보정applied=true/fallback없음,XY[0.009718532,0.032230608]mm/검사패킷225.126514ms·skew0/깊이524mm. 기존2점축·교시Z/회전·닫기35mm·힘40N유지,사용자요청310ms한계범위.
- result RGBD_APPROACH_GRIP_SIGNAL_HOLDING_NO_LIFT_TEST,작업자정확파지확인별도operator-review.json기록/원시result/events보존. 독립읽기3회 {"stopped": true, "commanded_target_error_mm_deg": [0.0008759105466503392, 0.00011551249225823034], "gripper_status": 2, "gripper_width_mm": 40.4}. 에이전트이동개폐0。cleanup_pending=true,자동상승/반복정밀도/결착/B/DB/25슬롯실물검증아님.
- 교육용대표RGBD공급파지T1슬롯4·T2슬롯3각1회확인,기본계획의추가대표시험은T2로완료. 다음사용자현재공급위치개방·수직이탈·관측복귀후일괄프로파일연결작업,새실물시험자동추가없음。

## 2026-10-15 T2 대표 RGB-D 파지 시험 정리 완료
- 사용자개방·복귀보고후독립읽기3회: {"stopped": true, "observation_error_mm_deg": [0.0007202811129841841, 1.5407723092281324e-05], "gripper_status": 0, "gripper_width_mm": 52.0}. T2_EDUCATIONAL_RGBD_SINGLE_GRASP_CLEANED_UP; cleanup-readonly-1792033463953276813.json 및trial-summary.json저장/원시로그보존,operator-review cleanup_pending=False. 에이전트이동개폐0.
- T1슬롯4/T2슬롯3 교육용대표RGBD공급파지각1회및교시예외파지근거확보. 전체25슬롯실행좌표·표면기준·실행조건일괄연결은별도미완료,결착/B/DB/전체통합완료아님. 다음현재관측자세유지·일괄프로파일연결검사,추가물리시험자동시작없음.

## 2026-10-15 교육용 조건부 공급 실행 프로파일 완성
- 사용자 모델 기반 확장·실행 승인 요청에 따라 settings/round3_supply_rgbd_20261015/execution-approved-20261015/profile.json 생성. 20개 RGBD_XY(짝 실측·단일 파지2개 + 관측 모델18개), 5개 TEACHING_ONLY(노랑2×2 슬롯1/2/3, 노랑2×3 슬롯3, 빨강1×2 슬롯1). 슬롯6 제외. 승인과 실제 파지·독립 정확도 검증을 분리하고 원자료/기존 시험 설정 보존.
- organize_supply_profile.py가 저장 근거 해시·기존 앵커 보간·25개 단일 실행 설정/20개 깊이 프로파일/ROI를 생성·검사. execution_profile.py가 명시적 승인과 출처 해시·슬롯 모드를 검증. RGB-D 실패 시 교시 전환 없음, 교시 예외는 등록된 정확한 자세만 허용. 모델18개 상대 XY 상한1mm, 각 슬롯 관측 기반 깊이/편차/높이 설계 한계이며 정확도 인증 아님.
- --execution-profile 선택 옵션을 단일 공급 runner, native T1~T3, HMI 고정 T1에 연결. 기존 높이·회전·힘·속도·닫힘 폭 유지, 조립판 XY 비활성 유지. 일반 C/A/B/D 자동 실행 경로에는 자동 적용하지 않음.
- 실제 저장 프로파일25개 load/bind 및 native3개 preview 검사 통과. native143 + HMI14 =157개 관련 테스트 통과. validation.json/integration-validation.json/native-tests.log/hmi-tests.log/manifest.json에 결과 저장. 장치 연결0·동작0; 다른 팀 장치 인계 상태 유지.
- 현재 RGB-D 단일 실파지 확인2개/교시 전용 단일 실파지 확인2개, 나머지 개별 파지·반복정밀도 미검증. B 실제 조립 확인/최종 DB 저장/전체 ABCD 완료를 주장하지 않음. 다음 제어권 반환 후 장착·TCP·영상·시각·배치 재확인, 선택 슬롯 무동작 check 후 작업자 실행. 사용법 RUN_GUIDE.ko.txt.

## 2026-10-15 Round3 서비스 연결: 승인된 실제 A 첫 Step → 해당 native 교시·공급 프로파일

### 시작 상태와 서비스 경계

- 작업 위치 `c2_integration_round3`, 브랜치 `codex/integration-round3`, HEAD `bda07e5`. 이후 커밋은 없었지만 공급판·교시·HMI 관련 미커밋 변경과 새 실행 프로파일이 있었다. 작업 전 diff/status를 상위 로컬 `reports/round3_service_step_20261015/preexisting.patch`, `preexisting-status.txt`에 보존했다. 기존 변경·원자료를 되돌리지 않았다.
- 사용자 지정 `robot_control_integration/settings/round3_supply_rgbd_20261015/execution-approved-20261015/profile.json`을 사용했다. 20개 RGBD_XY와 5개 TEACHING_ONLY 모두 조건부 실물 실행 대상이다. 개별 미검증을 실행 대상 제외로 해석하지 않으며, 개별 파지·반복성·전체 조립 검증 여부는 별도 기록한다.

| 서비스 구간 | 이번 확인 / 연결 범위 |
|---|---|
| 로그인·시작·사용자 소유자 | 기존 계정/Job 소유자 경로 유지. DB 설정 시 기존 로그인 시작 조건 적용. 이번 작업에서 DB 연결 검증하지 않음 |
| C 설계·미리보기·별도 APPROVE | 기존 C 호출·미리보기·승인 경로 재사용. 승인이 없으면 A 및 native 실행 없음 |
| A 전체 계획·단계 재평가·모션 | 실제 A 함수 사용. A 순서를 T1로 덮어쓰지 않음. 기존 8블록+T1/T2/T3 설계에서 첫 Step은 T2 |
| D 실제 실행 | 새 명시 모드에서 A 첫 Step의 여섯 배치 필드에 맞는 native case·교시·슬롯·공급 프로파일을 연결. 한 Step만 실행 가능 |
| B 초기 Current | B의 실제 저장 INITIAL 자료를 다시 B 검사 소유자에 전달하여 채택. 합성 scene이나 설계를 Current로 대체하지 않음 |
| D 실행 후 B STEP / 다음 Step | 이번 실물 경로에는 미연결. 동작 성공도 HOLD, Current·completed 유지 |
| C 중간 변경·새 승인·A 재계획 | 기존 저장 관측 MOCK 재생 경로는 유지. 새 native 한 Step이 시작된 뒤에는 변경·재개·재검사 자동 실행 없음 |
| 별도 FINAL B·종료·사용자별 저장/표시 | 기존 모의/독립 구현과 구분. 이번 native 결과로 COMPLETE/DB 저장을 시작하지 않음 |

### 구현과 입출력

- `app.mvp_real_trial.ApprovedStepRealTrial`과 `--round3-approved-step` 추가. 기존 `--round3-fixed-step`, 일반 REAL 시험, MOCK 재생의 기본 동작은 유지한다.
- 제한 설계는 지정 scenario의 사전배치 8개와 T1/T2/T3 목표 3개다. 사전배치+T1만을 설계로 쓰면 C 연결성 검사에서 탈락하므로 검사를 약화하지 않고 연결된 전체 후보를 승인받는다. 실행은 A가 실제 선택한 첫 Step 한 개이며, 나머지도 이후 실물 실행 대상이다.
- native 무동작 preview로 기존 교시·보정·등록 슬롯을 읽고, 대응 pickup/assembly 기준을 A 재평가·모션 입력에 함께 제공한다. 실행 시 native가 동일 설정을 다시 생성하고 해시를 비교한다. A의 운반 후보를 새 저수준 궤적으로 실행하지 않고, 매칭된 기존 D native skill을 사용한다.
- `approved-step.json`에 C 승인 설계, B 기준 Current, A shared bundle·재평가/모션 요청·결과, 예약 슬롯, 실행 ID, 교시 설정 해시, 프로파일 해시, 준비 확인과 120초 실행 인계 기한을 저장한다. native의 `--approved-step-document`가 Plan/Step/revision/generation·슬롯·설계·교시·프로파일 일치를 장치 연결 전에 재검사한다.
- REAL READ_STATE 프로세스를 종료·join하여 기존 writer lock을 해제한 뒤 native가 동일 lock을 획득한다. native는 실행 ID를 독점 기록하여 같은 실행을 자동 재시도하지 않는다. STOP은 native SIGINT로 전달하며 프로세스 종료를 실제 정지 확인으로 표시하지 않는다. 늦은 성공·다른 실행 결과는 성공으로 채택하지 않는다.
- native 결과에 `service_binding`을 추가했다. 공통 ABCD/ROS 메시지는 변경하지 않았다. HMI의 `observation_kind`에는 `SAVED_REAL_INITIAL_ONLY`를 명시적으로 추가하여 가짜 B, 초기 저장 실관측, 후속 B 미연결을 구분한다. 제어 높이·자세·힘·속도·그리퍼 폭·조립판 XY 정책은 변경하지 않았다.
- 약 10개 파일의 작은 연결 변경이다. 기존 프로세스와 native skill 재사용으로 새 서비스/DB/dependency/추상 계층을 추가하지 않았다. 전체 연속 실행까지 한 번에 확장하는 방안은 제외했다. 수동 코드 리뷰는 별도이며 AI 검사를 사람 리뷰로 표시하지 않는다.

### #55 확인과 초기 관측 입력

- [홍동 PR #55](https://github.com/suuuhululu/C-2/pull/55), 확인 SHA `04a382157b60a7697c0c4570478bda37211e5e1c`, OPEN, 대상 `codex/integration-round2`. round3 HEAD의 조상이 아니며 이번 작업에서 merge/cherry-pick하지 않았다.
- INITIAL을 V0 단독에서 V0→D1→D3로 복구한다. 새 `stud_layer`는 live/replay `process_frame`의 추가 층 진단값이며, 실제 관측 사이클의 `process_saved`→B 비교 입력 경로를 대체하지 않는다. 48/48 진단을 전체 B 조립 확인 성공으로 해석하지 않는다.
- D3 `confirm_view` 이후 `is_stopped=False` 문제는 PR에 미해결로 기록돼 있다. 해당 `inspection-state-failures` 원시 JSON은 현재 작업 폴더에서 찾지 못했으므로 원인을 단정하거나 정지 검사를 완화하지 않았다.
- `--initial-observation`은 B가 성공 저장한 **INITIAL cycle 디렉터리**다. `context.json`, `observed.json`, `V0/metadata.json`, `D1/metadata.json`, `D3/metadata.json`을 읽는다. mode=REAL, check_kind=INITIAL, 세 View, 동일 check_id/observation_seq/calibration_id/scene_id, timezone 포함 촬영시각을 검사한다. 초기 채택은 가장 오래된 촬영부터 300초 이내이며 원본 파일 해시와 source identity를 Job 로그에 보존한다. 실패·관측 불가·파일 변경·오래된 자료는 B 오류/보류이며 가짜 MATCH로 보완하지 않는다.

### 실행 준비 예시 (이번 작업에서 실물 실행하지 않음)

상위 로컬 `reports/round3_service_step_20261015/limited-design.candidate.json`은 기존 scenario에서 만든 11블록 **검토 후보**이며 승인 결과가 아니다. 준비 체크박스는 초기 관측 후 8블록 배치 유지·대상 공급 슬롯·빈 그리퍼 HOME·기존 경로 확인이다. `--start-zone home`은 HOME 이동 명령이 아니다. 정상 ROS 환경의 터미널에서 아래 초기 관측 경로를 실제 최신 B cycle 폴더로 지정한다. `HISTORY_DATABASE_DSN`이 설정돼 있으면 기존 제작자 로그인도 필요하다.

```bash
ROS_DOMAIN_ID=20 C_DESIGN_USE_LLM=0 python3 -m app.mvp_real_trial \
  --robot-root ./robot_control_integration \
  --log-directory ./logs/round3-approved-service \
  --round3-approved-step \
  --initial-observation /absolute/path/to/new-initial-capture \
  --fixed-trial-scenario ./robot_control_integration/settings/round3_educational_t1_20261015/scenario.json \
  --execution-profile ./robot_control_integration/settings/round3_supply_rgbd_20261015/execution-approved-20261015/profile.json \
  --design ../reports/round3_service_step_20261015/limited-design.candidate.json \
  --execute
```

준비 확인→시작→C 후보 미리보기→사용자 명시 승인의 순서로 진행한다. C 응답란은 기존 기능을 사용한다. `C_DESIGN_USE_LLM=1 --c-mode live`는 기존 C 음성/LLM 경로를 선택한다. 어느 경우든 승인 후 A가 계획하고 기존 native 관측·실행 팝업으로 한 Step만 실행한다. 실행 성공 후에도 `APPROVED_STEP_EXECUTED_B_CONFIRMATION_REQUIRED` HOLD이며 남은 Step·Current 갱신·최종 저장으로 진행하지 않는다.

### 검증·남은 작업

- 새 연결 검사는 실제 C review·A 계획/재평가/모션·B 채택 함수를 사용하고 장치 transport/실행 결과만 명시적으로 모의한다. 승인 전 차단, A 자동 첫 Step T2 유지, native 소비자 preview, Step·슬롯·revision·프로파일·만료 불일치, STOP 후 늦은 결과, 초기 세 View 누락/장면·ID 오류/원본 변경/오래됨/관측 불가, HMI JSON Schema·Qt 표시를 확인했다. 새 연결 12 passed (`final-approved-step-tests.log`), 고정 T1·HMI 계약·Workflow 포함 관련 검사 177 passed (`final-focused-tests.log`).
- 확장 회귀 검사: `final-root-tests.log` 203 passed / 5 failed. 다섯 실패 모두 `test_mvp_full_real_adapter.py`의 오래된 2~3점 지지 설계가 C의 최소4점 검사에서 거절된 결과다. 작업 전 코드(HEAD+보존한 미커밋 patch)를 별도 폴더에 복원하여 같은 다섯 node ID와 같은 support 오류를 재현했다(`baseline-failures.log`, 5 failed). 이번 변경으로 생긴 실패로 분류하거나 전체 PASS로 표시하지 않는다.
- native 제어/교시/공급 프로파일 관련 152 passed (`native-regression.log`). 별도 저장 관측/중간 변경 재생을 포함한 회귀 검사 197 passed / 5 skipped (`root-regression.log`, 당시 C2_ROBOT_ROOT 조건). #55 최신 소스 별도 검사 76 passed (`pr55-tests.log`). 모두 장치 없는 검사이며 현재 장치 상태를 증명하지 않는다.
- 변경 Python 8개 AST 파싱, HMI JSON 파싱과 `git diff --check` 통과. 제공 실행 프로파일은 native 전체 preview에 기록된 SHA256과 최종 파일 SHA256이 동일하다. 검사 로그·후보·PR diff/검토 소스·작업 전 비교 소스는 상위 로컬 `reports/round3_service_step_20261015`에 보존했다.
- 실물 L4, 실제 B INITIAL 촬영/채택, live C 음성/API, 실제 D 결착·후속 B STEP/FINAL, PostgreSQL/사용자별 최종 저장은 이번 작업에서 실행하지 않았다. 최신 성공 INITIAL cycle 폴더도 현재 작업 자료에서 찾지 못했다. 로봇/그리퍼 명령과 카메라 연결 0. lint/type checker는 저장소에 미구성이며 새 도구를 설치하지 않았다.
- 다음은 #55의 INITIAL 세 View 실행과 D3 정지 판정 원자료 확인→성공 저장 cycle을 새 모드에 공급→한 실제 A Step의 D 실행·로그 확인이다. 그 뒤 별도 작은 작업으로 B 실제 STEP 비교·MATCH 진행, 중간 변경/별도 승인·Current 유지 재계획, FINAL 확인·사용자별 저장을 연결한다. 커밋/push/PR 게시/merge는 수행하지 않았다.

## 2026-10-15 Git 업로드 대상 선별 및 공급 프로파일 의존자료 정리
- docs/ROUND3_GIT_UPLOAD_FILES.txt에 파일 단위 업로드 목록, ROUND3_GIT_UPLOAD_REVIEW.ko.txt에 코드/프로파일/별도 승인 Step 공용 변경과 로컬 제외 범위를 기록. 공용 파일의 승인 Step 수정은 제거하지 않고 별도 검토 묶음으로 표시. stage/commit/push 미실행.
- execution-portable-20261015 새 배포본 생성. source_sha256을 배포본 기준 상대경로로 지원하고, 필수 JSON26개를 evidence에 바이트 동일 복사. 원본 현장 프로파일·영상·logs/reports는 보존하고 .gitignore로 구분. 활성 설정의 /home 경로 제거, 중첩 원본 기록의 경로는 비실행 역사 출처로 유지. 기존 좌표·제한값·20 RGB-D/5교시 승인·미검증 상태 동일 대조.
- HEAD+선별 목록만 복사한 별도 경로에서 원래 PC 경로 읽기 차단 후 25슬롯 load/단일 설정 및 native3Step preview 통과. 별도 checkout 관련 native241 + HMI/승인 Step26=267 테스트 통과. packaging-validation.json에 결과 저장. 장치 연결0/동작0, 실제 후속 B 판정·DB·전체 ABCD 완료 주장 없음.


## 2026-10-15 PR55 실제 B 3-Step 별도 검토본

- 이 항목은 PR55_round3_verified/runtime 별도 폴더만의 구현/검증이다. 원본 C-2-round3 및 실행 HMI·장치를 변경하지 않았다. PR55 최신 확인 SHA: `2d3f001f905670af04a096dac87b8af99f090d48`.
- `--round3-b-three-step`: 실제 저장 INITIAL→C 승인→A T2/T1/T3·매번 재평가→native 단발 실행·빈 개방/HOME→실제 B STEP MATCH→다음 Step→별도 FINAL. B Current/revision/Expected/비교 소유를 유지한다. 고정 3-Step 외 설계/순서는 차단한다.
- 최신 사용자 지시의 공통 수평10mm/P70N, T2 판+X1.5mm, 일반 이동2배/접촉12mm/s, I 기존값·하강12mm·O47mm를 보존했다. 현장 프로파일은 별도 `settings/round3_b_three_step_20261015`에 원본 바이트 그대로 복사했다.
- 승인 prefix/슬롯/현재 revision/교시·HOME 해시/만료를 검증한다. native와 B의 writer를 순차 인계하고, 각 팝업 ENTER 뒤 승인 만료를 재확인한다. B 관측 순번은 check_id마다0이며 global 증가로 검사하지 않는다. native의 과거 app.contracts 이름 충돌을 피해 B의 배치 검증을 사용한다. T3의 별도 native 지지 팝업은 유지한다.
- 실제 C/A/B 로직과 명시적 장치 fixture: 루트127 passed/2 PostgreSQL DSN skipped, native211 passed, PR55 B 전체512 passed/1 외부 PR22 Consumer skipped, B 실제 Docker(네트워크·장치 없음)72 passed. 패치 무적용 검사/AST/YAML/JSON/프로파일 preview 통과. 결과는 상위 evidence 폴더의 이번 작업 로그다.
- 실물 L4·새 INITIAL 성공·실제 B 영상 판정·로봇 결착·DB/웹 저장은 시행하지 않았다. stud_layer는 진단값으로 실제 process_saved 관측을 대신하지 않는다. D3 원시 정지 실패 자료가 없어 원인을 확정하지 않았으며 정지 검사를 완화하지 않았다.
- 실행: `bash scripts/round3_b_three_step.bash initial` 이후 성공 결과의 `initial_capture_directory`를 `bash scripts/round3_b_three_step.bash hmi <cycle-directory>`에 지정한다. 기본 `preview`는 장치 없는 검사다. 상위 README_FIRST.ko.txt/REVIEW.ko.txt와 manifest/verify.py에 전달 절차·범위·해시·검증 한계를 기록했다. commit/push/PR 게시/merge 없음.


## 2026-10-15 수신 후 최신 사용자 설정 병합

- 이 별도 runtime에 T2 판+X1.5mm를 제거하고 판+Y1.5mm만 적용했다. 두 축 동시 입력은 거절한다. I 키는 사용자의 육안 각도 확인으로 바로 결착을 시작하며 자동 yaw를 일시 정지한다. T3 지지 확인·장치/힘/정지 검사는 유지한다.
- `settings/round3_b_three_step_20261015` 전체 묶음의 공급 RGB-D20슬롯에 수평거리·높이편차·3×3깊이퍼짐 모두10mm를 적용했다. 기준면·집기Z/자세·관측 pose·원자료 해시·절대 깊이518~542/최신310ms/동기50ms와 다른 설정을 유지한다. TEACHING_ONLY5개는 그대로다.
- 실제 B 전용 Step 분리/HOME/writer 해제/승인 prefix/ENTER 후 만료 재확인을 보존했다. launcher는 원래 PC의 private `.env.sixpart-local.bash` 계정/DB 설정을 source하되 프로젝트/PYTHONPATH/프로파일은 이 runtime으로 바인딩한다. 비밀값은 복사/출력하지 않았다. 가짜 interpreter/환경만으로 launcher 경로를 검증했다.
- 변경 후 native220 passed, 실제 C/A/B와 명시적 장치 fixture 통합45 passed/2 PostgreSQL DSN skipped. 두 설정 묶음의25슬롯/20RGB-D와 모든 원자료/설정 해시를 확인하고 initial/native preview를 장치 없이 실행했다. 새 INITIAL, 실제 RGB-D 판정/결착/DB·웹 저장은 미실행이다. 전달 당시 B512/1skip·Docker72 검사는 해당 B 파일이 바이트 동일함을 확인해 근거로 보존하며 이번 재실행 수치로 표시하지 않는다.
- 전달 원본 manifest·변경 전 파일은 상위 evidence에 보존했다. 현재 실행 대상은 이 runtime과 갱신된 manifest/verify.py다. reviewed.patch/reviewed-code.tar.gz는 수신 당시 역사 자료다. latest-local.patch/최신 로컬 변경 목록은 이번 보정만 나타내며 원본 main에 전체 덮어쓰지 않는다. 로봇 명령0/장치 연결0/commit·push0.

## 2026-10-15 빈 판 랜덤 5층 D·B 시험

- 최신 요청으로 별도 `app/round3_stack_five.py`와 실행 helper를 추가했다. 기본 preview는 무동작이다. 노랑·파랑 2×2/2×3 20슬롯에서 중복 없는 랜덤5개를 고정하고 기본 (13,11) 최소 점·0°·1~5층에 적층한다. 빨강 1×2 5슬롯은 제외한다. 기존 C 승인 3-Step·DB/웹 모드와 분리된 D·B 장치 시험이다.
- run은 실제 빈 판 INITIAL 성공·빈 B Current·HOME/writer 인계를 확인한 뒤 각 native 단발→개방·가압·상승/HOME→실제 B STEP MATCH를 진행한다. 마지막은 별도 FINAL이다. B 소유 Current/비교를 생성 목표로 대체하지 않는다. 오류·중단·비교 실패 때 다음 집기/자동 재실행은 없다.
- P 반력 정지 기준60N·I45N·접촉12mm/s·일반 이동2배·O47mm/44~50mm를 적용했다. 최신 사용자 요청으로 추가 60N 도달/정지확인 인증 조건은 제거했다. 기존 native가 가압 후 정상 완료하면 진행하며 최대 이동 한도 종료의 60N 미도달 자체를 보류 사유로 추가하지 않는다. P 생략·실제 장치/STOP 오류·HOME 실패는 기존대로 보류한다.
- 2×2 위 2×3의 기존 사람 지지 준비/해제 안내를 재사용한다. blue2×3 슬롯3의 원래 T2 교시는 원래 타깃으로 정상 로드한 뒤 기존 실측 판/층 모델 차이만큼 전달한다. 원본 교시 타깃 검사를 약화하지 않으며 새 층 경로는 실물 미검증이다. 계획·설정/소스 해시를 고정하고 같은 plan의 재실행을 차단한다. native 실패 뒤 STOP도 실패하면 최초 원인과 STOP 오류를 별도 보존한다.
- 이전 저장 INITIAL e74246df의 실제 YOLO/세 View 오프라인 재생에서 입력 영상 수신은 정상이며 V0 확인4개/D1·D3 확인0개를 재현했다. 미확인 형상·가림과 초기 전체 층 영역 증거 부족이 남는다. 빈 판 성공으로 간주하거나 기존 실패 관측을 재사용하지 않는다. B 인식 코드는 이 시험 추가에서 변경하지 않았다.
- 실행·확인 순서는 상위 `STACK_FIVE.ko.txt`를 따른다. 이번 작업의 실제 로봇/그리퍼/STOP/카메라 연결은0이며 실물5층 성공·B 최종 판정은 미검증이다.
- 변경 후5층/기존 B3-Step 통합37 passed, native 가압·결착·키 조작·3Step 관련139 passed(합계176)를 확인했다. 정상5STEP/FINAL 및 실패 보류, 전체20슬롯·층1~5 설정, 60N 미도달/최대 이동 정상 종료 허용, P 생략/중단 차단, 최초 오류 보존을 장치 fixture로 검증했다. 새 preview의5개 설정/소스 해시 검증·Python AST·shell 구문도 통과했다. 원시 로그는 상위 `evidence/initial-fix-20261015/stack-five-tests-current.log`, `stack-five-native-tests.log`다.

### 이후 요청: 이번 5층 시험의 B 실패 작업자 체크박스

- `--operator-b-review`에서만 INITIAL의 기존 범위 미확인 실패와 층별 B 실패를 기록 후 체크박스로 진행할 수 있다. 해제된 체크·비활성 계속 버튼으로 시작하며 취소/창 닫기는 보류한다. 건별 재확인이고 자동 통과/재실행은 없다. 원래 INITIAL/STEP 응답·실패 파일을 수정하지 않는다.
- INITIAL 실패 시 실제 정지/writer 해제 확인 후 작업자가 빈 판을 확인하면 기존 검토 HOME 경로로 복귀한다. 초기 비교 기준의 출처는 `OPERATOR_VISUAL_EMPTY_BOARD_TEST_ONLY`이며 INITIAL의 B Current=null/HOLD를 유지한다. 실제 B STEP이 생성한 Current만 결과 Current에 채택한다.
- 층별 예외는 로봇 정지·HOME·writer 해제가 확인된 B 결과에만 적용한다. 작업자가 확인한 시험 진행 prefix와 실제 B Current/비교/확인된 Step 목록을 구분한다. B MATCH를 만들거나 confirmed-Step 집합에 수동 승인 층을 넣지 않는다. native 오류/STOP/HOME/writer/취소/응답 식별 불일치는 체크박스로 넘기지 않는다.
- 실제 STEP MATCH가 누락되면 FINAL 전체 MATCH 요구는 유지하여 FINAL을 실행하지 않고 사유를 기록한다. 수동 확인이 하나라도 있으면 결과는 `FIVE_STEPS_EXECUTED_WITH_OPERATOR_REVIEW`, physical_completion=false이며 B 전체 조립/DB/웹 완료로 표시하지 않는다. 기존 C 승인3-Step 및 B 공통 코드/계약은 변경하지 않았다.
- 변경 후5층/기존 B3-Step 통합54 passed(실제 B 상태/비교, 명시적 장치 fixture)를 확인했다. INITIAL 실패 보존/수동 기준 표시, 층별 MISMATCH/UNOBSERVABLE/ERROR 건별 확인 후5층 진행, 실제 B Current 보존/FINAL 게이트 유지, 체크 초기 해제/버튼 비활성/취소, HOME·정지·writer 실패 차단과 검토 HOME 실제 피드백 요구를 포함한다. 로그는 `evidence/initial-fix-20261015/stack-five-operator-review-tests.log`이며 로봇/그리퍼/STOP/카메라 연결0이다.

### 5층 시험의 기존 HMI 화면 연결

- `bash scripts/round3_stack_five.bash hmi`: 기존 HmiWindow/BoardView/InspectionView를 재사용한5층 시험 화면이다. 전체 목표·실제 B Current·B 예상/차이·현재 목표/관측과 층별 공급/D 실행/B 판정 표를 표시한다. 기존 C 승인3-Step/계정/DB/웹 Job과 분리된 시험이며 그 완료 이력으로 저장하지 않는다.
- HMI 준비 체크/시작→INITIAL→매 층 HMI 실행 확인→기존 관측창 I/O/P/U·지지 안내→HOME→실제 B STEP 순서다. B 실패 체크박스를 HMI 안으로 연결했다. 원래 B 판정/Current를 보존하고 수동 진행 층을 별도 표시하며 FINAL 실제 MATCH 조건을 유지한다.
- 기존 native/CV 실행은 별도 자식 프로세스의 주 스레드에서 유지한다. 식별자가 결합된 요청/응답만 승인하고 EOF/잘못된 응답/취소를 승인으로 해석하지 않는다. HMI의 정지 요청은 기존 SIGINT 경로로 전달하며 프로세스 종료를 실제 정지로 표시하지 않는다. 시작 직후 정지와 늦은 확인 요청을 차단하고 실행 중 창 닫기는 정지 처리 후 닫도록 유지한다.
- HMI를 열거나 새 시험본을 만들 때 같은 seed/선택의 별도 plan을 만들고 장치에 연결하지 않는다. 기존 실행 폴더/기록과 중복 실행 방지를 유지한다. 사용한 CLI plan은 FileExistsError 대신 `PLAN_ALREADY_USED_CREATE_NEW_PREVIEW`로 장치 연결 전에 안내한다. 이전5d36b2a3 시험은 완료0개, 첫 공급 슬롯 관측 후 `SUPPLY_DEPTH_EXPIRED_BEFORE_PICKUP`이며 그 깊이 최신성 기준을 완화하지 않았다.
- 변경 후5층 HMI/프로토콜/실제 B 비교/기존 B3-Step 관련63 passed, 기존 HMI 화면/버튼/실행 표시103 passed(합계166)를 확인했다. 장치 없는 실제 자식 프로세스의 체크/승인 왕복과 실제 run_stack→HMI 정상/수동 흐름을 포함한다. 5행 표시·체크 초기 해제·버튼 비활성·중복 시작·오래된 승인/EOF·B Current 보존·완료 구분을 확인했다.
- 1200×900 대응 화면과 작은 화면의5행 표시를 장치 없이 확인했다. 화면 검증 이미지는 상위 evidence의 `stack-five-hmi-ready.png`, `stack-five-hmi-initial-review.png`이며 저장 실패 결과를 표시한 재생 화면이다. 실제 ROS/로봇/그리퍼/STOP/카메라 연결0·commit/push0이며 실물5층/B 확인 성공은 미검증이다.

### 공급 깊이 집기 전 만료의 처리 지연 수정

- 최신 c6259e1d 시험의 첫 yellow2×3 슬롯4는 인식 성공, 깊이522mm/퍼짐0mm/XY2.237mm/높이6.863mm였다. 검증204.034ms로310ms 이내였지만 결과 화면 갱신과 추가 전체 상태 조회 후 `SUPPLY_DEPTH_EXPIRED_BEFORE_PICKUP`으로 보류됐다. 완료 조립0이며 원본 영상·로그를 보존했다.
- 별도5층 build의 RGB-D 경로에만 `defer_depth_evidence`와 `defer_depth_pose_validation`을 활성화했다. 기존 지연 저장을 사용하고, 실제 수신 RGB/Depth/CameraInfo·선택 슬롯/프레임을 단발 결합한 뒤 집기 함수에서 얻은 한 번의 최신 전체 응답으로 RGB-D와 자세/장치 검사를 함께 완료한다. 촬영 후 검증용 상태 조회는2→1회이며 모션별 상태 조회/정지·TCP/Tool·그리퍼·힘 검사와 실제 촬영 전후 .05 자세 변화 검사는 유지한다. 캐시된 로봇 상태를 재사용하거나 검사 성공을 임의 생성하지 않는다.
- 결과 화면 그리기는 검증 뒤 첫 기존 수직 구간 완료 후 수행한다. 증거 PNG/JSON은 카메라 정리 시 성공/실패 모두 저장한다. 픽업 XYZ·Z/자세·경로·힘·속도·P60·O47과 등록 슬롯/보정 자료, RGB-D310ms/동기50ms/10mm 한계는 바꾸지 않았다. TEACHING_ONLY와 기존3-Step의 기본 실행 순서는 유지한다.
- 계산 전 monotonic 시점을 만료 기준에 고정하여 보정 계산 지연이 유효 시간을 늘리지 않게 했다. 실제 만료/다른 프레임·슬롯/자세변화/동작 중/그리퍼·TCP·힘·오래된 상태 응답은 계속 집기 전에 보류한다. 자동 재촬영/로봇 재실행/카메라 재시작은 추가하지 않았다. `SUPPLY_DEPTH_HANDOFF`에 잔여ms/조회ms/적용 경로를 기록한다.
- 변경 후 공급 RGB-D/집기/3Step native157 passed와5층/HMI/실제 B 계약63 passed(합계220)를 확인했다. 가상 조회114ms·인식16ms·저장20ms·화면180ms 조건에서 기존 경로 만료를 재현하고 수정 경로의 데이터 나이189ms·잔여121ms와 검증용 조회1회를 확인했다. 이 수치는 모의 시간이며 실물 개선 측정이 아니다. 만료/보정계산·로그 지연/프레임 결합/자세·그리퍼·TCP·힘·오래된 피드백의 차단과 모션 상태 조회 유지도 검사했다.
- 원시 로그는 상위 `evidence/initial-fix-20261015/stack-five-depth-latency-native-tests.log`, `stack-five-depth-latency-hmi-tests.log`다. 새 preview의 설정/소스 해시를 사용한다. 기존 HMI는 재시작해야 한다. 장치 연결/로봇·그리퍼·STOP 명령0·commit/push0이며 실제 재집기·5층/B 성공은 별도 현장 확인이다.
