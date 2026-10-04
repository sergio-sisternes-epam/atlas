"""`atlas memory-migrate` — the pre-beta -> beta.3 contract-file migration path.

This is distinct from `atlas migrate` (content into staging) and from the
document-era-to-memory-layers content migration described in
references/paths/memory-migrate.md. This command only ever rewrites the
store's root contract file (SCHEMA.json -> CONTRACT.json) and its stamp; it
never rewrites other pages.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.paths import CONTRACT_NAME, SCHEMA_NAME, store_root
from ..core.schema import (
    BETA3_LAYERS,
    BETA3_RELEASE,
    classify_lineage,
    find_contract_path,
)

REFUSE_BATCH_TOKENS = frozenset({"", "migrate everything"})
LEGACY_BATCH = "contract-file"


def _print(as_json: bool, payload: dict) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    ok = payload.get("ok")
    print(f"atlas memory-migrate — {'ok' if ok else 'FAIL'}")
    if payload.get("error"):
        print(payload["error"])
    if payload.get("lineage"):
        print(f"lineage: {payload['lineage']}")


def run(
    root: str | None,
    operation: str,
    batch: str | None = None,
    as_json: bool = False,
) -> int:
    r = store_root(root)
    contract_path, find_err = find_contract_path(r)
    if find_err or contract_path is None:
        payload = {
            "ok": False,
            "root": str(r),
            "operation": operation,
            "error": find_err or "missing contract file",
            "findings": [{"id": "schema_present", "path": f"{SCHEMA_NAME}|{CONTRACT_NAME}", "msg": find_err or "missing contract file"}],
        }
        _print(as_json, payload)
        return 2

    try:
        schema = json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        payload = {
            "ok": False,
            "root": str(r),
            "operation": operation,
            "error": f"invalid JSON in {contract_path.name}: {e}",
        }
        _print(as_json, payload)
        return 2
    if not isinstance(schema, dict):
        payload = {
            "ok": False,
            "root": str(r),
            "operation": operation,
            "error": f"{contract_path.name} must be a JSON object",
        }
        _print(as_json, payload)
        return 2

    contract_name = contract_path.name
    lineage = classify_lineage(contract_name, schema)

    if operation in ("assess", "inventory"):
        payload = {
            "ok": True,
            "root": str(r),
            "operation": operation,
            "contract_file": contract_name,
            "lineage": lineage,
            "notes": ["write nothing"],
        }
        _print(as_json, payload)
        return 0

    if operation != "apply":
        payload = {"ok": False, "root": str(r), "error": f"unsupported --operation {operation}"}
        _print(as_json, payload)
        return 2

    # --- apply ---
    if lineage == "current":
        payload = {
            "ok": True,
            "root": str(r),
            "operation": "apply",
            "contract_file": contract_name,
            "lineage": lineage,
            "notes": ["already current; no-op write"],
        }
        _print(as_json, payload)
        return 0

    if lineage == "in-beta":
        payload = {
            "ok": False,
            "root": str(r),
            "operation": "apply",
            "contract_file": contract_name,
            "lineage": lineage,
            "error": "in-beta stores are not eligible for the pre-beta -> beta.3 contract-file migration",
            "findings": [
                {
                    "id": "in_beta_not_legacy",
                    "path": contract_name,
                    "msg": (
                        "apply is only for pre-beta stores; this store is already in-beta "
                        "(atlas_release 0.13.0-beta/0.13.0-beta.2 or memory.layers "
                        "[frame, gist, page]) and was not rewritten"
                    ),
                }
            ],
        }
        _print(as_json, payload)
        return 2

    # lineage == "pre-beta"
    batch_value = (batch or "").strip()
    if batch_value.lower() in REFUSE_BATCH_TOKENS:
        payload = {
            "ok": False,
            "root": str(r),
            "operation": "apply",
            "contract_file": contract_name,
            "lineage": lineage,
            "error": "refusing an unscoped or unattested 'migrate everything' request; pass an explicit --batch",
            "findings": [
                {
                    "id": "batch_required",
                    "path": contract_name,
                    "msg": "apply needs an explicit --batch; no batch or 'migrate everything' writes nothing",
                }
            ],
        }
        _print(as_json, payload)
        return 2

    if batch_value != LEGACY_BATCH:
        payload = {
            "ok": False,
            "root": str(r),
            "operation": "apply",
            "contract_file": contract_name,
            "lineage": lineage,
            "error": f"unsupported --batch {batch_value!r}; only {LEGACY_BATCH!r} is implemented",
        }
        _print(as_json, payload)
        return 2

    # batch == "contract-file": rename SCHEMA.json -> CONTRACT.json, stamp
    # atlas_release/memory.layers to the beta.3 shape. Other pages untouched.
    new_path = r / CONTRACT_NAME
    schema["atlas_release"] = BETA3_RELEASE
    memory = schema.get("memory") if isinstance(schema.get("memory"), dict) else {}
    memory["layers"] = list(BETA3_LAYERS)
    schema["memory"] = memory
    new_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    if contract_path != new_path:
        contract_path.unlink()
    payload = {
        "ok": True,
        "root": str(r),
        "operation": "apply",
        "batch": batch_value,
        "contract_file": CONTRACT_NAME,
        "lineage": "current",
        "notes": [f"renamed {SCHEMA_NAME} -> {CONTRACT_NAME}; set atlas_release={BETA3_RELEASE}"],
    }
    _print(as_json, payload)
    return 0
