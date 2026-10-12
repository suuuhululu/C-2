"""Saved RGB instance-mask evaluation only; no training or device control."""
import json
from pathlib import Path
import cv2
import numpy as np
import torch
from scipy.optimize import linear_sum_assignment
from ultralytics import YOLO

BASE = Path('/home/roh/C-2/perception')
DATA = BASE / 'datasets/blocks_v1_yolo_seg'
MODELS = BASE / 'models/block_v1_six_runs_20261010'
OUT = MODELS / 'mask_iou_evaluation_conf025.json'
torch.set_num_threads(4)
images = sorted((DATA / 'images/valid').glob('*'))
assert len(images) == 25
ground_truth = []
for image in images:
    rgb = cv2.imread(str(image))
    height, width = rgb.shape[:2]
    masks, classes = [], []
    for line in (DATA / 'labels/valid' / (image.stem + '.txt')).read_text().splitlines():
        values = np.array(line.split(), dtype=float)
        points = values[1:].reshape(-1, 2) * [width, height]
        mask = np.zeros((height, width), dtype=np.uint8)
        cv2.fillPoly(mask, [np.rint(points).astype(np.int32)], 1)
        masks.append(mask.astype(bool)); classes.append(int(values[0]))
    ground_truth.append((image, masks, np.array(classes)))
assert sum(len(masks) for _, masks, _ in ground_truth) == 387
report = {'protocol': {'images':25, 'ground_truth_instances':387,
    'device':'cpu', 'imgsz':640, 'confidence':0.25, 'prediction_iou_argument':0.7,
    'retina_masks':True, 'matching':'same-class one-to-one, maximum valid match count then IoU; IoU >= 0.5',
    'matched_mean':'mean mask IoU among matched instances only',
    'gt_mean_with_misses_zero':'sum matched IoU divided by all GT instances; unmatched GT score zero',
    'limitation':'25-image validation reused for tuning, not independent test; false positives reported separately'},
    'models':[]}
for path in sorted(MODELS.glob('*.pt')):
    model = YOLO(str(path))
    assert model.task == 'segment' and len(model.names) == 5
    hits, fp, fn, ious = 0, 0, 0, []
    per_class = {int(k): {'name':v,'gt':0,'matched':0,'false_positive':0,'iou_sum':0.0} for k,v in model.names.items()}
    for index, (image, truth_masks, truth_classes) in enumerate(ground_truth):
        result = model.predict(str(image), device='cpu', imgsz=640, conf=0.25,
                               iou=0.7, retina_masks=True, verbose=False)[0]
        pred_masks = [] if result.masks is None else list(result.masks.data.cpu().numpy() > 0.5)
        pred_classes = result.boxes.cls.cpu().numpy().astype(int)
        assert len(pred_masks) == len(pred_classes)
        matrix = np.zeros((len(truth_masks), len(pred_masks)))
        for a, truth in enumerate(truth_masks):
            for b, pred in enumerate(pred_masks):
                assert pred.shape == truth.shape
                if truth_classes[a] == pred_classes[b]:
                    union = np.count_nonzero(truth | pred)
                    matrix[a,b] = np.count_nonzero(truth & pred) / union if union else 0.0
        valid = matrix >= 0.5
        matched_truth, matched_pred = set(), set()
        if matrix.size:
            # Prioritize match count before overlap: count bonus exceeds total possible IoU.
            bonus = min(matrix.shape) + 1
            aa, bb = linear_sum_assignment(-(valid * (bonus + matrix)))
            for a,b in zip(aa,bb):
                if valid[a,b]:
                    value = float(matrix[a,b]); ious.append(value)
                    matched_truth.add(a); matched_pred.add(b)
                    record = per_class[int(truth_classes[a])]
                    record['matched'] += 1; record['iou_sum'] += value
        hits += len(matched_truth); fn += len(truth_masks)-len(matched_truth)
        fp += len(pred_masks)-len(matched_pred)
        for cls in truth_classes: per_class[int(cls)]['gt'] += 1
        for b,cls in enumerate(pred_classes):
            if b not in matched_pred: per_class[int(cls)]['false_positive'] += 1
        print(path.name, index+1, '/25', flush=True)
    for record in per_class.values():
        record['matched_mean_iou'] = record['iou_sum']/record['matched'] if record['matched'] else None
        record['gt_mean_with_misses_zero'] = record['iou_sum']/record['gt'] if record['gt'] else None
    row = {'file':path.name, 'matched':hits, 'false_positive':fp, 'missed_or_wrong_class_or_iou_below_05':fn,
           'matched_mean_iou':float(np.mean(ious)) if ious else None,
           'gt_mean_with_misses_zero':sum(ious)/387,
           'instance_recall_at_mask_iou05':hits/387,
           'instance_precision_at_mask_iou05':hits/(hits+fp) if hits+fp else None,
           'per_class':per_class}
    report['models'].append(row)
    OUT.write_text(json.dumps(report, indent=2))
    print('COMPLETE', json.dumps({k:v for k,v in row.items() if k!='per_class'}), flush=True)
print('SAVED', OUT)
