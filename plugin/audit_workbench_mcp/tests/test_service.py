"""Service and client tests. No network, no browser: httpx.MockTransport + fake token sources."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from audit_workbench_mcp import errors
from audit_workbench_mcp.auth import TokenStore
from audit_workbench_mcp.client import AdminClient
from audit_workbench_mcp.service import AuditWorkbenchService

TOKEN = "secret-token-should-never-leak"

EDITOR = {
    "draft": {"config": {"rounds": []}, "updated_at": "2026-09-01T10:00:00", "wizard_step": 2},
    "published": {"config": {}, "version": 3, "published_at": "2026-08-30T09:00:00"},
    "platform": {"auditStatuses": [], "fieldTypes": [], "displayAreas": [], "taskList": {}},
    "fieldCatalog": [],
    "lastFeishuTableUrl": "https://example.feishu.cn/base/app?table=tbl",
    "runtimeStatus": "ACTIVE",
}


def ok(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"status_code": 0, "status_msg": "success", "data": data})


class Recorder:
    """Routes requests to handlers and remembers every call."""

    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = routes
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        handler = self.routes[(request.method, request.url.path)]
        return handler(request) if callable(handler) else handler

    def methods(self) -> list[str]:
        return [f"{r.method} {r.url.path}" for r in self.calls]


def make_service(
    routes: dict[tuple[str, str], Any], tokens: tuple[str, ...] = (TOKEN,)
) -> tuple[AuditWorkbenchService, Recorder]:
    recorder = Recorder(routes)
    sources = tuple((lambda _env, t=t: t) for t in tokens)
    store = TokenStore(sources=sources, capture=lambda *a, **k: TOKEN)
    client = AdminClient(store, transport=httpx.MockTransport(recorder), retry_delay=0)
    return AuditWorkbenchService(client), recorder


EDITOR_PATH = ("GET", "/api/v1/admin/projects/7/audit-workbench/editor")
DRAFT_PATH = ("PUT", "/api/v1/admin/projects/7/audit-workbench/draft")
PUBLISH_PATH = ("POST", "/api/v1/admin/projects/7/audit-workbench/publish")


def run(coro):
    return asyncio.run(coro)


def assert_no_token(value: Any) -> None:
    assert TOKEN not in json.dumps(value, ensure_ascii=False, default=str)


# ---- reads -----------------------------------------------------------------


def test_get_editor_unwraps_envelope_and_summarizes() -> None:
    service, rec = make_service({EDITOR_PATH: ok(EDITOR)})
    out = run(service.get_editor("boe", 7))
    assert out["ok"] is True
    assert out["summary"]["draft_updated_at"] == "2026-09-01T10:00:00"
    assert out["summary"]["published_version"] == 3
    assert rec.calls[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert str(rec.calls[0].url).startswith("https://service-boe.meetchances.com/")
    assert_no_token(out)


def test_field_pool_is_neither_shown_nor_sent() -> None:
    pool = [{"id": "f1", "name": "题目"}]
    editor = json.loads(json.dumps(EDITOR))
    editor["draft"]["config"]["sourceFields"] = pool
    editor["published"]["config"]["sourceFields"] = pool
    editor["fieldCatalog"] = pool
    service, rec = make_service({EDITOR_PATH: ok(editor), DRAFT_PATH: ok({"updated_at": "x"})})
    out = run(service.get_editor("boe", 7))
    assert "sourceFields" not in out["data"]["draft"]["config"]
    assert "sourceFields" not in out["data"]["published"]["config"]
    assert out["data"]["fieldCatalog"] == pool
    preview = run(service.save_draft("boe", 7, {"fields": [], "sourceFields": pool}, "2026-09-01T10:00:00"))
    assert preview["request"]["config_keys"] == ["fields"]
    run(service.save_draft("boe", 7, {"fields": [], "sourceFields": pool}, "2026-09-01T10:00:00", confirm=True))
    put = next(c for c in rec.calls if c.method == "PUT")
    assert "sourceFields" not in json.loads(put.content)["config"]


def test_prod_uses_prod_base_url() -> None:
    service, rec = make_service({EDITOR_PATH: ok(EDITOR)})
    run(service.get_editor("prod", 7))
    assert str(rec.calls[0].url).startswith("https://service.meetchances.com/")


def test_list_auditors_drops_none_params() -> None:
    path = ("GET", "/api/v1/admin/projects/7/auditors")
    service, rec = make_service({path: ok({"count": 0, "summary": {}, "data": []})})
    run(service.list_auditors("boe", 7, talent_name="张"))
    params = dict(rec.calls[0].url.params)
    assert params == {"skip": "0", "limit": "50", "talent_name": "张"}


def test_read_retries_once_on_5xx() -> None:
    responses = iter([httpx.Response(502, json={"detail": "上游失败"}), ok(EDITOR)])
    service, rec = make_service({EDITOR_PATH: lambda _r: next(responses)})
    out = run(service.get_editor("boe", 7))
    assert out["ok"] is True
    assert len(rec.calls) == 2


def test_read_gives_up_after_second_5xx() -> None:
    service, rec = make_service({EDITOR_PATH: httpx.Response(503, json={"detail": "维护中"})})
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        run(service.get_editor("boe", 7))
    assert exc.value.code == errors.UNAVAILABLE
    assert len(rec.calls) == 2


# ---- auth ------------------------------------------------------------------


def test_401_rotates_to_next_token_source() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["Authorization"] == "Bearer stale":
            return httpx.Response(401, json={"detail": "Could not validate credentials"})
        return ok(EDITOR)

    service, rec = make_service({EDITOR_PATH: handler}, tokens=("stale", TOKEN))
    out = run(service.get_editor("boe", 7))
    assert out["ok"] is True
    assert [r.headers["Authorization"] for r in rec.calls] == ["Bearer stale", f"Bearer {TOKEN}"]


def test_all_tokens_rejected_is_unauthorized_without_leaking() -> None:
    service, _ = make_service(
        {EDITOR_PATH: httpx.Response(401, json={"detail": "Could not validate credentials"})}
    )
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        run(service.get_editor("boe", 7))
    assert exc.value.code == errors.UNAUTHORIZED
    assert_no_token(exc.value.to_payload())
    assert TOKEN not in str(exc.value.to_tool_error())


def test_no_token_source_is_unauthorized() -> None:
    service, rec = make_service({EDITOR_PATH: ok(EDITOR)}, tokens=())
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        run(service.get_editor("boe", 7))
    assert exc.value.code == errors.UNAUTHORIZED
    assert rec.calls == []


# ---- error mapping -----------------------------------------------------------


def test_string_detail_maps_to_not_found() -> None:
    service, _ = make_service({EDITOR_PATH: httpx.Response(404, json={"detail": "项目不存在"})})
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        run(service.get_editor("boe", 7))
    assert exc.value.code == errors.NOT_FOUND
    assert exc.value.message == "项目不存在"


def test_conflict_payload_is_passed_through() -> None:
    conflict = {
        "detail": {
            "message": "草稿已被他人更新，请重新加载或强制覆盖",
            "latest_updated_at": "2026-09-01T11:00:00",
            "diff": [],
        }
    }
    service, _ = make_service({EDITOR_PATH: ok(EDITOR), DRAFT_PATH: httpx.Response(409, json=conflict)})
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        run(service.save_draft("boe", 7, {}, "2026-09-01T10:00:00", confirm=True))
    payload = exc.value.to_payload()
    assert payload["code"] == errors.CONFLICT
    assert payload["detail"]["latest_updated_at"] == "2026-09-01T11:00:00"
    assert "get_editor" in payload["hint"]


def test_publish_validation_errors_are_passed_through() -> None:
    body = {
        "detail": {
            "message": "配置校验失败",
            "errors": [{"rule": "layout_key_in_fields", "message": "x", "step": 3, "field_key": "f1"}],
        }
    }
    service, _ = make_service({EDITOR_PATH: ok(EDITOR), PUBLISH_PATH: httpx.Response(422, json=body)})
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        run(service.publish("boe", 7, {}, 3, confirm=True))
    assert exc.value.code == errors.VALIDATION_FAILED
    assert exc.value.detail["errors"][0]["rule"] == "layout_key_in_fields"


def test_fastapi_request_validation_list_is_flattened() -> None:
    body = {"detail": [{"loc": ["body", "config", "rounds"], "msg": "field required", "type": "missing"}]}
    service, _ = make_service({EDITOR_PATH: ok(EDITOR), DRAFT_PATH: httpx.Response(422, json=body)})
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        run(service.save_draft("boe", 7, {}, "2026-09-01T10:00:00", confirm=True))
    assert exc.value.code == errors.VALIDATION_FAILED
    assert exc.value.detail == {"errors": [{"loc": "body.config.rounds", "message": "field required"}]}


def test_2xx_with_nonzero_status_code_is_an_error() -> None:
    body = {"status_code": 1001, "status_msg": "业务失败", "data": None}
    service, _ = make_service({EDITOR_PATH: httpx.Response(200, json=body)})
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        run(service.get_editor("boe", 7))
    assert exc.value.message == "业务失败"


def test_non_json_body_is_handled() -> None:
    service, _ = make_service({EDITOR_PATH: httpx.Response(404, text="<html>nginx</html>")})
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        run(service.get_editor("boe", 7))
    assert exc.value.code == errors.NOT_FOUND


# ---- write gate --------------------------------------------------------------


def test_preview_does_not_send_the_write() -> None:
    service, rec = make_service({EDITOR_PATH: ok(EDITOR)})
    out = run(service.save_draft("boe", 7, {"rounds": []}, "2026-09-01T10:00:00"))
    assert out["preview"] is True and out["executed"] is False
    assert rec.methods() == ["GET /api/v1/admin/projects/7/audit-workbench/editor"]
    assert out["warnings"] == []


def test_preview_warns_when_base_is_stale() -> None:
    service, _ = make_service({EDITOR_PATH: ok(EDITOR)})
    out = run(service.publish("boe", 7, {}, base_version=2))
    assert out["warnings"] and "不一致" in out["warnings"][0]


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.discard_draft("boe", 7),
        lambda s: s.add_auditors("boe", 7, [1, 2]),
        lambda s: s.remove_auditors("boe", 7, [1]),
        lambda s: s.retry_workflows("boe", 7, force_update=True),
        lambda s: s.set_runtime_status("boe", 7, "PAUSED"),
    ],
)
def test_every_write_previews_by_default(call) -> None:
    service, rec = make_service({EDITOR_PATH: ok(EDITOR)})
    out = run(call(service))
    assert out["executed"] is False
    assert all(r.method == "GET" for r in rec.calls)


def test_prod_write_requires_matching_confirm_project_id() -> None:
    service, rec = make_service({EDITOR_PATH: ok(EDITOR), DRAFT_PATH: ok({})})
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        run(service.save_draft("prod", 7, {}, None, confirm=True, confirm_project_id=8))
    assert exc.value.code == errors.CONFIRM_MISMATCH
    assert rec.calls == []


def test_confirmed_write_sends_once_and_reads_back() -> None:
    saved = {"updated_at": "2026-09-01T12:00:00", "wizard_step": 2, "questionTags": []}
    service, rec = make_service({EDITOR_PATH: ok(EDITOR), DRAFT_PATH: ok(saved)})
    out = run(
        service.save_draft(
            "prod", 7, {"rounds": []}, "2026-09-01T10:00:00", wizard_step=2,
            confirm=True, confirm_project_id=7,
        )
    )
    assert out["executed"] is True
    assert out["data"] == saved
    assert out["after"]["published_version"] == 3
    assert rec.methods() == [
        "PUT /api/v1/admin/projects/7/audit-workbench/draft",
        "GET /api/v1/admin/projects/7/audit-workbench/editor",
    ]
    sent = json.loads(rec.calls[0].content)
    assert sent["base_updated_at"] == "2026-09-01T10:00:00"
    assert sent["force"] is False


def test_write_is_not_retried_and_marks_result_unknown() -> None:
    service, rec = make_service(
        {EDITOR_PATH: ok(EDITOR), PUBLISH_PATH: httpx.Response(504, json={"detail": "超时"})}
    )
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        run(service.publish("boe", 7, {}, 3, confirm=True))
    assert exc.value.code == errors.UNAVAILABLE
    assert exc.value.detail["result_unknown"] is True
    assert [r.method for r in rec.calls] == ["POST"]


def test_retry_body_uses_backend_field_names() -> None:
    path = ("POST", "/api/v1/admin/projects/7/audit-workbench/workflows/retry")
    service, rec = make_service({EDITOR_PATH: ok(EDITOR), path: ok({"projectId": 7, "queued": 2})})
    out = run(service.retry_workflows("boe", 7, stages=[2], kind="ENQUEUE", confirm=True))
    assert json.loads(rec.calls[0].content) == {"stages": [2], "kind": "ENQUEUE", "forceUpdate": False}
    assert out["data"]["queued"] == 2


def test_remove_auditors_sends_ids_field() -> None:
    path = ("POST", "/api/v1/admin/projects/7/auditors/batch-remove")
    result = {"removed_count": 1, "skipped_count": 0, "needs_reassign": False, "removed": []}
    service, rec = make_service({EDITOR_PATH: ok(EDITOR), path: ok(result)})
    run(service.remove_auditors("boe", 7, [42], confirm=True))
    assert json.loads(rec.calls[0].content) == {"ids": [42]}
