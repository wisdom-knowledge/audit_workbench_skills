"""Decide which onboarding stage a project is at, from online state only.

Publishing deletes the draft, so "draft exists" means not yet published, or
changed again after a publish. Checks run in stage order; the first unmet one
decides the stage.
"""

from __future__ import annotations

from typing import Any

from . import readiness

STAGE_NAMES = {
    1: "识别与初始化",
    2: "推荐配置",
    3: "发布前确认",
    4: "工作流交接",
    5: "审核员",
    6: "全链路校验与交付",
}


def missing_views(config: dict[str, Any]) -> list[str]:
    """Round IDs whose enqueue view link is still empty."""
    return [
        r.get("roundId") or f"round-{i + 1}"
        for i, r in enumerate(config.get("auditStatusRules") or [])
        if not (r.get("enqueueViewUrl") or "").strip()
    ]


def _workflow_gaps(summary: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    by_status = {
        "unsynced": [r["label"] for r in rows if r["sync"] != readiness.SYNCED],
        "not_repaired": [r["label"] for r in rows if r["sync"] == readiness.SYNCED and r["repaired"] is False],
        "not_enabled": [r["label"] for r in rows if r["sync"] == readiness.SYNCED and r["enabled"] is False],
        "unverified": [r["label"] for r in rows if r["sync"] == readiness.SYNCED and r["enabled"] is None],
    }
    by_status["problems"] = list(summary.get("problems") or [])
    return by_status


def judge(
    editor: dict[str, Any],
    workflows: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    auditor_count: int,
    binding_items: list[dict[str, Any]],
) -> dict[str, Any]:
    draft = editor.get("draft") or None
    published = editor.get("published") or None
    published_version = int((published or {}).get("version") or 0)
    out: dict[str, Any] = {
        "published_version": published_version,
        "draft_exists": draft is not None,
        "draft_updated_at": (draft or {}).get("updated_at"),
        "draft_after_publish": draft is not None and published_version > 0,
    }

    def done(stage: int, reason: str, **extra: Any) -> dict[str, Any]:
        return {**out, **extra, "stage": stage, "stage_name": STAGE_NAMES[stage], "reason": reason}

    if draft is None and published_version == 0:
        return done(1, "还没有草稿，也没有发布过。")

    if draft is not None:
        missing = missing_views(draft.get("config") or {})
        if missing:
            return done(2, f"草稿已保存，{len(missing)} 轮还没有入队视图。", missing_views=missing)
        reason = "草稿已保存，各轮入队视图都已填写，还没有发布。"
        if published_version:
            reason = f"已发布 v{published_version}，之后又保存了新草稿，还没有发布。"
        return done(3, reason, missing_views=[])

    gaps = _workflow_gaps(workflows or {}, rows)
    if gaps["problems"] or gaps["unsynced"]:
        return done(4, f"已发布 v{published_version}，有工作流没有同步完成或需要处理。", workflows=gaps)
    if gaps["not_repaired"] or gaps["not_enabled"] or gaps["unverified"]:
        return done(4, f"已发布 v{published_version}，工作流已同步，还有没启用的。", workflows=gaps)

    if auditor_count == 0:
        return done(5, "工作流都已启用，还没有添加审核员。", workflows=gaps, auditor_count=0)

    unbound = [i["talentId"] for i in binding_items if i.get("state") == "UNBOUND"]
    unverified = [i["talentId"] for i in binding_items if i.get("state") == "UNVERIFIED"]
    binding = {"unbound": unbound, "unverified": unverified}
    if unbound or unverified:
        return done(
            5, f"已有 {auditor_count} 位审核员，绑定检查有未完成的。",
            workflows=gaps, auditor_count=auditor_count, binding=binding,
        )
    return done(
        6, f"已有 {auditor_count} 位审核员，都已绑定飞书账号。",
        workflows=gaps, auditor_count=auditor_count, binding=binding,
    )
