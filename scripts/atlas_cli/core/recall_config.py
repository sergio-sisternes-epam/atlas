"""Closed recall configuration, built-in profiles and capability matrix."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .jsonutil import StrictJsonError, load_strict, loads_strict
from .schema import skill_root

RECALL_VERSION = 1
DEFAULT_CEILINGS = {
    "max_hits": 100,
    "max_hops": 3,
    "max_nodes": 200,
    "max_edges": 1000,
    "max_evidence_bytes": 65536,
}
DEFAULT_LIMITS = {
    "max_hits": 20,
    "max_hops": 0,
    "max_nodes": 200,
    "max_edges": 1000,
    "max_evidence_bytes": 32768,
}
DEFAULT_WEIGHTS = {"primary": 5.0, "secondary": 2.0, "body": 1.0}

BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "atlas:scan": {
        "description": "Current-tree substring scan without an index",
        "coarse": {"driver": "scan"},
        "rank": {"driver": "scan"},
        "retrieve": {"driver": "pages-graph", "max_hops": 0},
        "limits": dict(DEFAULT_LIMITS),
    },
    "atlas:ranked": {
        "description": "Fused SQLite FTS5 coarse and rank",
        "coarse": {"driver": "sqlite-fts5"},
        "rank": {"driver": "sqlite-fts5", "weights": dict(DEFAULT_WEIGHTS)},
        "retrieve": {"driver": "pages-graph", "max_hops": 0},
        "limits": dict(DEFAULT_LIMITS),
    },
    "atlas:ranked-graph": {
        "description": "FTS5 ranking plus explicit one-hop graph context",
        "coarse": {"driver": "sqlite-fts5"},
        "rank": {"driver": "sqlite-fts5", "weights": dict(DEFAULT_WEIGHTS)},
        "retrieve": {"driver": "pages-graph", "max_hops": 1},
        "limits": {**DEFAULT_LIMITS, "max_hops": 1},
    },
    "atlas:tgrep": {
        "description": "Advanced: tgrep coarse over an Atlas-owned on-disk index; never serve. Limited benefits vs atlas:ranked on small stores",
        "coarse": {"driver": "tgrep"},
        "rank": {"driver": "sqlite-fts5"},
        "retrieve": {"driver": "pages-graph", "max_hops": 0},
        "limits": dict(DEFAULT_LIMITS),
    },
}

DRIVER_CAPABILITIES: dict[str, dict[str, Any]] = {
    "scan": {
        "stages": ["coarse", "rank"],
        "supported": True,
        "fused": True,
    },
    "sqlite-fts5": {
        "stages": ["coarse", "rank"],
        "supported": True,
        "fused": True,
        "requires": "fts5",
    },
    "pages-graph": {
        "stages": ["retrieve"],
        "supported": True,
        "fused": False,
    },
    "tgrep": {
        "stages": ["coarse"],
        "supported": True,
        "fused": False,
        "serve": False,
        "requires": "tgrep_binary",
    },
}


class RecallConfigError(ValueError):
    pass


def schema_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "schemas"


def _load_schema_doc(name: str) -> dict[str, Any]:
    path = schema_dir() / name
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RecallConfigError(f"{name} must be an object")
    return data


def _registry():
    try:
        from referencing import Registry, Resource
    except ImportError as e:
        raise RecallConfigError("referencing package missing") from e
    recall = Resource.from_contents(_load_schema_doc("recall-v1.schema.json"))
    contrib = Resource.from_contents(_load_schema_doc("contribution-v1.schema.json"))
    store = Resource.from_contents(_load_schema_doc("store-v2.schema.json"))
    return (
        Registry()
        .with_resource("https://atlas.local/schemas/recall-v1", recall)
        .with_resource("https://atlas.local/schemas/contribution-v1", contrib)
        .with_resource("https://atlas.local/schemas/store-v2", store)
    )


def validate_against(schema_name: str, data: Any) -> list[str]:
    try:
        import jsonschema
        from jsonschema import Draft202012Validator
    except ImportError as e:
        raise RecallConfigError("jsonschema package missing") from e
    schema = _load_schema_doc(schema_name)
    registry = _registry()
    validator = Draft202012Validator(schema, registry=registry)
    errs = [f"{e.json_path}: {e.message}" for e in validator.iter_errors(data)]
    _ = jsonschema
    return errs


def fts5_available() -> bool:
    import sqlite3

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def driver_supported(name: str) -> tuple[bool, str | None]:
    cap = DRIVER_CAPABILITIES.get(name)
    if cap is None:
        return False, f"unknown_driver: {name}"
    if not cap.get("supported"):
        return False, str(cap.get("reason") or f"unsupported_driver: {name}")
    if cap.get("requires") == "fts5" and not fts5_available():
        return False, "unsupported_capability: sqlite_fts5"
    return True, None


def default_recall_block() -> dict[str, Any]:
    return {
        "version": RECALL_VERSION,
        "enabled": False,
        "preset": None,
        "overrides": {},
        "ceilings": dict(DEFAULT_CEILINGS),
    }


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, val in overlay.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


def _clamp_limits(limits: dict[str, Any], ceilings: dict[str, Any]) -> tuple[dict[str, int], list[str]]:
    out: dict[str, int] = {}
    notes: list[str] = []
    for key, ceiling in ceilings.items():
        raw = limits.get(key, DEFAULT_LIMITS.get(key, ceiling))
        try:
            n = int(raw)
        except (TypeError, ValueError):
            n = int(DEFAULT_LIMITS.get(key, 0))
        cap = int(ceiling)
        if n > cap:
            notes.append(f"limit {key}={n} clamped to host ceiling {cap}")
            n = cap
        if n < 0:
            n = 0
        out[key] = n
    return out, notes


def list_profiles(effective: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    profiles = {k: copy.deepcopy(v) for k, v in BUILTIN_PROFILES.items()}
    if isinstance(effective, dict):
        extra = effective.get("presets") or {}
        if isinstance(extra, dict):
            for name, body in extra.items():
                if isinstance(body, dict):
                    key = str(name)
                    if key in BUILTIN_PROFILES:
                        continue
                    profiles[key] = copy.deepcopy(body)
    return profiles


def resolve_profile(
    effective: dict[str, Any],
    preset: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recall = effective.get("recall") if isinstance(effective.get("recall"), dict) else {}
    chosen = preset if preset is not None else recall.get("preset")
    profiles = list_profiles(effective)
    if chosen:
        if chosen not in profiles:
            raise RecallConfigError(f"unknown preset {chosen!r}")
        base = copy.deepcopy(profiles[chosen])
        provenance = ["preset:" + chosen]
    else:
        chosen = "atlas:ranked"
        base = copy.deepcopy(profiles["atlas:ranked"])
        provenance = ["default:atlas:ranked"]
    host_over = recall.get("overrides") if isinstance(recall.get("overrides"), dict) else {}
    if host_over:
        base = _deep_merge(base, host_over)
        provenance.append("host.overrides")
    if overrides:
        base = _deep_merge(base, overrides)
        provenance.append("request.overrides")
    ceilings = recall.get("ceilings") if isinstance(recall.get("ceilings"), dict) else {}
    merged_ceil = dict(DEFAULT_CEILINGS)
    for k, v in ceilings.items():
        if k not in DEFAULT_CEILINGS:
            continue
        try:
            merged_ceil[k] = int(v)
        except (TypeError, ValueError) as e:
            raise RecallConfigError(f"ceilings.{k} must be an integer") from e
    limits, clamp_notes = _clamp_limits(base.get("limits") or {}, merged_ceil)
    base["limits"] = limits
    for stage in ("coarse", "rank", "retrieve"):
        block = base.get(stage) or {}
        driver = str(block.get("driver") or "")
        ok, reason = driver_supported(driver)
        if not ok:
            raise RecallConfigError(reason or f"unsupported driver {driver}")
    return {
        "preset": chosen,
        "effective": base,
        "provenance": provenance,
        "ceilings": merged_ceil,
        "notes": clamp_notes,
    }


def validate_store_v2(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["store must be an object"]
    errs = validate_against("store-v2.schema.json", data)
    recall = data.get("recall")
    if recall is not None:
        if not isinstance(recall, dict):
            errs.append("recall must be an object")
        else:
            try:
                resolve_profile(data)
            except RecallConfigError as e:
                if recall.get("enabled"):
                    errs.append(str(e))
    return errs


def validate_contribution(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["contribution must be an object"]
    return validate_against("contribution-v1.schema.json", data)


def load_json_file(path: Path) -> Any:
    try:
        return load_strict(path)
    except StrictJsonError as e:
        raise RecallConfigError(str(e)) from e


def parse_json_text(text: str) -> Any:
    try:
        return loads_strict(text)
    except StrictJsonError as e:
        raise RecallConfigError(str(e)) from e


def schema_version(schema: dict[str, Any] | None) -> str:
    if not schema:
        return "1.0"
    return str(schema.get("schema_version") or "1.0").strip() or "1.0"


def recall_enabled(schema: dict[str, Any] | None) -> bool:
    if not schema or schema_version(schema) != "2.0":
        return False
    recall = schema.get("recall") or {}
    return bool(isinstance(recall, dict) and recall.get("enabled"))
