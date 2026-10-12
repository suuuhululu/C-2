"""Small, ROS-independent adapter for original-image detector coordinates."""
import argparse
import json
from pathlib import Path

import numpy as np

from geometry import describe_point, pixel_to_board, read_json, write_json


class BoardCoordinateMapper:
    def __init__(self, calibration_path, allow_unvalidated=False):
        self.path = Path(calibration_path).resolve()
        self.calibration = read_json(self.path)
        if self.calibration.get("schema_version") != 1:
            raise ValueError("Unsupported calibration schema")
        self.validated = bool(self.calibration.get("independently_validated"))
        if not self.validated and not allow_unvalidated:
            raise ValueError("Calibration is not independently validated. Use allow_unvalidated=True only for provisional inspection.")

    def map_pixel(self, u, v, image_size, surface_height_mm=0):
        """u,v must belong to the original calibrated color image, not a resized tensor."""
        c = self.calibration
        if list(image_size) != c["image_size"]:
            raise ValueError("Detector image resolution differs from calibration")
        if not np.isfinite([u, v]).all() or not (0 <= u < image_size[0] and 0 <= v < image_size[1]):
            raise ValueError("Detection centre is outside original image")
        xy = pixel_to_board(c, [[float(u), float(v)]], surface_height_mm)[0]
        result = describe_point(c, xy, surface_height_mm)
        result.update({"pixel_xy": [float(u), float(v)], "frame_id": "lego_board",
                       "length_unit": "mm", "independently_validated": self.validated,
                       "row_index_0based": result["row_continuous"] - 1,
                       "col_index_0based": result["col_continuous"] - 1,
                       "view_id": c.get("view_id"),
                       "view_monitoring": "requires_frame_marker_check" if "marker_layout" in c else "unmonitored_fixed_view"})
        return result

    def map_bbox(self, xyxy, image_size, surface_height_mm=0):
        box = np.asarray(xyxy, dtype=float)
        if box.shape != (4,) or not np.isfinite(box).all() or box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("Expected a nonempty bbox [x1,y1,x2,y2] in original-image pixels")
        result = self.map_pixel((box[0] + box[2]) / 2, (box[1] + box[3]) / 2,
                                image_size, surface_height_mm)
        result["centre_definition"] = "bbox_centre_may_include_visible_sides"
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", required=True)
    parser.add_argument("--pixel", type=float, nargs=2, required=True)
    parser.add_argument("--image-size", type=int, nargs=2, required=True, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--surface-height-mm", type=float, default=0)
    parser.add_argument("--allow-unvalidated", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()
    mapper = BoardCoordinateMapper(args.calibration, args.allow_unvalidated)
    result = mapper.map_pixel(*args.pixel, args.image_size, args.surface_height_mm)
    if args.out:
        write_json(args.out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
