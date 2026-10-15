"""Human-reviewed real dataset validation, local segmentation training and inference."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import yaml

from .contracts import CLASS_NAMES, LIVE_CLASSES

CLASSES = tuple(CLASS_NAMES.values())


def load_segmentation_model(weights, *, trained=True, allowed_classes=None):
    weights = Path(weights)
    if not weights.is_file() or weights.suffix != ".pt":
        raise FileNotFoundError("local segmentation .pt weights required; no auto-download")
    from ultralytics import YOLO
    model = YOLO(str(weights))
    if model.task != "segment":
        raise ValueError("segmentation model required")
    if trained and allowed_classes is not None:
        names = list(model.names.values())
        if len(names) != len(allowed_classes) or set(names) != set(allowed_classes):
            raise ValueError('live model must contain exactly the five requested classes')
    elif trained and set(model.names.values()) not in (set(CLASS_NAMES.values()), set(LIVE_CLASSES)):
        raise ValueError("model must have exactly the legacy four or current five block classes")
    return model


def infer_masks(rgb, weights, detector_confidence, *, device="cpu", roi_mask=None):
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("uint8 original RGB required")
    if not np.isfinite(detector_confidence) or not 0 < detector_confidence <= 1:
        raise ValueError("explicit detector threshold in (0,1] required")
    x0, y0, x1, y1 = 0, 0, rgb.shape[1], rgb.shape[0]
    if roi_mask is not None:
        if roi_mask.dtype != bool or roi_mask.shape != rgb.shape[:2] or not roi_mask.any():
            raise ValueError('nonempty assembly ROI must match RGB resolution')
        ys, xs = np.nonzero(roi_mask)
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max())+1, int(ys.max())+1
    crop = rgb[y0:y1, x0:x1]
    model = load_segmentation_model(weights)
    result = model.predict(crop[:, :, ::-1].copy(), conf=detector_confidence,
                           retina_masks=True, verbose=False, device=device)[0]
    if result.boxes is None:
        raise ValueError("missing segmentation boxes")
    if len(result.boxes) == 0:
        return []
    if result.masks is None or len(result.masks.data) != len(result.boxes):
        raise ValueError("missing or mismatched instance masks")
    masks = result.masks.data.cpu().numpy() > .5
    if masks.shape[1:] != crop.shape[:2]:
        raise ValueError("mask resolution differs from original RGB")
    detections = []
    for small, cls, conf in zip(masks, result.boxes.cls.cpu().numpy(), result.boxes.conf.cpu().numpy()):
        mask = np.zeros(rgb.shape[:2], bool)
        mask[y0:y1, x0:x1] = small
        if roi_mask is None or np.any(mask & roi_mask):
            detections.append((mask, model.names[int(cls)], float(conf)))
    return detections


def check_labels(dataset_file, scene_manifest):
    """Scene manifest is real collection provenance, not auto-generated ground truth."""
    data = yaml.safe_load(Path(dataset_file).read_text(encoding="utf-8"))
    if data.get("names") != CLASS_NAMES or "download" in data:
        raise ValueError("exact four classes and no dataset auto-download required")
    if not isinstance(data.get("path"), str) or not Path(data["path"]).is_absolute():
        raise ValueError("dataset path must be an actual absolute directory")
    root = Path(data["path"]).resolve(strict=True)
    entries = json.loads(Path(scene_manifest).read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise ValueError("nonempty real scene manifest required")
    provenance = {}
    for entry in entries:
        if (entry["split"] not in ("train", "val") or
                not isinstance(entry["scene_id"], str) or not entry["scene_id"] or
                type(entry["empty_confirmed"]) is not bool or entry.get("reviewed") is not True):
            raise ValueError("scene_id, split, reviewed=true and human empty_confirmed required")
        image = (root / entry["image"]).resolve(strict=True)
        if image in provenance:
            raise ValueError(f"duplicate provenance: {image}")
        provenance[image] = entry
    scenes = {"train": set(), "val": set()}
    seen_images, hashes = set(), {}
    counts = {split: [0, 0, 0, 0] for split in scenes}
    image_counts = {}
    for split in scenes:
        directory = (root / data[split]).resolve(strict=True)
        relative = directory.relative_to(root)
        if not relative.parts or relative.parts[0] != "images":
            raise ValueError("split directories must be under dataset/images")
        label_dir = root / "labels" / Path(*relative.parts[1:])
        images = sorted(p for p in directory.rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
        if not images:
            raise ValueError(f"no real images in {split}")
        image_counts[split] = len(images)
        expected_labels = set()
        for image in images:
            image = image.resolve()
            entry = provenance[image]
            if entry["split"] != split or image in seen_images:
                raise ValueError(f"image split mismatch: {image}")
            seen_images.add(image)
            scenes[split].add(entry["scene_id"])
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            if digest in hashes and hashes[digest] != split:
                raise ValueError("identical image content crosses train/validation")
            hashes[digest] = split
            if cv2.imread(str(image)) is None:
                raise ValueError(f"unreadable image: {image}")
            label = label_dir / image.relative_to(directory).with_suffix(".txt")
            if label in expected_labels:
                raise ValueError("image stems collide on one label file")
            expected_labels.add(label)
            lines = [line for line in label.read_text(encoding="utf-8").splitlines() if line.strip()]
            if bool(lines) == entry["empty_confirmed"]:
                raise ValueError(f"empty label requires explicit human empty confirmation: {label}")
            for number, line in enumerate(lines, 1):
                tokens = line.split()
                if len(tokens) < 7 or (len(tokens) - 1) % 2 or tokens[0] not in ("0", "1", "2", "3"):
                    raise ValueError(f"invalid class/polygon: {label}:{number}")
                points = np.asarray(tokens[1:], dtype=float).reshape(-1, 2)
                if (not np.isfinite(points).all() or np.any(points < 0) or np.any(points > 1) or
                        len(np.unique(points, axis=0)) < 3 or cv2.contourArea(points.astype(np.float32)) <= 0):
                    raise ValueError(f"invalid normalized polygon: {label}:{number}")
                counts[split][int(tokens[0])] += 1
        if set(label_dir.rglob("*.txt")) != expected_labels:
            raise ValueError(f"orphan/missing labels in {split}")
    if set(provenance) != seen_images or scenes["train"] & scenes["val"]:
        raise ValueError("unused provenance or assembly scene leaks across train/validation")
    return {"images": image_counts, "instances_by_class": counts,
            "scene_counts": {split: len(ids) for split, ids in scenes.items()},
            "classes": CLASS_NAMES, "human_mask_accuracy": "requires_human_review"}


def train_or_evaluate(command, dataset, scene_manifest, weights, *, device, imgsz,
                      output, epochs=None, batch=None):
    report = check_labels(dataset, scene_manifest)
    if type(imgsz) is not int or imgsz <= 0 or not str(device):
        raise ValueError("positive image size and explicit device required")
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    if command == "train":
        if any(n == 0 for n in report["instances_by_class"]["train"]):
            raise ValueError("all four classes require real training instances")
        if type(epochs) is not int or epochs <= 0 or type(batch) is not int or batch <= 0:
            raise ValueError("positive epochs and batch required")
        model = load_segmentation_model(weights, trained=False)
        return model.train(data=str(Path(dataset).resolve()), epochs=epochs, batch=batch,
                           imgsz=imgsz, device=device, project=str(output.parent),
                           name=output.name, exist_ok=False)
    if command != "evaluate":
        raise ValueError("train or evaluate required")
    model = load_segmentation_model(weights)
    return model.val(data=str(Path(dataset).resolve()), split="val", imgsz=imgsz,
                     device=device, project=str(output.parent), name=output.name, exist_ok=False)
