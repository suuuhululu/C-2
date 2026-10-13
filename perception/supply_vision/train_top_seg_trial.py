"""Validate a Roboflow polygon ZIP and train a separate Colab T4 top-face segmentation trial."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import zipfile

import cv2
import numpy as np
import yaml

CLASSES = {'blue_2x2', 'blue_2x3', 'red_2x1', 'yellow_2x2', 'yellow_2x3'}


def prepare(archive_path, output):
    output.mkdir(exist_ok=False, parents=True)
    dataset = output / 'dataset'
    dataset.mkdir()
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError('corrupt ZIP')
        seen = {}
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            target = (dataset / entry.filename).resolve()
            if not target.is_relative_to(dataset.resolve()):
                raise ValueError('ZIP path outside dataset')
            content = archive.read(entry)
            if entry.filename in seen and seen[entry.filename] != content:
                raise ValueError('conflicting duplicate ZIP entry')
            seen[entry.filename] = content
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    original = yaml.safe_load((dataset/'data.yaml').read_text())
    names = original['names']
    if isinstance(names, dict):
        names = [names[i] for i in range(len(names))]
    if len(names) != 5 or set(names) != CLASSES:
        raise ValueError('five expected top-face classes required')
    report = {'zip_sha256': hashlib.sha256(Path(archive_path).read_bytes()).hexdigest(),
              'classes': names, 'splits': {}}
    hashes = set()
    for split, expected in [('train',6),('valid',2)]:
        images = sorted((dataset/split/'images').glob('*'))
        if len(images) != expected:
            raise ValueError('expected train=6, valid=2 real images')
        counts = Counter()
        stems = set()
        for image in images:
            pixels = cv2.imread(str(image))
            if pixels is None:
                raise ValueError('unreadable RGB')
            digest = hashlib.sha256(pixels.tobytes()).hexdigest()
            if digest in hashes:
                raise ValueError('duplicate decoded image')
            hashes.add(digest)
            stems.add(image.stem)
            label = dataset/split/'labels'/f'{image.stem}.txt'
            for line in label.read_text().splitlines():
                values = line.split()
                cls = int(values[0])
                if cls not in range(5) or len(values) < 7 or len(values) % 2 != 1:
                    raise ValueError('YOLO polygon row required, not detection boxes')
                points = np.array([float(n) for n in values[1:]],np.float32).reshape(-1,2)
                if (not np.isfinite(points).all() or (points<0).any() or (points>1).any()
                        or cv2.contourArea(points) <= 0):
                    raise ValueError('invalid polygon')
                counts[names[cls]] += 1
        if set(p.stem for p in (dataset/split/'labels').glob('*.txt')) != stems:
            raise ValueError('image/label mismatch')
        if set(counts) != CLASSES:
            raise ValueError('each split must include five classes')
        report['splits'][split] = {'images':len(images),'instances':dict(counts)}
    # Roboflow ../train and absent test path are replaced in a local copy only.
    data = {'path':str(dataset.resolve()), 'train':'train/images', 'val':'valid/images', 'names':names}
    (dataset/'data_local.yaml').write_text(yaml.safe_dump(data,sort_keys=False))
    (output/'DATA_CHECK.json').write_text(json.dumps(report,indent=2))
    return dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--pretrained', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    dataset = prepare(args.zip, output)
    print('DATA_CHECK_PASSED', output/'DATA_CHECK.json', flush=True)
    import torch
    from ultralytics import YOLO
    if not torch.cuda.is_available() or 'T4' not in torch.cuda.get_device_name(0):
        raise RuntimeError('Colab T4 GPU required; no CPU fallback')
    weights = Path(args.pretrained)
    if not weights.is_file():
        raise FileNotFoundError('local pretrained .pt required')
    model = YOLO(str(weights))
    if model.task != 'segment':
        raise ValueError('segment initialization required')
    model.train(data=str(dataset/'data_local.yaml'), epochs=60, patience=15, imgsz=640,
                batch=4, device=0, workers=2, seed=42, deterministic=True,
                project=str(output), name='run', exist_ok=False,
                val=True, plots=True, save=True, mask_ratio=2,
                mosaic=0.0, mixup=0.0, copy_paste=0.0)
    run = Path(model.trainer.save_dir)
    best = YOLO(str(run/'weights/best.pt'))
    assert best.task == 'segment' and set(best.names.values()) == CLASSES
    metrics = best.val(data=str(dataset/'data_local.yaml'), device=0, imgsz=640,
                       batch=4, workers=2, mask_ratio=2, project=str(output), name='best_validation')
    best.predict(source=str(dataset/'valid/images'), device=0, imgsz=640, conf=.25,
                 retina_masks=True, save=True, project=str(output), name='validation_preview')
    epochs = len(list(csv.DictReader((run/'results.csv').open())))
    summary = {'model':str(run/'weights/best.pt'),'epochs_completed':epochs,
               'metrics':metrics.results_dict,'device':torch.cuda.get_device_name(0),'train_images':6,'val_images':2,
               'note':'Small trial; nearby capture sessions, no independent test or grasp/center verification.'}
    (output/'TRAINING_SUMMARY.json').write_text(json.dumps(summary,indent=2))
    print('TRAINING_COMPLETED', json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
