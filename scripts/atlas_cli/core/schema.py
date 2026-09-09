from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import SCHEMA_NAME
from .type_rules import declaration_errors

# Re-export for commands that import SCHEMA_NAME from schema.


def load_schema(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return (schema_dict, error_message)."""
    path = root / SCHEMA_NAME
    if not path.is_file():
        return None, f"missing {SCHEMA_NAME}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, f"invalid JSON in {SCHEMA_NAME}: {e}"
    if not isinstance(data, dict):
        return None, f"{SCHEMA_NAME} must be a JSON object"
    return data, None


def required_root_fields(schema: dict) -> list[str]:
    declared = schema.get("required_root_fields")
    if isinstance(declared, list) and all(isinstance(key, str) for key in declared):
        return declared or ["schema_version", "atlas_id", "structure", "compile"]
    return ["schema_version", "atlas_id", "structure", "compile"]


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
    declared = schema.get("required_root_fields")
    if declared is not None and (
        not isinstance(declared, list) or not all(isinstance(key, str) for key in declared)
    ):
        errs.append("SCHEMA.required_root_fields must be a list of field names")
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
    structure = schema.get("structure", {})
    if not isinstance(structure, dict):
        errs.append("SCHEMA.structure must be an object")
    compile_cfg = schema.get("compile", {})
    if not isinstance(compile_cfg, dict):
        errs.append("SCHEMA.compile must be an object")
    budget = compile_cfg.get("simplicity_budget", {}) if isinstance(compile_cfg, dict) else {}
    if not isinstance(budget, dict):
        errs.append("SCHEMA.compile.simplicity_budget must be an object")
        budget = {}
    for key in ("max_required_frontmatter_keys_per_type", "max_required_sections_per_type"):
        if key in budget and (type(budget[key]) is not int or budget[key] < 0):
            errs.append(f"SCHEMA.compile.simplicity_budget.{key} must be a nonnegative integer")
    tmpl_obj = tmpl if isinstance(tmpl, dict) else {}
    templates = tmpl_obj.get("by_type", {})
    if isinstance(templates, dict):
        for tname, tdef in templates.items():
            rule_errors = declaration_errors(tname, tdef)
            errs.extend(rule_errors)
            if rule_errors:
                continue
            for group, key in (
                ("frontmatter", "max_required_frontmatter_keys_per_type"),
                ("sections", "max_required_sections_per_type"),
            ):
                required = tdef.get(group, {}).get("required", [])
                limit = budget.get(key)
                if type(limit) is int and len(required) > limit:
                    errs.append(
                        f"simplicity_budget exceeded for type {tname}: "
                        f"{len(required)} required {group} > {limit}"
                    )
    return errs


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
