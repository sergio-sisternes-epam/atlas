"""SMR pipeline: project current tree, Coarse/Rank, Retrieve."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import recall_index
from .drivers import fts5 as fts5_driver
from .drivers import scan as scan_driver
from .drivers import tgrep as tgrep_driver
from .overlay import merge_overlays
from .ignore_guard import is_warning
from .projection import ProjectedPage, ProjectionError, project_store
from .recall_config import (
    RecallConfigError,
    recall_enabled,
    resolve_profile,
    schema_version,
)
from .retrieve import neighbourhood
from .schema import load_schema

_FIELD_TOKEN = re.compile(
    r"(?:^|\s)(type|kva|status|work_id|path):([^\s]+)",
    re.I,
)
EXIT_STATES = frozenset({"terminated", "deprecated", "superseded"})


def split_filters(query: str) -> tuple[dict[str, str], str]:
    filters: dict[str, str] = {}
    for m in _FIELD_TOKEN.finditer(query):
        filters[m.group(1).lower()] = m.group(2)
    rest = _FIELD_TOKEN.sub(" ", query)
    return filters, re.sub(r"\s+", " ", rest).strip()


def _effective(root: Path) -> tuple[dict[str, Any] | None, str | None, dict[str, Any]]:
    schema, err = load_schema(root)
    if schema is None:
        return None, err, {}
    merged, critical, _ = merge_overlays(schema, root)
    if critical:
        return merged, "; ".join(i["msg"] for i in critical), merged
    return merged, None, merged


def _eligible(page: ProjectedPage, filters: dict[str, str], include_exits: bool) -> bool:
    if page.role == "log":
        return False
    meta = page.meta
    if filters.get("type") and str(meta.get("type") or "").strip() != filters["type"]:
        return False
    if filters.get("kva") and str(meta.get("kva") or "").strip() != filters["kva"]:
        return False
    if filters.get("status") and str(meta.get("status") or "").strip() != filters["status"]:
        return False
    if filters.get("work_id") and str(meta.get("work_id") or "").strip() != filters["work_id"]:
        return False
    asked_exit = (
        str(filters.get("kva") or "").lower() in EXIT_STATES
        or str(filters.get("status") or "").lower() in EXIT_STATES
    )
    if not include_exits and not asked_exit:
        for key in ("kva", "status"):
            if str(meta.get(key) or "").strip().lower() in EXIT_STATES:
                return False
    if filters.get("path"):
        prefix = filters["path"].replace("\\", "/").strip("/")
        hay = page.path.replace("\\", "/").lstrip("/")
        if prefix and hay != prefix and not hay.startswith(prefix + "/"):
            return False
    return True


def run_recall(
    root: Path,
    query: str,
    *,
    profile: str | None = None,
    allow_partial: bool = False,
    include_exits: bool = False,
    limit: int | None = None,
) -> tuple[dict[str, Any], int]:
    schema, err, effective = _effective(root)
    if schema is None:
        return {"ok": False, "error": err or "missing schema"}, 2
    if err:
        return {"ok": False, "error": err}, 2
    version = schema_version(schema)
    if version != "2.0":
        if profile:
            return {"ok": False, "error": "profile requires SCHEMA 2.0"}, 2
        return {"ok": False, "error": "legacy_store", "legacy": True}, 0
    if not recall_enabled(effective) and not profile:
        return {"ok": False, "error": "recall_disabled", "legacy": True}, 0
    try:
        resolved = resolve_profile(effective, preset=profile)
    except RecallConfigError as e:
        return {"ok": False, "error": str(e)}, 2

    filters, rest = split_filters(query)
    policy = resolved["effective"]
    max_hits = int(limit if limit is not None else policy["limits"]["max_hits"])
    coarse = str((policy.get("coarse") or {}).get("driver") or "scan")
    rank = str((policy.get("rank") or {}).get("driver") or coarse)
    retrieve_drv = str((policy.get("retrieve") or {}).get("driver") or "pages-graph")
    match_mode: str | None = None

    db_path = None
    ephemeral = False
    generation_id = None
    fast_path = False
    omitted: list[dict[str, str]] = []
    projection_pages: list[ProjectedPage]
    corpus_digest = ""
    complete = True

    legacy_used = False
    index_note: str | None = None
    index_rebuilt: bool | None = None
    extra_warnings: list[dict[str, str]] = []
    fast_gen = recall_index.find_generation(root, schema=schema, fast_path=True)
    if fast_gen is not None:
        projection_pages = recall_index.pages_from_db(fast_gen.db)
        corpus_digest = str(fast_gen.pointer.get("corpus_digest") or "")
        generation_id = fast_gen.pointer.get("generation")
        db_path = fast_gen.db
        legacy_used = fast_gen.legacy
        fast_path = True
    else:
        try:
            projection = project_store(root, schema, allow_partial=allow_partial)
        except ProjectionError as e:
            return {"ok": False, "error": str(e), "complete": False}, 2
        projection_pages = projection["pages"]
        corpus_digest = str(projection["corpus_digest"])
        complete = bool(projection["complete"])
        omitted = list(projection["omitted"])
        if recall_enabled(effective) and complete:
            # Same freshness + atomic publish path as a preferred bm25 engine.
            try:
                fresh = recall_index.ensure_fresh(
                    root, schema, projection=projection, guard_ignore=True
                )
            except Exception as e:  # noqa: BLE001 - unwritable/unsafe/busy -> temporary index
                index_note = f"index not written ({e}); used a temporary index"
            else:
                db_path = fresh.generation.db
                generation_id = fresh.generation.pointer.get("generation")
                legacy_used = fresh.generation.legacy
                index_rebuilt = fresh.rebuilt
                extra_warnings += [w for w in fresh.warnings if is_warning(w) and w.get("code")]

    pages: list[ProjectedPage] = [
        p for p in projection_pages if _eligible(p, filters, include_exits)
    ]
    if not rest and filters:
        hits = [
            {
                "path": page.path,
                "score": 1,
                "title": page.title,
                "type": str(page.meta.get("type") or ""),
                "terms": [],
                "snippet": page.body[:160].replace("\n", " ").strip(),
                "driver": "filter",
            }
            for page in pages
        ]
        hits.sort(key=lambda h: h["path"])
        if max_hits:
            hits = hits[:max_hits]
        engine_used = "filter"
    elif coarse == "tgrep":
        try:
            hits, tmeta = tgrep_driver.search(
                root,
                pages,
                rest or query,
                0,
                corpus_digest,
                schema=schema,
            )
        except tgrep_driver.TgrepError as e:
            return {"ok": False, "error": str(e), "complete": complete}, 2
        ephemeral = bool(tmeta.get("ephemeral"))
        fts_generation = generation_id
        generation_id = tmeta.get("index")
        if tmeta.get("legacy_warning"):
            extra_warnings.append(tmeta["legacy_warning"])
        extra_warnings += list(tmeta.get("index_warnings") or [])
        engine_used = "tgrep"
        if rank == "sqlite-fts5" and hits:
            fts_ephemeral = False
            if db_path is None:
                found = recall_index.find_generation(root, digest=corpus_digest)
                if found is None:
                    db_path = recall_index.build_ephemeral(
                        {"pages": projection_pages, "corpus_digest": corpus_digest}
                    )
                    fts_ephemeral = True
                    ephemeral = True
                else:
                    db_path = found.db
                    generation_id = found.pointer.get("generation") or generation_id
                    legacy_used = found.legacy
            else:
                generation_id = fts_generation or generation_id
            conn = recall_index.open_db(db_path)
            try:
                weights = ((policy.get("rank") or {}).get("weights")) or None
                ranked = fts5_driver.search(conn, rest or query, 0, weights)
            finally:
                conn.close()
                if fts_ephemeral and db_path is not None:
                    db_path.unlink(missing_ok=True)
            order = {h["path"]: i for i, h in enumerate(ranked)}
            hits.sort(key=lambda h: (order.get(h["path"], 10**9), -float(h.get("score") or 0), h["path"]))
            engine_used = "tgrep+sqlite-fts5"
        elif rank == "scan" and hits:
            allowed = {h["path"] for h in hits}
            subset = [p for p in pages if p.path in allowed]
            hits = scan_driver.search(subset, rest or query, 0)
            engine_used = "tgrep+scan"
        if max_hits:
            hits = hits[:max_hits]
    elif rank == "sqlite-fts5" or coarse == "sqlite-fts5":
        if db_path is None:
            found = recall_index.find_generation(root, digest=corpus_digest)
            if found is None:
                db_path = recall_index.build_ephemeral(
                    {"pages": projection_pages, "corpus_digest": corpus_digest}
                )
                ephemeral = True
            else:
                db_path = found.db
                generation_id = found.pointer.get("generation") or generation_id
                legacy_used = found.legacy
        conn = recall_index.open_db(db_path)
        allowed = {p.page_id for p in pages}
        try:
            weights = ((policy.get("rank") or {}).get("weights")) or None
            hits, match_mode = fts5_driver.search_eligible(
                conn, rest or query, max_hits, weights, allowed
            )
        finally:
            conn.close()
            if ephemeral and db_path is not None:
                db_path.unlink(missing_ok=True)
        if max_hits:
            hits = hits[:max_hits]
        engine_used = "sqlite-fts5"
    else:
        hits = scan_driver.search(pages, rest or query, max_hits)
        engine_used = "scan"

    by_id = {p.page_id: p for p in projection_pages}
    for hit in hits:
        page = by_id.get(hit["path"])
        if page:
            hit["relates_to"] = [
                {"path": e["target"], "kind": e["kind"]} for e in page.edges[:5]
            ]
            for key in ("kva", "status", "work_id", "growth"):
                val = page.meta.get(key)
                if val not in (None, ""):
                    hit[key] = val

    max_hops = int((policy.get("retrieve") or {}).get("max_hops") or policy["limits"]["max_hops"])
    neighbourhood_block = None
    if max_hops > 0:
        neighbourhood_block = neighbourhood(
            list(by_id.values()),
            [h["path"] for h in hits],
            max_hops,
            policy["limits"]["max_nodes"],
            policy["limits"]["max_edges"],
            include_exits,
        )

    payload = {
        "ok": True,
        "root": str(root),
        "query": query,
        "engine_configured": engine_used,
        "engine_used": engine_used,
        "count": len(hits),
        "hits": hits,
        "neighbourhood": neighbourhood_block,
        "recall": {
            "version": 1,
            "preset": resolved["preset"],
            "provenance": resolved["provenance"],
            "drivers": {"coarse": coarse, "rank": rank, "retrieve": retrieve_drv},
            "generation": generation_id,
            "corpus_digest": corpus_digest,
            "complete": complete,
            "consistency": "current-tree",
            "ephemeral": ephemeral,
            "fast_path": fast_path,
            "omitted": omitted,
            "limits": policy["limits"],
        },
    }
    if index_rebuilt is not None:
        payload["recall"]["index_rebuilt"] = index_rebuilt
    if index_note:
        payload["driver_note"] = index_note
    if db_path is not None and not ephemeral:
        try:
            payload["recall"].update(recall_index.index_location.describe(root, "fts5"))
        except recall_index.IndexError_:
            pass
    if legacy_used:
        extra_warnings.insert(0, recall_index.legacy_warning(root))
    if extra_warnings:
        payload.setdefault("warnings", []).extend(extra_warnings)
    if match_mode is not None:
        payload["match"] = match_mode
    if not complete:
        return payload, 1
    return payload, 0
