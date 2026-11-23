"""Backend run logs in Aliyun SLS, read as the current aliyun CLI user.

Only used by trace to back up the post-submit verdict: the backend logs the Feishu
writeback result, the written / skipped columns and every enqueue call with the
record_id, none of which is stored in MySQL. Never raises; a missing CLI or missing
permission comes back as {"ok": False, "message": ...} so trace can say "未核验".
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

Runner = Callable[[list[str]], subprocess.CompletedProcess]

REGION = "cn-beijing"
PROJECT = "k8s-log-c32adc70c4c89414982ad277c336722a5"
LOGSTORES = {"boe": "meetchances-log-boe", "prod": "meetchances-log-prod"}
MAX_WINDOW = timedelta(days=7)
LINE_LIMIT = 100
BEIJING = timezone(timedelta(hours=8))
# record_id 只放进 SLS 查询语句，限制字符防止拼出别的查询条件
_RECORD_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# 只是请求飞书的 HTTP 行，对判断没有帮助
_NOISE_LOGGERS = {"httpx", "httpcore", "app.access"}


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)


def _parse_line(content: str) -> dict[str, Any] | None:
    try:
        row = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(row, dict) or not row.get("message"):
        return None
    if row.get("logger") in _NOISE_LOGGERS:
        return None
    try:
        ts = datetime.fromisoformat(str(row.get("timestamp"))).astimezone(BEIJING)
    except ValueError:
        return None
    return {
        "time": ts,
        "level": row.get("level") or "",
        "logger": row.get("logger") or "",
        "message": str(row["message"]),
        "traceId": row.get("trace_id") or "",
    }


def window(since: datetime | None, now: datetime | None = None) -> tuple[int, int]:
    """[since, now] in epoch seconds, no longer than MAX_WINDOW. Naive times are Beijing time."""
    now = now or datetime.now(BEIJING)
    start = now - MAX_WINDOW
    if since is not None:
        since = since if since.tzinfo else since.replace(tzinfo=BEIJING)
        start = max(start, since - timedelta(minutes=1))
    return int(start.timestamp()), int(now.timestamp())


def search_record(
    env: str,
    record_id: str,
    since: datetime | None = None,
    *,
    now: datetime | None = None,
    runner: Runner = _run,
) -> dict[str, Any]:
    """Backend log lines mentioning record_id, newest first."""
    logstore = LOGSTORES.get(env)
    if logstore is None:
        return {"ok": False, "message": f"环境 {env} 没有对应的日志库", "logs": []}
    if not _RECORD_ID.match(record_id or ""):
        return {"ok": False, "message": "record_id 格式不对，没有查运行日志", "logs": []}
    if runner is _run and not shutil.which("aliyun"):
        return {"ok": False, "message": "本机没有安装 aliyun CLI", "logs": []}
    start, end = window(since, now)
    body = {"from": start, "to": end, "query": record_id, "line": LINE_LIMIT, "reverse": True}
    args = [
        "aliyun", "sls", "GetLogsV2", "--region", REGION, "--project", PROJECT,
        "--logstore", logstore, "--body", json.dumps(body),
    ]
    try:
        proc = runner(args)
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "查 SLS 超时", "logs": []}
    out = (proc.stdout or "").strip()
    try:
        data = json.loads(out)
    except ValueError:
        detail = (out + (proc.stderr or "")).strip()[:200]
        return {"ok": False, "message": f"查 SLS 失败：{detail}", "logs": []}
    if not isinstance(data, dict) or "data" not in data:
        return {"ok": False, "message": f"查 SLS 失败：{str(data)[:200]}", "logs": []}
    rows = data.get("data") or []
    logs = [p for p in (_parse_line(r.get("content") or "") for r in rows) if p]
    return {
        "ok": True,
        "message": None,
        "logs": logs,
        "truncated": len(rows) >= LINE_LIMIT,
        "logstore": logstore,
    }


def check_access(env: str, *, runner: Runner = _run) -> dict[str, Any]:
    """Whether the aliyun CLI user can read this env's logstore."""
    logstore = LOGSTORES.get(env)
    if logstore is None:
        return {"ok": False, "message": f"环境 {env} 没有对应的日志库"}
    if runner is _run and not shutil.which("aliyun"):
        return {"ok": False, "message": "本机没有安装 aliyun CLI"}
    args = ["aliyun", "sls", "GetLogStore", "--region", REGION, "--project", PROJECT, "--logstore", logstore]
    try:
        proc = runner(args)
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "查 SLS 超时"}
    out = (proc.stdout or "").strip()
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    if isinstance(data, dict) and data.get("logstoreName") == logstore:
        return {"ok": True, "message": None, "logstore": logstore}
    detail = (out + (proc.stderr or "")).strip()[:200]
    return {"ok": False, "message": f"读不了日志库 {logstore}：{detail}"}
