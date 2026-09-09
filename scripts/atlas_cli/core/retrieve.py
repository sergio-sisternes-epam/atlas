"""Bounded Retrieve: page evidence and directed graph neighbourhood."""

from __future__ import annotations

from collections import deque
from typing import Any

from .projection import ProjectedPage

EXIT_STATES = frozenset({"terminated", "deprecated", "superseded"})


def _is_exit(page: ProjectedPage) -> bool:
    for key in ("kva", "status"):
        if str(page.meta.get(key) or "").strip().lower() in EXIT_STATES:
            return True
    return False


def _visible(page: ProjectedPage, include_exits: bool) -> bool:
    if page.role == "log":
        return False
    if not include_exits and _is_exit(page):
        return False
    return True


def build_incoming(pages: list[ProjectedPage]) -> dict[str, list[tuple[str, str]]]:
    incoming: dict[str, list[tuple[str, str]]] = {}
    ids = {p.page_id for p in pages}
    for page in pages:
        for edge in page.edges:
            target = edge.get("target") or ""
            if target not in ids:
                continue
            incoming.setdefault(target, []).append((page.page_id, edge.get("kind") or "related"))
    return incoming


def neighbourhood(
    pages: list[ProjectedPage],
    seeds: list[str],
    max_hops: int,
    max_nodes: int,
    max_edges: int,
    include_exits: bool,
) -> dict[str, Any]:
    by_id = {p.page_id: p for p in pages}
    incoming = build_incoming(pages)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    truncated = False
    frontier: deque[tuple[str, int]] = deque(
        (sid, 0) for sid in seeds if sid in by_id
    )
    seen = set(seeds)
    while frontier:
        current, hop = frontier.popleft()
        page = by_id.get(current)
        if page is None or not _visible(page, include_exits):
            continue
        if current not in nodes:
            if max_nodes and len(nodes) >= max_nodes:
                truncated = True
                break
            nodes[current] = {
                "path": page.path,
                "title": page.title,
                "type": str(page.meta.get("type") or ""),
                "hop": hop,
            }
        if hop >= max_hops:
            continue
        outgoing = [(e.get("target") or "", e.get("kind") or "related", "outgoing") for e in page.edges]
        inbound = [(src, kind, "incoming") for src, kind in incoming.get(current, [])]
        for target, kind, direction in [*outgoing, *inbound]:
            if not target or target not in by_id:
                continue
            if max_edges and len(edges) >= max_edges:
                truncated = True
                break
            edges.append(
                {
                    "from": current if direction == "outgoing" else target,
                    "to": target if direction == "outgoing" else current,
                    "kind": kind,
                    "direction": direction,
                    "hop": hop + 1,
                }
            )
            if target in by_id and target not in seen:
                seen.add(target)
                frontier.append((target, hop + 1))
        if truncated:
            break
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "truncated": truncated,
        "max_hops": max_hops,
    }


def evidence(page: ProjectedPage, max_bytes: int) -> dict[str, Any]:
    body = page.body
    truncated = False
    encoded = body.encode("utf-8")
    if max_bytes and len(encoded) > max_bytes:
        body = encoded[:max_bytes].decode("utf-8", errors="ignore")
        truncated = True
    return {
        "path": page.path,
        "title": page.title,
        "type": str(page.meta.get("type") or ""),
        "body": body,
        "truncated": truncated,
        "relates_to": page.edges[:5],
    }
