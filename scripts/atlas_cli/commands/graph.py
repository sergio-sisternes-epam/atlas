"""atlas graph: structural lookups over the shared page projection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..core import graph as core
from ..core.paths import store_root


def _base(root: Path, verb: str, source: dict[str, Any] | None) -> dict[str, Any]:
    source = source or {}
    payload: dict[str, Any] = {
        "ok": True,
        "root": str(root),
        "verb": verb,
        "generation": source.get("generation"),
        "corpus_digest": source.get("corpus_digest"),
        "fast_path": bool(source.get("fast_path")),
        "complete": bool(source.get("complete", True)),
    }
    if source.get("omitted"):
        payload["omitted"] = source["omitted"]
    return payload


def _fail(root: Path, verb: str, error: str, as_json: bool) -> int:
    payload = {
        "ok": False,
        "root": str(root),
        "verb": verb,
        "error": error,
        "generation": None,
        "corpus_digest": None,
        "fast_path": False,
        "complete": False,
        "count": 0,
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(f"atlas graph {verb} — FAIL: {error}")
    return 2


def _emit(payload: dict[str, Any], as_json: bool, lines: list[str]) -> int:
    code = 0 if payload.get("complete") else 1
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
        return code
    for line in lines:
        print(line)
    tail = f"count={payload['count']} fast_path={str(payload['fast_path']).lower()}"
    if payload.get("truncated"):
        tail += " truncated=true"
    if not payload.get("complete"):
        tail += f" complete=false omitted={len(payload.get('omitted') or [])}"
    print(f"# {tail}")
    return code


def _run(
    root: str | None,
    verb: str,
    allow_partial: bool,
    as_json: bool,
    body: Callable[[Path, dict[str, Any]], tuple[dict[str, Any], list[str]]],
) -> int:
    r = store_root(root)
    try:
        source = core.load_source(r, allow_partial=allow_partial)
        extra, lines = body(r, source)
    except core.GraphError as e:
        return _fail(r, verb, str(e), as_json)
    payload = {**_base(r, verb, source), **extra}
    return _emit(payload, as_json, lines)


def _node_line(node: dict[str, Any]) -> str:
    prefix = f"hop={node['hop']} " if "hop" in node else ""
    state = " ".join(f"{k}={node[k]}" for k in ("kva", "status") if node.get(k))
    return f"{prefix}{node['path']}\t{node['type'] or '-'}\t{node['title']}" + (f"\t{state}" if state else "")


def _edge_line(edge: dict[str, Any]) -> str:
    prefix = f"hop={edge['hop']} " if "hop" in edge else ""
    line = f"{prefix}{edge['from']} -[{edge['kind']}]-> {edge['to']}"
    if "direction" in edge:
        line += f" ({edge['direction']})"
    if edge.get("external"):
        line += " external"
    elif edge.get("resolved") is False:
        line += " unresolved"
    return line


def run_nodes(
    root: str | None,
    where: tuple[str, ...],
    path_prefix: str | None,
    include_exits: bool,
    limit: int | None,
    allow_partial: bool,
    as_json: bool,
) -> int:
    try:
        wheres = core.parse_where(where)
    except core.GraphError as e:
        return _fail(store_root(root), "nodes", str(e), as_json)

    def body(_: Path, source: dict[str, Any]):
        result = core.query_nodes(
            source["pages"],
            wheres=wheres,
            path_prefix=path_prefix,
            include_exits=include_exits,
            limit=limit,
        )
        nodes = result["nodes"]
        extra = {"count": len(nodes), "nodes": nodes, "truncated": result["truncated"]}
        return extra, [_node_line(n) for n in nodes]

    return _run(root, "nodes", allow_partial, as_json, body)


def run_edges(
    root: str | None,
    from_page: str | None,
    to_page: str | None,
    all_edges: bool,
    kinds: tuple[str, ...],
    include_exits: bool,
    allow_partial: bool,
    as_json: bool,
) -> int:
    if all_edges and (from_page or to_page):
        return _fail(store_root(root), "edges", "--all cannot be combined with --from or --to", as_json)
    if not (all_edges or from_page or to_page):
        return _fail(store_root(root), "edges", "pass --from PAGE, --to PAGE or --all", as_json)

    def body(_: Path, source: dict[str, Any]):
        edges = core.query_edges(
            source["pages"],
            from_page=from_page,
            to_page=to_page,
            kinds=kinds,
            include_exits=include_exits,
        )["edges"]
        return {"count": len(edges), "edges": edges}, [_edge_line(e) for e in edges]

    return _run(root, "edges", allow_partial, as_json, body)


def run_neighbours(
    root: str | None,
    page: str,
    kinds: tuple[str, ...],
    direction: str,
    hops: int,
    where: tuple[str, ...],
    max_nodes: int,
    max_edges: int,
    include_exits: bool,
    allow_partial: bool,
    as_json: bool,
) -> int:
    if hops < 1 or hops > core.MAX_HOPS:
        return _fail(store_root(root), "neighbours", f"--hops must be between 1 and {core.MAX_HOPS}", as_json)
    try:
        wheres = core.parse_where(where)
    except core.GraphError as e:
        return _fail(store_root(root), "neighbours", str(e), as_json)

    def body(_: Path, source: dict[str, Any]):
        result = core.query_neighbours(
            source["pages"],
            page,
            kinds=kinds,
            direction=direction,
            hops=hops,
            wheres=wheres,
            max_nodes=max_nodes,
            max_edges=max_edges,
            include_exits=include_exits,
        )
        extra = {"count": len(result["nodes"]), **result}
        lines = [f"seed {result['seed']}"]
        lines += [_node_line(n) for n in result["nodes"]]
        lines += [_edge_line(e) for e in result["edges"]]
        return extra, lines

    return _run(root, "neighbours", allow_partial, as_json, body)


def run_export(
    root: str | None,
    fmt: str,
    out: str,
    allow_partial: bool,
    as_json: bool,
) -> int:
    r = store_root(root)
    try:
        out_dir = core.check_out_dir(r, out)
    except core.GraphError as e:
        return _fail(r, "export", str(e), as_json)

    def body(_: Path, source: dict[str, Any]):
        extra: dict[str, Any] = {"format": fmt, "out": str(out_dir), "count": len(source["pages"])}
        if fmt == "json":
            files = core.export_json(source, out_dir)
        else:
            files, receipt = core.export_nanograph(source, out_dir)
            extra["edges"] = receipt["edges"]
            extra["unresolved"] = len(receipt["unresolved"])
            extra["nanograph_schema_grammar"] = receipt["nanograph_schema_grammar"]
        extra["files"] = files
        return extra, [str(out_dir / f) for f in files]

    return _run(root, "export", allow_partial, as_json, body)
