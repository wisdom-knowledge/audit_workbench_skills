"""Workflow status derivation, waiting, and the readiness checklist."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from audit_workbench_mcp import errors, readiness
from audit_workbench_mcp.auth import TokenStore
from audit_workbench_mcp.client import AdminClient
from audit_workbench_mcp.service import AuditWorkbenchService

WF_PATH = "/api/v1/admin/projects/7/audit-workbench/workflows"
VALIDATE_PATH = "/api/v1/admin/projects/7/audit-workbench/validate"
AUDITORS_PATH = "/api/v1/admin/projects/7/auditors"
EDITOR_PATH = "/api/v1/admin/projects/7/audit-workbench/editor"


def ok(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"status_code": 0, "status_msg": "success", "data": data})


def row(stage: int = 1, status: str = "DONE", last_error: str | None = None) -> dict[str, Any]:
    return {
        "stage": stage, "stageLabel": f"{stage}轮", "kind": "ENQUEUE", "kindLabel": "入队",
        "status": status, "attempts": 1, "maxAttempts": 5, "lastError": last_error,
        "workflowId": "wkf", "workflowUrl": "u", "syncedAt": None, "updatedAt": None,
    }


def wf(items: list[dict[str, Any]], *, version: int = 2, expected: int | None = None,
       plan_error: str | None = None) -> dict[str, Any]:
    return {
        "projectId": 7, "publishedVersion": version,
        "expectedCount": len(items) if expected is None else expected,
        "planError": plan_error, "items": items,
    }


def make_service(handler) -> tuple[AuditWorkbenchService, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    store = TokenStore(sources=(lambda _env: "tok",), capture=lambda *a, **k: "tok")
    client = AdminClient(store, transport=httpx.MockTransport(_record), retry_delay=0)
    return AuditWorkbenchService(client), calls


# ---- display status and summary ----------------------------------------------


@pytest.mark.parametrize(
    ("status", "last_error", "expected"),
    [
        ("DONE", None, readiness.SYNCED),
        ("FAILED", "x", readiness.FAILED),
        ("RUNNING", None, readiness.RUNNING),
        ("PENDING", None, readiness.PENDING),
        ("PENDING", "飞书超时", readiness.RETRYING),
    ],
)
def test_display_status(status: str, last_error: str | None, expected: str) -> None:
    assert readiness.workflow_display_status(row(status=status, last_error=last_error)) == expected


def test_all_synced_is_settled_without_problems() -> None:
    s = readiness.summarize_workflows(wf([row(1), row(2)]))
    assert s["settled"] is True and s["needs_attention"] is False
    assert s["counts"] == {"synced": 2}


def test_missing_rows_are_flagged() -> None:
    s = readiness.summarize_workflows(wf([row(1)], expected=3))
    assert s["needs_attention"] is True
    assert "应有 3 条" in s["problems"][0]


def test_plan_error_and_unpublished_are_flagged() -> None:
    assert "没有排队" in readiness.summarize_workflows(wf([], plan_error="缺字段"))["problems"][0]
    assert "还没有发布" in readiness.summarize_workflows(wf([], version=0))["problems"][0]


def test_stop_waiting_rules() -> None:
    pending = readiness.summarize_workflows(wf([row(1), row(2, "PENDING")]))
    assert readiness.stop_waiting(pending) is False
    retrying = readiness.summarize_workflows(wf([row(1, "PENDING", "无权限")]))
    assert readiness.stop_waiting(retrying) is True
    # Rows are written in the publish transaction, so no rows after publish means
    # they were never queued; waiting longer will not change that.
    empty = readiness.summarize_workflows(wf([], expected=2))
    assert readiness.stop_waiting(empty) is True
    assert readiness.stop_waiting(readiness.summarize_workflows(wf([row(1)]))) is True


# ---- wait_workflows ------------------------------------------------------------


def test_wait_returns_once_synced() -> None:
    responses = iter([wf([row(1, "PENDING")]), wf([row(1, "RUNNING")]), wf([row(1)])])
    service, calls = make_service(lambda _r: ok(next(responses)))
    out = asyncio.run(service.wait_workflows("boe", 7, timeout=10, interval=0))
    assert out["timed_out"] is False and out["polls"] == 3
    assert out["data"]["settled"] is True
    assert len(calls) == 3


def test_wait_stops_early_on_first_error() -> None:
    responses = iter([wf([row(1, "PENDING")]), wf([row(1, "PENDING", "应用无权限")])])
    service, _ = make_service(lambda _r: ok(next(responses)))
    out = asyncio.run(service.wait_workflows("boe", 7, timeout=10, interval=0))
    assert out["timed_out"] is False
    assert "应用无权限" in out["data"]["problems"][0]


def test_wait_times_out_without_claiming_success() -> None:
    service, _ = make_service(lambda _r: ok(wf([row(1, "PENDING")])))
    out = asyncio.run(service.wait_workflows("boe", 7, timeout=0, interval=0))
    assert out["timed_out"] is True
    assert out["data"]["settled"] is False
    assert "不代表成功" in out["data"]["problems"][-1]


# ---- readiness checklist -------------------------------------------------------

CONFIG = {
    "fieldRounds": [
        {"id": "round-1", "name": "第1轮", "fields": [
            {"id": "fldS", "name": "审核状态", "options": ["待审核", "通过", "打回"]},
        ]},
    ],
    "auditStatusRules": [
        {"roundId": "round-1", "statusFieldId": "fldS",
         "statusValueMapping": {"待审核": "待审核", "通过": "审核通过"}},
    ],
}


def readiness_handler(validation: dict[str, Any], auditor_count: int, editor: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == VALIDATE_PATH:
            return ok(validation)
        if path == AUDITORS_PATH:
            return ok({"count": auditor_count, "summary": {"auditor_count": auditor_count}, "data": []})
        if path == EDITOR_PATH:
            return ok(editor)
        raise AssertionError(path)

    return handler


def test_readiness_only_uses_backend_validation_and_all_items_block() -> None:
    validation = {
        "publishable": False,
        "errors": [{"rule": "fields_non_empty", "message": "至少一个字段", "step": 1, "field_key": None}],
        "workflowErrors": [{"rule": "workflow_plan_invalid", "message": "缺 talent_id", "step": 2}],
        "workbenchType": 1, "workflowCount": 0,
    }
    service, calls = make_service(readiness_handler(validation, auditor_count=0))
    out = asyncio.run(service.check_readiness("boe", 7, CONFIG))["data"]

    codes = {i["code"]: i["level"] for i in out["items"]}
    assert codes == {"fields_non_empty": "blocker", "workflow_plan_invalid": "blocker"}
    assert out["summary"]["ready_to_publish"] is False
    assert out["summary"]["blockers"] == 2
    # Auditors and local status mapping are no longer part of the pre-publish check.
    assert {c.url.path for c in calls} == {VALIDATE_PATH}
    sent = json.loads(calls[0].content)
    assert sent == {"config": CONFIG}


def test_readiness_passes_when_backend_reports_nothing() -> None:
    validation = {"publishable": True, "errors": [], "workflowErrors": [],
                  "workbenchType": 1, "workflowCount": 1}
    service, _ = make_service(readiness_handler(validation, auditor_count=0))
    out = asyncio.run(service.check_readiness("boe", 7, CONFIG))["data"]
    assert out["summary"]["ready_to_publish"] is True
    assert out["items"] == []


def test_readiness_falls_back_to_draft_then_errors_when_nothing_saved() -> None:
    validation = {"errors": [], "workflowErrors": [], "workbenchType": 1, "workflowCount": 1}
    editor = {"draft": {"config": CONFIG, "updated_at": "t"}, "published": None}
    service, _ = make_service(readiness_handler(validation, 1, editor))
    assert asyncio.run(service.check_readiness("boe", 7))["data"]["summary"]["config_source"] == "draft"

    service, _ = make_service(readiness_handler(validation, 1, {"draft": None, "published": None}))
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        asyncio.run(service.check_readiness("boe", 7))
    assert exc.value.code == errors.NOT_FOUND
