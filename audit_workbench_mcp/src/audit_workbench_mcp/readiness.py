"""Derived views over backend data: workflow display status and the readiness checklist.

These are pure functions so the rules live in one place and are easy to test.
"""

from __future__ import annotations

from typing import Any

# Workflow display status, derived from the sync table row.
PENDING = "pending"  # queued, worker has not picked it up
RUNNING = "running"  # worker is writing it to Feishu
RETRYING = "retrying"  # failed at least once, will be retried automatically
SYNCED = "synced"
FAILED = "failed"  # reached the retry limit; needs retry_workflows

_TERMINAL = {SYNCED, FAILED}

# Readiness item levels.
BLOCKER = "blocker"  # publish will fail
WARNING = "warning"  # publish succeeds but something will not work as expected
UNVERIFIED = "unverified"  # could not be checked here; never counts as passed


def workflow_display_status(item: dict[str, Any]) -> str:
    status = item.get("status")
    if status == "DONE":
        return SYNCED
    if status == "FAILED":
        return FAILED
    if status == "RUNNING":
        return RUNNING
    if status == "PENDING" and item.get("lastError"):
        return RETRYING
    return PENDING


def summarize_workflows(data: dict[str, Any]) -> dict[str, Any]:
    """Annotate each row with display_status and add an overall verdict.

    settled: every row is synced or failed, so waiting longer changes nothing.
    needs_attention: a row failed or is retrying with an error, the published config
    cannot produce workflows, or fewer rows exist than the config expects.
    """
    items = []
    counts: dict[str, int] = {}
    for raw in data.get("items") or []:
        item = dict(raw)
        item["display_status"] = workflow_display_status(raw)
        counts[item["display_status"]] = counts.get(item["display_status"], 0) + 1
        items.append(item)

    published = int(data.get("publishedVersion") or 0)
    expected = int(data.get("expectedCount") or 0)
    plan_error = data.get("planError")
    problems: list[str] = []
    if published == 0:
        problems.append("项目还没有发布，没有工作流记录。")
    if plan_error:
        problems.append(f"已发布配置渲染不出工作流，发布时没有排队：{plan_error}")
    if published and not plan_error and len(items) < expected:
        problems.append(
            f"按已发布配置应有 {expected} 条工作流，只查到 {len(items)} 条记录，"
            "缺的那些没有排上队，可用 retry_workflows 重新排队。"
        )
    for item in items:
        if item["display_status"] in (FAILED, RETRYING):
            label = f"{item.get('stageLabel', '')}{item.get('kindLabel', '')}"
            state = "已到重试上限" if item["display_status"] == FAILED else "失败后等待自动重试"
            problems.append(f"{label}工作流{state}：{item.get('lastError') or '无错误信息'}")

    settled = bool(items) and all(i["display_status"] in _TERMINAL for i in items)
    return {
        **{k: v for k, v in data.items() if k != "items"},
        "items": items,
        "counts": counts,
        "settled": settled,
        "needs_attention": bool(problems),
        "problems": problems,
    }


def stop_waiting(summary: dict[str, Any]) -> bool:
    """Waiting is over once every row settled, or something already needs a human.

    A retrying row already shows its error; the cause rarely changes between
    retries, so surfacing it now beats waiting for all attempts to run out.
    """
    if summary["settled"]:
        return True
    if not summary["items"]:
        # Nothing queued yet; keep waiting only if the config can produce workflows.
        return bool(summary["problems"])
    return any(i["display_status"] in (FAILED, RETRYING) for i in summary["items"])


def _field_options(config: dict[str, Any], round_id: str, field_id: str) -> list[str] | None:
    """Options of a field, looked up in the round's fields first, then the shared pools."""
    pools: list[list[dict[str, Any]]] = []
    for round_item in config.get("fieldRounds") or []:
        if isinstance(round_item, dict) and round_item.get("id") == round_id:
            pools.append(round_item.get("fields") or [])
    pools.append(config.get("fields") or [])
    pools.append(config.get("sourceFields") or [])
    for pool in pools:
        for field in pool:
            if isinstance(field, dict) and field.get("id") == field_id:
                return list(field.get("options") or [])
    return None


def mapping_items(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Status options of each round that have no platform status mapped."""
    items = []
    for rule in config.get("auditStatusRules") or []:
        if not isinstance(rule, dict):
            continue
        round_id = str(rule.get("roundId") or "")
        status_id = str(rule.get("statusFieldId") or "")
        if not status_id:
            continue  # the backend validation reports missing role fields
        options = _field_options(config, round_id, status_id)
        if options is None:
            continue
        mapping = rule.get("statusValueMapping") or {}
        unmapped = [o for o in options if o not in mapping]
        if unmapped:
            items.append(
                {
                    "code": "status_value_unmapped",
                    "level": WARNING,
                    "round": round_id,
                    "message": f"{round_id} 审核状态有 {len(unmapped)} 个选项没有映射到平台状态："
                    + "、".join(unmapped),
                    "fix_hint": "在配置第二步为这些选项选择对应的平台审核状态。",
                }
            )
    return items


def validation_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for err in result.get("errors") or []:
        items.append(
            {
                "code": err.get("rule"),
                "level": BLOCKER,
                "step": err.get("step"),
                "field_key": err.get("field_key"),
                "message": err.get("message"),
                "fix_hint": "发布会因此失败，按提示修改配置后再检查。",
            }
        )
    for err in result.get("workflowErrors") or []:
        items.append(
            {
                "code": err.get("rule"),
                "level": WARNING,
                "step": err.get("step"),
                "message": err.get("message"),
                "fix_hint": "发布能成功，但飞书工作流建不出来，审核员会收不到任务。",
            }
        )
    return items


def auditor_items(auditor_list: dict[str, Any]) -> list[dict[str, Any]]:
    count = int((auditor_list.get("summary") or {}).get("auditor_count") or auditor_list.get("count") or 0)
    if count == 0:
        return [
            {
                "code": "no_auditors",
                "level": BLOCKER,
                "message": "项目还没有审核员。",
                "fix_hint": "用 add_auditors 添加审核员 talent_id。",
            }
        ]
    return []


APP_PERMISSION_ITEM = {
    "code": "app_collaborator_unverified",
    "level": UNVERIFIED,
    "message": "人才招聘应用是否为底表管理协作者，后端接口查不到。",
    "fix_hint": "由 Skill 用 lark-cli 以用户身份查看底表协作者确认；"
    "缺失时在底表的协作者设置里，把「人才招聘」应用添加为可管理协作者。",
}
