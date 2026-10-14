# 공급 stud 배열 검출 채택

2026-10-14 사용자 요청: 비교 결과로 검출 코드를 채택하고, 미검출 대상은 기존 좌표로 파지한다.

공급 `supply_pick_release_trial.py`에 `vision.backend=opencv_studs` 경로를 추가했다.
기본 supply_sequence_20261014/config.json에서 채택한다. 별도 held/assembly 설정은 변경하지 않는다.
카메라 토픽은 기존 `/camera/color/image_raw` 그대로다. 모델 로딩 없이 색상 외곽 안에서
CLAHE-V로 전체 stud 배열을 확인하고 실패하면 baseline을 검사한다. Black-hat은 채택하지 않는다.
코드는 robot_control_integration/app/supply_stud 안에 들어 있어 외부 실험 폴더 의존이 없다.

요청의 color/brick_type/slot으로 기존 layout의 단일 ROI를 선택한다.
사진 비교의 S1~S5는 종류 행이고 실제 slot은 종류별 오른쪽부터 1~5라는 차이를 유지한다.
배열 실패/색 외곽 실패에는 center_uv=null을 반환한다. 기존 center_target이 해당 요청의
pickup_pose 복사본으로 파지 위치를 선택한다. Z/ABC/그립 폭/경로/힘 제한은 기존 값을 유지한다.
설정 오류나 ROI 크기 불일치 등은 예외로 중단하며 미검출로 숨기지 않는다.

검출 성공도 픽셀 좌표를 바로 로봇 좌표로 사용하지 않는다. independently_verified=true와
center_basis=STUD_ARRAY를 가진 등록된 center_mapping만 기존 제한 내 XY 보정에 사용한다.
현재 설정에는 이 mapping이 없어 검출 성공/실패 모두 기존 교시 좌표로 파지한다.
검출은 팝업과 기록에 남는다. 기존 bbox 기준 mapping은 stud 기준으로 자동 재사용하지 않는다.

실행 전 preview:

```bash
python3 robot_control_integration/scripts/supply_pick_release_trial.py preview
```

기존 run 명령과 실행/손 비움 옵션은 그대로 유지한다. 이번 작업에서 실제 파지 실행은 하지 않았다.
새 분기의 미검출 좌표 유지, stud mapping 기준 검사, 설정 오류 중단과 기존 공급/파지/held 회귀를 검증했다.
저장한 20프레임에서 실제 공급 요청 5종을 재생해 분기와 교시 좌표 선택을 확인했다.
검출률은 배열 후보 확인 비율이며 실제 stud 정답/파지 성공/metric 보정 정확도를 뜻하지 않는다.
