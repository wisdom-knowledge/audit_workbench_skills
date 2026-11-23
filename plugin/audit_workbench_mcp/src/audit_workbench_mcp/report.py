"""Render the draft suggestion as the agreed terminal report (Markdown).

Step 2 of onboarding is confirmed in three parts, one message each:
2.1 the recommended fields per round, all taken from the project's own base;
2.2 round by round, the role and status mappings that were not resolved (first,
red) and the ones recommended by inference that the user should confirm (yellow);
2.3 the enqueue view link of each round.
"""

from __future__ import annotations

from typing import Any

from .draft_builder import HIGH, UNRESOLVED

AREA_ORDER = ("QUESTION_INFO", "EXPERT_INFO", "MACHINE_AUDIT_INFO", "AUDIT_ACTION")
AREA_LABEL = {
    "QUESTION_INFO": "🟦 题目信息",
    "EXPERT_INFO": "🟩 专家信息",
    "MACHINE_AUDIT_INFO": "🟪 机审信息",
    "AUDIT_ACTION": "🟧 审核操作",
}
AREA_ICON = {k: v.split()[0] for k, v in AREA_LABEL.items()}
PERM_LABEL = {"READONLY": "⚪ 仅阅读", "EDITABLE": "🔵 可编辑"}
ROLE_LABEL = {
    "status": "审核状态字段",
    "reviewer": "审核人字段",
    "talent_id": "talent_id 字段",
    "audit_advice": "审核建议字段",
    "audit_action": "审核操作字段",
}
TEMPLATE_LABEL = {1: "模版一", 2: "模版二"}


def _cell(text: Any) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def _fields_section(rounds: list[dict[str, Any]]) -> list[str]:
    lines = [
        "图例：" + "　".join(AREA_LABEL[a] for a in AREA_ORDER) + "　｜　" + "　".join(PERM_LABEL.values()),
        "",
    ]
    for r in rounds:
        fields = [item["field"] for item in r["fields"]]
        fields.sort(key=lambda f: AREA_ORDER.index(f["displayArea"]) if f["displayArea"] in AREA_ORDER else 9)
        area_counts = "　".join(
            f"{AREA_ICON[a]} {n}" for a in AREA_ORDER if (n := sum(f["displayArea"] == a for f in fields))
        )
        perm_counts = "　".join(
            f"{PERM_LABEL[p].split()[0]} {n}" for p in PERM_LABEL if (n := sum(f["permission"] == p for f in fields))
        )
        lines.append(f"{r['name']}（{len(fields)} 个字段：{area_counts}　｜　{perm_counts}）")
        lines.append("")
        if not fields:
            lines += ["没有推荐出字段：参考项目中的字段在本项目底表里都没有对应。", ""]
            continue
        lines += ["| 字段 | 展示位置 | 编辑权限 |", "|-|-|-|"]
        for f in fields:
            lines.append(
                f"| {_cell(f['name'])} | {AREA_LABEL.get(f['displayArea'], f['displayArea'])} "
                f"| {PERM_LABEL.get(f['permission'], f['permission'])} |"
            )
        lines.append("")
    return lines


def _round_mappings(r: dict[str, Any]) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """One round's mappings to confirm: (unresolved [(item, hint)], low [(item, value, reason)])."""
    unresolved: list[tuple[str, str]] = []
    low: list[tuple[str, str, str]] = []
    items: list[tuple[str, str, str, str, bool]] = []
    for role, info in r["roles"].items():
        items.append((ROLE_LABEL[role], info["name"], info["confidence"], info["reason"], False))
    for option, info in r["status_mapping"].items():
        items.append((f"状态「{option}」", info["target"], info["confidence"], info["reason"], True))
    for label, value, confidence, reason, is_status in items:
        if confidence == HIGH:
            continue
        if confidence == UNRESOLVED:
            hint = reason or ("请从 7 个平台状态中选一个" if is_status else "请在配置页选择字段")
            unresolved.append((label, hint))
        else:
            low.append((label, value, reason))
    return unresolved, low


def _mapping_section(rounds: list[dict[str, Any]]) -> list[str]:
    """Per round: unresolved first (high priority), then auto-recommended ones to confirm."""
    per_round = [(r, *_round_mappings(r)) for r in rounds]
    if not any(unresolved or low for _, unresolved, low in per_round):
        return ["所有字段映射和状态枚举都按名称一致或多数参考项目推荐，没有需要单独确认的项。"]
    lines = ["图例：🔴 没推荐出来，需要你来选　｜　🟡 系统自动推荐出来但是需要你确认", ""]
    for r, unresolved, low in per_round:
        lines += [f"**{r['name']}**", ""]
        if not unresolved and not low:
            lines += ["本轮没有需要确认的映射。", ""]
            continue
        if unresolved:
            lines += [f"🔴 **没推荐出来，需要你来选（{len(unresolved)} 项）**", "",
                      "| 映射项 | 说明 |", "|-|-|"]
            lines += [f"| 🔴 {_cell(label)} | {_cell(hint)} |" for label, hint in unresolved]
            lines.append("")
        if low:
            lines += [f"🟡 系统自动推荐出来但是需要你确认（{len(low)} 项）", "",
                      "| 映射项 | 推荐值 | 推荐依据 |", "|-|-|-|"]
            lines += [f"| 🟡 {_cell(label)} | {_cell(value)} | {_cell(reason) or '按语义推断'} |"
                      for label, value, reason in low]
            lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def link_block(page_url: str, saved: bool = True) -> list[str]:
    """Config page link shown as the last lines of every confirmation step, right after the question."""
    title = "管理端配置页" if saved else "管理端配置页（草稿尚未保存，确认覆盖后页面上才有推荐结果）"
    return ["", f"> 👉 **{title}**", ">", f"> **{page_url}**"]


def render_report(
    *,
    report: dict[str, Any],
    env: str,
    project_id: int,
    page_url: str,
    saved: bool,
) -> str:
    """Step 2.1: header and the recommended fields; ends with the question and the config page link."""
    rounds = report["rounds"]
    refs = report["references"]
    head = "**推荐配置已保存为草稿**" if saved else "**推荐配置（尚未保存：项目已有草稿，确认覆盖后才会保存）**"
    lines = [
        f"{head}：项目 {project_id} · {env.upper()} · {TEMPLATE_LABEL.get(report['workbench_type'], '')}",
        f"参考项目（同模版、最近发布的 {len(refs)} 个）：" + "、".join(str(r["project_id"]) for r in refs),
        "",
        "**2.1 确认展示的字段**",
        "",
        f"以下字段都来自本项目底表（已解析 {report['base_field_count']} 列）。"
        "布局按这些字段生成，可在配置页第 3 步查看。",
        "",
    ]
    lines += _fields_section(rounds)
    lines += [
        "---",
        "",
        "**展示的字段有需要调整的吗？**（比如增减字段、修改展示位置或编辑权限）"
        "可以直接在配置页手动调整并保存，也可以告诉我，我帮你调整。",
    ]
    lines += link_block(page_url, saved)
    return "\n".join(lines)


def has_mappings_to_confirm(report: dict[str, Any]) -> bool:
    return any(u or low for u, low in (_round_mappings(r) for r in report["rounds"]))


def render_mappings(*, report: dict[str, Any], page_url: str) -> str:
    """Step 2.2: per round, unresolved mappings first, then the auto-recommended ones to confirm."""
    lines = ["**2.2 确认字段映射和状态枚举映射**", ""]
    lines += _mapping_section(report["rounds"])
    if not has_mappings_to_confirm(report):
        return "\n".join(lines)
    lines += [
        "",
        "---",
        "",
        "🔴 的项请给出选择，🟡 的项请确认推荐值是否正确。**映射有需要调整的吗？**"
        "可以直接在配置页第 2 步手动调整并保存，也可以告诉我，我帮你调整。",
    ]
    lines += link_block(page_url)
    return "\n".join(lines)


def render_views_prompt(*, report: dict[str, Any], page_url: str) -> str:
    """Step 2.3: ask for each round's enqueue view link; page_url points at the views step."""
    lines = [
        "**2.3 给出每一轮的入队条件**",
        "",
        "请提供每一轮的入队视图链接（底表里筛选出「这一轮该进专家端」的记录的视图，链接里要有 "
        "table= 和 view=）：",
        "",
    ]
    lines += [f"- {r['name']}：" for r in report["rounds"]]
    lines += [
        "",
        "---",
        "",
        "可以直接在配置页第 2 步手动填写并保存，也可以把链接发给我，我帮你填。",
    ]
    lines += link_block(page_url)
    return "\n".join(lines)


def render_views_result(
    *, views: dict[str, dict[str, Any]], round_names: dict[str, str], missing: list[str], page_url: str
) -> str:
    """After set_enqueue_views: each saved round's view and filter summary, rounds still missing, link last."""
    lines = ["**2.3 入队条件已写入草稿，请核对**", "", "| 轮次 | 视图 | 筛选条件 |", "|-|-|-|"]
    for round_id, v in views.items():
        lines.append(
            f"| {_cell(round_names.get(round_id, round_id))} | {_cell(v.get('view_name')) or '—'} "
            f"| {_cell(v.get('summary')) or '（无筛选条件）'} |"
        )
    if missing:
        lines += ["", "🔴 还差这几轮的入队视图：" + "、".join(round_names.get(r, r) for r in missing)]
    lines += [
        "",
        "---",
        "",
        "**入队条件有需要调整的吗？**可以直接在配置页第 2 步手动调整并保存，也可以告诉我，我帮你调整。",
    ]
    lines += link_block(page_url)
    return "\n".join(lines)
