"""onboard_status: stage judgment from online state, and the one-call service read."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from audit_workbench_mcp import lark, onboard_status, readiness
from audit_workbench_mcp.auth import TokenStore
from audit_workbench_mcp.client import AdminClient
from audit_workbench_mcp.service import AuditWorkbenchService


def _rules(*urls: str) -> dict:
    return {"auditStatusRules": [{"roundId": f"round-{i + 1}", "enqueueViewUrl": u} for i, u in enumerate(urls)]}


def _row(label: str, sync: str = "synced", enabled: bool | None = True, repaired: bool | None = None) -> dict:
    return {"label": label, "sync": sync, "enabled": enabled, "repaired": repaired}


PUBLISHED = {"published": {"version": 2}}
OK_WF = {"problems": []}


@pytest.mark.parametrize(
    ("editor", "workflows", "rows", "count", "binding", "stage"),
    [
        ({}, None, [], 0, [], 1),
        ({"draft": {"config": _rules("v1", "")}}, None, [], 0, [], 2),
        ({"draft": {"config": _rules("v1", "v2")}}, None, [], 0, [], 3),
        ({**PUBLISHED, "draft": {"config": _rules("v1")}}, None, [], 0, [], 3),
        (PUBLISHED, {"problems": ["二轮入队工作流已到重试上限"]}, [_row("二轮")], 0, [], 4),
        (PUBLISHED, OK_WF, [_row("一轮", sync="pending")], 0, [], 4),
        (PUBLISHED, OK_WF, [_row("一轮", enabled=False)], 0, [], 4),
        (PUBLISHED, OK_WF, [_row("一轮 · 审核操作", enabled=False, repaired=False)], 0, [], 4),
        (PUBLISHED, OK_WF, [_row("一轮", enabled=None)], 0, [], 4),
        (PUBLISHED, OK_WF, [_row("一轮")], 0, [], 5),
        (PUBLISHED, OK_WF, [_row("一轮")], 2, [{"talentId": 1, "state": "UNBOUND"}], 5),
        (PUBLISHED, OK_WF, [_row("一轮")], 2, [{"talentId": 1, "state": "UNVERIFIED"}], 5),
        (PUBLISHED, OK_WF, [_row("一轮")], 2, [{"talentId": 1, "state": "BOUND"}], 6),
    ],
)
def test_judge_stage(editor, workflows, rows, count, binding, stage) -> None:
    out = onboard_status.judge(editor, workflows, rows, count, binding)
    assert out["stage"] == stage and out["stage_name"] == onboard_status.STAGE_NAMES[stage]


def test_judge_details() -> None:
    out = onboard_status.judge({"draft": {"config": _rules("v1", "", " ")}}, None, [], 0, [])
    assert out["missing_views"] == ["round-2", "round-3"]
    out = onboard_status.judge({**PUBLISHED, "draft": {"config": _rules("v1")}}, None, [], 0, [])
    assert out["draft_after_publish"] is True and "v2" in out["reason"]
    out = onboard_status.judge(PUBLISHED, OK_WF, [_row("一轮")], 1, [{"talentId": 9, "state": "UNBOUND"}])
    assert out["binding"] == {"unbound": [9], "unverified": []}


def _service(routes: dict[str, Any]):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        data = next(v for k, v in routes.items() if request.url.path.endswith(k))
        return httpx.Response(200, json={"status_code": 0, "status_msg": "success", "data": data})

    store = TokenStore(sources=(lambda _e: "tok",), capture=lambda *a, **k: "tok")
    client = AdminClient(store, transport=httpx.MockTransport(handler), retry_delay=0)
    return AuditWorkbenchService(client), calls


def _wf_item(wid: str) -> dict:
    return {"stage": 1, "stageLabel": "一轮", "kind": "ENQUEUE", "kindLabel": "入队",
            "status": "DONE", "lastError": None, "workflowId": wid, "workflowUrl": f"https://f/{wid}"}


def test_service_reads_all_four_and_feishu_state(monkeypatch: pytest.MonkeyPatch) -> None:
    routes = {
        "/audit-workbench/editor": {"draft": None, "published": {"version": 1, "config": {}}},
        "/audit-workbench/workflows": {"projectId": 7, "publishedVersion": 1, "appToken": "app",
                                       "expectedCount": 1, "items": [_wf_item("w1")]},
        "/auditors": {"count": 1, "summary": {"auditor_count": 1, "total_pending_count": 0}, "data": []},
        "/auditors/feishu-binding": {"items": [{"talentId": 5, "state": "UNBOUND", "accounts": []}]},
    }
    service, calls = _service(routes)
    monkeypatch.setattr(lark, "get_workflow", lambda _a, _w: {"ok": True, "status": "enabled", "steps": []})
    out = asyncio.run(service.onboard_status("boe", 7))
    assert out["data"]["stage"] == 5 and out["data"]["binding"]["unbound"] == [5]
    assert len(calls) == 4


def test_service_skips_feishu_reads_before_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    routes = {
        "/audit-workbench/editor": {"draft": {"config": _rules(""), "updated_at": "t"}, "published": None},
        "/audit-workbench/workflows": {"projectId": 7, "publishedVersion": 0, "items": []},
        "/auditors": {"count": 0, "summary": {"auditor_count": 0}, "data": []},
        "/auditors/feishu-binding": {"items": []},
    }
    service, _ = _service(routes)

    def _boom(*_a):
        raise AssertionError("should not read Feishu before publish")

    monkeypatch.setattr(lark, "get_workflow", _boom)
    out = asyncio.run(service.onboard_status("boe", 7))
    assert out["data"]["stage"] == 2 and out["data"]["missing_views"] == ["round-1"]
