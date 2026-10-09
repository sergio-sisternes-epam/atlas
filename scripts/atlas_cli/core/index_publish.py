"""Atomic generation publish and a simple builder lock for derived indexes.

Shared by the fts5 recall index (core/recall_index.py) and the nanograph
driver (core/drivers/nanograph.py). Both keep their files under
``<project-root>/.atlas/indexes/<driver-type>/<atlas-id>/`` (the *parent*):

- A builder takes ``<parent>/.lock`` (``O_CREAT | O_EXCL``; JSON with a
  per-acquisition ``owner`` token, pid, host and ``created_at``). A lock older
  than :data:`LOCK_STALE_SECONDS`, or whose pid is gone on this host, is stale:
  a new builder renames it aside to ``.lock.stale-<owner>-<rand>`` (atomic;
  losing that race means retrying) and then creates its own. Only the owner
  releases a lock, and a builder checks it still owns the lock before
  publishing; a builder that lost it publishes nothing (``lock_lost``).
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
TAKEOVER_STALE_SECONDS = 30.0
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


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return True  # no cheap, safe probe; rely on the age check
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


class BuildLock:
    """``<parent>/.lock`` with an owner token; only the owner releases it.

    ``lost`` becomes true when a release or :meth:`still_owned` finds that the
    lock now belongs to someone else (a stale takeover happened).
    """

    def __init__(self, parent: Path) -> None:
        self.parent = parent
        self.path = parent / LOCK_NAME
        self.owner = uuid.uuid4().hex
        self.held = False
        self.lost = False

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def info(self) -> dict[str, Any] | None:
        return self._read(self.path)

    def age(self, info: dict[str, Any] | None = None) -> float | None:
        info = self.info() if info is None else info
        created = (info or {}).get("created_at", (info or {}).get("created"))
        if isinstance(created, (int, float)) and not isinstance(created, bool):
            return time.time() - float(created)
        try:
            return time.time() - self.path.stat().st_mtime
        except OSError:
            return None

    def is_stale(self, info: dict[str, Any] | None = None) -> bool:
        info = self.info() if info is None else info
        age = self.age(info)
        if age is not None and age > LOCK_STALE_SECONDS:
            return True
        pid = (info or {}).get("pid")
        if (info or {}).get("host") == socket.gethostname() and isinstance(pid, int) and not isinstance(pid, bool):
            return not _pid_alive(pid)
        return False

    def still_owned(self) -> bool:
        owned = self.held and (self.info() or {}).get("owner") == self.owner
        if self.held and not owned:
            self.lost = True
        return owned

    def _create(self) -> bool:
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        try:
            body = {
                "owner": self.owner,
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "created_at": time.time(),
            }
            os.write(fd, (json.dumps(body) + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        self.held = True
        self.lost = False
        return True

    def _restore(self, aside: Path) -> None:
        """Put back a lock we renamed by mistake, without clobbering a newer one."""
        try:
            os.link(aside, self.path)
        except OSError:
            return
        try:
            aside.unlink()
        except OSError:
            pass

    @staticmethod
    def _identity(path: Path) -> tuple[int, int] | None:
        try:
            st = path.stat()
        except OSError:
            return None
        return st.st_ino, st.st_mtime_ns

    def _take_over(self, seen: dict[str, Any] | None, seen_id: tuple[int, int] | None) -> bool:
        """Rename the stale lock we read aside and create ours; False when we did not get it.

        Takeovers are serialised by a short-lived ``.lock.takeover`` guard
        (``O_EXCL``), so only one builder renames a stale lock at a time. Under
        the guard the lock is re-checked; after the rename the moved file must
        still be the one we judged stale, or it is put back.
        """
        guard = self.parent / f"{LOCK_NAME}.takeover"
        try:
            fd = os.open(str(guard), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                abandoned = time.time() - guard.stat().st_mtime > TAKEOVER_STALE_SECONDS
            except OSError:
                abandoned = False
            if abandoned:
                aside = self.parent / f"{LOCK_NAME}.takeover-stale-{new_name()}"
                try:
                    os.rename(guard, aside)
                    aside.unlink()
                except OSError:
                    pass
            return False
        os.close(fd)
        try:
            if self._identity(self.path) != seen_id or self.info() != seen:
                return False
            stale_owner = str((seen or {}).get("owner") or "unknown")
            aside = self.parent / f"{LOCK_NAME}.stale-{stale_owner}-{new_name()}"
            try:
                os.rename(self.path, aside)
            except OSError:
                return False
            if self._read(aside) != seen or self._identity(aside) != seen_id:
                # The lock changed between our check and our rename (its owner released it).
                self._restore(aside)
                return False
            try:
                aside.unlink()
            except OSError:
                pass
            return self._create()
        finally:
            try:
                guard.unlink()
            except OSError:
                pass

    def try_acquire(self) -> bool:
        self.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(5):
            if self._create():
                return True
            seen_id = self._identity(self.path)
            if seen_id is None:
                continue
            seen = self.info()
            if self._identity(self.path) != seen_id or not self.is_stale(seen):
                return False
            return self._take_over(seen, seen_id)
        return False

    def release(self) -> bool:
        """Remove the lock only if we still own it; ``False`` (and ``lost``) otherwise."""
        if not self.held:
            return False
        self.held = False
        if (self.info() or {}).get("owner") != self.owner:
            self.lost = True
            return False
        private = self.parent / f"{LOCK_NAME}.release-{self.owner}"
        try:
            os.rename(self.path, private)
        except OSError:
            self.lost = True
            return False
        if (self._read(private) or {}).get("owner") != self.owner:
            self._restore(private)
            self.lost = True
            return False
        try:
            private.unlink()
        except OSError:
            pass
        return True


class LockLost(IndexBusy):
    """The builder lock was taken over while building; nothing was published."""

    code = "lock_lost"


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
    the same digest build once. ``build`` receives the lock and must call
    :func:`ensure_owned` before publishing anything. A lock found taken over at
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
