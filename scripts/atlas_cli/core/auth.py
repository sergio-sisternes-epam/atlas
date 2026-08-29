"""Auth backends: gh, token, ssh. No tokens written to atlas-mesh.json."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class AuthResult:
    backend: str
    host: str
    token: str | None
    ssh: bool
    error: str | None = None


def _run(argv: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as e:
        return 127, str(e)
    return p.returncode, (p.stdout or "").strip()


def env_token() -> str | None:
    for key in ("ATLAS_PAT", "GITHUB_TOKEN", "GH_TOKEN", "GITHUB_APM_PAT"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return None


def gh_token(host: str) -> str | None:
    if not shutil.which("gh"):
        return None
    code, out = _run(["gh", "auth", "token", "--hostname", host])
    if code == 0 and out:
        return out.splitlines()[0].strip()
    return None


def interactive_login(host: str) -> str | None:
    if not sys.stdin.isatty() or not shutil.which("gh"):
        return None
    code, _ = _run(["gh", "auth", "login", "--hostname", host, "--web"])
    if code != 0:
        return None
    return gh_token(host)


def resolve_auth(host: str, want_ssh: bool = False) -> AuthResult:
    if want_ssh:
        return AuthResult(backend="ssh", host=host, token=None, ssh=True)
    tok = env_token()
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
