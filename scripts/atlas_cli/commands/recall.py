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
from ..core import index_location
from ..core.recall_index import (
    IndexError_,
    active_generation,
    legacy_warning,
    load_current,
)
from ..core.schema import find_contract_path, load_schema
from ..core.schema_upgrade import (
    RECALL_LOCK_TAG,
    acquire_store_lock,
    lock_held_message,
    release_store_lock,
)
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


def _locked(r: Path, as_json: bool, body) -> int:
    """Run a recall contract read-modify-write under the shared store lock.

    The contract is read and validated only inside ``body``, after the lock is
    taken. On an exception, keep the lock: a partial write needs an operator to
    check the store.
    """
    if not r.is_dir():
        return body()
    try:
        lock = acquire_store_lock(r, RECALL_LOCK_TAG)
    except FileExistsError:
        _print(as_json, {"ok": False, "error": lock_held_message(r), "root": str(r)})
        return 2
    except OSError as e:
        _print(as_json, {"ok": False, "error": f"cannot lock store: {e}", "root": str(r)})
        return 2
    code = body()
    release_store_lock(lock)
    return code


def run_activate(root: str | None, profile: str, as_json: bool = False) -> int:
    r = store_root(root)
    return _locked(r, as_json, lambda: _activate_locked(r, profile, as_json))


def _activate_locked(r: Path, profile: str, as_json: bool) -> int:
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
    return _locked(r, as_json, lambda: _disable_locked(r, as_json))


def _disable_locked(r: Path, as_json: bool) -> int:
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
    """Deprecated alias of ``atlas index build`` for the store from --root (removal after 0.14.x)."""
    from .index import run_build

    return run_build(root, None, False, False, as_json, deprecated=True)


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
