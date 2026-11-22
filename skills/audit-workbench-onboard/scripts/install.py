#!/usr/bin/env python3
"""Install this skill by symlinking the full folder into each agent's skills dir.

No remote fetch, no bootstrap stub: the folder under ~/.agents/skills is a
symlink to this repo, so edits here take effect immediately. Other agent skill
dirs get a symlink to that canonical link.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

SKILL_NAME = "audit-workbench-onboard"

WELL_KNOWN = (
    Path(".agents") / "skills",
    Path(".codex") / "skills",
    Path(".claude") / "skills",
    Path(".cursor") / "skills",
    Path(".gemini") / "skills",
    Path(".grok") / "skills",
    Path(".opencode") / "skills",
    Path(".trae-cn") / "builtin" / "global" / "skills",
)


def _same_dir(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _clear(dest: Path) -> None:
    if not dest.exists() and not dest.is_symlink():
        return
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    else:
        shutil.rmtree(dest)


def discover_skill_dirs(home: Path) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    candidates = [home / ".agents" / "skills"] + [home / rel for rel in WELL_KNOWN]
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        candidates.append(Path(codex_home) / "skills")
    for path in candidates:
        if path.exists() and not path.is_dir():
            continue
        if not path.exists():
            if not path.parent.is_dir():
                continue
            path.mkdir(parents=True, exist_ok=True)
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen or path.name != "skills":
            continue
        if any(t in str(path) for t in ("/plugins/", "/marketplace", "/cache/")):
            continue
        seen.add(resolved)
        found.append(path)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not (source / "SKILL.md").is_file():
        print(f"not a skill folder: {source}", file=sys.stderr)
        return 2

    home = Path.home()
    canonical = home / ".agents" / "skills" / SKILL_NAME
    if args.dry_run:
        print(f"would link {canonical} -> {source}")
    else:
        canonical.parent.mkdir(parents=True, exist_ok=True)
        if not _same_dir(source, canonical):
            _clear(canonical)
            canonical.symlink_to(source, target_is_directory=True)
        print(f"linked {canonical} -> {source}")

    for root in discover_skill_dirs(home):
        link = root / SKILL_NAME
        if root == canonical.parent:
            continue
        if link.is_symlink() and _same_dir(link, canonical):
            print(f"ok {link}")
            continue
        if args.dry_run:
            print(f"would link {link} -> {canonical}")
            continue
        _clear(link)
        link.symlink_to(canonical, target_is_directory=True)
        print(f"linked {link} -> {canonical}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
