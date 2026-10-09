"""SCHEMA 1.0 -> 2.0 upgrade with a store-local compatibility contribution."""

from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .jsonutil import StrictJsonError, load_strict
from .overlay import (
    SCHEMA_D,
    list_overlays,
    load_overlay,
    merge_overlays,
    overlay_path,
    receipt_path,
    write_json,
    write_receipt,
)
from .recall_config import (
    RecallConfigError,
    default_recall_block,
    schema_version,
    validate_contribution,
    validate_store_v2,
)
from .schema import find_contract_path, load_schema

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
        "memory",
        "atlas_release",
    }
)
COMPAT_ID = "atlas-compat-v1"
LOCK_NAME = ".atlas-upgrade.lock"
UPGRADE_LOCK_TAG = "schema-upgrade-2.0"
INSTALL_LOCK_TAG = "schema-install"
UNINSTALL_LOCK_TAG = "schema-uninstall"
NEW_LOCK_TAG = "schema-new"
MEMORY_RUNG_LOCK_TAG = "schema-memory-rung"
INIT_FORCE_LOCK_TAG = "init-force"
MEMORY_MIGRATE_LOCK_TAG = "memory-migrate-apply"


class UpgradeError(ValueError):
    pass


@dataclass(frozen=True)
class StoreLock:
    path: Path
    content: str


def acquire_store_lock(root: Path, tag: str) -> StoreLock:
    """Create the store's upgrade/install lock exclusively; FileExistsError if held.

    The lock carries a unique token so that only its owner ever removes it.
    """
    path = root / LOCK_NAME
    content = f"{tag} {uuid.uuid4().hex}\n"
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)
    return StoreLock(path, content)


def release_store_lock(lock: StoreLock) -> bool:
    """Remove the lock only if it is still the one this process created."""
    try:
        if lock.path.read_text(encoding="utf-8") != lock.content:
            return False
    except OSError:
        return False
    lock.path.unlink(missing_ok=True)
    return True


def lock_held_message(root: Path) -> str:
    """Explain an existing lock. Locks are never reclaimed automatically."""
    try:
        holder = (root / LOCK_NAME).read_text(encoding="utf-8").split()[0]
    except (OSError, IndexError):
        holder = ""
    if holder == INSTALL_LOCK_TAG:
        what = "a schema install is running or was interrupted"
    elif holder == UPGRADE_LOCK_TAG:
        what = "a schema upgrade is running or was interrupted"
    elif holder == UNINSTALL_LOCK_TAG:
        what = "a schema uninstall is running or was interrupted"
    elif holder == NEW_LOCK_TAG:
        what = "a schema new is running or was interrupted"
    elif holder == MEMORY_RUNG_LOCK_TAG:
        what = "a schema memory-rung is running or was interrupted"
    elif holder == INIT_FORCE_LOCK_TAG:
        what = "an init --force is running or was interrupted"
    elif holder == MEMORY_MIGRATE_LOCK_TAG:
        what = "a memory-migrate apply is running or was interrupted"
    else:
        what = "an Atlas command that writes the contract file or schema.d/ is running or was interrupted"
    return (
        f"{LOCK_NAME} present: {what}; retry when it finishes. Remove the lock only if "
        "no Atlas command is running and the contract file and schema.d/ have been checked"
    )


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
    if not unknown and not v2_errs:
        # Installed overlays must also hold under 2.0 rules, or compile fails after upgrade.
        merged, critical, _ = merge_overlays(target, root)
        v2_errs = [f"installed overlays: {i['path']}: {i['id']}: {i['msg']}" for i in critical]
        v2_errs += [f"installed overlays: {e}" for e in validate_store_v2(merged)]
        v2_errs += _overlay_envelope_errors(root)
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


def _overlay_envelope_errors(root: Path) -> list[str]:
    """Check every installed overlay against contribution-v1, as a 2.0 install would."""
    errs: list[str] = []
    for cid in list_overlays(root):
        if cid == COMPAT_ID:
            # Replaced by the overlay this upgrade writes.
            continue
        ov, err = load_overlay(root, cid)
        if err or ov is None:
            continue  # already reported by merge_overlays
        relp = f"{SCHEMA_D}/{cid}.json"
        try:
            cerrs = validate_contribution(ov)
        except RecallConfigError as e:
            cerrs = [str(e)]
        errs += [f"installed overlays: {relp}: overlay_contribution: {e}" for e in cerrs]
    return errs


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
    # Any existing lock is held; it is never reclaimed from contract state.
    try:
        lock = acquire_store_lock(root, UPGRADE_LOCK_TAG)
    except FileExistsError as e:
        raise UpgradeError(lock_held_message(root)) from e
    # Every other writer of schema.d/ or the contract file on an existing store takes the
    # same lock, so the overlay set and contract are stable from here on.
    # Recheck it before any write; nothing is written yet, so release on refusal.
    try:
        pre = preview(root)
    except Exception:
        release_store_lock(lock)
        raise
    if not pre["ok"]:
        release_store_lock(lock)
        raise UpgradeError(
            "; ".join(pre["notes"] or pre.get("target_errors") or ["upgrade blocked"])
        )
    try:
        schema, err = load_schema(root)
        if schema is None:
            raise UpgradeError(err or "missing SCHEMA.json or CONTRACT.json")
        contract_path, path_err = find_contract_path(root)
        if path_err or contract_path is None:
            raise UpgradeError(path_err or "missing SCHEMA.json or CONTRACT.json")
        try:
            live = load_strict(contract_path)
        except StrictJsonError as e:
            raise UpgradeError(str(e)) from e
        if live != schema:
            raise UpgradeError(f"{contract_path.name} is not strict JSON")
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
        tmp = contract_path.with_suffix(".json.upgrade")
        tmp.write_text(json.dumps(target, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, contract_path)
    except Exception:
        # Leave the lock: a partial upgrade needs an operator to check the store.
        raise
    else:
        release_store_lock(lock)
    return {
        "ok": True,
        "from": pre["from"],
        "to": "2.0",
        "compat_contribution": COMPAT_ID,
        "recall_enabled": False,
        "schema": contract_path.name,
    }
