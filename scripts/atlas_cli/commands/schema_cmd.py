from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from pathlib import Path

from ..core.overlay import (
    RESERVED_CORE_TYPES,
    SCHEMA_D,
    added_types,
    list_overlays,
    load_overlay,
    load_receipt,
    merge_overlays,
    normalize_rel_path,
    overlay_by_type,
    overlay_path,
    receipt_path,
    receipt_issues,
    required_fingerprint,
    validate_id,
    validate_type_name,
    write_json,
    write_receipt,
)
from ..core.paths import rel, store_root
from ..core.schema import (
    load_contract,
    load_schema,
    staging_dir_name,
    validate_against_contract,
    validate_schema_shape,
)


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
    if source.is_symlink():
        return None, None, f"symlink source is not allowed: {source}"
    if source.is_file():
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as e:
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
        if contrib.is_dir() and not contrib.is_symlink():
            subs = [p for p in contrib.iterdir() if p.is_dir()]
            if len(subs) == 1:
                return _source_overlay(subs[0])
        return None, None, f"no SCHEMA.overlay.json under {source}"
    return None, None, f"source not found: {source}"


def _safe_path(root: Path, relative: str) -> Path:
    if root.is_symlink():
        raise ValueError(f"symlink root is not allowed: {root}")
    normalized = normalize_rel_path(relative)
    if normalized is None or normalized != relative:
        raise ValueError(f"unsafe relative path: {relative!r}")
    path = root
    parts = Path(relative).parts
    for index, part in enumerate(parts):
        path = path / part
        if path.is_symlink():
            raise ValueError(f"symlink path is not allowed: {path}")
        if index < len(parts) - 1 and path.exists() and not path.is_dir():
            raise ValueError(f"path parent is not a directory: {path}")
    path.resolve().relative_to(root.resolve())
    if path.exists() and not path.is_file():
        raise ValueError(f"destination is not a regular file: {path}")
    return path


def _template_paths(overlay: dict) -> dict[str, str]:
    by_type, error = overlay_by_type(overlay)
    if error:
        raise ValueError(error)
    paths: dict[str, str] = {}
    for name, block in (by_type or {}).items():
        if validate_type_name(name) or not isinstance(block, dict):
            raise ValueError(f"invalid template type: {name}")
        path = block.get("file", f"templates/{name}.md")
        if (
            not isinstance(path, str)
            or normalize_rel_path(path) != path
            or not path.startswith("templates/")
            or not path.endswith(".md")
        ):
            raise ValueError(f"template for {name} must be a safe templates/*.md path")
        if _path_conflict(path, paths.values()):
            raise ValueError(f"template path collision: {path}")
        paths[name] = path
    return paths


def _path_conflict(path: str, others) -> bool:
    # Case aliases must not become two owners on case-insensitive filesystems.
    key = path.casefold()
    return any(
        key == other.casefold()
        or key.startswith(other.casefold() + "/")
        or other.casefold().startswith(key + "/")
        for other in others
    )


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(data: dict) -> bytes:
    return (json.dumps(data, indent=2) + "\n").encode("utf-8")


def _atomic_write(path: Path, data: bytes, mode: int | None = None) -> None:
    sibling = path.with_name(f".{path.name}.{uuid.uuid4().hex}.atlas-write")
    fd = os.open(sibling, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            if mode is not None:
                os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(sibling, path)
    finally:
        sibling.unlink(missing_ok=True)


def _apply_changes(root: Path, changes: dict[str, bytes | None]) -> None:
    """Atomic per-file writes; no cross-file isolation, locking, or crash-recovery journal.

    OS failures trigger best-effort rollback. Concurrent writers and process/power
    loss can still leave mixed versions; rollback failures are reported explicitly.
    """
    before: dict[str, tuple[bytes | None, int | None]] = {}
    for relative in changes:
        if _path_conflict(relative, before):
            raise ValueError(f"planned file path collision: {relative}")
        path = _safe_path(root, relative)
        before[relative] = (
            (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            if path.exists() else (None, None)
        )
    applied: list[str] = []
    created_dirs: list[Path] = []
    try:
        for relative, data in changes.items():
            path = _safe_path(root, relative)
            previous, mode = before[relative]
            if (path.read_bytes() if path.exists() else None) != previous:
                raise OSError(f"file changed during install: {relative}")
            if data == previous:
                continue
            missing: list[Path] = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir()
                created_dirs.append(directory)
            if data is None:
                path.unlink()
            else:
                _atomic_write(path, data, mode)
            applied.append(relative)
    except (OSError, ValueError) as error:
        failures: list[str] = []
        for relative in reversed(applied):
            try:
                path = _safe_path(root, relative)
                if (path.read_bytes() if path.exists() else None) != changes[relative]:
                    raise OSError("file changed again; refusing to overwrite")
                previous, mode = before[relative]
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    _atomic_write(path, previous, mode)
            except (OSError, ValueError) as rollback_error:
                failures.append(f"{relative}: {rollback_error}")
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError as rollback_error:
                failures.append(f"{directory}: {rollback_error}")
        suffix = f"; rollback incomplete: {'; '.join(failures)}" if failures else "; changes rolled back"
        raise OSError(f"{error}{suffix}") from error


def _candidate_schema(root: Path, cid: str, overlay: dict) -> tuple[dict, dict[str, dict]]:
    core, error = load_schema(root)
    if error or core is None:
        raise ValueError(error or "missing core schema")
    errors = validate_schema_shape(core) + validate_against_contract(core, load_contract())
    if errors:
        raise ValueError("; ".join(errors))
    effective, issues, _ = merge_overlays(core, root, candidate_overlays={cid: overlay})
    errors = [i["msg"] for i in issues]
    errors.extend(validate_schema_shape(effective))
    errors.extend(validate_against_contract(effective, load_contract()))
    if errors:
        raise ValueError("; ".join(errors))
    installed = {cid: overlay}
    for other_id in list_overlays(root):
        _safe_path(root, f"{SCHEMA_D}/{other_id}.json")
        _safe_path(root, f"{SCHEMA_D}/{other_id}.receipt.json")
        if other_id != cid:
            other, error = load_overlay(root, other_id)
            if error or other is None:
                raise ValueError(error or f"invalid overlay {other_id}")
            installed[other_id] = other
    owners = {path: "core" for path in _template_paths(core).values()}
    owners.update({f"templates/{name}.md": "core" for name in RESERVED_CORE_TYPES})
    for owner, candidate in installed.items():
        for path in _template_paths(candidate).values():
            _safe_path(root, path)
            if _path_conflict(path, owners):
                raise ValueError(f"template path collision: {path} (contribution {owner})")
            owners[path] = owner
    return core, installed


def _install_plan(root: Path, cid: str, overlay: dict, source_dir: Path, force: bool) -> tuple[dict, dict]:
    dest = _safe_path(root, f"{SCHEMA_D}/{cid}.json")
    rec_path = _safe_path(root, f"{SCHEMA_D}/{cid}.receipt.json")
    core, installed = _candidate_schema(root, cid, overlay)
    existing: dict = {}
    if dest.exists():
        existing, error = load_overlay(root, cid)
        if existing is None:
            if not force:
                raise ValueError(f"existing overlay unreadable; pass --force to replace ({error})")
            existing = {}
        if not force and required_fingerprint(existing) != required_fingerprint(overlay):
            raise ValueError("overlay required keys changed; pass --force to replace")
    receipt: dict = {}
    if rec_path.exists():
        receipt, error = load_receipt(root, cid)
        if receipt is None:
            raise ValueError(f"receipt unreadable; refusing to discard ownership: {error}")
    errors = receipt_issues(
        root, candidate_overlays={cid: existing or overlay}, candidate_receipts={cid: receipt}
    )
    if errors:
        raise ValueError("; ".join(f"{i['path']}: {i['msg']}" for i in errors))
    old_hashes = dict(receipt.get("template_hashes", {}))
    hashes = dict(old_hashes)
    written = set(receipt.get("written", []))
    paths = _template_paths(overlay)
    protected = set(_template_paths(core).values())
    protected.update(f"templates/{name}.md" for name in RESERVED_CORE_TYPES)
    for owner, candidate in installed.items():
        if owner != cid:
            protected.update(_template_paths(candidate).values())
            other_receipt, _ = load_receipt(root, owner)
            if other_receipt:
                protected.update(other_receipt.get("template_hashes", {}))
                protected.update(
                    p for p in other_receipt.get("written", []) if p.startswith("templates/")
                )
    for path, digest in old_hashes.items():
        if _path_conflict(path, protected):
            raise ValueError(f"receipt cannot own template: {path}")
        target = _safe_path(root, path)
        if target.exists() and _digest(target.read_bytes()) != digest:
            raise ValueError(f"user-edited template; refusing overwrite even with --force: {path}")
    template_root = source_dir
    if (
        not (source_dir / "templates").exists()
        and not (source_dir / "templates").is_symlink()
        and source_dir.name != "templates"
    ):
        template_root = source_dir.parent
    changes: dict[str, bytes | None] = {}
    copied: list[str] = []
    updated: list[str] = []
    notes: list[str] = []
    for name, path in paths.items():
        if _path_conflict(path, protected):
            raise ValueError(f"template path collision: {path}")
        target = _safe_path(root, path)
        source = _safe_path(template_root, path)
        if not source.exists():
            continue
        content = source.read_bytes()
        current = target.read_bytes() if target.exists() else None
        if current is not None and path not in old_hashes:
            if current != content:
                raise ValueError(f"unowned template; refusing overwrite even with --force: {path}")
            notes.append(f"unchanged unowned template preserved without acquiring ownership: {path}")
            continue
        hashes[path] = _digest(content)
        written.add(path)
        if current != content:
            changes[path] = content
            (copied if current is None else updated).append(name)
    overlay_rel = f"{SCHEMA_D}/{cid}.json"
    receipt_rel = f"{SCHEMA_D}/{cid}.receipt.json"
    written.update((overlay_rel, receipt_rel))
    new_receipt = {
        **receipt,
        "id": cid,
        "written": sorted(written),
        "added_types": sorted(set(receipt.get("added_types", [])) | set(added_types(existing)) | set(paths)),
        "template_hashes": hashes,
    }
    errors = receipt_issues(
        root, candidate_overlays={cid: overlay}, candidate_receipts={cid: new_receipt}
    )
    if errors:
        raise ValueError("; ".join(f"{i['path']}: {i['msg']}" for i in errors))
    claimed_paths = {
        "": set(_template_paths(core).values())
        | {f"templates/{name}.md" for name in RESERVED_CORE_TYPES}
    }
    for owner in installed:
        owner_receipt = new_receipt if owner == cid else load_receipt(root, owner)[0]
        own_paths = set(_template_paths(installed[owner]).values())
        for path in (owner_receipt or {}).get("written", []):
            _safe_path(root, path)
            if path.startswith("templates/"):
                own_paths.add(path)
        for path in own_paths:
            if any(_path_conflict(path, others) for others in claimed_paths.values()):
                raise ValueError(f"receipt/template ownership collision: {path} ({owner})")
        claimed_paths[owner] = own_paths
    changes[overlay_rel] = _json_bytes(overlay)
    changes[receipt_rel] = _json_bytes(new_receipt)
    return changes, {"templates_copied": copied, "templates_updated": updated, "notes": notes}


def run_install(
    source: str,
    root: str | None,
    force: bool = False,
    as_json: bool = False,
) -> int:
    r = store_root(root)
    cid = ""
    try:
        src = Path(source).expanduser().absolute()
        ov, src_dir, err = _source_overlay(src)
        if err or ov is None or src_dir is None:
            raise ValueError(err or "bad overlay")
        cid = str(ov.get("contribution_id") or "").strip()
        id_err = validate_id(cid)
        if id_err:
            raise ValueError(id_err)
        changes, details = _install_plan(r, cid, ov, src_dir, force)
        _apply_changes(r, changes)
    except (OSError, ValueError) as error:
        _print(as_json, {"ok": False, "error": str(error), "root": str(r), "id": cid})
        return 2
    _print(
        as_json,
        {
            "ok": True,
            "root": str(r),
            "id": cid,
            "overlay": rel(r, overlay_path(r, cid)),
            "receipt": rel(r, receipt_path(r, cid)),
            **details,
        },
    )
    return 0


def run_uninstall(cid: str, root: str | None, as_json: bool = False) -> int:
    try:
        return _run_uninstall(cid, root, as_json)
    except (OSError, ValueError) as error:
        _print(as_json, {"ok": False, "error": str(error), "root": str(store_root(root)), "id": cid})
        return 2


def _run_uninstall(cid: str, root: str | None, as_json: bool) -> int:
    r = store_root(root)
    err = validate_id(cid)
    if err:
        _print(as_json, {"ok": False, "error": err, "root": str(r)})
        return 2
    dest = _safe_path(r, f"{SCHEMA_D}/{cid}.json")
    _safe_path(r, f"{SCHEMA_D}/{cid}.receipt.json")
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
    errors = receipt_issues(r, candidate_receipts={cid: rec})
    if errors:
        raise ValueError("; ".join(f"{i['path']}: {i['msg']}" for i in errors))
    written = [str(x) for x in (rec.get("written") or [])]
    ov, _ = load_overlay(r, cid)
    gone_types = set(added_types(ov) if ov else [])
    for x in rec.get("added_types") or []:
        if isinstance(x, (dict, list)):
            continue
        s = str(x).strip()
        if s:
            gone_types.add(s)
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

    core, error = load_schema(r)
    if core is None:
        raise ValueError(error or "core schema unavailable; cannot identify protected templates")
    protected = set(_template_paths(core).values())
    protected.update(f"templates/{name}.md" for name in RESERVED_CORE_TYPES)
    for other in list_overlays(r):
        if other == cid:
            continue
        other_overlay, error = load_overlay(r, other)
        if other_overlay is None:
            raise ValueError(error or f"unreadable overlay {other}")
        protected.update(_template_paths(other_overlay).values())
        other_receipt, _ = load_receipt(r, other)
        protected.update(
            p for p in (other_receipt or {}).get("written", []) if p.startswith("templates/")
        )
    changes: dict[str, bytes | None] = {}
    hashes = rec.get("template_hashes", {})
    for wp in written:
        if not wp.startswith("templates/"):
            continue
        try:
            path = _safe_path(r, wp)
        except ValueError:
            notes.append(f"preserved unsafe template path: {wp}")
            continue
        if not path.exists():
            continue
        if _path_conflict(wp, protected):
            notes.append(f"preserved template belonging to core or another contribution: {wp}")
        elif wp not in hashes:
            notes.append(f"preserved unhashed template (no overwrite/delete authority): {wp}")
        elif _digest(path.read_bytes()) != hashes[wp]:
            notes.append(f"preserved user-edited template: {wp}")
        else:
            changes[wp] = None
    changes[f"{SCHEMA_D}/{cid}.json"] = None
    if receipt_path(r, cid).exists():
        changes[f"{SCHEMA_D}/{cid}.receipt.json"] = None
    _apply_changes(r, changes)
    deleted = list(changes)
    payload = {"ok": True, "root": str(r), "id": cid, "deleted": deleted, "notes": notes}
    if notes:
        payload["warning"] = "uninstall preserved files or found orphan overlay pages"
    _print(as_json, payload)
    return 0
