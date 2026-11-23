"""Feishu operations done as the current lark-cli user.

These touch the project's base directly (collaborators, workflow state), which
the backend does not expose. Every function returns a dict and never raises for
a lark-cli failure, so callers can report "could not verify" instead of crashing.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

Runner = Callable[[list[str]], subprocess.CompletedProcess]

# 「人才招聘」应用：后端 Worker 用它的身份在底表建工作流，所以必须是可管理协作者
RECRUIT_APP_ID = "cli_a8d939d8527fd01c"
RECRUIT_APP_NAME = "人才招聘"
FULL_ACCESS = "full_access"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)


def call(args: list[str], runner: Runner = _run) -> dict[str, Any]:
    """Run lark-cli and return its JSON envelope ({ok, data, error})."""
    if runner is _run and not shutil.which("lark-cli"):
        return {"ok": False, "error": {"message": "本机没有安装 lark-cli"}}
    try:
        proc = runner(["lark-cli", *args])
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"message": "lark-cli 超时"}}
    out = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(r"\{.*\}", out, re.S)
    if not match:
        return {"ok": False, "error": {"message": out.strip()[:300]}}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {"ok": False, "error": {"message": out.strip()[:300]}}
    data.pop("_notice", None)
    if "ok" not in data:
        data["ok"] = proc.returncode == 0 and data.get("code") in (None, 0)
    return data


def _error(resp: dict[str, Any]) -> str:
    err = resp.get("error") or {}
    return str(err.get("message") or resp.get("msg") or "")[:200]


def ensure_app_collaborator(app_token: str, runner: Runner = _run) -> dict[str, Any]:
    """Make 人才招聘 a full_access collaborator of the base. Copied from the enqueue
    skill's ensure_app_collaborator.py and owned here.

    Returns {"ok": True, "action": "present" | "added" | "upgraded"} or
    {"ok": False, "reason": ..., "message": ...}.
    """
    listed = call(["drive", "+member-list", "--token", app_token, "--type", "bitable",
                   "--as", "user", "--format", "json"], runner)
    if not listed.get("ok"):
        return {"ok": False, "reason": "member_list_failed", "message": _error(listed)}
    items = (listed.get("data") or {}).get("items") or []
    hit = next(
        (m for m in items if m.get("member_type") == "appid" and m.get("member_id") == RECRUIT_APP_ID),
        None,
    )
    if hit and hit.get("perm") == FULL_ACCESS:
        return {"ok": True, "action": "present", "app": RECRUIT_APP_NAME}

    body = json.dumps({"member_type": "appid", "member_id": RECRUIT_APP_ID, "perm": FULL_ACCESS})
    if hit:
        resp = call(["api", "PUT", f"/open-apis/drive/v1/permissions/{app_token}/members/{RECRUIT_APP_ID}",
                     "--params", json.dumps({"type": "bitable", "member_type": "appid"}),
                     "--data", body, "--as", "user", "--format", "json"], runner)
        action = "upgraded"
    else:
        resp = call(["drive", "permission.members", "create", "--token", app_token, "--type", "bitable",
                     "--data", body, "--as", "user", "--yes", "--format", "json"], runner)
        action = "added"
    if not resp.get("ok"):
        return {"ok": False, "reason": f"{action}_failed", "message": _error(resp)}
    return {"ok": True, "action": action, "app": RECRUIT_APP_NAME, "from": hit.get("perm") if hit else None}


def _workflow_of(resp: dict[str, Any]) -> dict[str, Any]:
    data = resp.get("data") or {}
    return data.get("workflow") or data


def get_workflow(app_token: str, workflow_id: str, runner: Runner = _run) -> dict[str, Any]:
    """{"ok", "status": "enabled"|"disabled"|None, "steps": [...]} for one workflow."""
    resp = call(["base", "+workflow-get", "--base-token", app_token, "--workflow-id", workflow_id,
                 "--as", "user", "--format", "json"], runner)
    if not resp.get("ok"):
        return {"ok": False, "message": _error(resp), "status": None, "steps": []}
    wf = _workflow_of(resp)
    return {"ok": True, "status": wf.get("status"), "title": wf.get("title"), "steps": wf.get("steps") or []}


def enable_workflow(app_token: str, workflow_id: str, runner: Runner = _run) -> dict[str, Any]:
    resp = call(["base", "+workflow-enable", "--base-token", app_token, "--workflow-id", workflow_id,
                 "--as", "user", "--format", "json"], runner)
    if not resp.get("ok"):
        return {"ok": False, "message": _error(resp)}
    return {"ok": True}


def has_manual_clear_step(steps: list[dict[str, Any]]) -> bool:
    """Same rule as the backend: a SetRecordAction that sets a column to empty can only
    be the step added by hand (the OpenAPI cannot create it). The backend's
    audit_workbench_workflow.has_manual_clear_step uses it to decide whether to
    overwrite; keep the two in sync."""
    for step in steps or []:
        if not isinstance(step, dict) or step.get("type") != "SetRecordAction":
            continue
        for item in (step.get("data") or {}).get("field_values") or []:
            if isinstance(item, dict) and item.get("value") in (None, [], {}, ""):
                return True
    return False


def auth_status(runner: Runner = _run) -> dict[str, Any]:
    """{"ok", "user": <飞书用户名>, "message"} for the lark-cli user identity."""
    resp = call(["auth", "status"], runner)
    user = ((resp.get("identities") or {}).get("user")) or {}
    if user.get("status") == "ready":
        return {"ok": True, "user": user.get("userName") or "", "message": None}
    message = user.get("message") or _error(resp) or "lark-cli 用户身份不可用"
    return {"ok": False, "user": None, "message": message}
