"""Structural graph lookups over the shared page projection.

Read-only: pages come from a published recall generation when its cheap
fingerprint matches, otherwise from an in-memory projection of the current
tree. Nothing is written to the store.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterable

from . import recall_index
from .overlay import merge_overlays
from .projection import ProjectedPage, ProjectionError, normalise_target, project_store
from .retrieve import EXIT_FIELDS, adjacent, build_incoming, is_exit_page, is_exit_value, is_visible
from .schema import load_schema

EXTERNAL_PREFIX = "atlas://"
MAX_HOPS = 3
DEFAULT_MAX_NODES = 200
DEFAULT_MAX_EDGES = 500
NANOGRAPH_GRAMMAR = "1.3.0"
NANOGRAPH_STRING_PROPS = (
    "type",
    "kva",
    "status",
    "work_id",
    "star_kind",
    "kva_role",
    "origin",
    "sensitivity",
)


class GraphError(ValueError):
    """Usage or data error; the CLI maps it to exit 2."""


# --- data source -----------------------------------------------------------


def load_source(root: Path, allow_partial: bool = False) -> dict[str, Any]:
    schema, err = load_schema(root)
    if schema is None:
        raise GraphError(err or "missing schema")
    merged, critical, _ = merge_overlays(schema, root)
    if critical:
        raise GraphError("; ".join(i["msg"] for i in critical))
    pages: list[ProjectedPage] | None = None
    source: dict[str, Any] = {
        "schema": merged,
        "generation": None,
        "fast_path": False,
        "complete": True,
        "omitted": [],
    }
    fast_gen = recall_index.find_generation(root, schema=merged, fast_path=True)
    if fast_gen is not None:
        try:
            pages = recall_index.pages_from_db(fast_gen.db)
        except sqlite3.Error:
            pages = None
    if pages is not None and fast_gen is not None:
        cur = fast_gen.pointer
        source["generation"] = cur.get("generation")
        source["corpus_digest"] = str(cur.get("corpus_digest") or "")
        source["fast_path"] = True
        source.update(recall_index.index_location.describe(root, "fts5"))
        if fast_gen.legacy:
            source["warnings"] = [recall_index.legacy_warning(root)]
    else:
        try:
            projection = project_store(root, merged, allow_partial=allow_partial)
        except ProjectionError as e:
            raise GraphError(str(e)) from e
        pages = projection["pages"]
        source["corpus_digest"] = str(projection["corpus_digest"])
        source["complete"] = bool(projection["complete"])
        source["omitted"] = list(projection["omitted"])
    source["pages"] = sorted((p for p in pages if p.role != "log"), key=lambda p: p.page_id)
    return source


def relation_vocabulary(schema: dict[str, Any] | None) -> list[str]:
    relations = (schema or {}).get("relations")
    kinds = relations.get("recommended_kinds") if isinstance(relations, dict) else None
    if not isinstance(kinds, list):
        return []
    return sorted({str(k).strip() for k in kinds if isinstance(k, str) and str(k).strip()})


# --- normalisation and filters ----------------------------------------------


def normalise_text(value: Any) -> str | None:
    """Comparison text for a scalar: booleans as true/false, numbers via str()."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    return None


def scalar_fields(meta: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in meta.items():
        text = normalise_text(value)
        if text is not None:
            out[str(key)] = text
    return out


def parse_where(raw: list[str] | tuple[str, ...]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in raw or ():
        if "=" not in item:
            raise GraphError(f"malformed --where {item!r}: expected field=value")
        field, value = item.split("=", 1)
        field = field.strip()
        if not field:
            raise GraphError(f"malformed --where {item!r}: empty field name")
        out.append((field, value.strip()))
    return out


def where_matches(meta: dict[str, Any], wheres: list[tuple[str, str]]) -> bool:
    for field, want in wheres:
        if field not in meta:
            return False
        value = meta[field]
        values = value if isinstance(value, list) else [value]
        if not any(normalise_text(v) == want for v in values):
            return False
    return True


def asks_for_exit(wheres: list[tuple[str, str]]) -> bool:
    return any(field in EXIT_FIELDS and is_exit_value(value) for field, value in wheres)


def _bool_or_none(value: Any) -> bool | None:
    text = normalise_text(value)
    if text is None:
        return None
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def _path_prefix_matches(path: str, prefix: str | None) -> bool:
    if not prefix:
        return True
    want = normalise_target(prefix).strip("/")
    if not want:
        return True
    hay = path.replace("\\", "/").lstrip("/")
    return hay == want or hay.startswith(want + "/")


# --- records ---------------------------------------------------------------


def node_record(page: ProjectedPage) -> dict[str, Any]:
    meta = page.meta
    record: dict[str, Any] = {
        "path": page.path,
        "type": normalise_text(meta.get("type")) or "",
        "title": page.title,
        "fields": scalar_fields(meta),
    }
    for key in ("kva", "status", "work_id"):
        text = normalise_text(meta.get(key))
        if text:
            record[key] = text
    growth = _bool_or_none(meta.get("growth"))
    if growth is not None:
        record["growth"] = growth
    return record


def all_edges(pages: list[ProjectedPage]) -> list[dict[str, Any]]:
    """Every authored relates_to edge, resolved or not, in authored direction."""
    ids = {p.page_id for p in pages}
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for page in pages:
        for edge in page.edges:
            target = normalise_target(edge.get("target") or "")
            if not target:
                continue
            kind = str(edge.get("kind") or "related")
            key = (page.page_id, target, kind)
            if key in seen:
                continue
            seen.add(key)
            record: dict[str, Any] = {
                "from": page.page_id,
                "to": target,
                "kind": kind,
                "resolved": target in ids,
            }
            if target.startswith(EXTERNAL_PREFIX):
                record["external"] = True
            out.append(record)
    out.sort(key=lambda e: (e["from"], e["to"], e["kind"]))
    return out


def _resolve_page(pages_by: dict[str, ProjectedPage], page: str) -> ProjectedPage:
    key = normalise_target(page).lstrip("/")
    found = pages_by.get(key)
    if found is None:
        raise GraphError(f"unknown page {page!r} (expected a store-relative path)")
    return found


# --- verbs -----------------------------------------------------------------


def exit_state(page: ProjectedPage) -> str | None:
    """The page's exit state (first of kva, status), or ``None`` for a live page."""
    for key in EXIT_FIELDS:
        value = page.meta.get(key)
        if is_exit_value(value):
            return str(value).strip().lower()
    return None


def check_anchor(page: ProjectedPage, include_exits: bool, *, label: str = "starting page") -> None:
    """Exit-state rule for anchors: refuse an exit-state page unless ``include_exits``."""
    if include_exits:
        return
    state = exit_state(page)
    if state is not None:
        raise GraphError(
            f"{label} {page.page_id} is in exit state {state}; pass --include-exits to traverse from it"
            if label == "starting page"
            else f"{label} {page.page_id} is in exit state {state}; pass --include-exits to include it"
        )


def check_seed(pages: list[ProjectedPage], seed: str, include_exits: bool) -> ProjectedPage:
    """Resolve a neighbours starting page and apply the exit-state rule (``GraphError``: exit 2)."""
    page = _resolve_page({p.page_id: p for p in pages}, seed)
    check_anchor(page, include_exits)
    return page


def query_nodes(
    pages: list[ProjectedPage],
    *,
    wheres: list[tuple[str, str]],
    path_prefix: str | None = None,
    include_exits: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    if limit is not None and limit < 1:
        raise GraphError("--limit must be at least 1")
    reveal = include_exits or asks_for_exit(wheres)
    nodes = [
        node_record(p)
        for p in pages
        if is_visible(p, reveal)
        and _path_prefix_matches(p.path, path_prefix)
        and where_matches(p.meta, wheres)
    ]
    nodes.sort(key=lambda n: n["path"])
    truncated = False
    if limit is not None and len(nodes) > limit:
        nodes = nodes[:limit]
        truncated = True
    return {"nodes": nodes, "truncated": truncated}


def query_edges(
    pages: list[ProjectedPage],
    *,
    from_page: str | None = None,
    to_page: str | None = None,
    kinds: list[str] | tuple[str, ...] = (),
    include_exits: bool = False,
) -> dict[str, Any]:
    by_id = {p.page_id: p for p in pages}
    src = None
    if from_page:
        src_page = _resolve_page(by_id, from_page)
        check_anchor(src_page, include_exits)
        src = src_page.page_id
    dst = normalise_target(to_page).lstrip("/") if to_page else None
    if dst is not None and dst in by_id:
        check_anchor(by_id[dst], include_exits, label="page")
    kind_set = set(kinds or ())
    out: list[dict[str, Any]] = []
    for edge in all_edges(pages):
        if src is not None and edge["from"] != src:
            continue
        if dst is not None and edge["to"] != dst:
            continue
        if kind_set and edge["kind"] not in kind_set:
            continue
        if not include_exits:
            ends = [by_id.get(edge["from"]), by_id.get(edge["to"])]
            if any(p is not None and is_exit_page(p) for p in ends):
                continue
        out.append(edge)
    return {"edges": out}


def query_neighbours(
    pages: list[ProjectedPage],
    seed: str,
    *,
    kinds: list[str] | tuple[str, ...] = (),
    direction: str = "both",
    hops: int = 1,
    wheres: list[tuple[str, str]] | None = None,
    max_nodes: int | None = DEFAULT_MAX_NODES,
    max_edges: int | None = DEFAULT_MAX_EDGES,
    include_exits: bool = False,
    adjacency: Callable[[str, str, frozenset[str]], list[tuple[str, str, str]]] | None = None,
) -> dict[str, Any]:
    """Bounded BFS. ``adjacency(page_id, direction, kinds)`` may replace the
    in-memory edge lookup (drivers); it returns (other, kind, outgoing|incoming).
    ``None`` leaves a cap unbounded; a cap below 1 raises ``GraphError``."""
    if direction not in ("in", "out", "both"):
        raise GraphError("--direction must be in, out or both")
    if hops < 1 or hops > MAX_HOPS:
        raise GraphError(f"--hops must be between 1 and {MAX_HOPS}")
    if max_nodes is not None and max_nodes < 1:
        raise GraphError("--max-nodes must be at least 1")
    if max_edges is not None and max_edges < 1:
        raise GraphError("--max-edges must be at least 1")
    wheres = wheres or []
    by_id = {p.page_id: p for p in pages}
    seed_page = _resolve_page(by_id, seed)
    check_anchor(seed_page, include_exits)
    reveal = include_exits or asks_for_exit(wheres)
    kind_set = frozenset(kinds or ())
    if adjacency is None:
        incoming = build_incoming(pages)

        def adjacency(page_id: str, direction: str, kinds: frozenset[str]) -> list[tuple[str, str, str]]:
            return adjacent(by_id[page_id], incoming, direction=direction, kinds=kinds)

    hop_of: dict[str, int] = {seed_page.page_id: 0}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str, str]] = set()
    truncated = False
    level = [seed_page.page_id]
    hop = 0
    while level and hop < hops and not truncated:
        next_level: list[str] = []
        for current in sorted(level):
            steps = sorted(
                adjacency(current, direction, kind_set),
                key=lambda s: (s[0], s[1], s[2]),
            )
            for other, kind, step_dir in steps:
                other_page = by_id.get(other)
                if other_page is None or not is_visible(other_page, reveal):
                    continue
                if step_dir == "outgoing":
                    key = (current, other, kind)
                else:
                    key = (other, current, kind)
                is_new_node = other not in hop_of
                if is_new_node and where_matches(other_page.meta, wheres):
                    if max_nodes is not None and len(nodes) >= max_nodes:
                        truncated = True
                        break
                if key not in edge_keys:
                    if max_edges is not None and len(edges) >= max_edges:
                        truncated = True
                        break
                    edge_keys.add(key)
                    edges.append(
                        {
                            "from": key[0],
                            "to": key[1],
                            "kind": kind,
                            "direction": "out" if step_dir == "outgoing" else "in",
                            "hop": hop + 1,
                        }
                    )
                if is_new_node:
                    hop_of[other] = hop + 1
                    next_level.append(other)
                    if where_matches(other_page.meta, wheres):
                        nodes.append({**node_record(other_page), "hop": hop + 1})
            if truncated:
                break
        level = next_level
        hop += 1
    nodes.sort(key=lambda n: (n["hop"], n["path"]))
    edges.sort(key=lambda e: (e["hop"], e["from"], e["to"], e["kind"]))
    return {
        "seed": seed_page.page_id,
        "direction": direction,
        "hops": hops,
        "nodes": nodes,
        "edges": edges,
        "truncated": truncated,
    }


# --- export ----------------------------------------------------------------


def _dump_line(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _dump_doc(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def edge_type_name(kind: str) -> str:
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", kind) if p]
    name = "".join(p[:1].upper() + p[1:] for p in parts) or "Related"
    if name[0].isdigit():
        name = "K" + name
    return name


_EDGE_TYPE_IDENT = re.compile(r"[A-Z][0-9A-Za-z]*")


def _edge_type_suffix(kind: str, external: bool) -> str:
    key = kind + ("\x00external" if external else "")
    return "X" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def edge_type_map(page_kinds: Iterable[str], external_kinds: Iterable[str]) -> dict[tuple[str, bool], str]:
    """Deterministic, collision-free nanograph edge type per ``(kind, is_external)``.

    The base name is the PascalCase kind (plus ``External`` for external
    targets). When several pairs share a base name, every member of that group
    gets ``X`` + the first 8 hex characters of sha256(kind, plus
    ``"\\x00external"`` for external targets); unique names are left unchanged.
    """
    pairs = sorted({(k, False) for k in page_kinds} | {(k, True) for k in external_kinds})
    base = {pair: edge_type_name(pair[0]) + ("External" if pair[1] else "") for pair in pairs}
    claims: dict[str, int] = {}
    for name in base.values():
        claims[name] = claims.get(name, 0) + 1
    out = {
        pair: name + _edge_type_suffix(*pair) if claims[name] > 1 else name
        for pair, name in base.items()
    }
    owner: dict[str, tuple[str, bool]] = {}
    for pair, name in out.items():
        if not _EDGE_TYPE_IDENT.fullmatch(name):
            raise GraphError(f"edge type {name!r} for relation kind {pair[0]!r} is not a valid identifier")
        if name in owner:
            raise GraphError(
                f"relation kinds {owner[name][0]!r} and {pair[0]!r} still collide on edge type {name} "
                "after disambiguation"
            )
        owner[name] = pair
    return out


def source_edge_type_map(
    source: dict[str, Any], edges: list[dict[str, Any]] | None = None
) -> dict[tuple[str, bool], str]:
    """The edge type map ``export_nanograph`` uses for ``source``."""
    if edges is None:
        edges = all_edges(source["pages"])
    page_kinds = set(relation_vocabulary(source.get("schema"))) | {e["kind"] for e in edges}
    external_kinds = {e["kind"] for e in edges if e.get("external")}
    return edge_type_map(page_kinds, external_kinds)


def check_out_dir(root: Path, out: str) -> Path:
    out_dir = Path(out).expanduser().resolve()
    try:
        out_dir.relative_to(root.resolve())
    except ValueError:
        return out_dir
    raise GraphError(f"--out {out_dir} is inside the store root; choose a directory outside it")


def export_json(source: dict[str, Any], out_dir: Path) -> list[str]:
    pages = source["pages"]
    doc = {
        "version": 1,
        "corpus_digest": source["corpus_digest"],
        "nodes": [{**node_record(p), "description": p.description} for p in pages],
        "edges": all_edges(pages),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "graph.json").write_text(_dump_doc(doc), encoding="utf-8")
    return ["graph.json"]


def _page_data(page: ProjectedPage) -> dict[str, Any]:
    meta = page.meta
    description = page.description or None
    data: dict[str, Any] = {
        "slug": page.page_id,
        "title": page.title,
        "description": description,
        "body": page.body,
        "text": f"{page.title}\n{page.description}\n{page.body}",
        "role": page.role,
        "growth": _bool_or_none(meta.get("growth")),
        "consolidation": _bool_or_none(meta.get("consolidation")),
    }
    for key in NANOGRAPH_STRING_PROPS:
        data[key] = normalise_text(meta.get(key)) or None
    return data


def nanograph_schema(edge_types: list[tuple[str, str]]) -> str:
    lines = [
        "node Page {",
        "  slug: String @key",
        "  title: String @index",
        "  description: String?",
        "  body: String",
        "  text: String @index",
        "  role: String",
        "  growth: Bool?",
        "  consolidation: Bool?",
    ]
    lines += [f"  {prop}: String?" for prop in NANOGRAPH_STRING_PROPS]
    lines += ["}", "", "node External {", "  slug: String @key", "}"]
    if edge_types:
        lines.append("")
        lines += [f"edge {name}: Page -> {target}" for name, target in edge_types]
    return "\n".join(lines) + "\n"


def export_nanograph(source: dict[str, Any], out_dir: Path) -> tuple[list[str], dict[str, Any]]:
    pages = source["pages"]
    edges = all_edges(pages)
    kinds_present = {e["kind"] for e in edges}
    type_map = source_edge_type_map(source, edges)
    edge_types = sorted(
        (name, "External" if external else "Page") for (_, external), name in type_map.items()
    )

    externals = sorted({e["to"] for e in edges if e.get("external")})
    edge_lines: set[tuple[str, str, str]] = set()
    unresolved: list[dict[str, Any]] = []
    per_kind: dict[str, int] = {}
    for e in edges:
        if e.get("external"):
            name = type_map[(e["kind"], True)]
        elif e["resolved"]:
            name = type_map[(e["kind"], False)]
        else:
            unresolved.append(e)
            continue
        if (name, e["from"], e["to"]) not in edge_lines:
            edge_lines.add((name, e["from"], e["to"]))
            per_kind[e["kind"]] = per_kind.get(e["kind"], 0) + 1

    seed: list[str] = [_dump_line({"type": "Page", "data": _page_data(p)}) for p in pages]
    seed += [_dump_line({"type": "External", "data": {"slug": slug}}) for slug in externals]
    seed += [_dump_line({"edge": n, "from": f, "to": t}) for n, f, t in sorted(edge_lines)]

    receipt = {
        "format": "nanograph",
        "nanograph_schema_grammar": NANOGRAPH_GRAMMAR,
        "corpus_digest": source["corpus_digest"],
        "complete": source["complete"],
        "omitted": source["omitted"],
        "pages": len(pages),
        "externals": len(externals),
        "edges": len(edge_lines),
        "edges_per_kind": dict(sorted(per_kind.items())),
        "kinds_present": sorted(kinds_present),
        "edge_types": [
            {"kind": kind, "external": external, "edge_type": name}
            for (kind, external), name in sorted(type_map.items())
        ],
        "unresolved": unresolved,
        "files": ["export-receipt.json", "schema.pg", "seed.jsonl"],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "schema.pg").write_text(nanograph_schema(edge_types), encoding="utf-8")
    (out_dir / "seed.jsonl").write_text("\n".join(seed) + "\n", encoding="utf-8")
    (out_dir / "export-receipt.json").write_text(_dump_doc(receipt), encoding="utf-8")
    return receipt["files"], receipt
