"""`atlas memory-migrate` — the pre-beta -> current contract-file migration path.

This is distinct from `atlas migrate` (content into staging) and from the
document-era-to-memory-layers content migration described in
references/paths/memory-migrate.md. This command rewrites the root contract file (SCHEMA.json -> CONTRACT.json)
and adds missing schema pages for gist-bearing folders; existing pages are
not rewritten. New current-shape pages use suffixes as search handles.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from ..core.frontmatter import FrontmatterError, read_page, split_fm, split_fm_v2
from ..core.paths import CONTRACT_NAME, RESERVED, SCHEMA_NAME, iter_concept_md, rel, store_root
from ..core.recall_config import schema_version
from ..core.schema import (
    BETA3_LAYERS,
    CURRENT_RELEASE,
    classify_lineage,
    find_contract_path,
    staging_dir_name,
)
from .validate import MD_LINK, WIKILINK

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
        gist_paths = sorted(gists_by_folder.get(folder, []))
        if not gist_paths or existing_schemas:
            continue

        directory = root if folder == "." else root.joinpath(*folder.split("/"))
        target = directory / "schema.schema.md"
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
        index_path = directory / "index.md"
        if index_path.is_symlink():
            return [], {
                "id": "schema_symlink",
                "path": rel(root, index_path),
                "msg": f"{rel(root, index_path)} is a symlink; refusing to write through it",
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


def _schema_cue_exists(index_path: Path, schema_path: Path, index_text: str) -> bool:
    index_targets = [
        match.group(2).strip().split()[0].strip("\"'")
        for match in MD_LINK.finditer(index_text)
    ]
    index_targets.extend(match.group(1).strip() for match in WIKILINK.finditer(index_text))
    for target in index_targets:
        if target.startswith(("http://", "https://", "atlas://", "#")):
            continue
        local_target = target.split("#", 1)[0].split("?", 1)[0]
        if not local_target:
            continue
        candidate = (index_path.parent / local_target).resolve()
        if candidate == schema_path.resolve():
            return True
    return False


def _converted_frame_text(
    meta: dict, body: str, gist_paths: list[str], version: str
) -> str:
    converted = dict(meta)
    converted["type"] = "schema"
    if "relates_to" not in converted:
        relates = []
    else:
        relates = converted["relates_to"]
    if not isinstance(relates, list):
        raise ValueError("relates_to is not a list")
    relates = list(relates)
    for gist_path in gist_paths:
        if not any(
            isinstance(item, dict)
            and item.get("path") == gist_path
            and str(item.get("kind") or item.get("role") or "").strip().lower() == "related"
            for item in relates
        ):
            relates.append({"path": gist_path, "kind": "related"})
    converted["relates_to"] = relates
    frontmatter = yaml.safe_dump(converted, allow_unicode=True, sort_keys=False)
    text = f"---\n{frontmatter}---{body}"
    round_trip, _ = split_fm_v2(text) if version == "2.0" else split_fm(text)
    if round_trip != converted:
        raise ValueError("frontmatter cannot be serialized without losing values")
    return text


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
            "error": "in-beta stores are not eligible for the pre-beta -> current contract-file migration",
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
    # atlas_release/memory.layers to the current shape. Existing pages stay
    # untouched; missing folder schema pages and their index cues are added.
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

    concept_pages = _read_concept_pages(r, schema)
    schema_pages, schema_error = _schema_pages_to_create(r, concept_pages)
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

    index_updates: dict[Path, str] = {}
    replaced_frames: list[Path] = []
    converted_frames: dict[Path, str] = {}
    created_schema_paths = {path for path, _ in schema_pages}
    schema_cue_pages = [
        (path, meta)
        for path, meta in concept_pages
        if str(meta.get("type") or "").strip() == "schema"
    ]
    schema_cue_pages.extend(
        (path, {"title": "Gist schema"})
        for path, _ in schema_pages
    )
    new_schema_gists = dict(schema_pages)
    for schema_path, schema_meta in schema_cue_pages:
        if schema_path in created_schema_paths:
            legacy_frame = schema_path.parent / "frame.md"
            if legacy_frame.is_symlink():
                payload = {
                    "ok": False,
                    "root": str(r),
                    "operation": "apply",
                    "contract_file": contract_name,
                    "lineage": lineage,
                    "error": f"{rel(r, legacy_frame)} is a symlink; refusing to replace it",
                    "findings": [{
                        "id": "schema_symlink",
                        "path": rel(r, legacy_frame),
                        "msg": f"{rel(r, legacy_frame)} is a symlink; refusing to replace it",
                    }],
                }
                _print(as_json, payload)
                return 2
            if legacy_frame.is_file():
                try:
                    legacy_meta, legacy_body = read_page(legacy_frame, schema_version(schema))
                except (FrontmatterError, OSError) as error:
                    legacy_meta, legacy_body = None, ""
                    frame_error = str(error)
                else:
                    frame_error = "frontmatter is missing or unreadable"
                if not legacy_meta:
                    finding = {
                        "id": "schema_manual_migration",
                        "path": rel(r, legacy_frame),
                        "msg": (
                            f"manual migration is required for {rel(r, legacy_frame)}: "
                            f"{frame_error}"
                        ),
                    }
                    payload = {
                        "ok": False,
                        "root": str(r),
                        "operation": "apply",
                        "contract_file": contract_name,
                        "lineage": lineage,
                        "error": finding["msg"],
                        "findings": [finding],
                    }
                    _print(as_json, payload)
                    return 2
                if str(legacy_meta.get("type") or "").strip() == "frame":
                    try:
                        converted_frames[schema_path] = _converted_frame_text(
                            legacy_meta,
                            legacy_body,
                            new_schema_gists[schema_path],
                            schema_version(schema),
                        )
                    except (TypeError, ValueError, yaml.YAMLError) as error:
                        finding = {
                            "id": "schema_manual_migration",
                            "path": rel(r, legacy_frame),
                            "msg": (
                                f"manual migration is required for {rel(r, legacy_frame)}: "
                                f"frontmatter cannot be preserved ({error})"
                            ),
                        }
                        payload = {
                            "ok": False,
                            "root": str(r),
                            "operation": "apply",
                            "contract_file": contract_name,
                            "lineage": lineage,
                            "error": finding["msg"],
                            "findings": [finding],
                        }
                        _print(as_json, payload)
                        return 2
                    replaced_frames.append(legacy_frame)
        index_path = schema_path.parent / "index.md"
        if index_path.is_symlink():
            payload = {
                "ok": False,
                "root": str(r),
                "operation": "apply",
                "contract_file": contract_name,
                "lineage": lineage,
                "error": f"{rel(r, index_path)} is a symlink; refusing to write through it",
                "findings": [{
                    "id": "schema_symlink",
                    "path": rel(r, index_path),
                    "msg": f"{rel(r, index_path)} is a symlink; refusing to write through it",
                }],
            }
            _print(as_json, payload)
            return 2
        try:
            index_text = (
                index_updates[index_path]
                if index_path in index_updates
                else index_path.read_text(encoding="utf-8") if index_path.exists() else ""
            )
        except OSError as error:
            payload = {
                "ok": False,
                "root": str(r),
                "operation": "apply",
                "contract_file": contract_name,
                "lineage": lineage,
                "error": f"cannot read {rel(r, index_path)}: {error}",
            }
            _print(as_json, payload)
            return 2
        if not _schema_cue_exists(index_path, schema_path, index_text):
            title = schema_meta.get("title")
            if not isinstance(title, str) or not title.strip():
                title = "Gist schema"
            cue = f"- [{title}](./{schema_path.name})"
            index_text = index_text.rstrip() + ("\n\n" if index_text.strip() else "") + cue + "\n"
        index_updates[index_path] = index_text

    schema["atlas_release"] = CURRENT_RELEASE
    memory = schema.get("memory") if isinstance(schema.get("memory"), dict) else {}
    memory["layers"] = list(BETA3_LAYERS)
    schema["memory"] = memory
    new_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    if contract_path != new_path:
        contract_path.unlink()
    for schema_path, gist_paths in schema_pages:
        if schema_path in converted_frames:
            schema_path.write_text(converted_frames[schema_path], encoding="utf-8")
        else:
            _write_schema_page(schema_path, gist_paths)
    for index_path, index_text in index_updates.items():
        index_path.write_text(index_text, encoding="utf-8")
    for legacy_frame in replaced_frames:
        legacy_frame.unlink()
    payload = {
        "ok": True,
        "root": str(r),
        "operation": "apply",
        "batch": batch_value,
        "contract_file": CONTRACT_NAME,
        "lineage": "current",
        "notes": [
            f"renamed {SCHEMA_NAME} -> {CONTRACT_NAME}; set atlas_release={CURRENT_RELEASE}",
            *[f"created schema page {rel(r, path)}" for path, _ in schema_pages],
            *[f"cued schema page in {rel(r, path)}" for path in index_updates],
            *[f"removed replaced frame page {rel(r, path)}" for path in replaced_frames],
        ],
    }
    _print(as_json, payload)
    return 0
