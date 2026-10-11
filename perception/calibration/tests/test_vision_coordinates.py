import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geometry import fit_calibration, write_json, board_to_pixels
from vision_coordinates import BoardCoordinateMapper


def calibration_file(tmp_path, validated):
    c = fit_calibration([[100,100],[850,120],[790,830],[150,850]],
                        [[0,0],[385.25,0],[385.25,385.25],[0,385.25]],
                        [1000,1000], pitch_mm=16.75)
    c["independently_validated"] = validated
    path = tmp_path / "calibration.json"
    write_json(path, c)
    return path, c


def test_unvalidated_requires_explicit_opt_in(tmp_path):
    path, _ = calibration_file(tmp_path, False)
    with pytest.raises(ValueError, match="not independently validated"):
        BoardCoordinateMapper(path)
    result = BoardCoordinateMapper(path, True).map_pixel(100, 100, [1000,1000])
    assert result["independently_validated"] is False
    assert abs(result["row_index_0based"]) < 1e-8
    assert abs(result["col_index_0based"]) < 1e-8


def test_vision_bbox_and_units_and_original_resolution(tmp_path):
    path, c = calibration_file(tmp_path, True)
    mapper = BoardCoordinateMapper(path)
    uv = board_to_pixels(c, [[50.25, 50.25]])[0]
    result = mapper.map_bbox([uv[0]-10,uv[1]-10,uv[0]+10,uv[1]+10], [1000,1000])
    np.testing.assert_allclose(result["board_xy_mm"], [50.25,50.25], atol=1e-7)
    assert result["length_unit"] == "mm" and result["frame_id"] == "lego_board"
    assert result["row_index_0based"] == pytest.approx(3)
    with pytest.raises(ValueError, match="resolution"):
        mapper.map_pixel(*uv,[640,640])
    with pytest.raises(ValueError, match="outside"):
        mapper.map_pixel(-1,10,[1000,1000])
    with pytest.raises(ValueError, match="bbox"):
        mapper.map_bbox([20,20,10,10],[1000,1000])
    with pytest.raises(ValueError, match="intrinsics"):
        mapper.map_pixel(*uv,[1000,1000],5)
