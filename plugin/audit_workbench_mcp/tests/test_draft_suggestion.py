"""Draft suggestion: reference compaction, field groups, voting rules, layout, report."""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any

import httpx
import pytest

from audit_workbench_mcp import draft_builder as db
from audit_workbench_mcp import errors, field_groups, references, report
from audit_workbench_mcp.auth import TokenStore
from audit_workbench_mcp.client import AdminClient
from audit_workbench_mcp.service import AuditWorkbenchService


def ref_field(fid: str, name: str, area: str, perm: str = "READONLY", ftype: str = "TEXT") -> dict:
    return {"id": fid, "name": name, "fieldType": ftype, "displayArea": area, "permission": perm, "options": []}


def ref_config(fields: list[dict], layout: dict, *, roles: dict | None = None,
               mapping: dict | None = None, ratio: str = "LEFT_2_RIGHT_1") -> dict:
    rule = {"roundId": "round-1", "statusValueMapping": mapping or {}}
    rule.update(roles or {})
    return {
        "fieldRounds": [{"id": "round-1", "name": "轮次一", "fields": fields}],
        "sourceFields": fields,
        "auditStatusRules": [rule],
        "layoutRounds": [{"roundId": "round-1", "layout": layout}],
        "canvasRatio": ratio,
    }


def compact(pid: int, fields: list[dict], layout: dict, **kw: Any) -> dict:
    return references.compact_config(
        {"projectId": pid, "projectName": f"P{pid}", "publishedAt": "2026-09-01"},
        ref_config(fields, layout, **kw),
    )


# Three references, most recent first.
REF_A = compact(
    1201,
    [ref_field("a1", "题目ID", "QUESTION_INFO"), ref_field("a2", "解答过程", "QUESTION_INFO"),
     ref_field("a3", "标签", "EXPERT_INFO"), ref_field("a4", "审核状态", "AUDIT_ACTION", "EDITABLE", "SINGLE_SELECT")],
    {"QUESTION_INFO": [{"id": "b", "columns": 2, "slots": [["a1"], ["a2"]]}],
     "AUDIT_ACTION": [{"id": "c", "columns": 1, "slots": [["a4"]]}]},
    roles={"statusFieldId": "a4", "talentIdFieldId": "a9"},
    mapping={"打回": "待返修"},
)
REF_B = compact(
    1188,
    [ref_field("b1", "题目ID", "QUESTION_INFO"), ref_field("b2", "解答过程", "QUESTION_INFO"),
     ref_field("b3", "标签", "QUESTION_INFO"), ref_field("b4", "审核状态", "AUDIT_ACTION", "EDITABLE", "SINGLE_SELECT")],
    {"QUESTION_INFO": [{"id": "d", "columns": 1, "slots": [["b1"]]}]},
    mapping={"打回": "待返修"},
)
REF_C = compact(
    1150,
    [ref_field("c1", "题目ID", "QUESTION_INFO", "EDITABLE"), ref_field("c4", "审核状态", "AUDIT_ACTION", "EDITABLE", "SINGLE_SELECT")],
    {},
    ratio="LEFT_1_RIGHT_1",
)
REFS = [REF_A, REF_B, REF_C]

BASE = [
    {"id": "n1", "name": "题目ID", "fieldType": "TEXT", "options": [], "displayArea": "QUESTION_INFO", "permission": "READONLY"},
    {"id": "n2", "name": "解题过程", "fieldType": "TEXT", "options": [], "displayArea": "QUESTION_INFO", "permission": "READONLY"},
    {"id": "n3", "name": "专家标签", "fieldType": "TEXT", "options": [], "displayArea": "QUESTION_INFO",
     "permission": "READONLY", "degraded": True},
    {"id": "n4", "name": "审核状态", "fieldType": "SINGLE_SELECT", "options": ["待审核", "打回", "搁置"],
     "displayArea": "AUDIT_ACTION", "permission": "READONLY"},
    {"id": "n5", "name": "一审人员ID", "fieldType": "TEXT", "options": [], "displayArea": "QUESTION_INFO", "permission": "READONLY"},
]

ALIGNMENT = {"rounds": [{
    "round": 1,
    "fields": [
        {"field_id": "n1", "matches": {"1201": "题目ID", "1188": "题目ID", "1150": "题目ID"}},
        {"field_id": "n2", "matches": {"1201": "解答过程", "1188": "解答过程", "1150": None}},
        {"field_id": "n3", "matches": {"1201": "标签", "1188": "标签"}},
        {"field_id": "n4", "matches": {"1201": "审核状态", "1188": "审核状态", "1150": "审核状态"}},
        {"field_id": "n5", "matches": {"1201": "不存在的字段"}},
    ],
    "roles": {
        "status": {"field_id": "n4", "basis": "exact"},
        "talent_id": {"field_id": "n5", "basis": "semantic", "reason": "参考项目叫「一轮审核员talent_id」"},
    },
    "status_mapping": {"待审核": {"target": "待审核", "basis": "exact"}},
}]}


def build(alignment: dict | None = None, refs: list | None = None) -> dict:
    return db.build_draft(
        base_fields=BASE, alignment=alignment or ALIGNMENT, references=REFS if refs is None else refs,
        workbench_type=1, feishu_table_url="https://x.feishu.cn/base/app?table=tbl",
    )


# ---- references.compact_config ------------------------------------------------


def test_compact_replaces_ids_with_names() -> None:
    r = REF_A["rounds"][0]
    assert REF_A["project_id"] == 1201
    assert [f["name"] for f in r["fields"]] == ["题目ID", "解答过程", "标签", "审核状态"]
    assert r["roles"]["status"] == "审核状态"
    assert r["layout"]["QUESTION_INFO"] == [{"columns": 2, "slots": [["题目ID"], ["解答过程"]]}]
    assert r["layout"]["EXPERT_INFO"] == []
    assert r["status_mapping"] == {"打回": "待返修"}


def test_compact_old_config_without_field_rounds() -> None:
    out = references.compact_config(
        {"projectId": 1}, {"fields": [ref_field("x", "题目", "QUESTION_INFO")],
                           "layout": {"QUESTION_INFO": [{"columns": 1, "slots": [["x"]]}]}}
    )
    assert out["rounds"][0]["fields"][0]["name"] == "题目"
    assert out["rounds"][0]["layout"]["QUESTION_INFO"][0]["slots"] == [["题目"]]


# ---- field_groups ---------------------------------------------------------------


def _proc(code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=out, stderr=err)


def test_field_groups_parsed() -> None:
    payload = {"code": 0, "data": {"groups": [
        {"id": "g1", "name": "一轮审核", "type": "group",
         "children": [{"id": "fld1", "type": "field"}, {"id": "fld2", "type": "field"}]},
    ]}}
    calls = []
    out = field_groups.fetch_field_groups("app", "tbl", runner=lambda a: calls.append(a) or _proc(0, json.dumps(payload)))
    assert out == {"ok": True, "reason": None, "groups": [{"name": "一轮审核", "field_ids": ["fld1", "fld2"]}]}
    assert calls[0][:3] == ["lark-cli", "api", "GET"] and "--as" in calls[0] and "user" in calls[0]
    assert "/bases/app/tables/tbl/field_groups" in calls[0][3]


@pytest.mark.parametrize(
    ("proc", "reason"),
    [
        (_proc(1, err="permission denied"), "lark_cli_failed"),
        (_proc(0, "not json"), "invalid_json"),
        (_proc(0, json.dumps({"code": 91402, "msg": "no access"})), "feishu_error"),
        (_proc(0, json.dumps({"code": 0, "data": {"groups": []}})), "no_groups"),
    ],
)
def test_field_groups_failures_are_returned(proc, reason: str) -> None:
    out = field_groups.fetch_field_groups("app", "tbl", runner=lambda _a: proc)
    assert out["reason"] == reason and out["groups"] == []


# ---- draft_builder: voting ------------------------------------------------------


def test_field_majority_and_exclusions() -> None:
    r = build()["report"]["rounds"][0]
    ids = [item["field"]["id"] for item in r["fields"]]
    # n5's only match is not a real field of that reference, so it has no votes.
    assert ids == ["n1", "n2", "n3", "n4"]
    by_id = {item["field"]["id"]: item for item in r["fields"]}
    assert by_id["n2"]["count"] == 2 and by_id["n2"]["total"] == 3


def test_area_and_permission_majority_with_tie_break() -> None:
    by_id = {i["field"]["id"]: i for i in build()["report"]["rounds"][0]["fields"]}
    assert by_id["n1"]["field"]["permission"] == "READONLY"  # 2 READONLY vs 1 EDITABLE
    assert by_id["n4"]["field"]["displayArea"] == "AUDIT_ACTION"
    assert by_id["n4"]["field"]["permission"] == "EDITABLE"
    # 1 EXPERT_INFO vs 1 QUESTION_INFO: tie goes to the most recent reference (1201)
    assert by_id["n3"]["field"]["displayArea"] == "EXPERT_INFO" and by_id["n3"]["area_tied"]
    # degraded fields stay read-only
    assert by_id["n3"]["field"]["permission"] == "READONLY"


def test_minority_field_becomes_optional() -> None:
    alignment = json.loads(json.dumps(ALIGNMENT))
    alignment["rounds"][0]["fields"][1]["matches"] = {"1201": "解答过程"}
    r = build(alignment)["report"]["rounds"][0]
    assert "n2" not in [i["field"]["id"] for i in r["fields"]]
    assert r["optional"] == [{"field_id": "n2", "name": "解题过程", "count": 1, "total": 3}]


def test_roles_confidence_and_required_roles() -> None:
    roles = build()["report"]["rounds"][0]["roles"]
    assert roles["status"]["confidence"] == db.HIGH
    assert roles["talent_id"]["confidence"] == db.LOW
    assert set(roles) == {"status", "talent_id"}

    alignment = json.loads(json.dumps(ALIGNMENT))
    alignment["rounds"][0]["roles"] = {"status": {"field_id": "ghost", "basis": "exact"}}
    roles = build(alignment)["report"]["rounds"][0]["roles"]
    assert roles["status"]["confidence"] == db.UNRESOLVED
    assert "不在本项目底表" in roles["status"]["reason"]
    assert roles["talent_id"]["confidence"] == db.UNRESOLVED  # required for template one


def test_status_mapping_falls_back_to_reference_votes() -> None:
    mapping = build()["report"]["rounds"][0]["status_mapping"]
    assert mapping["待审核"] == {"target": "待审核", "confidence": db.HIGH, "reason": ""}
    assert mapping["打回"]["target"] == "待返修" and mapping["打回"]["confidence"] == db.HIGH
    assert mapping["搁置"]["confidence"] == db.UNRESOLVED


def test_invalid_platform_status_is_unresolved() -> None:
    alignment = json.loads(json.dumps(ALIGNMENT))
    alignment["rounds"][0]["status_mapping"]["搁置"] = {"target": "暂停", "basis": "semantic"}
    assert build(alignment)["report"]["rounds"][0]["status_mapping"]["搁置"]["confidence"] == db.UNRESOLVED


def test_unknown_field_id_and_no_references_are_rejected() -> None:
    alignment = json.loads(json.dumps(ALIGNMENT))
    alignment["rounds"][0]["fields"].append({"field_id": "fake", "matches": {}})
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        build(alignment)
    assert exc.value.detail == {"field_ids": ["fake"]}
    with pytest.raises(errors.AuditWorkbenchError) as exc:
        build(refs=[])
    assert exc.value.code == errors.NOT_FOUND


# ---- draft_builder: layout and config shape --------------------------------------


def _slots(layout: dict, area: str) -> list:
    return [b["slots"] for b in layout[area]]


def test_layout_maps_best_reference_and_appends_the_rest() -> None:
    built = build()
    layout = built["config"]["layoutRounds"][0]["layout"]
    assert _slots(layout, "QUESTION_INFO") == [[["n1"], ["n2"]]]  # from 1201, 2 columns
    assert _slots(layout, "AUDIT_ACTION") == [[["n4"]]]
    assert _slots(layout, "EXPERT_INFO") == [[["n3"]]]  # not placed by 1201, appended
    assert _slots(layout, "MACHINE_AUDIT_INFO") == [[[]]]  # empty area keeps one block
    info = built["report"]["rounds"][0]["layout"]
    assert info == {"source_project_id": "1201", "appended_field_ids": ["n3"]}


def test_draft_passes_publish_layout_rules() -> None:
    """Mirror of the backend layout rules: every field placed once, in its own area."""
    config = build()["config"]
    area_of = {f["id"]: f["displayArea"] for f in config["fields"]}
    placed: list[str] = []
    for area, blocks in config["layout"].items():
        assert blocks, f"{area} needs a block"
        for block in blocks:
            assert block["columns"] in (1, 2, 3) and len(block["slots"]) == block["columns"]
            for slot in block["slots"]:
                for fid in slot:
                    assert area_of[fid] == area
                    placed.append(fid)
    assert sorted(placed) == sorted(area_of)


def test_config_shape_matches_admin_draft() -> None:
    config = build()["config"]
    assert config["fields"] == config["fieldRounds"][0]["fields"]
    assert config["layout"] == config["layoutRounds"][0]["layout"]
    assert config["fieldRounds"][0]["id"] == "round-1" and config["fieldRounds"][0]["name"] == "轮次一"
    assert "sourceFields" not in config  # 全量字段池后端不存，草稿里不带
    assert config["canvasRatio"] == "LEFT_2_RIGHT_1"
    rule = config["auditStatusRules"][0]
    assert rule["statusFieldId"] == "n4" and rule["talentIdFieldId"] == "n5"
    # every option of the status field is a key, unresolved ones as ""
    assert rule["statusValueMapping"] == {"待审核": "待审核", "打回": "待返修", "搁置": ""}
    assert rule["enqueueViewUrl"] == ""


def test_round_beyond_references_uses_their_last_round() -> None:
    alignment = json.loads(json.dumps(ALIGNMENT))
    second = json.loads(json.dumps(alignment["rounds"][0]))
    second["round"] = 2
    alignment["rounds"].append(second)
    config = build(alignment)["config"]
    assert [r["name"] for r in config["fieldRounds"]] == ["轮次一", "轮次二"]
    assert [f["id"] for f in config["fieldRounds"][1]["fields"]] == ["n1", "n2", "n3", "n4"]


# ---- report ------------------------------------------------------------------------


def _render(saved: bool = True) -> str:
    return report.render_report(
        report=build()["report"], env="boe", project_id=1234,
        page_url="https://admin-test.meetchances.com/projects/1234/audit-workbench?step=1", saved=saved,
    )


def test_report_part_one_sorted_by_area_with_markers() -> None:
    text = _render()
    assert "**推荐配置已保存为草稿**" in text
    assert "轮次一（4 个字段：🟦 2　🟩 1　🟧 1　｜　⚪ 3　🔵 1）" in text
    rows = [line for line in text.splitlines() if line.startswith("| ") and "|-" not in line and "| 字段 |" not in line]
    assert rows[0].startswith("| 题目ID |")
    assert text.index("| 解题过程 |") < text.index("| 专家标签 |") < text.index("| 审核状态 |")
    assert "| 审核状态 | 🟧 审核操作 | 🔵 可编辑 |" in text


def _mappings(data: dict | None = None) -> str:
    return report.render_mappings(report=data or build()["report"], page_url="https://admin/p/1234")


def test_field_step_asks_only_about_fields() -> None:
    text = _render()
    assert "**2.1 确认展示的字段**" in text and "展示的字段有需要调整的吗？" in text
    assert "需要确认的字段映射" not in text and "入队" not in text.split("**2.1")[1]


def test_mapping_step_splits_field_and_status_tables() -> None:
    text = _mappings()
    assert text.startswith("**2.2 确认字段映射和状态枚举映射**")
    assert "🟢 置信度最高，可以不关注" in text
    assert text.index("字段映射\n") < text.index("状态枚举映射\n")
    assert "| 🔴 搁置 | — | 请从 7 个平台状态中选一个 |" in text
    assert "| 🟡 talent_id | 一审人员ID | 参考项目叫「一轮审核员talent_id」 |" in text
    assert "| 🟢 审核状态 | 审核状态 |" in text and "| 🟢 待审核 | 待审核 |" in text
    assert "低置信" not in text and "状态「" not in text and "审核状态字段" not in text
    assert "🔴 的项请给出选择" in text and "（⭐️更快捷）" in text


def _info(name: str, confidence: str, reason: str = "") -> dict[str, str]:
    return {"name": name, "target": name, "confidence": confidence, "reason": reason}


def _two_round_report() -> dict:
    def rnd(i: int, name: str, roles: dict, mapping: dict) -> dict:
        return {"round_id": f"round-{i}", "name": name, "fields": [], "roles": roles, "status_mapping": mapping}
    return {
        "workbench_type": 1, "base_field_count": 9, "references": [{"project_id": 1}],
        "rounds": [
            rnd(1, "轮次一",
                {"talent_id": _info("一审ID", "low", "按语义推断"), "status": _info("初审状态", "high")},
                {"搁置": _info("", "unresolved")}),
            rnd(2, "轮次二",
                {"reviewer": _info("", "unresolved", "参考项目里没有对应字段")},
                {"复核中": _info("其他", "low", "")}),
        ],
    }


def test_mapping_step_splits_rounds_and_orders_red_yellow_green() -> None:
    text = _mappings(_two_round_report())
    one, two = text.split("**轮次二**")
    assert "**轮次一**" in one and "轮次二" not in one
    fields_one = one.split("字段映射\n")[1].split("状态枚举映射\n")[0]
    assert fields_one.index("| 🟡 talent_id | 一审ID | 按语义推断 |") < fields_one.index("| 🟢 审核状态 | 初审状态 | 名称一致 |")
    assert "| 🔴 搁置 | — | 请从 7 个平台状态中选一个 |" in one.split("状态枚举映射\n")[-1]
    assert "| 🔴 审核人 | — | 参考项目里没有对应字段 |" in two
    assert "| 🟡 复核中 | 其他 | 按语义推断 |" in two


def test_mapping_step_round_without_items_says_so() -> None:
    data = _two_round_report()
    data["rounds"][1]["roles"], data["rounds"][1]["status_mapping"] = {}, {}
    text = _mappings(data)
    assert "**轮次二**\n\n本轮没有映射项。" in text
    assert "**轮次二**\n\n字段映射" not in text


def test_mapping_step_with_nothing_to_confirm() -> None:
    data = _two_round_report()
    for r in data["rounds"]:
        r["roles"], r["status_mapping"] = {}, {}
    text = _mappings(data)
    assert report.has_mappings_to_confirm(data) is False
    assert "没有需要单独确认的项" in text and "请给出选择" not in text


URL = "https://admin-test.meetchances.com/projects/1234/audit-workbench?step=1"


def _ends_with_link(text: str, url: str) -> None:
    """Every confirmation step ends with: question line, blank, then the link callout."""
    lines = text.splitlines()
    assert lines[-1] == f"> **{url}**" and lines[-4] == "" and lines[-3].startswith("> 👉 **管理端配置页")
    assert "可以直接在配置页" in lines[-5] and "我帮你" in lines[-5]
    assert text.count(url) == 1


def test_every_step_puts_the_config_link_last() -> None:
    _ends_with_link(_render(), URL)
    _ends_with_link(_mappings(_two_round_report()), "https://admin/p/1234")
    views = report.render_views_prompt(report=_two_round_report(), page_url="https://admin/p/1234?step=2")
    _ends_with_link(views, "https://admin/p/1234?step=2")


def test_unsaved_preview_link_says_draft_not_saved() -> None:
    preview = _render(saved=False)
    assert "尚未保存" in preview.splitlines()[0]
    assert "> 👉 **管理端配置页（草稿尚未保存" in preview
    _ends_with_link(preview, URL)


def test_views_step_lists_every_round() -> None:
    text = report.render_views_prompt(report=_two_round_report(), page_url="u")
    assert text.startswith("**2.3 给出每一轮的入队条件**")
    assert "- 轮次一：\n- 轮次二：" in text


# ---- service: save rules -------------------------------------------------------------

PARSE = {"app_token": "app", "table_id": "tbl", "view_id": None, "fields": BASE}
LIST = {"items": [{"projectId": 1201, "projectName": "P1201", "publishedAt": "2026-09-12"}]}


def make_service(editor_draft: dict | None):
    calls: list[httpx.Request] = []
    ref_editor = {"published": {"config": ref_config(
        [ref_field("a1", "题目ID", "QUESTION_INFO"), ref_field("a4", "审核状态", "AUDIT_ACTION", "EDITABLE", "SINGLE_SELECT")],
        {"QUESTION_INFO": [{"id": "b", "columns": 1, "slots": [["a1"]]}]})}}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        ok = lambda d: httpx.Response(200, json={"status_code": 0, "status_msg": "success", "data": d})
        if path.endswith("/parse-feishu"):
            return ok(PARSE)
        if path.endswith("/recent-published"):
            return ok(LIST)
        if path.endswith("/projects/1201/audit-workbench/editor"):
            return ok(ref_editor)
        if path.endswith("/projects/1234/audit-workbench/editor"):
            return ok({"draft": editor_draft, "published": None})
        if path.endswith("/parse-view-filter"):
            return ok({"view_name": "待审", "summary_text": "审核状态 等于 待审核"})
        if path.endswith("/projects/1234/audit-workbench/draft"):
            return ok({"updated_at": "2026-09-20T10:00:00", "wizard_step": 1, "questionTags": []})
        raise AssertionError(path)

    store = TokenStore(sources=(lambda _e: "tok",), capture=lambda *a, **k: "tok")
    client = AdminClient(store, transport=httpx.MockTransport(handler), retry_delay=0)
    return AuditWorkbenchService(client), calls


SIMPLE_ALIGNMENT = {"rounds": [{"round": 1,
    "fields": [{"field_id": "n1", "matches": {"1201": "题目ID"}}, {"field_id": "n4", "matches": {"1201": "审核状态"}}],
    "roles": {"status": {"field_id": "n4", "basis": "exact"}, "talent_id": {"field_id": "n5", "basis": "exact"}}}]}


def _suggest(service, **kw):
    return asyncio.run(service.suggest_draft("boe", 1234, "https://x.feishu.cn/base/app?table=tbl", 1, SIMPLE_ALIGNMENT, **kw))


def test_no_draft_saves_directly() -> None:
    service, calls = make_service(None)
    out = _suggest(service)
    assert out["executed"] is True and "已保存为草稿" in out["report_markdown"]
    put = next(c for c in calls if c.method == "PUT")
    body = json.loads(put.content)
    assert body["base_updated_at"] is None and body["feishu_app_token"] == "app"
    assert body["config"]["fieldRounds"][0]["fields"][0]["id"] == "n1"
    parse = json.loads(next(c for c in calls if c.url.path.endswith("/parse-feishu")).content)
    assert parse == {"table_url": "https://x.feishu.cn/base/app?table=tbl", "project_id": 1234}
    assert out["page_url"] == "https://admin-test.meetchances.com/projects/1234/audit-workbench?step=1"
    # 2.2、2.3 的文本随结果一起返回，由技能在用户确认上一步后再展示
    assert out["mapping_markdown"].startswith("**2.2 ") and isinstance(out["mappings_to_confirm"], bool)
    assert out["views_markdown"].startswith("**2.3 ") and "需要确认的字段映射" not in out["report_markdown"]
    assert out["views_markdown"].endswith("audit-workbench?step=2**")
    # 映射在配置页第 2 步「审核规则配置」
    assert out["mapping_markdown"].endswith("audit-workbench?step=2**") or not out["mappings_to_confirm"]
    if out["mappings_to_confirm"]:
        assert "配置页第 2 步" in out["mapping_markdown"]


def test_existing_draft_previews_then_overwrites_on_confirm() -> None:
    draft = {"config": {}, "updated_at": "2026-09-19T08:00:00", "wizard_step": 2}
    service, calls = make_service(draft)
    out = _suggest(service)
    assert out["preview"] is True and "尚未保存" in out["report_markdown"]
    assert not any(c.method == "PUT" for c in calls)

    service, calls = make_service(draft)
    out = _suggest(service, confirm=True)
    body = json.loads(next(c for c in calls if c.method == "PUT").content)
    assert body["base_updated_at"] == "2026-09-19T08:00:00"
    assert out["executed"] is True


def test_set_enqueue_views_parses_and_saves() -> None:
    draft = {"config": {"auditStatusRules": [{"roundId": "round-1", "enqueueViewUrl": ""},
                                             {"roundId": "round-2", "enqueueViewUrl": ""}],
                        "fieldRounds": [{"id": "round-1", "name": "轮次一"}, {"id": "round-2", "name": "轮次二"}]},
             "updated_at": "2026-09-19T08:00:00", "wizard_step": 1}
    service, calls = make_service(draft)
    out = asyncio.run(service.set_enqueue_views("boe", 1234, {"round-1": "https://x/view"}))
    body = json.loads(next(c for c in calls if c.method == "PUT").content)
    assert body["config"]["auditStatusRules"][0]["enqueueViewUrl"] == "https://x/view"
    assert out["views"]["round-1"]["summary"] == "审核状态 等于 待审核"
    assert out["missing_views"] == ["round-2"]
    text = out["views_markdown"]
    assert "| 轮次一 |" in text and "审核状态 等于 待审核" in text and "还差这几轮的入队视图：轮次二" in text
    _ends_with_link(text, "https://admin-test.meetchances.com/projects/1234/audit-workbench?step=2")
    with pytest.raises(errors.AuditWorkbenchError):
        asyncio.run(service.set_enqueue_views("boe", 1234, {"round-9": "u"}))
