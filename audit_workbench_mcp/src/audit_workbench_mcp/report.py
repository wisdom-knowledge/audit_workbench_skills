"""Render the draft suggestion as the agreed terminal report (Markdown).

Part 1 lists every recommended field per round, all taken from the project's own
base. Part 2 lists only mappings that were not resolved or are low confidence.
The report ends by asking the user to check both parts and give each round's
enqueue view link.
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


def _mapping_rows(rounds: list[dict[str, Any]]) -> list[tuple[str, str, str, str]]:
    """(rounds, item, value, note) rows; identical items across rounds are merged."""
    merged: dict[tuple[str, str, str], list[str]] = {}
    for r in rounds:
        items: list[tuple[str, str, str]] = []
        for role, info in r["roles"].items():
            if info["confidence"] == HIGH:
                continue
            items.append((ROLE_LABEL[role], info["name"], info["confidence"], info["reason"]))
        for option, info in r["status_mapping"].items():
            if info["confidence"] == HIGH:
                continue
            items.append((f"状态「{option}」", info["target"], info["confidence"], info["reason"]))
        for label, value, confidence, reason in items:
            if confidence == UNRESOLVED:
                shown, note = "**未推荐出**", reason or (
                    "请从 7 个平台状态中选一个" if label.startswith("状态") else "请在配置页选择字段"
                )
            else:
                shown, note = value, f"低置信：{reason}" if reason else "低置信"
            merged.setdefault((label, shown, note), []).append(r["name"])
    rows = []
    for (label, shown, note), names in merged.items():
        rounds_text = names[0] if len(names) == 1 else names[0] + "、" + "、".join(n.removeprefix("轮次") for n in names[1:])
        rows.append((rounds_text, label, shown, note))
    return rows


def render_report(
    *,
    report: dict[str, Any],
    env: str,
    project_id: int,
    page_url: str,
    saved: bool,
    view_urls: dict[str, str] | None = None,
) -> str:
    rounds = report["rounds"]
    refs = report["references"]
    head = "**推荐配置已保存为草稿**" if saved else "**推荐配置（尚未保存：项目已有草稿，确认覆盖后才会保存）**"
    lines = [
        f"{head}：项目 {project_id} · {env.upper()} · {TEMPLATE_LABEL.get(report['workbench_type'], '')}",
        f"参考项目（同模版、最近发布的 {len(refs)} 个）：" + "、".join(str(r["project_id"]) for r in refs),
        f"配置页：{page_url}",
        "",
        "**一、推荐的展示字段**",
        "",
        f"以下字段都来自本项目底表（已解析 {report['base_field_count']} 列）。"
        "布局按这些字段生成，可在配置页第 3 步查看。",
        "",
    ]
    lines += _fields_section(rounds)

    lines += ["**二、需要确认的字段映射**", ""]
    rows = _mapping_rows(rounds)
    if rows:
        lines += ["只列出没推荐出来的，以及低置信度的：", "", "| 轮次 | 映射项 | 推荐值 | 说明 |", "|-|-|-|-|"]
        lines += [f"| {_cell(a)} | {_cell(b)} | {c} | {_cell(d)} |" for a, b, c, d in rows]
    else:
        lines.append("所有字段映射和状态枚举都按名称一致或多数参考项目推荐，没有需要单独确认的项。")
    lines += ["", "---", "", "**请核实以下三点：**", ""]
    lines.append("1. 展示的字段集合需要调整吗？比如增减字段、修改展示位置或编辑权限。")
    lines.append("2. 上面的字段映射需要调整吗？")
    lines.append("3. 请给出每一轮的入队条件（视图链接）：")
    for r in rounds:
        url = (view_urls or {}).get(r["round_id"], "")
        lines.append(f"   - {r['name']}：{url}")
    lines += ["", "可以直接在配置页修改并保存，也可以在这里回复，我来更新草稿。"]
    return "\n".join(lines)
