"""Storage strategy: shared (consumer atlas branch) vs dedicated (separate repo)."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

from ..core.auth import AuthResult, resolve_auth
from ..core.authstore import lookup
from ..core.gitops import (
    SHARED_BRANCH,
    commit_all,
    current_branch,
    ensure_attached_branch,
    ensure_shared_branch,
    git_root,
    has_git,
    inside_git,
    origin_url,
    push_history,
    ref_exists,
    remove_submodule,
    run_git,
    tree_has_schema,
)
from ..core.github_driver import protect_atlas_branch
from ..core.identity import IdentityError, parse_pointer
from ..core.meshfile import (
    MeshFileError,
    effective_strategy,
    find_store,
    load,
    remove_store,
    strategy_errors,
    upsert,
)
from ..core.schema import SCHEMA_NAME
from . import init as cmd_init
from . import mount as cmd_mount


def _mount(
    pointer: str,
    ref: str | None,
    target: str | None,
    ssh: bool,
    parent: Path,
    as_json: bool,
    strategy: str,
) -> int:
    return cmd_mount.run(
        pointer,
        ref,
        target,
        ssh,
        str(parent),
        as_json,
        True,
        strategy,
    )


def run_init(
    strategy: str,
    remote: str | None,
    start: str | None,
    ssh: bool,
    as_json: bool,
    schema_version: str = "1.0",
) -> int:
    if strategy not in ("shared", "dedicated"):
        return _fail(f"unknown strategy {strategy}", as_json)
    if not has_git():
        return _fail("git not on PATH", as_json)
    base = Path(start).resolve() if start else Path.cwd()
    parent = git_root(base)
    if parent is None:
        return _fail("no git repository", as_json)

    if strategy == "dedicated":
        if not remote:
            return _fail("dedicated init requires --remote (existing store; never creates it)", as_json)
        return _init_dedicated(parent, remote, ssh, as_json, schema_version)
    return _init_shared(parent, remote, ssh, as_json, schema_version)


def run_rehost(
    destination_strategy: str,
    remote: str | None,
    atlas_id: str | None,
    start: str | None,
    ssh: bool,
    as_json: bool,
) -> int:
    if destination_strategy not in ("shared", "dedicated"):
        return _fail(f"unknown destination strategy {destination_strategy}", as_json)
    if not has_git():
        return _fail("git not on PATH", as_json)
    base = Path(start).resolve() if start else Path.cwd()
    parent = git_root(base)
    if parent is None:
        return _fail("no git repository", as_json)
    try:
        source = _source_row(parent, atlas_id)
    except MeshFileError as e:
        return _fail(str(e), as_json)
    source_strategy = effective_strategy(source)
    if source_strategy == destination_strategy:
        return _fail(
            f"source and destination strategy are both {destination_strategy}",
            as_json,
        )
    if destination_strategy == "shared":
        return _rehost_to_shared(parent, source, ssh, as_json)
    if not remote:
        return _fail("dedicated destination requires --remote (existing repository)", as_json)
    return _rehost_to_dedicated(parent, source, remote, ssh, as_json)


def _init_shared(
    parent: Path,
    remote: str | None,
    ssh: bool,
    as_json: bool,
    schema_version: str,
) -> int:
    origin = origin_url(parent)
    pointer = origin or remote
    if not pointer:
        return _fail("shared init needs --remote or origin on the consumer repository", as_json)
    try:
        parsed = parse_pointer(pointer)
    except IdentityError as e:
        return _fail(str(e), as_json)
    atlas_id = parsed.atlas_id
    code, status, err = ensure_shared_branch(parent, SHARED_BRANCH)
    if code != 0:
        return _fail(err or "shared branch setup failed", as_json)

    dest = cmd_mount.default_mount(parent, atlas_id)
    warnings: list[str] = []
    auth = _auth_for(atlas_id, ssh)
    token = cmd_mount._explicit_git_token(auth)
    dest_url = origin_url(parent) or pointer
    if status == "created":
        code, err = push_history(
            parent,
            dest_url,
            SHARED_BRANCH,
            token=token,
            backend=auth.backend,
            source_ref=SHARED_BRANCH,
        )
        if code != 0:
            warnings.append(err or "push of empty atlas branch failed")
    if not (dest / ".git").exists():
        rc = _mount(
            atlas_id,
            SHARED_BRANCH,
            str(dest.relative_to(parent)),
            ssh,
            parent,
            as_json,
            "shared",
        )
        if rc != 0:
            return rc
    code, err = ensure_attached_branch(dest, SHARED_BRANCH)
    if code != 0:
        return _fail(err or "could not attach atlas branch in mount", as_json)

    created_schema = False
    if not (dest / SCHEMA_NAME).is_file():
        if status == "reused":
            return _fail(
                f"branch {SHARED_BRANCH} exists but is not an Atlas root (missing {SCHEMA_NAME})",
                as_json,
            )
        rc = _silent_init(dest, schema_version)
        if rc != 0:
            return rc
        _stamp_atlas_id(dest, atlas_id)
        code, err = commit_all(dest, "Initialize Atlas SCHEMA")
        if code != 0:
            return _fail(err or "SCHEMA commit failed", as_json)
        created_schema = True
        code, err = push_history(
            dest,
            dest_url,
            SHARED_BRANCH,
            token=token,
            backend=auth.backend,
            source_ref="HEAD",
        )
        if code != 0:
            warnings.append(err or "push of atlas SCHEMA failed; publish it before the GitHub ruleset")
        else:
            _, warn = protect_atlas_branch(atlas_id)
            if warn:
                warnings.append(warn)
    else:
        _, warn = protect_atlas_branch(atlas_id)
        if warn:
            warnings.append(warn)

    try:
        upsert(
            parent,
            {
                "id": atlas_id,
                "ref": SHARED_BRANCH,
                "path": str(dest.relative_to(parent)).replace("\\", "/"),
                "subpath": cmd_mount._infer_subpath(dest),
                "strategy": "shared",
            },
        )
    except MeshFileError as e:
        return _fail(str(e), as_json)
    for line in warnings:
        print(f"atlas store init: {line}", file=sys.stderr)
    return _ok(
        as_json,
        {
            "ok": True,
            "strategy": "shared",
            "id": atlas_id,
            "ref": SHARED_BRANCH,
            "path": str(dest),
            "branch_status": status,
            "schema": created_schema,
            "warnings": warnings,
        },
    )


def _init_dedicated(
    parent: Path,
    remote: str,
    ssh: bool,
    as_json: bool,
    schema_version: str,
) -> int:
    try:
        parsed = parse_pointer(remote)
    except IdentityError as e:
        return _fail(str(e), as_json)
    rc = _mount(remote, None, None, ssh, parent, as_json, "dedicated")
    if rc != 0:
        return rc
    dest = cmd_mount.default_mount(parent, parsed.atlas_id)
    created_schema = False
    if not (dest / SCHEMA_NAME).is_file():
        rc = _silent_init(dest, schema_version)
        if rc != 0:
            return rc
        _stamp_atlas_id(dest, parsed.atlas_id)
        code, err = commit_all(dest, "Initialize Atlas SCHEMA")
        if code != 0:
            return _fail(err or "SCHEMA commit failed", as_json)
        created_schema = True
    landed = current_branch(dest) or ""
    try:
        upsert(
            parent,
            {
                "id": parsed.atlas_id,
                "ref": landed,
                "path": str(dest.relative_to(parent)).replace("\\", "/"),
                "subpath": cmd_mount._infer_subpath(dest),
                "strategy": "dedicated",
            },
        )
    except MeshFileError as e:
        return _fail(str(e), as_json)
    return _ok(
        as_json,
        {
            "ok": True,
            "strategy": "dedicated",
            "id": parsed.atlas_id,
            "ref": landed,
            "path": str(dest),
            "schema": created_schema,
        },
    )


def _rehost_to_shared(parent: Path, source: dict, ssh: bool, as_json: bool) -> int:
    consumer = origin_url(parent)
    if not consumer:
        return _fail("shared destination needs origin on the consumer repository", as_json)
    try:
        dest_id = parse_pointer(consumer).atlas_id
    except IdentityError as e:
        return _fail(str(e), as_json)
    src_id = str(source["id"])
    try:
        src_path = _store_path(parent, source)
    except MeshFileError as e:
        return _fail(str(e), as_json)
    if not (src_path / ".git").exists() and not (src_path / SCHEMA_NAME).is_file():
        return _fail(f"source mount missing: {src_path}", as_json)

    code, status, err = ensure_shared_branch(parent, SHARED_BRANCH)
    if code != 0:
        return _fail(err, as_json)
    if status == "created" or not tree_has_schema(parent, SHARED_BRANCH):
        auth = _auth_for(dest_id, ssh)
        token = cmd_mount._explicit_git_token(auth)
        source_ref = current_branch(src_path) or "HEAD"
        code, err = push_history(
            src_path,
            consumer,
            SHARED_BRANCH,
            token=token,
            backend=auth.backend,
            source_ref=source_ref,
        )
        if code != 0:
            return _fail(err or "history push to shared atlas failed", as_json)
        run_git(["fetch", "origin", f"{SHARED_BRANCH}:{SHARED_BRANCH}"], cwd=parent)

    dest = cmd_mount.default_mount(parent, dest_id)
    if dest.resolve() != src_path.resolve():
        rc = _mount(
            dest_id,
            SHARED_BRANCH,
            str(dest.relative_to(parent)),
            ssh,
            parent,
            as_json,
            "shared",
        )
        if rc != 0:
            return rc
        code, err = remove_submodule(parent, src_path)
        if code != 0:
            return _fail(err or "could not remove previous submodule", as_json)
        try:
            remove_store(parent, src_id)
        except MeshFileError as e:
            return _fail(str(e), as_json)

    warnings: list[str] = []
    _, warn = protect_atlas_branch(dest_id)
    if warn:
        warnings.append(warn)
    try:
        upsert(
            parent,
            {
                "id": dest_id,
                "ref": SHARED_BRANCH,
                "path": str(dest.relative_to(parent)).replace("\\", "/"),
                "subpath": cmd_mount._infer_subpath(dest),
                "strategy": "shared",
            },
        )
    except MeshFileError as e:
        return _fail(str(e), as_json)
    row_errs = strategy_errors(
        {"id": dest_id, "ref": SHARED_BRANCH, "strategy": "shared"}
    )
    if row_errs:
        return _fail("; ".join(row_errs), as_json)
    for line in warnings:
        print(f"atlas store rehost: {line}", file=sys.stderr)
    return _ok(
        as_json,
        {
            "ok": True,
            "strategy": "shared",
            "id": dest_id,
            "from": src_id,
            "path": str(dest),
            "warnings": warnings,
        },
    )


def _rehost_to_dedicated(
    parent: Path,
    source: dict,
    remote: str,
    ssh: bool,
    as_json: bool,
) -> int:
    try:
        dest_parsed = parse_pointer(remote)
    except IdentityError as e:
        return _fail(str(e), as_json)
    dest_id = dest_parsed.atlas_id
    src_id = str(source["id"])
    try:
        src_path = _store_path(parent, source)
    except MeshFileError as e:
        return _fail(str(e), as_json)
    if not (src_path / ".git").exists() and not (src_path / SCHEMA_NAME).is_file():
        return _fail(f"source mount missing: {src_path}", as_json)
    auth = _auth_for(dest_id, ssh)
    token = cmd_mount._explicit_git_token(auth)
    source_ref = current_branch(src_path) or SHARED_BRANCH
    dest_branch = source_ref if source_ref not in ("HEAD", SHARED_BRANCH) else "main"
    if source_ref == SHARED_BRANCH:
        dest_branch = "main"
        source_ref = SHARED_BRANCH
    code, err = push_history(
        src_path,
        remote,
        dest_branch,
        token=token,
        backend=auth.backend,
        source_ref=source_ref if ref_exists(src_path, source_ref) else "HEAD",
    )
    if code != 0:
        return _fail(err or "history push to dedicated remote failed", as_json)
    dest = cmd_mount.default_mount(parent, dest_id)
    rc = _mount(remote, dest_branch, None, ssh, parent, as_json, "dedicated")
    if rc != 0:
        return rc
    if dest.resolve() != src_path.resolve():
        code, err = remove_submodule(parent, src_path)
        if code != 0:
            return _fail(err or "could not remove previous submodule", as_json)
        try:
            remove_store(parent, src_id)
        except MeshFileError as e:
            return _fail(str(e), as_json)
    landed = current_branch(dest) or dest_branch
    try:
        upsert(
            parent,
            {
                "id": dest_id,
                "ref": landed,
                "path": str(dest.relative_to(parent)).replace("\\", "/"),
                "subpath": cmd_mount._infer_subpath(dest),
                "strategy": "dedicated",
            },
        )
    except MeshFileError as e:
        return _fail(str(e), as_json)
    return _ok(
        as_json,
        {
            "ok": True,
            "strategy": "dedicated",
            "id": dest_id,
            "from": src_id,
            "path": str(dest),
        },
    )


def _source_row(parent: Path, atlas_id: str | None) -> dict:
    if atlas_id:
        row = find_store(parent, atlas_id)
        if not row:
            raise MeshFileError(f"no mesh row for {atlas_id}")
        return row
    stores = load(parent).get("stores") or []
    if len(stores) != 1:
        raise MeshFileError("pass --id when the mesh does not have exactly one store")
    return stores[0]


def _store_path(parent: Path, source: dict) -> Path:
    raw = str(source.get("path") or "").strip()
    if raw:
        dest = (parent / raw).resolve()
    else:
        dest = cmd_mount.default_mount(parent, str(source["id"]))
    if not inside_git(parent, dest):
        raise MeshFileError(
            f"mesh path escapes the consumer repository: {raw or dest}"
        )
    return dest


def _silent_init(dest: Path, schema_version: str) -> int:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        return cmd_init.run(str(dest), False, False, schema_version)


def _stamp_atlas_id(root: Path, atlas_id: str) -> None:
    path = root / SCHEMA_NAME
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    data["atlas_id"] = atlas_id
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _auth_for(atlas_id: str, ssh: bool) -> AuthResult:
    host, org, _repo = atlas_id.split("/", 2)
    recorded = lookup(host, org)
    if recorded and not ssh:
        ssh = bool(recorded.get("ssh") or recorded.get("backend") == "ssh")
    auth = resolve_auth(host, want_ssh=ssh)
    if auth.error:
        return AuthResult(backend="none", host=host, token=None, ssh=ssh, error=auth.error)
    return auth


def _fail(msg: str, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": msg}))
    else:
        print(f"atlas store: {msg}", file=sys.stderr)
    return 2


def _ok(as_json: bool, payload: dict) -> int:
    if as_json:
        print(json.dumps(payload))
    else:
        print(payload.get("path") or payload.get("id") or "ok")
    return 0
