"""Recall configuration and index CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..core.jsonutil import StrictJsonError, loads_strict
from ..core.overlay import merge_overlays
from ..core.paths import store_root
from ..core.recall import run_recall
from ..core.recall_config import (
    DRIVER_CAPABILITIES,
    RecallConfigError,
    default_recall_block,
    driver_supported,
    list_profiles,
    recall_enabled,
    resolve_profile,
    schema_version,
    validate_against,
    validate_store_v2,
)
from ..core import index_location, meshfile
from ..core.engine_preference import (
    ENGINES,
    EnginePreferenceError,
    INDEX_TYPES,
    effective_engine,
    ignored_notice,
    index_status,
    refresh_preferred,
    resolve_engine,
)
from ..core.ignore_guard import ensure_index_ignored, ensure_indexes_ignored
from ..core.recall_index import (
    IndexError_,
    active_generation,
    legacy_warning,
    load_current,
    publish_generation,
)
from ..core.schema import find_contract_path, load_schema
from ..core.drivers import tgrep as tgrep_driver


def _print(as_json: bool, payload: dict[str, Any]) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    if payload.get("ok") is False:
        print(f"atlas recall — FAIL: {payload.get('error')}")
        return
    print("atlas recall — ok")
    for key in ("preset", "enabled", "version", "error"):
        if payload.get(key) is not None:
            print(f"{key}: {payload[key]}")
    for line in payload.get("notes") or []:
        print(line)


def _effective(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    schema, err = load_schema(root)
    if schema is None:
        return None, err
    merged, critical, _ = merge_overlays(schema, root)
    if critical:
        return None, "; ".join(i["msg"] for i in critical)
    return merged, None


def _write_recall(root: Path, recall: dict[str, Any]) -> None:
    path, err = find_contract_path(root)
    if err or path is None:
        raise RecallConfigError(err or "missing contract file")
    try:
        data = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, StrictJsonError) as e:
        raise RecallConfigError(str(e)) from e
    if not isinstance(data, dict):
        raise RecallConfigError(f"{path.name} must be an object")
    if schema_version(data) != "2.0":
        raise RecallConfigError("SCHEMA 2.0 required")
    data["recall"] = recall
    merged, critical, _ = merge_overlays(data, root)
    if critical:
        raise RecallConfigError("; ".join(i["msg"] for i in critical))
    errs = validate_store_v2(merged)
    if errs:
        raise RecallConfigError("; ".join(errs))
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def run_profiles(root: str | None, as_json: bool = False) -> int:
    r = store_root(root)
    schema, err = _effective(r)
    if schema is None:
        _print(as_json, {"ok": False, "error": err, "root": str(r)})
        return 2
    profiles = {}
    for name, body in list_profiles(schema).items():
        drivers = [
            str((body.get(stage) or {}).get("driver") or "")
            for stage in ("coarse", "rank", "retrieve")
        ]
        unsupported = []
        for drv in drivers:
            if not drv:
                continue
            ok, reason = driver_supported(drv)
            if not ok:
                unsupported.append(reason or drv)
        profiles[name] = {
            "description": body.get("description"),
            "drivers": {
                "coarse": (body.get("coarse") or {}).get("driver"),
                "rank": (body.get("rank") or {}).get("driver"),
                "retrieve": (body.get("retrieve") or {}).get("driver"),
            },
            "supported": not unsupported,
            "unsupported": unsupported,
        }
    payload = {"ok": True, "root": str(r), "profiles": profiles, "tgrep": tgrep_driver.capability(store=r)}
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print("atlas recall profiles")
        for name, info in profiles.items():
            flag = "ok" if info["supported"] else "unsupported"
            print(f"  {name} [{flag}]")
    return 0


def run_show(root: str | None, as_json: bool = False) -> int:
    r = store_root(root)
    schema, err = _effective(r)
    if schema is None:
        _print(as_json, {"ok": False, "error": err, "root": str(r)})
        return 2
    try:
        resolved = resolve_profile(schema)
    except RecallConfigError as e:
        _print(as_json, {"ok": False, "error": str(e), "root": str(r)})
        return 2
    payload = {
        "ok": True,
        "root": str(r),
        "schema_version": schema_version(schema),
        "enabled": recall_enabled(schema),
        "preset": resolved["preset"],
        "provenance": resolved["provenance"],
        "effective": resolved["effective"],
        "ceilings": resolved["ceilings"],
        "notes": resolved["notes"],
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"enabled={payload['enabled']} preset={payload['preset']}")
        print("provenance: " + ", ".join(payload["provenance"]))
    return 0


def run_status(root: str | None, as_json: bool = False) -> int:
    r = store_root(root)
    schema, err = _effective(r)
    caps = {name: {**cap, "available": driver_supported(name)[0]} for name, cap in DRIVER_CAPABILITIES.items()}
    payload = {
        "ok": schema is not None,
        "root": str(r),
        "error": err,
        "schema_version": schema_version(schema) if schema else None,
        "enabled": recall_enabled(schema) if schema else False,
        "capabilities": caps,
        "generation": load_current(r),
        "tgrep": tgrep_driver.capability(store=r),
    }
    try:
        payload.update(index_location.describe(r, "fts5"))
    except (IndexError_, OSError):
        pass
    active = active_generation(r)
    if active is not None and active.legacy:
        payload["warnings"] = [legacy_warning(r)]
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        for item in payload.get("warnings") or []:
            print(f"warning: {index_location.warning_text(item)}", file=sys.stderr)
        if payload.get("index_dir"):
            print(f"index: {payload['index_dir']}")
        print(f"schema={payload['schema_version']} enabled={payload['enabled']}")
        print(f"tgrep: {payload['tgrep'].get('reason') or payload['tgrep'].get('binary') or 'unavailable'}")
        gen = payload["generation"]
        if gen:
            print(f"generation: {gen.get('generation')} digest={gen.get('corpus_digest')}")
        else:
            print("generation: none")
    return 0 if schema is not None else 2


def run_validate(root: str | None, config: str | None, as_json: bool = False) -> int:
    r = store_root(root)
    try:
        if config:
            path = Path(config)
            try:
                data = loads_strict(path.read_text(encoding="utf-8"))
            except (OSError, StrictJsonError) as e:
                _print(as_json, {"ok": False, "error": str(e), "root": str(r)})
                return 2
            errs = validate_against("recall-v1.schema.json", data)
        else:
            schema, err = _effective(r)
            if schema is None:
                _print(as_json, {"ok": False, "error": err, "root": str(r)})
                return 2
            errs = validate_store_v2(schema) if schema_version(schema) == "2.0" else []
            if schema_version(schema) != "2.0":
                errs = ["SCHEMA is not 2.0"]
    except RecallConfigError as e:
        _print(as_json, {"ok": False, "error": str(e), "root": str(r)})
        return 2
    payload = {"ok": not errs, "root": str(r), "errors": errs}
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print("ok" if not errs else "\n".join(errs))
    return 0 if not errs else 2


def run_activate(root: str | None, profile: str, as_json: bool = False) -> int:
    r = store_root(root)
    schema, err = _effective(r)
    if schema is None:
        _print(as_json, {"ok": False, "error": err, "root": str(r)})
        return 2
    if schema_version(schema) != "2.0":
        _print(as_json, {"ok": False, "error": "SCHEMA 2.0 required", "root": str(r)})
        return 2
    try:
        resolve_profile(schema, preset=profile)
    except RecallConfigError as e:
        _print(as_json, {"ok": False, "error": str(e), "root": str(r)})
        return 2
    recall = schema.get("recall") if isinstance(schema.get("recall"), dict) else default_recall_block()
    recall = dict(recall)
    recall["version"] = 1
    recall["enabled"] = True
    recall["preset"] = profile
    try:
        _write_recall(r, recall)
    except RecallConfigError as e:
        _print(as_json, {"ok": False, "error": str(e), "root": str(r)})
        return 2
    _print(as_json, {"ok": True, "root": str(r), "enabled": True, "preset": profile})
    return 0


def run_disable(root: str | None, as_json: bool = False) -> int:
    r = store_root(root)
    schema, err = load_schema(r)
    if schema is None:
        _print(as_json, {"ok": False, "error": err, "root": str(r)})
        return 2
    if schema_version(schema) != "2.0":
        _print(as_json, {"ok": False, "error": "SCHEMA 2.0 required", "root": str(r)})
        return 2
    recall = schema.get("recall") if isinstance(schema.get("recall"), dict) else default_recall_block()
    recall = dict(recall)
    recall["enabled"] = False
    try:
        _write_recall(r, recall)
    except RecallConfigError as e:
        _print(as_json, {"ok": False, "error": str(e), "root": str(r)})
        return 2
    _print(as_json, {"ok": True, "root": str(r), "enabled": False, "preset": recall.get("preset")})
    return 0


def run_index_build(root: str | None, as_json: bool = False) -> int:
    r = store_root(root)
    schema, err = _effective(r)
    if schema is None:
        _print(as_json, {"ok": False, "error": err, "root": str(r)})
        return 2
    try:
        result = publish_generation(r, schema, focused=False)
    except (IndexError_, Exception) as e:
        _print(as_json, {"ok": False, "error": str(e), "root": str(r)})
        return 2
    payload = {"ok": True, "root": str(r), **index_location.describe(r, "fts5"), **result}
    info = [item for item in (ensure_indexes_ignored(r), ensure_index_ignored(r)) if item]
    for item in refresh_preferred(r, schema):
        if item.get("level") == "warning":
            payload.setdefault("warnings", []).append(item)
        else:
            info.append(item)
    if info:
        payload["info"] = info
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"published={result.get('published')} generation={result.get('generation')}")
        if payload.get("index_dir"):
            print(f"index: {payload['index_dir']}")
    return 0


def run_probe(root: str | None, query: str, profile: str | None, allow_partial: bool, as_json: bool) -> int:
    r = store_root(root)
    payload, code = run_recall(r, query, profile=profile, allow_partial=allow_partial)
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        for item in payload.get("warnings") or []:
            print(f"warning: {index_location.warning_text(item)}", file=sys.stderr)
        if not payload.get("ok"):
            print(payload.get("error"))
        else:
            print(f"hits={payload.get('count')} complete={payload.get('recall', {}).get('complete')}")
    return code


def run_engine(root: str | None, as_json: bool = False) -> int:
    """Read-only: resolved preference, source, effective engine, index dir and freshness."""
    r = store_root(root)
    schema, err = _effective(r)
    try:
        pref = resolve_engine(r, None, schema)
    except EnginePreferenceError as e:
        _print(as_json, {"ok": False, "error": str(e), "root": str(r)})
        return 2
    payload: dict[str, Any] = {
        "ok": True,
        "root": str(r),
        "engine_requested": pref.requested,
        "engine_source": pref.source,
        "origin": pref.origin,
        "mesh_file": pref.mesh_file,
        "store_id": pref.store_id,
    }
    if err:
        payload["schema_error"] = err
    if schema is not None and recall_enabled(schema):
        try:
            preset = resolve_profile(schema)["preset"]
        except RecallConfigError:
            preset = (schema.get("recall") or {}).get("preset")
        payload["profile"] = preset
        payload["engine_effective"] = f"profile:{preset}"
        payload["driver_used"] = "sqlite-fts5"
        payload["index"] = index_status(r, schema, "bm25")
        if pref.is_preference and pref.requested != "bm25":
            payload["info"] = [ignored_notice(str(preset), pref)]
    else:
        eff = effective_engine(pref.requested)
        payload["engine_effective"] = eff.engine
        payload["driver_used"] = eff.driver
        if eff.note:
            payload["driver_note"] = eff.note
        payload["persist_index"] = pref.persist and eff.engine in INDEX_TYPES
        payload["index"] = index_status(r, schema, eff.engine)
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"requested: {pref.requested} (source: {pref.source}; {pref.origin})")
        print(f"effective: {payload['engine_effective']} driver={payload['driver_used']}")
        if payload.get("driver_note"):
            print(f"note: {payload['driver_note']}")
        for item in payload.get("info") or []:
            print(f"info: {item['message']}")
        idx = payload.get("index") or {}
        if idx.get("driver_type"):
            print(f"index: {idx.get('index_dir')} fresh={idx.get('fresh')} generation={idx.get('generation')}")
        else:
            print("index: none (grep needs no index)")
    return 0


def run_engine_set(root: str | None, value: str, project: bool, as_json: bool = False) -> int:
    """Write ``recall.engine`` on the store's mesh row (or the project default) atomically."""
    r = store_root(root)
    engine = None if value.lower() in ("default", "none", "unset") else value.lower()
    if engine is not None and engine not in ENGINES:
        _print(as_json, {"ok": False, "error": f"engine {value!r} is not allowed; allowed values: {', '.join(ENGINES)}", "root": str(r)})
        return 2
    match = index_location.mesh_match(r)
    if match is None:
        _print(
            as_json,
            {
                "ok": False,
                "error": (
                    "store has no row in any atlas-mesh.json above it; set ATLAS_RECALL_ENGINE "
                    "or pass --engine instead"
                ),
                "root": str(r),
            },
        )
        return 2
    target = None if project else str(match.row.get("id"))
    try:
        path = meshfile.set_recall_engine(match.directory, target, engine)
    except (meshfile.MeshFileError, OSError) as e:
        _print(as_json, {"ok": False, "error": str(e), "root": str(r)})
        return 2
    index_location.clear_cache()
    payload = {
        "ok": True,
        "root": str(r),
        "mesh_file": str(path),
        "scope": "project" if project else "store",
        "store_id": target,
        "engine": engine,
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        where = "project default" if project else f"store {target}"
        print(f"{path}: {where} recall.engine = {engine or '(unset)'}")
    return 0
