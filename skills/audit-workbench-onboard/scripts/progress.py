#!/usr/bin/env python3
"""Read and merge the onboard progress file. No network, no secrets.

Usage:
  progress.py show
  progress.py update --stage 3 --status done --env boe --project-id 1234 \
      --field published_version=1 --field 'pending=["a","b"]'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("AUDIT_WORKBENCH_PROGRESS_DIR") or Path.cwd())
FILE = ROOT / ".audit-workbench-onboard" / "progress.json"


def read() -> dict[str, Any]:
    if not FILE.is_file():
        return {}
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse(value: str) -> Any:
    try:
        return json.loads(value)
    except ValueError:
        return value  # plain text


def merge(patch: dict[str, Any]) -> dict[str, Any]:
    data = read()
    data.update(patch)
    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    update = sub.add_parser("update")
    update.add_argument("--stage", type=int)
    update.add_argument("--status")
    update.add_argument("--env")
    update.add_argument("--project-id", type=int)
    update.add_argument("--field", action="append", default=[])
    args = parser.parse_args(argv)

    if args.command == "show":
        json.dump(read(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    patch: dict[str, Any] = {}
    for key, value in (
        ("stage", args.stage), ("status", args.status),
        ("env", args.env), ("project_id", args.project_id),
    ):
        if value is not None:
            patch[key] = value
    for item in args.field:
        if "=" not in item:
            print(f"--field 需要 name=value: {item}", file=sys.stderr)
            return 2
        name, value = item.split("=", 1)
        patch[name.strip()] = _parse(value.strip())
    if not patch:
        print("没有要更新的字段", file=sys.stderr)
        return 2
    json.dump(merge(patch), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
