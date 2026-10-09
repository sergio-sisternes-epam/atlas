"""`atlas memory-migrate` — the pre-beta -> current contract-file migration path.

This is distinct from `atlas migrate` (content into staging) and from the
document-era-to-memory-layers content migration described in
references/paths/memory-migrate.md. This command rewrites the root contract file (SCHEMA.json -> CONTRACT.json)
and adds missing schema pages for gist-bearing folders; existing pages are
not rewritten. New current-shape pages use suffixes as search handles.

An unstamped full beta.2 init with no frame, gist, page, or memory content
pages is also eligible. Apply then aligns templates and types.recommended
with the blocks `atlas init` writes, and still does not rewrite content pages.

`--batch contract-file` writes the CURRENT_RELEASE stamp ("0.13.0"). A store
that is already current (CONTRACT.json stamped 0.13.0-beta.3, beta.4, beta.7
or 0.13.0) is a no-op for that batch and for apply with no batch. The
separate, operator-chosen `--batch restamp` replaces only the top-level
``atlas_release`` string value inside the original bytes of a current
CONTRACT.json that still carries an older accepted stamp; every other byte
and every other file stays unchanged, and it refuses with zero writes when
that single-value replacement cannot be verified.
"""

from __future__ import annotations

import copy
import json
import os
import re
import stat
import tempfile
from pathlib import Path

import yaml

from ..core.frontmatter import FrontmatterError, read_page, split_fm, split_fm_v2
from ..core.paths import (
    CONTRACT_NAME,
    RESERVED,
    SCHEMA_NAME,
    SKIP_DIRS,
    iter_concept_md,
    rel,
    store_root,
)
from ..core.recall_config import schema_version
from ..core.schema import (
    BETA3_LAYERS,
    CURRENT_RELEASE,
    OLDER_CURRENT_STAMPS,
    classify_lineage,
    find_contract_path,
    is_unstamped_full_beta2_init,
    skill_root,
    staging_dir_name,
)
from .init import _by_type_block
from .validate import MD_LINK, WIKILINK

REFUSE_BATCH_TOKENS = frozenset({"", "migrate everything"})
LEGACY_BATCH = "contract-file"
RESTAMP_BATCH = "restamp"
SUPPORTED_BATCHES = (LEGACY_BATCH, RESTAMP_BATCH)
MEMORY_PAGE_TYPES = frozenset({"memory", "gist", "frame"})
# Content types that keep an unstamped full beta.2 init on the in-beta
# refusal. `page` is included here; the pre-beta lineage flip above does
# not use this set.
BETA2_CONTENT_TYPES = frozenset({"frame", "gist", "page", "memory"})
RETIRED_BETA2_TYPES = ("frame", "page")
CURRENT_LAYER_TYPES = ("schema", "memory")
SCHEMA_PAGE_BODY = (
    "This schema page groups the gists in this folder for consistent "
    "navigation and interpretation."
)
FRAME_DESCRIPTION_NEXT_STEP = (
    "make the description a plain scalar the reader round-trips, then re-run "
    "`atlas memory-migrate --operation apply --batch contract-file`"
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
    frontmatter = yaml.safe_dump(
        converted, allow_unicode=True, sort_keys=False, width=10**9
    )
    text = f"---\n{frontmatter}---{body}"
    round_trip, _ = split_fm_v2(text) if version == "2.0" else split_fm(text)
    if round_trip != converted:
        raise ValueError("frontmatter cannot be serialized without losing values")
    return text


def _write_frame_operator_steps(root: Path, frame: Path, description: str) -> None:
    staging = root / "staging"
    steps = staging / "memory-migrate-operator-steps.md"
    if staging.is_symlink() or steps.is_symlink():
        raise OSError("refusing to write operator steps through a symlink")
    staging.mkdir(parents=True, exist_ok=True)
    steps.write_text(
        "# Memory migration operator steps\n\n"
        f"Frame: {rel(root, frame)}\n\n"
        "Original description (verbatim):\n\n"
        f"{description}\n\n"
        f"Next step: {FRAME_DESCRIPTION_NEXT_STEP}.\n",
        encoding="utf-8",
    )


def _store_path(root: Path, raw: str) -> Path:
    """Resolve a store-relative path that contains no symlink component."""
    text = raw.strip().replace("\\", "/")
    if not text or text.startswith("/"):
        raise ValueError(f"template path {raw!r} is not inside the store")
    parts = [part for part in text.split("/") if part]
    if not parts or any(part in (".", "..") for part in parts):
        raise ValueError(f"template path {raw!r} is not inside the store")
    current = root
    if current.is_symlink():
        raise ValueError("store root is a symlink")
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"template path {raw!r} contains a symlink")
    resolved = current.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"template path {raw!r} escapes the store")
    return current


def _templates_directory(root: Path, templates: dict) -> Path:
    raw = templates.get("directory")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("templates.directory is missing")
    directory = _store_path(root, raw.strip().strip("/"))
    if directory == root:
        raise ValueError("templates.directory must be a directory inside the store")
    if directory.exists() and not directory.is_dir():
        raise ValueError("templates.directory is not a directory")
    return directory


def _rewrite_recommended(recommended: list[str]) -> list[str]:
    """Drop frame/page and ensure schema/memory, preserving other types in order."""
    replacement = {"frame": "schema", "page": "memory"}
    rewritten: list[str] = []
    seen: set[str] = set()
    for item in recommended:
        if item in replacement:
            repl = replacement[item]
            if repl in recommended or repl in seen:
                continue
            rewritten.append(repl)
            seen.add(repl)
            continue
        if item not in seen:
            rewritten.append(item)
            seen.add(item)
    for name in CURRENT_LAYER_TYPES:
        if name not in seen:
            rewritten.append(name)
            seen.add(name)
    return rewritten


def _normalize_beta2_contract(schema: dict) -> None:
    """Align templates and types.recommended with the blocks `atlas init` writes.

    Store-specific settings and custom types stay. ``frame`` and ``page`` are
    removed. Missing ``schema`` and ``memory`` by-type blocks are the same
    objects ``atlas init`` writes.
    """
    types = schema.get("types")
    if not isinstance(types, dict):
        raise ValueError("types is not an object")
    recommended = types.get("recommended")
    if not isinstance(recommended, list) or any(not isinstance(item, str) for item in recommended):
        raise ValueError("types.recommended is not a list of strings")
    types["recommended"] = _rewrite_recommended(recommended)
    if "unconstrained" in types:
        unconstrained = types.get("unconstrained")
        if not isinstance(unconstrained, list):
            raise ValueError("types.unconstrained is not a list")
        types["unconstrained"] = [
            item for item in unconstrained if item not in RETIRED_BETA2_TYPES
        ]
    templates = schema.get("templates")
    if not isinstance(templates, dict):
        raise ValueError("templates is not an object")
    by_type = templates.get("by_type")
    if not isinstance(by_type, dict):
        raise ValueError("templates.by_type is not an object")
    for name in RETIRED_BETA2_TYPES:
        by_type.pop(name, None)
    for name in CURRENT_LAYER_TYPES:
        if name not in by_type:
            by_type[name] = _by_type_block(name)


def _beta2_content_pages(root: Path, schema: dict) -> tuple[list[str], dict | None]:
    """Return (blocking concept paths, finding).

    A finding means the store cannot be proved free of frame/gist/page/memory
    content pages. Reserved ``index.md`` / ``log.md``, staging, and
    ``templates/`` are not content pages — the same walk as the rest of this
    command.
    """
    staging = staging_dir_name(schema)
    version = schema_version(schema)
    skip_roots = set(SKIP_DIRS) | {staging}
    blockers: list[str] = []
    root_resolved = root.resolve()

    for path in sorted(root.rglob("*.md")):
        if path.name in RESERVED:
            continue
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            return [], {
                "id": "beta2_content_ambiguous",
                "path": path.name,
                "msg": f"{path.name} cannot be classified as a concept page; refusing",
            }
        if parts and parts[0] in skip_roots:
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(root_resolved)
        except (OSError, ValueError):
            shown = rel(root, path)
            return [], {
                "id": "beta2_content_ambiguous",
                "path": shown,
                "msg": f"{shown} is a symlink that cannot be classified; refusing",
            }
        if path.is_symlink() and not path.is_file():
            shown = rel(root, path)
            return [], {
                "id": "beta2_content_ambiguous",
                "path": shown,
                "msg": (
                f"{shown} is a symlink that is not a readable concept page; "
                "refusing to classify beta.2 content pages"
            ),
            }
        if not path.is_file():
            continue
        try:
            meta, _body = read_page(path, version)
        except (FrontmatterError, OSError, UnicodeError) as error:
            shown = rel(root, path)
            return [], {
                "id": "beta2_content_ambiguous",
                "path": shown,
                "msg": f"cannot classify {shown}: {error}",
            }
        if not meta:
            continue
        raw_type = meta.get("type")
        if raw_type is None or raw_type == "":
            continue
        if not isinstance(raw_type, str):
            shown = rel(root, path)
            return [], {
                "id": "beta2_content_ambiguous",
                "path": shown,
                "msg": (
                    f"{shown} has a non-string type; refusing to treat the store as free "
                    "of frame, gist, page, and memory content"
                ),
            }
        if raw_type.strip().lower() in BETA2_CONTENT_TYPES:
            blockers.append(rel(root, path))
    return blockers, None


def _by_type_files(root: Path, by_type: dict, names: tuple[str, ...] | None = None) -> set[Path]:
    files: set[Path] = set()
    items = by_type.items() if names is None else ((name, by_type.get(name)) for name in names)
    for type_name, block in items:
        if not isinstance(block, dict):
            continue
        file_field = block.get("file")
        if file_field is None:
            continue
        if not isinstance(file_field, str) or not file_field.strip():
            raise ValueError(f"templates.by_type.{type_name}.file is not a path")
        files.add(_store_path(root, file_field))
    return files


def _plan_beta2_template_files(
    root: Path, original: dict, normalized: dict
) -> tuple[list[Path], list[tuple[Path, bytes]]]:
    """Plan template-file deletes and package copies. Reads bytes; writes nothing.

    Deletes come from the original frame/page template files. Copies come from
    the normalised schema/memory blocks, which are the blocks ``atlas init``
    writes when those types were missing.
    """
    templates = original.get("templates")
    if not isinstance(templates, dict):
        raise ValueError("templates is not an object")
    templates_dir = _templates_directory(root, templates)
    by_type = templates.get("by_type")
    if not isinstance(by_type, dict):
        raise ValueError("templates.by_type is not an object")
    normalized_templates = normalized.get("templates")
    if not isinstance(normalized_templates, dict):
        raise ValueError("templates is not an object")
    normalized_by_type = normalized_templates.get("by_type")
    if not isinstance(normalized_by_type, dict):
        raise ValueError("templates.by_type is not an object")

    deletes: list[Path] = []
    seen: set[Path] = set()

    def _add_delete(path: Path) -> None:
        if path in seen:
            return
        if templates_dir not in path.parents:
            raise ValueError(f"{rel(root, path)} is outside templates.directory")
        if path.is_symlink():
            raise ValueError(f"{rel(root, path)} is a symlink; refusing to delete it")
        if path.exists() and not path.is_file():
            raise ValueError(f"{rel(root, path)} is not a file")
        seen.add(path)
        if path.is_file():
            deletes.append(path)

    for name in ("frame.md", "page.md"):
        candidate = templates_dir / name
        if candidate.exists() or candidate.is_symlink():
            _add_delete(candidate)
    for path in _by_type_files(root, by_type, RETIRED_BETA2_TYPES):
        _add_delete(path)

    kept_names = tuple(name for name in by_type if name not in RETIRED_BETA2_TYPES)
    kept_files = _by_type_files(root, by_type, kept_names)
    kept_files.update(
        _by_type_files(root, normalized_by_type, tuple(normalized_by_type))
    )
    overlap = [path for path in deletes if path in kept_files]
    if overlap:
        raise ValueError(
            "a kept template file is also a frame or page template: "
            + ", ".join(rel(root, path) for path in overlap)
        )

    copies: list[tuple[Path, bytes]] = []
    package_dir = skill_root() / "references" / "templates"
    for type_name in CURRENT_LAYER_TYPES:
        block = normalized_by_type.get(type_name)
        if not isinstance(block, dict):
            raise ValueError(f"templates.by_type.{type_name} is missing after normalisation")
        file_field = block.get("file")
        if not isinstance(file_field, str) or not file_field.strip():
            raise ValueError(f"templates.by_type.{type_name}.file is not a path")
        dest = _store_path(root, file_field)
        if templates_dir not in dest.parents:
            raise ValueError(f"{file_field} is outside templates.directory")
        if dest in seen:
            raise ValueError(f"{file_field} is also scheduled for deletion")
        if dest.is_symlink():
            raise ValueError(f"{rel(root, dest)} is a symlink; refusing to replace it")
        if dest.exists():
            if not dest.is_file():
                raise ValueError(f"{rel(root, dest)} is not a file")
            continue
        source = package_dir / f"{type_name}.md"
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"package template {type_name}.md is missing")
        copies.append((dest, source.read_bytes()))
    return deletes, copies


def _empty_beta2_migration_status(root: Path, contract_name: str, schema: dict) -> dict:
    """Read-only eligibility for an unstamped full beta.2 init.

    ``match`` is the contract shape. ``eligible`` also requires zero
    frame/gist/page/memory content pages and a template plan that can be
    applied without an ambiguous path. Nothing is written.
    """
    status = {
        "match": False,
        "eligible": False,
        "blockers": [],
        "finding": None,
        "deletes": [],
        "copies": [],
    }
    if not is_unstamped_full_beta2_init(contract_name, schema):
        return status
    status["match"] = True
    blockers, finding = _beta2_content_pages(root, schema)
    status["blockers"] = blockers
    if finding:
        status["finding"] = finding
        return status
    if blockers:
        return status
    try:
        trial = copy.deepcopy(schema)
        _normalize_beta2_contract(trial)
        deletes, copies = _plan_beta2_template_files(root, schema, trial)
    except (OSError, ValueError, UnicodeError) as error:
        status["finding"] = {
            "id": "beta2_contract_ambiguous",
            "path": contract_name,
            "msg": f"refusing to migrate this beta.2 init: {error}",
        }
        return status
    status["deletes"] = deletes
    status["copies"] = copies
    status["eligible"] = True
    return status


def _restamp_status(contract_name: str, schema: dict, contract_lineage: str) -> str:
    """Classify a store for ``--batch restamp`` without writing anything.

    Returns ``"eligible"`` when restamp would rewrite ``atlas_release`` (a
    current CONTRACT.json with layers schema/gist/memory and an older
    accepted current stamp), ``"already"`` when it already carries
    CURRENT_RELEASE, and ``"refused"`` for anything else.
    """
    if contract_name != CONTRACT_NAME or contract_lineage != "current":
        return "refused"
    memory = schema.get("memory") if isinstance(schema.get("memory"), dict) else None
    layers = memory.get("layers") if isinstance(memory, dict) else None
    if layers != BETA3_LAYERS:
        return "refused"
    atlas_release = schema.get("atlas_release")
    if atlas_release == CURRENT_RELEASE:
        return "already"
    if atlas_release in OLDER_CURRENT_STAMPS:
        return "eligible"
    return "refused"


def _restamp_refusal_msg(contract_name: str, lineage: str, atlas_release: object) -> str:
    msg = (
        f"--batch {RESTAMP_BATCH} only rewrites atlas_release on a current "
        f"{CONTRACT_NAME} (layers {BETA3_LAYERS!r}) stamped "
        f"{', '.join(OLDER_CURRENT_STAMPS)}; this store is {contract_name} "
        f"lineage {lineage} with atlas_release={atlas_release!r} and was not rewritten"
    )
    if lineage == "pre-beta":
        msg += f"; pre-beta stores use --batch {LEGACY_BATCH}, which writes {CURRENT_RELEASE}"
    return msg


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
    if "contract_file_eligible" in payload:
        print(f"contract_file_eligible: {str(bool(payload['contract_file_eligible'])).lower()}")
    if "atlas_release" in payload:
        print(f"atlas_release: {payload['atlas_release']}")
    if "restamp_eligible" in payload:
        print(f"restamp_eligible: {str(bool(payload['restamp_eligible'])).lower()}")
    for note in payload.get("notes") or []:
        print(f"note: {note}")


def _unsupported_batch(
    r: Path, contract_name: str, lineage: str, batch_value: str, as_json: bool
) -> int:
    payload = {
        "ok": False,
        "root": str(r),
        "operation": "apply",
        "contract_file": contract_name,
        "lineage": lineage,
        "error": (
            f"unsupported --batch {batch_value!r}; supported batches are "
            f"{LEGACY_BATCH!r} (pre-beta or empty beta.2 init -> {CURRENT_RELEASE}) "
            f"and {RESTAMP_BATCH!r} (current store stamp -> {CURRENT_RELEASE})"
        ),
    }
    _print(as_json, payload)
    return 2


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
    beta2 = _empty_beta2_migration_status(r, contract_name, schema)
    if beta2["eligible"]:
        lineage = "empty-beta2-init"
    restamp = _restamp_status(contract_name, schema, contract_lineage)

    if operation in ("assess", "inventory"):
        notes = ["write nothing"]
        if beta2["eligible"]:
            notes.append(
                "unstamped full beta.2 init with no frame, gist, page, or memory "
                "content pages; eligible for apply --batch contract-file"
            )
        elif beta2["match"] and beta2["finding"]:
            notes.append(beta2["finding"]["msg"])
        elif beta2["match"] and beta2["blockers"]:
            notes.append(
                "unstamped full beta.2 init has frame, gist, page, or memory "
                "content pages; not eligible for apply"
            )
        if restamp == "eligible":
            notes.append(
                f"current store with an older accepted stamp; eligible for apply "
                f"--batch {RESTAMP_BATCH} (atlas_release -> {CURRENT_RELEASE})"
            )
        elif restamp == "already":
            notes.append("already at current stamp")
        payload = {
            "ok": True,
            "root": str(r),
            "operation": operation,
            "contract_file": contract_name,
            "lineage": lineage,
            "contract_file_eligible": contract_lineage == "pre-beta" or beta2["eligible"],
            "atlas_release": schema.get("atlas_release"),
            "restamp_eligible": restamp == "eligible",
            "notes": notes,
        }
        if beta2["match"] and beta2["finding"] is None:
            payload["beta_content_pages"] = list(beta2["blockers"])
        _print(as_json, payload)
        return 0

    if operation != "apply":
        payload = {"ok": False, "root": str(r), "error": f"unsupported --operation {operation}"}
        _print(as_json, payload)
        return 2

    # --- apply ---
    batch_value = (batch or "").strip()
    if batch_value == RESTAMP_BATCH:
        return _apply_restamp(r, contract_path, schema, lineage, restamp, as_json)
    # Reject typos such as "restmap" before any lineage-specific no-op or
    # refusal, so a mistyped batch never exits 0 on a current store.
    if batch_value.lower() not in REFUSE_BATCH_TOKENS and batch_value not in SUPPORTED_BATCHES:
        return _unsupported_batch(r, contract_name, lineage, batch_value, as_json)

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

    if contract_lineage == "in-beta" and not beta2["eligible"]:
        if beta2["finding"]:
            finding = beta2["finding"]
            error = finding["msg"]
        else:
            error = (
                "in-beta stores are not eligible for the pre-beta -> current "
                "contract-file migration"
            )
            finding = {
                "id": "in_beta_not_legacy",
                "path": contract_name,
                "msg": (
                    "apply is only for pre-beta stores, or an unstamped full beta.2 "
                    "init with no frame, gist, page, or memory content pages; this "
                    "store is already in-beta (atlas_release 0.13.0-beta/0.13.0-beta.2, "
                    "memory.layers frame/gist/page or frame/gist/memory, or a full "
                    "beta.2 init that already has those content pages) and was not rewritten"
                ),
            }
        payload = {
            "ok": False,
            "root": str(r),
            "operation": "apply",
            "contract_file": contract_name,
            "lineage": lineage,
            "contract_file_eligible": False,
            "error": error,
            "findings": [finding],
        }
        _print(as_json, payload)
        return 2

    # contract_lineage == "pre-beta"
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
        return _unsupported_batch(r, contract_name, lineage, batch_value, as_json)

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
                            "id": "frame_description_not_round_trippable",
                            "path": rel(r, legacy_frame),
                            "msg": (
                                f"manual migration is required for {rel(r, legacy_frame)}: "
                                f"frontmatter cannot be preserved ({error})"
                            ),
                        }
                        try:
                            _write_frame_operator_steps(
                                r, legacy_frame, str(legacy_meta.get("description", ""))
                            )
                        except OSError as steps_error:
                            finding["msg"] += f"; cannot write operator steps: {steps_error}"
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
    if beta2["eligible"]:
        try:
            _normalize_beta2_contract(schema)
        except ValueError as error:
            payload = {
                "ok": False,
                "root": str(r),
                "operation": "apply",
                "contract_file": contract_name,
                "lineage": lineage,
                "contract_file_eligible": False,
                "error": f"refusing to migrate this beta.2 init: {error}",
                "findings": [{
                    "id": "beta2_contract_ambiguous",
                    "path": contract_name,
                    "msg": f"refusing to migrate this beta.2 init: {error}",
                }],
            }
            _print(as_json, payload)
            return 2
    created_templates: list[Path] = []
    try:
        for dest, data in beta2["copies"]:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() or dest.is_symlink():
                raise OSError(f"{rel(r, dest)} changed before it could be written")
            dest.write_bytes(data)
            created_templates.append(dest)
        new_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        for created in reversed(created_templates):
            if created.is_file() and not created.is_symlink():
                created.unlink()
        if contract_path != new_path and new_path.is_file() and not new_path.is_symlink():
            new_path.unlink()
        finding = {
            "id": "beta2_contract_ambiguous" if beta2["eligible"] else "contract_write",
            "path": contract_name,
            "msg": f"refusing to leave a partial migration: {error}",
        }
        payload = {
            "ok": False,
            "root": str(r),
            "operation": "apply",
            "contract_file": contract_name,
            "lineage": lineage,
            "contract_file_eligible": False,
            "error": finding["msg"],
            "findings": [finding],
        }
        _print(as_json, payload)
        return 2
    if contract_path != new_path:
        contract_path.unlink()
    for retired in beta2["deletes"]:
        if retired.is_file() and not retired.is_symlink():
            retired.unlink()
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
            *(
                [
                    "aligned templates and types.recommended with current init "
                    "(removed frame and page; added schema and memory)"
                ]
                if beta2["eligible"]
                else []
            ),
            *[f"created schema page {rel(r, path)}" for path, _ in schema_pages],
            *[f"cued schema page in {rel(r, path)}" for path in index_updates],
            *[f"removed replaced frame page {rel(r, path)}" for path in replaced_frames],
        ],
    }
    _print(as_json, payload)
    return 0


class _DuplicateKeyError(ValueError):
    pass


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict:
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise _DuplicateKeyError(key)
        seen.add(key)
    return dict(pairs)


def _ordered(value: object) -> object:
    """Normalise parsed JSON so equality also checks object key order."""
    if isinstance(value, dict):
        return [(key, _ordered(item)) for key, item in value.items()]
    if isinstance(value, list):
        return [_ordered(item) for item in value]
    return value


def _restamp_bytes(original: bytes, old_stamp: str) -> tuple[bytes | None, str]:
    """Return ``original`` with only the top-level stamp value replaced.

    The raw UTF-8 bytes must hold exactly one ``"atlas_release": "<old>"``
    member (any spacing around the colon), and re-parsing the result must
    equal the original object, key order included, with only the top-level
    ``atlas_release`` changed to CURRENT_RELEASE. Duplicate keys at any depth,
    a nested key carrying the same stamp, or an escaped key or value all
    refuse. Returns ``(None, reason)`` on refusal.
    """
    try:
        text = original.decode("utf-8")
        before = json.loads(text, object_pairs_hook=_strict_pairs)
    except _DuplicateKeyError as error:
        return None, f"duplicate JSON key {error.args[0]!r}"
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, f"cannot re-read the contract as UTF-8 JSON ({error})"
    if not isinstance(before, dict) or before.get("atlas_release") != old_stamp:
        return None, "the contract changed while it was being read"
    pattern = re.compile(
        rb'"atlas_release"(\s*:\s*)"' + re.escape(old_stamp.encode("utf-8")) + rb'"'
    )
    matches = list(pattern.finditer(original))
    if len(matches) != 1:
        return None, (
            f"expected exactly one \"atlas_release\": \"{old_stamp}\" member in the "
            f"raw file, found {len(matches)}"
        )
    match = matches[0]
    replacement = b'"atlas_release"' + match.group(1) + b'"' + CURRENT_RELEASE.encode("utf-8") + b'"'
    new_bytes = original[: match.start()] + replacement + original[match.end():]
    expected = dict(before)
    expected["atlas_release"] = CURRENT_RELEASE
    try:
        after = json.loads(new_bytes.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (ValueError, UnicodeDecodeError) as error:
        return None, f"the restamped contract does not re-parse ({error})"
    if _ordered(after) != _ordered(expected):
        return None, (
            "replacing the matched member would change more than the top-level "
            "atlas_release value"
        )
    return new_bytes, ""


def _read_regular_file(path: Path) -> bytes:
    """Read ``path`` without following a final-component symlink where possible."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(fd, "rb") as handle:
        return handle.read()


def _replace_contract(contract_path: Path, data: bytes, mode: int) -> None:
    """Atomically replace ``contract_path`` with ``data``, keeping ``mode``.

    The bytes go to a sibling temporary file that is fsynced and then moved
    over the contract with ``os.replace``, which swaps the directory entry
    and never writes through a symlink. The temporary file is removed on
    any error.
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=contract_path.parent, prefix=".CONTRACT.json.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, contract_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _apply_restamp(
    r: Path,
    contract_path: Path,
    schema: dict,
    lineage: str,
    restamp: str,
    as_json: bool,
) -> int:
    """`apply --batch restamp`: move a current store's stamp to CURRENT_RELEASE.

    Replaces only the top-level ``atlas_release`` string value inside the
    original CONTRACT.json bytes; encoding, spacing, line endings, key order
    and every other byte stay as they were. If that replacement cannot be
    proven safe (see ``_restamp_bytes``) it refuses and writes nothing. No
    page, template or other file is touched.
    """
    contract_name = contract_path.name
    atlas_release = schema.get("atlas_release")
    base = {
        "root": str(r),
        "operation": "apply",
        "batch": RESTAMP_BATCH,
        "contract_file": contract_name,
        "lineage": lineage,
        "atlas_release": atlas_release,
    }
    if restamp == "already":
        _print(as_json, {"ok": True, **base, "notes": ["already at current stamp; no-op write"]})
        return 0
    if restamp != "eligible":
        msg = _restamp_refusal_msg(contract_name, lineage, atlas_release)
        _print(as_json, {
            "ok": False,
            **base,
            "error": msg,
            "findings": [{"id": "restamp_not_eligible", "path": contract_name, "msg": msg}],
        })
        return 2

    # Re-check immediately before reading: only a regular file, never a
    # symlink swapped in after find_contract_path ran.
    lstat_error = ""
    try:
        original_stat = os.lstat(contract_path)
    except OSError as error:
        original_stat = None
        lstat_error = f" ({error})"
    if original_stat is None or not stat.S_ISREG(original_stat.st_mode):
        msg = (
            f"{contract_name} is not a regular file{lstat_error}; "
            "refusing to restamp, no file was written"
        )
        _print(as_json, {
            "ok": False,
            **base,
            "error": msg,
            "findings": [{"id": "restamp_not_eligible", "path": contract_name, "msg": msg}],
        })
        return 2
    try:
        original = _read_regular_file(contract_path)
    except OSError as error:
        msg = f"cannot read {contract_name}: {error}"
        _print(as_json, {
            "ok": False,
            **base,
            "error": msg,
            "findings": [{"id": "contract_read", "path": contract_name, "msg": msg}],
        })
        return 2
    new_bytes, reason = _restamp_bytes(original, str(atlas_release))
    if new_bytes is None:
        msg = (
            f"--batch {RESTAMP_BATCH} refused to rewrite {contract_name}: {reason}; "
            f"no file was written. Set \"atlas_release\": \"{CURRENT_RELEASE}\" by hand "
            "if this store should carry the current stamp"
        )
        _print(as_json, {
            "ok": False,
            **base,
            "error": msg,
            "findings": [{"id": "restamp_not_byte_safe", "path": contract_name, "msg": msg}],
        })
        return 2
    try:
        _replace_contract(contract_path, new_bytes, stat.S_IMODE(original_stat.st_mode))
    except OSError as error:
        msg = f"cannot write {contract_name}: {error}"
        _print(as_json, {
            "ok": False,
            **base,
            "error": msg,
            "findings": [{"id": "contract_write", "path": contract_name, "msg": msg}],
        })
        return 2
    _print(as_json, {
        "ok": True,
        **base,
        "atlas_release": CURRENT_RELEASE,
        "previous_atlas_release": atlas_release,
        "notes": [
            f"set atlas_release {atlas_release} -> {CURRENT_RELEASE}; no other key or file changed",
            f"compile this store with an Atlas {CURRENT_RELEASE} package; "
            "beta.13 and earlier packages fail closed on this stamp",
        ],
    })
    return 0
