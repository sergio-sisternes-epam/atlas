"""Atomic generation publish and a simple builder lock for derived indexes.

Shared by the fts5 recall index (core/recall_index.py) and the nanograph
driver (core/drivers/nanograph.py). Both keep their files under
``<project-root>/.atlas/indexes/<driver-type>/<atlas-id>/`` (the *parent*):

- A builder takes ``<parent>/.lock`` (``O_CREAT | O_EXCL``; JSON with a
  per-acquisition ``owner`` token, pid, host and ``created_at``). A lock older
  than :data:`LOCK_STALE_SECONDS`, or whose pid is gone on this host, is stale:
  a new builder renames it aside to ``.lock.stale-<owner>-<rand>`` (atomic;
  losing that race means retrying) and then creates its own. Only the owner
  releases a lock; a builder that lost it publishes nothing (``lock_lost``).
- It builds into ``<parent>/.tmp-<name>``, fsyncs, then publishes with one
  ``os.replace`` of the directory and one ``os.replace`` of the pointer file.
  The final ownership check, the pointer replace and the pruning of old
  generations run inside :func:`critical_section` (the lock's takeover guard
  held throughout), so a stale takeover cannot slip between the check and the
  write; pruned generations are only renamed to ``.tmp-*`` there and removed
  afterwards, keeping the section short.
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
import time
import uuid
from pathlib import Path
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Callable, TypeVar

from .owned_lock import TAKEOVER_STALE_SECONDS, OwnedLock, OwnershipLost

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


class BuildLock(OwnedLock):
    """``<parent>/.lock`` with an owner token; only the owner releases it (see core/owned_lock.py)."""

    def __init__(self, parent: Path) -> None:
        super().__init__(parent, LOCK_NAME, LOCK_STALE_SECONDS, TAKEOVER_STALE_SECONDS)


class LockLost(IndexBusy, OwnershipLost):
    """The builder lock was taken over while building; nothing was published."""

    code = "lock_lost"


@contextmanager
def critical_section(lock: BuildLock | None) -> Iterator[None]:
    """Hold the lock's takeover guard around a publish step; :class:`LockLost` if no longer ours.

    ``None`` (no lock) runs the step unguarded. Wrap only the commit step
    (pointer replace, prune), never a build.
    """
    if lock is None:
        yield
        return
    with lock.owned_critical_section(lost=lambda _msg: LockLost("index build lock lost (lock_lost); generation not published")):
        yield


def retire(paths: list[Path], into: Path) -> list[Path]:
    """Rename generations aside to ``<into>/.tmp-retired-*`` (cheap; call in the critical section).

    Readers and the pointer never see ``.tmp-*`` names; :func:`discard` (or the
    next lock holder's :func:`clean_temp`) removes them.
    """
    moved: list[Path] = []
    for path in paths:
        aside = into / f"{TMP_PREFIX}retired-{path.name}-{new_name()}"
        try:
            os.replace(path, aside)
        except OSError:
            continue
        moved.append(aside)
    return moved


def discard(paths: list[Path]) -> None:
    for path in paths:
        shutil.rmtree(path, ignore_errors=True)


def ensure_owned(lock: BuildLock | None) -> None:
    """Raise :class:`LockLost` unless ``lock`` is still ours (call before publishing)."""
    if lock is not None and not lock.still_owned():
        raise LockLost("index build lock lost (lock_lost); generation not published")


def lock_lost_warning() -> dict[str, str]:
    return {
        "code": "lock_lost",
        "level": "debug",
        "message": "index builder lock was taken over by another builder before release",
    }


def locked_build(
    parent: Path,
    fresh: Callable[[], T | None],
    build: Callable[[BuildLock], T],
    wait: float | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> tuple[T, bool]:
    """Return ``(result, built)``: a fresh generation found while waiting, or a new build.

    ``fresh`` is re-checked after taking the lock so two builders racing for
    the same digest build once. ``build`` receives the lock and must publish
    only inside :func:`critical_section`. A lock found taken over at
    release time appends a ``lock_lost`` debug warning to ``warnings``.
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
        return build(lock), True
    finally:
        if not lock.release() and lock.lost and warnings is not None:
            warnings.append(lock_lost_warning())
