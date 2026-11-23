"""check_setup: admin login, lark-cli identity and SLS read access, each reported on its own."""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any

import httpx
import pytest

from audit_workbench_mcp import lark, setup_check, sls
from audit_workbench_mcp.auth import TokenStore
from audit_workbench_mcp.client import AdminClient


def _client(status: int) -> AdminClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"detail": "no"})
        return httpx.Response(200, json={"status_code": 0, "status_msg": "success", "data": {"items": []}})
    store = TokenStore(sources=(lambda _e: "tok",), capture=lambda *a, **k: "tok")
    return AdminClient(store, transport=httpx.MockTransport(handler), retry_delay=0)


def _patch(monkeypatch: pytest.MonkeyPatch, lark_ok: bool, sls_ok: bool) -> None:
    monkeypatch.setattr(lark, "auth_status", lambda: {"ok": lark_ok, "user": "张三", "message": "未登录"})
    monkeypatch.setattr(sls, "check_access", lambda env: {"ok": sls_ok, "logstore": "meetchances-log-boe",
                                                           "message": "本机没有安装 aliyun CLI"})


def test_all_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, True, True)
    out = asyncio.run(setup_check.check_setup(_client(200), "boe"))
    assert out["ready"] is True and [i["state"] for i in out["items"]] == ["pass", "pass", "pass"]
    assert "环境 boe" in out["setup_markdown"] and "已登录：张三" in out["setup_markdown"]


def test_missing_sls_is_only_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, True, False)
    out = asyncio.run(setup_check.check_setup(_client(200), "boe"))
    assert out["ready"] is True and out["items"][2]["state"] == "warn"


def test_forbidden_admin_and_missing_lark_block(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, False, True)
    out = asyncio.run(setup_check.check_setup(_client(403), "prod"))
    admin, lark_item, _ = out["items"]
    assert out["ready"] is False
    assert admin["state"] == "fail" and "没有管理端权限" in admin["detail"]
    assert lark_item["state"] == "fail" and "lark-cli auth login" in lark_item["fix"]


def test_lark_auth_status_parses_identity() -> None:
    payload = {"identities": {"user": {"status": "ready", "userName": "张三"}}}

    def run(args: list[str]) -> subprocess.CompletedProcess:
        assert args == ["lark-cli", "auth", "status"]
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
    assert lark.auth_status(run) == {"ok": True, "user": "张三", "message": None}


def test_sls_check_access() -> None:
    def run(payload: Any):
        def inner(args: list[str]) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(args, 0, stdout=payload, stderr="")
        return inner
    ok = sls.check_access("prod", runner=run(json.dumps({"logstoreName": "meetchances-log-prod", "ttl": 90})))
    assert ok["ok"] is True
    denied = sls.check_access("prod", runner=run("ERROR: Unauthorized"))
    assert denied["ok"] is False and "Unauthorized" in denied["message"]
