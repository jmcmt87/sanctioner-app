from __future__ import annotations

import sys
from pathlib import Path

# Ensure the backend package is importable when running tests from the ingestion directory.
# The editable install .pth file may not be processed in all environments.
backend_path = str(Path(__file__).resolve().parent.parent / "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)
