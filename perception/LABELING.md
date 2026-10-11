# 실제 RGB 라벨 작성부터 YOLO Segmentation 학습까지

라벨링 도구는 기존 OpenCV를 사용하는 `perception_mvp.labeling`입니다. LabelImg/Labelme 설치나
새 dependency 없이 직접 polygon을 작성합니다. 모델이 라벨을 추측하거나 검수 완료를 자동 지정하지 않습니다.

## 1. 실제 촬영 RGB 정리

```bash
cd /home/roh/C-2/perception
python3 -m perception_mvp.labeling prepare --source recordings/assembly_01
```

촬영한 조립 과정 전체 폴더를 source로 지정합니다. step/View 하나를 source로 지정하지 않습니다.
labeling/images에 고유 파일명으로 RGB만 복사하고 provenance.json에 원본 RGB-D 경로·과정·View·
촬영 시각·SHA-256을 기록합니다. 원본은 이동/수정하지 않습니다. 같은 명령을 다시 실행하면
이전에 정리한 자료는 확인 후 유지하고 신규 촬영만 추가합니다. 기존 라벨은 덮어쓰지 않습니다.
다른 조립 과정도 같은 workspace에 추가하되 실제 source 경로를 지정합니다.
board_calibration은 보정 자료이며 기본 학습 수집 대상에 넣지 않습니다.

## 2. 수동 라벨 작성

```bash
cd /home/roh/C-2/perception
python3 -m perception_mvp.labeling annotate
```

원본 종횡비를 유지해 이미지를 표시하며 클릭 좌표는 원본 해상도로 복원합니다.

| 조작 | 기능 |
|---|---|
| 0 | yellow_2x2 선택 |
| 1 | yellow_2x3 선택 |
| 2 | blue_2x2 선택 |
| 3 | blue_2x3 선택 |
| 왼쪽 클릭 | 블록 경계의 꼭짓점 추가 |
| 오른쪽 클릭 | 아직 작성 중인 마지막 꼭짓점 취소 |
| Enter | polygon 확정. 같은 색 접촉 블록도 하나씩 별도 작성 |
| U | 작성 중 꼭짓점 취소. 작성 중이 아니면 마지막 polygon 삭제 |
| S | 보이는 모든 블록을 검수했다는 확인으로 JSON 저장하고 다음 이미지 |
| E | 실제 빈 보드임을 사람이 확인했을 때 빈 라벨 저장. polygon이 있으면 거절 |
| P | 이전 이미지. 현재 미저장 변경은 취소 |
| Q / 창 닫기 | 종료. 미저장 변경은 저장하지 않음 |

보드는 라벨링하지 않습니다. 가려진 경계는 추측하지 않고 보이는 영역만 그립니다.
부분적으로 가려진 같은 물리 블록의 분리된 영역/group 처리는 이 최소 도구에서 지원하지 않으며,
여러 블록으로 임의 분할하지 마세요. 지원되지 않는 장면은 별도 검토해야 합니다.
잘못된 클래스·영역 밖/교차 polygon은 거절합니다. 선택한 클래스는 Enter 시 적용되므로 먼저 선택하세요.
S는 모든 보이는 블록 mask/클래스를 직접 확인한 뒤 누릅니다. 미완성·품질 불가 이미지를 E로 넘기지 마세요.
Q로 종료한 뒤 문제 사진을 수집 원본에서 삭제하지 말고 별도 선별 workspace를 준비하세요.
annotations JSON의 reviewed/empty_confirmed는 사람이 S/E로 확인한 결과입니다.

## 3. 조립 과정 단위 분리·YOLO 변환

학습 과정과 검증 과정이 각각 필요합니다. 같은 조립의 단계/세 View는 통째로 같은 split에 둡니다.
예를 들어 실제 assembly_01을 학습, 별도로 촬영한 assembly_02를 검증으로 선택했다면:

```bash
python3 -m perception_mvp.labeling prepare --source recordings/assembly_01 recordings/assembly_02
python3 -m perception_mvp.labeling annotate
python3 -m perception_mvp.labeling export --val-scenes recordings/assembly_02 --output datasets/blocks_v1
```

assembly_02는 이름 설명이며 실제 촬영 전에는 생성하지 않습니다. 한 조립 과정밖에 없다면
train/val 분리를 거절합니다. 사진 무작위 분리나 같은 사진 복사로 검증 데이터를 만들지 않습니다.
모든 사진의 실제 검수 JSON이 있어야 변환합니다. 기존 export 폴더는 덮어쓰지 않습니다.
export는 polygon 픽셀을 정규화해 클래스+polygon 좌표의 YOLO TXT로 저장하고,
dataset.yaml/scenes.json을 생성한 뒤 기존 check_labels를 실행합니다.

## 4. 기존 검사·학습 연결

```bash
python3 -m perception_mvp.main check-labels --dataset datasets/blocks_v1/dataset.yaml --scene-manifest datasets/blocks_v1/scenes.json
```

학습은 같은 dataset.yaml/scenes.json을 기존 main train에 전달하며 --device cpu를 사용합니다.
추가로 로컬 segmentation 초기 .pt 모델·imgsz·epochs·batch·새 결과 경로를 명시해야 합니다.
모델은 제공되지 않았으므로 임의 다운로드/학습 실행/성능 보장을 하지 않습니다.
train은 네 클래스의 실제 train instance가 모두 있어야 진행합니다. 검사 통과는 사람 mask 정확도나 모델 성능 보장이 아닙니다.

labeling/과 datasets/는 로컬 작업 산출물로 Git에서 제외합니다. RGB-D 캡처·Board 보정·Observed 계약은 변경하지 않습니다.
