"""Contract checks for the audit-workbench entry skill and its sub-skills.

Run from the MCP project so pytest is available:
  cd audit_workbench_mcp && uv run pytest ../skills/audit-workbench/scripts/test_skills.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
REPO = SKILLS.parent
SERVER = REPO / "audit_workbench_mcp" / "src" / "audit_workbench_mcp" / "server.py"
NAMES = (
    "audit-workbench",
    "audit-workbench-onboard",
    "audit-workbench-config",
    "audit-workbench-workflow",
    "audit-workbench-auditors",
)
LINK = re.compile(r"\]\(([^)#\s]+\.md)\)")
CODE = re.compile(r"`([a-z][a-z_]+)(?:\(|`)")


def _docs():
    for name in NAMES:
        yield from sorted((SKILLS / name).rglob("*.md"))


def _tools() -> set[str]:
    return set(re.findall(r"^async def (\w+)\(", SERVER.read_text(encoding="utf-8"), re.M))


def test_every_skill_has_frontmatter_name():
    for name in NAMES:
        head = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
        assert f"name: {name}" in head


def test_relative_links_resolve():
    broken = []
    for doc in _docs():
        for target in LINK.findall(doc.read_text(encoding="utf-8")):
            if not (doc.parent / target).resolve().is_file():
                broken.append(f"{doc.relative_to(SKILLS)} -> {target}")
    assert not broken, broken


def test_tool_names_exist_in_mcp():
    tools = _tools()
    # Backticked snake_case words are tool names unless listed here as params or result keys.
    fields = {
        "draft_updated_at", "published_version", "runtime_status", "app_token", "table_id",
        "base_updated_at", "base_version", "confirm_project_id", "view_urls", "talent_ids",
        "talent_name", "display_status", "force_update", "timed_out", "ready_to_publish",
        "report_markdown", "checklist_markdown", "workflows_markdown", "binding_markdown",
        "page_url", "pending_count", "needs_reassign", "feishu_table_url", "status_mapping",
        "talent_id", "audit_advice", "audit_action", "workbench_type", "published_at",
        "field_id", "project_id", "missing_views", "draft_after_publish",
    }
    unknown = set()
    for doc in _docs():
        for word in CODE.findall(doc.read_text(encoding="utf-8")):
            if "_" in word and word not in fields and word not in tools:
                unknown.add(f"{doc.relative_to(SKILLS)}: {word}")
    assert not unknown, sorted(unknown)


def test_no_local_progress_file():
    for doc in _docs():
        assert "progress.json" not in doc.read_text(encoding="utf-8"), doc


def test_sub_skills_load_shared_rules():
    for name in NAMES[1:]:
        text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
        assert "../audit-workbench/references/rules.md" in text, name
