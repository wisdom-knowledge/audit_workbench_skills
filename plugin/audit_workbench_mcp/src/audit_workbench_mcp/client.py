"""HTTP calls to the existing /api/v1/admin endpoints.

All permission, optimistic-lock and idempotency checks stay in the backend;
this layer only attaches the token, unwraps the envelope and maps failures.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from . import errors
from .auth import TokenStore
from .envs import Env

API_PREFIX = "/api/v1"
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
READ_RETRY_DELAY = 1.0


class AdminClient:
    def __init__(
        self,
        tokens: TokenStore,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_delay: float = READ_RETRY_DELAY,
    ) -> None:
        self._tokens = tokens
        self._transport = transport
        self._retry_delay = retry_delay

    async def request(
        self,
        env: Env,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        is_write: bool = False,
    ) -> Any:
        """Return the envelope's ``data`` or raise AuditWorkbenchError.

        Reads are retried once on 5xx, timeouts and connection errors. Writes are
        never retried here, because a timed-out write may already have applied.
        """
        attempts = 1 if is_write else 2
        for attempt in range(attempts):
            try:
                return await self._request_once(env, method, path, json=json, params=params)
            except errors.AuditWorkbenchError as exc:
                if exc.code != errors.UNAVAILABLE or attempt == attempts - 1:
                    raise
            await asyncio.sleep(self._retry_delay)
        raise AssertionError("unreachable")

    async def _request_once(
        self,
        env: Env,
        method: str,
        path: str,
        *,
        json: Any,
        params: dict[str, Any] | None,
    ) -> Any:
        url = f"{env.base_url}{API_PREFIX}{path}"
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        candidates = self._tokens.candidates(env)
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, transport=self._transport
        ) as http:
            while True:
                # The browser-profile source starts headless Chrome; keep it off the event loop.
                token = await asyncio.to_thread(next, candidates, None)
                if token is None:
                    raise errors.AuditWorkbenchError(
                        errors.UNAUTHORIZED,
                        f"{env.name} 环境没有可用的管理员登录态",
                        http_status=401,
                    )
                try:
                    resp = await http.request(
                        method,
                        url,
                        json=json,
                        params=clean_params or None,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/json",
                        },
                    )
                except httpx.TimeoutException as exc:
                    raise errors.AuditWorkbenchError(
                        errors.UNAVAILABLE, f"请求超时：{method} {path}"
                    ) from exc
                except httpx.HTTPError as exc:
                    raise errors.AuditWorkbenchError(
                        errors.UNAVAILABLE, f"请求失败：{type(exc).__name__}"
                    ) from exc

                if resp.status_code == 401:
                    # Expired or wrong token; drop it and try the next source.
                    self._tokens.reject(env, token)
                    continue
                self._tokens.accept(env, token)
                return _unwrap(resp)


def _unwrap(resp: httpx.Response) -> Any:
    try:
        body = resp.json()
    except ValueError:
        body = None

    if resp.is_success:
        if isinstance(body, dict) and body.get("status_code", 0) == 0 and "data" in body:
            return body["data"]
        if isinstance(body, dict) and body.get("status_code", 0) != 0:
            raise errors.from_http_failure(resp.status_code, body)
        raise errors.AuditWorkbenchError(
            errors.UNEXPECTED_RESPONSE,
            "后端返回的不是预期的 {status_code, status_msg, data} 结构",
            http_status=resp.status_code,
        )

    if body is None:
        raise errors.AuditWorkbenchError(
            errors.code_for_status(resp.status_code),
            f"HTTP {resp.status_code}",
            http_status=resp.status_code,
        )
    raise errors.from_http_failure(resp.status_code, body)
