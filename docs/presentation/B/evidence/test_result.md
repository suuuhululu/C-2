# B 발표 초안 근거 — 코드 검사 기록

- 실행일: 2026-10-11 (Asia/Seoul)
- 저장소: /home/roh/C-2
- 브랜치: work/hongdong-vision-round1
- 소스 HEAD: 8f75e5a15bfc0fd51b56f83e60d73ea7eab76f6d
- 검사 전 git status는 clean. 검사 중 발표 Markdown만 추가. 코드·설정 변경 없음.
- 수준: 장치 없는 B 단위/계약 검사, 로컬 실제 소비자 검증 함수 대조 포함. Camera·Controller·실제 Qt 실행기·DB 서버·팀 전체 동작 시험 아님.

## 실제 실행 명령

```bash
env PYTHONDONTWRITEBYTECODE=1 \
QT_QPA_PLATFORM=offscreen \
PYTHONPATH=.:perception:perception/legacy \
B_ROUND1_CONSUMER_PATH=/home/roh/C-2/history/final_mvp.py \
B_ROUND1_HMI_CONSUMER_PATH=/home/roh/C-2/app/hmi_mvp_contracts.py \
python3 -m pytest -p no:cacheprovider \
  perception/perception_mvp/tests perception/legacy/tests \
  perception/calibration/tests perception/supply_vision/tests -q
```

## 결과

도구가 반환한 실행 stdout의 최종 줄을 옮긴 기록이며 원시 로그 파일을 보존한 것으로 표시하지 않는다.

```text
247 passed in 13.48s
```

프로세스 종료 코드 0. 실패·오류·skip 없음. 전체 저장소 시험은 이번에 실행하지 않았다. 과거 246 passed/1 skipped는 소비자 경로 미설정의 별도 실행이며 이번 수치와 합산하지 않는다.

모델 실제 데이터 정확도·실시간 FPS·5층 판별·안전 정지·물리 결착·DB 적재 성공을 이 검사로 입증하지 않는다.
