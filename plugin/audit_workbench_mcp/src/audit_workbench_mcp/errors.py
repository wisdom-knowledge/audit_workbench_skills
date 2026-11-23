"""Stable error codes and the mapping from backend HTTP failures to them.

The backend has no business error codes. Success is HTTP 2xx with the envelope
{status_code: 0, status_msg, data}. Failures come from FastAPI HTTPException as
{detail: ...}, where detail is one of:

- a string, e.g. "项目不存在"
- an object with "message" plus extras, e.g. the draft conflict payload
  {message, latest_updated_at, diff} or publish validation {message, errors}
- a list, from FastAPI's own request validation (422) [{loc, msg, type}, ...]
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

UNAUTHORIZED = "unauthorized"
FORBIDDEN = "forbidden"
NOT_FOUND = "not_found"
BAD_REQUEST = "bad_request"
CONFLICT = "conflict"
VALIDATION_FAILED = "validation_failed"
RATE_LIMITED = "rate_limited"
UNAVAILABLE = "unavailable"
CONFIRM_MISMATCH = "confirm_mismatch"
UNEXPECTED_RESPONSE = "unexpected_response"

_STATUS_TO_CODE = {
    400: BAD_REQUEST,
    401: UNAUTHORIZED,
    403: FORBIDDEN,
    404: NOT_FOUND,
    409: CONFLICT,
    422: VALIDATION_FAILED,
    429: RATE_LIMITED,
}

_HINTS = {
    UNAUTHORIZED: "管理员登录态无效或已过期。调用 login 工具重新登录后再试。",
    FORBIDDEN: "当前管理员没有该操作权限，或审核工作台已暂停。",
    NOT_FOUND: "项目或对象不存在，核对 env 与 project_id。",
    CONFLICT: "数据已被他人更新。先调用 get_editor 重新读取，核对差异后再提交。",
    VALIDATION_FAILED: "按 detail 中的逐条校验项修正后再提交。",
    RATE_LIMITED: "飞书或后端限流，稍后再试。",
    UNAVAILABLE: "后端或飞书暂时不可用。读操作已自动重试一次；写操作不会自动重试。",
}


class AuditWorkbenchError(Exception):
    """A failure the tools report back as a structured MCP tool error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.http_status = http_status
        self.detail = detail

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": False, "code": self.code, "message": self.message}
        if self.http_status is not None:
            payload["http_status"] = self.http_status
        if self.detail is not None:
            payload["detail"] = self.detail
        hint = _HINTS.get(self.code)
        if hint:
            payload["hint"] = hint
        return payload

    def to_tool_error(self) -> ToolError:
        return ToolError(json.dumps(self.to_payload(), ensure_ascii=False, default=str))


def code_for_status(http_status: int) -> str:
    if http_status in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[http_status]
    if http_status >= 500:
        return UNAVAILABLE
    return BAD_REQUEST


def from_http_failure(http_status: int, body: Any) -> AuditWorkbenchError:
    """Turn a non-success backend response into an AuditWorkbenchError.

    Keeps the useful parts of ``detail`` (conflict payload, validation items)
    so the caller can act on them instead of re-reading a flattened string.
    """
    code = code_for_status(http_status)
    detail = body.get("detail") if isinstance(body, dict) else None

    if isinstance(detail, str):
        return AuditWorkbenchError(code, detail, http_status=http_status)

    if isinstance(detail, dict):
        message = str(detail.get("message") or f"HTTP {http_status}")
        extra = {k: v for k, v in detail.items() if k != "message"}
        return AuditWorkbenchError(
            code, message, http_status=http_status, detail=extra or None
        )

    if isinstance(detail, list):
        # FastAPI request validation: the request body did not match the schema.
        items = [
            {
                "loc": ".".join(str(p) for p in item.get("loc", [])),
                "message": item.get("msg", ""),
            }
            for item in detail
            if isinstance(item, dict)
        ]
        return AuditWorkbenchError(
            VALIDATION_FAILED,
            "请求参数不符合接口要求",
            http_status=http_status,
            detail={"errors": items},
        )

    # 2xx with status_code != 0, or a body without detail.
    if isinstance(body, dict) and body.get("status_msg"):
        return AuditWorkbenchError(code, str(body["status_msg"]), http_status=http_status)
    return AuditWorkbenchError(code, f"HTTP {http_status}", http_status=http_status)
