from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ACCESS_ENUM = frozenset({"read", "read/write"})
REQUIRED_ENTRY = ("id", "root", "access")


def _load_json(path: Path) -> tuple[dict | list | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    except OSError as e:
        return None, str(e)
    return data, None


def discover_fragments(root: Path) -> list[Path]:
    """Find partial mesh fragment files under the Atlas root."""
    names = (
        "mesh.fragment.json",
        "mesh.partial.json",
        "mesh-fragment.json",
    )
    found: list[Path] = []
    for p in sorted(root.rglob("*.json")):
        if p.name in names or p.name.endswith(".mesh.fragment.json"):
            found.append(p)
        # also accept mesh/fragments/*.json
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) >= 2 and parts[0] == "mesh" and parts[1] in ("fragments", "partial"):
            if p.suffix == ".json" and p.name != "mesh.json":
                found.append(p)
    # de-dupe preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for p in found:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


def _entries_from_doc(data: Any, source: str) -> tuple[list[dict], list[str]]:
    errs: list[str] = []
    entries: list[dict] = []
    if isinstance(data, dict):
        raw = data.get("atlases") or data.get("entries") or data.get("mesh")
        if raw is None and "id" in data:
            raw = [data]
        if raw is None:
            errs.append(f"{source}: no atlases/entries list")
            return [], errs
    elif isinstance(data, list):
        raw = data
    else:
        errs.append(f"{source}: root must be object or array")
        return [], errs

    if not isinstance(raw, list):
        errs.append(f"{source}: atlases must be a list")
        return [], errs

    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            errs.append(f"{source}[{i}]: entry must be object")
            continue
        entries.append({**item, "_source": source})
    return entries, errs


def validate_entry(entry: dict, source: str) -> list[str]:
    errs: list[str] = []
    for key in REQUIRED_ENTRY:
        if not str(entry.get(key) or "").strip():
            errs.append(f"{source}: missing required field '{key}'")
    access = str(entry.get("access") or "").strip()
    if access and access not in ACCESS_ENUM:
        errs.append(
            f"{source}: invalid access '{access}' (expected read | read/write)"
        )
    contrib = entry.get("contribution")
    if contrib is not None:
        if not isinstance(contrib, dict):
            errs.append(f"{source}: contribution must be an object")
        else:
            # optional keys only — type / repository
            for k in contrib:
                if k not in ("type", "repository"):
                    # tolerate extra keys but note? keep strict-light: allow extras
                    pass
    return errs


def consolidate(root: Path) -> dict[str, Any]:
    """
    Merge all partial fragments; return result structure:
      ok, critical[], warnings[], mesh (dict|None), written (path|None)
    """
    critical: list[dict] = []
    warnings: list[dict] = []
    fragments = discover_fragments(root)

    if not fragments:
        return {
            "ok": True,
            "critical": [],
            "warnings": [],
            "mesh": None,
            "written": None,
            "fragment_count": 0,
            "note": "no mesh fragments found — mesh step skipped",
        }

    all_entries: list[dict] = []
    for fp in fragments:
        rel = str(fp.relative_to(root)).replace("\\", "/")
        data, err = _load_json(fp)
        if err:
            critical.append({"id": "mesh_fragment", "path": rel, "msg": err})
            continue
        entries, errs = _entries_from_doc(data, rel)
        for e in errs:
            critical.append({"id": "mesh_fragment", "path": rel, "msg": e})
        for ent in entries:
            for ve in validate_entry(ent, rel):
                critical.append({"id": "mesh_schema", "path": rel, "msg": ve})
            all_entries.append(ent)

    # merge by id
    by_id: dict[str, dict] = {}
    for ent in all_entries:
        eid = str(ent.get("id") or "").strip()
        if not eid:
            continue
        if eid not in by_id:
            by_id[eid] = dict(ent)
            continue
        prev = by_id[eid]
        # conflicts
        for field in ("root", "access"):
            a = str(prev.get(field) or "").strip()
            b = str(ent.get(field) or "").strip()
            if a and b and a != b:
                critical.append(
                    {
                        "id": "mesh_conflict",
                        "path": eid,
                        "msg": (
                            f"conflict on '{field}': "
                            f"{prev.get('_source')} has {a!r}, "
                            f"{ent.get('_source')} has {b!r}"
                        ),
                    }
                )
        # contribution conflict if both present and differ
        ca, cb = prev.get("contribution"), ent.get("contribution")
        if isinstance(ca, dict) and isinstance(cb, dict) and ca != cb:
            critical.append(
                {
                    "id": "mesh_conflict",
                    "path": eid,
                    "msg": (
                        f"conflict on contribution between "
                        f"{prev.get('_source')} and {ent.get('_source')}"
                    ),
                }
            )
        # fill missing optional fields from later fragment
        for k, v in ent.items():
            if k == "_source":
                continue
            if k not in prev or prev[k] in (None, "", []):
                prev[k] = v

    if critical:
        return {
            "ok": False,
            "critical": critical,
            "warnings": warnings,
            "mesh": None,
            "written": None,
            "fragment_count": len(fragments),
        }

    atlases = []
    for eid, ent in sorted(by_id.items()):
        clean = {k: v for k, v in ent.items() if not k.startswith("_")}
        atlases.append(clean)

    mesh = {
        "schema_version": "1.0",
        "atlases": atlases,
        "consolidated_from": [
            str(p.relative_to(root)).replace("\\", "/") for p in fragments
        ],
    }

    out = root / "mesh.json"
    out.write_text(json.dumps(mesh, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "critical": [],
        "warnings": warnings,
        "mesh": mesh,
        "written": "mesh.json",
        "fragment_count": len(fragments),
        "atlas_count": len(atlases),
    }
