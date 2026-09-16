from __future__ import annotations

import argparse
import os
from pathlib import Path

from src.infrastructure.report_storage import MonthlyReportStorage, create_report_storage


def load_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def migrate(source_dir: Path) -> dict[str, int]:
    source = MonthlyReportStorage(source_dir)
    target = create_report_storage()
    existing = {(item.report_type, item.period_start, item.period_end) for item in target.list()}
    result = {"copied": 0, "skipped": 0, "failed": 0, "target_count": 0}

    for item in source.list():
        key = (item.report_type, item.period_start, item.period_end)
        if key in existing:
            result["skipped"] += 1
            print(f"skip {item.report_type} {item.period_start} {item.period_end}")
            continue
        resolved = source.resolve(item.id)
        if resolved is None:
            result["failed"] += 1
            print(f"failed {item.report_type} {item.period_start} {item.period_end}: file missing")
            continue
        target.save(item.report_type, item.original_name, resolved[1].read_bytes())
        existing.add(key)
        result["copied"] += 1
        print(f"copied {item.report_type} {item.period_start} {item.period_end}")

    result["target_count"] = len(target.list())
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/docker-volume-export"))
    args = parser.parse_args()
    load_env()
    print(migrate(args.source))


if __name__ == "__main__":
    main()
