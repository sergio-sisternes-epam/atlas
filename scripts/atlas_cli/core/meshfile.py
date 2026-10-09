"""Project-root atlas-mesh.json — catalogue only, no tokens."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .identity import IdentityError, normalise

MESH_NAME = "atlas-mesh.json"
FORBIDDEN = frozenset({"token", "pat", "password", "secret", "credential"})
SCHEMA_FILE = Path(__file__).resolve().parents[1] / "schemas" / "atlas-mesh.schema.json"
STRATEGIES = frozenset({"shared", "dedicated"})
DEFAULT_STRATEGY = "dedicated"
SHARED_REF = "atlas"
RECALL_ENGINES = ("grep", "bm25", "nanograph")
RECALL_KEYS = frozenset({"engine"})


class MeshFileError(ValueError):
    pass


def find_project_root(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    for d in [cur, *cur.parents]:
        if (d / ".git").exists() or (d / MESH_NAME).exists():
            return d
    return cur


def mesh_path(project: Path) -> Path:
    return project / MESH_NAME


def load(project: Path) -> dict[str, Any]:
    fp = mesh_path(project)
    if not fp.is_file():
        return {"version": 1, "stores": []}
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise MeshFileError(f"invalid JSON in {fp}: {e}") from e
    errs = validate_doc(data, source=str(fp))
    if errs:
        raise MeshFileError("; ".join(errs))
    return data


def load_for_location(project: Path) -> dict[str, Any]:
    """Like :func:`load`, but a bad ``recall`` block does not hide the store rows.

    Index location must not move because a recall preference is invalid; the
    recall preference resolver reports that error on its own (see
    core/engine_preference.py).
    """
    fp = mesh_path(project)
    try:
        return load(project)
    except MeshFileError:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise
        if not isinstance(data, dict) or not recall_errors(data, str(fp)):
            raise
        if validate_doc(strip_recall(data)):
            raise
        return data


def strip_recall(data: dict[str, Any]) -> dict[str, Any]:
    """A copy of a mesh document without any ``recall`` blocks."""
    out = {k: v for k, v in data.items() if k != "recall"}
    stores = data.get("stores")
    if isinstance(stores, list):
        out["stores"] = [
            {k: v for k, v in row.items() if k != "recall"} if isinstance(row, dict) else row
            for row in stores
        ]
    return out


def recall_block_errors(block: Any, where: str) -> list[str]:
    allowed = ", ".join(RECALL_ENGINES)
    if not isinstance(block, dict):
        return [f"{where}: recall must be an object like {{\"engine\": \"bm25\"}}; allowed engine values: {allowed}"]
    errs: list[str] = []
    for key in sorted(k for k in block if k not in RECALL_KEYS):
        errs.append(f"{where}: unknown key {key!r} in recall; allowed keys: {', '.join(sorted(RECALL_KEYS))}")
    if "engine" in block and block["engine"] not in RECALL_ENGINES:
        errs.append(f"{where}: recall.engine {block['engine']!r} is not allowed; allowed values: {allowed}")
    return errs


def recall_errors(data: Any, source: str | None = None) -> list[str]:
    """Clear messages for invalid ``recall`` blocks (top level and store rows)."""
    if not isinstance(data, dict):
        return []
    label = source or MESH_NAME
    errs: list[str] = []
    if "recall" in data:
        errs += recall_block_errors(data["recall"], f"{label}: project default")
    stores = data.get("stores")
    for i, row in enumerate(stores if isinstance(stores, list) else []):
        if isinstance(row, dict) and "recall" in row:
            sid = str(row.get("id") or f"stores[{i}]")
            errs += recall_block_errors(row["recall"], f"{label}: store {sid}")
    return errs


def _in_recall(path: Any) -> bool:
    parts = list(path)
    return (parts[:1] == ["recall"]) or (len(parts) >= 3 and parts[0] == "stores" and parts[2] == "recall")


def validate_doc(data: Any, source: str | None = None) -> list[str]:
    errs: list[str] = []
    try:
        import jsonschema
    except ImportError:
        errs.append("jsonschema package missing — install from scripts/requirements.txt")
        jsonschema = None  # type: ignore
    if jsonschema is not None:
        try:
            schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
            validator = jsonschema.Draft202012Validator(schema)
            for err in validator.iter_errors(data):
                if _in_recall(err.absolute_path):
                    continue
                errs.append(err.message)
        except Exception as e:
            errs.append(f"schema engine: {e}")
    errs.extend(recall_errors(data, source))
    if not isinstance(data, dict):
        return errs or ["mesh root must be an object"]
    if data.get("version") != 1:
        errs.append("version must be 1")
    stores = data.get("stores")
    if not isinstance(stores, list):
        errs.append("stores must be a list")
        return errs
    for i, row in enumerate(stores):
        if not isinstance(row, dict):
            errs.append(f"stores[{i}] must be an object")
            continue
        for bad in FORBIDDEN:
            if bad in row:
                errs.append(f"stores[{i}] forbids field '{bad}'")
        sid = str(row.get("id") or "").strip()
        if not sid:
            errs.append(f"stores[{i}] missing id")
            continue
        try:
            if normalise(sid) != sid:
                errs.append(f"stores[{i}] id is not canonical: {sid}")
        except IdentityError:
            errs.append(f"stores[{i}] id is not host/org/repo: {sid}")
        errs.extend(strategy_errors(row, i))
    return errs


def effective_strategy(row: dict[str, Any] | None) -> str:
    """Missing strategy is dedicated. Do not infer from id+ref."""
    raw = (row or {}).get("strategy")
    if raw in (None, ""):
        return DEFAULT_STRATEGY
    return str(raw)


def strategy_errors(row: dict[str, Any], index: int | str = "") -> list[str]:
    prefix = f"stores[{index}] " if index != "" else ""
    raw = row.get("strategy")
    if raw in (None, ""):
        return []
    if raw not in STRATEGIES:
        return [f"{prefix}strategy must be shared or dedicated"]
    ref = str(row.get("ref") or "").strip()
    if raw == "shared" and ref != SHARED_REF:
        if not ref:
            return [f"{prefix}strategy shared requires ref {SHARED_REF}"]
        return [f"{prefix}strategy shared requires ref {SHARED_REF}, have {ref}"]
    return []


def _write_atomic(fp: Path, doc: dict[str, Any]) -> None:
    tmp = fp.with_name(f".{fp.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, fp)


def upsert(project: Path, row: dict[str, str]) -> Path:
    doc = load(project)
    sid = row["id"]
    previous = next((s for s in doc["stores"] if s.get("id") == sid), None)
    stores = [s for s in doc["stores"] if s.get("id") != sid]
    clean = {k: v for k, v in row.items() if v}
    if previous and "recall" in previous and "recall" not in clean:
        clean["recall"] = previous["recall"]
    stores.append(clean)
    doc["stores"] = stores
    errs = validate_doc(doc)
    if errs:
        raise MeshFileError("; ".join(errs))
    fp = mesh_path(project)
    fp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return fp


def set_recall_engine(project: Path, store_id: str | None, engine: str | None) -> Path:
    """Set (or clear, with ``engine=None``) a store row's or the project's ``recall.engine``.

    ``store_id=None`` targets the project-wide default. Validates the whole
    document before an atomic replace; never writes an invalid file.
    """
    fp = mesh_path(project)
    if not fp.is_file():
        raise MeshFileError(f"{fp} not found")
    doc = load(project)
    if store_id is None:
        target = doc
    else:
        target = next((s for s in doc.get("stores") or [] if s.get("id") == store_id), None)
        if target is None:
            raise MeshFileError(f"{fp}: no store row with id {store_id}")
    block = dict(target.get("recall") or {})
    if engine is None:
        block.pop("engine", None)
    else:
        block["engine"] = engine
    if block:
        target["recall"] = block
    else:
        target.pop("recall", None)
    errs = validate_doc(doc, source=str(fp))
    if errs:
        raise MeshFileError("; ".join(errs))
    _write_atomic(fp, doc)
    return fp


def find_store(project: Path, atlas_id: str) -> dict | None:
    doc = load(project)
    for row in doc.get("stores") or []:
        if row.get("id") == atlas_id:
            return row
    return None


def known_ids(project: Path) -> set[str]:
    doc = load(project)
    return {str(s.get("id")) for s in doc.get("stores") or [] if s.get("id")}


def remove_store(project: Path, atlas_id: str) -> Path:
    doc = load(project)
    doc["stores"] = [s for s in doc.get("stores") or [] if s.get("id") != atlas_id]
    errs = validate_doc(doc)
    if errs:
        raise MeshFileError("; ".join(errs))
    fp = mesh_path(project)
    fp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return fp
