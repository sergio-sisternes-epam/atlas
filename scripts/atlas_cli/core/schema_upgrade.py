"""SCHEMA 1.0 -> 2.0 upgrade with a store-local compatibility contribution."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from .jsonutil import StrictJsonError, load_strict
from .overlay import SCHEMA_D, overlay_path, receipt_path, write_json, write_receipt
from .paths import SCHEMA_NAME
from .recall_config import default_recall_block, schema_version, validate_store_v2
from .schema import load_schema

KNOWN_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "atlas_id",
        "title",
        "description",
        "structure",
        "compile",
        "templates",
        "types",
        "query",
        "relations",
        "mesh",
        "sources_profile",
        "required_root_fields",
        "recall",
        "bindings",
        "presets",
    }
)
COMPAT_ID = "atlas-compat-v1"
LOCK_NAME = ".atlas-upgrade.lock"


class UpgradeError(ValueError):
    pass


def preview(root: Path) -> dict[str, Any]:
    schema, err = load_schema(root)
    if schema is None:
        raise UpgradeError(err or "missing SCHEMA.json")
    version = schema_version(schema)
    unknown = sorted(k for k in schema.keys() if k not in KNOWN_ROOT_KEYS)
    notes: list[str] = []
    if version == "2.0":
        notes.append("already SCHEMA 2.0")
    if unknown:
        notes.append("unknown root keys block upgrade: " + ", ".join(unknown))
    overlay = _compat_overlay(schema)
    target = _target_schema(schema)
    v2_errs = validate_store_v2(target) if not unknown else []
    return {
        "ok": version != "2.0" and not unknown and not v2_errs,
        "from": version,
        "to": "2.0",
        "unknown_keys": unknown,
        "target_errors": v2_errs,
        "compat_contribution": COMPAT_ID,
        "recall_enabled": False,
        "notes": notes,
        "overlay": overlay,
    }


def _target_schema(schema: dict[str, Any]) -> dict[str, Any]:
    target = deepcopy(schema)
    target["schema_version"] = "2.0"
    if not isinstance(target.get("recall"), dict):
        target["recall"] = default_recall_block()
    else:
        target["recall"]["enabled"] = False
    return target


def _compat_overlay(schema: dict[str, Any]) -> dict[str, Any]:
    compile_cfg = schema.get("compile") if isinstance(schema.get("compile"), dict) else {}
    page_contract = compile_cfg.get("page_contract") if isinstance(compile_cfg, dict) else {}
    by_type = ((schema.get("templates") or {}).get("by_type") or {}) if isinstance(schema.get("templates"), dict) else {}
    bindings: dict[str, Any] = {}
    if isinstance(page_contract, dict) and page_contract:
        bindings["page-contract"] = {
            "kind": "page_contract",
            "predicate": deepcopy(page_contract),
        }
    if isinstance(by_type, dict):
        for tname, block in by_type.items():
            if not isinstance(block, dict):
                continue
            fm = (block.get("frontmatter") or {}).get("required") or []
            if fm:
                bindings[f"type-{tname}"] = {
                    "kind": "page_contract",
                    "applies_to": {"types": [str(tname)]},
                    "predicate": {"required": list(fm)},
                }
    return {
        "contribution_id": COMPAT_ID,
        "claimed_folders": [],
        "bindings": bindings,
        "presets": {},
    }


def apply(root: Path) -> dict[str, Any]:
    pre = preview(root)
    if not pre["ok"]:
        raise UpgradeError(
            "; ".join(pre["notes"] or pre.get("target_errors") or ["upgrade blocked"])
        )
    lock = root / LOCK_NAME
    if lock.is_file():
        schema, _ = load_schema(root)
        if schema and schema_version(schema) == "2.0":
            lock.unlink(missing_ok=True)
        else:
            raise UpgradeError("interrupted upgrade lock present; refusing to continue blindly")
    fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        try:
            os.write(fd, b"schema-upgrade-2.0\n")
        finally:
            os.close(fd)
        schema, err = load_schema(root)
        if schema is None:
            raise UpgradeError(err or "missing SCHEMA.json")
        try:
            live = load_strict(root / SCHEMA_NAME)
        except StrictJsonError as e:
            raise UpgradeError(str(e)) from e
        if live != schema:
            raise UpgradeError("SCHEMA.json is not strict JSON")
        target = _target_schema(schema)
        overlay = _compat_overlay(schema)
        dest = overlay_path(root, COMPAT_ID)
        dest.parent.mkdir(exist_ok=True)
        write_json(dest, overlay)
        write_receipt(
            root,
            COMPAT_ID,
            [f"{SCHEMA_D}/{COMPAT_ID}.json", f"{SCHEMA_D}/{COMPAT_ID}.receipt.json"],
            types=[],
        )
        schema_path = root / SCHEMA_NAME
        tmp = schema_path.with_suffix(".json.upgrade")
        tmp.write_text(json.dumps(target, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, schema_path)
    except Exception:
        if lock.exists():
            # leave lock for fail-closed detection
            pass
        raise
    else:
        lock.unlink(missing_ok=True)
    return {
        "ok": True,
        "from": pre["from"],
        "to": "2.0",
        "compat_contribution": COMPAT_ID,
        "recall_enabled": False,
        "schema": SCHEMA_NAME,
    }
