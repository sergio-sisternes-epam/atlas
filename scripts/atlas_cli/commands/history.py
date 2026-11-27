"""CLI commands for repository-version history."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from ..core import history
from ..core.paths import store_root


def _version_payload(version: history.Version) -> dict[str, Any]:
    return {
        "commit": version.commit,
        "recorded_time": version.recorded_at,
        "blob": version.blob,
        "availability": version.availability,
        **({"reason_code": version.reason} if version.reason else {}),
    }


def run(root: str | None, page: str, as_json: bool = False) -> int:
    store = store_root(root)
    try:
        versions = history.list_versions(store, page)
        shallow = history.is_shallow(store)
    except history.HistoryError as exc:
        payload = {
            "ok": False,
            "error": {"code": exc.reason, "message": str(exc)},
            "root": str(store),
            "path": page,
            "versions": [],
        }
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"atlas history — unavailable: {exc}")
        return 2
    entries = [
        {"label": "repository version", **_version_payload(version)}
        for version in versions
    ]
    payload: dict[str, Any] = {
        "ok": True,
        "root": str(store),
        "path": page,
        "versions": entries,
        "availability": "available" if entries else "unavailable",
    }
    if not entries and shallow:
        payload["reason_code"] = "shallow_history"
    elif not entries:
        payload["reason_code"] = "no_history"
    elif shallow:
        payload["history_completeness"] = "partial"
        payload["reason_code"] = "shallow_history"
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"atlas history — {page}")
        if not entries:
            print(f"unavailable ({payload['reason_code']})")
        elif payload.get("reason_code"):
            print(f"history incomplete ({payload['reason_code']})")
        for entry in entries:
            state = entry["availability"]
            detail = f" ({entry.get('reason_code')})" if entry.get("reason_code") else ""
            print(
                f"repository version {entry['commit']}  recorded={entry['recorded_time']}  "
                f"blob={entry['blob'] or 'unavailable'}  {state}{detail}"
            )
    return 0


def run_as_of(
    root: str | None,
    query: str,
    as_of: str,
    limit: int,
    as_json: bool,
    engine: str | None = None,
    profile: str | None = None,
    allow_partial: bool = False,
) -> int:
    """Recall from a local historical snapshot and fail closed when unavailable."""
    from . import search

    store = store_root(root)
    try:
        moment = history.parse_as_of(as_of)
    except history.HistoryError as exc:
        return _print_failure(as_json, store, query, exc.reason, str(exc))

    # Current matches are used only to identify paths when no historical object
    # can be materialized. Their text and metadata are never returned.
    current = search.search(
        store, query, limit, engine, True, profile, allow_partial
    ).payload
    current_paths = [
        str(hit.get("path"))
        for hit in current.get("hits") or []
        if isinstance(hit, dict) and hit.get("path")
    ]
    unavailable_reason: str | None = None
    try:
        _, _, commit = history.repository_version_at(store, moment)
        with tempfile.TemporaryDirectory(prefix="atlas-history-") as raw_temp:
            historical_root = history.materialize_store(store, commit, Path(raw_temp))
            outcome = search.search(
                historical_root,
                query,
                limit,
                engine,
                True,
                profile,
                allow_partial,
            )
            historical = outcome.payload
            if outcome.code not in (0, 1) or historical.get("ok") is False:
                return _print_failure(
                    as_json,
                    store,
                    query,
                    "historical_recall_failed",
                    str(historical.get("error") or "historical recall failed"),
                )
            hits = []
            seen: set[str] = set()
            unavailable = []
            for hit in historical.get("hits") or []:
                page = str(hit.get("path") or "")
                historical_blob = history.blob_at_commit(store, commit, page)
                version = (
                    history.version_for_date(store, page, moment, historical_blob)
                    if historical_blob
                    else None
                )
                if version is None:
                    unavailable.append(
                        {
                            "path": page,
                            "availability": "unavailable",
                            "reason_code": "history_unavailable",
                        }
                    )
                    continue
                if version.availability != "available":
                    unavailable.append(
                        {
                            "path": page,
                            "availability": "unavailable",
                            "reason_code": version.reason or "history_unavailable",
                        }
                    )
                    continue
                result = dict(hit)
                result["provenance"] = {
                    "label": "repository version at that date",
                    "commit": version.commit,
                    "recorded_time": version.recorded_at,
                }
                hits.append(result)
                seen.add(page)
            for page in current_paths:
                if page in seen:
                    continue
                version = history.version_for_date(store, page, moment)
                if version is None:
                    unavailable.append(
                        {"path": page, "availability": "unavailable", "reason_code": "path_absent"}
                    )
                elif version.availability != "available":
                    unavailable.append(
                        {
                            "path": page,
                            "availability": "unavailable",
                            "reason_code": version.reason or "history_unavailable",
                        }
                    )
            return _print_as_of(
                as_json, store, query, moment, hits, unavailable, outcome.code
            )
    except history.HistoryError as exc:
        unavailable_reason = exc.reason

    unavailable = [
        {"path": page, "availability": "unavailable", "reason_code": unavailable_reason}
        for page in current_paths
    ]
    return _print_as_of(as_json, store, query, moment, [], unavailable, 0)


def _print_as_of(
    as_json: bool,
    root: Path,
    query: str,
    moment,
    hits: list[dict],
    unavailable: list[dict[str, str]],
    code: int,
) -> int:
    payload = {
        "ok": True,
        "root": str(root),
        "query": query,
        "as_of": moment.isoformat().replace("+00:00", "Z"),
        "label": "repository version at that date",
        "hits": hits,
        "unavailable": unavailable,
        "count": len(hits),
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"atlas recall run — repository version at that date ({payload['as_of']})")
        for hit in hits:
            provenance = hit["provenance"]
            print(
                f"{hit['path']}  commit={provenance['commit']}  "
                f"recorded={provenance['recorded_time']}"
            )
            if hit.get("snippet"):
                print(f"  {hit['snippet']}")
        for item in unavailable:
            print(f"{item['path']}  unavailable ({item['reason_code']})")
        if not hits and not unavailable:
            print("no hits")
    return code


def _print_failure(
    as_json: bool, root: Path, query: str, reason: str, message: str
) -> int:
    payload = {
        "ok": False,
        "root": str(root),
        "query": query,
        "error": {"code": reason, "message": message},
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"atlas recall run — FAIL: {message}")
    return 2
