"""Rules and report text for the hand-off: pre-publish checklist, created workflows,
which workflows may be enabled, and auditor Feishu binding.
"""

from __future__ import annotations

from typing import Any

from .draft_builder import round_name

TEMPLATE_TWO = 2
REPAIR_STEP = "在工作流触发后的第一步，加一个「修改记录」，把本轮审核操作列设为空"


def _col(name: str | None) -> str:
    return f"「{name}」" if name else "「未配置」"


def planned_workflows(config: dict[str, Any], workbench_type: int) -> list[dict[str, Any]]:
    """Workflows the Worker will create after publish, described by column names."""
    names = {
        str(f.get("id")): str(f.get("name") or "")
        for pool in (config.get("sourceFields") or [], config.get("fields") or [])
        for f in pool
        if isinstance(f, dict)
    }
    out = []
    for index, rule in enumerate(config.get("auditStatusRules") or []):
        label = round_name(index)
        out.append(
            {
                "round": label,
                "kind": "入队",
                "detail": f"监听{_col(names.get(rule.get('statusFieldId', '')))}"
                f"{_col(names.get(rule.get('talentIdFieldId', '')))}，满足入队条件时为审核员建任务",
                "needs_repair": False,
            }
        )
        if workbench_type == TEMPLATE_TWO:
            out.append(
                {
                    "round": label,
                    "kind": "审核操作",
                    "detail": f"审核员点击打回/通过/拒绝后，写回{_col(names.get(rule.get('statusFieldId', '')))}"
                    f"并记录操作日志（监听{_col(names.get(rule.get('auditActionFieldId', '')))}）",
                    "needs_repair": True,
                }
            )
    return out


def render_pre_publish_checklist(
    *,
    env: str,
    project_id: int,
    page_url: str,
    draft_updated_at: str | None,
    workbench_type: int,
    planned: list[dict[str, Any]],
    blockers: list[str],
) -> str:
    lines = [
        f"**发布前确认清单**：项目 {project_id} · {env.upper()} · {'模版二' if workbench_type == TEMPLATE_TWO else '模版一'}",
        "",
        "- [ ] **配置信息是否无误**",
        f"  - 配置页：{page_url}",
        f"  - 草稿最后保存于 {draft_updated_at or '未知'}，发布的是这份草稿",
        "- [ ] **工作流配置是否无误**：发布后会在底表「审核工作台」目录下创建以下工作流（默认停用）",
    ]
    for wf in planned:
        lines.append(f"  - {wf['round']} · {wf['kind']}：{wf['detail']}")
    if any(wf["needs_repair"] for wf in planned):
        lines += [
            "",
            "⚠️ **模版二：发布后「审核操作」工作流需要人工修补**。接口建不出「清空审核操作」这一步，"
            f"需要你在飞书上打开该工作流，{REPAIR_STEP}。修补完成前这条工作流不会被启用。",
        ]
    if blockers:
        lines += ["", "**发布前必须先处理：**"] + [f"- {b}" for b in blockers]
    lines += ["", "确认以上两项无误后回复「确认发布」。"]
    return "\n".join(lines)


ENABLED = "enabled"


def workflow_rows(summary: dict[str, Any], lark_states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge sync rows with what Feishu says (enabled? repaired?) and decide enable eligibility."""
    rows = []
    for item in summary.get("items") or []:
        wid = item.get("workflowId")
        state = lark_states.get(wid or "", {})
        is_action = item.get("kind") == "AUDIT_ACTION"
        repaired = state.get("repaired") if is_action else None
        enabled = state.get("status") == ENABLED if state.get("ok") else None
        reason = ""
        if item["display_status"] != "synced":
            reason = "同步未完成"
        elif not state.get("ok"):
            reason = "读不到飞书上的工作流状态"
        elif enabled:
            reason = "已启用"
        elif is_action and not repaired:
            reason = "等待人工修补"
        rows.append(
            {
                "label": f"{item.get('stageLabel', '')} · {item.get('kindLabel', '')}",
                "workflow_id": wid,
                "url": item.get("workflowUrl"),
                "sync": item["display_status"],
                "enabled": enabled,
                "repaired": repaired,
                "can_enable": reason == "",
                "skip_reason": reason,
            }
        )
    return rows


_SYNC_LABEL = {
    "synced": "✅ 已同步", "pending": "⏳ 排队中", "running": "⏳ 同步中",
    "retrying": "⚠️ 失败待重试", "failed": "❌ 已失败", "manual": "⚠️ 需人工同步",
}


def render_workflows(rows: list[dict[str, Any]], problems: list[str], timed_out: bool) -> str:
    lines = ["**已创建的工作流**", "", "| 工作流 | 同步 | 启用 | 人工修补 | 链接 |", "|-|-|-|-|-|"]
    for r in rows:
        enabled = "已启用" if r["enabled"] else ("未启用" if r["enabled"] is False else "未知")
        repaired = "—" if r["repaired"] is None else ("✅ 已补" if r["repaired"] else "⚠️ 未补")
        lines.append(f"| {r['label']} | {_SYNC_LABEL.get(r['sync'], r['sync'])} | {enabled} | {repaired} | {r['url'] or '—'} |")
    if timed_out:
        lines += ["", "还有工作流在同步中，稍后再查一次。"]
    if problems:
        lines += ["", "**需要处理：**"] + [f"- {p}" for p in problems]
    pending_repair = [r for r in rows if r["repaired"] is False]
    if pending_repair:
        lines += ["", f"⚠️ 请先修补以下工作流：{REPAIR_STEP}。补完后告诉我，我回读确认后再启用："]
        lines += [f"- {r['label']}：{r['url'] or r['workflow_id']}" for r in pending_repair]
    ready = [r for r in rows if r["can_enable"]]
    if ready:
        lines += ["", "确认这些工作流无误后回复「确认启用」，我会启用以下工作流："]
        lines += [f"- {r['label']}" for r in ready]
    return "\n".join(lines)


def render_binding(items: list[dict[str, Any]]) -> str:
    bound = [i for i in items if i["state"] == "BOUND"]
    unbound = [i for i in items if i["state"] == "UNBOUND"]
    unknown = [i for i in items if i["state"] == "UNVERIFIED"]
    lines = [f"**审核员飞书绑定**：共 {len(items)} 人，已绑定 {len(bound)} 人"]
    if bound:
        lines += [""] + [
            f"- ✅ {i['talentName'] or '未知姓名'}（{i['talentId']}）→ 飞书账号 "
            + "、".join(a.get("name") or "未知" for a in i.get("accounts") or [])
            for i in bound
        ]
    if unknown:
        lines += ["", "以下审核员读不到绑定表，无法判断是否已绑定，请稍后重试："]
        lines += [f"- ❔ {i['talentName'] or '未知姓名'}（{i['talentId']}）" for i in unknown]
    if unbound:
        lines += [""] + [
            f"🔴 **{i['talentName'] or '未知姓名'}（talent_id {i['talentId']}）未绑定飞书账号，"
            "请务必通知其在专家端自行完成绑定**"
            for i in unbound
        ]
    return "\n".join(lines)
