"""Tool logic, kept free of MCP types so it can be tested directly.

Every write goes through the same gate:
- confirm=False (default): read the current state and return a preview of the
  target, the request and its impact. Nothing is sent.
- confirm=True: in prod, confirm_project_id must equal project_id. Then the
  request is sent once, and the editor is read back so the result shows the
  version / updated_at after the change.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from . import errors, readiness
from .client import AdminClient
from .envs import get_env


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def snapshot_from_editor(editor: dict[str, Any]) -> dict[str, Any]:
    """The few editor values a caller needs to judge state and pass back as OCC bases."""
    draft = editor.get("draft") or {}
    published = editor.get("published") or {}
    return {
        "draft_exists": bool(editor.get("draft")),
        "draft_updated_at": draft.get("updated_at"),
        "draft_wizard_step": draft.get("wizard_step"),
        "published_version": published.get("version"),
        "published_at": published.get("published_at"),
        "runtime_status": editor.get("runtimeStatus"),
        "feishu_table_url": editor.get("lastFeishuTableUrl"),
    }


class AuditWorkbenchService:
    def __init__(self, client: AdminClient) -> None:
        self._client = client

    # ---- shared helpers -------------------------------------------------

    def _ok(self, env: str, project_id: int | None, data: Any, **extra: Any) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": True, "env": env, "fetched_at": _now()}
        if project_id is not None:
            out["project_id"] = project_id
        out.update(extra)
        out["data"] = data
        return out

    async def _editor(self, env: str, project_id: int) -> dict[str, Any]:
        return await self._client.request(
            get_env(env), "GET", f"/admin/projects/{project_id}/audit-workbench/editor"
        )

    async def _snapshot(self, env: str, project_id: int) -> dict[str, Any]:
        return snapshot_from_editor(await self._editor(env, project_id))

    @staticmethod
    def _check_confirm(env: str, project_id: int, confirm_project_id: int | None) -> None:
        if get_env(env).name == "prod" and confirm_project_id != project_id:
            raise errors.AuditWorkbenchError(
                errors.CONFIRM_MISMATCH,
                "生产环境写操作必须把 confirm_project_id 填成与 project_id 相同的值",
                detail={"project_id": project_id, "confirm_project_id": confirm_project_id},
            )

    async def _preview(
        self,
        env: str,
        project_id: int,
        action: str,
        request: dict[str, Any],
        impact: str,
        warnings: list[str] | None = None,
        current: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if current is None:
            current = await self._snapshot(env, project_id)
        next_step = "确认无误后，带 confirm=true 再次调用"
        if get_env(env).name == "prod":
            next_step += f"，并传 confirm_project_id={project_id}"
        return {
            "ok": True,
            "preview": True,
            "executed": False,
            "env": env,
            "project_id": project_id,
            "action": action,
            "request": request,
            "current": current,
            "impact": impact,
            "warnings": warnings or [],
            "next": next_step,
            "fetched_at": _now(),
        }

    async def _write(
        self,
        env: str,
        project_id: int,
        method: str,
        path: str,
        body: Any = None,
    ) -> dict[str, Any]:
        try:
            data = await self._client.request(
                get_env(env), method, path, json=body, is_write=True
            )
        except errors.AuditWorkbenchError as exc:
            if exc.code == errors.UNAVAILABLE:
                # The request may have been applied before the connection dropped.
                exc.detail = {
                    "result_unknown": True,
                    "next": "先调用 get_editor 回读，确认是否已生效，再决定是否重试",
                }
            raise
        try:
            after: dict[str, Any] = await self._snapshot(env, project_id)
        except errors.AuditWorkbenchError as exc:
            after = {"readback_failed": exc.to_payload()}
        return self._ok(env, project_id, data, executed=True, after=after)

    # ---- reads ------------------------------------------------------------

    async def get_editor(self, env: str, project_id: int) -> dict[str, Any]:
        editor = await self._editor(env, project_id)
        return self._ok(env, project_id, editor, summary=snapshot_from_editor(editor))

    async def parse_feishu(
        self, env: str, table_url: str, project_id: int | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"table_url": table_url}
        if project_id is not None:
            body["project_id"] = project_id
        data = await self._client.request(
            get_env(env), "POST", "/admin/audit-workbench/parse-feishu", json=body
        )
        return self._ok(env, project_id, data)

    async def parse_view_filter(self, env: str, view_url: str) -> dict[str, Any]:
        data = await self._client.request(
            get_env(env),
            "POST",
            "/admin/audit-workbench/parse-view-filter",
            json={"view_url": view_url},
        )
        return self._ok(env, None, data)

    async def list_auditors(
        self,
        env: str,
        project_id: int,
        skip: int = 0,
        limit: int = 50,
        talent_id: int | None = None,
        talent_name: str | None = None,
    ) -> dict[str, Any]:
        data = await self._client.request(
            get_env(env),
            "GET",
            f"/admin/projects/{project_id}/auditors",
            params={
                "skip": skip,
                "limit": limit,
                "talent_id": talent_id,
                "talent_name": talent_name,
            },
        )
        return self._ok(env, project_id, data)

    # ---- writes -----------------------------------------------------------

    async def save_draft(
        self,
        env: str,
        project_id: int,
        config: dict[str, Any],
        base_updated_at: str | None,
        wizard_step: int = 1,
        feishu_app_token: str | None = None,
        feishu_table_id: str | None = None,
        feishu_view_id: str | None = None,
        confirm: bool = False,
        confirm_project_id: int | None = None,
    ) -> dict[str, Any]:
        body = {
            "config": config,
            "base_updated_at": base_updated_at,
            "wizard_step": wizard_step,
            "force": False,
            "feishu_app_token": feishu_app_token,
            "feishu_table_id": feishu_table_id,
            "feishu_view_id": feishu_view_id,
        }
        path = f"/admin/projects/{project_id}/audit-workbench/draft"
        if not confirm:
            current = await self._snapshot(env, project_id)
            warnings = []
            if current["draft_exists"] and base_updated_at != current["draft_updated_at"]:
                warnings.append(
                    "base_updated_at 与当前草稿的 updated_at 不一致，执行会返回 conflict。"
                    "先用 get_editor 读取最新草稿再合并。"
                )
            return await self._preview(
                env,
                project_id,
                "save_draft",
                {
                    "base_updated_at": base_updated_at,
                    "wizard_step": wizard_step,
                    "config_keys": sorted(config.keys()),
                },
                "覆盖该项目的草稿；已发布版本不受影响。版本不一致时后端拒绝覆盖。",
                warnings,
                current,
            )
        self._check_confirm(env, project_id, confirm_project_id)
        return await self._write(env, project_id, "PUT", path, body)

    async def discard_draft(
        self,
        env: str,
        project_id: int,
        confirm: bool = False,
        confirm_project_id: int | None = None,
    ) -> dict[str, Any]:
        if not confirm:
            return await self._preview(
                env,
                project_id,
                "discard_draft",
                {},
                "删除该项目的草稿，不可恢复；已发布版本不受影响。",
            )
        self._check_confirm(env, project_id, confirm_project_id)
        return await self._write(
            env, project_id, "DELETE", f"/admin/projects/{project_id}/audit-workbench/draft"
        )

    async def publish(
        self,
        env: str,
        project_id: int,
        config: dict[str, Any],
        base_version: int,
        confirm: bool = False,
        confirm_project_id: int | None = None,
    ) -> dict[str, Any]:
        body = {"base_version": base_version, "config": config, "force": False}
        if not confirm:
            current = await self._snapshot(env, project_id)
            warnings = []
            if (current["published_version"] or 0) != base_version:
                warnings.append(
                    f"base_version={base_version} 与线上已发布版本 "
                    f"{current['published_version']} 不一致，执行会返回 conflict。"
                )
            return await self._preview(
                env,
                project_id,
                "publish",
                {"base_version": base_version, "config_keys": sorted(config.keys())},
                "生成新的配置版本，专家端立即按新配置展示；发布后 Worker 按新配置同步飞书工作流。",
                warnings,
                current,
            )
        self._check_confirm(env, project_id, confirm_project_id)
        return await self._write(
            env,
            project_id,
            "POST",
            f"/admin/projects/{project_id}/audit-workbench/publish",
            body,
        )

    async def retry_workflows(
        self,
        env: str,
        project_id: int,
        stages: list[int] | None = None,
        kind: str | None = None,
        force_update: bool = False,
        confirm: bool = False,
        confirm_project_id: int | None = None,
    ) -> dict[str, Any]:
        body = {"stages": stages, "kind": kind, "forceUpdate": force_update}
        if not confirm:
            impact = (
                "把匹配的工作流任务重置为 PENDING，Worker 约 10 秒内重新写入飞书。"
                "接口不等待写入结果，需稍后查询同步状态。"
            )
            warnings = []
            if force_update:
                warnings.append("forceUpdate=true 会以平台配置覆盖飞书界面上对工作流的手工修改。")
            return await self._preview(
                env, project_id, "retry_workflows", body, impact, warnings
            )
        self._check_confirm(env, project_id, confirm_project_id)
        return await self._write(
            env,
            project_id,
            "POST",
            f"/admin/projects/{project_id}/audit-workbench/workflows/retry",
            body,
        )

    async def set_runtime_status(
        self,
        env: str,
        project_id: int,
        runtime_status: str,
        confirm: bool = False,
        confirm_project_id: int | None = None,
    ) -> dict[str, Any]:
        body = {"runtime_status": runtime_status}
        if not confirm:
            impact = (
                "PAUSED 后配置端写操作与专家端提交都不可用；ACTIVE 恢复使用。"
                if runtime_status == "PAUSED"
                else "恢复为生效中，配置端写操作与专家端提交重新可用。"
            )
            return await self._preview(
                env, project_id, "set_runtime_status", body, impact
            )
        self._check_confirm(env, project_id, confirm_project_id)
        return await self._write(
            env,
            project_id,
            "PATCH",
            f"/admin/projects/{project_id}/audit-workbench/runtime-status",
            body,
        )

    async def add_auditors(
        self,
        env: str,
        project_id: int,
        talent_ids: list[int],
        confirm: bool = False,
        confirm_project_id: int | None = None,
    ) -> dict[str, Any]:
        body = {"talent_ids": talent_ids}
        if not confirm:
            return await self._preview(
                env,
                project_id,
                "add_auditors",
                body,
                f"把 {len(talent_ids)} 个 talent_id 加入审核员名单；已在名单中的会被跳过。",
            )
        self._check_confirm(env, project_id, confirm_project_id)
        return await self._write(
            env, project_id, "POST", f"/admin/projects/{project_id}/auditors", body
        )

    async def remove_auditors(
        self,
        env: str,
        project_id: int,
        talent_ids: list[int],
        confirm: bool = False,
        confirm_project_id: int | None = None,
    ) -> dict[str, Any]:
        body = {"ids": talent_ids}
        if not confirm:
            return await self._preview(
                env,
                project_id,
                "remove_auditors",
                {"talent_ids": talent_ids},
                f"把 {len(talent_ids)} 个 talent_id 从审核员名单移除（软删）。"
                "仍有待审任务时返回 needs_reassign=true，需要重新分配。",
            )
        self._check_confirm(env, project_id, confirm_project_id)
        return await self._write(
            env,
            project_id,
            "POST",
            f"/admin/projects/{project_id}/auditors/batch-remove",
            body,
        )

    # ---- workflow status and readiness -----------------------------------

    async def _workflows(self, env: str, project_id: int) -> dict[str, Any]:
        data = await self._client.request(
            get_env(env), "GET", f"/admin/projects/{project_id}/audit-workbench/workflows"
        )
        return readiness.summarize_workflows(data)

    async def get_workflows(self, env: str, project_id: int) -> dict[str, Any]:
        return self._ok(env, project_id, await self._workflows(env, project_id))

    async def wait_workflows(
        self,
        env: str,
        project_id: int,
        timeout: float = 90,
        interval: float = 5,
    ) -> dict[str, Any]:
        """Poll the sync table until it settles, needs attention, or times out."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        polls = 0
        while True:
            summary = await self._workflows(env, project_id)
            polls += 1
            if readiness.stop_waiting(summary):
                return self._ok(env, project_id, summary, timed_out=False, polls=polls)
            remaining = deadline - loop.time()
            if remaining <= 0:
                summary["problems"] = summary["problems"] + [
                    f"等待 {int(timeout)} 秒后仍有工作流在排队或执行中，尚未完成，不代表成功。"
                ]
                return self._ok(env, project_id, summary, timed_out=True, polls=polls)
            await asyncio.sleep(min(interval, remaining))

    async def validate_config(
        self, env: str, project_id: int, config: dict[str, Any]
    ) -> dict[str, Any]:
        data = await self._client.request(
            get_env(env),
            "POST",
            f"/admin/projects/{project_id}/audit-workbench/validate",
            json={"config": config},
        )
        return self._ok(env, project_id, data)

    async def check_readiness(
        self, env: str, project_id: int, config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Pre-publish checklist. Uses the saved draft when config is not given."""
        source = "argument"
        if config is None:
            editor = await self._editor(env, project_id)
            if editor.get("draft"):
                config, source = editor["draft"]["config"], "draft"
            elif editor.get("published"):
                config, source = editor["published"]["config"], "published"
            else:
                raise errors.AuditWorkbenchError(
                    errors.NOT_FOUND,
                    "项目既没有草稿也没有已发布配置，先保存草稿再检查",
                )
        target = get_env(env)
        validation = await self._client.request(
            target,
            "POST",
            f"/admin/projects/{project_id}/audit-workbench/validate",
            json={"config": config},
        )
        auditors = await self._client.request(
            target, "GET", f"/admin/projects/{project_id}/auditors", params={"limit": 1}
        )
        items = (
            readiness.validation_items(validation)
            + readiness.mapping_items(config)
            + readiness.auditor_items(auditors)
            + [dict(readiness.APP_PERMISSION_ITEM)]
        )
        levels = [i["level"] for i in items]
        summary = {
            "config_source": source,
            "blockers": levels.count(readiness.BLOCKER),
            "warnings": levels.count(readiness.WARNING),
            "unverified": levels.count(readiness.UNVERIFIED),
            # Ready only when nothing blocks; unverified items still need a human check.
            "ready_to_publish": readiness.BLOCKER not in levels,
            "workflow_count": validation.get("workflowCount"),
            "workbench_type": validation.get("workbenchType"),
        }
        return self._ok(env, project_id, {"summary": summary, "items": items})
