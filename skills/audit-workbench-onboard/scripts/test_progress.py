"""progress.py 的纯文件测试，用临时目录，不碰工作区。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("progress.py")


def run(tmp: Path, *args: str, env=None):
    import os

    e = dict(os.environ)
    e["AUDIT_WORKBENCH_PROGRESS_DIR"] = str(tmp)
    e.update(env or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=e, check=False
    )


def test_show_empty(tmp_path: Path) -> None:
    r = run(tmp_path, "show")
    assert r.returncode == 0 and json.loads(r.stdout) == {}


def test_update_merges_fields_and_parses_types(tmp_path: Path) -> None:
    r = run(tmp_path, "update", "--stage", "2", "--status", "waiting_views",
            "--env", "boe", "--project-id", "1234",
            "--field", "published_version=1", "--field", 'pending=["round-2"]')
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["stage"] == 2 and data["project_id"] == 1234
    assert data["published_version"] == 1 and data["pending"] == ["round-2"]
    assert "updated_at" in data

    r = run(tmp_path, "update", "--field", "round_count=2")
    data = json.loads(r.stdout)
    assert data["stage"] == 2 and data["round_count"] == 2  # 合并而非覆盖


def test_plain_text_stays_text(tmp_path: Path) -> None:
    r = run(tmp_path, "update", "--field", "reason=等用户提供视图链接")
    assert json.loads(r.stdout)["reason"] == "等用户提供视图链接"


def test_invalid_field_is_rejected(tmp_path: Path) -> None:
    r = run(tmp_path, "update", "--field", "broken")
    assert r.returncode == 2 and "name=value" in r.stderr


def test_no_patch_is_rejected(tmp_path: Path) -> None:
    assert run(tmp_path, "update").returncode == 2
