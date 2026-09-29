"""Make the adjacent deployable service modules importable during tests."""

import sys
from pathlib import Path

BACKEND = str(Path(__file__).resolve().parent)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
