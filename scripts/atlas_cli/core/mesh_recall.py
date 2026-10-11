"""Federated recall across a mesh (M11, M12): per-member search, tiered RRF.

Three separate concerns, three places:

- who is in the mesh: :mod:`mesh_scope` (members, ids, exclusions);
- how one store ranks text: each member's own ``recall run`` pipeline, in
  process, with its own engine preference (P23), recall profile and
  exclusions (P26), reading only its own index at its own path;
- how the member lists merge: :func:`fuse` here, a pure function.

No shared or combined text index is created (M7(4)). Excluded members are
never read; unmounted members are reported and never mounted. Pages with
``sensitivity: restricted`` leave each member's eligible set before ranking
(M7(2), M20), so hits, ranks and ``members[].hits`` never reveal them.

Fusion: tier 1 holds hits from lists produced by all-words matching, grep or
nanograph; tier 2 holds hits from an any-word retry (``match: any``). Order
by tier, then RRF score ``sum(1 / (k + rank))`` with a 1-based member rank,
then mesh row order, then path; truncate to ``limit``. Page ids are disjoint
across stores, so within a tier v1 ranks like an interleave; the formula is
kept so later per-member lists can join without a contract change.

Members follow :func:`mesh_scope.members`: only ``ok`` members are searched,
each with its index location pinned to its mesh row (project and row id).
``excluded``, ``unmounted`` and ``invalid`` members (a row outside the project,
with an invalid atlas id, a symlinked root, or whose lexical root overlaps
another row's root) are never read and are reported with their
status and, when ``mesh_scope`` gives one, a ``reason``. Mesh page walks do
not follow symlinks. Hit URIs are
:func:`mesh_scope.node_id` ids, so a path with ``%``, ``#``, ``?`` or
whitespace is percent-encoded and round-trips through
:func:`mesh_scope.parse_node_id`.
"""

from __future__ import annotations

import sys
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import index_location, mesh_scope, meshfile
from .paths import mesh_walks

SCOPES = meshfile.SCOPES
DEFAULT_SCOPE = "store"
DEFAULT_RRF_K = 60
OVERFETCH = 2
TIER_ALL = 1
TIER_ANY = 2

STATUS_ERROR = "error"
ERROR_MAX = 200

PROFILE_ERROR = "--profile cannot be used with --scope mesh: recall profiles are per store"
PARTIAL_ERROR = "--allow-partial cannot be used with --scope mesh: partial projection is a per-store profile option"
LIMIT_ERROR = "--limit with --scope mesh must be 0 (all hits) or a positive integer"
# What a member pipeline is asked for when the mesh limit is 0 (all): grep would read 0 as "none".
MEMBER_UNBOUNDED = sys.maxsize
RRF_K_STORE_ERROR = "--rrf-k applies only to --scope mesh; this request resolved to store scope"


class MeshRecallError(ValueError):
    """Invalid mesh recall input; callers map it to exit 2."""


# --- settings ------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    scope: str
    scope_source: str
    rrf_k: int
    rrf_k_source: str
    mesh: mesh_scope.Mesh | None = None


def parse_rrf_k(raw: Any) -> int:
    """``--rrf-k`` as an integer in 1..1000, else :class:`MeshRecallError`."""
    text = str(raw).strip()
    try:
        value = int(text, 10)
    except ValueError:
        value = None
    if value is None or not meshfile.valid_rrf_k(value):
        raise MeshRecallError(
            f"--rrf-k {raw!r} is not allowed; use an integer from {meshfile.RRF_K_MIN} to {meshfile.RRF_K_MAX}"
        )
    return value


def resolve_settings(root: Path, scope_flag: str | None, rrf_k_flag: Any = None) -> Settings:
    """Scope and k with their sources (M14): flag > top-level ``recall`` > built-in.

    With no ``--scope`` and no mesh (or a mesh file the strict loader rejects),
    the scope is ``store`` and nothing else changes: the store pipeline reports
    any mesh file problem exactly as it always has.

    A listed row root is a mesh even when the row is excluded, has an id that
    is not an index path, a ``subpath`` row or pathless. Discovery names the
    project without reading that store, so a project ``recall.scope: mesh``
    federates and reports the member excluded or invalid
    (``invalid_atlas_id``) instead of falling back to store recall. Explicit
    ``--scope store`` still searches that store alone: exclusion is a
    mesh-scope rule, and the flag overrides the project setting.
    """
    k_flag = parse_rrf_k(rrf_k_flag) if rrf_k_flag is not None else None
    scope = str(scope_flag).strip().lower() if scope_flag else None
    if scope is not None and scope not in SCOPES:
        raise MeshRecallError(f"--scope {scope_flag!r} is not allowed; allowed values: {', '.join(SCOPES)}")
    mesh: mesh_scope.Mesh | None = None
    if scope == "mesh":
        try:
            mesh = mesh_scope.discover(root)
        except mesh_scope.MeshScopeError as e:
            raise MeshRecallError(str(e)) from e
    elif scope is None:
        # Failure means this root is not a listed row. An excluded, invalid-id,
        # subpath or pathless root is listed, so it is not a failure and cannot
        # drop ``recall.scope: mesh`` into store recall.
        try:
            mesh = mesh_scope.discover(root)
        except mesh_scope.MeshScopeError:
            mesh = None
    block = (mesh.doc.get("recall") if mesh is not None else None) or {}
    if not isinstance(block, dict):
        block = {}
    if scope is not None:
        scope_source = "cli"
    elif block.get("scope") in SCOPES:
        scope, scope_source = block["scope"], "project"
    else:
        scope, scope_source = DEFAULT_SCOPE, "default"
    if k_flag is not None:
        rrf_k, k_source = k_flag, "cli"
    elif meshfile.valid_rrf_k(block.get("rrf_k")):
        rrf_k, k_source = block["rrf_k"], "project"
    else:
        rrf_k, k_source = DEFAULT_RRF_K, "default"
    if scope != "mesh":
        if k_flag is not None:
            raise MeshRecallError(RRF_K_STORE_ERROR)
        return Settings(scope, scope_source, rrf_k, k_source, None)
    return Settings(scope, scope_source, rrf_k, k_source, mesh)


# --- fusion --------------------------------------------------------------------


@dataclass
class RankedList:
    """One member's ranked hits (best first), as fusion sees them."""

    row: int
    atlas_id: str
    tier: int
    engine_used: str
    hits: list[dict[str, Any]] = field(default_factory=list)


def tier_of(match: Any) -> int:
    """Tier 2 only for an any-word retry; all-words, grep and nanograph lists are tier 1."""
    return TIER_ANY if str(match or "").strip().lower() == "any" else TIER_ALL


def fuse(lists: list[RankedList], k: int, limit: int) -> list[dict[str, Any]]:
    """Tiered RRF over member lists; deterministic; truncated to ``limit`` (0 = all)."""
    if not meshfile.valid_rrf_k(k):
        raise MeshRecallError(f"rrf_k {k!r} is not an integer from {meshfile.RRF_K_MIN} to {meshfile.RRF_K_MAX}")
    fused: dict[tuple[str, str], dict[str, Any]] = {}
    for ranked in lists:
        for rank, hit in enumerate(ranked.hits, 1):
            path = str(hit["path"])
            key = (ranked.atlas_id, path)
            entry = fused.get(key)
            if entry is None:
                entry = {
                    "atlas_id": ranked.atlas_id,
                    "path": path,
                    "uri": mesh_scope.node_id(ranked.atlas_id, path),
                    "title": str(hit.get("title") or Path(path).stem),
                    "member_rank": rank,
                    "tier": ranked.tier,
                    "rrf_score": 0.0,
                    "engine_used": ranked.engine_used,
                    "_row": ranked.row,
                }
                fused[key] = entry
            else:
                entry["member_rank"] = min(entry["member_rank"], rank)
                entry["tier"] = min(entry["tier"], ranked.tier)
                entry["_row"] = min(entry["_row"], ranked.row)
            entry["rrf_score"] += 1.0 / (k + rank)
    ordered = sorted(fused.values(), key=lambda h: (h["tier"], -h["rrf_score"], h["_row"], h["path"]))
    if limit and limit > 0:
        ordered = ordered[:limit]
    for hit in ordered:
        del hit["_row"]
    return ordered


# --- member search -------------------------------------------------------------


class MemberError(RuntimeError):
    """One member could not answer; the others still do."""


@dataclass
class MemberAnswer:
    hits: list[dict[str, Any]]
    match: str | None
    engine_requested: str | None
    engine_used: str | None
    driver_note: str | None


MemberSearch = Callable[..., MemberAnswer]


def withhold(meta: dict[str, Any]) -> bool:
    """The mesh pre-filter (M7(2), M20): restricted pages are never eligible."""
    return mesh_scope.is_restricted(meta)


def store_search(
    root: Path,
    query: str,
    limit: int,
    engine_override: str | None,
    include_exits: bool,
) -> MemberAnswer:
    """Run one member's own ``recall run`` pipeline in process (P23, P26 unchanged).

    ``limit`` 0 means all hits for every engine, as in :func:`fuse`.
    """
    from ..commands import search as search_cmd
    from .schema import load_schema

    schema, err = load_schema(root)
    if schema is None:
        raise MemberError(err or "missing schema")
    outcome = search_cmd.search(
        root, query, limit or MEMBER_UNBOUNDED, engine_override, include_exits, None, False, withhold=withhold
    )
    payload = outcome.payload
    if outcome.render in ("critical", "fail", "partial") or payload.get("ok") is False or outcome.code != 0:
        raise MemberError(str(payload.get("error") or f"exit {outcome.code}"))
    return MemberAnswer(
        hits=list(payload.get("hits") or []),
        match=payload.get("match"),
        engine_requested=payload.get("engine_requested"),
        engine_used=payload.get("engine_used"),
        driver_note=payload.get("driver_note"),
    )


def _short(err: BaseException) -> str:
    text = str(err).strip().splitlines()[0] if str(err).strip() else type(err).__name__
    return text if len(text) <= ERROR_MAX else text[: ERROR_MAX - 3] + "..."


def _member_record(member: mesh_scope.Member, status: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "atlas_id": member.atlas_id,
        "status": status,
        "engine_requested": None,
        "engine_used": None,
        "driver_note": None,
        "match": None,
        "hits": 0,
    }
    if member.reason is not None:
        record["reason"] = member.reason
    return record


def _pinned(member: mesh_scope.Member, mesh: mesh_scope.Mesh):
    """The member's mesh index location and row for the duration of its search.

    No walk-up or standalone id, and the row and project ``recall.engine``
    apply to ``subpath`` and pathless rows too.
    """
    location = member.location()
    if location is None:
        return nullcontext()
    match = index_location.MeshMatch(mesh.project, mesh.doc["stores"][member.index], mesh.doc)
    return index_location.pinned(location, match)


def federate(
    settings: Settings,
    query: str,
    *,
    limit: int = 10,
    engine_override: str | None = None,
    include_exits: bool = False,
    search: MemberSearch | None = None,
) -> tuple[dict[str, Any], int]:
    """Ask every included member for ``2 x limit`` hits, fuse, and build the M12 payload.

    ``limit`` 0 means all hits; a negative ``limit`` raises :class:`MeshRecallError`.
    Exit 0 when every included member answered, 1 when at least one failed.
    """
    if settings.mesh is None or settings.scope != "mesh":
        raise MeshRecallError("federated recall needs mesh scope")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise MeshRecallError(LIMIT_ERROR)
    run_member = search or store_search
    per_member = limit * OVERFETCH
    records: list[dict[str, Any]] = []
    lists: list[RankedList] = []
    complete = True
    for member in mesh_scope.members(settings.mesh):
        if member.status != mesh_scope.STATUS_OK:
            # excluded, unmounted or invalid: reported, never read
            records.append(_member_record(member, member.status))
            continue
        record = _member_record(member, mesh_scope.STATUS_OK)
        try:
            with _pinned(member, settings.mesh), mesh_walks():
                answer = run_member(member.root, query, per_member, engine_override, include_exits)
        except Exception as e:  # noqa: BLE001 - one broken member must not sink the others
            complete = False
            record["status"] = STATUS_ERROR
            record["error"] = _short(e)
            records.append(record)
            continue
        hits = answer.hits[:per_member] if per_member else answer.hits
        record.update(
            engine_requested=answer.engine_requested,
            engine_used=answer.engine_used,
            driver_note=answer.driver_note,
            match=answer.match,
            hits=len(hits),
        )
        records.append(record)
        lists.append(RankedList(member.index, member.atlas_id, tier_of(answer.match), str(answer.engine_used or ""), hits))
    fused = fuse(lists, settings.rrf_k, limit)
    payload = {
        "scope": "mesh",
        "scope_source": settings.scope_source,
        "rrf_k": settings.rrf_k,
        "rrf_k_source": settings.rrf_k_source,
        "project": str(settings.mesh.project),
        "query": query,
        "limit": limit,
        "complete": complete,
        "count": len(fused),
        "hits": fused,
        "members": records,
    }
    return payload, 0 if complete else 1


def render_text(payload: dict[str, Any]) -> list[str]:
    """Short, stable text: one line per hit led by its atlas id, then one member summary line."""
    lines = [f"{h['atlas_id']} {h['path']} tier={h['tier']} {h['title']}".rstrip() for h in payload["hits"]]
    if not lines:
        lines.append("no hits")
    parts = []
    for m in payload["members"]:
        if m["status"] == mesh_scope.STATUS_OK:
            match = f" match={m['match']}" if m.get("match") else ""
            parts.append(f"{m['atlas_id']} ok {m['engine_used']} hits={m['hits']}{match}")
        elif m["status"] == STATUS_ERROR:
            parts.append(f"{m['atlas_id']} error ({m.get('error')})")
        elif m.get("reason"):
            parts.append(f"{m['atlas_id']} {m['status']} ({m['reason']})")
        else:
            parts.append(f"{m['atlas_id']} {m['status']}")
    lines.append(f"members (complete={str(payload['complete']).lower()} rrf_k={payload['rrf_k']}): " + "; ".join(parts))
    return lines
