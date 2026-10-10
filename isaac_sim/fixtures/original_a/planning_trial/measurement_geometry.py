"""Latest explicit user dimensions; retained older records are not overwritten."""
import json
from pathlib import Path

GEOMETRY_FILE = Path(__file__).resolve().parent/'measurements/block_geometry.user_20261008.rev2.json'
ABS_REFERENCE_FILE = GEOMETRY_FILE.parent/'abs_reference_properties.user_20261008.json'


def load_geometry():
    return json.loads(GEOMETRY_FILE.read_text())


def load_material_reference():
    return json.loads(ABS_REFERENCE_FILE.read_text())
