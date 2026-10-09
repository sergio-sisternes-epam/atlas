"""Project-root atlas-mesh.json — catalogue only, no tokens."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
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
LOCK_NAME = f"{MESH_NAME}.lock"
# Mesh writes take milliseconds: a lock this old is abandoned, and a writer
# gives up (exit 2) rather than wait longer than MESH_LOCK_WAIT_SECONDS.
MESH_LOCK_STALE_SECONDS = 60.0
MESH_LOCK_WAIT_SECONDS = 10.0
MESH_LOCK_POLL_SECONDS = 0.05


class MeshFileError(ValueError):
    pass


class MeshLockTimeout(MeshFileError):
    """Another writer held ``atlas-mesh.json.lock`` for longer than the wait budget."""


@contextmanager
def mesh_lock(project: Path) -> Iterator[Any]:
    """Serialise every mesh mutation on ``<project>/atlas-mesh.json.lock`` (owner-token lock).

    Waits up to :data:`MESH_LOCK_WAIT_SECONDS`, taking over a stale lock
    (older than :data:`MESH_LOCK_STALE_SECONDS` or a dead pid on this host);
    raises :class:`MeshLockTimeout` otherwise. Nothing is written without it.
    """
    from .ignore_guard import ensure_mesh_lock_ignored
    from .owned_lock import OwnedLock

    lock = OwnedLock(project, LOCK_NAME, MESH_LOCK_STALE_SECONDS)
    deadline = time.monotonic() + MESH_LOCK_WAIT_SECONDS
    while True:
        try:
            got = lock.try_acquire()
        except OSError as e:
            raise MeshFileError(f"cannot take {lock.path}: {e.strerror or e}; not modified") from e
        if got:
            break
        if time.monotonic() >= deadline:
            raise MeshLockTimeout(
                f"{lock.path} is held by another atlas process (waited {MESH_LOCK_WAIT_SECONDS:g}s); "
                "retry, or remove the lock file if no atlas command is running; not modified"
            )
        time.sleep(MESH_LOCK_POLL_SECONDS)
    try:
        ensure_mesh_lock_ignored(project)
        yield lock
    finally:
        lock.release()


class MeshLockLost(MeshFileError):
    """The mesh lock was taken over (it went stale) before this writer replaced the file."""


def _write_locked(lock: Any, fp: Path, doc: Any, indent: str | int = 2, trailing_newline: bool = True) -> None:
    """Re-check ownership and replace ``fp`` under the lock's takeover guard.

    The guard is held from the check to the ``os.replace``, so a writer whose
    stale lock was taken over can never overwrite the new holder's change.
    """
    lost = lambda _msg: MeshLockLost(  # noqa: E731
        f"{lock.path} was taken over by another writer (lock_lost); {fp} not modified"
    )
    with lock.owned_critical_section(lost=lost):
        write_json_atomic(fp, doc, indent=indent, trailing_newline=trailing_newline)


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
    errs.extend(duplicate_id_errors(data))
    return errs


def _id_key(sid: str) -> str:
    try:
        canon = normalise(sid)
    except IdentityError:
        canon = sid
    return canon.lower()


def duplicate_id_errors(data: Any) -> list[str]:
    """Store ids must be unique after normalisation, ignoring case (``--store`` matching ignores case)."""
    stores = data.get("stores") if isinstance(data, dict) else None
    seen: dict[str, tuple[int, str]] = {}
    errs: list[str] = []
    for i, row in enumerate(stores if isinstance(stores, list) else []):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip():
            continue
        sid = row["id"].strip()
        key = _id_key(sid)
        path = row.get("path")
        if key in seen:
            first, first_path = seen[key]
            try:
                shown = normalise(sid)
            except IdentityError:
                shown = sid
            errs.append(
                f"duplicate store id {shown}: stores[{first}] (path {first_path}) and stores[{i}] (path {path})"
            )
        else:
            seen[key] = (i, str(path))
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
    """Add or replace a store row (keeping its ``recall`` block) under the mesh lock."""
    with mesh_lock(project) as lock:
        return _upsert_locked(lock, project, row)


def _upsert_locked(lock: Any, project: Path, row: dict[str, str]) -> Path:
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
    _write_locked(lock, fp, doc, indent=2)
    return fp


DEFAULT_TARGET = "default"


@dataclass(frozen=True)
class RecallWrite:
    path: Path
    target: str
    previous: str | None
    value: str | None
    changed: bool


def detect_indent(text: str) -> str | int:
    """Indentation of an existing JSON file: a tab, or the width of the first indented line (default 2)."""
    for line in text.splitlines()[1:]:
        stripped = line.lstrip(" \t")
        if not stripped or len(stripped) == len(line):
            continue
        lead = line[: len(line) - len(stripped)]
        if lead.startswith("\t"):
            return "\t"
        return len(lead)
    return 2


def _current_umask() -> int:
    """The process umask without changing it (``os.umask`` would race other threads)."""
    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if line.startswith("Umask:"):
                return int(line.split()[1], 8)
    except (OSError, ValueError, IndexError):
        pass
    return 0o022


def write_json_atomic(fp: Path, doc: Any, indent: str | int = 2, trailing_newline: bool = True) -> None:
    """Temp file in the same directory, flush + fsync, then ``os.replace``; no temp file survives."""
    text = json.dumps(doc, indent=indent, ensure_ascii=False) + ("\n" if trailing_newline else "")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{fp.name}.", suffix=".tmp", dir=str(fp.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            mode = fp.stat().st_mode & 0o7777
        except OSError:
            # New file: the mode a plain open() would give, not mkstemp's 0600.
            mode = 0o666 & ~_current_umask()
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
        os.replace(tmp, fp)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    try:
        dir_fd = os.open(str(fp.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def set_recall_engine(project: Path, target: str | None, value: str | None) -> RecallWrite:
    """Set (or clear, with ``value=None``) ``recall.engine`` on a store row or the project default.

    ``target`` is a canonical store id, or ``None`` / :data:`DEFAULT_TARGET`
    for the top-level (project-wide) default. Only the target's ``recall`` key
    changes: key order, row order, unknown keys, indentation and the trailing
    newline are preserved. Unchanged values do not touch the file. A file that
    is not valid JSON, or a result that fails validation, raises
    :class:`MeshFileError` and nothing is written. The file is re-read and
    written under the mesh lock (:func:`mesh_lock`), so concurrent writers
    never lose each other's changes.
    """
    fp = mesh_path(project)
    if not fp.is_file():
        raise MeshFileError(f"{fp} not found")
    if value is not None and value not in RECALL_ENGINES:
        raise MeshFileError(f"engine {value!r} is not allowed; allowed values: {', '.join(RECALL_ENGINES)}")
    with mesh_lock(project) as lock:
        return _set_recall_engine_locked(lock, fp, target, value)


def _set_recall_engine_locked(lock: Any, fp: Path, target: str | None, value: str | None) -> RecallWrite:
    if not fp.is_file():
        raise MeshFileError(f"{fp} not found")
    raw = fp.read_text(encoding="utf-8")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise MeshFileError(f"invalid JSON in {fp}: {e}; not modified") from e
    if not isinstance(doc, dict) or not isinstance(doc.get("stores"), list):
        errs = validate_doc(doc, source=str(fp))
        raise MeshFileError("; ".join(errs or [f"{fp}: mesh root must be an object with stores"]) + "; not modified")
    label = DEFAULT_TARGET if target in (None, DEFAULT_TARGET) else str(target)
    if label == DEFAULT_TARGET:
        obj = doc
    else:
        obj = next((s for s in doc["stores"] if isinstance(s, dict) and s.get("id") == label), None)
        if obj is None:
            raise MeshFileError(f"{fp}: no store row with id {label}")
    block = obj.get("recall")
    previous = block.get("engine") if isinstance(block, dict) else None
    if isinstance(block, dict):
        new_block: dict[str, Any] | None = dict(block)
    else:
        new_block = {}
    if value is None:
        new_block.pop("engine", None)
    else:
        new_block["engine"] = value
    if not new_block:
        new_block = None
    current = block if "recall" in obj else None
    if new_block == current:
        return RecallWrite(fp, label, previous, value, False)
    if new_block is None:
        obj.pop("recall", None)
    else:
        obj["recall"] = new_block
    # A broken recall block on the target is repairable here; any other error refuses the write.
    errs = validate_doc(doc, source=str(fp))
    if errs:
        raise MeshFileError("; ".join(errs) + "; not modified")
    _write_locked(lock, fp, doc, indent=detect_indent(raw), trailing_newline=raw.endswith("\n"))
    return RecallWrite(fp, label, previous, value, True)


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
    """Drop a store row under the mesh lock (re-read, validate, atomic write)."""
    with mesh_lock(project) as lock:
        doc = load(project)
        doc["stores"] = [s for s in doc.get("stores") or [] if s.get("id") != atlas_id]
        errs = validate_doc(doc)
        if errs:
            raise MeshFileError("; ".join(errs))
        fp = mesh_path(project)
        _write_locked(lock, fp, doc, indent=2)
        return fp
