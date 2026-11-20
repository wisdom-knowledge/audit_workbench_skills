"""Target environments: backend base URL, admin site, cookie name and login URL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EnvName = Literal["boe", "prod"]


@dataclass(frozen=True)
class Env:
    name: str
    base_url: str
    admin_url: str
    cookie_name: str
    secrets_key: str
    login_url: str


ENVS: dict[str, Env] = {
    "boe": Env(
        name="boe",
        base_url="https://service-boe.meetchances.com",
        admin_url="https://admin-test.meetchances.com",
        cookie_name="boe_admin_access_token",
        secrets_key="BOE_ADMIN_TOKEN",
        login_url=(
            "https://meetchances-admin-boe.authing.cn/oidc/auth?client_id=68b58e0849acdf7f76eb5861"
            "&redirect_uri=https://service-boe.meetchances.com/api/v1/admin/login-callback"
            "&response_type=code&scope=openid+profile+email+phone+address+username+offline_access"
            "&state=redirect_uri=https://admin-test.meetchances.com"
        ),
    ),
    "prod": Env(
        name="prod",
        base_url="https://service.meetchances.com",
        admin_url="https://admin.meetchances.com",
        cookie_name="prod_admin_access_token",
        secrets_key="PROD_ADMIN_TOKEN",
        login_url=(
            "https://meetchances-admin.authing.cn/oidc/auth?client_id=68b696c2eb7703051e9f8cea"
            "&redirect_uri=https://service.meetchances.com/api/v1/admin/login-callback"
            "&response_type=code&scope=openid+profile+email+phone+address+username+offline_access"
            "&state=redirect_uri=https://admin.meetchances.com"
        ),
    ),
}


def get_env(name: str) -> Env:
    env = ENVS.get(name.lower())
    if env is None:
        raise ValueError(f"env 只能是 boe 或 prod，收到 {name!r}")
    return env
