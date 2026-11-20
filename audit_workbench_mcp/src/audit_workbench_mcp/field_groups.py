"""Field groups of the project's base table, read with lark-cli as the user.

Only the base being configured needs groups: reference projects already record
round membership and roles in their config. Group names usually carry round
meaning (e.g. 「一轮审核」), which narrows the candidates for round split and
role mapping.

Failures are returned, not raised: without groups the Agent falls back to
name-only matching and lowers confidence.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)


def parse_groups(payload: Any) -> list[dict[str, Any]]:
    """Normalize the field_groups response into [{name, field_ids}]."""
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    groups = data.get("groups") if isinstance(data, dict) else None
    out = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        field_ids = [
            str(child.get("id"))
            for child in group.get("children") or []
            if isinstance(child, dict) and child.get("id") and child.get("type", "field") == "field"
        ]
        out.append({"name": str(group.get("name") or ""), "field_ids": field_ids})
    return out


def fetch_field_groups(
    app_token: str, table_id: str, runner: Runner = _run
) -> dict[str, Any]:
    if runner is _run and not shutil.which("lark-cli"):
        return {"ok": False, "reason": "lark_cli_missing", "groups": []}
    path = f"/open-apis/base/v3/bases/{app_token}/tables/{table_id}/field_groups"
    try:
        proc = runner(["lark-cli", "api", "GET", path, "--as", "user", "--format", "json"])
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "timeout", "groups": []}
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip().splitlines()
        return {"ok": False, "reason": "lark_cli_failed", "detail": message[-1] if message else "", "groups": []}
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return {"ok": False, "reason": "invalid_json", "groups": []}
    if isinstance(payload, dict) and payload.get("code") not in (None, 0):
        return {"ok": False, "reason": "feishu_error", "detail": payload.get("msg"), "groups": []}
    groups = parse_groups(payload)
    return {"ok": True, "reason": None if groups else "no_groups", "groups": groups}
