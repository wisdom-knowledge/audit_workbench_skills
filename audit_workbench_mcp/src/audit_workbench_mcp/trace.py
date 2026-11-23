"""Record trace: fill the workflow-enabled step the backend cannot read, re-derive the
verdict with the same rule as the backend, and render a short report.
"""

from __future__ import annotations

from typing import Any

from . import handoff

PASS, FAIL, UNVERIFIED, SKIP = "pass", "fail", "unverified", "skip"
_ICON = {PASS: "✅", FAIL: "❌", UNVERIFIED: "❔", SKIP: "➖"}


def apply_workflow_state(checks: list[dict[str, Any]], state: dict[str, Any] | None) -> None:
    """state is lark.get_workflow output for the round's enqueue workflow, or None if unread."""
    check = next((c for c in checks if c["key"] == "workflow" and c["state"] == UNVERIFIED), None)
    if check is None or state is None:
        return
    if not state.get("ok"):
        check["evidence"] = check["evidence"].replace("需要回读", "回读失败") + f"：{state.get('message') or ''}".rstrip("：")
        return
    if state.get("status") == handoff.ENABLED:
        check["state"] = PASS
        check["evidence"] = check["evidence"].split("，")[0] + "，飞书上已启用"
        check["next"] = None
    else:
        check["state"] = FAIL
        check["evidence"] = check["evidence"].split("，")[0] + "，但飞书上没有启用"
        check["next"] = "用 enable_workflows 启用；启用后要改动一次这条记录才会触发入队"


def diagnose(checks: list[dict[str, Any]], data_url: str = "") -> dict[str, Any]:
    """Same rule as the backend: first fail; else the unverified ones; else all_pass."""
    first_fail = next((c for c in checks if c["state"] == FAIL), None)
    if first_fail is not None:
        return {"result": "blocked", "step": first_fail["key"], "label": first_fail["label"],
                "message": first_fail["evidence"], "next": first_fail["next"]}
    unverified = [c for c in checks if c["state"] == UNVERIFIED]
    if unverified:
        return {"result": "unverified", "step": unverified[0]["key"], "label": unverified[0]["label"],
                "message": "；".join(c["evidence"] for c in unverified), "next": unverified[0]["next"]}
    tail = f"。记录链接：{data_url}" if data_url else ""
    return {
        "result": "all_pass", "step": None, "label": None,
        "message": "按已有证据，链路各环节都正常，无法解释为什么看不到",
        "next": "请审核员刷新专家端对应轮次的列表，确认登录的账号就是这个 talent_id；仍看不到时把 "
                "record_id、talent_id 和本次结果交给研发" + tail,
    }


def _round_rows(rounds: list[dict[str, Any]]) -> list[str]:
    # 模版二多一列飞书当前的审核操作值
    action = any("actionValue" in r for r in rounds)
    head = "| 轮次 | 飞书当前状态 | 平台任务状态 | 一致 | 入队条件 |" + (" 审核操作列 |" if action else "")
    lines = [head, "|-|-|-|-|-|" + ("-|" if action else "")]
    for r in rounds:
        consistent = {True: "是", False: "**否**", None: "—"}[r.get("consistent")]
        if r.get("viewActive"):
            view = "满足" if r.get("viewMatched") else "**不满足**"
        else:
            view = "无筛选，按状态"
        row = (
            f"| {r['stage']} | {r.get('statusLabel') or '空'} | {r.get('taskStatusLabel') or '无任务'} "
            f"| {consistent} | {view} |"
        )
        if action:
            row += f" {r.get('actionValue') or '空'} |" if r.get("actionConfigured") else " 未配置 |"
        lines.append(row)
    return lines


def _submit_lines(submit: dict[str, Any] | None) -> list[str]:
    if not submit:
        return []
    lines = ["", "**提交后**", "", submit["message"]]
    if submit.get("next"):
        lines += ["", f"下一步：{submit['next']}"]
    diff = (submit.get("lastSubmit") or {}).get("diff") or {}
    if diff:
        changes = "；".join(f"{k}：{v.get('from') or '空'} → {v.get('to') or '空'}" for k, v in diff.items())
        lines += ["", f"最近一次提交改了：{changes}"]
    if submit.get("viewNote"):
        lines += ["", submit["viewNote"]]
    return lines


def render(data: dict[str, Any]) -> str:
    diag = data["diagnosis"]
    head = {
        "blocked": f"**卡在：{diag['label']}**",
        "unverified": f"**没有查到明确卡点，有环节未核验：{diag['label']}**",
        "all_pass": "**各环节都通过，按证据无法解释**",
    }[diag["result"]]
    lines = [f"记录 `{data['recordId']}`，第 {data['stage']} 轮", "", head, "", diag["message"]]
    if diag.get("next"):
        lines += ["", f"下一步：{diag['next']}"]
    lines += ["", "| 环节 | 结果 | 证据 |", "|-|-|-|"]
    for c in data["checks"]:
        lines.append(f"| {c['label']} | {_ICON[c['state']]} | {c['evidence']} |")
    lines += _submit_lines(data.get("submit"))
    rounds = (data.get("feishu") or {}).get("rounds") or []
    if rounds:
        lines += ["", *_round_rows(rounds)]
    elif (data.get("feishu") or {}).get("error"):
        lines += ["", f"飞书记录：{data['feishu']['error']}"]
    return "\n".join(lines)
