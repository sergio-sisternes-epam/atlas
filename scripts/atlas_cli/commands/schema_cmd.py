from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..core.overlay import (
    SCHEMA_D,
    added_types,
    load_overlay,
    load_receipt,
    overlay_by_type,
    overlay_path,
    receipt_path,
    required_fingerprint,
    resolve_under_root,
    validate_id,
    validate_type_name,
    write_json,
    write_receipt,
)
from ..core.paths import rel, store_root
from ..core.schema import load_schema, staging_dir_name


def _print(as_json: bool, payload: dict) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        ok = payload.get("ok")
        print(f"atlas schema — {'ok' if ok else 'FAIL'}")
        if payload.get("error"):
            print(payload["error"])
        for line in payload.get("notes") or []:
            print(line)


def run_new(
    cid: str,
    root: str | None,
    claims: tuple[str, ...] | list[str] | None = None,
    as_json: bool = False,
) -> int:
    err = validate_id(cid)
    r = store_root(root)
    if err:
        _print(as_json, {"ok": False, "error": err, "root": str(r)})
        return 2
    dest = overlay_path(r, cid)
    if dest.is_file():
        _print(as_json, {"ok": False, "error": f"{SCHEMA_D}/{cid}.json already exists", "root": str(r)})
        return 2
    claimed = [c.strip().strip("/") for c in (claims or []) if str(c).strip()]
    overlay = {"contribution_id": cid, "claimed_folders": claimed, "templates": {"by_type": {}}}
    write_json(dest, overlay)
    written = [f"{SCHEMA_D}/{cid}.json"]
    rec = write_receipt(r, cid, written + [f"{SCHEMA_D}/{cid}.receipt.json"], types=[])
    _print(
        as_json,
        {
            "ok": True,
            "root": str(r),
            "id": cid,
            "overlay": rel(r, dest),
            "receipt": rel(r, rec),
            "claimed_folders": claimed,
        },
    )
    return 0


def _source_overlay(source: Path) -> tuple[dict | None, Path | None, str | None]:
    if source.is_file():
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return None, None, f"cannot read overlay: {e}"
        if not isinstance(data, dict):
            return None, None, "overlay must be a JSON object"
        return data, source.parent, None
    if source.is_dir():
        for name in ("SCHEMA.overlay.json", "overlay.json"):
            cand = source / name
            if cand.is_file():
                return _source_overlay(cand)
        contrib = source / "contributions"
        if contrib.is_dir():
            subs = [p for p in contrib.iterdir() if p.is_dir()]
            if len(subs) == 1:
                return _source_overlay(subs[0])
        return None, None, f"no SCHEMA.overlay.json under {source}"
    return None, None, f"source not found: {source}"


def run_install(
    source: str,
    root: str | None,
    force: bool = False,
    as_json: bool = False,
) -> int:
    r = store_root(root)
    src = Path(source).expanduser().resolve()
    ov, src_dir, err = _source_overlay(src)
    if err or ov is None:
        _print(as_json, {"ok": False, "error": err or "bad overlay", "root": str(r)})
        return 2
    cid = str(ov.get("contribution_id") or "").strip()
    id_err = validate_id(cid)
    if id_err:
        _print(as_json, {"ok": False, "error": id_err, "root": str(r)})
        return 2
    dest = overlay_path(r, cid)
    _, by_err = overlay_by_type(ov)
    if by_err:
        _print(as_json, {"ok": False, "error": by_err, "root": str(r), "id": cid})
        return 2
    for tname in added_types(ov):
        t_err = validate_type_name(tname)
        if t_err:
            _print(as_json, {"ok": False, "error": t_err, "root": str(r), "id": cid})
            return 2
    if dest.is_file() and not force:
        existing, ex_err = load_overlay(r, cid)
        if existing is None:
            _print(
                as_json,
                {
                    "ok": False,
                    "error": f"existing overlay unreadable; pass --force to replace ({ex_err})",
                    "root": str(r),
                    "id": cid,
                },
            )
            return 2
        if required_fingerprint(existing) != required_fingerprint(ov):
            _print(
                as_json,
                {
                    "ok": False,
                    "error": "overlay required keys changed; pass --force to replace",
                    "root": str(r),
                    "id": cid,
                },
            )
            return 2
    write_json(dest, ov)
    written = [f"{SCHEMA_D}/{cid}.json"]
    # Copy templates for types this overlay adds (not core types).
    copied: list[str] = []
    if src_dir is not None:
        tmpl_src = src_dir / "templates"
        if not tmpl_src.is_dir() and src_dir.name != "templates":
            tmpl_src = src_dir.parent / "templates"
        add = added_types(ov)
        if tmpl_src.is_dir():
            tmpl_dst = r / "templates"
            tmpl_dst.mkdir(exist_ok=True)
            for tname in add:
                src_f = tmpl_src / f"{tname}.md"
                dest_f = tmpl_dst / f"{tname}.md"
                if src_f.is_file() and not dest_f.exists():
                    shutil.copy2(src_f, dest_f)
                    written.append(f"templates/{tname}.md")
                    copied.append(tname)
    rec = write_receipt(r, cid, written + [f"{SCHEMA_D}/{cid}.receipt.json"], types=added_types(ov))
    _print(
        as_json,
        {
            "ok": True,
            "root": str(r),
            "id": cid,
            "overlay": rel(r, dest),
            "receipt": rel(r, rec),
            "templates_copied": copied,
        },
    )
    return 0


def run_uninstall(cid: str, root: str | None, as_json: bool = False) -> int:
    r = store_root(root)
    err = validate_id(cid)
    if err:
        _print(as_json, {"ok": False, "error": err, "root": str(r)})
        return 2
    dest = overlay_path(r, cid)
    if not dest.is_file():
        _print(as_json, {"ok": False, "error": f"no overlay {cid}", "root": str(r)})
        return 2
    rec, rec_err = load_receipt(r, cid)
    notes: list[str] = []
    if rec_err and receipt_path(r, cid).is_file():
        _print(
            as_json,
            {
                "ok": False,
                "error": f"receipt unreadable; refusing uninstall so files are not silently left: {rec_err}",
                "root": str(r),
                "id": cid,
            },
        )
        return 2
    if rec is None:
        notes.append("warning: no receipt — overlay file will be removed; other CLI writes cannot be cleaned up")
        rec = {}
    written = [str(x) for x in (rec.get("written") or [])]
    ov, _ = load_overlay(r, cid)
    gone_types = added_types(ov) if ov else list(rec.get("added_types") or [])
    if gone_types:
        from ..core.frontmatter import read_page
        from ..core.paths import iter_concept_md

        schema, _ = load_schema(r)
        staging = staging_dir_name(schema)
        orphans: list[str] = []
        for path in iter_concept_md(r, staging):
            meta, _ = read_page(path)
            if not meta:
                continue
            t = str(meta.get("type") or "").strip()
            if t in gone_types:
                orphans.append(f"{rel(r, path)} type={t}")
        if orphans:
            notes.append("pages still use overlay types (not deleted):")
            notes.extend(f"  {o}" for o in orphans[:20])

    deleted: list[str] = []
    # Receipt writes only — never delete later authored pages.
    # Confine every path under --root; skip `..` / absolute entries.
    root_res = r.resolve()
    dest_res = dest.resolve()
    for wp in written:
        p = resolve_under_root(r, wp)
        if p is None or not p.is_file():
            continue
        if p == dest_res or p.name.endswith(".receipt.json"):
            continue
        try:
            rel_parts = p.relative_to(root_res).parts
        except ValueError:
            continue
        if rel_parts and rel_parts[0] in {SCHEMA_D, "templates"}:
            p.unlink()
            deleted.append("/".join(rel_parts))
    dest.unlink(missing_ok=True)
    deleted.append(f"{SCHEMA_D}/{cid}.json")
    rp = receipt_path(r, cid)
    if rp.is_file():
        rp.unlink()
        deleted.append(f"{SCHEMA_D}/{cid}.receipt.json")
    payload = {"ok": True, "root": str(r), "id": cid, "deleted": deleted, "notes": notes}
    if notes:
        payload["warning"] = "orphan overlay types remain on pages"
    _print(as_json, payload)
    return 0
