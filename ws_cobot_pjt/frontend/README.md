# Frontend

화면 소스는 `src/`, 정적 파일은 `public/`에 둔다. 웹 프레임워크는 아직 선택하지 않았으며 package.json과 실행 가능한 웹 앱도 없다.

- 공유: 화면 소스·정적 파일, 선택한 프레임워크의 package.json·잠금 파일, 실행 방법.
- 로컬 전용: node_modules, 빌드 결과, `.env`의 실제 값.
- `node_modules/`는 의존성을 설치할 때 각 PC에서 생성한다. 저장소에 복사하지 않는다.
- ROS 패키지로 구성하는 PyQt HMI는 `../ws_cobot1/src/`에 두고 이 웹 폴더에 중복 구현하지 않는다.
- API·상태·오류 표시의 계약은 [프로젝트 계획](../docs/PROJECT_PLAN.md)에 기록한다.
