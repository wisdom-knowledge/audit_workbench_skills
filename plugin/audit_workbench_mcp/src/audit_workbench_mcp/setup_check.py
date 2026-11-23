"""Setup check run once per env: admin login, lark-cli user, and (optional) SLS read access.

Login and lark-cli are required; without SLS only trace's run-log step is skipped.
"""

from __future__ import annotations

import asyncio
from importlib import metadata
from typing import Any

from . import errors, lark, sls
from .client import AdminClient
from .envs import get_env

PASS, FAIL, WARN = "pass", "fail", "warn"
_ICON = {PASS: "✅", FAIL: "❌", WARN: "⚠️"}


def version() -> str:
    try:
        return metadata.version("audit-workbench-mcp")
    except metadata.PackageNotFoundError:
        return "unknown"


def _item(key: str, label: str, state: str, detail: str, fix: str | None = None) -> dict[str, Any]:
    return {"key": key, "label": label, "state": state, "detail": detail, "fix": fix}


async def _admin(client: AdminClient, env: str) -> dict[str, Any]:
    label = f"{env} 管理端登录"
    try:
        # 最轻的管理端只读接口，能返回就说明登录态有效
        await client.request(get_env(env), "GET", "/admin/audit-workbench/recent-published",
                             params={"workbench_type": 1, "limit": 1, "exclude_project_id": 0})
    except errors.AuditWorkbenchError as exc:
        if exc.code == errors.UNAUTHORIZED:
            return _item("admin", label, FAIL, "没有可用的管理员登录态", f"调用 login(env={env}) 登录")
        if exc.code == errors.FORBIDDEN:
            return _item("admin", label, FAIL, "已登录，但账号没有管理端权限", "找管理员开通管理端权限")
        return _item("admin", label, FAIL, f"管理端接口不可用：{exc.message}", "稍后重试")
    return _item("admin", label, PASS, "登录态有效")


def _lark(found: dict[str, Any]) -> dict[str, Any]:
    if found.get("ok"):
        return _item("lark", "lark-cli 用户身份", PASS, f"已登录：{found.get('user') or '未知用户'}")
    return _item("lark", "lark-cli 用户身份", FAIL, found.get("message") or "不可用",
                 "安装 lark-cli 后在终端运行 `lark-cli auth login --recommend` 完成授权")


def _sls(found: dict[str, Any], env: str) -> dict[str, Any]:
    label = "阿里云日志读权限（可选）"
    if found.get("ok"):
        return _item("sls", label, PASS, f"能读 {found.get('logstore')}")
    return _item("sls", label, WARN, found.get("message") or "不可用",
                 "配置 aliyun CLI 并申请 AliyunLogReadOnlyAccess；不配置也能用，只是排障时不查运行日志")


def render(env: str, items: list[dict[str, Any]], ver: str) -> str:
    lines = [f"审核工作台 v{ver}，环境 {env}", "", "| 检查项 | 结果 | 说明 | 处理 |", "|-|-|-|-|"]
    for i in items:
        lines.append(f"| {i['label']} | {_ICON[i['state']]} | {i['detail']} | {i['fix'] or '—'} |")
    return "\n".join(lines)


async def check_setup(client: AdminClient, env: str) -> dict[str, Any]:
    admin, lark_found, sls_found = await asyncio.gather(
        _admin(client, env),
        asyncio.to_thread(lark.auth_status),
        asyncio.to_thread(sls.check_access, env),
    )
    items = [admin, _lark(lark_found), _sls(sls_found, env)]
    ver = version()
    return {
        "ok": True,
        "env": env,
        "version": ver,
        "ready": all(i["state"] != FAIL for i in items),
        "items": items,
        "setup_markdown": render(env, items, ver),
    }
