"""Current-tree page projection for SMR."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .frontmatter import FrontmatterError, read_page
from .paths import rel, store_root
from .recall_config import schema_version
from .schema import staging_dir_name

SKIP_TOP = frozenset({"templates", ".atlas-index", "mesh", "schema.d"})


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
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            parts = path.resolve().relative_to(root.resolve()).parts
        except ValueError:
            continue
        if parts and parts[0] in skip:
            continue
        if path.name == "SCHEMA.json":
            continue
        out.append(path)
    return out


def cheap_fingerprint(root: Path, schema: dict[str, Any] | None) -> str:
    """Path + size + mtime_ns over eligible files. Query gate, not content truth."""
    h = hashlib.sha256()
    for path in eligible_paths(root, schema):
        try:
            st = path.stat()
        except OSError:
            continue
        h.update(rel(root, path).encode("utf-8"))
        h.update(b"\0")
        h.update(str(st.st_size).encode("ascii"))
        h.update(b"\0")
        h.update(str(st.st_mtime_ns).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


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
    bytes_blob: list[bytes] = []
    for path in eligible_paths(root, schema):
        if not _contained(root, path):
            omitted.append({"path": rel(root, path), "reason": "root_escape"})
            continue
        try:
            raw = path.read_bytes()
        except OSError as e:
            omitted.append({"path": rel(root, path), "reason": f"unreadable:{e}"})
            continue
        digest = _sha256_bytes(raw)
        bytes_blob.append(digest.encode("ascii"))
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
    corpus_digest = _sha256_bytes(b"".join(sorted(bytes_blob)))
    return {
        "root": str(root),
        "schema_version": version,
        "corpus_digest": corpus_digest,
        "cheap_fingerprint": cheap_fingerprint(root, schema),
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
