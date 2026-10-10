"""Current-tree page projection for SMR.

Freshness inputs: an index generation is current only when its recorded
corpus digest equals :func:`content_digest` of the store, which covers every
eligible Markdown file (relative path plus sha256) *and* the projection inputs
(:func:`projection_inputs`): the bytes of SCHEMA.json / CONTRACT.json and the
``schema.d/*.json`` overlays that ``merge_overlays`` reads (the same
enumeration, symlinks followed), which decide how pages are parsed (schema
version, relation vocabulary, recall field config), plus
:data:`PROJECTION_VERSION`. :func:`project_store` records the same digest, and
:func:`cheap_fingerprint` covers the same files by stat (of a link's target), so every caller
(fts5, nanograph, the graph fast path, legacy reuse, ``index show/status``)
agrees.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .frontmatter import FrontmatterError, read_page
from .overlay import overlay_files
from .paths import CONTRACT_NAME, SCHEMA_NAME, rel, store_root
from .recall_config import schema_version
from .schema import staging_dir_name

# ".atlas" holds project-owned indexes (and mounts) when a store is its own project root.
SKIP_TOP = frozenset({"templates", ".atlas-index", ".atlas", "mesh", "schema.d", ".git"})
OVERLAY_DIR = "schema.d"
# Bump whenever projection logic (parsing, roles, edges, eligibility) changes:
# it is part of the corpus digest, so every existing generation rebuilds once.
PROJECTION_VERSION = 2


class ProjectionError(ValueError):
    pass


@dataclass
class ProjectedPage:
    page_id: str
    path: str
    role: str
    digest: str
    meta: dict[str, Any]
    body: str
    title: str
    description: str
    edges: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _contained(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def eligible_paths(root: Path, schema: dict[str, Any] | None) -> list[Path]:
    staging = staging_dir_name(schema)
    skip = set(SKIP_TOP) | {staging}
    out: list[Path] = []
    root_r = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        try:
            parts = Path(dirpath).resolve().relative_to(root_r).parts
        except ValueError:
            dirnames[:] = []
            continue
        if parts and parts[0] in skip:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in skip]
        for name in filenames:
            if not name.endswith(".md"):
                continue
            path = Path(dirpath) / name
            if path.is_file():
                out.append(path)
    return sorted(out)


def projection_inputs(root: Path) -> list[Path]:
    """Store files besides pages that decide how pages are projected (sorted, existing only).

    SCHEMA.json / CONTRACT.json and the overlays :func:`overlay.overlay_files`
    lists (the very list :func:`overlay.merge_overlays` reads, so a symlinked
    ``schema.d`` or overlay file is included): they carry the schema version,
    relation vocabulary and recall field config that :func:`project_store`
    and its callers read.
    """
    out = [root / name for name in (CONTRACT_NAME, SCHEMA_NAME) if os.path.lexists(root / name)]
    out.extend(overlay_files(root))
    return out


def _input_key(root: Path, path: Path) -> str:
    """Store-relative name of a projection input, without resolving symlinks."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return rel(root, path)


def _input_digest(path: Path) -> str:
    """sha256 of the bytes a reader gets (symlinks followed).

    A dangling or unreadable input gets a marker that is never a hex digest,
    keyed by the link text for a symlink so retargeting it still counts.
    """
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        pass
    try:
        return "unreadable-link:" + _sha256_bytes(os.readlink(path).encode("utf-8", "surrogateescape"))
    except OSError:
        return "unreadable"


def _input_entries(root: Path) -> list[tuple[str, str]]:
    entries = [("\0projection-version", str(PROJECTION_VERSION))]
    for path in projection_inputs(root):
        entries.append(("\0input:" + _input_key(root, path), _input_digest(path)))
    return entries


def inputs_digest(root: Path) -> str:
    """sha256 over the projection inputs and :data:`PROJECTION_VERSION` alone."""
    return _corpus_digest(_input_entries(root))


def cheap_fingerprint(root: Path, schema: dict[str, Any] | None, paths: list[Path] | None = None) -> str:
    """Path + size + mtime_ns over eligible files and the projection inputs.

    A fast pre-check only: a mismatch proves an index stale, but a match never
    proves it fresh (a same-length edit can keep its mtime). Freshness is
    decided by :func:`content_digest`.
    """
    h = hashlib.sha256()
    h.update(f"projection-version {PROJECTION_VERSION}\n".encode("ascii"))
    inputs = [(_input_key(root, p), p) for p in projection_inputs(root)]
    pages = [(rel(root, p), p) for p in (eligible_paths(root, schema) if paths is None else paths)]
    for key, path in [*inputs, *pages]:
        # stat() follows symlinks, so an edited link target changes the fingerprint.
        try:
            st = path.stat()
        except OSError:
            try:
                st = path.lstat()
            except OSError:
                continue
        h.update(key.encode("utf-8"))
        h.update(b"\0")
        h.update(str(st.st_size).encode("ascii"))
        h.update(b"\0")
        h.update(str(st.st_mtime_ns).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def _corpus_digest(entries: list[tuple[str, str]]) -> str:
    """sha256 over sorted ``relative path NUL sha256`` lines (renames change it too).

    Callers pass page entries plus :func:`_input_entries` (whose NUL-prefixed
    keys can never collide with a page path).
    """
    h = hashlib.sha256()
    for path, digest in sorted(entries):
        h.update(path.encode("utf-8"))
        h.update(b"\0")
        h.update(digest.encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def content_digest(root: Path, schema: dict[str, Any] | None, paths: list[Path] | None = None) -> str | None:
    """Corpus digest from raw page and projection-input bytes, without parsing (equals ``project_store``'s).

    Returns ``None`` when an eligible file is unreadable or escapes the root:
    such a corpus is incomplete and never matches a complete generation.
    """
    entries: list[tuple[str, str]] = _input_entries(root)
    for path in eligible_paths(root, schema) if paths is None else paths:
        if not _contained(root, path):
            return None
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        entries.append((rel(root, path), _sha256_bytes(raw)))
    return _corpus_digest(entries)


def normalise_target(target: str) -> str:
    """Store-relative relates_to target with any leading ``./`` removed."""
    text = str(target or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _edges_from_meta(meta: dict[str, Any]) -> list[dict[str, str]]:
    raw = meta.get("relates_to") or []
    edges: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return edges
    for item in raw:
        if not isinstance(item, dict):
            continue
        target = str(item.get("path") or "").strip()
        if not target:
            continue
        kind = str(item.get("kind") or item.get("role") or "related").strip() or "related"
        edges.append({"target": target, "kind": kind, "direction": "outgoing"})
    return edges


def project_store(
    root: Path,
    schema: dict[str, Any] | None,
    allow_partial: bool = False,
) -> dict[str, Any]:
    version = schema_version(schema)
    pages: list[ProjectedPage] = []
    omitted: list[dict[str, str]] = []
    entries: list[tuple[str, str]] = _input_entries(root)
    paths = eligible_paths(root, schema)
    for path in paths:
        if not _contained(root, path):
            omitted.append({"path": rel(root, path), "reason": "root_escape"})
            continue
        try:
            raw = path.read_bytes()
        except OSError as e:
            omitted.append({"path": rel(root, path), "reason": f"unreadable:{e}"})
            continue
        digest = _sha256_bytes(raw)
        entries.append((rel(root, path), digest))
        role = "navigation" if path.name == "index.md" else "concept"
        if path.name == "log.md":
            role = "log"
        try:
            meta, body = read_page(path, version)
        except FrontmatterError as e:
            omitted.append({"path": rel(root, path), "reason": f"parse:{e}"})
            continue
        except OSError as e:
            omitted.append({"path": rel(root, path), "reason": f"unreadable:{e}"})
            continue
        page_id = rel(root, path)
        pages.append(
            ProjectedPage(
                page_id=page_id,
                path=page_id,
                role=role,
                digest=digest,
                meta=meta if isinstance(meta, dict) else {},
                body=body,
                title=str((meta or {}).get("title") or path.stem),
                description=str((meta or {}).get("description") or ""),
                edges=_edges_from_meta(meta if isinstance(meta, dict) else {}),
            )
        )
    if omitted and not allow_partial:
        reasons = ", ".join(f"{row['path']} ({row['reason']})" for row in omitted[:8])
        raise ProjectionError(f"incomplete corpus: {reasons}")
    corpus_digest = _corpus_digest(entries)
    return {
        "root": str(root),
        "schema_version": version,
        "corpus_digest": corpus_digest,
        "cheap_fingerprint": cheap_fingerprint(root, schema, paths),
        "complete": not omitted,
        "omitted": omitted,
        "pages": pages,
    }


def pointer_value(meta: dict[str, Any], pointer: str) -> Any:
    if not pointer or pointer == "/":
        return meta
    parts = [p for p in pointer.split("/") if p]
    cur: Any = meta
    for part in parts:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def store_root_resolved(root: str | None) -> Path:
    return store_root(root)


def pages_by_id(projection: dict[str, Any]) -> dict[str, ProjectedPage]:
    return {p.page_id: p for p in projection["pages"]}


def dump_projection_meta(projection: dict[str, Any]) -> dict[str, Any]:
    return {
        "corpus_digest": projection["corpus_digest"],
        "complete": projection["complete"],
        "count": len(projection["pages"]),
        "omitted": projection["omitted"],
        "schema_version": projection["schema_version"],
    }
