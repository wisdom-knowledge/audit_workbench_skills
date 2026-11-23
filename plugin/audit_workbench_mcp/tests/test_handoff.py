"""Hand-off: collaborator, pre-publish checklist, workflow enable rules, auditor binding."""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any

import httpx
import pytest

from audit_workbench_mcp import handoff, lark, readiness
from audit_workbench_mcp.auth import TokenStore
from audit_workbench_mcp.client import AdminClient
from audit_workbench_mcp.service import AuditWorkbenchService


def proc(payload: dict, code: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=json.dumps(payload), stderr="")


class FakeLark:
    """Scripted lark-cli: responses keyed by the subcommand, records every call."""

    def __init__(self, responses: dict[str, list[dict]]) -> None:
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        key = next(k for k in self.responses if k in args)
        return proc(self.responses[key].pop(0))


# ---- ensure_app_collaborator ---------------------------------------------------


def _members(perm: str | None) -> dict:
    items = [] if perm is None else [{"member_type": "appid", "member_id": lark.RECRUIT_APP_ID, "perm": perm}]
    return {"ok": True, "data": {"items": items}}


@pytest.mark.parametrize(
    ("perm", "action", "write_cmd"),
    [("full_access", "present", None), (None, "added", "permission.members"), ("view", "upgraded", "PUT")],
)
def test_ensure_app_collaborator(perm, action, write_cmd) -> None:
    fake = FakeLark({"+member-list": [_members(perm)], "permission.members": [{"ok": True}], "PUT": [{"ok": True}]})
    out = lark.ensure_app_collaborator("app", runner=fake)
    assert out["ok"] is True and out["action"] == action
    assert len(fake.calls) == (1 if write_cmd is None else 2)
    if write_cmd:
        assert write_cmd in fake.calls[1] and "--as" in fake.calls[1]


def test_ensure_app_collaborator_reports_failure() -> None:
    fake = FakeLark({"+member-list": [{"ok": False, "error": {"message": "no permission"}}]})
    out = lark.ensure_app_collaborator("app", runner=fake)
    assert out == {"ok": False, "reason": "member_list_failed", "message": "no permission"}


def test_manual_clear_step_detection() -> None:
    clear = {"type": "SetRecordAction", "data": {"field_values": [{"field_name": "审核操作", "value": []}]}}
    keep = {"type": "SetRecordAction", "data": {"field_values": [{"field_name": "状态", "value": [{"x": 1}]}]}}
    assert lark.has_manual_clear_step([keep, clear]) is True
    assert lark.has_manual_clear_step([keep]) is False


# ---- pre-publish checklist -------------------------------------------------------

CONFIG = {
    "sourceFields": [{"id": "s1", "name": "一轮状态"}, {"id": "t1", "name": "一轮talent"}, {"id": "a1", "name": "一轮操作"}],
    "auditStatusRules": [{"roundId": "round-1", "statusFieldId": "s1", "talentIdFieldId": "t1", "auditActionFieldId": "a1"}],
}


def test_planned_workflows_template_one_and_two() -> None:
    one = handoff.planned_workflows(CONFIG, 1)
    assert [(w["round"], w["kind"]) for w in one] == [("轮次一", "入队")]
    assert "「一轮状态」「一轮talent」" in one[0]["detail"]
    two = handoff.planned_workflows(CONFIG, 2)
    assert [w["kind"] for w in two] == ["入队", "审核操作"] and two[1]["needs_repair"]


def test_checklist_text() -> None:
    text = handoff.render_pre_publish_checklist(
        env="boe", project_id=7, page_url="u", draft_updated_at="t", workbench_type=2,
        planned=handoff.planned_workflows(CONFIG, 2), blockers=["字段列表不能为空"],
    )
    assert "- [ ] **配置信息是否无误**" in text and "- [ ] **工作流配置是否无误**" in text
    assert "需要人工修补" in text and "**发布前必须先处理：**" in text
    one = handoff.render_pre_publish_checklist(
        env="boe", project_id=7, page_url="u", draft_updated_at="t", workbench_type=1,
        planned=handoff.planned_workflows(CONFIG, 1), blockers=[],
    )
    assert "人工修补" not in one


# ---- workflow rows / enable eligibility ------------------------------------------


def _summary(items: list[dict]) -> dict:
    return readiness.summarize_workflows(
        {"projectId": 7, "publishedVersion": 1, "appToken": "app", "expectedCount": len(items), "items": items}
    )


def _item(wid: str, kind: str = "ENQUEUE", status: str = "DONE") -> dict:
    return {"stage": 1, "stageLabel": "一轮", "kind": kind, "kindLabel": "入队" if kind == "ENQUEUE" else "审核操作",
            "status": status, "lastError": None, "workflowId": wid, "workflowUrl": f"https://f/{wid}"}


def test_enable_rules() -> None:
    summary = _summary([
        _item("w1"),                                  # synced, disabled → enable
        _item("w2", status="PENDING"),                # not synced
        _item("w3", kind="AUDIT_ACTION"),             # not repaired
        _item("w4", kind="AUDIT_ACTION"),             # repaired → enable
        _item("w5"),                                  # already enabled
        _item("w6"),                                  # cannot read
    ])
    states = {
        "w1": {"ok": True, "status": "disabled", "repaired": False},
        "w3": {"ok": True, "status": "disabled", "repaired": False},
        "w4": {"ok": True, "status": "disabled", "repaired": True},
        "w5": {"ok": True, "status": "enabled", "repaired": False},
        "w6": {"ok": False},
    }
    rows = {r["workflow_id"]: r for r in handoff.workflow_rows(summary, states)}
    assert {w for w, r in rows.items() if r["can_enable"]} == {"w1", "w4"}
    assert rows["w2"]["skip_reason"] == "同步未完成"
    assert rows["w3"]["skip_reason"] == "等待人工修补"
    assert rows["w5"]["skip_reason"] == "已启用"
    assert rows["w6"]["skip_reason"] == "读不到飞书上的工作流状态"
    assert rows["w1"]["repaired"] is None  # only audit-action workflows need repair
    text = handoff.render_workflows(list(rows.values()), [], False)
    assert "请先修补以下工作流" in text and "回复「确认启用」" in text


def test_manual_status_is_terminal_and_flagged() -> None:
    summary = _summary([dict(_item("w1", kind="AUDIT_ACTION", status="MANUAL"), lastError="请按新配置修改")])
    assert summary["items"][0]["display_status"] == readiness.MANUAL
    assert summary["settled"] is True and "需人工同步" in summary["problems"][0]


# ---- binding report -------------------------------------------------------------


def test_binding_report_marks_unbound_red_and_keeps_unverified_separate() -> None:
    text = handoff.render_binding([
        {"talentId": 1, "talentName": "张三", "state": "BOUND", "accounts": [{"name": "张三"}]},
        {"talentId": 2, "talentName": "李四", "state": "UNBOUND", "accounts": []},
        {"talentId": 3, "talentName": "王五", "state": "UNVERIFIED", "accounts": []},
    ])
    assert "共 3 人，已绑定 1 人" in text
    assert "🔴 **李四（talent_id 2）未绑定飞书账号" in text
    assert "❔ 王五（3）" in text and "🔴 **王五" not in text
    assert text.rstrip().splitlines()[-1].startswith("🔴")  # unbound reminders come last


# ---- service: enable with confirm, binding endpoint -------------------------------


def make_service(routes: dict[str, Any]):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        data = next(v for k, v in routes.items() if request.url.path.endswith(k))
        return httpx.Response(200, json={"status_code": 0, "status_msg": "success", "data": data})

    store = TokenStore(sources=(lambda _e: "tok",), capture=lambda *a, **k: "tok")
    return AuditWorkbenchService(AdminClient(store, transport=httpx.MockTransport(handler), retry_delay=0)), calls


def test_enable_previews_then_enables_and_reads_back(monkeypatch: pytest.MonkeyPatch) -> None:
    wf = {"projectId": 7, "publishedVersion": 1, "appToken": "app", "expectedCount": 1, "items": [_item("w1")]}
    service, _ = make_service({"/workflows": wf})
    status = {"w1": "disabled"}
    enabled: list[str] = []
    monkeypatch.setattr(lark, "get_workflow", lambda _a, wid: {"ok": True, "status": status[wid], "steps": []})

    def _enable(_a: str, wid: str) -> dict:
        enabled.append(wid)
        status[wid] = "enabled"
        return {"ok": True}

    monkeypatch.setattr(lark, "enable_workflow", _enable)
    preview = asyncio.run(service.enable_workflows("boe", 7))
    assert preview["executed"] is False and preview["request"]["enable"] == ["一轮 · 入队"]
    assert enabled == []
    out = asyncio.run(service.enable_workflows("boe", 7, confirm=True))
    assert enabled == ["w1"] and out["data"]["enabled"] == [{"label": "一轮 · 入队", "ok": True, "message": ""}]


def test_check_auditor_binding_passes_talent_ids() -> None:
    data = {"items": [{"talentId": 2, "talentName": "李四", "state": "UNBOUND", "accounts": []}]}
    service, calls = make_service({"/auditors/feishu-binding": data})
    out = asyncio.run(service.check_auditor_binding("boe", 7, [2, 3]))
    assert calls[0].url.params.get_list("talent_ids") == ["2", "3"]
    assert out["unbound"] == [2] and "🔴" in out["binding_markdown"]
