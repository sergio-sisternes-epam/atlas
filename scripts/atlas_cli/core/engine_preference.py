"""Preferred recall engine: one resolver, availability fallback and index refresh.

Precedence, highest first (see references/paths/recall.md):

1. ``--engine`` on the command (``cli``)
2. ``ATLAS_RECALL_ENGINE`` (``env``)
3. the store's ``atlas-mesh.json`` row ``recall.engine`` (``store``), matched
   with core/index_location.py's mesh resolution
4. the same mesh file's top-level ``recall.engine`` (``project``)
5. built-in default (``default``): SCHEMA ``query.search_engine`` when it is
   ``bm25``, else ``grep``

A standalone store (no mesh row) skips levels 3 and 4. Indexed engines map to
driver types: ``bm25`` -> ``fts5``, ``nanograph`` -> ``nanograph``. The
effective engine falls back nanograph -> bm25 -> grep when a driver is
unavailable; no index is built for an unavailable driver.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import index_location, meshfile

ENGINES = meshfile.RECALL_ENGINES
ENV = "ATLAS_RECALL_ENGINE"
SOURCES = ("cli", "env", "store", "project", "default")
PREFERENCE_SOURCES = frozenset({"env", "store", "project"})
INDEX_TYPES = {"bm25": "fts5", "nanograph": "nanograph"}
ENGINE_DRIVERS = {"grep": "grep", "bm25": "sqlite-fts5", "nanograph": "nanograph"}
FALLBACK = {"nanograph": "bm25", "bm25": "grep"}
IGNORED_CODE = "preferred_engine_ignored"


class EnginePreferenceError(ValueError):
    """An engine preference is invalid; the message names where it was set."""


@dataclass(frozen=True)
class EnginePreference:
    requested: str
    source: str
    origin: str
    mesh_file: str | None = None
    store_id: str | None = None

    @property
    def is_preference(self) -> bool:
        """Set by configuration (env or mesh) rather than the command or a default."""
        return self.source in PREFERENCE_SOURCES

    @property
    def persist(self) -> bool:
        """Whether an indexed engine should keep its index fresh on disk."""
        return self.source != "default"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EffectiveEngine:
    requested: str
    engine: str
    driver: str
    unavailable: list[tuple[str, str]] = field(default_factory=list)

    @property
    def note(self) -> str | None:
        return fallback_note(self.requested, self.unavailable, self.engine)


def allowed_text() -> str:
    return ", ".join(ENGINES)


def _check(value: Any, where: str) -> str:
    text = value.strip().lower() if isinstance(value, str) else value
    if text not in ENGINES:
        raise EnginePreferenceError(f"{where}: engine {value!r} is not allowed; allowed values: {allowed_text()}")
    return text


def schema_default(schema: dict[str, Any] | None) -> str:
    query = (schema or {}).get("query") or {}
    raw = str(query.get("search_engine") or "grep").strip().lower() if isinstance(query, dict) else "grep"
    return "bm25" if raw == "bm25" else "grep"


def resolve_engine(
    store: Path,
    cli_engine: str | None = None,
    schema: dict[str, Any] | None = None,
) -> EnginePreference:
    """Resolve the requested engine and where it came from. Raises :class:`EnginePreferenceError`.

    Every configured level is validated, even when a higher level wins, so a
    broken setting is reported instead of lurking.
    """
    cli_value = _check(cli_engine, "--engine") if cli_engine else None
    env_raw = os.environ.get(ENV, "")
    env_value = _check(env_raw, ENV) if env_raw.strip() else None
    store_value = project_value = None
    mesh_file = store_id = None
    match = index_location.mesh_match(Path(store))
    if match is not None:
        mesh_file = str(match.mesh_file)
        store_id = str(match.row.get("id"))
        errs = meshfile.recall_block_errors(match.row["recall"], f"{mesh_file}: store {store_id}") if "recall" in match.row else []
        if "recall" in match.doc:
            errs += meshfile.recall_block_errors(match.doc["recall"], f"{mesh_file}: project default")
        if errs:
            raise EnginePreferenceError("; ".join(errs))
        store_value = (match.row.get("recall") or {}).get("engine")
        project_value = (match.doc.get("recall") or {}).get("engine")
    if cli_value:
        return EnginePreference(cli_value, "cli", "--engine", mesh_file, store_id)
    if env_value:
        return EnginePreference(env_value, "env", ENV, mesh_file, store_id)
    if store_value:
        return EnginePreference(store_value, "store", f"{mesh_file} (store {store_id})", mesh_file, store_id)
    if project_value:
        return EnginePreference(project_value, "project", f"{mesh_file} (project default)", mesh_file, store_id)
    query = (schema or {}).get("query") if isinstance(schema, dict) else None
    origin = "SCHEMA query.search_engine" if isinstance(query, dict) and query.get("search_engine") else "built-in default"
    return EnginePreference(schema_default(schema), "default", origin, mesh_file, store_id)


def fallback_note(requested: str, unavailable: list[tuple[str, str]], used: str) -> str | None:
    if not unavailable:
        return None
    first, reason = unavailable[0]
    parts = [f"preferred engine {first} unavailable: {reason}"]
    parts += [f"{eng} unavailable: {why}" for eng, why in unavailable[1:]]
    return "; ".join(parts) + f"; used {used}"


def failure_note(engine: str, error: str, used: str) -> str:
    return f"preferred engine {engine} failed: {error}; used {used}"


def effective_engine(requested: str) -> EffectiveEngine:
    """Walk the fallback chain using driver detection; never builds anything."""
    from .driver_overlay import get_driver
    from .recall_config import fts5_available

    engine = requested
    unavailable: list[tuple[str, str]] = []
    while True:
        if engine == "nanograph":
            det = get_driver("nanograph").detect()
            if det.available:
                break
            unavailable.append(("nanograph", det.reason))
        elif engine == "bm25":
            if fts5_available():
                break
            unavailable.append(("bm25", "sqlite3 lacks FTS5"))
        else:
            break
        engine = FALLBACK[engine]
    return EffectiveEngine(requested, engine, ENGINE_DRIVERS[engine], unavailable)


def ignored_notice(profile: str, pref: EnginePreference) -> dict[str, str]:
    return {
        "code": IGNORED_CODE,
        "level": "info",
        "message": (
            f"store recall profile {profile} is authoritative; preferred engine "
            f"{pref.requested} from {pref.source} not applied"
        ),
    }


def index_status(store: Path, schema: dict[str, Any] | None, engine: str) -> dict[str, Any]:
    """Read-only: index directory and freshness for an effective engine (never builds)."""
    driver_type = INDEX_TYPES.get(engine)
    if driver_type is None:
        return {"driver_type": None, "index_dir": None, "fresh": None}
    out: dict[str, Any] = {"driver_type": driver_type}
    try:
        out.update(index_location.describe(store, driver_type))
    except (index_location.IndexLocationError, OSError):
        out["index_dir"] = None
    try:
        if engine == "bm25":
            from . import recall_index
            from .projection import project_store

            projection = project_store(store, schema, allow_partial=False)
            digest = str(projection.get("corpus_digest") or "")
            gen = recall_index.find_generation(store, digest=digest) if projection.get("complete") else None
            out["fresh"] = gen is not None
            if gen is not None:
                out["generation"] = gen.pointer.get("generation")
                if gen.legacy:
                    out["legacy"] = True
        else:
            from . import graph
            from .driver_overlay import get_driver

            source = graph.load_source(store)
            out.update(get_driver("nanograph").index_state(store, str(source.get("corpus_digest") or "")))
    except Exception as e:  # noqa: BLE001 - status is advisory
        out["fresh"] = False
        out["reason"] = str(e)
    return out


def refresh_index(store: Path, schema: dict[str, Any] | None, engine: str) -> dict[str, Any]:
    """Make the effective engine's new-location index fresh. Raises on failure.

    Returns ``{"driver", "driver_type", "generation", "rebuilt", "index_dir"}``.
    """
    driver_type = INDEX_TYPES[engine]
    if engine == "bm25":
        from . import recall_index

        fresh = recall_index.ensure_fresh(store, schema, allow_legacy=False)
        gen = fresh.generation.pointer.get("generation")
        rebuilt = fresh.rebuilt
    else:
        from . import graph
        from .driver_overlay import get_driver

        driver = get_driver("nanograph")
        source = graph.load_source(store)
        driver.ensure_index(store, source, allow_legacy=False)
        info = driver.last_index or {}
        gen = info.get("generation")
        rebuilt = not info.get("reused", True)
    where = index_location.describe(store, driver_type)
    return {
        "driver": ENGINE_DRIVERS[engine],
        "driver_type": driver_type,
        "generation": gen,
        "rebuilt": rebuilt,
        "index_dir": where.get("index_dir"),
    }


def refresh_preferred(store: Path, schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Compile/validate/index-build hook. Returns info or warning items; never raises.

    Only a configured preference (env, mesh store row, mesh project default)
    triggers work. Profile stores (SCHEMA 2.0 recall enabled) are skipped: the
    profile's own fts5 index is published by the caller.
    """
    from .recall_config import recall_enabled

    try:
        pref = resolve_engine(store, None, schema)
    except EnginePreferenceError as e:
        return [{"id": "preferred_engine_invalid", "level": "warning", "path": meshfile.MESH_NAME, "msg": str(e)}]
    if not pref.is_preference or recall_enabled(schema):
        return []
    eff = effective_engine(pref.requested)
    if eff.engine not in INDEX_TYPES:
        return []
    try:
        res = refresh_index(store, schema, eff.engine)
    except Exception as e:  # noqa: BLE001 - index work never fails compile
        return [
            {
                "id": "preferred_index_failed",
                "level": "warning",
                "path": INDEX_TYPES[eff.engine],
                "msg": f"could not refresh the {eff.driver} index for preferred engine {pref.requested}: {e}",
                "driver": eff.driver,
            }
        ]
    code = "preferred_index_refreshed" if res["rebuilt"] else "preferred_index_fresh"
    verb = "rebuilt" if res["rebuilt"] else "already fresh"
    item = {
        "id": code,
        "level": "info",
        "path": res.get("index_dir") or INDEX_TYPES[eff.engine],
        "msg": f"{eff.driver} index for preferred engine {pref.requested} ({pref.source}) {verb}: generation {res['generation']}",
        "driver": eff.driver,
        "driver_type": res["driver_type"],
        "generation": res["generation"],
        "engine_requested": pref.requested,
        "engine_source": pref.source,
    }
    if eff.note:
        item["driver_note"] = eff.note
    return [item]
