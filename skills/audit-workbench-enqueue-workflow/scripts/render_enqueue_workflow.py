#!/usr/bin/env python3
"""Render one Feishu Base enqueue workflow JSON from a confirmed binding."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


ENQUEUE_RESPONSE = (
    '{"status_code": 0, "status_msg": "success", "data": {"result": "updated", '
    '"reason": null, "task_id": 1, "project_id": 24, "review_stage": 1, '
    '"review_status": "PENDING_AUDIT", "event_id": null}}'
)

TRIGGER_CONTROLS = [
    "pasteUpdate",
    "automationBatchUpdate",
    "openAPIBatchUpdate",
]


def _text(value: str) -> dict[str, str]:
    return {"value_type": "text", "value": value}


def _ref(path: str) -> dict[str, str]:
    return {"value_type": "ref", "value": path}


def _http_step(
    step_id: str,
    title: str,
    *,
    enqueue_url: str,
    api_key: str,
    app_token: str,
    table_id: str,
    review_stage: int,
    status_name: str,
    reviewer_name: str,
    next_id: str | None,
) -> dict[str, Any]:
    prefix = (
        f'{{"app_token":"{app_token}","table_id":"{table_id}",'
        f'"review_stage":{review_stage},"record_id":"'
    )
    suffix = f'","changed_fields":["{status_name}", "{reviewer_name}"]}}'
    step: dict[str, Any] = {
        "id": step_id,
        "type": "HTTPClientAction",
        "title": title,
        "next": next_id,
        "data": {
            "method": "POST",
            "url": [_text(enqueue_url)],
            "headers": [
                {"key": "Content-Type", "value": [_text("application/json")]},
                {"key": "X-API-Key", "value": [_text(api_key)]},
            ],
            "body_type": "raw",
            "raw_body": [_text(prefix), _ref("$.trig.recordId"), _text(suffix)],
            "response_type": "json",
            "response_value": ENQUEUE_RESPONSE,
        },
    }
    return step


def render(binding: dict[str, Any]) -> dict[str, Any]:
    stage = int(binding["review_stage"])
    table_name = binding["table_name"]
    status_name = binding["status_field_name"]
    status_id = binding["status_field_id"]
    reviewer_name = binding["reviewer_field_name"]
    chain_next = bool(binding.get("chain_next"))
    title = f"审核工作台题目入队·第{stage}轮"

    trig_next = "http"
    steps: list[dict[str, Any]] = [
        {
            "id": "trig",
            "type": "SetRecordTrigger",
            "title": f"修改时：仅监听第{stage}轮状态/审核员talent_id",
            "next": trig_next,
            "data": {
                "table_name": table_name,
                "field_watch_info": [
                    {"field_name": status_name},
                    {"field_name": reviewer_name},
                ],
                "trigger_control_list": list(TRIGGER_CONTROLS),
            },
        }
    ]

    if chain_next:
        next_stage = stage + 1
        next_status = binding["next_status_field_name"]
        next_reviewer = binding["next_reviewer_field_name"]
        pass_options = binding.get("pass_options") or []
        if len(pass_options) < 1:
            raise ValueError("chain_next requires pass_options")
        http_next = _http_step(
            "http_next",
            f"enqueue review_stage={next_stage}",
            enqueue_url=binding["enqueue_url"],
            api_key=binding["api_key"],
            app_token=binding["app_token"],
            table_id=binding["table_id"],
            review_stage=next_stage,
            status_name=next_status,
            reviewer_name=next_reviewer,
            next_id=None,
        )
        branch = {
            "id": "branch",
            "type": "IfElseBranch",
            "title": "条件判断（If/Else）",
            "children": {
                "links": [
                    {"kind": "if_true", "to": "http_next"},
                    {"kind": "if_false", "to": ""},
                ]
            },
            "data": {
                "condition": {
                    "conjunction": "or",
                    "conditions": [
                        {
                            "conjunction": "and",
                            "conditions": [
                                {
                                    "left_value": {
                                        "extra_info": {"table_name": table_name},
                                        "value": f"$.trig.{status_id}",
                                        "value_type": "ref",
                                    },
                                    "operator": "containsAny",
                                    "right_value": [
                                        {
                                            "value_type": "option",
                                            "value": (
                                                {"id": opt["id"], "name": opt["name"]}
                                                if opt.get("id")
                                                else {"name": opt["name"]}
                                            ),
                                        }
                                        for opt in pass_options
                                    ],
                                }
                            ],
                        }
                    ],
                }
            },
        }
        http = _http_step(
            "http",
            f"enqueue review_stage={stage}",
            enqueue_url=binding["enqueue_url"],
            api_key=binding["api_key"],
            app_token=binding["app_token"],
            table_id=binding["table_id"],
            review_stage=stage,
            status_name=status_name,
            reviewer_name=reviewer_name,
            next_id="branch",
        )
        steps.extend([http, branch, http_next])
    else:
        http = _http_step(
            "http",
            f"enqueue review_stage={stage}",
            enqueue_url=binding["enqueue_url"],
            api_key=binding["api_key"],
            app_token=binding["app_token"],
            table_id=binding["table_id"],
            review_stage=stage,
            status_name=status_name,
            reviewer_name=reviewer_name,
            next_id=None,
        )
        steps.append(http)

    client_token = binding.get("client_token") or f"enqueue-stage-{stage}"
    return {
        "client_token": client_token,
        "title": title,
        "steps": steps,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True, help="path to binding JSON, or - for stdin")
    args = parser.parse_args()
    if args.binding == "-":
        binding = json.load(sys.stdin)
    else:
        with open(args.binding, encoding="utf-8") as handle:
            binding = json.load(handle)
    json.dump(render(binding), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
