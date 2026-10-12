# X-AnyLabeling 서플라이 윗면 OBB 작업

Roboflow 작업 중단·X-AnyLabeling 수동 OBB 작성으로 전환한다. 기존 사진/라벨은 보존한다.
images/는 원본 RGB의 작업 복사본이며 image_sources.json에 출처가 있다.
classes.txt의 다섯 클래스 순서를 학습/내보내기에도 유지한다.
annotations/에 검수한 라벨을 저장한다. 현재 라벨은 생성하지 않았다.

공식 배포: https://github.com/CVHub520/X-AnyLabeling/releases/tag/v4.1.0
Linux CPU 실행 파일을 사용할 수 있다. 다운로드 승인 거절로 아직 설치/실행하지 않았다.

설치 후 Open Dir로 images/를 열고 출력 라벨 폴더를 annotations/로 지정한다.
회전 사각형 도구(공식 단축키 O)로 박스를 그리고 회전 손잡이와 크기/위치를 조절한다.
옆면 제외·윗면만 감싸며 클래스를 선택하고 저장한다. 불명확한 사진은 검수 보류한다.
기본 자동 모델이 우리 다섯 클래스/윗면을 구분한다고 가정하지 않는다.
우선 수동 라벨 → 검수 → 별도 촬영 세션의 학습/검증 분리 → YOLO OBB 학습으로 진행한다.
YOLO OBB 내보내기 후 파일 형식·클래스 순서·회전/중심을 확인해야 한다.
현재 공급 실행기는 일반 Detection용이며 OBB 모델 연결은 아직 수정/검증하지 않았다.

공식 사용 설명: https://github.com/CVHub520/X-AnyLabeling/blob/main/docs/en/user_guide.md
