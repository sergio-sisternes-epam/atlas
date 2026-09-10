"""Project-root atlas-mesh.json — catalogue only, no tokens."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .identity import IdentityError, normalise

MESH_NAME = "atlas-mesh.json"
FORBIDDEN = frozenset({"token", "pat", "password", "secret", "credential"})
SCHEMA_FILE = Path(__file__).resolve().parents[1] / "schemas" / "atlas-mesh.schema.json"
STRATEGIES = frozenset({"shared", "dedicated"})
DEFAULT_STRATEGY = "dedicated"
SHARED_REF = "atlas"


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
    errs = validate_doc(data)
    if errs:
        raise MeshFileError("; ".join(errs))
    return data


def validate_doc(data: Any) -> list[str]:
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
                errs.append(err.message)
        except Exception as e:
            errs.append(f"schema engine: {e}")
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


def upsert(project: Path, row: dict[str, str]) -> Path:
    doc = load(project)
    sid = row["id"]
    stores = [s for s in doc["stores"] if s.get("id") != sid]
    clean = {k: v for k, v in row.items() if v}
    stores.append(clean)
    doc["stores"] = stores
    errs = validate_doc(doc)
    if errs:
        raise MeshFileError("; ".join(errs))
    fp = mesh_path(project)
    fp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
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
