from __future__ import annotations

import json
import sys
from pathlib import Path

from ..core.gitops import git_root
from ..core.identity import IdentityError, parse_pointer
from ..core.meshfile import MeshFileError, find_project_root, find_store


def default_mount(project: Path, atlas_id: str) -> Path:
    return project / ".atlas" / Path(*atlas_id.split("/"))


def run(pointer: str, start: str | None, as_json: bool) -> int:
    base = Path(start).resolve() if start else Path.cwd()
    try:
        parsed = parse_pointer(pointer)
    except IdentityError as e:
        return _fail(str(e), as_json)
    project = git_root(base) or find_project_root(base)
    try:
        row = find_store(project, parsed.atlas_id)
    except MeshFileError as e:
        return _fail(str(e), as_json)
    if not row:
        return _fail(f"not mounted: {parsed.atlas_id}", as_json)
    mount = Path(row["path"]) if row.get("path") else default_mount(project, parsed.atlas_id)
    if not mount.is_absolute():
        mount = project / mount
    if not parsed.in_store:
        target = mount
    else:
        sub = row.get("subpath") or ""
        target = mount.joinpath(*Path(sub).parts, *Path(parsed.in_store).parts) if sub else mount.joinpath(*Path(parsed.in_store).parts)
    if not target.exists():
        return _fail(f"missing path: {target}", as_json)
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
