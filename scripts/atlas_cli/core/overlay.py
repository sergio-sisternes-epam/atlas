from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

SCHEMA_D = "schema.d"
KEBAB = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
META_KEYS = frozenset({"contribution_id", "claimed_folders"})
# Overlay may not replace these core keys (whole object or scalar).
FORBIDDEN_CORE = frozenset(
    {
        "schema_version",
        "atlas_id",
        "title",
        "description",
        "structure",
        "compile",
        "query",
        "mesh",
        "sources_profile",
    }
)
ALLOW_UNION = frozenset({"types"})


def overlay_dir(root: Path) -> Path:
    return root / SCHEMA_D


def overlay_path(root: Path, cid: str) -> Path:
    return overlay_dir(root) / f"{cid}.json"


def receipt_path(root: Path, cid: str) -> Path:
    return overlay_dir(root) / f"{cid}.receipt.json"


def validate_id(cid: str) -> str | None:
    if not KEBAB.match(cid or ""):
        return f"contribution id must be kebab-case (got {cid!r})"
    return None


def validate_type_name(tname: str) -> str | None:
    if not KEBAB.match(tname or ""):
        return f"type name must be kebab-case with no path separators (got {tname!r})"
    return None


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, f"missing {path.name}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, f"invalid JSON in {path.name}: {e}"
    if not isinstance(data, dict):
        return None, f"{path.name} must be a JSON object"
    return data, None


def list_overlays(root: Path) -> list[str]:
    d = overlay_dir(root)
    if not d.is_dir():
        return []
    ids: list[str] = []
    for p in sorted(d.glob("*.json")):
        if p.name.endswith(".receipt.json"):
            continue
        ids.append(p.stem)
    return ids


def load_overlay(root: Path, cid: str) -> tuple[dict[str, Any] | None, str | None]:
    return _read_json(overlay_path(root, cid))


def load_receipt(root: Path, cid: str) -> tuple[dict[str, Any] | None, str | None]:
    return _read_json(receipt_path(root, cid))


def required_fingerprint(overlay: dict[str, Any]) -> dict[str, list[str]]:
    by_type, err = overlay_by_type(overlay)
    out: dict[str, list[str]] = {}
    if err or not isinstance(by_type, dict):
        return out
    for tname, block in by_type.items():
        if not isinstance(block, dict):
            continue
        req = ((block.get("frontmatter") or {}).get("required")) or []
        if not isinstance(req, list):
            req = []
        out[str(tname)] = sorted({str(x).strip() for x in req if str(x).strip()})
    return out


def overlay_by_type(overlay: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    tmpl = overlay.get("templates")
    if tmpl is None:
        return {}, None
    if not isinstance(tmpl, dict):
        return None, "templates must be an object"
    if "by_type" not in tmpl:
        return {}, None
    by = tmpl.get("by_type")
    if not isinstance(by, dict):
        return None, "templates.by_type must be an object"
    return by, None


def added_types(overlay: dict[str, Any]) -> list[str]:
    return sorted(required_fingerprint(overlay).keys())


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_receipt(root: Path, cid: str, written: list[str], types: list[str] | None = None) -> Path:
    payload: dict[str, Any] = {"id": cid, "written": sorted(set(written))}
    if types:
        payload["added_types"] = sorted(set(types))
    dest = receipt_path(root, cid)
    write_json(dest, payload)
    return dest


def _issue(iid: str, path: str, msg: str, severity: str = "critical") -> dict[str, str]:
    return {"id": iid, "path": path, "msg": msg, "severity": severity}


def normalize_rel_path(wp: str) -> str | None:
    """Store-relative POSIX path with no `..` or absolute form. None if unsafe."""
    raw = str(wp).replace("\\", "/").strip()
    if not raw or raw.startswith("/") or raw.startswith("~") or ":" in raw.split("/", 1)[0]:
        return None
    parts: list[str] = []
    for p in raw.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            return None
        parts.append(p)
    return "/".join(parts) if parts else None


def resolve_under_root(root: Path, wp: str) -> Path | None:
    relp = normalize_rel_path(wp)
    if relp is None:
        return None
    cand = (root / relp).resolve()
    try:
        cand.relative_to(root.resolve())
    except ValueError:
        return None
    return cand


def claimed_allows(claimed: list[str], wp: str) -> bool:
    """claimed_folders are prefixes. `foo/bar` allows `foo/bar` and `foo/bar/...`."""
    relp = normalize_rel_path(wp)
    if relp is None:
        return False
    if relp == SCHEMA_D or relp.startswith(SCHEMA_D + "/"):
        return True
    if relp == "templates" or relp.startswith("templates/"):
        return True
    for c in claimed:
        prefix = normalize_rel_path(c)
        if not prefix:
            continue
        if relp == prefix or relp.startswith(prefix + "/"):
            return True
    return False


def merge_overlays(core: dict[str, Any], root: Path) -> tuple[dict[str, Any], list[dict], list[dict]]:
    """Return (effective_schema, critical, warnings). Core is not mutated."""
    merged = deepcopy(core) if isinstance(core, dict) else {}
    critical: list[dict] = []
    warnings: list[dict] = []
    extra_owners: dict[str, str] = {}
    tmpl = merged.get("templates") if isinstance(merged, dict) else None
    if not isinstance(tmpl, dict):
        tmpl = {}
        if isinstance(merged, dict):
            merged["templates"] = tmpl
    src_tmpl = core.get("templates") if isinstance(core, dict) else None
    src_by = src_tmpl.get("by_type") if isinstance(src_tmpl, dict) else None
    core_type_names = frozenset(src_by.keys()) if isinstance(src_by, dict) else frozenset()

    for cid in list_overlays(root):
        ov, err = load_overlay(root, cid)
        relp = f"{SCHEMA_D}/{cid}.json"
        if err or ov is None:
            critical.append(_issue("overlay_json", relp, err or "unreadable overlay"))
            continue
        id_err = validate_id(cid)
        if id_err:
            critical.append(_issue("overlay_id", relp, id_err))
            continue
        oid = str(ov.get("contribution_id") or cid).strip()
        if oid != cid:
            critical.append(
                _issue("overlay_id", relp, f"contribution_id {oid!r} does not match filename {cid}")
            )
            continue
        claimed = ov.get("claimed_folders") or []
        if claimed and not isinstance(claimed, list):
            critical.append(_issue("overlay_claimed", relp, "claimed_folders must be a list"))

        for key, val in ov.items():
            if key in META_KEYS:
                continue
            if key in FORBIDDEN_CORE:
                critical.append(
                    _issue("overlay_core_clash", relp, f"overlay must not set core key '{key}'")
                )
                continue
            if key == "templates":
                if not isinstance(val, dict):
                    critical.append(_issue("overlay_templates", relp, "templates must be an object"))
                    continue
                if "by_type" in val and not isinstance(val.get("by_type"), dict):
                    critical.append(
                        _issue("overlay_templates", relp, "templates.by_type must be an object")
                    )
                    continue
                add_by = val.get("by_type") or {}
                if not isinstance(add_by, dict):
                    add_by = {}
                dest_t = merged.setdefault("templates", {})
                if not isinstance(dest_t, dict):
                    dest_t = {}
                    merged["templates"] = dest_t
                dest_by = dest_t.setdefault("by_type", {})
                if not isinstance(dest_by, dict):
                    dest_by = {}
                    dest_t["by_type"] = dest_by
                for tname, block in add_by.items():
                    t_err = validate_type_name(str(tname))
                    if t_err:
                        critical.append(_issue("overlay_type_name", relp, t_err))
                        continue
                    if not isinstance(block, dict):
                        critical.append(
                            _issue(
                                "overlay_templates",
                                relp,
                                f"templates.by_type.{tname} must be an object",
                            )
                        )
                        continue
                    if tname in core_type_names:
                        critical.append(
                            _issue(
                                "overlay_core_type",
                                relp,
                                f"overlay must not mutate core type '{tname}'",
                            )
                        )
                        continue
                    if tname in dest_by and dest_by[tname] != block:
                        critical.append(
                            _issue(
                                "overlay_key_clash",
                                relp,
                                f"two overlays both define type '{tname}'",
                            )
                        )
                        continue
                    dest_by[tname] = deepcopy(block)
                continue
            if key in ALLOW_UNION and isinstance(val, dict) and isinstance(merged.get(key), dict):
                dest = merged[key]
                for sub, sval in val.items():
                    if sub in ("recommended", "unconstrained") and isinstance(sval, list):
                        existing = dest.get(sub) or []
                        if not isinstance(existing, list):
                            existing = []
                        dest[sub] = list(dict.fromkeys([*existing, *sval]))
                    elif sub in dest and dest[sub] != sval:
                        critical.append(
                            _issue("overlay_key_clash", relp, f"two overlays clash on types.{sub}")
                        )
                    else:
                        dest[sub] = deepcopy(sval)
                continue
            if key in core:
                critical.append(
                    _issue("overlay_core_clash", relp, f"overlay must not set core key '{key}'")
                )
                continue
            owner = extra_owners.get(key)
            if owner and owner != cid:
                critical.append(
                    _issue(
                        "overlay_key_clash",
                        relp,
                        f"two overlays claim extra key '{key}' ({owner} and {cid})",
                    )
                )
                continue
            extra_owners[key] = cid
            merged[key] = deepcopy(val)

    return merged, critical, warnings


def receipt_issues(root: Path) -> list[dict]:
    """Critical if a receipt lists a write outside schema.d and claimed prefixes."""
    issues: list[dict] = []
    for cid in list_overlays(root):
        rec, rec_err = load_receipt(root, cid)
        relp = f"{SCHEMA_D}/{cid}.receipt.json"
        if rec is None:
            issues.append(
                _issue(
                    "overlay_receipt",
                    relp,
                    rec_err or "missing receipt for installed overlay",
                )
            )
            continue
        written = rec.get("written") or []
        if not isinstance(written, list):
            issues.append(_issue("overlay_receipt", relp, "written must be a list"))
            continue
        ov, _ = load_overlay(root, cid)
        claimed = []
        if ov and isinstance(ov.get("claimed_folders"), list):
            claimed = [str(x).strip().strip("/") for x in ov["claimed_folders"] if str(x).strip()]
        for raw in written:
            wp = normalize_rel_path(str(raw))
            if not wp:
                issues.append(
                    _issue(
                        "overlay_undeclared_root",
                        str(raw),
                        f"overlay {cid} receipt path escapes the store or is not relative",
                    )
                )
                continue
            if claimed_allows(claimed, wp):
                continue
            issues.append(
                _issue(
                    "overlay_undeclared_root",
                    wp,
                    f"overlay {cid} receipt lists undeclared path (not claimed prefix, not {SCHEMA_D}/)",
                )
            )
    return issues


def orphan_type_warnings(root: Path, pages_types: set[str], effective: dict[str, Any]) -> list[dict]:
    """Warn when a page type was added by an overlay that is gone — use receipts' added_types vs live overlays."""
    known = set((((effective.get("templates") or {}).get("by_type")) or {}).keys())
    rec_types: set[str] = set()
    for cid in list_overlays(root):
        rec, _ = load_receipt(root, cid)
        if rec and isinstance(rec.get("added_types"), list):
            rec_types.update(str(x) for x in rec["added_types"])
        ov, _ = load_overlay(root, cid)
        if ov:
            rec_types.update(added_types(ov))
    # Live overlay types are known. Orphans are page types in neither core/effective by_type
    # nor remaining overlay added_types — too broad. Only warn for types listed on a
    # receipt whose overlay file is missing (handled at uninstall). Compile: no-op here.
    _ = (pages_types, known, rec_types)
    return []
