"""Recall configuration and index CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.jsonutil import StrictJsonError, loads_strict
from ..core.overlay import merge_overlays
from ..core.paths import SCHEMA_NAME, store_root
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
from ..core.recall_index import IndexError_, load_current, publish_generation
from ..core.schema import load_schema
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
    path = root / SCHEMA_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RecallConfigError("SCHEMA.json must be an object")
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
    payload = {"ok": True, "root": str(r), "profiles": profiles, "tgrep": tgrep_driver.capability()}
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
        "tgrep": tgrep_driver.capability(),
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
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
    payload = {"ok": True, "root": str(r), **result}
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"published={result.get('published')} generation={result.get('generation')}")
    return 0


def run_probe(root: str | None, query: str, profile: str | None, allow_partial: bool, as_json: bool) -> int:
    r = store_root(root)
    payload, code = run_recall(r, query, profile=profile, allow_partial=allow_partial)
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        if not payload.get("ok"):
            print(payload.get("error"))
        else:
            print(f"hits={payload.get('count')} complete={payload.get('recall', {}).get('complete')}")
    return code
