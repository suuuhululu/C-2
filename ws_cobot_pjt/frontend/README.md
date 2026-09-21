# 새김 · 운영자 HMI

1920×1080 모니터·마우스·키보드용 **React 19 + TypeScript + Vite** 화면이다. 고객용 웹앱은 현재 진입점에서 사용하지 않는다. 브라우저에서 실행하지만 역할은 작업자 관제 HMI다.

## 실행

Node.js 22 이상, pnpm 11을 준비한다.

```bash
cd ws_cobot_pjt/frontend
pnpm install --frozen-lockfile
```

저장소 루트에서 `python3 ws_cobot_pjt/run_monitor.py`를 실행하고 http://127.0.0.1:5174/operator 를 연다. 기본은 MOCK이다.
실제 이미지 경로 노드는 `--transport ros`로 연결한다. 서버 설치는 [서버 README](../backend/README.md), ROS 환경은
[한 PC 통합 안내](../docs/HMI_PATH_INTEGRATION.md)를 따른다. 두 모드 모두 로컬 SIMULATION 환경이다.

화면만 개발할 때 `pnpm dev`를 사용한다. Vite 5174의 `/api/operator` HTTP·WebSocket 요청을 8010으로 전달한다. 실제 로봇 브링업은 수행하지 않는다.

```bash
pnpm build
pnpm exec prettier --check 'src/monitor/*.{ts,tsx,css}' src/main.tsx vite.config.ts
```

빌드 뒤 서버를 실행하면 http://127.0.0.1:8010/operator 에서 정적 화면과 API를 함께 제공한다. `pnpm preview`에는 API 프록시가 없으므로 전체 기능 확인은 위 주소를 사용한다.

## 사용 순서

**파일 통합 시험**에서는 SIM 스냅샷 등록·선택 → 입력 ZIP 전달 → 결과 ZIP 가져오기 →
전개면/원기둥 미리보기 → 공정팀 전달 ZIP을 사용할 수 있다.
파일 교환용 선택은 아래 ROS/MOCK 기본 생성 설정과 별도이며, 공통 공정 필드의 승인으로 취급하지 않는다.
[파일 형식·담당별 후속 작업](../docs/HMI_FILE_INTEGRATION.md)을 확인한다.

1. **작업 준비**에서 PNG/JPEG 첨부 또는 ‘샘플로 둘러보기’.
2. 가로·세로·중심 U/V·회전 입력. 전개면에서 마우스로 위치를 바꿀 수도 있다.
3. **경로 생성**. 전개면과 원기둥의 동일 경로를 확인한다. 원기둥 드래그는 관찰 방향만 바꾼다.
4. 두 확인 항목을 체크한 뒤 **시작 요청**. 모의 공정의 단계·진행률·이벤트를 확인한다.
5. 공정 관제에서 구간별 예정(검정)·진행(황색)·확인(초록)·실패(빨강)·미확인(회색 점선)을 확인한다. 현재 판정은 모의 데이터다. 필요하면 상단 **정지 요청**. 접수와 정지 확인을 구분해 표시한다.
6. **실행 이력 → 상세·검사**에서 판정과 근거를 저장한다.
7. **설정 정보**에서 실패·통신 단절 시나리오를 선택한다. ‘모의 상태 초기화’는 가짜 현재 상태만 초기화하고 기록을 보존한다.

위 4~7번의 공정 실행·시나리오 선택은 MOCK 전용이다. MOCK은 첨부 이미지를 보관하고 고정 식물 중심선 샘플을 반환한다.
ROS 모드는 PR #38의 `raster_centerline_bezier`로 첨부 이미지를 실제 변환하며 `c2-path-preview/1`의
분리 구간과 profile 원점을 반영한다. 가로·세로는 비율 유지 맞춤 상자이며 편집 중 그림은 참고 표시다.
초기 24×24 mm/U0/V107.5로 생성해 미리보기를 확인한다. 경로 노드 연결과 공정 상태 수신은 별개로 표시한다.
현재 ROS 경로는 test_only라 시작을 차단하고 J6_RANGE 미검사를 표시한다. 실패 보고서·SVG는 진단용이며
실행 경로가 아니다. 입력 변경 시 이전 결과를 구분하고 실행 확인을 해제한다.

좌표 표시·구간 분리 시험(Node 24에서 확인): `node --experimental-strip-types --test tests/preview.test.mjs`.

## 소스

- `src/main.tsx`: 새 모니터 진입점
- `src/monitor/Monitor.tsx`: 작업 준비·관제·이력·알람·설정
- `src/monitor/FileIntegration.tsx`: SIM 스냅샷·입력/결과 ZIP·등록 결과 미리보기
- `src/monitor/LivePathPreview.tsx`: 실시간 경로·모의 가공 판정 표시
- `src/monitor/Previews.tsx`: U/V 전개면과 3D 점의 원기둥 투영
- `src/monitor/preview.ts`: 실제/모의 preview 선택·원통 표시 좌표 변환(경로 파일 변경 없음)
- `src/monitor/api.ts`: HTTP 타입·요청·오류 구분
- `src/monitor/monitor.css`: 목업 기반 녹색·오프화이트 디자인
- `public/samples/monitor_centerline.png`: 직접 작성한 모의 중심선 샘플

외부 폰트·도자기 사진·외부 미디어를 불러오지 않는다. 시스템 한글 폰트를 사용한다. 작은 화면에서는 스크롤을 허용하며 모바일 앱으로 설계하지 않았다.

이전 고객 웹앱 초안은 개발 PC에 별도로 보존했다. 이 게시본의 진입점은 `src/monitor/Monitor.tsx`이며 고객용 화면은 포함하지 않는다. [DB·게이트웨이·미확정 계약](../docs/HMI_MONITOR_IMPLEMENTATION.md).
