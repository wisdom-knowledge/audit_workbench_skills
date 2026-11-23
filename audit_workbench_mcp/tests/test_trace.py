"""trace: fill the workflow-enabled step from Feishu, re-derive the verdict, render the report."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from audit_workbench_mcp import lark
from audit_workbench_mcp import trace as tr
from audit_workbench_mcp.auth import TokenStore
from audit_workbench_mcp.client import AdminClient
from audit_workbench_mcp.service import AuditWorkbenchService


def _checks(workflow_state: str = "unverified") -> list[dict[str, Any]]:
    return [
        {"key": "published", "label": "配置已发布", "state": "pass", "evidence": "已发布 v1", "next": None},
        {"key": "view", "label": "记录满足本轮入队条件", "state": "pass", "evidence": "满足视图", "next": None},
        {"key": "workflow", "label": "入队工作流已同步并启用", "state": workflow_state,
         "evidence": "第 1 轮入队工作流已同步，飞书上是否启用需要回读", "next": "回读",
         "workflowId": "wkf1"},
        {"key": "task", "label": "任务已建", "state": "fail", "evidence": "第 1 轮没有任务", "next": "改动一次记录"},
    ]


def test_disabled_workflow_becomes_first_fail() -> None:
    checks = _checks()
    tr.apply_workflow_state(checks, {"ok": True, "status": "disabled"})
    out = tr.diagnose(checks)
    assert out["step"] == "workflow" and "没有启用" in out["message"] and "enable_workflows" in out["next"]


def test_enabled_workflow_passes_and_task_stays_first_fail() -> None:
    checks = _checks()
    tr.apply_workflow_state(checks, {"ok": True, "status": "enabled"})
    assert checks[2]["state"] == "pass" and tr.diagnose(checks)["step"] == "task"


def test_unreadable_workflow_stays_unverified() -> None:
    checks = _checks()
    tr.apply_workflow_state(checks, {"ok": False, "message": "no permission"})
    assert checks[2]["state"] == "unverified" and "回读失败：no permission" in checks[2]["evidence"]


def test_all_pass_and_render() -> None:
    checks = [{"key": "published", "label": "配置已发布", "state": "pass", "evidence": "已发布 v1", "next": None}]
    diag = tr.diagnose(checks, "https://x?record=r")
    assert diag["result"] == "all_pass" and "record=r" in diag["next"]
    text = tr.render({
        "recordId": "r", "stage": 1, "checks": checks, "diagnosis": diag,
        "feishu": {"rounds": [{"stage": 1, "statusLabel": "待审核", "taskStatusLabel": "审核通过",
                               "consistent": False, "viewActive": True, "viewMatched": True}]},
    })
    assert "各环节都通过" in text and "| 1 | 待审核 | 审核通过 | **否** | 满足 |" in text


def test_service_reads_enabled_state(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "recordId": "rec1", "stage": 1, "dataUrl": "", "checks": _checks(),
        "diagnosis": {"result": "blocked", "step": "task"},
        "workflows": {"appToken": "app"}, "feishu": {"ok": True, "rounds": []},
    }
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status_code": 0, "status_msg": "success", "data": payload})

    store = TokenStore(sources=(lambda _e: "tok",), capture=lambda *a, **k: "tok")
    service = AuditWorkbenchService(AdminClient(store, transport=httpx.MockTransport(handler), retry_delay=0))
    monkeypatch.setattr(lark, "get_workflow", lambda app, wid: {"ok": True, "status": "disabled"})
    out = asyncio.run(service.trace("boe", 7, "rec1", talent_id=5))
    assert seen[0].url.path.endswith("/projects/7/audit-workbench/trace")
    assert seen[0].url.params["record_id"] == "rec1" and "stage" not in seen[0].url.params
    assert out["data"]["diagnosis"]["step"] == "workflow" and "卡在：入队工作流已同步并启用" in out["trace_markdown"]


def test_render_submit_section_and_action_column() -> None:
    checks = [{"key": "task", "label": "任务已建", "state": "pass", "evidence": "已存在", "next": None}]
    text = tr.render({
        "recordId": "r", "stage": 1, "checks": checks, "diagnosis": tr.diagnose(checks),
        "submit": {
            "result": "action_workflow_not_run", "message": "审核操作列为「通过」，审核操作工作流没有跑",
            "next": "查审核操作工作流", "viewNote": "专家端记录过 1 次看题（专家端上报，仅供参考）",
            "lastSubmit": {"diff": {"审核操作": {"from": None, "to": "通过"}}},
        },
        "feishu": {"rounds": [{"stage": 1, "statusLabel": "待审核", "taskStatusLabel": "待审核",
                               "consistent": True, "viewActive": False,
                               "actionConfigured": True, "actionValue": "通过"}]},
    })
    assert "**提交后**" in text and "下一步：查审核操作工作流" in text
    assert "最近一次提交改了：审核操作：空 → 通过" in text and "仅供参考" in text
    assert "| 1 | 待审核 | 待审核 | 是 | 无筛选，按状态 | 通过 |" in text


def _log(minute: int, message: str) -> dict[str, Any]:
    from datetime import datetime

    from audit_workbench_mcp import sls
    return {"time": datetime(2026, 11, 23, 10, minute, tzinfo=sls.BEIJING), "level": "INFO",
            "logger": "x", "message": message, "traceId": f"t{minute}"}


def _data(result: str, submit_at: str | None = None) -> dict[str, Any]:
    last = {"time": submit_at} if submit_at else None
    return {"stage": 1, "tasks": [{"stage": 1, "createdAt": "2026-11-23T09:00:00"}],
            "submit": {"result": result, "message": "m", "next": "n", "lastSubmit": last}}


def test_log_since_uses_task_created_at() -> None:
    assert tr.log_since(_data("not_submitted")).hour == 9


def test_writeback_failure_in_logs_becomes_certain() -> None:
    data = _data("not_submitted")
    tr.apply_logs(data, {"ok": True, "logs": [
        _log(5, "更新记录失败: record_id=rec1, FieldNameNotFound body={}"),
        _log(1, "audit_workbench submit project=1 record=rec1 written=[]"),
    ]})
    sub = data["submit"]
    assert sub["result"] == "writeback_failed" and "FieldNameNotFound" in sub["message"]
    assert [r["kind"] for r in sub["logs"]] == ["write_failed", "submit_ok"]


def test_not_submitted_with_success_or_nothing_in_logs() -> None:
    data = _data("not_submitted")
    tr.apply_logs(data, {"ok": True, "logs": [_log(5, "audit_workbench submit(action) record=rec1 written=[]")]})
    assert data["submit"]["result"] == "not_submitted" and "task_submit 没记上" in data["submit"]["logNote"]
    data = _data("not_submitted")
    tr.apply_logs(data, {"ok": True, "logs": []})
    assert "没有这条记录的提交" in data["submit"]["logNote"]


def test_enqueue_calls_after_submit_only() -> None:
    data = _data("enqueue_not_returned", "2026-11-23T10:03:00")
    tr.apply_logs(data, {"ok": True, "logs": [_log(1, "audit_workbench enqueue created record=rec1")]})
    assert "没有提交之后的入队调用" in data["submit"]["logNote"]
    data = _data("enqueue_not_returned", "2026-11-23T10:03:00")
    tr.apply_logs(data, {"ok": True, "logs": [
        _log(6, "audit_workbench enqueue ignored WORKBENCH_PAUSED project=1 record=rec1"),
        _log(4, "audit_workbench submit skipped project=1 record=rec1 skipped=['fldNote']"),
    ]})
    note = data["submit"]["logNote"]
    assert "WORKBENCH_PAUSED" in note and "fldNote" in note


def test_unreadable_logs_are_unverified_and_rendered() -> None:
    data = _data("log_missing")
    tr.apply_logs(data, {"ok": False, "message": "本机没有安装 aliyun CLI"})
    assert data["submit"]["logNote"] == "运行日志未核验：本机没有安装 aliyun CLI"
    data = _data("not_submitted")
    tr.apply_logs(data, {"ok": True, "logs": [_log(5, "更新记录失败: record_id=rec1 a|b")]})
    checks = [{"key": "task", "label": "任务已建", "state": "pass", "evidence": "已存在", "next": None}]
    text = tr.render({**data, "recordId": "rec1", "checks": checks, "diagnosis": tr.diagnose(checks), "feishu": {}})
    assert "| 2026-11-23 10:05:00 | 更新记录失败: record_id=rec1 a/b | t5 |" in text


def test_service_searches_logs_only_for_open_verdicts(monkeypatch: pytest.MonkeyPatch) -> None:
    from audit_workbench_mcp import sls

    calls: list[tuple[Any, ...]] = []

    def fake_search(*args: Any) -> dict[str, Any]:
        calls.append(args)
        return {"ok": True, "logs": []}

    monkeypatch.setattr(sls, "search_record", fake_search)
    for result, expect in (("not_submitted", 1), ("ok", 0)):
        calls.clear()
        payload = {"recordId": "rec1", "stage": 1, "dataUrl": "", "checks": [],
                   "diagnosis": {"result": "all_pass", "step": None, "label": None, "message": "", "next": None},
                   "workflows": {}, "feishu": {"ok": True, "rounds": []},
                   "tasks": [{"stage": 1, "createdAt": "2026-11-23T09:00:00"}],
                   "submit": {"result": result, "message": "m", "next": None, "lastSubmit": None}}

        def handler(request: httpx.Request, payload: dict[str, Any] = payload) -> httpx.Response:
            return httpx.Response(200, json={"status_code": 0, "status_msg": "success", "data": payload})

        store = TokenStore(sources=(lambda _e: "tok",), capture=lambda *a, **k: "tok")
        service = AuditWorkbenchService(AdminClient(store, transport=httpx.MockTransport(handler), retry_delay=0))
        asyncio.run(service.trace("prod", 7, "rec1"))
        assert len(calls) == expect
        if expect:
            assert calls[0][0] == "prod" and calls[0][1] == "rec1"
