"""Let pytest find the repository's backend `app` package when run from perception/.

Only adds the repository root to sys.path (read access); no backend file is changed.
"""
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.append(ROOT)
