"""Admin token lookup, tried in this order:

1. ~/.agents/secrets/audit-workbench-admin.env  (BOE_ADMIN_TOKEN / PROD_ADMIN_TOKEN)
2. environment variable AUDIT_WORKBENCH_BOE_ADMIN_TOKEN / AUDIT_WORKBENCH_PROD_ADMIN_TOKEN
3. the dedicated Chrome profile, read headless without a window

The visible login window is never opened implicitly; only the ``login`` tool
opens it. Tokens live in this process's memory and are sent as
``Authorization: Bearer``. They never appear in tool results or logs.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

from . import browser_login
from .envs import Env

SECRETS_FILE = Path.home() / ".agents" / "secrets" / "audit-workbench-admin.env"


def _from_secrets_file(env: Env, path: Path = SECRETS_FILE) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == env.secrets_key and value.strip():
            return value.strip().strip("'\"")
    return None


def _from_environ(env: Env) -> str | None:
    value = os.environ.get(f"AUDIT_WORKBENCH_{env.secrets_key}", "").strip()
    return value or None


def _from_browser_profile(env: Env) -> str | None:
    return browser_login.read_saved_token(env.cookie_name)


DEFAULT_SOURCES: tuple[Callable[[Env], str | None], ...] = (
    _from_secrets_file,
    _from_environ,
    _from_browser_profile,
)


class TokenStore:
    """Per-env token cache. Rejected tokens are remembered so they are not reused."""

    def __init__(
        self,
        sources: tuple[Callable[[Env], str | None], ...] = DEFAULT_SOURCES,
        capture: Callable[..., str] = browser_login.capture_token,
    ) -> None:
        self._sources = sources
        self._capture = capture
        self._cached: dict[str, str] = {}
        self._rejected: dict[str, set[str]] = {}

    def candidates(self, env: Env) -> Iterator[str]:
        """Yield usable tokens: the cached one first, then each source in order."""
        rejected = self._rejected.setdefault(env.name, set())
        cached = self._cached.get(env.name)
        if cached and cached not in rejected:
            yield cached
        for source in self._sources:
            token = source(env)
            if token and token not in rejected and token != cached:
                yield token

    def accept(self, env: Env, token: str) -> None:
        self._cached[env.name] = token

    def reject(self, env: Env, token: str) -> None:
        self._rejected.setdefault(env.name, set()).add(token)
        if self._cached.get(env.name) == token:
            del self._cached[env.name]

    def login(self, env: Env, timeout: int = 300) -> None:
        """Open the visible login window and cache the new token. Blocking."""
        rejected = self._rejected.get(env.name, set())
        reject = next(iter(rejected), None)
        token = self._capture(env.login_url, env.cookie_name, timeout, reject=reject)
        self._rejected.pop(env.name, None)
        self._cached[env.name] = token
