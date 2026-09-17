# 기술 참고 자료와 확인 범위

상위 협동1 프로젝트의 `local_file/AGENT.md`를 기본 참고 체계로 삼았다. 이 파일은 clone만 받은 팀원도 자료를 찾을 수 있도록 원문 링크를 옮긴 것이다. 링크가 있다고 전체 문서나 실제 장비를 검증한 것은 아니다.

| ID | 원문 | 사용할 때 |
| --- | --- | --- |
| R1 | [V2 매뉴얼](https://v2-manual.scroll.site) | 대상 제품·문서 버전을 확인하고 조작·DRL 절을 읽는다. |
| R2 | [DRFL GL013301](https://doosanrobotics.github.io/doosan-robotics-api-manual/GL013301/index.html) | DRFL API·연결·권한·오류. 설치 라이브러리·제어기 호환성을 별도로 확인한다. |
| R3 | [두산 협동로봇 교육 영상](https://www.youtube.com/playlist?list=PLEkBnBwQmnmvCREKyRleWnG8WwsANLuY-) | 개별 영상을 실제로 본 경우 제목·링크·시각을 기록한다. |
| R4 | [OnRobot 공식 사이트](https://onrobot.com/en) | 실제 그리퍼 모델 확인 후 해당 제품 문서를 선택한다. |
| R5 | [Jazzy Motion Services](https://doosanrobotics.github.io/doosan-robotics-ros-manual/jazzy/services/motion_services.html#movejoint) | ROS 2 요청·응답·단위·완료 확인을 설치 인터페이스와 대조한다. |
| R6 | [공식 doosan-robot2 Jazzy](https://github.com/DoosanRobotics/doosan-robot2/tree/jazzy) | 설치·빌드·패키지·소스 정의. 기본 브랜치와 혼동하지 않는다. |

## 이 대화에서 확인한 범위

- 2026-09-14: 노션 강의 본문·평가기준·7/8/9/10차시 공지를 열람했다. [강의 링크](https://app.notion.com/p/1-389478936edf8075a4e6c218d6cebded).
- 2026-09-14: R1의 [DRL 2.12.1 movej 본문](https://v2-manual.scroll.site/ko/v2-programming-manual/2.12.1/publish/movej), R5 Motion Services, R6 Jazzy README를 열람했다. 전체 매뉴얼 검토는 아니다.
- 2026-09-15: 상위 로컬 `doosan/`의 브랜치 `jazzy`와 커밋 `8e033f0e2284be0a25b655266e02878ebc915c50`을 확인했다. 빌드·모션 호출은 하지 않았다.
- 지정 R2 인덱스 본문은 앞선 조회에서 확보하지 못했다. 개별 API를 사용할 때 해당 절을 다시 확인한다.
- R3 개별 영상·타임스탬프는 미확인이다.
- 노션의 RG2 참고자료만으로 실제 장착 그리퍼를 RG2로 확정하지 않는다.
- 로컬 초급교육 PDF는 상위 프로젝트에 있지만 이 작업에서 내용을 읽거나 저장소에 복사하지 않았다. 교육 자료의 공개 가능 범위를 확인한 뒤 필요한 링크·요약을 관리한다.

2026-09-16에는 사용자 제공 강사 구조, 로컬 doosan Jazzy README·동일 커밋과 ROS Jazzy 워크스페이스 공식 원문을 확인했다. 공급자 소스는 설치하지 않았다. [의존성 기록](DEPENDENCIES.md)에 확인 범위를 구분했다.

2026-09-17 진행 상황 점검에서는 C-2의 PR #1·#3 승인·병합, Issue #2 종료·봇 댓글, Actions 실행과 main 보호 규칙을 원격 조회했다. [진행 현황](REVIEW_STATUS.md)에 근거를 연결했다. 환경 기록은 9/16 사용자 보고와 [이시율의 Issue 댓글](https://github.com/suuuhululu/C-2/issues/2#issuecomment-5691159901)을 바탕으로 정리했으며, 이번에 제조사 문서·교육 공지를 다시 전부 읽거나 장비를 실행한 것은 아니다.

## 기술 기록 규칙

2026-09-17 음각 서비스 문서화에는 사용자 대화, 개인 작업 폴더의 이전 오프라인 검증 기록, 두산 공식 DRL·모션·힘 서비스 및 ROS 공식 Jazzy 설치·RViz 문서를 반영했다. [시스템 아키텍처](../ws_cobot_pjt/docs/SYSTEM_ARCHITECTURE.md)와 [알고리즘 검증 보고서](../ws_cobot_pjt/docs/ALGORITHM_VALIDATION.md)에 직접 근거와 검증 한계를 연결했다. 이번 GitHub 게시 작업은 기록 정리이며 실기나 알고리즘 성능 시험을 새로 수행한 것은 아니다.

2026-09-17 추가 일지 작업에서는 [팀 Notion](https://app.notion.com/p/1-M0609-3de52118113980728852e200d8b9610a)에서 평면 1차 검증·하드웨어 메모·시율의 사전 작업 자동화·홍동/수현 보고서·세은의 2D→3D 변환 본문을 읽었다. 구체 출처와 본문·코드·첨부 존재·사용자 보고의 확인 범위는 [0917 일지](../ws_cobot_pjt/docs/daily/2026-09-17.md)에 구분했다. 원본 bag·첨부 실행 코드를 재실행하지 않았으며 새 로봇 구동이나 실측을 수행하지 않았다. GitHub의 PR #4 병합·main 커밋·해당 작업 브랜치 CI 성공도 읽기 전용으로 재확인했다.

API를 기록할 때 `제어 계층 / 문서 버전 / 설치본 버전 / 함수·타입 / 단위·좌표계 / 반환·완료 판단 / 원문 절 / 확인 날짜`를 함께 적는다.

예를 들어 ROS 2 `MoveJoint`와 DRL `movej()`의 문법을 서로 복사하지 않는다. Jazzy 서비스 소스 경로는 `dsr_msgs2/srv/MoveJoint.srv`이며 Humble의 이전 경로를 기준으로 안내하지 않는다.

소스와 문서의 버전이 다르면 차이를 기록한다. 로컬 릴리스 표기 DRFL 1.33.4와 지정 문서 GL013301이 완전히 일치한다고 가정하지 않는다.
