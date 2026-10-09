"""Immutable recall index generations."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import index_location, index_publish
from .ignore_guard import ensure_indexes_ignored
from .index_location import IndexLocationError
from .projection import ProjectedPage, cheap_fingerprint, project_store
from .recall_config import fts5_available, recall_enabled

INDEX_DIR = index_location.LEGACY_DIR
CURRENT_NAME = "current.json"
DRIVER_TYPE = "fts5"
DB_NAME = "projection.sqlite"
# The pointer's generation plus one previous one, so a reader that resolved the
# old pointer just before a swap can finish its query.
KEEP_GENERATIONS = 2

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
    index_publish.write_json_atomic(root / CURRENT_NAME, pointer)


class IndexNotBuilt(Exception):
    """The corpus cannot be indexed as a complete generation (``reason`` says why)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Freshness:
    """Outcome of :func:`ensure_fresh`: the generation to read and whether it was just built."""

    generation: Generation
    rebuilt: bool
    previous: str | None = None


def _fresh_new(root: Path, *, digest: str | None = None, fingerprint: str | None = None) -> Generation | None:
    cur = _read_pointer(root / CURRENT_NAME)
    if not cur or not cur.get("complete"):
        return None
    if fingerprint is not None:
        if not cur.get("cheap_fingerprint") or cur.get("cheap_fingerprint") != fingerprint:
            return None
    elif digest is None or cur.get("corpus_digest") != digest:
        return None
    db = _pointer_db(root, cur.get("db"))
    return Generation(db, cur, False) if db is not None else None


def _prune(root: Path, keep: str | None) -> None:
    """Keep the pointer's generation plus the newest other one (readers mid-query keep working)."""
    gens = root / "generations"
    if not gens.is_dir():
        return
    others: list[tuple[int, str, Path]] = []
    for child in gens.iterdir():
        if child.name == keep or child.is_symlink() or not child.is_dir():
            continue
        if child.name.startswith(index_publish.TMP_PREFIX):
            continue
        try:
            others.append((child.stat().st_mtime_ns, child.name, child))
        except OSError:
            continue
    others.sort(reverse=True)
    for _, _, old in others[KEEP_GENERATIONS - 1 :]:
        shutil.rmtree(old, ignore_errors=True)


def ensure_fresh(
    store: Path,
    schema: dict[str, Any] | None,
    *,
    projection: dict[str, Any] | None = None,
    allow_legacy: bool = True,
    wait: float | None = None,
    guard_ignore: bool = False,
) -> Freshness:
    """Return a generation matching the current corpus, building one when needed.

    Order: cheap fingerprint on the current pointer (no projection), then the
    content digest (pointer fingerprint refreshed in place), then a fresh
    legacy ``.atlas-index/`` generation when the new location has none (read
    only), else build under the lock and publish atomically. Raises
    :class:`IndexLocationError` (unsafe path), :class:`IndexNotBuilt`
    (incomplete corpus), :class:`index_publish.IndexBusy`, ``OSError`` or
    ``sqlite3.Error``; callers fall back to a temporary index.
    """
    root = index_root(store)
    base = index_location.indexes_base(store)
    _reject_symlink_escape(base, root)
    fingerprint = cheap_fingerprint(store, schema)
    hit = _fresh_new(root, fingerprint=fingerprint)
    if hit is not None:
        return Freshness(hit, False)
    if projection is None:
        projection = project_store(store, schema, allow_partial=False)
    if not projection.get("complete"):
        raise IndexNotBuilt("incomplete")
    digest = str(projection["corpus_digest"])
    hit = _fresh_new(root, digest=digest)
    if hit is not None:
        pointer = {**hit.pointer, "cheap_fingerprint": fingerprint}
        try:
            _write_pointer(root, pointer)
        except OSError:
            pass
        return Freshness(Generation(hit.db, pointer, False), False)
    current = _read_pointer(root / CURRENT_NAME)
    if allow_legacy and not (current and current.get("complete") and _pointer_db(root, current.get("db"))):
        legacy = _read_pointer(legacy_root(store) / CURRENT_NAME)
        if legacy and legacy.get("complete") and legacy.get("corpus_digest") == digest:
            db = _legacy_pointer_db(store, legacy.get("db"))
            if db is not None:
                return Freshness(Generation(db, legacy, True), False)
    previous = str((current or {}).get("generation") or "") or None

    def build() -> Generation:
        if guard_ignore:
            ensure_indexes_ignored(store)
        gen_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        tmp_dir = root / f"{index_publish.TMP_PREFIX}{gen_id}"
        dest = root / "generations" / gen_id
        _reject_symlink_escape(base, tmp_dir)
        _reject_symlink_escape(base, dest)
        tmp_dir.mkdir(parents=True)
        try:
            inserted = _write_sqlite(tmp_dir / DB_NAME, projection["pages"], digest)
            index_publish.publish_dir(tmp_dir, dest)
        except BaseException:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        pointer = {
            "generation": gen_id,
            "corpus_digest": digest,
            "cheap_fingerprint": fingerprint,
            "db": (dest / DB_NAME).relative_to(root).as_posix(),
            "complete": True,
            "count": inserted,
        }
        _write_pointer(root, pointer)
        _prune(root, gen_id)
        return Generation(dest / DB_NAME, pointer, False)

    gen, built = index_publish.locked_build(
        root, lambda: _fresh_new(root, digest=digest), build, wait=wait
    )
    return Freshness(gen, built, previous if built else None)


def publish_generation(
    store: Path,
    schema: dict[str, Any] | None,
    focused: bool,
    projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish a complete generation of a recall-enabled store under the project-owned root.

    Never reads from or writes to the legacy in-store ``.atlas-index/``.
    """
    if focused:
        raise IndexError_("focused compile cannot publish a complete generation")
    if not recall_enabled(schema):
        return {"published": False, "reason": "recall_disabled"}
    return publish_fts5(store, schema, projection=projection)


def publish_fts5(
    store: Path,
    schema: dict[str, Any] | None,
    projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make the new-location fts5 index fresh (any store); legacy is never used or written."""
    where = index_location.describe(store, DRIVER_TYPE)
    try:
        fresh = ensure_fresh(store, schema, projection=projection, allow_legacy=False)
    except IndexNotBuilt as e:
        return {"published": False, "reason": e.reason, **where}
    pointer = fresh.generation.pointer
    out = {
        "published": True,
        "reused": not fresh.rebuilt,
        "generation": pointer.get("generation"),
        "corpus_digest": pointer.get("corpus_digest"),
        "cheap_fingerprint": pointer.get("cheap_fingerprint"),
        "db": pointer.get("db"),
        "complete": True,
        "count": pointer.get("count"),
        **where,
    }
    if fresh.previous:
        out["previous_generation"] = fresh.previous
    return out


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
