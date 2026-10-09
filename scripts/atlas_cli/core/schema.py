from __future__ import annotations

import json
import re
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
# BETA3_RELEASE ("0.13.0-beta.3") is the original stamp for this contract
# shape. It, "0.13.0-beta.4" and "0.13.0-beta.7" are still accepted on read
# (compute_stamp_shape / classify_lineage -> "current") but are no longer
# written. CURRENT_RELEASE ("0.13.0") is the stamp that `atlas init` and
# `memory-migrate apply --batch contract-file` WRITE for this same shape.
# All four stamps, with layers schema/gist/memory on CONTRACT.json, are
# "current" and never unknown. Only the explicit, operator-chosen
# `memory-migrate apply --batch restamp` moves an older accepted stamp to
# CURRENT_RELEASE; no other path rewrites a current stamp.
BETA3_RELEASE = "0.13.0-beta.3"
CURRENT_RELEASE = "0.13.0"
OLDER_CURRENT_STAMPS = (BETA3_RELEASE, "0.13.0-beta.4", "0.13.0-beta.7")
CURRENT_STAMPS = (*OLDER_CURRENT_STAMPS, CURRENT_RELEASE)
IN_BETA_RELEASES = ("0.13.0-beta.2",)


def find_contract_path(root: Path) -> tuple[Path | None, str | None]:
    """Locate the store's single contract file.

    Readers accept exactly one of SCHEMA.json / CONTRACT.json. Both present
    or neither present is a compile-closed failure (finding id
    schema_present).
    """
    schema_path = root / SCHEMA_NAME
    contract_path = root / CONTRACT_NAME
    # is_file() follows symlinks (and is False for a broken link, which would
    # otherwise let a later write_text() follow the link, even outside the
    # root, before anyone noticed). Reject either filename as a symlink
    # before ever treating it as the contract file — this must happen
    # before the is_file() checks below so a broken symlink is also caught.
    if schema_path.is_symlink():
        return None, f"{SCHEMA_NAME} is a symlink; refusing to use it as the contract file"
    if contract_path.is_symlink():
        return None, f"{CONTRACT_NAME} is a symlink; refusing to use it as the contract file"
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


# The only unstamped (or "0.13.0-beta"-stamped) release markers that may
# resolve to shipped_beta. Any other stamp value — including unknown or
# newer ones such as "0.13.0-beta.5" — must fail stamp_shape instead of
# silently compiling under the old frame rules.
SHIPPED_BETA_STAMPS = (None, "0.13.0-beta")


def _is_full_beta2_init(schema: dict) -> bool:
    """True when ``schema`` is a full shipped-beta.2 init document.

    The shipped beta.2 default had neither ``atlas_release`` nor a ``memory``
    object (so ``memory.layers`` is absent, not ``IN_BETA_LAYERS``), but its
    full-init shape — templates plus types.recommended including "frame" —
    is still the beta.2 shape (memory / one gist), not the original shipped
    beta page/frame shape. Shared by ``compute_stamp_shape`` and
    ``classify_lineage`` so the two never disagree on this document. This
    inference only applies when ``atlas_release`` is absent; a document
    stamped exactly "0.13.0-beta" keeps its explicit shipped_beta path even
    if it happens to also carry this full-init shape.
    """
    types = schema.get("types") if isinstance(schema.get("types"), dict) else None
    recommended_types = types.get("recommended") if isinstance(types, dict) else None
    return (
        "templates" in schema
        and isinstance(recommended_types, list)
        and "frame" in recommended_types
    )


def is_unstamped_full_beta2_init(contract_name: str, schema: dict) -> bool:
    """True for a released beta.2 init document with no stamp and no memory key.

    ``classify_lineage`` still reports this document as ``in-beta`` so it
    keeps agreeing with ``compute_stamp_shape``. ``memory-migrate`` is the
    caller that may treat the same document as contract-file eligible, and
    only when the store also has no frame, gist, page, or memory content
    pages. A present ``atlas_release`` or ``memory`` key — even null — is
    not this document.
    """
    if contract_name != SCHEMA_NAME:
        return False
    if "atlas_release" in schema or "memory" in schema:
        return False
    return _is_full_beta2_init(schema)


def compute_stamp_shape(contract_name: str, schema: dict) -> tuple[str | None, str | None]:
    """Return (shape, error). shape in {'shipped_beta', 'in_beta', 'current'}.

    The stamp (atlas_release) and the shape (contract filename + memory.layers)
    must agree or compile fails closed with finding id stamp_shape:

    - SCHEMA.json, atlas_release absent or exactly "0.13.0-beta", layers
      frame/gist/page (or absent and not the full beta.2 init document):
      shipped_beta — reads/compiles under old frame rules. Any other stamp
      value never resolves to shipped_beta, even when layers happen to
      match; an unknown stamp (e.g. "0.13.0-beta.5") always fails closed,
      regardless of layers.
    - SCHEMA.json, atlas_release "0.13.0-beta.2": in_beta, regardless of
      layers. SCHEMA.json with layers frame/gist/memory and a known stamp
      (absent or "0.13.0-beta.2") is also in_beta (the shipped beta.2
      layers shape), and so is an unstamped full beta.2 init document
      (templates plus types.recommended including "frame") with no memory
      key at all — align with classify_lineage.
    - CONTRACT.json, atlas_release "0.13.0-beta.3", "0.13.0-beta.4",
      "0.13.0-beta.7" or "0.13.0", layers schema/gist/memory: current — the
      current contract shape. beta.3 is the original stamp; beta.3, beta.4
      and beta.7 are still accepted on read; "0.13.0" is the stamp
      `atlas init` and `memory-migrate apply` WRITE for this shape. Any
      other stamp (e.g. "0.13.0-beta.6", "0.13.1", "0.13.0-rc.1") fails
      closed.
    - Anything else is a stamp_shape mismatch (shape is None).
    """
    memory = schema.get("memory") if isinstance(schema.get("memory"), dict) else None
    layers = memory.get("layers") if isinstance(memory, dict) else None
    atlas_release = schema.get("atlas_release")

    if contract_name == SCHEMA_NAME:
        if atlas_release in CURRENT_STAMPS:
            return None, (
                f"SCHEMA.json cannot carry atlas_release={atlas_release!r}; "
                f"the current contract shape is written to {CONTRACT_NAME}"
            )
        if atlas_release in IN_BETA_RELEASES:
            return "in_beta", None
        if atlas_release not in SHIPPED_BETA_STAMPS:
            # Unknown/newer stamps (e.g. "0.13.0-beta.5") must fail closed
            # rather than inferring a shape from memory.layers alone — an
            # unknown stamp never resolves to in_beta or shipped_beta.
            return None, (
                f"SCHEMA.json atlas_release={atlas_release!r} is not a known stamp "
                '(absent, "0.13.0-beta", or "0.13.0-beta.2")'
            )
        if layers == SHIPPED_BETA_LAYERS:
            return "shipped_beta", None
        if layers == IN_BETA_LAYERS:
            return "in_beta", None
        if layers is None:
            # The full-init -> in_beta inference only applies when
            # atlas_release is absent entirely. A document stamped exactly
            # "0.13.0-beta" with no memory key stays shipped_beta even when
            # it also carries templates/types.recommended with "frame" —
            # the known stamp wins over the full-init heuristic.
            if atlas_release is None and _is_full_beta2_init(schema):
                return "in_beta", None
            return "shipped_beta", None
        return None, (
            f"SCHEMA.json atlas_release={atlas_release!r} memory.layers={layers!r} does not "
            f"match the shipped beta shape {SHIPPED_BETA_LAYERS!r} (stamp absent or "
            f'"0.13.0-beta") or the 0.13.0-beta.2 shape {IN_BETA_LAYERS!r}'
        )

    if contract_name == CONTRACT_NAME:
        if atlas_release in CURRENT_STAMPS and layers == BETA3_LAYERS:
            return "current", None
        return None, (
            f"CONTRACT.json atlas_release={atlas_release!r} layers={layers!r} does not match "
            f"the current contract shape ({CURRENT_STAMPS!r}, layers={BETA3_LAYERS!r})"
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



# Full semver: X.Y.Z optionally followed by a -prerelease and/or +build
# suffix made of dot-separated alphanumeric/hyphen identifiers. Using
# fullmatch (via $ anchor with no re.match prefix shortcut) means a
# malformed value such as "0.12.0oops" — which merely starts with a valid
# X.Y.Z prefix — never matches and so is never treated as older/pre-beta.
_FULL_SEMVER_RE = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _release_older_than_beta_line(atlas_release: Any) -> bool:
    """True when atlas_release is absent, or a full X.Y.Z semver is < 0.13.0.

    The value must match a *complete* semver (anchored start to end) before
    its numeric parts are compared — a malformed value that merely starts
    with a valid X.Y.Z prefix, such as "0.12.0oops", must never be treated
    as older/pre-beta; it fails closed to "not older" so `apply` falls
    through to in-beta rather than migrating an unknown stamp. Unknown,
    non-numeric, or newer-looking values (including unknown beta stamps
    such as "0.13.0-beta.5") are likewise never treated as older, and
    neither is the final "0.13.0" write stamp itself.
    """
    if atlas_release is None:
        return True
    if not isinstance(atlas_release, str):
        return False
    match = _FULL_SEMVER_RE.match(atlas_release)
    if not match:
        return False
    major, minor, patch = (int(part) for part in match.groups())
    return (major, minor, patch) < (0, 13, 0)


def classify_lineage(contract_name: str, schema: dict) -> str:
    """Classify a store for `memory-migrate` (path memory-migrate / pin 5).

    - current: the current contract shape (CONTRACT.json, atlas_release
      0.13.0-beta.3, 0.13.0-beta.4, 0.13.0-beta.7, or 0.13.0, memory.layers
      schema/gist/memory). beta.3, beta.4 and beta.7 remain current on read
      (default apply is a no-op; only the explicit restamp batch rewrites
      the stamp); 0.13.0 is the stamp `apply`/`atlas init` WRITE.
    - in-beta: atlas_release is exactly "0.13.0-beta" or "0.13.0-beta.2", OR
      SCHEMA.json already has memory.layers ["frame", "gist", "page"], OR
      SCHEMA.json is a full shipped-beta.2 init document (templates plus
      types.recommended including "frame") even though it has no memory key
      and no atlas_release stamp. ``memory-migrate`` may still apply that
      last document when the store has no frame, gist, page, or memory
      content pages; this function stays ``in-beta`` either way so it keeps
      agreeing with ``compute_stamp_shape``. The command reports that empty
      store as lineage ``empty-beta2-init``.
    - pre-beta: contract file is SCHEMA.json, the `memory` key is absent
      (not merely present-but-invalid), it is not the full shipped-beta.2
      init document above, and atlas_release is absent or semantically
      older than the 0.13.0-beta line (e.g. 0.12.0).
    Anything not covered by the three rules above is treated as in-beta so
    `apply` never silently rewrites a shape it was not told about — this
    includes unknown or newer atlas_release values and a present-but-invalid
    (non-object) `memory` value.
    """
    atlas_release = schema.get("atlas_release")
    has_memory_key = "memory" in schema
    memory = schema.get("memory") if isinstance(schema.get("memory"), dict) else None
    layers = memory.get("layers") if isinstance(memory, dict) else None

    if contract_name == CONTRACT_NAME and atlas_release in CURRENT_STAMPS and layers == BETA3_LAYERS:
        return "current"

    if atlas_release in ("0.13.0-beta", *IN_BETA_RELEASES):
        return "in-beta"
    if contract_name == SCHEMA_NAME and layers == SHIPPED_BETA_LAYERS:
        return "in-beta"

    full_init_shape = _is_full_beta2_init(schema)
    if contract_name == SCHEMA_NAME and full_init_shape:
        return "in-beta"

    if (
        contract_name == SCHEMA_NAME
        and not has_memory_key
        and _release_older_than_beta_line(atlas_release)
    ):
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
