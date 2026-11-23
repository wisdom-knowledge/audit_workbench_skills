"""Record trace: fill the workflow-enabled step the backend cannot read, re-derive the
verdict with the same rule as the backend, and render a short report.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import handoff, sls

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


# 提交后判断里这几种结论，运行日志能补上平台没落库的证据
LOG_RESULTS = {"not_submitted", "log_missing", "action_workflow_half", "enqueue_not_returned"}
EVIDENCE_LIMIT = 12


def _kind(message: str) -> str:
    if message.startswith("audit_workbench submit skipped"):
        return "skipped"
    if message.startswith("audit_workbench submit"):
        return "submit_ok"
    if message.startswith(("更新记录失败", "更新记录时发生错误")):
        return "write_failed"
    if message.startswith("audit_workbench review_log write failed"):
        return "review_log_failed"
    if message.startswith("audit_workbench review_log written"):
        return "review_log"
    if message.startswith("audit_workbench enqueue"):
        return "enqueue"
    if message.startswith("audit_workbench advance"):
        return "advance"
    return "other"


def _as_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        t = value
    else:
        try:
            t = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    return t if t.tzinfo else t.replace(tzinfo=sls.BEIJING)


def _fmt(t: datetime) -> str:
    return t.astimezone(sls.BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def log_since(data: dict[str, Any]) -> datetime | None:
    """Search window start: when the round's task was created."""
    task = next((t for t in data.get("tasks") or [] if t.get("stage") == data.get("stage")), None)
    return _as_time(task.get("createdAt")) if task else None


def apply_logs(data: dict[str, Any], found: dict[str, Any]) -> None:
    """Fold SLS log lines into data["submit"]: notes, evidence, and writeback_failed when certain."""
    submit = data.get("submit")
    if not submit:
        return
    if not found.get("ok"):
        submit["logNote"] = f"运行日志未核验：{found.get('message') or '未知原因'}"
        return
    logs = [{**row, "kind": _kind(row["message"])} for row in found.get("logs") or []]
    submit["logs"] = [row for row in logs if row["kind"] != "other"][:EVIDENCE_LIMIT]
    after = _as_time((submit.get("lastSubmit") or {}).get("time"))
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for row in logs:  # 新的在前
        by_kind.setdefault(row["kind"], []).append(row)
    notes: list[str] = []

    fails, oks = by_kind.get("write_failed") or [], by_kind.get("submit_ok") or []
    result = submit["result"]
    if result == "not_submitted":
        if fails and (not oks or fails[0]["time"] > oks[0]["time"]):
            submit["result"] = "writeback_failed"
            submit["message"] = f"运行日志显示 {_fmt(fails[0]['time'])} 回写飞书失败：{fails[0]['message']}"
            submit["next"] = "按报错原因处理后，请审核员在专家端重新提交"
        elif oks:
            notes.append(f"运行日志显示 {_fmt(oks[0]['time'])} 提交已回写飞书成功，只是 task_submit 没记上")
        else:
            notes.append("运行日志里没有这条记录的提交和回写：审核员没提交过，或提交在校验阶段就被拒了（专家端会提示原因）")
    if result == "log_missing" and by_kind.get("review_log_failed"):
        row = by_kind["review_log_failed"][0]
        notes.append(f"运行日志显示 {_fmt(row['time'])} 写审核日志失败（trace_id {row['traceId']}）")
    if result in ("enqueue_not_returned", "action_workflow_half"):
        calls = [r for r in by_kind.get("enqueue") or [] if after is None or r["time"] >= after]
        if calls:
            notes.append(f"提交后入队接口被调用过，最近一次 {_fmt(calls[0]['time'])}：{calls[0]['message']}")
        else:
            notes.append("运行日志里没有提交之后的入队调用：入队工作流没有调用平台")
    skipped = [r for r in by_kind.get("skipped") or [] if after is None or r["time"] >= after]
    if skipped:
        notes.append(f"这次提交有字段没回写飞书：{skipped[0]['message']}")
    if found.get("truncated"):
        notes.append(f"只看了最近 {sls.LINE_LIMIT} 条日志")
    submit["logNote"] = "；".join(notes)


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
    if submit.get("logNote"):
        lines += ["", submit["logNote"]]
    if submit.get("logs"):
        lines += ["", "| 时间 | 运行日志 | trace_id |", "|-|-|-|"]
        for row in submit["logs"]:
            text = row["message"].replace("|", "/")[:160]
            lines.append(f"| {_fmt(row['time'])} | {text} | {row['traceId']} |")
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
