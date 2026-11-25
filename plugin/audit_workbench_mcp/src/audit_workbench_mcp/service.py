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

from . import draft_builder, errors, field_groups, handoff, lark, onboard_status, pipeline_check, readiness, references, report, sls
from . import trace as trace_mod
from .client import AdminClient
from .envs import get_env


def _without_field_pool(config: dict[str, Any]) -> dict[str, Any]:
    """The admin page's full field pool is not stored by the backend; never send or show it."""
    return {k: v for k, v in config.items() if k != "sourceFields"}


def _hide_field_pool(editor: dict[str, Any]) -> dict[str, Any]:
    out = dict(editor)
    for key in ("draft", "published"):
        if isinstance(out.get(key), dict) and isinstance(out[key].get("config"), dict):
            out[key] = {**out[key], "config": _without_field_pool(out[key]["config"])}
    return out


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

    @property
    def client(self) -> AdminClient:
        return self._client

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
        return self._ok(env, project_id, _hide_field_pool(editor), summary=snapshot_from_editor(editor))

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
        config = _without_field_pool(config)
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
        config = _without_field_pool(config)
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
        validation = await self._client.request(
            get_env(env),
            "POST",
            f"/admin/projects/{project_id}/audit-workbench/validate",
            json={"config": config},
        )
        # Only the backend validation runs before publish; everything it reports blocks.
        items = readiness.validation_items(validation)
        summary = {
            "config_source": source,
            "blockers": len(items),
            "ready_to_publish": not items,
            "workflow_count": validation.get("workflowCount"),
            "workbench_type": validation.get("workbenchType"),
        }
        return self._ok(env, project_id, {"summary": summary, "items": items})

    # ---- draft suggestion (3.3) --------------------------------------------

    @staticmethod
    def page_url(env: str, project_id: int) -> str:
        return f"{get_env(env).admin_url}/projects/{project_id}/audit-workbench?step=1"

    async def _references(
        self, env: str, workbench_type: int, exclude_project_id: int, limit: int
    ) -> list[dict[str, Any]]:
        target = get_env(env)
        listing = await self._client.request(
            target,
            "GET",
            "/admin/audit-workbench/recent-published",
            params={
                "workbench_type": workbench_type,
                "limit": limit,
                "exclude_project_id": exclude_project_id,
            },
        )
        refs = []
        for item in listing.get("items") or []:
            editor = await self._editor(env, int(item["projectId"]))
            published = editor.get("published") or {}
            if published.get("config"):
                refs.append(references.compact_config(item, published["config"]))
        return refs

    async def get_reference_configs(
        self, env: str, project_id: int, workbench_type: int, limit: int = 5
    ) -> dict[str, Any]:
        refs = await self._references(env, workbench_type, project_id, limit)
        return self._ok(env, project_id, {"count": len(refs), "references": refs})

    async def get_field_groups(self, env: str, app_token: str, table_id: str) -> dict[str, Any]:
        result = await asyncio.to_thread(field_groups.fetch_field_groups, app_token, table_id)
        return self._ok(env, None, result)

    async def suggest_draft(
        self,
        env: str,
        project_id: int,
        table_url: str,
        workbench_type: int,
        alignment: dict[str, Any],
        limit: int = 5,
        confirm: bool = False,
        confirm_project_id: int | None = None,
    ) -> dict[str, Any]:
        """Build the draft from the alignment, save it, and return the report.

        No draft yet: saved directly, a draft does not touch the live config.
        A draft exists: returns the report as a preview; confirm=True overwrites it.
        """
        target = get_env(env)
        parsed = await self._client.request(
            target,
            "POST",
            "/admin/audit-workbench/parse-feishu",
            json={"table_url": table_url, "project_id": project_id},
        )
        refs = await self._references(env, workbench_type, project_id, limit)
        built = draft_builder.build_draft(
            base_fields=parsed.get("fields") or [],
            alignment=alignment,
            references=refs,
            workbench_type=workbench_type,
            feishu_table_url=table_url,
        )
        current = await self._snapshot(env, project_id)
        must_confirm = current["draft_exists"]
        if must_confirm and not confirm:
            text = report.render_report(
                report=built["report"], env=env, project_id=project_id,
                page_url=self.page_url(env, project_id), saved=False,
            )
            return {
                "ok": True, "preview": True, "executed": False, "env": env,
                "project_id": project_id, "report_markdown": text,
                **self._later_steps(built["report"], env, project_id),
                "impact": f"会覆盖现有草稿（更新于 {current['draft_updated_at']}）",
                "next": "用户同意覆盖后，带 confirm=true 再次调用"
                + (f"，并传 confirm_project_id={project_id}" if target.name == "prod" else ""),
                "fetched_at": _now(),
            }
        if must_confirm:
            self._check_confirm(env, project_id, confirm_project_id)
        body = {
            "config": built["config"],
            "base_updated_at": current["draft_updated_at"],
            "wizard_step": 1,
            "force": False,
            "feishu_app_token": parsed.get("app_token"),
            "feishu_table_id": parsed.get("table_id"),
            "feishu_view_id": parsed.get("view_id"),
        }
        saved = await self._write(
            env, project_id, "PUT", f"/admin/projects/{project_id}/audit-workbench/draft", body
        )
        text = report.render_report(
            report=built["report"], env=env, project_id=project_id,
            page_url=self.page_url(env, project_id), saved=True,
        )
        return {
            **saved, "report_markdown": text, "page_url": self.page_url(env, project_id),
            **self._later_steps(built["report"], env, project_id),
        }

    def _later_steps(self, built_report: dict[str, Any], env: str, project_id: int) -> dict[str, Any]:
        """Messages for steps 2.2 and 2.3; shown one at a time after the field set is confirmed."""
        # 配置页第 1 步是字段，第 2 步「审核规则配置」是角色字段、状态枚举映射和入队视图
        rules_page = self.page_url(env, project_id).replace("step=1", "step=2")
        return {
            "mapping_markdown": report.render_mappings(report=built_report, page_url=rules_page),
            "mappings_to_confirm": report.has_mappings_to_confirm(built_report),
            "views_markdown": report.render_views_prompt(
                report=built_report, page_url=rules_page
            ),
        }

    async def set_enqueue_views(
        self,
        env: str,
        project_id: int,
        view_urls: dict[str, str],
    ) -> dict[str, Any]:
        """Fill each round's enqueue view link into the existing draft and save it.

        Links are parsed first; any link that fails to parse stops the save.
        Called with links the user gave in the conversation, so no preview step.
        """
        target = get_env(env)
        editor = await self._editor(env, project_id)
        draft = editor.get("draft")
        if not draft:
            raise errors.AuditWorkbenchError(errors.NOT_FOUND, "项目还没有草稿，先生成推荐配置")
        config = draft["config"]
        rules = {r.get("roundId"): r for r in config.get("auditStatusRules") or []}
        unknown = [rid for rid in view_urls if rid not in rules]
        if unknown:
            raise errors.AuditWorkbenchError(
                errors.VALIDATION_FAILED, "草稿里没有这些轮次", detail={"round_ids": unknown}
            )
        parsed = {}
        for round_id, url in view_urls.items():
            parsed[round_id] = await self._client.request(
                target, "POST", "/admin/audit-workbench/parse-view-filter", json={"view_url": url}
            )
            rules[round_id]["enqueueViewUrl"] = url
        body = {
            "config": _without_field_pool(config),
            "base_updated_at": draft.get("updated_at"),
            "wizard_step": draft.get("wizard_step") or 1,
            "force": False,
            "feishu_app_token": draft.get("feishu_app_token"),
            "feishu_table_id": draft.get("feishu_table_id"),
            "feishu_view_id": draft.get("feishu_view_id"),
        }
        saved = await self._write(
            env, project_id, "PUT", f"/admin/projects/{project_id}/audit-workbench/draft", body
        )
        saved["views"] = {
            rid: {"view_name": p.get("view_name"), "summary": p.get("summary_text")}
            for rid, p in parsed.items()
        }
        saved["page_url"] = self.page_url(env, project_id).replace("step=1", "step=2")
        names = {r.get("id"): r.get("name") or r.get("id") for r in config.get("fieldRounds") or []}
        saved["missing_views"] = [rid for rid, r in rules.items() if not r.get("enqueueViewUrl")]
        saved["views_markdown"] = report.render_views_result(
            views=saved["views"], round_names=names, missing=saved["missing_views"],
            page_url=saved["page_url"],
        )
        return saved

    # ---- hand-off (3.4) -------------------------------------------------------

    async def ensure_app_collaborator(self, env: str, app_token: str) -> dict[str, Any]:
        """Initialization step: make 人才招聘 a manage collaborator of the base."""
        result = await asyncio.to_thread(lark.ensure_app_collaborator, app_token)
        return self._ok(env, None, result)

    async def pre_publish_checklist(self, env: str, project_id: int) -> dict[str, Any]:
        editor = await self._editor(env, project_id)
        draft = editor.get("draft")
        if not draft:
            raise errors.AuditWorkbenchError(errors.NOT_FOUND, "项目没有草稿，没有可发布的内容")
        config = draft["config"]
        checked = (await self.check_readiness(env, project_id, config))["data"]
        workbench_type = int(checked["summary"].get("workbench_type") or config.get("workbenchType") or 1)
        planned = handoff.planned_workflows(config, workbench_type)
        blockers = [str(i.get("message")) for i in checked["items"]]
        text = handoff.render_pre_publish_checklist(
            env=env, project_id=project_id, page_url=self.page_url(env, project_id),
            draft_updated_at=draft.get("updated_at"), workbench_type=workbench_type,
            planned=planned, blockers=blockers,
        )
        return self._ok(
            env, project_id,
            {"publishable": not blockers, "planned": planned, "blockers": blockers},
            checklist_markdown=text,
            base_version=(editor.get("published") or {}).get("version") or 0,
        )

    async def verify_pipeline(
        self, env: str, project_id: int, timeout: float = 90, interval: float = 5
    ) -> dict[str, Any]:
        """After publish: auditors, talent_id lookup, 人才招聘 collaborator, workflow creation."""
        target = get_env(env)
        editor = await self._editor(env, project_id)
        published = editor.get("published") or {}
        version = int(published.get("version") or 0)
        if not version:
            raise errors.AuditWorkbenchError(errors.NOT_FOUND, "项目还没有发布，先发布再做全链路校验")
        config = published.get("config") or {}
        table_url = str(config.get("feishuTableUrl") or "")
        # No project_id: parse only, do not rewrite the project's field catalog.
        parsed = await self._client.request(
            target, "POST", "/admin/audit-workbench/parse-feishu", json={"table_url": table_url}
        )
        app_token, table_id = str(parsed.get("app_token") or ""), str(parsed.get("table_id") or "")

        auditors = await self._client.request(
            target, "GET", f"/admin/projects/{project_id}/auditors", params={"skip": 0, "limit": 1}
        )
        count = int((auditors.get("summary") or {}).get("auditor_count") or auditors.get("count") or 0)
        fields, tables, collaborator = await asyncio.gather(
            asyncio.to_thread(lark.list_fields, app_token, table_id),
            asyncio.to_thread(lark.list_tables, app_token),
            asyncio.to_thread(lark.app_collaborator, app_token),
        )
        waited = await self.wait_workflows(env, project_id, timeout, interval)

        items = (
            [pipeline_check.auditors_item(count)]
            + pipeline_check.talent_id_items(config, fields, tables)
            + [pipeline_check.collaborator_item(collaborator)]
            + [pipeline_check.workflow_item(waited["data"], waited["timed_out"])]
        )
        result = pipeline_check.judge(items)
        text = pipeline_check.render(result, env=env, project_id=project_id, version=version)
        return self._ok(env, project_id, result, checklist_markdown=text,
                        timed_out=waited["timed_out"], published_version=version)

    async def _workflow_rows(self, summary: dict[str, Any]) -> list[dict[str, Any]]:
        app_token = summary.get("appToken") or ""
        states: dict[str, dict[str, Any]] = {}
        for item in summary.get("items") or []:
            wid = item.get("workflowId")
            if not wid or not app_token:
                continue
            state = await asyncio.to_thread(lark.get_workflow, app_token, wid)
            state["repaired"] = lark.has_manual_clear_step(state.get("steps") or [])
            states[wid] = state
        return handoff.workflow_rows(summary, states)

    async def created_workflows(
        self, env: str, project_id: int, timeout: float = 90, interval: float = 5
    ) -> dict[str, Any]:
        """After publish: wait for sync, then read each workflow's enabled / repaired state."""
        waited = await self.wait_workflows(env, project_id, timeout, interval)
        summary = waited["data"]
        rows = await self._workflow_rows(summary)
        text = handoff.render_workflows(rows, summary.get("problems") or [], waited["timed_out"])
        return self._ok(env, project_id, {"rows": rows, "summary": summary},
                        workflows_markdown=text, timed_out=waited["timed_out"])

    async def enable_workflows(
        self,
        env: str,
        project_id: int,
        confirm: bool = False,
        confirm_project_id: int | None = None,
    ) -> dict[str, Any]:
        """Enable synced workflows. Template-two audit-action workflows only once repaired."""
        summary = await self._workflows(env, project_id)
        rows = await self._workflow_rows(summary)
        targets = [r for r in rows if r["can_enable"]]
        skipped = [{"label": r["label"], "reason": r["skip_reason"]} for r in rows if not r["can_enable"]]
        if not confirm:
            return await self._preview(
                env, project_id, "enable_workflows",
                {"enable": [r["label"] for r in targets], "skip": skipped},
                "启用后，底表记录满足入队条件就会为审核员创建任务。", [],
                current={"workflows": len(rows)},
            )
        self._check_confirm(env, project_id, confirm_project_id)
        app_token = summary.get("appToken") or ""
        results = []
        for r in targets:
            res = await asyncio.to_thread(lark.enable_workflow, app_token, r["workflow_id"])
            after = await asyncio.to_thread(lark.get_workflow, app_token, r["workflow_id"])
            results.append({
                "label": r["label"],
                "ok": bool(res.get("ok")) and after.get("status") == handoff.ENABLED,
                "message": res.get("message") or ("" if after.get("status") == handoff.ENABLED else "回读状态不是已启用"),
            })
        return self._ok(env, project_id, {"enabled": results, "skipped": skipped}, executed=True)

    async def onboard_status(self, env: str, project_id: int) -> dict[str, Any]:
        """One read of everything resume needs: editor, workflows, auditors, binding."""
        target = get_env(env)
        base = f"/admin/projects/{project_id}"
        editor, workflows, auditors, binding = await asyncio.gather(
            self._editor(env, project_id),
            self._workflows(env, project_id),
            self._client.request(target, "GET", f"{base}/auditors", params={"skip": 0, "limit": 1}),
            self._client.request(target, "GET", f"{base}/auditors/feishu-binding"),
        )
        published = int((editor.get("published") or {}).get("version") or 0)
        rows = await self._workflow_rows(workflows) if published and not editor.get("draft") else []
        count = int((auditors.get("summary") or {}).get("auditor_count") or auditors.get("count") or 0)
        result = onboard_status.judge(editor, workflows, rows, count, binding.get("items") or [])
        return self._ok(env, project_id, result, summary=snapshot_from_editor(editor),
                        page_url=self.page_url(env, project_id))

    async def trace(
        self,
        env: str,
        project_id: int,
        record_id: str,
        talent_id: int | None = None,
        stage: int | None = None,
    ) -> dict[str, Any]:
        """Backend record trace, plus the Feishu enabled state of that round's enqueue workflow and,
        for post-submit verdicts the platform cannot settle, the backend run logs in SLS."""
        params = {"record_id": record_id, "talent_id": talent_id, "stage": stage}
        data = await self._client.request(
            get_env(env), "GET", f"/admin/projects/{project_id}/audit-workbench/trace", params=params
        )
        check = next(
            (c for c in data.get("checks") or [] if c["key"] == "workflow" and c["state"] == "unverified"),
            None,
        )
        app_token = (data.get("workflows") or {}).get("appToken") or ""
        if check is not None and check.get("workflowId") and app_token:
            state = await asyncio.to_thread(lark.get_workflow, app_token, check["workflowId"])
            trace_mod.apply_workflow_state(data["checks"], state)
            data["diagnosis"] = trace_mod.diagnose(data["checks"], data.get("dataUrl") or "")
        submit = data.get("submit") or {}
        if submit.get("result") in trace_mod.LOG_RESULTS:
            found = await asyncio.to_thread(
                sls.search_record, env, record_id, trace_mod.log_since(data)
            )
            trace_mod.apply_logs(data, found)
        return self._ok(env, project_id, data, trace_markdown=trace_mod.render(data))

    async def check_auditor_binding(
        self, env: str, project_id: int, talent_ids: list[int] | None = None
    ) -> dict[str, Any]:
        params = {"talent_ids": talent_ids} if talent_ids else None
        data = await self._client.request(
            get_env(env), "GET", f"/admin/projects/{project_id}/auditors/feishu-binding", params=params
        )
        items = data.get("items") or []
        return self._ok(env, project_id, data, binding_markdown=handoff.render_binding(items),
                        unbound=[i["talentId"] for i in items if i.get("state") == "UNBOUND"])
