#!/usr/bin/env python3
"""Install the fetch-on-use stub into ~/.agents/skills and symlink other agent skill dirs."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

SKILL_NAME = "audit-workbench-enqueue-workflow"

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


def _home() -> Path:
    return Path.home()


def canonical_dir() -> Path:
    return _home() / ".agents" / "skills" / SKILL_NAME


def _is_skills_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if path.name != "skills":
        return False
    text = str(path)
    skip = ("/plugins/", "/marketplace", "/node_modules/", "/extensions/", "/cache/")
    return not any(token in text for token in skip)


def discover_skill_dirs(home: Path) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path, *, mkdir: bool) -> None:
        path = path.expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            return
        if path.exists() and not path.is_dir():
            return
        if mkdir and not path.exists() and path.parent.is_dir():
            path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            return
        seen.add(resolved)
        found.append(path)

    add(home / ".agents" / "skills", mkdir=True)
    for rel in WELL_KNOWN:
        add(home / rel, mkdir=True)
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        add(Path(codex_home) / "skills", mkdir=True)

    for dot in home.glob(".*"):
        if not dot.is_dir() or dot.name in {".", ".."}:
            continue
        candidate = dot / "skills"
        if _is_skills_dir(candidate):
            add(candidate, mkdir=False)

    return found


def _same_dir(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _link_ok(link: Path, target: Path) -> bool:
    return link.is_symlink() and _same_dir(link, target)


def _clear(dest: Path) -> None:
    if not dest.exists() and not dest.is_symlink():
        return
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    else:
        shutil.rmtree(dest)


def install_stub(source: Path, dest: Path, *, dry_run: bool) -> str:
    bootstrap = source / "bootstrap" / "SKILL.md"
    sync = source / "scripts" / "sync_from_github.py"
    yaml = source / "agents" / "openai.yaml"
    if not bootstrap.is_file():
        return f"missing {bootstrap}"
    if not sync.is_file():
        return f"missing {sync}"
    if dry_run:
        return f"would install stub -> {dest}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    _clear(dest)
    dest.mkdir(parents=True)
    (dest / "scripts").mkdir()
    (dest / "agents").mkdir()
    shutil.copy2(bootstrap, dest / "SKILL.md")
    shutil.copy2(sync, dest / "scripts" / "sync_from_github.py")
    if yaml.is_file():
        shutil.copy2(yaml, dest / "agents" / "openai.yaml")
    return f"installed stub {dest}"


def install_local(source: Path, dest: Path, *, dry_run: bool) -> str:
    source = source.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and _same_dir(source, dest):
        return f"canonical already at {dest}"
    if dry_run:
        return f"would link {dest} -> {source}"
    _clear(dest)
    dest.symlink_to(source, target_is_directory=True)
    return f"linked {dest} -> {source}"


def link_into(skill_root: Path, canonical: Path, *, dry_run: bool) -> str:
    if _same_dir(skill_root, canonical.parent):
        return f"skip {skill_root} (canonical parent)"
    link = skill_root / SKILL_NAME
    if _link_ok(link, canonical):
        return f"ok {link}"
    if dry_run:
        return f"would link {link} -> {canonical}"
    if link.is_symlink() or link.is_file():
        link.unlink()
    elif link.is_dir():
        shutil.rmtree(link)
    link.symlink_to(canonical, target_is_directory=True)
    return f"linked {link} -> {canonical}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install fetch-on-use stub into ~/.agents/skills and symlink other agent skill dirs"
    )
    parser.add_argument(
        "--source",
        default=str(Path(__file__).resolve().parents[1]),
        help="full skill folder (contains bootstrap/ and scripts/)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="symlink ~/.agents/skills/<name> to this folder instead of installing the stub",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not (source / "SKILL.md").is_file():
        print(f"not a skill folder: {source}", file=sys.stderr)
        return 2
    if not args.local and not (source / "bootstrap" / "SKILL.md").is_file():
        print(f"missing bootstrap: {source / 'bootstrap' / 'SKILL.md'}", file=sys.stderr)
        return 2

    canonical = canonical_dir()
    if args.local:
        print(install_local(source, canonical, dry_run=args.dry_run))
    else:
        print(install_stub(source, canonical, dry_run=args.dry_run))

    for skill_root in discover_skill_dirs(_home()):
        print(link_into(skill_root, canonical, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
