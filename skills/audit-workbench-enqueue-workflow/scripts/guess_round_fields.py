#!/usr/bin/env python3
"""Guess per-round 审核状态 / 审核员talent_id fields from lark-cli +field-list JSON."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

EXCLUDE_NAME = ("盲审", "更新时间", "建议", "评价", "回传")
EXCLUDE_TYPE = {"button", "lookup", "formula", "created_at", "updated_at"}
PASS_NAMES = ("审核通过", "审核员修改后通过")
REVIEWER_MARKERS = ("审核员talent_id", "审核人talent_id")

CN_NUM = {
    1: ("一", "1", "首"),
    2: ("二", "2"),
    3: ("三", "3"),
    4: ("四", "4"),
    5: ("五", "5"),
    6: ("六", "6"),
    7: ("七", "7"),
    8: ("八", "8"),
    9: ("九", "9"),
    10: ("十", "10"),
}


def _fields_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("items", "fields", "list"):
        items = data.get(key)
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    inner = data.get("data")
    if isinstance(inner, dict):
        items = inner.get("items") or inner.get("fields")
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    return []


def _norm_field(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = str(raw.get("name") or raw.get("field_name") or "").strip()
    field_id = str(raw.get("id") or raw.get("field_id") or "").strip()
    ftype = raw.get("type")
    if isinstance(ftype, dict):
        ftype = ftype.get("name") or ftype.get("type")
    ftype = str(ftype or "").strip().lower()
    if not name or not field_id:
        return None
    options = []
    for opt in raw.get("options") or raw.get("property", {}).get("options") or []:
        if not isinstance(opt, dict):
            continue
        oname = str(opt.get("name") or "").strip()
        oid = str(opt.get("id") or opt.get("option_id") or "").strip()
        if oname:
            item = {"name": oname}
            if oid:
                item["id"] = oid
            options.append(item)
    return {"name": name, "id": field_id, "type": ftype, "options": options}


def _excluded(field: dict[str, Any]) -> bool:
    name = field["name"]
    if any(token in name for token in EXCLUDE_NAME):
        return True
    if field["type"] == "lookup" and any(marker in name for marker in REVIEWER_MARKERS):
        return False
    return field["type"] in EXCLUDE_TYPE


def _round_tokens(stage: int) -> tuple[str, ...]:
    return CN_NUM.get(stage, (str(stage),))


def _has_other_round_token(name: str, stage: int) -> bool:
    for other, tokens in CN_NUM.items():
        if other == stage:
            continue
        for token in tokens:
            if token in ("1",) and stage != 1:
                continue
            patterns = (
                f"{token}轮",
                f"第{token}轮",
                f"第{other}轮",
            )
            if any(p in name for p in patterns):
                return True
            if token in ("二", "三", "四", "五", "六", "七", "八", "九", "十") and name.startswith(f"{token}轮"):
                return True
    return False


def _score_status(field: dict[str, Any], stage: int) -> int:
    if "审核状态" not in field["name"]:
        return -1
    if field["type"] and field["type"] != "select":
        return -1
    name = field["name"]
    if _has_other_round_token(name, stage):
        return -1
    score = 10
    if field["type"] == "select":
        score += 5
    if stage == 1 and name == "审核状态":
        score += 20
    tokens = _round_tokens(stage)
    if stage >= 2:
        if any(f"{t}轮审核状态" in name or f"第{t}轮审核状态" in name for t in tokens):
            score += 20
        elif any(t in name for t in tokens):
            score += 8
        else:
            return -1
    elif name != "审核状态":
        if any(f"{t}轮审核状态" in name or "首轮审核状态" in name for t in tokens):
            score += 8
        else:
            score -= 5
    return score


def _score_reviewer(field: dict[str, Any], stage: int) -> int:
    name = field["name"]
    if not any(marker in name for marker in REVIEWER_MARKERS):
        return -1
    if _has_other_round_token(name, stage):
        return -1
    score = 10
    if "审核员talent_id" in name:
        score += 5
    if stage == 1 and name in REVIEWER_MARKERS:
        score += 20
    tokens = _round_tokens(stage)
    if stage >= 2:
        if any(
            f"{t}轮审核员talent_id" in name
            or f"{t}轮审核人talent_id" in name
            or f"第{t}轮审核员talent_id" in name
            or f"第{t}轮审核人talent_id" in name
            for t in tokens
        ):
            score += 20
        elif any(t in name for t in tokens):
            score += 8
        else:
            return -1
    elif name not in REVIEWER_MARKERS:
        if any(f"{t}轮审核员talent_id" in name or "首轮审核员talent_id" in name for t in tokens):
            score += 8
        else:
            score -= 5
    return score


def _rank(fields: list[dict[str, Any]], stage: int, scorer) -> list[dict[str, Any]]:
    ranked = []
    for field in fields:
        score = scorer(field, stage)
        if score < 0:
            continue
        ranked.append({**field, "score": score})
    ranked.sort(key=lambda x: (-x["score"], x["name"]))
    return ranked


def _pass_options(field: dict[str, Any] | None) -> list[dict[str, str]]:
    if not field:
        return []
    found = []
    for opt in field.get("options") or []:
        if opt["name"] in PASS_NAMES:
            found.append(dict(opt))
    return found


def guess(fields: list[dict[str, Any]], rounds: int) -> dict[str, Any]:
    usable = [f for f in fields if not _excluded(f)]
    rounds_out = []
    for stage in range(1, rounds + 1):
        status_ranked = _rank(usable, stage, _score_status)
        reviewer_ranked = _rank(usable, stage, _score_reviewer)
        status = status_ranked[0] if status_ranked else None
        reviewer = reviewer_ranked[0] if reviewer_ranked else None
        rounds_out.append(
            {
                "review_stage": stage,
                "status": None
                if not status
                else {
                    "name": status["name"],
                    "id": status["id"],
                    "type": status["type"],
                },
                "reviewer": None
                if not reviewer
                else {
                    "name": reviewer["name"],
                    "id": reviewer["id"],
                    "type": reviewer["type"],
                },
                "pass_options": _pass_options(status),
                "status_alternatives": [
                    {"name": x["name"], "id": x["id"]} for x in status_ranked[1:4]
                ],
                "reviewer_alternatives": [
                    {"name": x["name"], "id": x["id"]} for x in reviewer_ranked[1:4]
                ],
            }
        )
    return {"rounds": rounds_out}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, required=True)
    args = parser.parse_args()
    if args.rounds < 1:
        print("rounds must be >= 1", file=sys.stderr)
        return 2
    payload = json.load(sys.stdin)
    fields = [_norm_field(x) for x in _fields_from_payload(payload)]
    fields = [x for x in fields if x]
    json.dump(guess(fields, args.rounds), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
