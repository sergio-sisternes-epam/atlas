from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from .. import __version__
from ..core.overlay import merge_overlays, receipt_issues
from ..core.paths import store_root
from ..core.schema import load_contract, validate_against_contract, validate_schema_shape
from .schema_cmd import _print

CAPABILITIES = {
    "required_h2_sections": 1,
    "scalar_date_rules": 1,
    "date_order_rules": 1,
    "typed_local_relates_to": 1,
    "core_section_budget_configure": 1,
    "receipt_hash_template_upgrades": 1,
}


def capabilities(as_json: bool = False) -> int:
    payload = {
        "ok": True,
        "capability_version": 1,
        "atlas_version": __version__,
        "features": CAPABILITIES,
        "frontmatter_format": "atlas-minimal",
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"atlas {__version__} — schema capabilities v1")
        for feature, version in CAPABILITIES.items():
            print(f"  {feature}: {version}")
    return 0


def configure(root: str | None, max_sections: int, as_json: bool = False) -> int:
    r = store_root(root)
    path = r / "SCHEMA.json"
    temporary: Path | None = None
    try:
        if path.is_symlink():
            raise ValueError("SCHEMA.json must not be a symlink")
        if type(max_sections) is not int or max_sections < 0:
            raise ValueError("max-required-sections-per-type must be a nonnegative integer")
        original = path.read_bytes()
        schema = json.loads(original)
        if not isinstance(schema, dict):
            raise ValueError("SCHEMA.json must be an object")
        errors = validate_schema_shape(schema) + validate_against_contract(schema, load_contract())
        if errors:
            raise ValueError("; ".join(errors))
        candidate = deepcopy(schema)
        candidate["compile"].setdefault("simplicity_budget", {})["max_required_sections_per_type"] = max_sections
        merged, critical, _ = merge_overlays(candidate, r)
        errors = validate_schema_shape(merged) + validate_against_contract(merged, load_contract())
        errors.extend(issue["msg"] for issue in critical + receipt_issues(r))
        if errors:
            raise ValueError("; ".join(errors))
        content = (json.dumps(candidate, indent=2) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(prefix=".SCHEMA-", suffix=".tmp", dir=r, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(path.stat().st_mode & 0o777)
        if path.is_symlink() or path.read_bytes() != original:
            raise ValueError("SCHEMA.json changed during configure; retry against the current version")
        os.replace(temporary, path)
        temporary = None
    except (OSError, ValueError) as exc:
        _print(as_json, {"ok": False, "root": str(r), "error": str(exc)})
        return 2
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    _print(as_json, {
        "ok": True,
        "root": str(r),
        "setting": "compile.simplicity_budget.max_required_sections_per_type",
        "value": max_sections,
        "notes": [f"max_required_sections_per_type = {max_sections}; compile the store after configuration"],
    })
    return 0
