# 첫 REAL 통합 완료 기록·오프라인 단위시험 샘플

2026-09-23 실제 M0609에서 운영자가 실행한 측정→BIND→경로 생성→별도 실행→PRECHECK→ENTRY→ENGRAVE→FINISH 기록이다.
**전 과정 완료 사례이며 조각 형상·접촉 품질 합격 사례가 아니다.** 사진의 도면 차이는 미해결이다.

## 파일과 연결

| 파일 | 내용 |
| --- | --- |
| measurement.json | PrepareWorkpiece 원본 Result, 윗면+옆면 8점 |
| input-config.json | 해당 측정이 사용한 설정 스냅샷 |
| preparation.json | HMI 측정·BIND 완료 기록 |
| profile.json | BIND한 실측 실행 스냅샷 |
| path.json | 실제 실행한 55구간 경로 |
| generation.json | 경로 생성 성공 결과 |
| run.json | 시작·종료 시각과 최종 실행 상태 |
| events.json | 해당 run의 단계 이벤트 |
| execution-result.json | 공정 SQLite 원장의 최종 Result |
| engraved-result.png | 운영자가 제공한 실제 조각 결과 사진 |
| manifest.json | 위 파일 SHA-256 및 원본 자산 ID 연결 |

원본 자산은 바이트와 해시를 보존했다. 사진은 해당 실기 결과를 육안 비교하는 자료이며 치수 측정 근거가 아니다.
샘플의 REAL·실행 가능 플래그는 원본 보존을 위한 값이다. **실행 Action 입력으로 재전송하는 예제가 아니다.**
개인 DB·ROS 설치본 없이 아래 순수 계산 단위시험에 사용한다.

## 로봇 없는 단위시험

저장소 루트에서 Python 3.12와 프로젝트 개발 의존성(pytest 포함)을 준비한 뒤:

```bash
python3 -m pytest ws_cobot_pjt/ws_cobot1/src/c2_process/test/test_real_integration_sample.py -q
python3 -m pytest ws_cobot_pjt/ws_cobot1/src/c2_process/test/test_engraving_workspace.py -q
```

첫 시험은 파일 해시·측정/경로 연결·프로파일 계약·조각 Z 하한·선택 ENTRY 후보의 단순 형상을 검사한다.
장치 연결, ROS 초기화, IK 서비스, 모션 호출을 하지 않는다. 현재 현장의 실행 가능성이나 재현 품질을 판정하지 않는다.
두 번째 시험은 0.05 m 경계, 미만 거부, 모든 구간 및 ENTRY 중간점, TCP와 도구 끝 구분, 측정 박스 분리, 양초 간격 유지 사례다.

## 시간·결과

- run: `a7505b65-d863-4b17-a514-1fad63249380`
- preparation: `3ea29d78-6a71-4c0c-b8f8-fa00a206a019`
- measurement: `002d8cfb-296b-46be-a60c-ae91190d0e7e`
- path: `047c5fe4-0d3f-4684-9fb5-5665c710635e`, v1
- 16:30:01 KST 요청, 16:33:41 ENTRY, 16:33:50 ENGRAVE, 16:41:53 FINISH.
- 요청부터 종료까지 약 712.2초. PRECHECK 약 219.7초. 경로 재생 내부 타이머 약 460.3초.
- 최종 `SUCCEEDED / NONE`, `seg-0055`, 진행률 1.0.
- `contact_verified=false`, `engraving_quality_verified=false`는 그대로 보존.
- 중심 [0.4233923696696419, 0.00031013526838899696] m, 반지름 0.03386009976984811 m, 윗면 0.21575921630919023 m.
- 측정 FIT RMS 약 112.3 µm, 최대 잔차 약 162.5 µm. 독립 정확도 검증이 아니다.

## 한계와 후속 점검

- 운영자 육안 관찰: 그리퍼 회전에 드릴 끝이 뒤따르지 않는 느낌, 도면과 조각의 차이. 고정 유격·도구 오프셋·TCP 보간·접촉 깊이 원인을 아직 구분하지 못했다.
- 고정 상태 확인 후 도구 끝 보정과 원본 이미지→경로→실행 TCP 변환을 비교한다. 철사 고정 중 그리퍼를 열지 않는다.
- HMI 구간별 색상 표시가 갱신되지 않았다는 보고가 있다. PRECHECK 후보별 중간 로그가 없어 진행 관측이 부족하다.
- 완료 후 ProcessState.elapsed_s가 계속 증가하는 현상이 있어 시험 시간은 run.json의 종료 시각과 종료 기록으로 산정했다.
- 이번 사례로 반복 재현성·형상 품질·힘 감시·정지 시험을 완료했다고 판단하지 않는다.
- 새 코드 적용을 위해 공정 노드를 재기동하면 메모리 준비 기록을 다시 확보해야 한다. 새 측정·새 경로를 사용한다.
