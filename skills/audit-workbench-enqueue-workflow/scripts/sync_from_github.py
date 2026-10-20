#!/usr/bin/env python3
"""Fetch latest audit-workbench-enqueue-workflow skill from GitHub into a local cache."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_SSH = "git@github.com:wisdom-knowledge/audit_workbench_skills.git"
REPO_HTTPS = "https://github.com/wisdom-knowledge/audit_workbench_skills.git"
REF = "main"
CACHE = Path.home() / ".agents" / "cache" / "audit_workbench_skills"
SKILL_REL = Path("skills") / "audit-workbench-enqueue-workflow"
TIMEOUT = 60


def _run(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


def _emit(*, ok: bool, skill_dir: Path | None, rev: str = "", error: str = "") -> int:
    print(f"ok={'true' if ok else 'false'}")
    if skill_dir is not None:
        print(f"skill_dir={skill_dir}")
    if rev:
        print(f"rev={rev}")
    if error:
        print(f"error={error}", file=sys.stderr)
    return 0 if ok or skill_dir is not None else 1


def _skill_dir() -> Path:
    return CACHE / SKILL_REL


def _rev() -> str:
    git_dir = CACHE / ".git"
    if not git_dir.exists():
        return ""
    proc = _run(["git", "rev-parse", "--short", "HEAD"], cwd=CACHE)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _cached() -> Path | None:
    path = _skill_dir()
    if (path / "SKILL.md").is_file():
        return path
    return None


def _clone(url: str) -> subprocess.CompletedProcess[str]:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if CACHE.exists():
        import shutil

        shutil.rmtree(CACHE)
    return _run(["git", "clone", "--depth", "1", "--branch", REF, url, str(CACHE)])


def _update() -> subprocess.CompletedProcess[str]:
    fetch = _run(["git", "fetch", "--depth", "1", "origin", REF], cwd=CACHE)
    if fetch.returncode != 0:
        return fetch
    return _run(["git", "reset", "--hard", f"origin/{REF}"], cwd=CACHE)


def main() -> int:
    cached = _cached()
    try:
        if (CACHE / ".git").is_dir():
            proc = _update()
            if proc.returncode != 0:
                proc = _clone(REPO_SSH)
                if proc.returncode != 0:
                    proc = _clone(REPO_HTTPS)
        else:
            proc = _clone(REPO_SSH)
            if proc.returncode != 0:
                proc = _clone(REPO_HTTPS)
    except subprocess.TimeoutExpired:
        return _emit(ok=False, skill_dir=cached, rev=_rev(), error="git timed out")
    except OSError as exc:
        return _emit(ok=False, skill_dir=cached, rev=_rev(), error=str(exc))

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "git failed").strip().splitlines()
        return _emit(
            ok=False,
            skill_dir=_cached(),
            rev=_rev(),
            error=err[-1] if err else "git failed",
        )

    skill_dir = _cached()
    if skill_dir is None:
        return _emit(ok=False, skill_dir=None, error=f"missing {SKILL_REL}/SKILL.md")
    return _emit(ok=True, skill_dir=skill_dir, rev=_rev())


if __name__ == "__main__":
    raise SystemExit(main())
