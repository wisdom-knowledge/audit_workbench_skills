"""Post-publish full-chain check: rules per item and the service wiring."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from audit_workbench_mcp import errors, lark, pipeline_check, readiness
from audit_workbench_mcp.auth import TokenStore
from audit_workbench_mcp.client import AdminClient
from audit_workbench_mcp.service import AuditWorkbenchService

CONFIG = {
    "feishuTableUrl": "https://x.feishu.cn/base/APP?table=tblData",
    "fieldRounds": [{"id": "round-1", "name": "一轮"}, {"id": "round-2", "name": "二轮"}],
    "auditStatusRules": [
        {"roundId": "round-1", "talentIdFieldId": "fldLook"},
        {"roundId": "round-2", "talentIdFieldId": "fldText"},
    ],
}
FIELDS = {"ok": True, "fields": [
    {"id": "fldLook", "name": "审核员talent_id", "type": "lookup", "from": "审核员列表", "select": "talent_id"},
    {"id": "fldText", "name": "talent_id", "type": "text"},
    {"id": "fldGone", "name": "一面用户 id", "type": "lookup", "from": "tblDeleted", "select": "fldX"},
]}
TABLES = {"ok": True, "tables": [{"id": "tblData", "name": "数据底表"}, {"id": "tblAud", "name": "审核员列表"}]}


def states(items: list[dict[str, Any]]) -> list[str]:
    return [i["state"] for i in items]


def test_auditors_item() -> None:
    assert pipeline_check.auditors_item(0)["state"] == "fail"
    assert pipeline_check.auditors_item(2)["state"] == "pass"


def test_talent_id_must_be_lookup_into_this_base() -> None:
    items = pipeline_check.talent_id_items(CONFIG, FIELDS, TABLES)
    assert states(items) == ["pass", "fail"]
    assert items[0]["detail"].startswith("一轮：")
    assert "不是查找引用" in items[1]["detail"]


@pytest.mark.parametrize(
    ("field_id", "expect"),
    [("fldGone", "不在当前多维表格里"), ("fldMissing", "在底表里不存在"), ("", "没有配置")],
)
def test_talent_id_failures(field_id: str, expect: str) -> None:
    config = {**CONFIG, "auditStatusRules": [{"roundId": "round-1", "talentIdFieldId": field_id}]}
    [item] = pipeline_check.talent_id_items(config, FIELDS, TABLES)
    assert item["state"] == "fail" and expect in item["detail"]


def test_talent_id_unreadable_counts_as_fail() -> None:
    [item] = pipeline_check.talent_id_items(CONFIG, {"ok": False, "message": "no perm"}, TABLES)
    assert item["state"] == "fail" and "no perm" in item["detail"]
    [item] = pipeline_check.talent_id_items(CONFIG, FIELDS, {"ok": False, "message": "x", "tables": []})
    assert item["state"] == "fail"


@pytest.mark.parametrize(
    ("state", "expect"),
    [
        ({"ok": True, "member": {"perm": "full_access"}}, "pass"),
        ({"ok": True, "member": {"perm": "edit"}}, "fail"),
        ({"ok": True, "member": None}, "fail"),
        ({"ok": False, "message": "no perm"}, "fail"),
    ],
)
def test_collaborator_item(state: dict[str, Any], expect: str) -> None:
    assert pipeline_check.collaborator_item(state)["state"] == expect


def _wf(statuses: list[str], expected: int | None = None, last_error: str | None = None) -> dict[str, Any]:
    items = [{"stage": 1, "stageLabel": "一轮", "kind": "ENQUEUE", "kindLabel": "入队", "status": s,
              "lastError": last_error, "workflowId": "w"} for s in statuses]
    return readiness.summarize_workflows({
        "publishedVersion": 1, "planError": None, "items": items,
        "expectedCount": len(items) if expected is None else expected,
    })


def test_workflow_item_states() -> None:
    assert pipeline_check.workflow_item(_wf(["DONE", "DONE"]), False)["state"] == "pass"
    assert pipeline_check.workflow_item(_wf(["DONE", "PENDING"]), True)["state"] == "pending"
    failed = pipeline_check.workflow_item(_wf(["FAILED"], last_error="boom"), False)
    assert failed["state"] == "fail" and "boom" in failed["detail"]
    assert pipeline_check.workflow_item(_wf(["DONE"], expected=2), False)["state"] == "fail"


def test_render_marks_each_item() -> None:
    result = pipeline_check.judge([pipeline_check.auditors_item(0), pipeline_check.auditors_item(1)])
    text = pipeline_check.render(result, env="boe", project_id=7, version=3)
    assert "❌ **有审核员**" in text and "✅ **有审核员**" in text and "v3" in text
    assert result["all_passed"] is False and result["failed"] == 1


# ---- service -------------------------------------------------------------------


def ok(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"status_code": 0, "status_msg": "success", "data": data})


def make_service(editor: dict[str, Any], auditor_count: int, workflows: dict[str, Any]):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if path.endswith("/audit-workbench/editor"):
            return ok(editor)
        if path.endswith("/audit-workbench/parse-feishu"):
            return ok({"app_token": "APP", "table_id": "tblData", "view_id": None, "fields": []})
        if path.endswith("/auditors"):
            return ok({"count": auditor_count, "summary": {"auditor_count": auditor_count}, "data": []})
        if path.endswith("/audit-workbench/workflows"):
            return ok(workflows)
        raise AssertionError(path)

    store = TokenStore(sources=(lambda _env: "tok",), capture=lambda *a, **k: "tok")
    client = AdminClient(store, transport=httpx.MockTransport(handler), retry_delay=0)
    return AuditWorkbenchService(client), calls


def test_verify_pipeline_runs_all_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple] = []
    monkeypatch.setattr(lark, "list_fields", lambda a, t: seen.append(("fields", a, t)) or FIELDS)
    monkeypatch.setattr(lark, "list_tables", lambda a: TABLES)
    monkeypatch.setattr(lark, "app_collaborator", lambda a: {"ok": True, "member": {"perm": "full_access"}})
    editor = {"draft": None, "published": {"version": 2, "config": CONFIG}}
    workflows = {"publishedVersion": 2, "planError": None, "expectedCount": 1, "items": [
        {"stage": 1, "kind": "ENQUEUE", "status": "DONE", "workflowId": "w"}]}
    service, calls = make_service(editor, auditor_count=1, workflows=workflows)

    out = asyncio.run(service.verify_pipeline("boe", 7, timeout=0, interval=0))
    keys = [(i["key"], i["state"]) for i in out["data"]["items"]]
    assert keys == [("auditors", "pass"), ("talent_id_lookup", "pass"), ("talent_id_lookup", "fail"),
                    ("app_collaborator", "pass"), ("workflows", "pass")]
    assert seen == [("fields", "APP", "tblData")]
    assert "全链路校验" in out["checklist_markdown"]
    parse = next(c for c in calls if c.url.path.endswith("/parse-feishu"))
    assert b"project_id" not in parse.content  # must not rewrite the field catalog


def test_verify_pipeline_requires_publish() -> None:
    service, _ = make_service({"draft": {"config": {}}, "published": None}, 0, {})
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        asyncio.run(service.verify_pipeline("boe", 7))
    assert exc.value.code == errors.NOT_FOUND
