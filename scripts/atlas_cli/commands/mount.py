from __future__ import annotations

import json
import sys
from pathlib import Path

from ..core.auth import AuthResult, resolve_auth
from ..core.authstore import lookup
from ..core.gitops import (
    SubmoduleSnapshot,
    bootstrap_empty_repository,
    capture_submodule_state,
    current_branch,
    git_root,
    has_git,
    inside_git,
    is_empty_repository,
    is_dirty,
    is_gitlink,
    remote_is_empty,
    rollback_submodule_state,
    run_git,
    submodule_add,
    submodule_init,
    submodule_register,
)
from ..core.identity import IdentityError, parse_pointer
from ..core.meshfile import MeshFileError, find_store, upsert
from ..core.translate import remote_url


def default_mount(project: Path, atlas_id: str) -> Path:
    return project / ".atlas" / Path(*atlas_id.split("/"))


def run(
    pointer: str,
    ref: str | None,
    target: str | None,
    ssh: bool,
    start: str | None,
    as_json: bool,
    quiet: bool = False,
    strategy: str | None = None,
) -> int:
    base = Path(start).resolve() if start else Path.cwd()
    try:
        parsed = parse_pointer(pointer)
    except IdentityError as e:
        return _fail(str(e), as_json)

    if not has_git():
        return _fail("git not on PATH (headless: mount is unavailable)", as_json)

    parent_git = git_root(base)
    if parent_git is None:
        return _fail("no git repository (refuse to mount; persist requires an active repo)", as_json)

    project = parent_git
    dest = (project / target).resolve() if target else default_mount(project, parsed.atlas_id)
    if not inside_git(project, dest):
        return _fail(
            "target must be inside the active git repository; omit --target to use .atlas/<id>",
            as_json,
        )

    host, org, _repo = parsed.atlas_id.split("/", 2)
    recorded = lookup(host, org)
    if recorded and not ssh:
        ssh = bool(recorded.get("ssh") or recorded.get("backend") == "ssh")
    auth = resolve_auth(host, want_ssh=ssh)
    if auth.error:
        auth = AuthResult(backend="none", host=host, token=None, ssh=ssh, error=auth.error)
    url = remote_url(pointer, auth)
    token = _explicit_git_token(auth)

    if dest.exists() and not dest.is_dir():
        return _fail(f"target is not a directory: {dest}", as_json)

    existing = dest / ".git"
    gitmodules_listed = _in_gitmodules(parent_git, dest)
    registered = is_gitlink(parent_git, dest)

    if dest.exists() and existing.exists():
        if is_dirty(dest):
            return _fail(f"dirty worktree: {dest}", as_json)
        actual_id, identity_error = _checkout_atlas_id(dest, parent_git)
        if actual_id != parsed.atlas_id:
            detail = actual_id or identity_error or "unknown origin"
            return _fail(
                f"existing checkout origin is {detail}; expected {parsed.atlas_id}",
                as_json,
            )
        if not registered:
            snapshot = capture_submodule_state(parent_git, dest)
            if is_empty_repository(dest):
                verify_code, remote_empty, verify_error = remote_is_empty(
                    url,
                    token=token,
                    backend=auth.backend,
                )
                if verify_code != 0 or not remote_empty:
                    cleanup = rollback_submodule_state(snapshot)
                    detail = (
                        verify_error
                        if verify_code != 0
                        else "remote contains refs but the checkout has no commit"
                    )
                    return _fail_with_cleanup(
                        detail or "unable to verify empty remote",
                        cleanup,
                        as_json,
                    )
                branch = ref or current_branch(dest)
                if not branch:
                    return _fail("empty repository has no branch; pass --ref", as_json)
                code, err = bootstrap_empty_repository(dest, branch)
                if code != 0:
                    cleanup = rollback_submodule_state(snapshot)
                    return _fail_with_cleanup(
                        err or "empty repository bootstrap failed",
                        cleanup,
                        as_json,
                    )
            code, err = submodule_register(parent_git, dest, url, ref)
            if code != 0:
                cleanup = rollback_submodule_state(snapshot)
                return _fail_with_cleanup(
                    err or "submodule register failed",
                    cleanup,
                    as_json,
                )
            landed = _persistable_ref(current_branch(dest), ref)
            result = _finish(
                project,
                dest,
                parsed.atlas_id,
                landed,
                as_json,
                "mounted",
                snapshot,
                quiet=quiet,
                strategy=strategy,
            )
            return result
        stored = None
        try:
            row = find_store(project, parsed.atlas_id)
            stored = (row or {}).get("ref")
        except MeshFileError:
            stored = None
        want = ref or stored
        have = current_branch(dest)
        if want and have and have != want and have != "HEAD":
            return _fail(f"wrong branch: have {have} want {want}", as_json)
        return _finish(
            project,
            dest,
            parsed.atlas_id,
            _persistable_ref(have, want),
            as_json,
            "noop",
            quiet=quiet,
            strategy=strategy,
        )

    dest_empty = dest.is_dir() and not any(dest.iterdir())
    if dest.is_dir() and not dest_empty:
        return _fail(f"target directory is not empty: {dest}", as_json)

    snapshot = capture_submodule_state(parent_git, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if gitmodules_listed and (not dest.exists() or dest_empty):
        code, err = submodule_init(
            parent_git,
            dest,
            token=token,
            host=host,
            backend=auth.backend,
        )
        if code != 0:
            cleanup = rollback_submodule_state(snapshot)
            return _fail_with_cleanup(
                err or "submodule update failed",
                cleanup,
                as_json,
            )
    else:
        code, err = submodule_add(
            parent_git,
            url,
            dest,
            ref,
            token=token,
            backend=auth.backend,
        )
        if code != 0:
            actual_id = None
            if (dest / ".git").exists():
                actual_id, _ = _checkout_atlas_id(dest, parent_git)
            if actual_id == parsed.atlas_id and is_empty_repository(dest):
                verify_code, remote_empty, verify_error = remote_is_empty(
                    url,
                    token=token,
                    backend=auth.backend,
                )
                if verify_code == 0 and remote_empty:
                    branch = ref or current_branch(dest)
                    if not branch:
                        cleanup = rollback_submodule_state(snapshot)
                        return _fail_with_cleanup(
                            "empty repository has no branch; pass --ref",
                            cleanup,
                            as_json,
                        )
                    code, bootstrap_error = bootstrap_empty_repository(dest, branch)
                    if code == 0:
                        code, register_error = submodule_register(
                            parent_git,
                            dest,
                            url,
                            ref,
                        )
                        if code == 0:
                            err = ""
                        else:
                            err = register_error or "submodule register failed"
                    else:
                        err = bootstrap_error or "empty repository bootstrap failed"
                elif verify_code != 0 and verify_error:
                    err = f"{err}; remote verification failed: {verify_error}"
            if code != 0:
                cleanup = rollback_submodule_state(snapshot)
                return _fail_with_cleanup(
                    err or "submodule add failed",
                    cleanup,
                    as_json,
                )
    landed = _persistable_ref(current_branch(dest), ref)
    return _finish(
        project,
        dest,
        parsed.atlas_id,
        landed,
        as_json,
        "mounted",
        snapshot,
        quiet=quiet,
        strategy=strategy,
    )


def _persistable_ref(*candidates: str | None) -> str:
    for candidate in candidates:
        if candidate and candidate != "HEAD":
            return candidate
    return ""


def _infer_subpath(dest: Path) -> str:
    if (dest / "SCHEMA.json").is_file():
        return ""
    if (dest / "atlas" / "SCHEMA.json").is_file():
        return "atlas"
    if (dest / "references" / "atlas" / "SCHEMA.json").is_file():
        return "references/atlas"
    return ""


def _explicit_git_token(auth: AuthResult) -> str | None:
    return auth.token if auth.backend == "token" and not auth.ssh else None


def _in_gitmodules(parent: Path, dest: Path) -> bool:
    gm = parent / ".gitmodules"
    if not gm.is_file():
        return False
    try:
        rel = str(dest.relative_to(parent)).replace("\\", "/")
    except ValueError:
        return False
    code, out, _ = run_git(
        ["config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"],
        cwd=parent,
    )
    if code != 0:
        return False
    for line in out.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2 and parts[1] == rel:
            return True
    return False


def _checkout_atlas_id(
    dest: Path,
    parent: Path | None = None,
) -> tuple[str | None, str | None]:
    code, raw_origin, raw_error = run_git(
        ["config", "--get", "remote.origin.url"],
        cwd=dest,
    )
    if code != 0 or not raw_origin:
        return None, raw_error or "origin remote is missing"

    _, expanded_origin, expanded_error = run_git(
        ["remote", "get-url", "origin"],
        cwd=dest,
    )
    errors: list[str] = []
    for origin in dict.fromkeys((raw_origin, expanded_origin)):
        if not origin:
            continue
        try:
            return parse_pointer(origin).atlas_id, None
        except IdentityError as exc:
            errors.append(str(exc))
    if parent is not None and _relative_origin(raw_origin or expanded_origin):
        p_code, parent_origin, _ = run_git(["remote", "get-url", "origin"], cwd=parent)
        if p_code == 0 and parent_origin:
            try:
                return parse_pointer(parent_origin).atlas_id, None
            except IdentityError as exc:
                errors.append(str(exc))
    detail = "; ".join(errors) or expanded_error or "unparseable origin"
    return None, f"origin remote is invalid ({detail})"


def _relative_origin(url: str | None) -> bool:
    if not url:
        return False
    return url in (".", "..", "./") or url.startswith("./") or url.startswith("../")


def _finish(
    project: Path,
    dest: Path,
    atlas_id: str,
    landed: str,
    as_json: bool,
    status: str,
    snapshot: SubmoduleSnapshot | None = None,
    quiet: bool = False,
    strategy: str | None = None,
) -> int:
    try:
        rel = dest.relative_to(project)
    except ValueError:
        return _fail("mounted Atlas is outside the active git repository", as_json)
    row = {
        "id": atlas_id,
        "ref": landed,
        "path": str(rel).replace("\\", "/"),
        "subpath": _infer_subpath(dest),
    }
    chosen = strategy
    if not chosen:
        try:
            existing = find_store(project, atlas_id)
        except MeshFileError:
            existing = None
        chosen = (existing or {}).get("strategy")
    if chosen:
        row["strategy"] = chosen
    try:
        upsert(project, row)
    except MeshFileError as e:
        cleanup = rollback_submodule_state(snapshot) if snapshot else []
        return _fail_with_cleanup(str(e), cleanup, as_json)
    return _ok(str(dest), atlas_id, landed, as_json, status, quiet)


def _fail(msg: str, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": msg}))
    else:
        print(f"atlas mount: {msg}", file=sys.stderr)
    return 2


def _fail_with_cleanup(msg: str, cleanup: list[str], as_json: bool) -> int:
    if cleanup:
        msg = f"{msg}; rollback failed: {'; '.join(cleanup)}"
    return _fail(msg, as_json)


def _ok(
    path: str,
    atlas_id: str,
    ref: str,
    as_json: bool,
    status: str,
    quiet: bool = False,
) -> int:
    if quiet:
        return 0
    if as_json:
        print(json.dumps({"ok": True, "path": path, "id": atlas_id, "ref": ref, "status": status}))
    else:
        print(path)
    return 0
