"""Is the installed plugin the latest on GitHub main, and how to update if not.

The check only reads. Updating is left to the Agent's shell, so the user sees
the commands run and the client's own permission prompts still apply. The
client is told apart by where this package was installed from.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import setup_check

Runner = Callable[[list[str]], subprocess.CompletedProcess]

REPO = "wisdom-knowledge/audit_workbench_skills"
MANIFEST = "plugin/.claude-plugin/plugin.json"
SELECTOR = "audit-workbench@audit-workbench"

COMMANDS = {
    "claude": [
        "claude plugin marketplace update audit-workbench",
        f"claude plugin update {SELECTOR}",
    ],
    "codex": [
        "codex plugin marketplace upgrade audit-workbench",
        f"codex plugin add {SELECTOR}",
    ],
}


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)


def detect_client(path: str | None = None) -> str:
    """claude / codex when installed as a plugin; local for a developer checkout."""
    where = path or str(Path(__file__).resolve())
    if "/.claude/plugins/cache/" in where:
        return "claude"
    if "/.codex/plugins/cache/" in where:
        return "codex"
    return "local"


def parse_version(text: str) -> tuple[int, ...] | None:
    match = re.match(r"^\s*(\d+(?:\.\d+)*)", text or "")
    return tuple(int(p) for p in match.group(1).split(".")) if match else None


def _version_of(manifest_text: str) -> str | None:
    try:
        return str(json.loads(manifest_text).get("version") or "") or None
    except ValueError:
        return None


def latest_version(runner: Runner = _run) -> dict[str, Any]:
    """Version on GitHub main: via gh when logged in, else a shallow SSH clone."""
    if runner is not _run or shutil.which("gh"):
        try:
            proc = runner(["gh", "api", f"repos/{REPO}/contents/{MANIFEST}",
                           "-H", "Accept: application/vnd.github.raw"])
            if proc.returncode == 0 and (ver := _version_of(proc.stdout)):
                return {"ok": True, "version": ver, "via": "gh"}
        except (subprocess.TimeoutExpired, OSError):
            pass
    if runner is _run and not shutil.which("git"):
        return {"ok": False, "message": "本机没有 gh 也没有 git，查不到最新版本"}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            clone = runner(["git", "clone", "--quiet", "--depth", "1", "--no-checkout",
                            f"git@github.com:{REPO}.git", tmp])
            if clone.returncode != 0:
                return {"ok": False, "message": (clone.stderr or clone.stdout or "").strip()[:200]}
            show = runner(["git", "-C", tmp, "show", f"HEAD:{MANIFEST}"])
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {"ok": False, "message": f"访问 GitHub 失败：{exc}"}
    ver = _version_of(show.stdout) if show.returncode == 0 else None
    if not ver:
        return {"ok": False, "message": "读不到远端插件版本号"}
    return {"ok": True, "version": ver, "via": "git"}


def check_update(runner: Runner = _run, client: str | None = None,
                 installed: str | None = None) -> dict[str, Any]:
    client = client or detect_client()
    current = installed or setup_check.version()
    out: dict[str, Any] = {"ok": True, "client": client, "installed": current,
                           "latest": None, "update_available": False, "commands": []}
    if client == "local":
        out["message"] = "开发者本地安装（软链），不走插件更新，跳过版本检查。"
        return out
    found = latest_version(runner)
    if not found["ok"]:
        return {**out, "ok": False, "message": f"查不到最新版本：{found['message']}。先按当前版本继续。"}
    out["latest"] = found["version"]
    have, want = parse_version(current), parse_version(found["version"])
    if have is None or want is None:
        return {**out, "ok": False, "message": f"版本号无法比较：当前 {current}，最新 {found['version']}"}
    if want > have:
        out["update_available"] = True
        out["commands"] = COMMANDS[client]
        out["message"] = f"有新版本 {found['version']}（当前 {current}），按 commands 依次更新后重启客户端。"
    else:
        out["message"] = f"已是最新版本 {current}。"
    return out
