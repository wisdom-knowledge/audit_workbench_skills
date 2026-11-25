"""Post-publish full-chain check: auditors, base dependencies, workflow creation.

Pure functions over data already fetched, so the rules are easy to test. Every
item is pass or fail; a check that could not be read counts as fail. The only
exception is workflow creation still in progress when the wait ran out, which
is reported as pending, never as passed.
"""

from __future__ import annotations

from typing import Any

from . import lark

PASS, FAIL, PENDING = "pass", "fail", "pending"
_ICON = {PASS: "✅", FAIL: "❌", PENDING: "⏳"}

LOOKUP = "lookup"


def _item(key: str, label: str, state: str, detail: str) -> dict[str, Any]:
    return {"key": key, "label": label, "state": state, "detail": detail}


def auditors_item(count: int) -> dict[str, Any]:
    if count > 0:
        return _item("auditors", "有审核员", PASS, f"已有 {count} 位审核员")
    return _item("auditors", "有审核员", FAIL, "项目还没有审核员，用 add_auditors 添加")


def _round_names(config: dict[str, Any]) -> dict[str, str]:
    return {
        str(r.get("id") or ""): str(r.get("name") or r.get("id") or "")
        for r in config.get("fieldRounds") or []
        if isinstance(r, dict)
    }


def talent_id_items(
    config: dict[str, Any],
    fields: dict[str, Any],
    tables: dict[str, Any],
) -> list[dict[str, Any]]:
    """One item per round: the talent_id field must be a lookup into a table of this base."""
    label = "依赖无误：审核员 talent_id 引用"
    rules = [r for r in config.get("auditStatusRules") or [] if isinstance(r, dict)]
    if not rules:
        return [_item("talent_id_lookup", label, FAIL, "已发布配置里没有轮次规则")]
    if not fields.get("ok"):
        return [_item("talent_id_lookup", label, FAIL, f"读不到底表字段：{fields.get('message') or '未知错误'}")]
    if not tables.get("ok"):
        return [_item("talent_id_lookup", label, FAIL, f"读不到底表所在多维表格的数据表：{tables.get('message') or '未知错误'}")]

    by_id = {str(f.get("id") or ""): f for f in fields.get("fields") or []}
    known = {t["id"] for t in tables["tables"] if t["id"]} | {t["name"] for t in tables["tables"] if t["name"]}
    names = _round_names(config)
    items = []
    for rule in rules:
        round_id = str(rule.get("roundId") or "")
        prefix = f"{names.get(round_id) or round_id}："
        fid = str(rule.get("talentIdFieldId") or "").strip()
        field = by_id.get(fid)
        if not fid:
            state, detail = FAIL, "没有配置 talent_id 字段"
        elif field is None:
            state, detail = FAIL, f"talent_id 字段 {fid} 在底表里不存在"
        elif field.get("type") != LOOKUP:
            state, detail = FAIL, f"「{field.get('name')}」是 {field.get('type')} 字段，不是查找引用"
        elif str(field.get("from") or "") not in known:
            state, detail = FAIL, f"「{field.get('name')}」引用的表 {field.get('from') or '空'} 不在当前多维表格里"
        else:
            state, detail = PASS, f"「{field.get('name')}」引用「{field.get('from')}」的 {field.get('select')}"
        items.append(_item("talent_id_lookup", label, state, prefix + detail))
    return items


def collaborator_item(state: dict[str, Any]) -> dict[str, Any]:
    label = f"依赖无误：「{lark.RECRUIT_APP_NAME}」是底表管理协作者"
    if not state.get("ok"):
        return _item("app_collaborator", label, FAIL, f"读不到底表协作者：{state.get('message') or '未知错误'}")
    member = state.get("member")
    if member is None:
        return _item("app_collaborator", label, FAIL, "不是底表协作者，用 ensure_app_collaborator 添加")
    if member.get("perm") != lark.FULL_ACCESS:
        return _item("app_collaborator", label, FAIL,
                     f"权限是 {member.get('perm')}，不是可管理，用 ensure_app_collaborator 升级")
    return _item("app_collaborator", label, PASS, "已是可管理协作者")


def workflow_item(summary: dict[str, Any], timed_out: bool) -> dict[str, Any]:
    label = "工作流创建"
    if _hard_problem(summary):
        problems = [p for p in summary.get("problems") or [] if "不代表成功" not in p]
        return _item("workflows", label, FAIL, "；".join(problems) or "工作流同步有问题")
    if timed_out or not summary.get("settled"):
        return _item("workflows", label, PENDING, "还有工作流在排队或执行中，稍后再查一次")
    return _item("workflows", label, PASS, f"{len(summary.get('items') or [])} 条工作流都已在飞书上创建")


def _hard_problem(summary: dict[str, Any]) -> bool:
    """A problem that waiting will not fix: failed, retrying, manual, plan error, missing rows."""
    if summary.get("planError") or int(summary.get("publishedVersion") or 0) == 0:
        return True
    items = summary.get("items") or []
    if len(items) < int(summary.get("expectedCount") or 0):
        return True
    return any(i.get("display_status") in ("failed", "retrying", "manual") for i in items)


def judge(items: list[dict[str, Any]]) -> dict[str, Any]:
    states = [i["state"] for i in items]
    return {
        "items": items,
        "all_passed": all(s == PASS for s in states),
        "failed": states.count(FAIL),
        "pending": states.count(PENDING),
    }


def render(result: dict[str, Any], *, env: str, project_id: int, version: int) -> str:
    lines = [f"**全链路校验**：项目 {project_id} · {env.upper()} · 已发布 v{version}", ""]
    for item in result["items"]:
        lines.append(f"- {_ICON[item['state']]} **{item['label']}**：{item['detail']}")
    lines.append("")
    if result["all_passed"]:
        lines.append("以上各项都已通过。")
    elif result["failed"]:
        lines.append("有 ❌ 的项要先处理，处理完再校验一次。")
    else:
        lines.append("工作流还在创建中，稍后再校验一次。")
    return "\n".join(lines)
