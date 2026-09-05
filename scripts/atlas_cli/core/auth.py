"""Auth backends: gh, token, ssh. No tokens written to atlas-mesh.json."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass


TOKEN_ENV_KEYS = (
    "ATLAS_PAT",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GITHUB_APM_PAT",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
)
GITHUB_CLOUD_TOKEN_KEYS = (
    "ATLAS_PAT",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_APM_PAT",
)
GHES_TOKEN_KEYS = (
    "ATLAS_PAT",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
    "GITHUB_APM_PAT",
)


@dataclass
class AuthResult:
    backend: str
    host: str
    token: str | None
    ssh: bool
    error: str | None = None


def _run(
    argv: list[str], drop_keys: tuple[str, ...] = ()
) -> tuple[int, str]:
    env = os.environ.copy()
    for key in drop_keys:
        env.pop(key, None)
    try:
        p = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
    except OSError as e:
        return 127, str(e)
    return p.returncode, (p.stdout or "").strip()


def _normalise_host(host: str) -> str:
    return host.strip().lower()


def _is_github_cloud_host(host: str) -> bool:
    normalised = _normalise_host(host)
    return normalised == "github.com" or normalised.endswith(".ghe.com")


def env_token(host: str = "github.com") -> str | None:
    normalised = _normalise_host(host)
    configured_host = _normalise_host(os.environ.get("GH_HOST", ""))
    if _is_github_cloud_host(normalised):
        keys = GITHUB_CLOUD_TOKEN_KEYS
    elif configured_host and configured_host == normalised:
        keys = GHES_TOKEN_KEYS
    else:
        return None

    for key in keys:
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return None


def gh_token(host: str) -> str | None:
    if not shutil.which("gh"):
        return None
    code, out = _run(
        ["gh", "auth", "token", "--hostname", host],
        drop_keys=TOKEN_ENV_KEYS,
    )
    if code == 0 and out:
        return out.splitlines()[0].strip()
    return None


def interactive_login(host: str) -> str | None:
    if not sys.stdin.isatty() or not shutil.which("gh"):
        return None
    code, _ = _run(
        ["gh", "auth", "login", "--hostname", host, "--web"],
        drop_keys=TOKEN_ENV_KEYS,
    )
    if code != 0:
        return None
    return gh_token(host)


def resolve_auth(host: str, want_ssh: bool = False) -> AuthResult:
    if want_ssh:
        return AuthResult(backend="ssh", host=host, token=None, ssh=True)
    tok = env_token(host)
    if tok:
        return AuthResult(backend="token", host=host, token=tok, ssh=False)
    tok = gh_token(host)
    if tok:
        return AuthResult(backend="gh", host=host, token=tok, ssh=False)
    tok = interactive_login(host)
    if tok:
        return AuthResult(backend="gh", host=host, token=tok, ssh=False)
    hint = f"atlas auth login --host {host}"
    if not sys.stdin.isatty():
        return AuthResult(
            backend="none",
            host=host,
            token=None,
            ssh=False,
            error=f"no credentials for {host}; run {hint}",
        )
    return AuthResult(
        backend="none",
        host=host,
        token=None,
        ssh=False,
        error=f"no credentials for {host}; run {hint}",
    )
