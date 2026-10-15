#!/usr/bin/env python3
"""Load enqueue API keys from local secrets file or env. Never print full keys."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SECRETS_PATH = Path.home() / ".agents" / "secrets" / "audit-workbench-enqueue.env"

URLS = {
    "boe": "https://service-boe.meetchances.com/api/v1/internal/audit-workbench/tasks/enqueue",
    "prod": "https://service.meetchances.com/api/v1/internal/audit-workbench/tasks/enqueue",
}

ENV_NAMES = {
    "boe": ("AUDIT_WORKBENCH_ENQUEUE_API_KEY_BOE",),
    "prod": ("AUDIT_WORKBENCH_ENQUEUE_API_KEY_PROD",),
}
FILE_KEYS = {"boe": "BOE_API_KEY", "prod": "PROD_API_KEY"}
FALLBACK_ENV = "AUDIT_WORKBENCH_ENQUEUE_API_KEY"


def mask(key: str | None) -> str | None:
    if not key:
        return None
    return key[-4:] if len(key) >= 4 else "****"


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        out[name.strip()] = value.strip().strip("'").strip('"')
    return out


def load(env: str) -> dict[str, object]:
    env = env.lower()
    key = None
    source = None
    attempts: list[dict[str, object]] = []

    file_map = _parse_env_file(SECRETS_PATH)
    file_name = FILE_KEYS[env]
    file_value = file_map.get(file_name)
    attempts.append(
        {
            "kind": "local-file",
            "name": str(SECRETS_PATH),
            "ok": bool(file_value),
            "error": None if file_value else "missing or empty",
        }
    )
    if file_value:
        key, source = file_value, f"file/{file_name}"

    if not key:
        for name in (*ENV_NAMES[env], FALLBACK_ENV):
            value = os.environ.get(name)
            attempts.append(
                {"kind": "env", "name": name, "ok": bool(value), "error": None if value else "unset"}
            )
            if value:
                key, source = value.strip(), f"env/{name}"
                break

    return {
        "env": env,
        "url": URLS[env],
        "secrets_path": str(SECRETS_PATH),
        "source": source,
        "has_key": bool(key),
        "last4": mask(key),
        "next_step": None if key else "ask_user_for_key",
        "attempts": attempts,
        "key": key,
    }


def load_key(env: str) -> str | None:
    return load(env).get("key")  # type: ignore[return-value]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=("boe", "prod"), required=True)
    parser.add_argument("--print-key", action="store_true")
    args = parser.parse_args()
    result = load(args.env)
    key = result.pop("key")
    if args.print_key:
        if not key:
            print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
            return 2
        sys.stdout.write(key)
        return 0
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if key else 2


if __name__ == "__main__":
    raise SystemExit(main())
