"""sls: search backend run logs by record_id through the aliyun CLI, never raise."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from typing import Any

from audit_workbench_mcp import sls

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=sls.BEIJING)


def _line(ts: str, message: str, logger: str = "app.services.audit_workbench_task") -> dict[str, Any]:
    return {"content": json.dumps({"timestamp": ts, "level": "INFO", "logger": logger,
                                   "message": message, "trace_id": "t1"})}


def _runner(payload: Any, seen: list[list[str]] | None = None):
    def run(args: list[str]) -> subprocess.CompletedProcess:
        if seen is not None:
            seen.append(args)
        out = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")
    return run


def test_search_builds_query_and_parses_lines() -> None:
    seen: list[list[str]] = []
    payload = {"data": [
        _line("2026-11-23T03:00:00+00:00", "audit_workbench submit project=1 record=rec1 written=['a']"),
        _line("2026-11-23T03:00:00+00:00", "HTTP Request: PUT ...", logger="httpx"),
        {"content": "             HTTP/1.1\" 200"},
    ], "meta": {"count": 3}}
    since = datetime(2026, 11, 23, 9, 0)  # naive = 北京时间
    out = sls.search_record("prod", "rec1", since, now=NOW, runner=_runner(payload, seen))
    assert out["ok"] is True and len(out["logs"]) == 1
    assert out["logs"][0]["time"].hour == 11 and out["logs"][0]["traceId"] == "t1"
    args = seen[0]
    assert args[args.index("--logstore") + 1] == "meetchances-log-prod"
    body = json.loads(args[args.index("--body") + 1])
    assert body["query"] == "rec1" and body["to"] == int(NOW.timestamp())
    assert body["from"] == int((since.replace(tzinfo=sls.BEIJING) - timedelta(minutes=1)).timestamp())


def test_window_is_capped() -> None:
    start, end = sls.window(datetime(2026, 1, 1), NOW)
    assert end - start == int(sls.MAX_WINDOW.total_seconds())


def test_bad_record_id_and_env_do_not_call_cli() -> None:
    def boom(_args: list[str]) -> subprocess.CompletedProcess:
        raise AssertionError("should not run")
    assert sls.search_record("prod", "rec1 or *", runner=boom)["ok"] is False
    assert sls.search_record("dev", "rec1", runner=boom)["ok"] is False


def test_cli_error_and_timeout_are_reported() -> None:
    out = sls.search_record("boe", "rec1", now=NOW, runner=_runner("ERROR: Forbidden.NoPermission"))
    assert out["ok"] is False and "Forbidden" in out["message"]

    def slow(args: list[str]) -> subprocess.CompletedProcess:
        raise subprocess.TimeoutExpired(args, 60)
    assert sls.search_record("boe", "rec1", now=NOW, runner=slow)["message"] == "查 SLS 超时"
