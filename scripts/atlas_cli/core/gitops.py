"""Git helpers for mount/resolve. Git is the overlay."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


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


def _auth_args(token: str | None) -> tuple[list[str], tuple[str, ...]]:
    """Git -c flags plus env keys to drop so a stale GH_TOKEN cannot override auth."""
    drop = ("GH_TOKEN", "GITHUB_TOKEN")
    if token:
        # Prefer the resolved token (env/gh) so CI/headless works even if `gh` is present.
        injected = f"https://x-access-token:{token}@github.com/"
        return (
            [
                "-c",
                "credential.helper=",
                "-c",
                f"url.{injected}.insteadOf=https://github.com/",
            ],
            drop,
        )
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
    return [], ()


def clone(
    url: str,
    dest: Path,
    ref: str | None,
    extra_env: dict | None = None,
    token: str | None = None,
) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    auth, drop = _auth_args(token)
    args = [*auth, "clone"]
    if ref:
        args.extend(["--branch", ref])
    args.extend([url, str(dest)])
    code, _out, err = run_git(args, env=extra_env, drop_keys=drop)
    return code, err


def submodule_add(
    parent: Path,
    url: str,
    dest: Path,
    ref: str | None,
    token: str | None = None,
) -> tuple[int, str]:
    rel = os.path.relpath(dest, parent)
    auth, drop = _auth_args(token)
    args = [*auth, "submodule", "add"]
    if ref:
        args.extend(["-b", ref])
    args.extend([url, rel])
    code, _out, err = run_git(args, cwd=parent, drop_keys=drop)
    return code, err


def submodule_init(
    parent: Path, dest: Path, token: str | None = None
) -> tuple[int, str]:
    rel = os.path.relpath(dest, parent)
    auth, drop = _auth_args(token)
    code, _out, err = run_git(
        [*auth, "submodule", "update", "--init", "--", rel],
        cwd=parent,
        drop_keys=drop,
    )
    return code, err
