"""Compact a reference project's published config for semantic alignment.

The Agent aligns the new base's fields to these compact views by name, so every
field_id here is replaced by the field name. Order of the reference list is the
backend's: most recently published first; the draft builder relies on it for
tie-breaks.
"""

from __future__ import annotations

from typing import Any

AREAS = ("QUESTION_INFO", "EXPERT_INFO", "MACHINE_AUDIT_INFO", "AUDIT_ACTION")

# Round rule keys that bind a role to a field, in display order.
ROLE_KEYS = {
    "status": "statusFieldId",
    "reviewer": "reviewerFieldId",
    "talent_id": "talentIdFieldId",
    "audit_advice": "auditAdviceFieldId",
    "audit_action": "auditActionFieldId",
}


def _rounds(config: dict[str, Any]) -> list[dict[str, Any]]:
    rounds = [r for r in config.get("fieldRounds") or [] if isinstance(r, dict)]
    if rounds:
        return rounds
    # Old configs without fieldRounds: a single round built from fields.
    return [{"id": "round-1", "name": "轮次一", "fields": config.get("fields") or []}]


def _name_index(config: dict[str, Any], round_fields: list[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for pool in (round_fields, config.get("sourceFields") or [], config.get("fields") or []):
        for field in pool:
            if isinstance(field, dict) and field.get("id") and field.get("name"):
                names.setdefault(str(field["id"]), str(field["name"]))
    return names


def _layout_for(config: dict[str, Any], round_id: str, index: int) -> dict[str, Any]:
    for item in config.get("layoutRounds") or []:
        if isinstance(item, dict) and item.get("roundId") == round_id:
            return item.get("layout") or {}
    return (config.get("layout") or {}) if index == 0 else {}


def compact_config(project: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Reference project → {project_id, name, published_at, canvas_ratio, rounds[...]}."""
    rules = {
        str(r.get("roundId")): r
        for r in config.get("auditStatusRules") or []
        if isinstance(r, dict)
    }
    rounds_out = []
    for index, round_item in enumerate(_rounds(config)):
        round_id = str(round_item.get("id") or f"round-{index + 1}")
        fields = [f for f in round_item.get("fields") or [] if isinstance(f, dict)]
        names = _name_index(config, fields)
        rule = rules.get(round_id) or {}
        layout = _layout_for(config, round_id, index)
        rounds_out.append(
            {
                "round": index + 1,
                "fields": [
                    {
                        "name": f.get("name"),
                        "type": f.get("fieldType"),
                        "area": f.get("displayArea"),
                        "permission": f.get("permission"),
                    }
                    for f in fields
                ],
                "roles": {
                    role: names.get(str(rule.get(key) or ""))
                    for role, key in ROLE_KEYS.items()
                    if rule.get(key)
                },
                "status_mapping": {
                    k: v for k, v in (rule.get("statusValueMapping") or {}).items() if v
                },
                "layout": {
                    area: [
                        {
                            "columns": int(block.get("columns") or 1),
                            "slots": [
                                [names.get(str(fid), str(fid)) for fid in slot or []]
                                for slot in block.get("slots") or []
                            ],
                        }
                        for block in layout.get(area) or []
                        if isinstance(block, dict)
                    ]
                    for area in AREAS
                },
            }
        )
    return {
        "project_id": project.get("projectId"),
        "name": project.get("projectName"),
        "published_at": project.get("publishedAt"),
        "canvas_ratio": config.get("canvasRatio"),
        "rounds": rounds_out,
    }
