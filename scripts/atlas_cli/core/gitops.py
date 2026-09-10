"""Git helpers for mount/resolve. Git is the overlay."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .auth import TOKEN_ENV_KEYS

EMPTY_MOUNT_AUTHOR = "Atlas CLI"
EMPTY_MOUNT_EMAIL = "atlas@example.invalid"
EMPTY_MOUNT_DATE = "2000-01-01T00:00:00+00:00"
EMPTY_MOUNT_MESSAGE = "Initialize empty Atlas mount"


def has_git() -> bool:
    return shutil.which("git") is not None


def run_git(
    args: list[str],
    cwd: Path | None = None,
    env: dict | None = None,
    drop_keys: tuple[str, ...] = (),
    input_text: str | None = None,
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
        input=input_text,
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
    if code == 0:
        return out
    code, out, _ = run_git(["symbolic-ref", "--short", "HEAD"], cwd=repo)
    return out if code == 0 else ""


def is_empty_repository(repo: Path) -> bool:
    """True for an unborn checkout with no locally recorded refs."""
    code, _, _ = run_git(["rev-parse", "--verify", "HEAD"], cwd=repo)
    if code == 0:
        return False
    code, out, _ = run_git(
        ["for-each-ref", "--format=%(objectname)"],
        cwd=repo,
    )
    return code == 0 and not out


def remote_is_empty(
    url: str,
    token: str | None = None,
    backend: str = "none",
) -> tuple[int, bool, str]:
    """Check the remote directly; authentication or network errors are failures."""
    auth, drop = _auth_args(token, host=_https_host(url), backend=backend)
    code, out, err = run_git(
        [*auth, "ls-remote", url],
        drop_keys=drop,
    )
    return code, code == 0 and not out, _redact(err, token)


def bootstrap_empty_repository(repo: Path, branch: str) -> tuple[int, str]:
    """Create the deterministic root commit needed for a valid gitlink."""
    if not is_empty_repository(repo):
        return 2, "refuse to bootstrap a repository that already has refs"

    code, _, err = run_git(["check-ref-format", "--branch", branch], cwd=repo)
    if code != 0:
        return code, err or f"invalid branch: {branch}"

    code, _, err = run_git(
        ["symbolic-ref", "HEAD", f"refs/heads/{branch}"],
        cwd=repo,
    )
    if code != 0:
        return code, err

    code, tree, err = run_git(["mktree"], cwd=repo, input_text="")
    if code != 0:
        return code, err

    identity = {
        "GIT_AUTHOR_NAME": EMPTY_MOUNT_AUTHOR,
        "GIT_AUTHOR_EMAIL": EMPTY_MOUNT_EMAIL,
        "GIT_AUTHOR_DATE": EMPTY_MOUNT_DATE,
        "GIT_COMMITTER_NAME": EMPTY_MOUNT_AUTHOR,
        "GIT_COMMITTER_EMAIL": EMPTY_MOUNT_EMAIL,
        "GIT_COMMITTER_DATE": EMPTY_MOUNT_DATE,
    }
    code, commit, err = run_git(
        ["commit-tree", tree, "-m", EMPTY_MOUNT_MESSAGE],
        cwd=repo,
        env=identity,
    )
    if code != 0:
        return code, err

    code, _, err = run_git(
        ["update-ref", f"refs/heads/{branch}", commit],
        cwd=repo,
    )
    return code, err


SHARED_BRANCH = "atlas"
SCHEMA_BLOB = "SCHEMA.json"


def origin_url(repo: Path) -> str:
    """Configured origin URL, not the insteadOf-rewritten fetch URL."""
    code, out, _ = run_git(["config", "--get", "remote.origin.url"], cwd=repo)
    return out if code == 0 else ""


def ref_exists(repo: Path, branch: str) -> bool:
    code, _, _ = run_git(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo,
    )
    return code == 0


def tree_has_schema(repo: Path, treeish: str) -> bool:
    code, _, _ = run_git(["cat-file", "-e", f"{treeish}:{SCHEMA_BLOB}"], cwd=repo)
    return code == 0


def create_orphan_empty_branch(repo: Path, branch: str) -> tuple[int, str]:
    """Empty-tree orphan ref. Does not checkout; does not copy the working tree."""
    if ref_exists(repo, branch):
        return 2, f"branch already exists: {branch}"
    code, _, err = run_git(["check-ref-format", "--branch", branch], cwd=repo)
    if code != 0:
        return code, err or f"invalid branch: {branch}"
    code, tree, err = run_git(["mktree"], cwd=repo, input_text="")
    if code != 0:
        return code, err
    identity = {
        "GIT_AUTHOR_NAME": EMPTY_MOUNT_AUTHOR,
        "GIT_AUTHOR_EMAIL": EMPTY_MOUNT_EMAIL,
        "GIT_AUTHOR_DATE": EMPTY_MOUNT_DATE,
        "GIT_COMMITTER_NAME": EMPTY_MOUNT_AUTHOR,
        "GIT_COMMITTER_EMAIL": EMPTY_MOUNT_EMAIL,
        "GIT_COMMITTER_DATE": EMPTY_MOUNT_DATE,
    }
    code, commit, err = run_git(
        ["commit-tree", tree, "-m", EMPTY_MOUNT_MESSAGE],
        cwd=repo,
        env=identity,
    )
    if code != 0:
        return code, err
    code, _, err = run_git(
        ["update-ref", f"refs/heads/{branch}", commit],
        cwd=repo,
    )
    return code, err


def ensure_shared_branch(
    repo: Path,
    branch: str = SHARED_BRANCH,
    remote: str = "origin",
) -> tuple[int, str, str]:
    """Reuse atlas if SCHEMA.json is at the store root; else create empty orphan.

    Returns (code, status, error) where status is created|reused|"".
    """
    if not ref_exists(repo, branch):
        code, out, _ = run_git(
            ["ls-remote", "--heads", remote, branch],
            cwd=repo,
        )
        if code == 0 and out:
            fetch_code, _, fetch_err = run_git(
                ["fetch", remote, f"{branch}:{branch}"],
                cwd=repo,
            )
            if fetch_code != 0:
                return fetch_code, "", fetch_err or "failed to fetch shared branch"
    if ref_exists(repo, branch):
        if tree_has_schema(repo, branch):
            return 0, "reused", ""
        return (
            2,
            "",
            f"branch {branch} exists but is not an Atlas root (missing {SCHEMA_BLOB})",
        )
    code, err = create_orphan_empty_branch(repo, branch)
    if code != 0:
        return code, "", err or "orphan branch create failed"
    return 0, "created", ""


def ensure_attached_branch(repo: Path, branch: str) -> tuple[int, str]:
    have = current_branch(repo)
    if have == branch:
        return 0, ""
    code, _, err = run_git(["checkout", "-B", branch, f"refs/heads/{branch}"], cwd=repo)
    if code != 0:
        code, _, err = run_git(["checkout", "-B", branch], cwd=repo)
    return code, err


def commit_all(repo: Path, message: str) -> tuple[int, str]:
    code, _, err = run_git(["add", "-A"], cwd=repo)
    if code != 0:
        return code, err
    code, out, err = run_git(["status", "--porcelain"], cwd=repo)
    if code != 0:
        return code, err or out or "git status failed"
    if not out:
        return 0, ""
    identity = {
        "GIT_AUTHOR_NAME": EMPTY_MOUNT_AUTHOR,
        "GIT_AUTHOR_EMAIL": EMPTY_MOUNT_EMAIL,
        "GIT_COMMITTER_NAME": EMPTY_MOUNT_AUTHOR,
        "GIT_COMMITTER_EMAIL": EMPTY_MOUNT_EMAIL,
    }
    code, _, err = run_git(["commit", "-m", message], cwd=repo, env=identity)
    return code, err


def push_history(
    source: Path,
    dest_url: str,
    dest_branch: str,
    token: str | None = None,
    backend: str = "none",
    source_ref: str = "HEAD",
) -> tuple[int, str]:
    """Push source_ref to dest_url dest_branch. Fail closed if not fast-forward."""
    auth, drop = _auth_args(token, host=_https_host(dest_url), backend=backend)
    code, out, err = run_git(
        [*auth, "ls-remote", "--heads", dest_url, dest_branch],
        cwd=source,
        drop_keys=drop,
    )
    if code != 0:
        return code, _redact(err, token) or "unable to list destination heads"
    dest_tip = ""
    if out:
        dest_tip = out.split()[0]
    if dest_tip:
        fetch_code, _, fetch_err = run_git(
            [*auth, "fetch", dest_url, dest_branch],
            cwd=source,
            drop_keys=drop,
        )
        if fetch_code != 0:
            return fetch_code, _redact(fetch_err, token)
        anc_code, _, _ = run_git(
            ["merge-base", "--is-ancestor", dest_tip, source_ref],
            cwd=source,
        )
        if anc_code != 0:
            return 2, "destination history is unrelated; refuse to rewrite"
    code, _, err = run_git(
        [*auth, "push", dest_url, f"{source_ref}:refs/heads/{dest_branch}"],
        cwd=source,
        drop_keys=drop,
    )
    return code, _redact(err, token)


def remove_submodule(parent: Path, dest: Path) -> tuple[int, str]:
    rel = os.path.relpath(dest, parent).replace("\\", "/")
    run_git(["submodule", "deinit", "-f", "--", rel], cwd=parent)
    code, _, err = run_git(["rm", "-f", "--", rel], cwd=parent)
    if code != 0:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        return 0, ""
    modules = _git_path(parent, "modules")
    if modules:
        nested = modules / Path(*rel.split("/"))
        if nested.exists():
            shutil.rmtree(nested, ignore_errors=True)
    return 0, err


@dataclass(frozen=True)
class _FileSnapshot:
    path: Path
    content: bytes | None


@dataclass(frozen=True)
class SubmoduleSnapshot:
    parent: Path
    dest: Path
    dest_existed: bool
    dest_was_empty: bool
    dest_git_was_dir: bool
    missing_dest_parents: tuple[Path, ...]
    gitmodules: _FileSnapshot
    index: _FileSnapshot | None
    config: _FileSnapshot | None
    dest_git_config: _FileSnapshot | None
    dest_head_ref: str | None
    dest_head_oid: str | None
    modules_root: Path | None
    modules_root_existed: bool
    modules_path: Path | None
    modules_existed: bool
    modules_config: _FileSnapshot | None
    modules_head_ref: str | None
    modules_head_oid: str | None


def capture_submodule_state(parent: Path, dest: Path) -> SubmoduleSnapshot:
    """Capture all parent state that submodule add/register can mutate."""
    rel = os.path.relpath(dest, parent).replace("\\", "/")
    modules_root = _git_path(parent, "modules")
    modules_path = modules_root / Path(*rel.split("/")) if modules_root else None
    head_ref = _git_output(dest, ["symbolic-ref", "-q", "HEAD"])
    head_oid = _git_output(dest, ["rev-parse", "--verify", "HEAD"])
    modules_head_ref = _git_dir_output(
        modules_path,
        ["symbolic-ref", "-q", "HEAD"],
    )
    modules_head_oid = _git_dir_output(
        modules_path,
        ["rev-parse", "--verify", "HEAD"],
    )
    return SubmoduleSnapshot(
        parent=parent,
        dest=dest,
        dest_existed=dest.exists(),
        dest_was_empty=dest.is_dir() and not any(dest.iterdir()),
        dest_git_was_dir=(dest / ".git").is_dir(),
        missing_dest_parents=_missing_parents(dest.parent, parent),
        gitmodules=_snapshot_file(parent / ".gitmodules"),
        index=_snapshot_git_file(parent, "index"),
        config=_snapshot_git_file(parent, "config"),
        dest_git_config=(
            _snapshot_file(dest / ".git" / "config")
            if (dest / ".git").is_dir()
            else None
        ),
        dest_head_ref=head_ref,
        dest_head_oid=head_oid,
        modules_root=modules_root,
        modules_root_existed=bool(modules_root and modules_root.exists()),
        modules_path=modules_path,
        modules_existed=bool(modules_path and modules_path.exists()),
        modules_config=(
            _snapshot_file(modules_path / "config")
            if modules_path and modules_path.is_dir()
            else None
        ),
        modules_head_ref=modules_head_ref,
        modules_head_oid=modules_head_oid,
    )


def rollback_submodule_state(snapshot: SubmoduleSnapshot) -> list[str]:
    """Restore a captured state after a failed mount operation."""
    errors: list[str] = []
    dest_git = snapshot.dest / ".git"

    if snapshot.dest_existed and dest_git.exists():
        error = _restore_checkout_head(
            snapshot.dest,
            snapshot.dest_head_ref,
            snapshot.dest_head_oid,
        )
        if error:
            errors.append(error)

    if snapshot.modules_existed and snapshot.modules_path:
        error = _restore_git_dir_head(
            snapshot.modules_path,
            snapshot.modules_head_ref,
            snapshot.modules_head_oid,
        )
        if error:
            errors.append(error)

    if (
        snapshot.dest_existed
        and snapshot.dest_git_was_dir
        and dest_git.is_file()
        and snapshot.modules_path
        and snapshot.modules_path.is_dir()
        and not snapshot.modules_existed
    ):
        try:
            dest_git.unlink()
            shutil.move(str(snapshot.modules_path), str(dest_git))
        except OSError as exc:
            errors.append(f"restore nested git directory: {exc}")

    for file_snapshot in (
        snapshot.dest_git_config,
        snapshot.modules_config,
    ):
        if file_snapshot is not None:
            error = _restore_file(file_snapshot)
            if error:
                errors.append(error)

    if not snapshot.dest_existed or snapshot.dest_was_empty:
        try:
            if snapshot.dest.exists():
                shutil.rmtree(snapshot.dest)
            if snapshot.dest_existed:
                snapshot.dest.mkdir(parents=True)
        except OSError as exc:
            errors.append(f"restore mount target: {exc}")

    if (
        snapshot.modules_path
        and snapshot.modules_path.exists()
        and not snapshot.modules_existed
    ):
        try:
            shutil.rmtree(snapshot.modules_path)
        except OSError as exc:
            errors.append(f"remove partial submodule git directory: {exc}")

    for file_snapshot in (
        snapshot.gitmodules,
        snapshot.index,
        snapshot.config,
    ):
        if file_snapshot is not None:
            error = _restore_file(file_snapshot)
            if error:
                errors.append(error)

    for path in snapshot.missing_dest_parents:
        try:
            path.rmdir()
        except FileNotFoundError:
            continue
        except OSError:
            break

    if snapshot.modules_path and snapshot.modules_root:
        current = snapshot.modules_path.parent
        while (
            current != snapshot.modules_root.parent
            and current != snapshot.parent
        ):
            if current == snapshot.modules_root and snapshot.modules_root_existed:
                break
            try:
                current.rmdir()
            except FileNotFoundError:
                pass
            except OSError:
                break
            if current == snapshot.modules_root:
                break
            current = current.parent

    return errors


def _snapshot_file(path: Path) -> _FileSnapshot:
    return _FileSnapshot(path, path.read_bytes() if path.is_file() else None)


def _snapshot_git_file(parent: Path, name: str) -> _FileSnapshot | None:
    path = _git_path(parent, name)
    return _snapshot_file(path) if path else None


def _git_output(repo: Path, args: list[str]) -> str | None:
    if not (repo / ".git").exists():
        return None
    code, out, _ = run_git(args, cwd=repo)
    return out if code == 0 and out else None


def _git_dir_output(git_dir: Path | None, args: list[str]) -> str | None:
    if not git_dir or not git_dir.is_dir():
        return None
    code, out, _ = run_git(["--git-dir", str(git_dir), *args])
    return out if code == 0 and out else None


def _git_path(parent: Path, name: str) -> Path | None:
    code, out, _ = run_git(["rev-parse", "--git-path", name], cwd=parent)
    if code != 0 or not out:
        return None
    path = Path(out)
    return path if path.is_absolute() else (parent / path).resolve()


def _missing_parents(path: Path, stop: Path) -> tuple[Path, ...]:
    missing: list[Path] = []
    current = path
    while current != stop and not current.exists():
        missing.append(current)
        current = current.parent
    return tuple(missing)


def _restore_file(snapshot: _FileSnapshot) -> str | None:
    try:
        if snapshot.content is None:
            snapshot.path.unlink(missing_ok=True)
        else:
            snapshot.path.parent.mkdir(parents=True, exist_ok=True)
            snapshot.path.write_bytes(snapshot.content)
    except OSError as exc:
        return f"restore {snapshot.path}: {exc}"
    return None


def _restore_checkout_head(
    repo: Path,
    original_ref: str | None,
    original_oid: str | None,
) -> str | None:
    current_ref = _git_output(repo, ["symbolic-ref", "-q", "HEAD"])
    if current_ref and current_ref != original_ref:
        code, _, err = run_git(["update-ref", "-d", current_ref], cwd=repo)
        if code != 0:
            return f"remove bootstrap ref: {err}"
    if original_ref:
        code, _, err = run_git(
            ["symbolic-ref", "HEAD", original_ref],
            cwd=repo,
        )
        if code != 0:
            return f"restore checkout branch: {err}"
        if original_oid:
            code, _, err = run_git(
                ["update-ref", original_ref, original_oid],
                cwd=repo,
            )
            if code != 0:
                return f"restore checkout commit: {err}"
        else:
            code, _, err = run_git(
                ["update-ref", "-d", original_ref],
                cwd=repo,
            )
            if code != 0:
                return f"remove bootstrap commit: {err}"
    elif original_oid:
        code, _, err = run_git(
            ["update-ref", "--no-deref", "HEAD", original_oid],
            cwd=repo,
        )
        if code != 0:
            return f"restore detached checkout: {err}"
    return None


def _restore_git_dir_head(
    git_dir: Path,
    original_ref: str | None,
    original_oid: str | None,
) -> str | None:
    prefix = ["--git-dir", str(git_dir)]
    current_ref = _git_dir_output(git_dir, ["symbolic-ref", "-q", "HEAD"])
    if current_ref and current_ref != original_ref:
        code, _, err = run_git([*prefix, "update-ref", "-d", current_ref])
        if code != 0:
            return f"remove submodule bootstrap ref: {err}"
    if original_ref:
        code, _, err = run_git([*prefix, "symbolic-ref", "HEAD", original_ref])
        if code != 0:
            return f"restore submodule branch: {err}"
        if original_oid:
            code, _, err = run_git(
                [*prefix, "update-ref", original_ref, original_oid],
            )
        else:
            code, _, err = run_git([*prefix, "update-ref", "-d", original_ref])
        if code != 0:
            return f"restore submodule commit: {err}"
    elif original_oid:
        code, _, err = run_git(
            [*prefix, "update-ref", "--no-deref", "HEAD", original_oid],
        )
        if code != 0:
            return f"restore detached submodule: {err}"
    return None


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
    token: str | None,
    host: str = "github.com",
    backend: str = "none",
) -> tuple[list[str], tuple[str, ...]]:
    """Auth for clone / submodule add / submodule update.

    Never set http.extraHeader=Authorization — GitHub rejects that for
    private HTTPS clone/submodule add (invalid credentials). An explicitly
    resolved token is authoritative and uses a process-local URL rewrite for
    the already-authorized remote host. The gh backend uses its credential
    helper with token environment variables removed, so it can only select a
    stored credential for the host requested by Git. Anonymous HTTPS disables
    helpers rather than exposing generic credentials to an arbitrary host.
    """
    if token:
        injected = f"https://x-access-token:{token}@{host}/"
        return (
            [
                "-c",
                "credential.helper=",
                "-c",
                f"url.{injected}.insteadOf=https://{host}/",
            ],
            TOKEN_ENV_KEYS,
        )
    if backend == "gh":
        return (
            [
                "-c",
                "credential.helper=",
                "-c",
                "credential.helper=!gh auth git-credential",
            ],
            TOKEN_ENV_KEYS,
        )
    if backend == "ssh":
        return [], ()
    return ["-c", "credential.helper="], TOKEN_ENV_KEYS


def clone(
    url: str,
    dest: Path,
    ref: str | None,
    extra_env: dict | None = None,
    token: str | None = None,
    backend: str = "none",
) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    auth, drop = _auth_args(token, host=_https_host(url), backend=backend)
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
    backend: str = "none",
) -> tuple[int, str]:
    rel = os.path.relpath(dest, parent)
    auth, drop = _auth_args(token, host=_https_host(url), backend=backend)
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
    backend: str = "none",
) -> tuple[int, str]:
    rel = os.path.relpath(dest, parent)
    auth, drop = _auth_args(token, host=host, backend=backend)
    code, _out, err = run_git(
        [*auth, "submodule", "update", "--init", "--", rel],
        cwd=parent,
        drop_keys=drop,
    )
    return code, _redact(err, token)
