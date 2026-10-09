"""Immutable recall index generations."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import index_location
from .index_location import IndexLocationError
from .projection import ProjectedPage, cheap_fingerprint, project_store
from .recall_config import fts5_available, recall_enabled

INDEX_DIR = index_location.LEGACY_DIR
CURRENT_NAME = "current.json"
DRIVER_TYPE = "fts5"

IndexError_ = IndexLocationError


@dataclass(frozen=True)
class Generation:
    """A published generation a reader may use; ``legacy`` marks the deprecated location."""

    db: Path
    pointer: dict[str, Any]
    legacy: bool


def index_root(store: Path) -> Path:
    return index_location.index_dir(store, DRIVER_TYPE)


def legacy_root(store: Path) -> Path:
    return index_location.legacy_dir(store, DRIVER_TYPE)


def _reject_symlink_escape(anchor: Path, path: Path) -> None:
    index_location.reject_symlink_escape(anchor, path)


def current_pointer(store: Path) -> Path:
    return index_root(store) / CURRENT_NAME


def _read_pointer(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _new_pointer(store: Path) -> tuple[Path | None, dict[str, Any] | None]:
    try:
        root = index_root(store)
    except IndexLocationError:
        return None, None
    return root, _read_pointer(root / CURRENT_NAME)


def _candidates(store: Path) -> list[Generation]:
    """Usable published generations, new location first, then the legacy one."""
    out: list[Generation] = []
    root, cur = _new_pointer(store)
    if root is not None and cur and cur.get("complete"):
        db = _pointer_db(root, cur.get("db"))
        if db is not None:
            out.append(Generation(db, cur, False))
    legacy = _read_pointer(legacy_root(store) / CURRENT_NAME)
    if legacy and legacy.get("complete"):
        db = _legacy_pointer_db(store, legacy.get("db"))
        if db is not None:
            out.append(Generation(db, legacy, True))
    return out


def load_current(store: Path) -> dict[str, Any] | None:
    """The pointer readers see: new location when usable, else a usable legacy one."""
    found = _candidates(store)
    if found:
        return found[0].pointer
    return _new_pointer(store)[1]


def active_generation(store: Path) -> Generation | None:
    found = _candidates(store)
    return found[0] if found else None


def _write_sqlite(path: Path, pages: list[ProjectedPage], digest: str) -> int:
    conn = sqlite3.connect(str(path))
    inserted = 0
    try:
        conn.execute(
            "CREATE TABLE pages (id TEXT PRIMARY KEY, path TEXT, role TEXT, digest TEXT, title TEXT, description TEXT, body TEXT, meta_json TEXT, edges_json TEXT)"
        )
        have_fts = fts5_available()
        if have_fts:
            conn.execute(
                "CREATE VIRTUAL TABLE pages_fts USING fts5(id, title, description, body, tokenize='unicode61')"
            )
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        for page in pages:
            if page.role == "log":
                continue
            conn.execute(
                "INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    page.page_id,
                    page.path,
                    page.role,
                    page.digest,
                    page.title,
                    page.description,
                    page.body,
                    json.dumps(page.meta, ensure_ascii=False),
                    json.dumps(page.edges, ensure_ascii=False),
                ),
            )
            if have_fts:
                conn.execute(
                    "INSERT INTO pages_fts(id, title, description, body) VALUES (?,?,?,?)",
                    (page.page_id, page.title, page.description, page.body),
                )
            inserted += 1
        conn.execute("INSERT INTO meta VALUES ('corpus_digest', ?)", (digest,))
        conn.execute("INSERT INTO meta VALUES ('page_count', ?)", (str(inserted),))
        conn.commit()
    finally:
        conn.close()
    return inserted


def _write_pointer(root: Path, pointer: dict[str, Any]) -> None:
    target = root / CURRENT_NAME
    tmp = target.with_suffix(".json.tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def publish_generation(
    store: Path,
    schema: dict[str, Any] | None,
    focused: bool,
    projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish a complete generation under the project-owned index root only.

    Never reads from or writes to the legacy in-store ``.atlas-index/``.
    """
    if focused:
        raise IndexError_("focused compile cannot publish a complete generation")
    if not recall_enabled(schema):
        return {"published": False, "reason": "recall_disabled"}
    root = index_root(store)
    base = index_location.indexes_base(store)
    _reject_symlink_escape(base, root)
    where = index_location.describe(store, DRIVER_TYPE)
    if projection is None:
        projection = project_store(store, schema, allow_partial=False)
    if not projection.get("complete"):
        return {"published": False, "reason": "incomplete", **where}
    digest = projection["corpus_digest"]
    cur = _read_pointer(root / CURRENT_NAME)
    if cur and cur.get("complete") and cur.get("corpus_digest") == digest:
        db = _pointer_db(root, cur.get("db"))
        if db is not None:
            pointer = {
                "generation": cur.get("generation"),
                "corpus_digest": digest,
                "cheap_fingerprint": cheap_fingerprint(store, schema),
                "db": cur.get("db"),
                "complete": True,
                "count": cur.get("count"),
            }
            _write_pointer(root, pointer)
            return {"published": True, "reused": True, **pointer, **where}
    gen_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    dest_dir = root / "generations" / gen_id
    _reject_symlink_escape(base, dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    _reject_symlink_escape(base, dest_dir)
    db_path = dest_dir / "projection.sqlite"
    fd, tmp_name = tempfile.mkstemp(
        prefix="atlas-recall-", suffix=".sqlite", dir=str(dest_dir)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        inserted = _write_sqlite(tmp, projection["pages"], projection["corpus_digest"])
        os.replace(tmp, db_path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    pointer = {
        "generation": gen_id,
        "corpus_digest": projection["corpus_digest"],
        "cheap_fingerprint": cheap_fingerprint(store, schema),
        "db": db_path.relative_to(root).as_posix(),
        "complete": True,
        "count": inserted,
    }
    _write_pointer(root, pointer)
    return {"published": True, **pointer, **where}


def _relative_pointer(raw: object) -> Path | None:
    text = str(raw or "").strip().replace("\\", "/")
    if not text or Path(text).is_absolute() or Path(text).anchor:
        return None
    rel = Path(text)
    if ".." in rel.parts:
        return None
    return rel


def _pointer_db(root: Path, raw: object) -> Path | None:
    """Resolve a pointer ``db`` stored relative to the index root ``root``."""
    rel = _relative_pointer(raw)
    if rel is None or not rel.parts or rel.parts[0] != "generations":
        return None
    try:
        _reject_symlink_escape(root, root / rel)
    except IndexLocationError:
        return None
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _legacy_pointer_db(store: Path, raw: object) -> Path | None:
    """Deprecated layout: ``db`` relative to the store under ``.atlas-index/recall``."""
    rel = _relative_pointer(raw)
    if rel is None:
        return None
    try:
        rel.relative_to(Path(INDEX_DIR) / index_location.LEGACY_NAMES[DRIVER_TYPE])
    except ValueError:
        return None
    candidate = (store / rel).resolve()
    try:
        candidate.relative_to(store.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def find_generation(
    store: Path,
    *,
    digest: str | None = None,
    schema: dict[str, Any] | None = None,
    fast_path: bool = False,
) -> Generation | None:
    """First usable generation matching ``digest`` (or the cheap fingerprint).

    The new location is preferred; the legacy location is only consulted when
    the new one has no match, and is never modified.
    """
    fingerprint = cheap_fingerprint(store, schema) if fast_path else None
    for gen in _candidates(store):
        cur = gen.pointer
        if fast_path:
            if not cur.get("cheap_fingerprint") or cur.get("cheap_fingerprint") != fingerprint:
                continue
        elif cur.get("corpus_digest") != digest:
            continue
        return gen
    return None


def matching_generation(store: Path, digest: str) -> Path | None:
    gen = find_generation(store, digest=digest)
    return gen.db if gen else None


def matching_fast_path(store: Path, schema: dict[str, Any] | None) -> Path | None:
    gen = find_generation(store, schema=schema, fast_path=True)
    return gen.db if gen else None


def legacy_warning(store: Path) -> dict[str, str]:
    return index_location.legacy_warning(store, DRIVER_TYPE)


def pages_from_db(db_path: Path) -> list[ProjectedPage]:
    conn = open_db(db_path)
    try:
        rows = conn.execute(
            "SELECT id, path, role, digest, title, description, body, meta_json, edges_json FROM pages"
        ).fetchall()
    finally:
        conn.close()
    pages: list[ProjectedPage] = []
    for row in rows:
        try:
            meta = json.loads(row[7] or "{}")
        except json.JSONDecodeError:
            meta = {}
        try:
            edges = json.loads(row[8] or "[]")
        except json.JSONDecodeError:
            edges = []
        if not isinstance(meta, dict):
            meta = {}
        if not isinstance(edges, list):
            edges = []
        pages.append(
            ProjectedPage(
                page_id=str(row[0]),
                path=str(row[1]),
                role=str(row[2] or "concept"),
                digest=str(row[3] or ""),
                meta=meta,
                body=str(row[6] or ""),
                title=str(row[4] or ""),
                description=str(row[5] or ""),
                edges=edges,
            )
        )
    return pages


def open_db(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def build_ephemeral(projection: dict[str, Any]) -> Path:
    fd, name = tempfile.mkstemp(prefix="atlas-recall-eph-", suffix=".sqlite")
    os.close(fd)
    path = Path(name)
    _write_sqlite(path, projection["pages"], projection["corpus_digest"])
    return path
