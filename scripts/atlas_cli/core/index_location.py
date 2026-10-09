"""Where derived indexes live: ``<project-root>/.atlas/indexes/<driver-type>/<atlas-id>/``.

Single source of truth for the fts5 recall index, the nanograph index and the
tgrep index. Indexes are derived data: they belong to the consuming project,
never to a store's git history.

Resolution rule for a store directory ``S`` (resolved):

a. Mesh mode. Walk up from ``S.parent`` through its ancestors. At each
   directory ``D`` that contains ``atlas-mesh.json``, load it (malformed files
   are skipped) and look for a row whose ``path``, resolved against ``D``,
   equals ``S``. The first match wins: ``project_root = D``,
   ``atlas_id = row["id"]``, ``id_source = "mesh"``.
b. Standalone mode (no mesh row matches). ``project_root`` is the git
   work-tree top level of ``S`` (``git rev-parse --show-toplevel`` run in
   ``S``), or ``S`` itself when it is not inside a git work tree. When ``S`` is
   that top level and ``remote.origin.url`` normalises to ``host/org/repo``,
   ``atlas_id`` is that id (``id_source = "origin"``); otherwise it is
   ``local/<sanitised dir name>-<first 8 hex of sha256(str(S))>``
   (``id_source = "local"``). A store in a subdirectory of a larger work tree
   always gets a ``local`` id so two stores in one repository never share an
   index.
c. ``ATLAS_INDEX_ROOT`` (an absolute path) replaces ``project_root``; the
   atlas id and mode are resolved as above. Relative values are ignored with
   a warning.

The index directory is ``project_root/.atlas/indexes/<driver-type>/<id path>``
where ``<id path>`` is the validated atlas id split on ``/``. The legacy
in-store ``.atlas-index/`` layout is read-only for 0.14.x and removed after.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from . import gitops, meshfile
from .identity import IdentityError, normalise

DRIVER_TYPES = frozenset({"fts5", "nanograph", "tgrep"})
INDEXES_REL = PurePosixPath(".atlas") / "indexes"
LEGACY_DIR = ".atlas-index"
LEGACY_NAMES = {"fts5": "recall", "nanograph": "nanograph", "tgrep": "tgrep"}
OVERRIDE_ENV = "ATLAS_INDEX_ROOT"
LEGACY_WARNING_CODE = "legacy_index_location"
LEGACY_REMOVAL = "0.14.x"
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_NAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

_cache: dict[tuple[str, str], "IndexLocation"] = {}
_warned_relative = False


class IndexLocationError(ValueError):
    """An index path cannot be resolved or would escape its base."""


@dataclass(frozen=True)
class IndexLocation:
    store: Path
    project_root: Path
    atlas_id: str
    id_source: str  # "mesh" | "origin" | "local"
    mode: str  # "mesh" | "standalone"

    def as_dict(self) -> dict[str, str]:
        return {"mode": self.mode, "atlas_id": self.atlas_id, "id_source": self.id_source}


def clear_cache() -> None:
    _cache.clear()


def safe_id_path(atlas_id: str) -> PurePosixPath:
    """Validate an atlas id as a relative path; never re-normalises it."""
    text = atlas_id if isinstance(atlas_id, str) else ""
    if not text:
        raise IndexLocationError("atlas id for index path is empty")
    if "\\" in text or "\x00" in text:
        raise IndexLocationError(f"atlas id {atlas_id!r} contains a backslash or NUL")
    if text.startswith("/"):
        raise IndexLocationError(f"atlas id {atlas_id!r} must not be an absolute path")
    segments = text.split("/")
    for seg in segments:
        if seg in ("", ".", ".."):
            raise IndexLocationError(f"atlas id {atlas_id!r} has an empty, '.' or '..' segment")
        if not _SEGMENT.match(seg):
            raise IndexLocationError(f"atlas id {atlas_id!r} has an unsafe segment {seg!r}")
    return PurePosixPath(*segments)


def _local_id(store: Path) -> str:
    name = _NAME_UNSAFE.sub("-", store.name).strip("-._") or "store"
    digest = hashlib.sha256(str(store).encode("utf-8")).hexdigest()[:8]
    return f"local/{name}-{digest}"


@dataclass(frozen=True)
class MeshMatch:
    directory: Path
    row: dict[str, Any]
    doc: dict[str, Any]

    @property
    def mesh_file(self) -> Path:
        return self.directory / meshfile.MESH_NAME


def mesh_match(store: Path) -> MeshMatch | None:
    """The first ``atlas-mesh.json`` row (walking up from ``store.parent``) whose path is ``store``."""
    store = Path(store).expanduser().resolve()
    for directory in [store.parent, *store.parent.parents]:
        if not (directory / meshfile.MESH_NAME).is_file():
            continue
        try:
            doc = meshfile.load_for_location(directory)
        except (meshfile.MeshFileError, OSError, ValueError):
            continue
        for row in doc.get("stores") or []:
            if not isinstance(row, dict):
                continue
            raw = row.get("path")
            sid = row.get("id")
            if not isinstance(raw, str) or not raw.strip() or not isinstance(sid, str):
                continue
            try:
                candidate = (directory / raw).resolve()
            except (OSError, RuntimeError):
                continue
            if candidate == store:
                return MeshMatch(directory, row, doc)
    return None


def _mesh_match(store: Path) -> tuple[Path, str] | None:
    found = mesh_match(store)
    return (found.directory, str(found.row["id"])) if found else None


def _standalone(store: Path) -> tuple[Path, str, str]:
    top: Path | None = None
    if gitops.has_git() and store.is_dir():
        try:
            found = gitops.git_root(store)
        except OSError:
            found = None
        top = found.resolve() if found else None
    project_root = top or store
    if top is not None and top == store:
        try:
            url = gitops.origin_url(store)
        except OSError:
            url = ""
        if url:
            try:
                atlas_id = normalise(url)
                safe_id_path(atlas_id)
                return project_root, atlas_id, "origin"
            except (IdentityError, IndexLocationError):
                pass
    return project_root, _local_id(store), "local"


def _override_root() -> Path | None:
    global _warned_relative
    raw = os.environ.get(OVERRIDE_ENV, "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        if not _warned_relative:
            print(f"warning: {OVERRIDE_ENV} must be an absolute path; ignoring {raw!r}", file=sys.stderr)
            _warned_relative = True
        return None
    return path.resolve()


def resolve(store: Path) -> IndexLocation:
    """Resolve the project root and atlas id that own this store's indexes."""
    store_r = Path(store).expanduser().resolve()
    override = _override_root()
    key = (str(store_r), str(override or ""))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    match = _mesh_match(store_r)
    if match is not None:
        project_root, atlas_id = match
        loc = IndexLocation(store_r, project_root, atlas_id, "mesh", "mesh")
    else:
        project_root, atlas_id, source = _standalone(store_r)
        loc = IndexLocation(store_r, project_root, atlas_id, source, "standalone")
    if override is not None:
        loc = IndexLocation(store_r, override, loc.atlas_id, loc.id_source, loc.mode)
    _cache[key] = loc
    return loc


def _check_type(driver_type: str) -> None:
    if driver_type not in DRIVER_TYPES:
        raise ValueError(f"unknown index driver type {driver_type!r}; expected one of {sorted(DRIVER_TYPES)}")


def indexes_base(store: Path) -> Path:
    return resolve(store).project_root / INDEXES_REL


def reject_symlink_escape(anchor: Path, path: Path) -> None:
    """Reject ``path`` when it is outside ``anchor`` or crosses a symlink below it."""
    anchor_r = anchor.resolve()
    try:
        rel = path.relative_to(anchor)
    except ValueError as e:
        raise IndexLocationError("index path escapes its base") from e
    if ".." in rel.parts:
        raise IndexLocationError("index path escapes its base")
    acc = anchor
    for part in rel.parts:
        acc = acc / part
        if acc.is_symlink():
            raise IndexLocationError("index path must not be a symlink")
        if acc.exists():
            try:
                acc.resolve().relative_to(anchor_r)
            except ValueError as e:
                raise IndexLocationError("index path escapes its base") from e


def index_dir(store: Path, driver_type: str) -> Path:
    """``<project_root>/.atlas/indexes/<driver_type>/<atlas-id path>``, validated."""
    _check_type(driver_type)
    loc = resolve(store)
    base = loc.project_root / INDEXES_REL
    for guarded in (base.parent, base):
        if guarded.is_symlink():
            raise IndexLocationError(f"{guarded} must not be a symlink")
    type_base = base / driver_type
    path = type_base / safe_id_path(loc.atlas_id)
    reject_symlink_escape(base, path)
    try:
        path.resolve().relative_to(type_base.resolve())
    except ValueError as e:
        raise IndexLocationError("index path escapes its driver-type base") from e
    return path


def legacy_dir(store: Path, driver_type: str) -> Path:
    """Deprecated in-store location (``.atlas-index/...``); read-only for 0.14.x."""
    _check_type(driver_type)
    return Path(store) / LEGACY_DIR / LEGACY_NAMES[driver_type]


def project_relative(store: Path, path: Path) -> str:
    root = resolve(store).project_root
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()


def describe(store: Path, driver_type: str) -> dict[str, Any]:
    """``{"index_dir": <project-relative POSIX>, "index_location": {...}}`` for payloads."""
    loc = resolve(store)
    try:
        rel = project_relative(store, index_dir(store, driver_type))
    except IndexLocationError:
        rel = None
    return {"index_dir": rel, "index_location": loc.as_dict()}


def legacy_warning(store: Path, driver_type: str) -> dict[str, str]:
    old = (PurePosixPath(LEGACY_DIR) / LEGACY_NAMES[driver_type]).as_posix()
    try:
        new = project_relative(store, index_dir(store, driver_type))
    except IndexLocationError:
        new = (INDEXES_REL / driver_type).as_posix()
    return {
        "code": LEGACY_WARNING_CODE,
        "level": "warning",
        "message": (
            f"reading deprecated index at {old}; rebuild with `atlas recall index build` "
            f"(or rerun) to move it to {new}; legacy {LEGACY_DIR}/ support will be "
            f"removed after {LEGACY_REMOVAL}"
        ),
    }


def warning_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("message") or item.get("msg") or item)
    return str(item)
