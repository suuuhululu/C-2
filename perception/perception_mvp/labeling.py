"""Real RGB preparation, manual polygon annotation and reviewed YOLO export."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import numpy as np
import yaml

from .contracts import CLASS_NAMES
from .yolo_pipeline import check_labels

ROOT = Path(__file__).resolve().parent.parent
NAMES = tuple(CLASS_NAMES.values())


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    # Replace only this tool's working metadata; original recordings never change.
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(sources, workspace):
    workspace = Path(workspace).resolve()
    manifest = workspace / "provenance.json"
    if workspace.exists() and not manifest.is_file():
        raise ValueError("existing workspace without provenance; refuse overwrite")
    entries = read(manifest) if manifest.is_file() else []
    known = {entry["recording"]: entry for entry in entries}
    planned = []
    for source in sources:
        source = Path(source).resolve(strict=True)
        # Source must be ONE complete assembly/session, not an individual step/View.
        if source.name in ("V0", "D1", "D2", "D3", "D4") or source.name.startswith("step_"):
            raise ValueError("source must be an entire assembly/session directory")
        for image in sorted(source.rglob("rgb.png")):
            metadata = read(image.with_name("metadata.json"))
            if metadata.get("mode") != "REAL" or metadata.get("view_id") not in ("V0", "D1", "D2", "D3", "D4"):
                raise ValueError("actual recording with supported View required")
            if not image.with_name("depth_aligned.npy").is_file():
                raise FileNotFoundError("source aligned Depth missing: " + str(image.parent))
            recording, sha = str(image.parent), digest(image)
            if recording in known:
                entry = known[recording]
                if entry["sha256"] != sha or digest(workspace / entry["image"]) != sha:
                    raise ValueError("previous source/copy changed; refuse silent replacement")
                continue
            # Readable prefix + path hash avoids equal rgb.png/timestamp collisions.
            identity = hashlib.sha256(recording.encode()).hexdigest()[:16]
            name = source.name + "__" + "__".join(image.parent.relative_to(source).parts) + "__" + identity + ".png"
            entry = {"image": "images/" + name, "scene_id": str(source),
                     "recording": recording, "source_rgb": str(image), "view_id": metadata["view_id"],
                     "captured_at": metadata["captured_at"], "sha256": sha}
            planned.append(entry)
            known[recording] = entry
    if not entries and not planned:
        raise ValueError("no actual RGB recordings found")
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "images").mkdir(exist_ok=True)
    (workspace / "annotations").mkdir(exist_ok=True)
    for entry in planned:
        target = workspace / entry["image"]
        if target.exists():
            raise FileExistsError(target)
        shutil.copy2(entry["source_rgb"], target)
        if digest(target) != entry["sha256"]:
            raise OSError("RGB copy integrity failure")
    entries.extend(planned)
    write(manifest, entries)
    print(f"RGB 정리 완료: 총 {len(entries)}장, 신규 {len(planned)}장. 원본 RGB-D 보존.")


def polygon_lines(annotation, image, width, height):
    if (annotation.get("imagePath") != image.name or annotation.get("imageWidth") != width or
            annotation.get("imageHeight") != height or annotation.get("flags", {}).get("reviewed") is not True):
        raise ValueError("matching image dimensions/name and explicit human reviewed flag required")
    shapes = annotation["shapes"]
    empty = annotation["flags"].get("empty_confirmed")
    if type(empty) is not bool or bool(shapes) == empty:
        raise ValueError("empty annotation requires explicit human empty confirmation")
    lines = []
    for shape in shapes:
        if shape["shape_type"] != "polygon" or shape["label"] not in NAMES:
            raise ValueError("four-class instance polygons only; rectangles unsupported")
        if shape.get("group_id") is not None:
            raise ValueError("grouped/disconnected polygons require manual single-instance review")
        points = np.asarray(shape["points"], float)
        if (points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or
                not np.isfinite(points).all() or len(np.unique(points, axis=0)) < 3 or
                np.any(points < 0) or np.any(points[:, 0] >= width) or np.any(points[:, 1] >= height) or
                cv2.contourArea(points.astype(np.float32)) <= 0):
            raise ValueError("invalid pixel polygon")
        # Reject crossings rather than exporting ambiguous masks.
        def cross(a, b, c):
            return float(np.cross(b - a, c - a))
        for i in range(len(points)):
            a, b = points[i], points[(i + 1) % len(points)]
            for j in range(i + 1, len(points)):
                if j == i + 1 or (i == 0 and j == len(points) - 1):
                    continue
                c, d = points[j], points[(j + 1) % len(points)]
                if cross(a,b,c) * cross(a,b,d) <= 0 and cross(c,d,a) * cross(c,d,b) <= 0:
                    # Collinear disjoint edges are not intersections.
                    if np.all(np.maximum(np.minimum(a,b),np.minimum(c,d)) <= np.minimum(np.maximum(a,b),np.maximum(c,d))):
                        raise ValueError("self-intersecting polygon")
        normalized = points / np.array([width, height])
        lines.append(str(NAMES.index(shape["label"])) + " " + " ".join(f"{v:.10f}" for v in normalized.ravel()))
    return lines


def annotate(workspace):
    workspace = Path(workspace).resolve()
    entries = read(workspace / "provenance.json")
    index = 0
    title = "B Perception - manual polygon"
    try:
        while 0 <= index < len(entries):
            entry = entries[index]
            image = workspace / entry["image"]
            if digest(image) != entry["sha256"]:
                raise ValueError("prepared RGB changed")
            rgb = cv2.imread(str(image))
            if rgb is None:
                raise ValueError("unreadable actual RGB")
            height, width = rgb.shape[:2]
            path = workspace / "annotations" / image.with_suffix(".json").name
            annotation = read(path) if path.exists() else {"imagePath": image.name,
                "imageHeight": height, "imageWidth": width, "flags": {}, "shapes": []}
            if path.exists():
                polygon_lines(annotation, image, width, height)
            scale = min(1., 1200 / width, 750 / height)
            state = {"points": [], "class": 0}
            def click(event, x, y, flags, unused):
                if event == cv2.EVENT_LBUTTONDOWN and 0 <= x < int(width*scale) and 0 <= y < int(height*scale):
                    state["points"].append([min(width-1, x/scale), min(height-1, y/scale)])
                elif event == cv2.EVENT_RBUTTONDOWN and state["points"]:
                    state["points"].pop()
            cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
            cv2.setMouseCallback(title, click)
            print(f"[{index+1}/{len(entries)}] {image.name}", flush=True)
            while True:
                display = cv2.resize(rgb, (int(width*scale), int(height*scale)))
                for shape in annotation["shapes"]:
                    polygon = np.rint(np.asarray(shape["points"])*scale).astype(np.int32)
                    cv2.polylines(display, [polygon], True, (0,255,0), 2)
                    cv2.putText(display, shape["label"], tuple(polygon[0]), cv2.FONT_HERSHEY_SIMPLEX, .45, (0,255,0), 1)
                if state["points"]:
                    polygon = np.rint(np.asarray(state["points"])*scale).astype(np.int32)
                    cv2.polylines(display, [polygon], False, (0,255,255), 2)
                cv2.putText(display, f"class {state['class']}: {NAMES[state['class']]}", (8,20), cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,255),1)
                cv2.putText(display, "0-3 class | click vertices | Enter finish | U undo | S reviewed save | E empty | Q quit", (8,40), cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,255),1)
                cv2.imshow(title, display)
                key = cv2.waitKey(30) & 0xff
                if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1 or key == ord("q"):
                    return
                if key in map(ord, "0123"):
                    state["class"] = key - ord("0")
                elif key in (10,13):
                    shape = {"label": NAMES[state["class"]], "points": state["points"],
                             "shape_type": "polygon", "group_id": None}
                    trial = dict(annotation, shapes=[shape], flags={"reviewed": True, "empty_confirmed": False})
                    try:
                        polygon_lines(trial, image, width, height)
                    except ValueError as error:
                        print("polygon 오류: " + str(error), flush=True)
                        continue
                    annotation["shapes"].append(shape)
                    state["points"] = []
                elif key == ord("u"):
                    if state["points"]:
                        state["points"].pop()
                    elif annotation["shapes"]:
                        annotation["shapes"].pop()
                elif key in (ord("s"),ord("e")):
                    if state["points"] or (key == ord("s") and not annotation["shapes"]) or (key == ord("e") and annotation["shapes"]):
                        print("S: 모든 블록 polygon 완료 후 / E: 실제 빈 보드일 때만 사용", flush=True)
                        continue
                    annotation["flags"] = {"reviewed": True, "empty_confirmed": key == ord("e")}
                    polygon_lines(annotation, image, width, height)
                    write(path, annotation)
                    print("검수 라벨 저장: " + str(path), flush=True)
                    index += 1
                    break
                elif key == ord("p"):
                    index = max(0,index-1)
                    print("미저장 변경은 취소합니다.", flush=True)
                    break
    finally:
        cv2.destroyAllWindows()


def export(workspace, output, validation_scenes):
    workspace, output = Path(workspace).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("new output directory required: " + str(output))
    entries = read(workspace / "provenance.json")
    scenes = {entry["scene_id"] for entry in entries}
    validation = {str(Path(s).resolve(strict=True)) for s in validation_scenes}
    if not validation <= scenes or not validation or not scenes - validation:
        raise ValueError("select existing complete validation sessions; separate training sessions required")
    planned, manifest = [], []
    hashes = {}
    for entry in entries:
        image = workspace / entry["image"]
        if digest(image) != entry["sha256"] or digest(entry["source_rgb"]) != entry["sha256"]:
            raise ValueError("original/prepared RGB changed")
        rgb = cv2.imread(str(image))
        if rgb is None:
            raise ValueError("unreadable image")
        annotation = read(workspace / "annotations" / image.with_suffix(".json").name)
        lines = polygon_lines(annotation, image, rgb.shape[1], rgb.shape[0])
        split = "val" if entry["scene_id"] in validation else "train"
        if entry["sha256"] in hashes and hashes[entry["sha256"]] != split:
            raise ValueError("identical RGB crosses train/validation")
        hashes[entry["sha256"]] = split
        manifest.append(dict(entry, image=f"images/{split}/{image.name}", split=split,
                             reviewed=True, empty_confirmed=annotation["flags"]["empty_confirmed"]))
        planned.append((image, split, lines))
    for split in ("train","val"):
        (output / "images" / split).mkdir(parents=True, exist_ok=False)
        (output / "labels" / split).mkdir(parents=True, exist_ok=False)
    for image, split, lines in planned:
        shutil.copy2(image, output / "images" / split / image.name)
        (output / "labels" / split / image.with_suffix(".txt").name).write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    write(output / "scenes.json", manifest)
    (output / "dataset.yaml").write_text(yaml.safe_dump({"path": str(output),
        "train": "images/train", "val": "images/val", "names": CLASS_NAMES}, sort_keys=False), encoding="utf-8")
    print(json.dumps(check_labels(output / "dataset.yaml", output / "scenes.json"), ensure_ascii=False, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--source", nargs="+", type=Path, required=True)
    prepare_parser.add_argument("--workspace", type=Path, default=ROOT / "labeling")
    label_parser = commands.add_parser("annotate")
    label_parser.add_argument("--workspace", type=Path, default=ROOT / "labeling")
    export_parser = commands.add_parser("export")
    export_parser.add_argument("--workspace", type=Path, default=ROOT / "labeling")
    export_parser.add_argument("--output", type=Path, required=True)
    export_parser.add_argument("--val-scenes", nargs="+", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        prepare(args.source, args.workspace)
    elif args.command == "annotate":
        annotate(args.workspace)
    else:
        export(args.workspace, args.output, args.val_scenes)


if __name__ == "__main__":
    main()
