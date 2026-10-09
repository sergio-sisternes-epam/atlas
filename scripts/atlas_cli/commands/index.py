"""`atlas index`: manage the preferred recall engine and its indexes.

Engines are ``grep`` | ``bm25`` | ``nanograph``. The preference is stored as
``recall.engine`` on a store row of the project's ``atlas-mesh.json`` or at its
top level (the project default, ``--default`` on the CLI). Precedence and
fallback live in core/engine_preference.py; this module only reads, writes
(core/meshfile.set_recall_engine) and builds.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core import engine_preference as ep
from ..core import index_location, meshfile
from ..core.identity import IdentityError, normalise
from ..core.ignore_guard import ensure_index_ignored, ensure_indexes_ignored, indexes_ignore_status
from ..core.paths import store_root
from ..core.recall_config import RecallConfigError, recall_enabled, resolve_profile

DEPRECATED_CODE = "deprecated_command"
DEPRECATION = {
    "code": DEPRECATED_CODE,
    "level": "warning",
    "message": "`atlas recall index build` is deprecated; use `atlas index build` (removal after 0.14.x)",
}
UNAVAILABLE_CODE = "engine_unavailable_here"
MOUNT_HINT = "register the store with `atlas mount <source>` (from the project root) first"


class UsageError(Exception):
    """Bad target or arguments; exit 2 and nothing written."""


@dataclass
class Located:
    root: Path
    project: Path | None
    match: index_location.MeshMatch | None
    doc: dict[str, Any] | None = None
    error: str | None = None

    @property
    def mesh_file(self) -> Path | None:
        return meshfile.mesh_path(self.project) if self.project else None


@dataclass
class StoreRef:
    store_id: str
    path: Path
    row: dict[str, Any] | None = None
    rel: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def mounted(self) -> bool:
        return self.path.is_dir()


# --- output -------------------------------------------------------------------


def _emit(as_json: bool, payload: dict[str, Any], lines: list[str]) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return
    for item in payload.get("warnings") or []:
        print(f"warning: {index_location.warning_text(item)}", file=sys.stderr)
    for line in lines:
        print(line)


def _fail(as_json: bool, error: str, code: int = 2, **extra: Any) -> int:
    payload = {"ok": False, "error": error, **extra}
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(f"atlas index — error: {error}", file=sys.stderr)
    return code


# --- locating the project and stores ------------------------------------------------


def _nearest_mesh(start: Path) -> Path | None:
    for d in [start, *start.parents]:
        if meshfile.mesh_path(d).is_file():
            return d
    return None


def locate(root: str | None) -> Located:
    """The store at ``--root`` (when it is a mesh row) and the project that owns the mesh file."""
    r = store_root(root)
    index_location.clear_cache()
    try:
        match = index_location.mesh_match(r)
    except index_location.IndexLocationError as e:
        return Located(r, _nearest_mesh(r), None, error=str(e))
    if match is not None:
        return Located(r, match.directory, match)
    return Located(r, _nearest_mesh(r), None)


def _load_doc(loc: Located) -> dict[str, Any]:
    if loc.doc is None:
        assert loc.project is not None
        try:
            loc.doc = meshfile.load_for_location(loc.project)
        except (meshfile.MeshFileError, json.JSONDecodeError) as e:
            raise UsageError(f"{loc.mesh_file}: {e}") from e
        except OSError as e:
            raise UsageError(f"{loc.mesh_file}: cannot read ({e})") from e
    return loc.doc


def _no_mesh_error(loc: Located) -> UsageError:
    return UsageError(
        f"no {meshfile.MESH_NAME} at or above {loc.root}; {MOUNT_HINT}. "
        "For one-off use, set ATLAS_RECALL_ENGINE or pass --engine to `atlas recall run`"
    )


def _rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in doc.get("stores") or [] if isinstance(r, dict) and isinstance(r.get("id"), str)]


def _known(doc: dict[str, Any]) -> str:
    ids = [str(r["id"]) for r in _rows(doc)]
    return ", ".join(ids) if ids else "(none)"


def _ref(project: Path, row: dict[str, Any]) -> StoreRef:
    raw = row.get("path")
    rel = raw if isinstance(raw, str) and raw.strip() else None
    path = (project / rel).resolve() if rel else project / ".atlas-missing-path" / str(row["id"])
    return StoreRef(str(row["id"]), path, row, rel)


def _row_for(loc: Located, raw_id: str) -> StoreRef:
    if loc.project is None:
        raise _no_mesh_error(loc)
    doc = _load_doc(loc)
    try:
        wanted = normalise(raw_id)
    except IdentityError:
        wanted = raw_id.strip()
    for row in _rows(doc):
        if row["id"] == wanted:
            return _ref(loc.project, row)
    # normalise() keeps org/repo case; accept a different spelling when exactly one row matches case-insensitively.
    folded = [row for row in _rows(doc) if row["id"].lower() == wanted.lower()]
    if len(folded) == 1:
        return _ref(loc.project, folded[0])
    raise UsageError(f"unknown store id {raw_id!r} in {loc.mesh_file}; known ids: {_known(doc)}")


def _root_store(loc: Located, *, need_row: bool) -> StoreRef:
    if loc.match is not None:
        assert loc.project is not None
        return _ref(loc.project, loc.match.row)
    if need_row:
        if loc.project is None:
            raise UsageError(f"store at {loc.root} has no row in any {meshfile.MESH_NAME}; {MOUNT_HINT}")
        doc = _load_doc(loc)
        raise UsageError(
            f"{loc.root} is not a store listed in {loc.mesh_file}; pass --store <atlas-id> "
            f"(known ids: {_known(doc)}) or --default"
        )
    return StoreRef(index_location.resolve(loc.root).atlas_id, loc.root)


def _rel(loc: Located, path: Path | None) -> str | None:
    if path is None or loc.project is None:
        return None
    try:
        return path.relative_to(loc.project).as_posix()
    except ValueError:
        return os.path.relpath(path, loc.project)


def _effective_schema(store: Path) -> tuple[dict[str, Any] | None, str | None]:
    from .recall import _effective

    return _effective(store)


def _preset(schema: dict[str, Any]) -> str:
    try:
        return str(resolve_profile(schema)["preset"])
    except RecallConfigError:
        return str((schema.get("recall") or {}).get("preset"))


# --- availability warnings ------------------------------------------------------


def unavailable_warning(value: str) -> dict[str, str] | None:
    if value not in ep.INDEX_TYPES:
        return None
    eff = ep.effective_engine(value)
    if not eff.unavailable:
        return None
    engine, reason = eff.unavailable[0]
    what = f"{engine} {reason}" if reason.startswith("unavailable") else f"{engine} unavailable ({reason})"
    return {
        "code": UNAVAILABLE_CODE,
        "level": "warning",
        "message": f"{what}; recall here will fall back to {eff.engine}",
    }


# --- build (shared with the deprecated `atlas recall index build`) ------------------------


def build_store(ref: StoreRef, force: bool = False) -> dict[str, Any]:
    """Build or refresh the index the store's effective engine reads. Never raises.

    ``status`` is ``built`` | ``fresh`` | ``no_index_needed`` | ``skipped`` |
    ``failed`` (``error`` says why). Profile stores (SCHEMA 2.0 recall
    enabled) build the profile's fts5 index; other stores build for the
    effective engine after availability fallback.
    """
    from ..core import recall_index

    res: dict[str, Any] = {"store_id": ref.store_id, "root": str(ref.path), "mounted": ref.mounted}
    if ref.rel:
        res["path"] = ref.rel
    if not ref.mounted:
        res.update(status="skipped", message="skipped: store not mounted")
        return res
    schema, err = _effective_schema(ref.path)
    if schema is None:
        res.update(status="failed", error=err or "store contract unreadable", config_error=True)
        return res
    info: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    try:
        pref = ep.resolve_engine(ref.path, None, schema)
    except ep.EnginePreferenceError as e:
        res.update(status="failed", error=str(e), config_error=True)
        return res
    res.update(engine_requested=pref.requested, engine_source=pref.source)
    if recall_enabled(schema):
        preset = _preset(schema)
        res.update(profile=preset, engine_effective=f"profile:{preset}", driver="sqlite-fts5", driver_type="fts5")
        if pref.is_preference and pref.requested != "bm25":
            info.append(ep.ignored_notice(preset, pref))
        try:
            out = recall_index.publish_generation(ref.path, schema, focused=False, force=force)
        except Exception as e:  # noqa: BLE001 - reported per store
            res.update(status="failed", error=str(e))
        else:
            res.update(out)
            if out.get("published"):
                res["rebuilt"] = not out.get("reused", False)
                res["status"] = "built" if res["rebuilt"] else "fresh"
            else:
                res.update(status="failed", error=f"profile index not published: {out.get('reason')}")
    else:
        eff = ep.effective_engine(pref.requested)
        res.update(engine_effective=eff.engine, driver=eff.driver)
        if eff.note:
            res["driver_note"] = eff.note
        if eff.engine not in ep.INDEX_TYPES:
            why = "grep fallback" if eff.engine != pref.requested else "grep"
            res.update(status="no_index_needed", published=False, reason="no_index_needed", message=f"no index needed ({why})")
        else:
            try:
                out = ep.refresh_index(ref.path, schema, eff.engine, force=force)
            except Exception as e:  # noqa: BLE001 - reported per store
                res.update(status="failed", driver_type=ep.INDEX_TYPES[eff.engine], error=str(e))
                try:
                    res.update(index_location.describe(ref.path, ep.INDEX_TYPES[eff.engine]))
                except (index_location.IndexLocationError, OSError):
                    pass
            else:
                res.update(out)
                try:
                    res["index_location"] = index_location.describe(ref.path, out["driver_type"])["index_location"]
                except (index_location.IndexLocationError, OSError):
                    pass
                res["published"] = True
                res["status"] = "built" if out["rebuilt"] else "fresh"
                prefix = "preferred_index" if pref.is_preference else "index"
                verb = "rebuilt" if out["rebuilt"] else "already fresh"
                info.append(
                    {
                        "id": f"{prefix}_refreshed" if out["rebuilt"] else f"{prefix}_fresh",
                        "level": "info",
                        "path": out.get("index_dir") or out["driver_type"],
                        "msg": f"{out['driver']} index for engine {pref.requested} ({pref.source}) {verb}: generation {out['generation']}",
                        "driver": out["driver"],
                        "driver_type": out["driver_type"],
                        "generation": out["generation"],
                        "engine_requested": pref.requested,
                        "engine_source": pref.source,
                    }
                )
    warnings = [*(res.get("warnings") or []), *warnings]
    for item in (ensure_indexes_ignored(ref.path), ensure_index_ignored(ref.path)):
        if item:
            (warnings if item.get("level") == "warning" else info).append(item)
    if info:
        res["info"] = info
    if warnings:
        res["warnings"] = _dedupe_items(warnings)
    return res


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop repeats of the same warning (a driver build and the command may both guard)."""
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (item.get("code") or item.get("id"), item.get("path"), item.get("message") or item.get("msg"))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _build_line(res: dict[str, Any]) -> str:
    sid = res.get("store_id")
    status = res.get("status")
    if status == "skipped":
        return f"{sid}: {res.get('message')}"
    if status == "failed":
        return f"{sid}: FAILED: {res.get('error')}"
    if status == "no_index_needed":
        return f"{sid}: {res.get('engine_effective')} — {res.get('message')}"
    verb = "built" if status == "built" else "fresh (not rebuilt)"
    return f"{sid}: {res.get('engine_effective')} {verb} generation={res.get('generation')} index={res.get('index_dir')}"


def run_build(
    root: str | None,
    store: str | None,
    all_stores: bool,
    force: bool,
    as_json: bool,
    deprecated: bool = False,
) -> int:
    if store and all_stores:
        return _fail(as_json, "--store and --all are mutually exclusive")
    loc = locate(root)
    if loc.error:
        return _fail(as_json, loc.error, root=str(loc.root))
    try:
        if all_stores:
            if loc.project is None:
                raise _no_mesh_error(loc)
            refs = [_ref(loc.project, row) for row in _rows(_load_doc(loc))]
        elif store:
            refs = [_row_for(loc, store)]
        else:
            refs = [_root_store(loc, need_row=False)]
    except UsageError as e:
        return _fail(as_json, str(e), root=str(loc.root))
    results = [build_store(ref, force) for ref in refs]
    failed = [r for r in results if r.get("status") == "failed"]
    if all_stores:
        payload: dict[str, Any] = {
            "ok": not failed,
            "root": str(loc.root),
            "project": str(loc.project),
            "mesh_file": _rel(loc, loc.mesh_file),
            "stores": results,
        }
        code = 1 if failed else 0
    else:
        only = results[0]
        if only.get("config_error"):
            return _fail(as_json, str(only.get("error")), root=str(refs[0].path))
        payload = {"ok": not failed, "root": str(refs[0].path), **only, "stores": results}
        code = 1 if failed else 0
    if deprecated:
        payload["warnings"] = [DEPRECATION, *(payload.get("warnings") or [])]
    lines = [_build_line(r) for r in results]
    if failed:
        lines.append(f"{len(failed)} build(s) failed")
    _emit(as_json, payload, lines)
    return code


# --- set / unset ----------------------------------------------------------------


def _write_target(loc: Located, store: str | None, default: bool) -> tuple[Path, str | None, StoreRef | None]:
    """``(project, target id or None for the default, store ref or None)``; raises UsageError."""
    if store and default:
        raise UsageError("--store and --default are mutually exclusive")
    if store:
        ref = _row_for(loc, store)
        assert loc.project is not None
        return loc.project, ref.store_id, ref
    if default:
        if loc.project is None:
            raise _no_mesh_error(loc)
        _load_doc(loc)
        return loc.project, None, None
    ref = _root_store(loc, need_row=True)
    assert loc.project is not None
    return loc.project, ref.store_id, ref


def _write(
    root: str | None, store: str | None, default: bool, value: str | None, build: bool, as_json: bool
) -> int:
    loc = locate(root)
    if loc.error:
        return _fail(as_json, loc.error, root=str(loc.root))
    try:
        project, target, ref = _write_target(loc, store, default)
        result = meshfile.set_recall_engine(project, target, value)
    except UsageError as e:
        return _fail(as_json, str(e), root=str(loc.root))
    except (meshfile.MeshFileError, OSError) as e:
        return _fail(as_json, str(e), root=str(loc.root), mesh_file=_rel(loc, loc.mesh_file))
    index_location.clear_cache()
    loc.doc = None
    payload: dict[str, Any] = {
        "ok": True,
        "changed": result.changed,
        "target": result.target,
        "previous": result.previous,
        "value": result.value,
        "mesh_file": _rel(loc, result.path),
        "project": str(project),
    }
    warnings: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []
    if value is not None:
        warn = unavailable_warning(value)
        if warn:
            warnings.append(warn)
    env_raw = os.environ.get(ep.ENV, "").strip()
    if env_raw:
        info.append({"code": "env_overrides", "level": "info", "message": f"{ep.ENV}={env_raw} overrides atlas-mesh.json in this environment"})
    doc = _load_doc(loc)
    if target is None:
        own = [str(r["id"]) for r in _rows(doc) if isinstance(r.get("recall"), dict) and r["recall"].get("engine")]
        if own:
            info.append(
                {"code": "store_overrides_default", "level": "info", "message": f"stores with their own engine keep it: {', '.join(own)}"}
            )
    elif ref is not None and ref.mounted and value is not None:
        schema, _ = _effective_schema(ref.path)
        if schema is not None and recall_enabled(schema) and value != "bm25":
            pref = ep.EnginePreference(value, "store", f"{result.path} (store {target})")
            info.append(ep.ignored_notice(_preset(schema), pref))
    if value is None:
        kind = "<type>"
        sid = target or "<atlas-id>"
        payload["note"] = (
            f"index files are not deleted; .atlas/indexes/{kind}/{sid}/ can be deleted by hand if no longer needed"
        )
    if warnings:
        payload["warnings"] = warnings
    if info:
        payload["info"] = info
    code = 0
    if build:
        if target is None:
            refs = [
                _ref(project, r)
                for r in _rows(doc)
                if not (isinstance(r.get("recall"), dict) and r["recall"].get("engine"))
            ]
        else:
            refs = [_row_for(loc, target)]
        builds = [build_store(r_) for r_ in refs]
        payload["builds"] = builds
        if any(b.get("status") == "failed" for b in builds):
            payload["ok"] = False
            code = 1
    where = "project default" if target is None else f"store {target}"
    if result.changed:
        lines = [f"{payload['mesh_file']}: {where} recall.engine {result.previous or '(unset)'} -> {value or '(unset)'}"]
    else:
        lines = [f"{payload['mesh_file']}: {where} recall.engine already {value or '(unset)'} (unchanged)"]
    for item in info:
        lines.append(f"info: {item['message']}")
    if payload.get("note"):
        lines.append(f"note: {payload['note']}")
    for b in payload.get("builds") or []:
        lines.append("build " + _build_line(b))
    _emit(as_json, payload, lines)
    return code


def run_set(
    value: str, root: str | None, store: str | None, default: bool, build: bool, as_json: bool
) -> int:
    engine = value.strip().lower()
    if engine not in ep.ENGINES:
        return _fail(as_json, f"engine {value!r} is not allowed; allowed values: {ep.allowed_text()}")
    return _write(root, store, default, engine, build, as_json)


def run_unset(root: str | None, store: str | None, default: bool, as_json: bool) -> int:
    return _write(root, store, default, None, False, as_json)


# --- show / status ----------------------------------------------------------------


def _levels(ref: StoreRef, doc: dict[str, Any] | None, schema: dict[str, Any] | None) -> dict[str, Any]:
    row_recall = (ref.row or {}).get("recall")
    top_recall = (doc or {}).get("recall") if ref.row is not None else None
    return {
        "env": os.environ.get(ep.ENV, "").strip() or None,
        "store": row_recall.get("engine") if isinstance(row_recall, dict) else None,
        "project": top_recall.get("engine") if isinstance(top_recall, dict) else None,
        "default": ep.schema_default(schema),
    }


def describe_store(ref: StoreRef, doc: dict[str, Any] | None) -> dict[str, Any]:
    """Read-only resolution for one store: preference, effective engine, profile and index freshness."""
    out: dict[str, Any] = {"store_id": ref.store_id, "root": str(ref.path), "mounted": ref.mounted}
    if ref.rel:
        out["path"] = ref.rel
    schema, err = _effective_schema(ref.path) if ref.mounted else (None, None)
    if err:
        out["schema_error"] = err
    out["levels"] = _levels(ref, doc, schema)
    try:
        pref = ep.resolve_engine(ref.path, None, schema)
    except ep.EnginePreferenceError as e:
        out["error"] = str(e)
        return out
    out.update(engine_requested=pref.requested, engine_source=pref.source, origin=pref.origin)
    profile = _preset(schema) if schema is not None and recall_enabled(schema) else None
    out["profile"] = profile
    if profile:
        out["engine_effective"] = f"profile:{profile}"
        out["driver_used"] = "sqlite-fts5"
        out["preference_ignored"] = pref.is_preference and pref.requested != "bm25"
        index_engine = "bm25"
    else:
        eff = ep.effective_engine(pref.requested)
        out["engine_effective"] = eff.engine
        out["driver_used"] = eff.driver
        out["preference_ignored"] = False
        out["fallback"] = [{"engine": e, "reason": why} for e, why in eff.unavailable]
        if eff.note:
            out["driver_note"] = eff.note
        index_engine = eff.engine
    if ref.mounted:
        out["index"] = ep.index_status(ref.path, schema, index_engine)
    else:
        idx: dict[str, Any] = {"driver_type": ep.INDEX_TYPES.get(index_engine), "freshness": None, "fresh": None}
        if idx["driver_type"]:
            try:
                idx.update(index_location.describe(ref.path, idx["driver_type"]))
            except (index_location.IndexLocationError, OSError):
                idx["index_dir"] = None
        out["index"] = idx
    return out


def _freshness_text(idx: dict[str, Any], mounted: bool) -> str:
    if not idx.get("driver_type"):
        return "no index needed"
    if not mounted:
        return "n/a (not mounted)"
    text = str(idx.get("freshness"))
    if idx.get("generation"):
        text += f" generation={idx['generation']}"
    if idx.get("digest"):
        text += f" digest={idx['digest']}"
    if idx.get("corpus_digest") and idx.get("freshness") != "fresh":
        text += f" corpus={idx['corpus_digest']}"
    return text


def run_show(root: str | None, store: str | None, as_json: bool) -> int:
    loc = locate(root)
    if loc.error:
        return _fail(as_json, loc.error, root=str(loc.root))
    try:
        ref = _row_for(loc, store) if store else _root_store(loc, need_row=False)
        doc = _load_doc(loc) if ref.row is not None else None
    except UsageError as e:
        return _fail(as_json, str(e), root=str(loc.root))
    info = describe_store(ref, doc)
    if info.get("error"):
        return _fail(as_json, str(info["error"]), root=str(ref.path))
    ignore = indexes_ignore_status(ref.path, loc.project)
    payload = {"ok": True, "mesh_file": _rel(loc, loc.mesh_file) if ref.row is not None else None, **info, "ignore": ignore}
    lv = info["levels"]
    lines = [
        f"store: {ref.store_id}" + (f" ({ref.rel})" if ref.rel else "") + ("" if ref.mounted else " — not mounted"),
        f"  {ep.ENV}: {lv['env'] or '-'}",
        f"  store row:        {lv['store'] or '-'}",
        f"  project default:  {lv['project'] or '-'}",
        f"  built-in default: {lv['default']}",
        f"requested: {info['engine_requested']} (source: {info['engine_source']}; {info['origin']})",
    ]
    eff_line = f"effective: {info['engine_effective']} (driver {info['driver_used']})"
    if info.get("fallback"):
        eff_line += " — " + "; ".join(f"{f['engine']}: {f['reason']}" for f in info["fallback"])
    lines.append(eff_line)
    if info.get("profile"):
        state = "preference ignored" if info.get("preference_ignored") else "profile is authoritative"
        lines.append(f"profile: {info['profile']} ({state})")
    idx = info.get("index") or {}
    lines.append(f"index: {idx.get('index_dir') or '-'} {_freshness_text(idx, ref.mounted)}")
    lines.append(_ignore_line(ignore))
    _emit(as_json, payload, lines)
    return 0


def _ignore_line(ignore: dict[str, Any]) -> str:
    reason = ignore.get("reason")
    return f"ignore: {ignore.get('status')}" + (f" ({reason})" if reason and ignore.get("status") != "ok" else "")


def run_status(root: str | None, as_json: bool) -> int:
    loc = locate(root)
    if loc.error:
        return _fail(as_json, loc.error, root=str(loc.root))
    if loc.project is None:
        refs = [_root_store(loc, need_row=False)]
        doc: dict[str, Any] | None = None
        mode = "standalone"
    else:
        try:
            doc = _load_doc(loc)
        except UsageError as e:
            return _fail(as_json, str(e), root=str(loc.root))
        refs = [_ref(loc.project, row) for row in _rows(doc)]
        mode = "mesh"
    top = (doc or {}).get("recall")
    default = top.get("engine") if isinstance(top, dict) else None
    rows = []
    for ref in refs:
        d = describe_store(ref, doc)
        lv = d.get("levels") or {}
        configured, source = (lv.get("store"), "store") if lv.get("store") else (lv.get("project"), "project") if lv.get("project") else (None, "default")
        idx = d.get("index") or {}
        rows.append(
            {
                "store_id": ref.store_id,
                "path": ref.rel,
                "mounted": ref.mounted,
                "configured": configured,
                "configured_source": source,
                "engine_requested": d.get("engine_requested"),
                "engine_source": d.get("engine_source"),
                "engine_effective": d.get("engine_effective"),
                "profile": d.get("profile"),
                "freshness": idx.get("freshness") if ref.mounted else None,
                "generation": idx.get("generation") if ref.mounted else None,
                "index_dir": idx.get("index_dir"),
                **({"error": d["error"]} if d.get("error") else {}),
            }
        )
    ignore = indexes_ignore_status(refs[0].path if refs else loc.root, loc.project)
    payload = {
        "ok": True,
        "mode": mode,
        "project": str(loc.project) if loc.project else None,
        "mesh_file": _rel(loc, loc.mesh_file),
        "default": default,
        "ignore": ignore,
        "stores": rows,
    }
    lines = [f"project default: {default or '-'}" + (f" ({payload['mesh_file']})" if payload["mesh_file"] else " (standalone store)")]
    header = ("ID", "MOUNTED", "CONFIGURED", "EFFECTIVE", "FRESHNESS", "INDEX")
    table = [header]
    for row in rows:
        conf = f"{row['configured']} ({row['configured_source']})" if row["configured"] else "- (default)"
        if row.get("error"):
            eff, fresh = "error", row["error"]
        else:
            eff = str(row["engine_effective"])
            fresh = row["freshness"] or ("n/a" if not row["mounted"] else "no index needed")
        table.append((row["store_id"], "yes" if row["mounted"] else "no", conf, eff, str(fresh), row["index_dir"] or "-"))
    widths = [max(len(str(r[i])) for r in table) for i in range(len(header))]
    lines += ["  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip() for r in table]
    lines.append(_ignore_line(ignore))
    _emit(as_json, payload, lines)
    return 0
