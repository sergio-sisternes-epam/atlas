from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import CONTRACT_NAME, SCHEMA_NAME

# Re-export for commands that import SCHEMA_NAME from schema.

# 0.13.0-beta.3 stamp/shape pins (do not widen):
SHIPPED_BETA_LAYERS = ["frame", "gist", "page"]
# 0.13.0-beta.2 (PR 43, now on main) renamed the episode type page -> memory
# and moved the frame rule to one-frame-per-folder-with-a-gist, but kept
# SCHEMA.json and never stamped atlas_release. Readers must still accept
# this shape without treating it as a stamp_shape mismatch.
IN_BETA_LAYERS = ["frame", "gist", "memory"]
BETA3_LAYERS = ["schema", "gist", "memory"]
BETA3_RELEASE = "0.13.0-beta.3"
IN_BETA_RELEASES = ("0.13.0-beta.2",)


def find_contract_path(root: Path) -> tuple[Path | None, str | None]:
    """Locate the store's single contract file.

    Readers accept exactly one of SCHEMA.json / CONTRACT.json. Both present
    or neither present is a compile-closed failure (finding id
    schema_present).
    """
    schema_path = root / SCHEMA_NAME
    contract_path = root / CONTRACT_NAME
    has_schema = schema_path.is_file()
    has_contract = contract_path.is_file()
    if has_schema and has_contract:
        return None, (
            f"both {SCHEMA_NAME} and {CONTRACT_NAME} present; a store must have "
            "exactly one contract file"
        )
    if not has_schema and not has_contract:
        return None, f"missing {SCHEMA_NAME} or {CONTRACT_NAME}"
    return (schema_path if has_schema else contract_path), None


def contract_filename(root: Path) -> str | None:
    path, _ = find_contract_path(root)
    return path.name if path else None


def load_schema(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return (schema_dict, error_message)."""
    path, err = find_contract_path(root)
    if err:
        return None, err
    assert path is not None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, f"invalid JSON in {path.name}: {e}"
    if not isinstance(data, dict):
        return None, f"{path.name} must be a JSON object"
    return data, None


def compute_stamp_shape(contract_name: str, schema: dict) -> tuple[str | None, str | None]:
    """Return (shape, error). shape in {'shipped_beta', 'in_beta', 'current'}.

    The stamp (atlas_release) and the shape (contract filename + memory.layers)
    must agree or compile fails closed with finding id stamp_shape:

    - SCHEMA.json, layers frame/gist/page, atlas_release absent/"0.13.0-beta"
      (or absent entirely): shipped_beta — reads/compiles under old frame rules.
    - SCHEMA.json, atlas_release "0.13.0-beta.2": in_beta, regardless of layers.
    - CONTRACT.json, atlas_release "0.13.0-beta.3", layers schema/gist/memory:
      current — the beta.3 contract shape.
    - Anything else is a stamp_shape mismatch (shape is None).
    """
    memory = schema.get("memory") if isinstance(schema.get("memory"), dict) else None
    layers = memory.get("layers") if isinstance(memory, dict) else None
    atlas_release = schema.get("atlas_release")

    if contract_name == SCHEMA_NAME:
        if atlas_release == BETA3_RELEASE:
            return None, (
                f"SCHEMA.json cannot carry atlas_release={BETA3_RELEASE!r}; "
                f"the {BETA3_RELEASE} contract shape is written to {CONTRACT_NAME}"
            )
        if atlas_release in IN_BETA_RELEASES:
            return "in_beta", None
        if layers in (None, SHIPPED_BETA_LAYERS):
            return "shipped_beta", None
        if layers == IN_BETA_LAYERS:
            return "in_beta", None
        return None, (
            f"SCHEMA.json memory.layers={layers!r} does not match the shipped beta shape "
            f"{SHIPPED_BETA_LAYERS!r} or the 0.13.0-beta.2 shape {IN_BETA_LAYERS!r} "
            f"(atlas_release={atlas_release!r})"
        )

    if contract_name == CONTRACT_NAME:
        if atlas_release == BETA3_RELEASE and layers == BETA3_LAYERS:
            return "current", None
        return None, (
            f"CONTRACT.json atlas_release={atlas_release!r} layers={layers!r} does not match "
            f"the {BETA3_RELEASE} contract shape (layers={BETA3_LAYERS!r})"
        )

    return None, f"unknown contract filename {contract_name!r}"


def required_root_fields(schema: dict) -> list[str]:
    return list(schema.get("required_root_fields") or ["schema_version", "atlas_id", "structure", "compile"])


def skill_root() -> Path:
    """Atlas skill root (parent of scripts/)."""
    return Path(__file__).resolve().parents[3]


def load_contract() -> dict[str, Any] | None:
    path = skill_root() / "references" / "SCHEMA.contract.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def recommended_types(schema: dict) -> list[str]:
    types = schema.get("types") or {}
    rec = types.get("recommended") or []
    return [str(t) for t in rec] if isinstance(rec, list) else []


def unconstrained_types(schema: dict) -> set[str]:
    types = schema.get("types") or {}
    raw = types.get("unconstrained") or []
    return {str(t) for t in raw} if isinstance(raw, list) else set()


def by_type_map(schema: dict) -> dict[str, Any]:
    templates = schema.get("templates") or {}
    by_type = templates.get("by_type") or {}
    return by_type if isinstance(by_type, dict) else {}


def page_contract(schema: dict) -> dict[str, Any]:
    compile_cfg = schema.get("compile") or {}
    pc = compile_cfg.get("page_contract") or {}
    return pc if isinstance(pc, dict) else {}


def validate_against_contract(schema: dict, contract: dict | None) -> list[str]:
    """Layer 1: live SCHEMA must carry the contract's required root fields."""
    if not contract:
        return []
    errs: list[str] = []
    for key in contract.get("required_root_fields") or []:
        if key not in schema:
            errs.append(f"SCHEMA missing contract field: {key}")
    return errs


def recommended_without_contract(schema: dict) -> list[str]:
    """Recommended types that have no by_type block and are not marked unconstrained."""
    by_type = by_type_map(schema)
    free = unconstrained_types(schema)
    missing: list[str] = []
    for tname in recommended_types(schema):
        if tname in free:
            continue
        block = by_type.get(tname)
        if not isinstance(block, dict) or not (block.get("frontmatter") or {}).get("required"):
            missing.append(tname)
    return missing


def validate_schema_shape(schema: dict) -> list[str]:
    """Structural checks on SCHEMA.json itself."""
    errs: list[str] = []
    for key in required_root_fields(schema):
        # required_root_fields may be listed inside the contract file; for a live
        # Atlas SCHEMA the keys must exist on the object itself.
        if key == "required_root_fields":
            continue
        if key not in schema:
            errs.append(f"SCHEMA missing required field: {key}")
    if "atlas_id" in schema and not str(schema.get("atlas_id") or "").strip():
        errs.append("SCHEMA atlas_id is empty")
    tmpl = schema.get("templates")
    if tmpl is not None and not isinstance(tmpl, dict):
        errs.append("SCHEMA.templates must be an object")
    elif isinstance(tmpl, dict):
        by = tmpl.get("by_type")
        if by is not None and not isinstance(by, dict):
            errs.append("SCHEMA.templates.by_type must be an object")
    structure = schema.get("structure") or {}
    if not isinstance(structure, dict):
        errs.append("SCHEMA.structure must be an object")
    compile_cfg = schema.get("compile") or {}
    if not isinstance(compile_cfg, dict):
        errs.append("SCHEMA.compile must be an object")
    budget = (compile_cfg.get("simplicity_budget") or {}) if isinstance(compile_cfg, dict) else {}
    if budget:
        max_keys = budget.get("max_required_frontmatter_keys_per_type")
        max_secs = budget.get("max_required_sections_per_type")
        tmpl_obj = schema.get("templates") if isinstance(schema.get("templates"), dict) else {}
        templates = tmpl_obj.get("by_type") if isinstance(tmpl_obj.get("by_type"), dict) else {}
        if isinstance(templates, dict):
            for tname, tdef in templates.items():
                if not isinstance(tdef, dict):
                    continue
                fm = tdef.get("frontmatter") or {}
                req = fm.get("required") or []
                if max_keys is not None and len(req) > int(max_keys):
                    errs.append(
                        f"simplicity_budget exceeded for type {tname}: "
                        f"{len(req)} required frontmatter keys > {max_keys}"
                    )
                secs = (tdef.get("sections") or {}).get("required") or []
                if max_secs is not None and len(secs) > int(max_secs):
                    errs.append(
                        f"simplicity_budget exceeded for type {tname}: "
                        f"{len(secs)} required sections > {max_secs}"
                    )
    return errs


def classify_lineage(contract_name: str, schema: dict) -> str:
    """Classify a store for `memory-migrate` (path memory-migrate / pin 5).

    - current: the beta.3 shape (CONTRACT.json, atlas_release 0.13.0-beta.3,
      memory.layers schema/gist/memory).
    - in-beta: atlas_release is exactly "0.13.0-beta" or "0.13.0-beta.2", OR
      SCHEMA.json already has memory.layers ["frame", "gist", "page"].
    - pre-beta: contract file is SCHEMA.json, no memory object, and
      atlas_release is absent or older than 0.13.0-beta (e.g. 0.12.0).
    Anything not covered by the three rules above is treated as in-beta so
    `apply` never silently rewrites a shape it was not told about.
    """
    atlas_release = schema.get("atlas_release")
    memory = schema.get("memory") if isinstance(schema.get("memory"), dict) else None
    layers = memory.get("layers") if isinstance(memory, dict) else None

    if contract_name == CONTRACT_NAME and atlas_release == BETA3_RELEASE and layers == BETA3_LAYERS:
        return "current"

    if atlas_release in ("0.13.0-beta", *IN_BETA_RELEASES):
        return "in-beta"
    if contract_name == SCHEMA_NAME and layers == SHIPPED_BETA_LAYERS:
        return "in-beta"

    if contract_name == SCHEMA_NAME and memory is None and atlas_release != BETA3_RELEASE:
        return "pre-beta"

    return "in-beta"


def staging_dir_name(schema: dict | None) -> str:
    if not schema:
        return "staging"
    structure = schema.get("structure") or {}
    return str(structure.get("staging_dir") or "staging")


def min_body_chars(schema: dict | None) -> int:
    if not schema:
        return 40
    compile_cfg = schema.get("compile") or {}
    return int(compile_cfg.get("min_body_chars") or 40)
