"""Immutable recall index generations."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from .projection import ProjectedPage, cheap_fingerprint, project_store
from .recall_config import fts5_available, recall_enabled

INDEX_DIR = ".atlas-index"
CURRENT_NAME = "current.json"


class IndexError_(ValueError):
    pass


def index_root(store: Path) -> Path:
    return store / INDEX_DIR / "recall"


def current_pointer(store: Path) -> Path:
    return index_root(store) / CURRENT_NAME


def load_current(store: Path) -> dict[str, Any] | None:
    path = current_pointer(store)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


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


def publish_generation(
    store: Path,
    schema: dict[str, Any] | None,
    focused: bool,
    projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if focused:
        raise IndexError_("focused compile cannot publish a complete generation")
    if not recall_enabled(schema):
        return {"published": False, "reason": "recall_disabled"}
    if projection is None:
        projection = project_store(store, schema, allow_partial=False)
    if not projection.get("complete"):
        return {"published": False, "reason": "incomplete"}
    gen_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    dest_dir = index_root(store) / "generations" / gen_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    db_path = dest_dir / "projection.sqlite"
    fd, tmp_name = tempfile.mkstemp(prefix="atlas-recall-", suffix=".sqlite")
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
        "db": str(db_path.relative_to(store)),
        "complete": True,
        "count": inserted,
    }
    ptr_tmp = current_pointer(store).with_suffix(".json.tmp")
    ptr_tmp.parent.mkdir(parents=True, exist_ok=True)
    ptr_tmp.write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
    os.replace(ptr_tmp, current_pointer(store))
    return {"published": True, **pointer}


def _pointer_db(store: Path, raw: object) -> Path | None:
    text = str(raw or "").strip()
    if not text or Path(text).is_absolute() or Path(text).anchor:
        return None
    candidate = (store / text).resolve()
    try:
        candidate.relative_to(index_root(store).resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def matching_generation(store: Path, digest: str) -> Path | None:
    cur = load_current(store)
    if not cur or cur.get("corpus_digest") != digest or not cur.get("complete"):
        return None
    return _pointer_db(store, cur.get("db"))


def matching_fast_path(store: Path, schema: dict[str, Any] | None) -> Path | None:
    cur = load_current(store)
    if not cur or not cur.get("complete") or not cur.get("cheap_fingerprint"):
        return None
    if cur.get("cheap_fingerprint") != cheap_fingerprint(store, schema):
        return None
    return _pointer_db(store, cur.get("db"))


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
    uri = f"file:{path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def build_ephemeral(projection: dict[str, Any]) -> Path:
    fd, name = tempfile.mkstemp(prefix="atlas-recall-eph-", suffix=".sqlite")
    os.close(fd)
    path = Path(name)
    _write_sqlite(path, projection["pages"], projection["corpus_digest"])
    return path
