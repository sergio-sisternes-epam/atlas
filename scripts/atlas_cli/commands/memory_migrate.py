"""`atlas memory-migrate` — the pre-beta -> current contract-file migration path.

This is distinct from `atlas migrate` (content into staging) and from the
document-era-to-memory-layers content migration described in
references/paths/memory-migrate.md. This command rewrites the root contract file (SCHEMA.json -> CONTRACT.json)
and adds missing schema pages for gist-bearing folders; existing pages are
not rewritten. New current-shape pages use suffixes as search handles.
"""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path

import yaml

from ..core.frontmatter import FrontmatterError, read_page, split_fm, split_fm_v2
from ..core.paths import CONTRACT_NAME, RESERVED, SCHEMA_NAME, iter_concept_md, rel, store_root
from ..core.recall_config import schema_version
from ..core.schema import (
    BETA3_LAYERS,
    CURRENT_RELEASE,
    _is_full_beta2_init,
    classify_lineage,
    find_contract_path,
    skill_root,
    staging_dir_name,
)
from .init import _by_type_block
from .validate import MD_LINK, WIKILINK

REFUSE_BATCH_TOKENS = frozenset({"", "migrate everything"})
LEGACY_BATCH = "contract-file"
MEMORY_PAGE_TYPES = frozenset({"memory", "gist", "frame"})
# Content types that mean a beta.2 init already holds layer pages. "page" is
# the original episode type id; "memory" is the beta.2 rename of it.
_BETA2_LAYER_CONTENT_TYPES = frozenset({"frame", "gist", "page", "memory"})
_RETIRED_BETA2_TYPES = ("frame", "page")
_CURRENT_INIT_LAYER_TYPES = ("schema", "memory")
_ENSURE_TEMPLATE_FILES = ("schema.md", "memory.md")
_SKIP_CONTENT_ROOTS = frozenset({"templates", ".atlas-index", "mesh", "schema.d", ".git"})
SCHEMA_PAGE_BODY = (
    "This schema page groups the gists in this folder for consistent "
    "navigation and interpretation."
)
FRAME_DESCRIPTION_NEXT_STEP = (
    "make the description a plain scalar the reader round-trips, then re-run "
    "`atlas memory-migrate --operation apply --batch contract-file`"
)


def _ambiguous(path: str, msg: str) -> dict:
    return {"id": "beta2_init_ambiguous", "path": path, "msg": msg}


def _is_unstamped_full_beta2_init(contract_name: str, schema: dict) -> bool:
    """True for the contract shape this batch may newly migrate.

    Stamped beta releases and any present ``memory`` key stay on the
    in-beta refusal path. ``classify_lineage`` still reports this shape as
    ``in-beta``; the content-page check below is what makes an empty init
    eligible.
    """
    return (
        contract_name == SCHEMA_NAME
        and "atlas_release" not in schema
        and "memory" not in schema
        and _is_full_beta2_init(schema)
    )


def _contained(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _templates_dir(root: Path, schema: dict) -> tuple[Path | None, dict | None]:
    templates = schema.get("templates")
    if not isinstance(templates, dict):
        return None, _ambiguous(SCHEMA_NAME, "templates must be an object to normalise a beta.2 init")
    directory = templates.get("directory", "templates/")
    if not isinstance(directory, str) or not directory.strip():
        return None, _ambiguous(SCHEMA_NAME, "templates.directory must be a relative directory path")
    raw = Path(directory)
    if raw.is_absolute() or any(part == ".." for part in raw.parts):
        return None, _ambiguous(SCHEMA_NAME, "templates.directory must stay inside the store")
    candidate = root / raw
    if candidate.is_symlink():
        return None, _ambiguous(rel(root, candidate), "templates directory is a symlink; refusing")
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None, _ambiguous(SCHEMA_NAME, "templates.directory must stay inside the store")
    if candidate.exists() and not candidate.is_dir():
        return None, _ambiguous(rel(root, candidate), "templates directory path is not a directory")
    return candidate, None


def _normalize_recommended(recommended: list[str]) -> list[str]:
    """Drop leftover frame/page names and ensure schema/memory, in init order."""
    retired = set(_RETIRED_BETA2_TYPES)
    kept: list[str] = []
    insert_at: int | None = None
    for item in recommended:
        if item in retired:
            if insert_at is None:
                insert_at = len(kept)
            continue
        kept.append(item)
    missing = [name for name in _CURRENT_INIT_LAYER_TYPES if name not in kept]
    if insert_at is None:
        kept.extend(missing)
    else:
        for offset, name in enumerate(missing):
            kept.insert(insert_at + offset, name)
    return kept


def _normalize_beta2_contract(schema: dict) -> dict | None:
    """Align templates and recommended types with current ``atlas init``.

    Store-specific types and template blocks stay. ``frame`` and ``page``
    are leftover beta.2 type ids, so they are removed. ``schema`` and
    ``memory`` are added, when missing, with the same by_type block init
    writes. Returns a finding when the contract is not safe to rewrite.
    """
    templates = schema.get("templates")
    if not isinstance(templates, dict):
        return _ambiguous(SCHEMA_NAME, "templates must be an object to normalise a beta.2 init")
    by_type = templates.get("by_type", {})
    if by_type is None:
        by_type = {}
        templates["by_type"] = by_type
    if not isinstance(by_type, dict):
        return _ambiguous(SCHEMA_NAME, "templates.by_type must be an object")
    types = schema.get("types")
    if not isinstance(types, dict):
        return _ambiguous(SCHEMA_NAME, "types must be an object")
    recommended = types.get("recommended")
    if not isinstance(recommended, list) or any(not isinstance(item, str) for item in recommended):
        return _ambiguous(SCHEMA_NAME, "types.recommended must be a list of strings")
    if "unconstrained" in types:
        unconstrained = types.get("unconstrained")
        if not isinstance(unconstrained, list) or any(
            not isinstance(item, str) for item in unconstrained
        ):
            return _ambiguous(SCHEMA_NAME, "types.unconstrained must be a list of strings")
        types["unconstrained"] = [
            item for item in unconstrained if item not in _RETIRED_BETA2_TYPES
        ]
    for name in _CURRENT_INIT_LAYER_TYPES:
        existing = by_type.get(name)
        if existing is not None and not isinstance(existing, dict):
            return _ambiguous(
                SCHEMA_NAME,
                f"templates.by_type.{name} must be an object to keep or replace it",
            )
    for name, block in by_type.items():
        if name in _RETIRED_BETA2_TYPES or not isinstance(block, dict):
            continue
        file_field = block.get("file")
        if isinstance(file_field, str) and Path(file_field).name in ("frame.md", "page.md"):
            return _ambiguous(
                SCHEMA_NAME,
                f"templates.by_type.{name} still points at a frame or page template file",
            )
    for name in _RETIRED_BETA2_TYPES:
        by_type.pop(name, None)
    for name in _CURRENT_INIT_LAYER_TYPES:
        if name not in by_type:
            by_type[name] = _by_type_block(name)
    types["recommended"] = _normalize_recommended(recommended)
    return None


def _plan_template_files(root: Path, schema: dict) -> tuple[dict | None, dict | None]:
    tmpl_dir, finding = _templates_dir(root, schema)
    if finding or tmpl_dir is None:
        return None, finding or _ambiguous(SCHEMA_NAME, "templates directory is not usable")
    staging_name = staging_dir_name(schema)
    staging = root / staging_name
    if staging.is_symlink():
        return None, _ambiguous(rel(root, staging), "staging directory is a symlink; refusing")
    if tmpl_dir.exists() and staging.exists() and tmpl_dir.resolve() == staging.resolve():
        return None, _ambiguous(
            rel(root, tmpl_dir),
            "templates directory and staging directory are the same path",
        )
    deletes: list[Path] = []
    for name in ("frame.md", "page.md"):
        path = tmpl_dir / name
        if path.is_symlink():
            return None, _ambiguous(rel(root, path), f"{name} template is a symlink; refusing")
        if path.exists() and not path.is_file():
            return None, _ambiguous(rel(root, path), f"{name} template path is not a file")
        if path.is_file():
            deletes.append(path)
    package_templates = skill_root() / "references" / "templates"
    copies: list[tuple[Path, Path]] = []
    for name in _ENSURE_TEMPLATE_FILES:
        dest = tmpl_dir / name
        if dest.is_symlink():
            return None, _ambiguous(rel(root, dest), f"{name} template is a symlink; refusing")
        if dest.exists() and not dest.is_file():
            return None, _ambiguous(rel(root, dest), f"{name} template path is not a file")
        if dest.exists():
            continue
        source = package_templates / name
        if not source.is_file():
            return None, _ambiguous(
                f"references/templates/{name}",
                f"package template {name} is missing; refusing to invent one",
            )
        copies.append((source, dest))
    return {"dir": tmpl_dir, "mkdir": not tmpl_dir.exists(), "deletes": deletes, "copies": copies}, None


def _beta2_migration_plan(root: Path, schema: dict) -> tuple[dict | None, dict | None]:
    """Return a write plan, or a finding. Does not touch the store."""
    rewritten = deepcopy(schema)
    finding = _normalize_beta2_contract(rewritten)
    if finding:
        return None, finding
    files, finding = _plan_template_files(root, rewritten)
    if finding or files is None:
        return None, finding or _ambiguous(SCHEMA_NAME, "template plan failed")
    return {"schema": rewritten, "files": files}, None


def _apply_template_plan(files: dict) -> None:
    if files["mkdir"]:
        files["dir"].mkdir(parents=True, exist_ok=True)
    for source, dest in files["copies"]:
        shutil.copy2(source, dest)
    for path in files["deletes"]:
        path.unlink()


def _beta2_page_status(root: Path, schema: dict) -> tuple[str, dict | None]:
    """Classify layer content for an unstamped full beta.2 init.

    Returns ``eligible`` when no concept or staging page is frame, gist,
    page, or memory; ``layer_content`` when one is; ``ambiguous`` when a
    page cannot be classified. Template files are not content pages.
    """
    tmpl_dir, finding = _templates_dir(root, schema)
    if finding:
        return "ambiguous", finding
    assert tmpl_dir is not None
    staging_name = staging_dir_name(schema)
    staging = root / staging_name
    if staging.is_symlink():
        return "ambiguous", _ambiguous(rel(root, staging), "staging directory is a symlink; refusing")
    version = schema_version(schema)
    try:
        matches = sorted(root.rglob("*"))
    except OSError as error:
        return "ambiguous", _ambiguous(".", f"cannot list store pages: {error}")
    for path in matches:
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            return "ambiguous", _ambiguous(str(path), "path is outside the store")
        if not parts or parts[0] in _SKIP_CONTENT_ROOTS:
            continue
        try:
            path.relative_to(tmpl_dir)
        except ValueError:
            under_templates = False
        else:
            under_templates = True
        if under_templates:
            continue
        if path.is_symlink() and (path.suffix == ".md" or not path.is_file()):
            return "ambiguous", _ambiguous(
                rel(root, path),
                "page path is a symlink; refusing to guess whether it is layer content",
            )
        if path.suffix != ".md" or not path.is_file():
            if path.suffix == ".md":
                return "ambiguous", _ambiguous(rel(root, path), "markdown path is not a file")
            continue
        if not _contained(root, path):
            return "ambiguous", _ambiguous(rel(root, path), "markdown page resolves outside the store")
        try:
            meta, _ = read_page(path, version)
        except (FrontmatterError, OSError) as error:
            return "ambiguous", _ambiguous(rel(root, path), f"cannot classify page type: {error}")
        raw_type = meta.get("type") if isinstance(meta, dict) else None
        if raw_type is None or raw_type == "":
            continue
        if not isinstance(raw_type, str):
            return "ambiguous", _ambiguous(rel(root, path), "page type is not a string")
        if raw_type.strip().lower() in _BETA2_LAYER_CONTENT_TYPES:
            return "layer_content", None
    return "eligible", None


def _beta2_status(
    root: Path, contract_name: str, schema: dict
) -> tuple[str | None, dict | None, dict | None]:
    """Return (kind, plan, finding) for an unstamped full beta.2 init.

    ``kind`` is None when this store is not that contract shape. ``plan`` is
    set only when the store is eligible to migrate.
    """
    if not _is_unstamped_full_beta2_init(contract_name, schema):
        return None, None, None
    kind, finding = _beta2_page_status(root, schema)
    if kind != "eligible":
        return kind, None, finding
    plan, finding = _beta2_migration_plan(root, schema)
    if finding or plan is None:
        return "ambiguous", None, finding or _ambiguous(SCHEMA_NAME, "beta.2 init is not normalisable")
    return "eligible", plan, None


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
    if payload.get("beta2_init"):
        print(f"beta2_init: {payload['beta2_init']}")


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

    beta2_kind, beta2_plan, beta2_finding = _beta2_status(r, contract_name, schema)
    beta2_notes: list[str] = []
    if beta2_kind == "eligible":
        lineage = "unstamped-beta2"
        beta2_notes.append(
            "unstamped full beta.2 init with no frame, gist, page, or memory "
            "content pages; eligible for apply --batch contract-file"
        )
    elif beta2_kind == "layer_content":
        beta2_notes.append(
            "frame, gist, page, or memory content pages are present; apply "
            "refuses with in_beta_not_legacy"
        )
    elif beta2_kind == "ambiguous" and beta2_finding:
        beta2_notes.append(beta2_finding["msg"])

    if operation in ("assess", "inventory"):
        payload = {
            "ok": True,
            "root": str(r),
            "operation": operation,
            "contract_file": contract_name,
            "lineage": lineage,
            "notes": ["write nothing", *beta2_notes],
        }
        if beta2_kind:
            payload["beta2_init"] = beta2_kind
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

    if contract_lineage == "in-beta" and beta2_kind != "eligible":
        if beta2_kind == "ambiguous" and beta2_finding:
            payload = {
                "ok": False,
                "root": str(r),
                "operation": "apply",
                "contract_file": contract_name,
                "lineage": lineage,
                "beta2_init": beta2_kind,
                "error": beta2_finding["msg"],
                "findings": [beta2_finding],
            }
            _print(as_json, payload)
            return 2
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
                        "apply is only for pre-beta stores and for an unstamped full "
                        "beta.2 init with no frame, gist, page, or memory content pages; "
                        "this store is already in-beta (atlas_release 0.13.0-beta/"
                        "0.13.0-beta.2, memory.layers [frame, gist, page] or "
                        "[frame, gist, memory], or beta.2 layer content) and was not rewritten"
                    ),
                }
            ],
        }
        if beta2_kind:
            payload["beta2_init"] = beta2_kind
        _print(as_json, payload)
        return 2

    # contract_lineage == "pre-beta", or an eligible unstamped beta.2 init
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

    if beta2_plan is not None:
        schema = beta2_plan["schema"]
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
    template_notes: list[str] = []
    if beta2_plan is not None:
        files = beta2_plan["files"]
        template_notes.append(
            "aligned templates and types.recommended with current init "
            "(dropped frame and page; ensured schema and memory)"
        )
        template_notes.extend(f"removed template {rel(r, path)}" for path in files["deletes"])
        template_notes.extend(
            f"added template {rel(r, dest)}" for _, dest in files["copies"]
        )
        _apply_template_plan(files)
    payload = {
        "ok": True,
        "root": str(r),
        "operation": "apply",
        "batch": batch_value,
        "contract_file": CONTRACT_NAME,
        "lineage": "current",
        "notes": [
            f"renamed {SCHEMA_NAME} -> {CONTRACT_NAME}; set atlas_release={CURRENT_RELEASE}",
            *template_notes,
            *[f"created schema page {rel(r, path)}" for path, _ in schema_pages],
            *[f"cued schema page in {rel(r, path)}" for path in index_updates],
            *[f"removed replaced frame page {rel(r, path)}" for path in replaced_frames],
        ],
    }
    _print(as_json, payload)
    return 0
