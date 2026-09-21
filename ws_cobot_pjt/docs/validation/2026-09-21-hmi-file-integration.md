# HMI 파일 통합 검증 · 2026-09-21

## 기준과 변경

- 기준 main: be023a9 (PR #39 병합). 브랜치: feat/hmi-snapshot-bundles.
- 테스트 대상: 이 브랜치의 수정 작업 트리. PR은 사용자가 직접 작성한다.
- 환경: macOS, backend 기존 Python 3.12 가상환경, Node 24.16.0, ROS 2 Jazzy conda 환경.
- 공통 타입은 기존 Jazzy 빌드 overlay를 재사용했다. 이번에 ROS 타입/패키지를 새로 빌드하지 않았다.
- 기존 ROS 시험은 LOCALHOST domain 174, 경로 노드와 HTTP 게이트웨이만 사용한다.
- 실제 로봇·그리퍼·공정 노드·힘 제어는 호출하지 않았다.

## 확인 결과

- 최종 백엔드 전체 시험: 67개 통과 (파일 시험 20개와 실제 ROS Action 통합 2개 포함), 13.98초.
- 손상 ZIP 처리 보완 뒤 빌드 완료 상태에서 전체 시험을 재실행했다. skip 없음.
- 프런트엔드 경로 표시 시험: 3개 통과.
- TypeScript/Vite 빌드 통과.
- 브라우저 직접 확인: JSON 등록·UUID/해시 표시, 이미지 첨부·24×24/U0/V105 입력 묶음 준비,
  별도 임시 저장소에서 원본 c2_path로 계산한 결과 ZIP 업로드,
  전개면/원기둥 미리보기·J6_RANGE 미검사·공정 실행 미확인 표시.
- 브라우저 콘솔 error 없음. 기존 화면은 데스크톱 HMI용이며 좁은 창의 가로 스크롤을 유지한다.

## 실패·보존 시험

파일 바이트 변조, 누락/추가/경로 이탈 파일, 다른 preview 참조, 변경된 profile/Goal,
중복 asset ID, Result 필수 필드 누락, 잘못된 ZIP을 거절했다.
기존 ID 충돌 및 DB 삽입 실패를 주입해 신규 파일/DB 등록의 롤백을 확인했다.
동일 결과 재전송은 중복 등록하지 않고 같은 경로를 반환한다.
같은 JSON의 들여쓰기 차이는 같은 프로필로 등록하고, 값 변경은 새 ID/해시를 발급한다.
실행 중 등록 차단, 가져온 경로의 POST runs 차단을 확인했다.

처음 전체 시험에서는 프런트엔드 빌드가 dist/assets를 교체하는 순간과 겹쳐 fixture 1개가 실패했고,
네트워크 제한 환경에서 ROS 서버 탐색 2개가 실패했다.
빌드 완료 후 로컬 ROS 통신이 가능한 환경에서 전체 시험을 다시 실행해 66개가 모두 통과했다.
이 실패를 기능 통과로 계산하지 않았다.

## 재현

[파일 통합 안내](../HMI_FILE_INTEGRATION.md)의 화면·규격을 따른다.
backend 가상환경과 c2_path 계산 의존성이 준비된 상태에서:

```bash
cd ws_cobot_pjt/backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_file_integration.py
```

ROS 전체 시험은 [경로 통합 안내](../HMI_PATH_INTEGRATION.md#재현-시험)대로
Jazzy 및 기존 c2_interfaces/c2_path overlay를 source하고 C2_RUN_ROS_TESTS=1로 실행한다.
프런트엔드 빌드와 backend fixture 생성은 동시에 실행하지 않는다.

## 한계와 후속

- 공통 스냅샷의 공정 필드는 형식 합의 전이다. 등록은 JSON 값 보관이며 의미 검증이 아니다.
- 현재 가져오기는 PR #38/39의 canonical path/preview 계약을 검사한다.
- 파일 교환용 선택이 실행 중인 ROS/MOCK 기본 프로필을 바꾸지는 않는다.
- 공정팀 로더 → 관절 검사 → 한 획 모의 실행 및 준비·측정 API는 이번에 구현·시험하지 않았다.
- 전원 차단 시 파일시스템과 SQLite의 완전한 원자성까지 보장하지 않는다.
  DB 트랜잭션 실패 시 롤백은 시험했으며 충돌 파일은 덮어쓰지 않는다.
