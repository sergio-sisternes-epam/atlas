"""`atlas memory-migrate` — the pre-beta -> beta.3 contract-file migration path.

This is distinct from `atlas migrate` (content into staging) and from the
document-era-to-memory-layers content migration described in
references/paths/memory-migrate.md. This command rewrites the root contract file (SCHEMA.json -> CONTRACT.json)
and adds missing beta.3 schema pages for gist-bearing folders; it never
rewrites existing pages.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.frontmatter import FrontmatterError, read_page
from ..core.paths import CONTRACT_NAME, RESERVED, SCHEMA_NAME, iter_concept_md, rel, store_root
from ..core.recall_config import schema_version
from ..core.schema import (
    BETA3_LAYERS,
    BETA3_RELEASE,
    classify_lineage,
    find_contract_path,
    staging_dir_name,
)

REFUSE_BATCH_TOKENS = frozenset({"", "migrate everything"})
LEGACY_BATCH = "contract-file"
MEMORY_PAGE_TYPES = frozenset({"memory", "gist", "frame"})
SCHEMA_PAGE_BODY = (
    "This schema page groups the gists in this folder for consistent "
    "navigation and interpretation."
)


def _read_concept_pages(root: Path, schema: dict) -> list[tuple[Path, dict]]:
    pages: list[tuple[Path, dict]] = []
    version = schema_version(schema)
    for path in iter_concept_md(root, staging_dir_name(schema)):
        if path.name in RESERVED:
            continue
        try:
            meta, _ = read_page(path, version)
        except FrontmatterError:
            continue
        if meta:
            pages.append((path, meta))
    return pages


def _schema_pages_to_create(
    root: Path, pages: list[tuple[Path, dict]]
) -> tuple[list[tuple[Path, list[str]]], dict | None]:
    gists_by_folder: dict[str, list[str]] = {}
    schemas_by_folder: dict[str, list[str]] = {}
    for path, meta in pages:
        folder = str(path.parent.resolve().relative_to(root.resolve())).replace("\\", "/")
        ptype = str(meta.get("type") or "").strip()
        if ptype == "gist":
            gists_by_folder.setdefault(folder, []).append(rel(root, path))
        elif ptype == "schema":
            schemas_by_folder.setdefault(folder, []).append(rel(root, path))

    additions: list[tuple[Path, list[str]]] = []
    for folder in sorted(set(gists_by_folder) | set(schemas_by_folder)):
        existing_schemas = schemas_by_folder.get(folder, [])
        if len(existing_schemas) > 1:
            return [], {
                "id": "schema_folder",
                "path": folder or ".",
                "msg": (
                    f"folder {folder or '.'!r} already has {len(existing_schemas)} "
                    "type=schema pages; refusing to make the schema_folder invariant worse"
                ),
            }
        gist_paths = sorted(gists_by_folder.get(folder, []))
        if not gist_paths or existing_schemas:
            continue

        directory = root if folder == "." else root.joinpath(*folder.split("/"))
        target = directory / "schema.md"
        current = root
        has_symlink_component = current.is_symlink()
        for part in (() if folder == "." else folder.split("/")):
            current = current / part
            has_symlink_component = has_symlink_component or current.is_symlink()
        if has_symlink_component or target.is_symlink():
            return [], {
                "id": "schema_symlink",
                "path": rel(root, target),
                "msg": f"{rel(root, target)} would be written through a symlink; refusing",
            }
        if target.exists():
            return [], {
                "id": "schema_path_exists",
                "path": rel(root, target),
                "msg": f"{rel(root, target)} already exists; refusing to overwrite it",
            }
        additions.append((target, gist_paths))
    return additions, None


def _write_schema_page(path: Path, gist_paths: list[str]) -> None:
    relates = "".join(
        f"  - path: {json.dumps(gist_path, ensure_ascii=False)}\n"
        "    kind: related\n"
        for gist_path in gist_paths
    )
    path.write_text(
        "---\n"
        "type: schema\n"
        "title: Gist schema\n"
        "created: 2026-10-04\n"
        "relates_to:\n"
        f"{relates}"
        "---\n\n"
        f"{SCHEMA_PAGE_BODY}\n",
        encoding="utf-8",
    )


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
    contract_lineage = classify_lineage(contract_name, schema)
    lineage = contract_lineage
    if lineage == "pre-beta" and any(
        str(meta.get("type") or "").strip() in MEMORY_PAGE_TYPES
        for _, meta in _read_concept_pages(r, schema)
    ):
        lineage = "in-beta"

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
    if contract_lineage == "current":
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

    if contract_lineage == "in-beta":
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

    # contract_lineage == "pre-beta"
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
    # atlas_release/memory.layers to the beta.3 shape. Existing pages stay
    # untouched; missing folder schema pages are added below.
    new_path = r / CONTRACT_NAME
    if new_path.is_symlink():
        # is_file() follows symlinks and is False for a broken link, which would
        # otherwise let write_text() follow the link (even outside the root)
        # before the stale SCHEMA.json is deleted. Refuse unconditionally.
        payload = {
            "ok": False,
            "root": str(r),
            "operation": "apply",
            "contract_file": contract_name,
            "lineage": lineage,
            "error": f"{CONTRACT_NAME} is a symlink; refusing to write through it",
            "findings": [
                {
                    "id": "contract_symlink",
                    "path": CONTRACT_NAME,
                    "msg": f"{CONTRACT_NAME} is a symlink; refusing to write through it",
                }
            ],
        }
        _print(as_json, payload)
        return 2

    schema_pages, schema_error = _schema_pages_to_create(r, _read_concept_pages(r, schema))
    if schema_error:
        payload = {
            "ok": False,
            "root": str(r),
            "operation": "apply",
            "contract_file": contract_name,
            "lineage": lineage,
            "error": schema_error["msg"],
            "findings": [schema_error],
        }
        _print(as_json, payload)
        return 2

    schema["atlas_release"] = BETA3_RELEASE
    memory = schema.get("memory") if isinstance(schema.get("memory"), dict) else {}
    memory["layers"] = list(BETA3_LAYERS)
    schema["memory"] = memory
    new_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    if contract_path != new_path:
        contract_path.unlink()
    for schema_path, gist_paths in schema_pages:
        _write_schema_page(schema_path, gist_paths)
    payload = {
        "ok": True,
        "root": str(r),
        "operation": "apply",
        "batch": batch_value,
        "contract_file": CONTRACT_NAME,
        "lineage": "current",
        "notes": [
            f"renamed {SCHEMA_NAME} -> {CONTRACT_NAME}; set atlas_release={BETA3_RELEASE}",
            *[f"created schema page {rel(r, path)}" for path, _ in schema_pages],
        ],
    }
    _print(as_json, payload)
    return 0
