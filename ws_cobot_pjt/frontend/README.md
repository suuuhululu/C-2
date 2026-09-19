# 새김 · 운영자 HMI

1920×1080 모니터·마우스·키보드용 **React 19 + TypeScript + Vite** 화면이다. 고객용 웹앱은 현재 진입점에서 사용하지 않는다. 브라우저에서 실행하지만 역할은 작업자 관제 HMI다.

## 실행

Node.js 22 이상, pnpm 11을 준비한다.

```bash
cd ws_cobot_pjt/frontend
pnpm install --frozen-lockfile
```

저장소 루트에서 `python3 ws_cobot_pjt/run_monitor.py`를 실행하고 http://127.0.0.1:5174/operator 를 연다. 서버 설치는 [서버 README](../backend/README.md)를 따른다. 접근 키 없이 로컬 모의 환경에서 사용한다.

화면만 개발할 때 `pnpm dev`를 사용한다. Vite 5174의 `/api/operator` HTTP·WebSocket 요청을 8010으로 전달한다. 실제 로봇 브링업은 수행하지 않는다.

```bash
pnpm build
pnpm exec prettier --check 'src/monitor/*.{ts,tsx,css}' src/main.tsx vite.config.ts
```

빌드 뒤 서버를 실행하면 http://127.0.0.1:8010/operator 에서 정적 화면과 API를 함께 제공한다. `pnpm preview`에는 API 프록시가 없으므로 전체 기능 확인은 위 주소를 사용한다.

## 사용 순서

1. **작업 준비**에서 PNG/JPEG 첨부 또는 ‘샘플로 둘러보기’.
2. 가로·세로·중심 U/V·회전 입력. 전개면에서 마우스로 위치를 바꿀 수도 있다.
3. **경로 생성**. 전개면과 원기둥의 동일 경로를 확인한다. 원기둥 드래그는 관찰 방향만 바꾼다.
4. 두 확인 항목을 체크한 뒤 **시작 요청**. 모의 공정의 단계·진행률·이벤트를 확인한다.
5. 공정 관제에서 구간별 예정(검정)·진행(황색)·확인(초록)·실패(빨강)·미확인(회색 점선)을 확인한다. 현재 판정은 모의 데이터다. 필요하면 상단 **정지 요청**. 접수와 정지 확인을 구분해 표시한다.
6. **실행 이력 → 상세·검사**에서 판정과 근거를 저장한다.
7. **설정 정보**에서 실패·통신 단절 시나리오를 선택한다. ‘모의 상태 초기화’는 가짜 현재 상태만 초기화하고 기록을 보존한다.

첨부 이미지는 보관되지만 **실제 SVG로 변환하지 않는다**. 모의 상대가 고정 식물 중심선 샘플을 반환한다. 실제 변환은 좌표 노드 연동 후 제공한다. 실패 진단 그림은 실행할 수 없다. 입력 변경 시 이전 결과를 구분하고 실행 확인을 해제한다.

## 소스

- `src/main.tsx`: 새 모니터 진입점
- `src/monitor/Monitor.tsx`: 작업 준비·관제·이력·알람·설정
- `src/monitor/LivePathPreview.tsx`: 실시간 경로·모의 가공 판정 표시
- `src/monitor/Previews.tsx`: U/V 전개면과 3D 점의 원기둥 투영
- `src/monitor/api.ts`: HTTP 타입·요청·오류 구분
- `src/monitor/monitor.css`: 목업 기반 녹색·오프화이트 디자인
- `public/samples/monitor_centerline.png`: 직접 작성한 모의 중심선 샘플

외부 폰트·도자기 사진·외부 미디어를 불러오지 않는다. 시스템 한글 폰트를 사용한다. 작은 화면에서는 스크롤을 허용하며 모바일 앱으로 설계하지 않았다.

이전 고객 웹앱 초안은 개발 PC에 별도로 보존했다. 이 게시본의 진입점은 `src/monitor/Monitor.tsx`이며 고객용 화면은 포함하지 않는다. [DB·게이트웨이·미확정 계약](../docs/HMI_MONITOR_IMPLEMENTATION.md).
