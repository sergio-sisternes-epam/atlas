"""Git helpers for mount/resolve. Git is the overlay."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def has_git() -> bool:
    return shutil.which("git") is not None


def run_git(
    args: list[str],
    cwd: Path | None = None,
    env: dict | None = None,
    drop_keys: tuple[str, ...] = (),
) -> tuple[int, str, str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    for key in drop_keys:
        full_env.pop(key, None)
    p = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def git_root(start: Path) -> Path | None:
    code, out, _ = run_git(["rev-parse", "--show-toplevel"], cwd=start)
    if code == 0 and out:
        return Path(out)
    return None


def is_dirty(repo: Path) -> bool:
    code, out, _ = run_git(["status", "--porcelain"], cwd=repo)
    return code == 0 and bool(out)


def current_branch(repo: Path) -> str:
    code, out, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    return out if code == 0 else ""


def is_ignored(parent: Path, dest: Path) -> bool:
    """True when dest is ignored by parent git (e.g. default .atlas/ overlay)."""
    try:
        rel = os.path.relpath(dest, parent)
    except ValueError:
        return False
    code, _, _ = run_git(["check-ignore", "-q", rel], cwd=parent)
    return code == 0


def inside_git(parent: Path, dest: Path) -> bool:
    try:
        dest.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _https_host(url: str | None) -> str:
    if not url:
        return "github.com"
    if url.startswith("git@"):
        rest = url[4:]
        return rest.split(":", 1)[0] or "github.com"
    return urlsplit(url).hostname or "github.com"


def _redact(err: str, token: str | None) -> str:
    if err and token:
        return err.replace(token, "***")
    return err


def _auth_args(
    token: str | None, host: str = "github.com"
) -> tuple[list[str], tuple[str, ...]]:
    """Auth for clone / submodule add / submodule update.

    Never set http.extraHeader=Authorization — GitHub rejects that for
    private HTTPS clone/submodule add (invalid credentials). Prefer the
    gh credential helper when gh is on PATH (including machines that also
    have GH_TOKEN). Token insteadOf is only the no-gh / CI fallback, and
    rewrites the same host as the remote (not only github.com).
    Drop GH_TOKEN/GITHUB_TOKEN so a stale env token cannot override gh.
    """
    drop = ("GH_TOKEN", "GITHUB_TOKEN")
    if shutil.which("gh"):
        return (
            [
                "-c",
                "credential.helper=",
                "-c",
                "credential.helper=!gh auth git-credential",
            ],
            drop,
        )
    if token:
        injected = f"https://x-access-token:{token}@{host}/"
        return (
            [
                "-c",
                "credential.helper=",
                "-c",
                f"url.{injected}.insteadOf=https://{host}/",
            ],
            drop,
        )
    return [], ()


def clone(
    url: str,
    dest: Path,
    ref: str | None,
    extra_env: dict | None = None,
    token: str | None = None,
) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    auth, drop = _auth_args(token, host=_https_host(url))
    args = [*auth, "clone"]
    if ref:
        args.extend(["--branch", ref])
    args.extend([url, str(dest)])
    code, _out, err = run_git(args, env=extra_env, drop_keys=drop)
    return code, _redact(err, token)


def submodule_add(
    parent: Path,
    url: str,
    dest: Path,
    ref: str | None,
    token: str | None = None,
) -> tuple[int, str]:
    rel = os.path.relpath(dest, parent)
    auth, drop = _auth_args(token, host=_https_host(url))
    args = [*auth, "submodule", "add"]
    if ref:
        args.extend(["-b", ref])
    args.extend([url, rel])
    code, _out, err = run_git(args, cwd=parent, drop_keys=drop)
    return code, _redact(err, token)


def is_gitlink(parent: Path, dest: Path) -> bool:
    try:
        rel = os.path.relpath(dest, parent).replace("\\", "/")
    except ValueError:
        return False
    code, out, _ = run_git(["ls-files", "-s", "--", rel], cwd=parent)
    return code == 0 and out.startswith("160000")


def submodule_register(
    parent: Path,
    dest: Path,
    url: str,
    ref: str | None,
) -> tuple[int, str]:
    """Register an existing checkout as a submodule of parent."""
    rel = os.path.relpath(dest, parent).replace("\\", "/")
    name = rel
    for key, val in (
        (f"submodule.{name}.path", rel),
        (f"submodule.{name}.url", url),
    ):
        code, _, err = run_git(["config", "--file", ".gitmodules", key, val], cwd=parent)
        if code != 0:
            return code, err
    if ref:
        code, _, err = run_git(
            ["config", "--file", ".gitmodules", f"submodule.{name}.branch", ref],
            cwd=parent,
        )
        if code != 0:
            return code, err
    code, _, err = run_git(["add", "--", ".gitmodules", rel], cwd=parent)
    if code != 0:
        return code, err
    code, _, err = run_git(["submodule", "absorbgitdirs", "--", rel], cwd=parent)
    return code, err


def submodule_init(
    parent: Path,
    dest: Path,
    token: str | None = None,
    host: str = "github.com",
) -> tuple[int, str]:
    rel = os.path.relpath(dest, parent)
    auth, drop = _auth_args(token, host=host)
    code, _out, err = run_git(
        [*auth, "submodule", "update", "--init", "--", rel],
        cwd=parent,
        drop_keys=drop,
    )
    return code, _redact(err, token)
