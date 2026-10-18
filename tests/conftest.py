"""Make the repository's verification helpers available to regression tests."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _directory in (ROOT / "deploy", ROOT / "scripts"):
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))
