"""check_update: compare installed vs GitHub main, hand back per-client commands."""

from __future__ import annotations

import json
import subprocess

import pytest

from audit_workbench_mcp import update_check


def proc(stdout: str = "", code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


def manifest(ver: str) -> str:
    return json.dumps({"name": "audit-workbench", "version": ver})


@pytest.mark.parametrize(
    ("path", "client"),
    [
        ("/Users/a/.claude/plugins/cache/audit-workbench/audit-workbench/1.0.5/x.py", "claude"),
        ("/Users/a/.codex/plugins/cache/audit-workbench/audit-workbench/1.0.5/x.py", "codex"),
        ("/Users/a/works/audit_workbench_skills/plugin/x.py", "local"),
    ],
)
def test_detect_client(path: str, client: str) -> None:
    assert update_check.detect_client(path) == client


def test_newer_version_returns_commands_for_the_client() -> None:
    runner = lambda args: proc(manifest("1.0.10"))  # noqa: E731
    out = update_check.check_update(runner, client="codex", installed="1.0.9")
    assert out["update_available"] is True and out["latest"] == "1.0.10"
    assert out["commands"] == update_check.COMMANDS["codex"]


@pytest.mark.parametrize("latest", ["1.0.5", "1.0.4"])
def test_same_or_older_remote_is_up_to_date(latest: str) -> None:
    out = update_check.check_update(lambda a: proc(manifest(latest)), client="claude", installed="1.0.5")
    assert out["ok"] is True and out["update_available"] is False and out["commands"] == []


def test_falls_back_to_git_clone_when_gh_fails() -> None:
    calls: list[list[str]] = []

    def runner(args: list[str]) -> subprocess.CompletedProcess:
        calls.append(args)
        if args[0] == "gh":
            return proc(code=1, stderr="not logged in")
        if args[1] == "clone":
            return proc()
        return proc(manifest("1.0.6"))

    out = update_check.check_update(runner, client="claude", installed="1.0.5")
    assert out["update_available"] is True
    assert [c[0] for c in calls] == ["gh", "git", "git"]


def test_unreachable_remote_does_not_block() -> None:
    def runner(args: list[str]) -> subprocess.CompletedProcess:
        return proc(code=128, stderr="Permission denied (publickey)")

    out = update_check.check_update(runner, client="claude", installed="1.0.5")
    assert out["ok"] is False and out["update_available"] is False
    assert "publickey" in out["message"]


def test_local_checkout_skips_the_check() -> None:
    def runner(args: list[str]) -> subprocess.CompletedProcess:
        raise AssertionError("must not reach GitHub")

    out = update_check.check_update(runner, client="local", installed="1.0.5")
    assert out["ok"] is True and out["update_available"] is False
