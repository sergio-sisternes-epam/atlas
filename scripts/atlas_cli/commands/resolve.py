from __future__ import annotations

import json
import sys
from pathlib import Path

from ..core.gitops import git_root, inside_git
from ..core.identity import IdentityError, parse_pointer
from ..core.meshfile import MeshFileError, find_store

_RESOLVE_ERRORS = (OSError, RuntimeError)


def default_mount(project: Path, atlas_id: str) -> Path:
    return project / ".atlas" / Path(*atlas_id.split("/"))


def _join_under(base: Path, *relatives: str) -> Path | None:
    cur = base
    for rel in relatives:
        if not rel:
            continue
        part = Path(rel)
        if part.is_absolute() or ".." in part.parts:
            return None
        cur = cur.joinpath(*part.parts)
    return cur


def run(pointer: str, start: str | None, as_json: bool) -> int:
    base = Path(start).resolve() if start else Path.cwd()
    try:
        parsed = parse_pointer(pointer)
    except IdentityError as e:
        return _fail(str(e), as_json)
    project = git_root(base)
    if project is None:
        return _fail("no git repository (refuse to resolve)", as_json)
    try:
        row = find_store(project, parsed.atlas_id)
    except MeshFileError as e:
        return _fail(str(e), as_json)
    if not row:
        return _fail(f"not mounted: {parsed.atlas_id}", as_json)
    mount = Path(row["path"]) if row.get("path") else default_mount(project, parsed.atlas_id)
    if not mount.is_absolute():
        mount = project / mount
    try:
        mount = mount.resolve()
    except _RESOLVE_ERRORS as e:
        return _fail(str(e), as_json)
    if not inside_git(project, mount):
        return _fail(
            "resolved path must be inside the active git repository",
            as_json,
        )
    if not parsed.in_store:
        target = mount
    else:
        target = _join_under(mount, str(row.get("subpath") or ""), parsed.in_store)
        if target is None:
            return _fail(
                "resolved path must stay under the registered mount",
                as_json,
            )
    if not target.exists():
        return _fail(f"missing path: {target}", as_json)
    try:
        target = target.resolve()
    except _RESOLVE_ERRORS as e:
        return _fail(str(e), as_json)
    if not inside_git(project, target) or not inside_git(mount, target):
        return _fail(
            "resolved path must stay under the registered mount",
            as_json,
        )
    if as_json:
        print(json.dumps({"ok": True, "path": str(target), "id": parsed.atlas_id}))
    else:
        print(target)
    return 0


def _fail(msg: str, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": msg}))
    else:
        print(f"atlas resolve: {msg}", file=sys.stderr)
    return 2
