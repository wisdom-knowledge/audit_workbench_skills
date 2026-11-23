#!/usr/bin/env python3
"""Install the audit-workbench entry skill and its sub-skills by symlink.

Each skill folder in this repo gets a canonical link under ~/.agents/skills, so
edits here take effect immediately; other agent skill dirs link to that
canonical link. Sub-skills reference each other by relative path, so they must
be installed together. No remote fetch, no bootstrap stub.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

SKILL_NAMES = (
    "audit-workbench",
    "audit-workbench-onboard",
    "audit-workbench-config",
    "audit-workbench-workflow",
    "audit-workbench-auditors",
    "audit-workbench-ops",
)

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


def link_skill(name: str, source: Path, home: Path, roots: list[Path], dry_run: bool) -> None:
    canonical = home / ".agents" / "skills" / name
    if dry_run:
        print(f"would link {canonical} -> {source}")
    else:
        canonical.parent.mkdir(parents=True, exist_ok=True)
        if not _same_dir(source, canonical):
            _clear(canonical)
            canonical.symlink_to(source, target_is_directory=True)
        print(f"linked {canonical} -> {source}")

    for root in roots:
        if root == canonical.parent:
            continue
        link = root / name
        if link.is_symlink() and _same_dir(link, canonical):
            print(f"ok {link}")
            continue
        if dry_run:
            print(f"would link {link} -> {canonical}")
            continue
        _clear(link)
        link.symlink_to(canonical, target_is_directory=True)
        print(f"linked {link} -> {canonical}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    skills_root = Path(args.skills_root).expanduser().resolve()
    sources = {name: skills_root / name for name in SKILL_NAMES}
    missing = [name for name, path in sources.items() if not (path / "SKILL.md").is_file()]
    if missing:
        print(f"missing skill folders under {skills_root}: {', '.join(missing)}", file=sys.stderr)
        return 2

    home = Path.home()
    roots = discover_skill_dirs(home)
    for name, source in sources.items():
        link_skill(name, source, home, roots, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
