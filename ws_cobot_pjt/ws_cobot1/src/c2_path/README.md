# c2_path · 좌표·경로 생성 개발 위치

개발 폴더만 준비된 상태다. `path_planner_node` 하나가 내부 계산 모듈을 호출하는 구조로 구현한다. 파일별 역할은 [목표 구조](../../../docs/SYSTEM_STRUCTURE.md), 입력·출력은 [GeneratePath 계약](../../../docs/INTERFACE_RECOMMENDATION.md)을 따른다.

| 구현 위치 | 담당 기능 |
| --- | --- |
| `c2_path/node.py` | GeneratePath Action 수신, 진행·결과·취소 처리 |
| `c2_path/image_to_svg.py` | 입력 이미지 정규화·SVG 변환 |
| `c2_path/extract_2d.py` | SVG의 2D 좌표 추출 |
| `c2_path/optimize_2d.py` | 좌표·작업선 순서 최적화 |
| `c2_path/map_3d.py` | 대상 표면 매핑·고정 좌표 변환 |
| `c2_path/generate_path.py` | 공구 자세·접근·가공·이탈 경로 생성 |
| `c2_path/validate_path.py` | 실행 경로 검증 |

구현 시 `package.xml`·`setup.py`·`setup.cfg`, `c2_path/__init__.py`, `resource/c2_path`와 실제 모듈을 작성한다. 아직 이 파일들은 없으며 `resource/.gitkeep`은 ROS 패키지 등록 파일을 대신하지 않는다.

이 노드에서 로봇을 움직이지 않는다. 도안 크기·고정 변환·도구 설정 스냅샷을 이용해 경로와 미리보기를 만들고 동일한 ID·버전·해시로 반환한다. 필수 검증이 구현되지 않았으면 검증 통과로 보고하지 않는다.
