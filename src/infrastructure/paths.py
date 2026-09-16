from __future__ import annotations

import sys
from pathlib import Path


def project_path(relative_path: str) -> Path:
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        bundled = bundle_root / relative_path
        if bundled.exists():
            return bundled
    return Path(relative_path)
