"""Atomic generation publish and a simple builder lock for derived indexes.

Shared by the fts5 recall index (core/recall_index.py) and the nanograph
driver (core/drivers/nanograph.py). Both keep their files under
``<project-root>/.atlas/indexes/<driver-type>/<atlas-id>/`` (the *parent*):

- A builder takes ``<parent>/.lock`` (``O_CREAT | O_EXCL``; JSON with pid,
  host and creation time). A lock older than :data:`LOCK_STALE_SECONDS` is
  treated as abandoned and broken.
- It builds into ``<parent>/.tmp-<name>``, fsyncs, then publishes with one
  ``os.replace`` of the directory and one ``os.replace`` of the pointer file.
  Readers resolve the pointer once and open that generation, so they never see
  a half-built one. Leftover ``.tmp-*`` entries are ignored by readers and
  removed by the next lock holder.
- A caller that finds the lock held polls for up to
  :data:`LOCK_WAIT_SECONDS`; if a fresh generation appears it is used,
  otherwise :class:`IndexBusy` is raised and the caller falls back (fts5:
  temporary in-memory-style index; nanograph: the built-in bm25 driver).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Callable, TypeVar

LOCK_NAME = ".lock"
LOCK_STALE_SECONDS = 600.0
LOCK_WAIT_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.1
TMP_PREFIX = ".tmp-"

T = TypeVar("T")


class IndexBusy(RuntimeError):
    """Another builder holds the lock and no fresh generation appeared in time."""


def new_name(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def fsync_path(path: Path) -> None:
    """Best-effort fsync of a file or directory (directories are a no-op on Windows)."""
    flags = os.O_RDONLY
    if path.is_dir():
        if os.name == "nt":
            return
        flags |= getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def fsync_tree(path: Path) -> None:
    for child in sorted(path.rglob("*")):
        if child.is_file() and not child.is_symlink():
            fsync_path(child)
    for child in sorted((p for p in path.rglob("*") if p.is_dir()), reverse=True):
        fsync_path(child)
    fsync_path(path)


def write_json_atomic(target: Path, data: dict[str, Any]) -> None:
    """Write ``target`` via a unique temp sibling, fsync and ``os.replace``."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f"{TMP_PREFIX}{target.name}.{os.getpid()}.{new_name()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    fsync_path(target.parent)


def publish_dir(tmp_dir: Path, dest: Path) -> None:
    """Atomically move a fully written temp generation to its final name."""
    fsync_tree(tmp_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp_dir, dest)
    fsync_path(dest.parent)


def clean_temp(parent: Path) -> None:
    """Remove leftover ``.tmp-*`` entries (only safe while holding the lock)."""
    if not parent.is_dir():
        return
    for child in parent.iterdir():
        if not child.name.startswith(TMP_PREFIX) or child.is_symlink():
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass


class BuildLock:
    def __init__(self, parent: Path) -> None:
        self.parent = parent
        self.path = parent / LOCK_NAME
        self.held = False

    def info(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def age(self) -> float | None:
        info = self.info() or {}
        created = info.get("created")
        if isinstance(created, (int, float)) and not isinstance(created, bool):
            return time.time() - float(created)
        try:
            return time.time() - self.path.stat().st_mtime
        except OSError:
            return None

    def is_stale(self) -> bool:
        age = self.age()
        return age is not None and age > LOCK_STALE_SECONDS

    def _break_stale(self) -> None:
        aside = self.parent / f"{TMP_PREFIX}lock-{new_name()}"
        try:
            os.replace(self.path, aside)
        except OSError:
            return
        try:
            aside.unlink()
        except OSError:
            pass

    def try_acquire(self) -> bool:
        self.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                if attempt == 0 and self.is_stale():
                    self._break_stale()
                    continue
                return False
            try:
                body = {"pid": os.getpid(), "host": socket.gethostname(), "created": time.time()}
                os.write(fd, (json.dumps(body) + "\n").encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            self.held = True
            return True
        return False

    def release(self) -> None:
        if not self.held:
            return
        self.held = False
        try:
            self.path.unlink()
        except OSError:
            pass


def locked_build(
    parent: Path,
    fresh: Callable[[], T | None],
    build: Callable[[], T],
    wait: float | None = None,
) -> tuple[T, bool]:
    """Return ``(result, built)``: a fresh generation found while waiting, or a new build.

    ``fresh`` is re-checked after taking the lock so two builders racing for
    the same digest build once.
    """
    lock = BuildLock(parent)
    budget = LOCK_WAIT_SECONDS if wait is None else wait
    deadline = time.monotonic() + budget
    while not lock.try_acquire():
        found = fresh()
        if found is not None:
            return found, False
        if time.monotonic() >= deadline:
            raise IndexBusy(f"index build in progress (lock {lock.path.name} held)")
        time.sleep(LOCK_POLL_SECONDS)
    try:
        found = fresh()
        if found is not None:
            return found, False
        clean_temp(parent)
        return build(), True
    finally:
        lock.release()
