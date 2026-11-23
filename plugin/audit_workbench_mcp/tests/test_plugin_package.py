"""The plugin folder is self-contained and its manifests agree with each other."""

from __future__ import annotations

import json
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
REPO = PLUGIN.parent
SKILLS = {
    "audit-workbench",
    "audit-workbench-onboard",
    "audit-workbench-config",
    "audit-workbench-workflow",
    "audit-workbench-auditors",
    "audit-workbench-ops",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_versions_match() -> None:
    claude = _json(PLUGIN / ".claude-plugin" / "plugin.json")
    codex = _json(PLUGIN / ".codex-plugin" / "plugin.json")
    # tomllib 要 3.11，项目最低 3.10，按行取版本号
    pyproject = (PLUGIN / "audit_workbench_mcp" / "pyproject.toml").read_text(encoding="utf-8")
    project_version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    assert claude["version"] == codex["version"] == project_version
    assert claude["name"] == codex["name"] == "audit-workbench"
    assert f"## {claude['version']}" in (PLUGIN / "CHANGELOG.md").read_text(encoding="utf-8")


def test_skills_are_real_folders() -> None:
    # Codex 安装时不跟随软链，插件里的技能和 MCP 必须是实体文件
    found = {p.name for p in (PLUGIN / "skills").iterdir() if p.is_dir()}
    assert found == SKILLS
    for name in SKILLS:
        folder = PLUGIN / "skills" / name
        assert not folder.is_symlink() and (folder / "SKILL.md").is_file()
    assert not (PLUGIN / "audit_workbench_mcp").is_symlink()


def test_mcp_server_points_inside_the_plugin() -> None:
    server = _json(PLUGIN / ".mcp.json")["mcpServers"]["audit-workbench"]
    directory = server["args"][server["args"].index("--directory") + 1]
    assert directory == "${CLAUDE_PLUGIN_ROOT}/audit_workbench_mcp"
    codex = _json(PLUGIN / ".codex-plugin" / "plugin.json")
    assert codex["mcpServers"] == "./.codex-mcp.json"
    codex_server = _json(PLUGIN / ".codex-mcp.json")["mcpServers"]["audit-workbench"]
    assert codex_server["cwd"] == "." and "./audit_workbench_mcp" in codex_server["args"]


def test_marketplaces_point_at_the_plugin_folder() -> None:
    claude = _json(REPO / ".claude-plugin" / "marketplace.json")["plugins"][0]
    codex = _json(REPO / ".agents" / "plugins" / "marketplace.json")["plugins"][0]
    assert claude["source"] == "./plugin" and codex["source"]["path"] == "./plugin"
    assert claude["name"] == codex["name"] == "audit-workbench"
