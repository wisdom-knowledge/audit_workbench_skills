"""Server registration: tool schemas survive the error-wrapping decorator, and
backend failures reach the client as a JSON tool error."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from audit_workbench_mcp import server
from audit_workbench_mcp.auth import TokenStore
from audit_workbench_mcp.client import AdminClient
from audit_workbench_mcp.service import AuditWorkbenchService

EXPECTED_TOOLS = {
    "login", "get_editor", "parse_feishu", "parse_view_filter", "list_auditors",
    "add_auditors", "remove_auditors", "save_draft", "discard_draft", "publish",
    "retry_workflows", "set_runtime_status",
    "check_readiness", "validate_config", "get_workflows", "wait_workflows",
    "get_reference_configs", "get_field_groups", "suggest_draft", "set_enqueue_views",
    "ensure_app_collaborator", "pre_publish_checklist", "created_workflows",
    "enable_workflows", "check_auditor_binding", "onboard_status",
}


def _tools() -> dict:
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def test_all_tools_registered() -> None:
    assert set(_tools()) == EXPECTED_TOOLS


def test_schemas_come_from_the_wrapped_functions() -> None:
    tools = _tools()
    publish = tools["publish"].inputSchema
    assert set(publish["required"]) == {"env", "project_id", "config", "base_version"}
    assert publish["properties"]["env"]["enum"] == ["boe", "prod"]
    assert "confirm" in publish["properties"]
    assert set(tools["get_editor"].inputSchema["required"]) == {"env", "project_id"}


def test_backend_error_becomes_json_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "项目不存在"})

    store = TokenStore(sources=(lambda _env: "tok",), capture=lambda *a, **k: "tok")
    service = AuditWorkbenchService(
        AdminClient(store, transport=httpx.MockTransport(handler), retry_delay=0)
    )
    monkeypatch.setattr(server, "_service", service)

    with pytest.raises(ToolError) as exc:
        asyncio.run(server.mcp.call_tool("get_editor", {"env": "boe", "project_id": 7}))
    # FastMCP may prefix the text with "Error executing tool <name>: "; the JSON follows.
    text = str(exc.value)
    payload = json.loads(text[text.index("{"):])
    assert payload["code"] == "not_found"
    assert payload["message"] == "项目不存在"
