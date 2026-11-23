"""Render the draft suggestion as the agreed terminal report (Markdown).

Part 1 lists every recommended field per round, all taken from the project's own
base. Part 2 lists, round by round, the mappings that were not resolved (first,
red) and the ones recommended by inference that the user should confirm (yellow).
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
        "",
    ]
    if saved:
        # 草稿已保存时用户要去配置页核对，链接单独成块放在最前面
        lines += [
            "> 👉 **管理端配置页：草稿已保存，可以打开核对和修改**",
            ">",
            f"> **{page_url}**",
            "",
        ]
    else:
        lines += [f"配置页：{page_url}", ""]
    lines += [
        "**一、推荐的展示字段**",
        "",
        f"以下字段都来自本项目底表（已解析 {report['base_field_count']} 列）。"
        "布局按这些字段生成，可在配置页第 3 步查看。",
        "",
    ]
    lines += _fields_section(rounds)

    lines += ["**二、需要确认的字段映射**", ""]
    lines += _mapping_section(rounds)
    lines += ["", "---", "", "**请核实以下三点：**", ""]
    lines.append("1. 展示的字段集合需要调整吗？比如增减字段、修改展示位置或编辑权限。")
    lines.append("2. 上面的字段映射需要调整吗？")
    lines.append("3. 请给出每一轮的入队条件（视图链接）：")
    for r in rounds:
        url = (view_urls or {}).get(r["round_id"], "")
        lines.append(f"   - {r['name']}：{url}")
    lines += ["", f"可以直接在配置页修改并保存（{page_url}），也可以在这里回复，我来更新草稿。"]
    return "\n".join(lines)
