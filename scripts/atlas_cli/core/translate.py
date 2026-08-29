"""Pointer → authenticated git remote URL."""

from __future__ import annotations

from .auth import AuthResult
from .identity import parse_pointer


def remote_url(pointer: str, auth: AuthResult) -> str:
    parsed = parse_pointer(pointer)
    host, org, repo = parsed.atlas_id.split("/", 2)
    if auth.ssh:
        return f"git@{host}:{org}/{repo}.git"
    return f"https://{host}/{org}/{repo}.git"


def git_env(auth: AuthResult) -> dict[str, str]:
    env = {}
    if auth.token and not auth.ssh:
        env["GIT_ASKPASS"] = "echo"
        env["GIT_TERMINAL_PROMPT"] = "0"
        # extraheader set by caller via -c if needed
    return env
