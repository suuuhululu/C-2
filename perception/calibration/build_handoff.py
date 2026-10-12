#!/usr/bin/env python3
"""Package current code, guides, measured results and their SHA-256 manifest."""
import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import zipfile


def build(output):
    root = Path(__file__).resolve().parent
    calibration = json.loads((root / "runs/view01/calibration.json").read_text())
    validation = calibration.get("last_validation", {})
    validated = bool(calibration.get("independently_validated") and validation.get("passed"))
    state = "BOARD_VALIDATED_BLOCK_TEST_PENDING" if validated else "DRAFT_VALIDATION_PENDING"
    with (root / "runs/view01/stud_coordinates.csv").open() as file:
        count = sum(1 for _ in csv.DictReader(file))
    if count != calibration["rows"] * calibration["cols"]:
        raise ValueError("Coordinate CSV row count differs from calibrated grid")
    generated = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    status = f"""# 전달본 상태\n\n생성: {generated}\n\n- 상태: **{state}**\n- 판: {calibration['rows']}×{calibration['cols']}, stud 좌표 {count}개\n- 영상 크기: {calibration['image_size']}\n- 중심 간격 입력: {calibration['pitch_mm']} mm (지름 약 8 mm를 포함한 사용자 치수로 계산)\n- 최대 독립 검증 오차: {validation.get('max_error_mm', '미측정')} mm\n- RMSE: {validation.get('rmse_mm', '미측정')} mm\n- 검증 문턱: {validation.get('threshold_mm', '미정')} mm\n- 독립 검증 통과: {validated}\n- 블록 윗면 높이 및 블록 검출 중심의 현장 검증: **미완료**\n- 같은 카메라-판 상대 자세에서만 기존 변환을 사용한다. 다른 설치는 재캘리브레이션한다.\n- 미검증 결과는 개발 시험용으로 명시적으로 허용할 때만 사용한다.\n\n먼저 `HONGDONG_VISION_GUIDE.md`를 읽고 API/ROS 연동을 진행한다.\n"""
    (root / "HANDOFF_STATUS.md").write_text(status, encoding="utf-8")
    paths = list(root.glob("*.py")) + list(root.glob("*.md")) + [root / "requirements.txt", root / ".gitignore"]
    for folder, patterns in (("tests", ("*.py",)), ("examples", ("*.json",)),
                             ("captures", ("*.json", "*.png")), ("runs/view01", ("*.json", "*.csv", "*.png"))):
        for pattern in patterns:
            paths.extend((root / folder).glob(pattern))
    paths = sorted(set(p for p in paths if p.is_file()))
    entries = [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]
    manifest = {"generated_at": generated, "status": state, "independently_validated": validated,
                "calibration_file": "runs/view01/calibration.json", "stud_count": count,
                "block_height_and_detection_validation_completed": False, "files": entries}
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = Path("lego_calibration")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, prefix / path.relative_to(root))
        archive.writestr(str(prefix / "MANIFEST.json"), json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
        for item in entries:
            if hashlib.sha256(archive.read(str(prefix / item["path"]))).hexdigest() != item["sha256"]:
                raise ValueError("Packaged file checksum differs")
    print(json.dumps({"archive": str(output), "status": state, "files": len(entries) + 1,
                      "bytes": output.stat().st_size}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    build(parser.parse_args().out)
