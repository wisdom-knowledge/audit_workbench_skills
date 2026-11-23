"""Assemble a draft config from the Agent's alignment table. All rules live here.

The Agent only judges correspondence (which new field matches which reference
field, which field plays which role, which platform status an option means).
This module counts votes, derives confidence, maps the layout and produces a
config in the exact shape the admin page saves, so the draft echoes back.

Alignment input (one entry per round the Agent decided the base has). In round N,
"matches" name fields of each reference's round N, or of its last round when the
reference has fewer rounds:

    {"rounds": [{
        "round": 1,
        "fields": [{"field_id": "fldA", "matches": {"1201": "题目ID", "1150": null}}],
        "roles": {"status": {"field_id": "fldS", "basis": "exact", "reason": "..."}},
        "status_mapping": {"待审核": {"target": "待审核", "basis": "exact", "reason": "..."}}
    }]}

basis: "exact" = same name / text as the references or a platform status;
"semantic" = inferred by meaning; "none" = could not decide.
"""

from __future__ import annotations

import uuid
from typing import Any

from . import errors
from .references import AREAS, ROLE_KEYS

PLATFORM_STATUSES = ("待审核", "审核通过", "审核拒绝", "已返修待审核", "待返修", "其他", "做题中")
PERMISSIONS = ("READONLY", "EDITABLE")
CANVAS_RATIOS = ("LEFT_2_RIGHT_1", "LEFT_1_RIGHT_1")
ROUND_NAMES = "一二三四五六七八九十"

HIGH = "high"
LOW = "low"
UNRESOLVED = "unresolved"

# Roles that must be bound for workflows and submission to work, per template.
REQUIRED_ROLES = {1: ("status", "talent_id"), 2: ("status", "talent_id", "reviewer", "audit_action")}


def round_name(index: int) -> str:
    return f"轮次{ROUND_NAMES[index]}" if index < len(ROUND_NAMES) else f"轮次{index + 1}"


def _confidence(basis: str | None, has_value: bool) -> str:
    if not has_value or basis in (None, "", "none"):
        return UNRESOLVED
    return HIGH if basis == "exact" else LOW


def _majority(values_in_ref_order: list[str]) -> tuple[str | None, bool]:
    """Most common value; ties go to the most recent reference. Returns (value, tied)."""
    if not values_in_ref_order:
        return None, False
    counts: dict[str, int] = {}
    for v in values_in_ref_order:
        counts[v] = counts.get(v, 0) + 1
    top = max(counts.values())
    leaders = {v for v, c in counts.items() if c == top}
    winner = next(v for v in values_in_ref_order if v in leaders)
    return winner, len(leaders) > 1


def _ref_round(ref: dict[str, Any], round_no: int) -> dict[str, Any] | None:
    """Reference round N; a reference with fewer rounds is compared by its last round."""
    rounds = ref.get("rounds") or []
    for r in rounds:
        if r.get("round") == round_no:
            return r
    return rounds[-1] if rounds else None


def _vote_fields(
    round_no: int,
    entries: list[dict[str, Any]],
    base_by_id: dict[str, dict[str, Any]],
    refs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Return (included fields, optional candidates, {field_id: {ref_id: ref_name}}).

    A field is included when it matches in more than half of the references that
    have this round. Area / permission take the majority of the matched fields.
    """
    ref_rounds = [(str(ref["project_id"]), _ref_round(ref, round_no)) for ref in refs]
    ref_rounds = [(pid, r) for pid, r in ref_rounds if r is not None]
    n = len(ref_rounds)
    by_name = {pid: {f["name"]: f for f in r["fields"] if f.get("name")} for pid, r in ref_rounds}

    included, optional, matches_out = [], [], {}
    seen: set[str] = set()
    for entry in entries:
        field_id = str(entry.get("field_id") or "")
        if field_id in seen:
            continue
        seen.add(field_id)
        base = base_by_id[field_id]
        # Keep only matches that name a real field of that reference round.
        matched = {
            pid: by_name[pid][name]
            for pid, name in (entry.get("matches") or {}).items()
            if pid in by_name and name and name in by_name[pid]
        }
        matches_out[field_id] = {pid: f["name"] for pid, f in matched.items()}
        count = len(matched)
        ordered = [matched[pid] for pid, _ in ref_rounds if pid in matched]
        if count == 0:
            continue
        if count * 2 <= n:
            optional.append({"field_id": field_id, "name": base["name"], "count": count, "total": n})
            continue
        area, area_tied = _majority([f["area"] for f in ordered if f.get("area") in AREAS])
        perm, perm_tied = _majority([f["permission"] for f in ordered if f.get("permission") in PERMISSIONS])
        field = dict(base)
        field["displayArea"] = area or base.get("displayArea") or "QUESTION_INFO"
        field["permission"] = "READONLY" if base.get("degraded") else (perm or "READONLY")
        included.append(
            {
                "field": field,
                "count": count,
                "total": n,
                "area_tied": area_tied,
                "permission_tied": perm_tied,
            }
        )
    return included, optional, matches_out


def _resolve_roles(
    round_no: int,
    roles_in: dict[str, Any],
    base_by_id: dict[str, dict[str, Any]],
    refs: list[dict[str, Any]],
    workbench_type: int,
) -> dict[str, dict[str, Any]]:
    """{role: {field_id, name, confidence, reason}} for every role worth reporting.

    A role is reported when it is required for this template, the Agent bound it,
    or most references bind it.
    """
    ref_rounds = [r for r in (_ref_round(ref, round_no) for ref in refs) if r]
    out: dict[str, dict[str, Any]] = {}
    for role in ROLE_KEYS:
        if role == "audit_action" and workbench_type != 2:
            continue
        raw = roles_in.get(role) or {}
        field_id = str(raw.get("field_id") or "")
        valid = field_id in base_by_id
        bound_by_refs = sum(1 for r in ref_rounds if r["roles"].get(role))
        relevant = (
            role in REQUIRED_ROLES.get(workbench_type, ())
            or valid
            or (ref_rounds and bound_by_refs * 2 > len(ref_rounds))
        )
        if not relevant:
            continue
        reason = str(raw.get("reason") or "")
        if field_id and not valid:
            reason = f"字段 {field_id} 不在本项目底表中"
        out[role] = {
            "field_id": field_id if valid else "",
            "name": base_by_id[field_id]["name"] if valid else "",
            "confidence": _confidence(raw.get("basis"), valid),
            "reason": reason,
        }
    return out


def _resolve_status_mapping(
    round_no: int,
    options: list[str],
    mapping_in: dict[str, Any],
    refs: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """{option: {target, confidence, reason}} for every option of the status field.

    Options the Agent left out fall back to what the references map the same text to.
    """
    ref_maps = [r["status_mapping"] for r in (_ref_round(ref, round_no) for ref in refs) if r]
    out: dict[str, dict[str, Any]] = {}
    for option in options:
        raw = mapping_in.get(option) or {}
        target = str(raw.get("target") or "")
        if target and target not in PLATFORM_STATUSES:
            out[option] = {"target": "", "confidence": UNRESOLVED, "reason": f"「{target}」不是平台状态"}
            continue
        if not target:
            votes = [m[option] for m in ref_maps if m.get(option) in PLATFORM_STATUSES]
            winner, tied = _majority(votes)
            if winner:
                out[option] = {
                    "target": winner,
                    "confidence": LOW if tied else HIGH,
                    "reason": f"参考项目中 {votes.count(winner)}/{len(ref_maps)} 映射为「{winner}」"
                    + ("（票数打平）" if tied else ""),
                }
                continue
        out[option] = {
            "target": target,
            "confidence": _confidence(raw.get("basis"), bool(target)),
            "reason": str(raw.get("reason") or ""),
        }
    return out


def _block(columns: int, slots: list[list[str]]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "columns": columns, "slots": slots}


def _build_layout(
    round_no: int,
    fields: list[dict[str, Any]],
    matches: dict[str, dict[str, str]],
    refs: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Map the best-covering reference layout onto the new field ids.

    The source is the reference whose layout places the most included fields
    (ties: most recent). Fields it does not place, or places in a different area
    than chosen, are appended as one-column blocks. Every area keeps at least one
    block, which publish validation requires.
    """
    area_of = {f["id"]: f["displayArea"] for f in fields}
    best: tuple[int, str | None, dict[str, Any]] = (-1, None, {})
    for ref in refs:
        r = _ref_round(ref, round_no)
        if not r:
            continue
        pid = str(ref["project_id"])
        name_to_id = {name: fid for fid, m in matches.items() if fid in area_of for p, name in m.items() if p == pid}
        placed = {
            name_to_id[name]
            for blocks in r["layout"].values()
            for block in blocks
            for slot in block["slots"]
            for name in slot
            if name in name_to_id
        }
        if len(placed) > best[0]:
            best = (len(placed), pid, {"layout": r["layout"], "name_to_id": name_to_id})

    layout: dict[str, list[dict[str, Any]]] = {area: [] for area in AREAS}
    placed_ids: set[str] = set()
    source = best[2]
    for area in AREAS:
        for block in (source.get("layout") or {}).get(area) or []:
            columns = int(block.get("columns") or 1)
            slots: list[list[str]] = []
            for slot in block.get("slots") or []:
                ids = []
                for name in slot:
                    fid = source["name_to_id"].get(name)
                    if fid and area_of.get(fid) == area and fid not in placed_ids:
                        ids.append(fid)
                        placed_ids.add(fid)
                slots.append(ids)
            slots = (slots + [[] for _ in range(columns)])[:columns]
            if any(slots):
                layout[area].append(_block(columns, slots))

    appended = [f["id"] for f in fields if f["id"] not in placed_ids]
    for fid in appended:
        layout[area_of[fid]].append(_block(1, [[fid]]))
    for area in AREAS:
        if not layout[area]:
            layout[area].append(_block(1, [[]]))
    return layout, {"source_project_id": best[1], "appended_field_ids": appended}


def build_draft(
    *,
    base_fields: list[dict[str, Any]],
    alignment: dict[str, Any],
    references: list[dict[str, Any]],
    workbench_type: int,
    feishu_table_url: str,
) -> dict[str, Any]:
    """Return {"config": <edit config>, "report": <data for the report>}."""
    if not references:
        raise errors.AuditWorkbenchError(
            errors.NOT_FOUND, "没有可参考的同模版已发布项目，无法推荐配置"
        )
    rounds_in = sorted(alignment.get("rounds") or [], key=lambda r: int(r.get("round") or 0))
    if not rounds_in:
        raise errors.AuditWorkbenchError(errors.VALIDATION_FAILED, "对齐表里没有轮次")
    base_by_id = {str(f["id"]): f for f in base_fields}

    unknown = sorted(
        {
            str(e.get("field_id"))
            for r in rounds_in
            for e in r.get("fields") or []
            if str(e.get("field_id")) not in base_by_id
        }
    )
    if unknown:
        raise errors.AuditWorkbenchError(
            errors.VALIDATION_FAILED,
            "对齐表里有不在本项目底表中的字段",
            detail={"field_ids": unknown},
        )

    field_rounds, layout_rounds, rules, report_rounds = [], [], [], []
    for index, round_in in enumerate(rounds_in):
        round_no = index + 1
        round_id = f"round-{round_no}"
        included, optional, matches = _vote_fields(round_no, round_in.get("fields") or [], base_by_id, references)
        fields = [item["field"] for item in included]
        roles = _resolve_roles(round_no, round_in.get("roles") or {}, base_by_id, references, workbench_type)
        status_id = roles.get("status", {}).get("field_id", "")
        options = [str(o).strip() for o in (base_by_id.get(status_id, {}).get("options") or []) if str(o).strip()]
        mapping = _resolve_status_mapping(round_no, options, round_in.get("status_mapping") or {}, references)
        layout, layout_info = _build_layout(round_no, fields, matches, references)

        field_rounds.append({"id": round_id, "name": round_name(index), "fields": fields})
        layout_rounds.append({"roundId": round_id, "layout": layout})
        rule = {"roundId": round_id, "statusValueMapping": {o: m["target"] for o, m in mapping.items()}, "enqueueViewUrl": ""}
        for role, key in ROLE_KEYS.items():
            rule[key] = roles.get(role, {}).get("field_id", "")
        rules.append(rule)
        report_rounds.append(
            {
                "round_id": round_id,
                "name": round_name(index),
                "fields": included,
                "optional": optional,
                "roles": roles,
                "status_mapping": mapping,
                "layout": layout_info,
            }
        )

    ratio, ratio_tied = _majority([r["canvas_ratio"] for r in references if r.get("canvas_ratio") in CANVAS_RATIOS])
    config = {
        "feishuTableUrl": feishu_table_url,
        "fields": field_rounds[0]["fields"],
        "fieldRounds": field_rounds,
        "sourceFields": base_fields,
        "auditStatusRules": rules,
        "questionTags": [],
        "layout": layout_rounds[0]["layout"],
        "layoutRounds": layout_rounds,
        "canvasRatio": ratio or "LEFT_2_RIGHT_1",
        "workbenchType": workbench_type,
    }
    report = {
        "workbench_type": workbench_type,
        "references": [
            {"project_id": r["project_id"], "name": r.get("name"), "published_at": r.get("published_at")}
            for r in references
        ],
        "base_field_count": len(base_fields),
        "canvas_ratio": {"value": config["canvasRatio"], "tied": ratio_tied},
        "rounds": report_rounds,
    }
    return {"config": config, "report": report}
