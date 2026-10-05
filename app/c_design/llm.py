"""LLM API 호출 전용.

목적:
    C 파트에서 외부 LLM provider와 통신하는 유일한 지점.

향후 들어갈 기능:
    - 실제 LLM API 호출(개발 8단계)
    - 구조화(JSON) 응답 수신·파싱
    - 호출·파싱 실패는 예외로 알림(재시도는 designer.py 담당)
    - API key는 환경 변수에서 읽고 저장소에 기록하지 않는다.

하지 않는 것:
    - 프롬프트 내용 구성, Design 검증, 재시도 정책
    - Robot joint / TCP / 속도 / 힘 / trajectory 값 생성
    - import 시 API 호출·secret loading·네트워크 요청

연결:
    designer.py 와 dialogue.py(애매한 응답 fallback)가 호출한다.
"""
