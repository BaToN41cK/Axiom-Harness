"""Make the adjacent deployable service modules importable during tests."""

import os
import sys
import tempfile
from pathlib import Path

BACKEND = str(Path(__file__).resolve().parent)
# main creates its default app on import. Never open the runtime payment DB in tests.
_database_dir = tempfile.TemporaryDirectory(prefix="axiom-auth-tests-")
os.environ["PAYMENT_DATABASE_PATH"] = str(Path(_database_dir.name) / "import.sqlite3")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
