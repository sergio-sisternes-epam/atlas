from __future__ import annotations

import json
import sys
from pathlib import Path

from ..core.auth import AuthResult, resolve_auth
from ..core.authstore import lookup
from ..core.gitops import (
    current_branch,
    git_root,
    has_git,
    inside_git,
    is_dirty,
    is_gitlink,
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
    token = None if auth.ssh else auth.token

    if dest.exists() and not dest.is_dir():
        return _fail(f"target is not a directory: {dest}", as_json)

    existing = dest / ".git"
    gitmodules_listed = _in_gitmodules(parent_git, dest)
    registered = is_gitlink(parent_git, dest)

    if dest.exists() and existing.exists():
        if is_dirty(dest):
            return _fail(f"dirty worktree: {dest}", as_json)
        actual_id, identity_error = _checkout_atlas_id(dest)
        if actual_id != parsed.atlas_id:
            detail = actual_id or identity_error or "unknown origin"
            return _fail(
                f"existing checkout origin is {detail}; expected {parsed.atlas_id}",
                as_json,
            )
        if not registered:
            code, err = submodule_register(parent_git, dest, url, ref)
            if code != 0:
                return _fail(err or "submodule register failed", as_json)
            landed = current_branch(dest) or ref or ""
            return _finish(project, dest, parsed.atlas_id, landed, as_json, "mounted")
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
            have or want or "",
            as_json,
            "noop",
        )

    dest_empty = dest.is_dir() and not any(dest.iterdir())
    dest.parent.mkdir(parents=True, exist_ok=True)
    if gitmodules_listed and (not dest.exists() or dest_empty):
        code, err = submodule_init(parent_git, dest, token=token, host=host)
        if code != 0:
            return _fail(err or "submodule update failed", as_json)
    else:
        code, err = submodule_add(parent_git, url, dest, ref, token=token)
        if code != 0:
            return _fail(err or "submodule add failed", as_json)
    landed = current_branch(dest) or ref or ""
    return _finish(project, dest, parsed.atlas_id, landed, as_json, "mounted")


def _infer_subpath(dest: Path) -> str:
    if (dest / "SCHEMA.json").is_file():
        return ""
    if (dest / "atlas" / "SCHEMA.json").is_file():
        return "atlas"
    if (dest / "references" / "atlas" / "SCHEMA.json").is_file():
        return "references/atlas"
    return ""


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


def _checkout_atlas_id(dest: Path) -> tuple[str | None, str | None]:
    code, origin, error = run_git(["remote", "get-url", "origin"], cwd=dest)
    if code != 0 or not origin:
        return None, error or "origin remote is missing"
    try:
        return parse_pointer(origin).atlas_id, None
    except IdentityError as exc:
        return None, f"origin remote is invalid ({exc})"


def _finish(
    project: Path,
    dest: Path,
    atlas_id: str,
    landed: str,
    as_json: bool,
    status: str,
) -> int:
    try:
        rel = dest.relative_to(project)
    except ValueError:
        return _fail("mounted Atlas is outside the active git repository", as_json)
    try:
        upsert(
            project,
            {
                "id": atlas_id,
                "ref": landed,
                "path": str(rel).replace("\\", "/"),
                "subpath": _infer_subpath(dest),
            },
        )
    except MeshFileError as e:
        return _fail(str(e), as_json)
    return _ok(str(dest), atlas_id, landed, as_json, status)


def _fail(msg: str, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": msg}))
    else:
        print(f"atlas mount: {msg}", file=sys.stderr)
    return 2


def _ok(path: str, atlas_id: str, ref: str, as_json: bool, status: str) -> int:
    if as_json:
        print(json.dumps({"ok": True, "path": path, "id": atlas_id, "ref": ref, "status": status}))
    else:
        print(path)
    return 0
