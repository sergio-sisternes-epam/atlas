"""Owner-token lock file shared by index builders and mesh writers.

A holder creates ``<parent>/<name>`` with ``O_CREAT | O_EXCL`` and writes JSON
with a per-acquisition ``owner`` token, pid, host and ``created_at``. A lock
older than ``stale_seconds``, or whose pid is gone on this host, is stale: a
new holder renames it aside to ``<name>.stale-<owner>-<rand>`` (atomic; losing
that race means retrying) and then creates its own. Only the owner releases a
lock, and a holder checks it still owns the lock before publishing anything.

Takeover (re-check, rename aside, create) and release (re-check, rename aside,
unlink) both run under a short-lived ``<name>.takeover`` guard: an ``O_EXCL``
file holding its own owner token, removed only by its creator. So a release can
never move a lock that a takeover installed after the release's ownership
check. A guard older than ``takeover_stale_seconds`` is abandoned and is broken
(renamed aside, verified by token and identity, then removed).

Used by core/index_publish.py (``.lock`` per index parent) and
core/meshfile.py (``atlas-mesh.json.lock`` per project).
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from pathlib import Path
from typing import Any

TAKEOVER_STALE_SECONDS = 30.0
# How long a takeover waits for a busy guard (release waits until it is stale).
GUARD_WAIT_SECONDS = 2.0
GUARD_POLL_SECONDS = 0.005


def _new_name() -> str:
    return uuid.uuid4().hex[:8]


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


class OwnedLock:
    """``<parent>/<name>`` with an owner token; only the owner releases it.

    ``lost`` becomes true when a release or :meth:`still_owned` finds that the
    lock now belongs to someone else (a stale takeover happened).
    """

    def __init__(
        self,
        parent: Path,
        name: str,
        stale_seconds: float,
        takeover_stale_seconds: float = TAKEOVER_STALE_SECONDS,
    ) -> None:
        self.parent = parent
        self.name = name
        self.path = parent / name
        self.stale_seconds = stale_seconds
        self.takeover_stale_seconds = takeover_stale_seconds
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
        if age is not None and age > self.stale_seconds:
            return True
        pid = (info or {}).get("pid")
        if (info or {}).get("host") == socket.gethostname() and isinstance(pid, int) and not isinstance(pid, bool):
            return not _pid_alive(pid)
        return False

    def still_owned(self) -> bool:
        """True while the lock file carries our token.

        A plain read is enough on the happy path: every rename of a lock runs
        under the takeover guard and only ever moves the lock it judged stale
        or its own, so our lock is never moved aside transiently. A negative
        read is confirmed once under the guard (a consistent view after any
        in-flight guarded operation) before ``lost`` is set.
        """
        if not self.held:
            return False
        if (self.info() or {}).get("owner") == self.owner:
            return True
        token = self._acquire_guard(GUARD_WAIT_SECONDS)
        try:
            owned = (self.info() or {}).get("owner") == self.owner
        finally:
            if token is not None:
                self._release_guard(token)
        if not owned:
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

    @staticmethod
    def _restore(aside: Path, path: Path) -> None:
        """Put back a file we renamed by mistake, without clobbering a newer one."""
        try:
            os.link(aside, path)
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

    # --- takeover guard ---------------------------------------------------

    def _guard_path(self) -> Path:
        return self.parent / f"{self.name}.takeover"

    def _guard_stale(self, info: dict[str, Any] | None, guard: Path) -> bool:
        created = (info or {}).get("created_at")
        if isinstance(created, (int, float)) and not isinstance(created, bool):
            return time.time() - float(created) > self.takeover_stale_seconds
        try:
            return time.time() - guard.stat().st_mtime > self.takeover_stale_seconds
        except OSError:
            return False

    def _break_guard(self, guard: Path) -> None:
        """Remove an abandoned guard, but only the one we judged stale (by its owner token)."""
        seen_id = self._identity(guard)
        seen = self._read(guard)
        if seen_id is None or not self._guard_stale(seen, guard):
            return
        aside = self.parent / f"{self.name}.takeover-stale-{_new_name()}"
        try:
            os.rename(guard, aside)
        except OSError:
            return
        if self._identity(aside) != seen_id or (self._read(aside) or {}).get("owner") != (seen or {}).get("owner"):
            # Someone replaced the stale guard between our read and our rename: put theirs back.
            self._restore(aside, guard)
            return
        try:
            aside.unlink()
        except OSError:
            pass

    def _acquire_guard(self, wait: float) -> str | None:
        """Create ``<name>.takeover`` (``O_EXCL``) with our own token; ``None`` after ``wait`` seconds."""
        guard = self._guard_path()
        deadline = time.monotonic() + wait
        while True:
            token = uuid.uuid4().hex
            try:
                fd = os.open(str(guard), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                self._break_guard(guard)
                if time.monotonic() >= deadline:
                    return None
                time.sleep(GUARD_POLL_SECONDS)
                continue
            try:
                body = {"owner": token, "pid": os.getpid(), "created_at": time.time()}
                os.write(fd, (json.dumps(body) + "\n").encode("utf-8"))
            finally:
                os.close(fd)
            return token

    def _release_guard(self, token: str) -> None:
        """Remove the guard only if it is still the one we created."""
        guard = self._guard_path()
        private = self.parent / f"{self.name}.takeover-release-{token}"
        try:
            os.rename(guard, private)
        except OSError:
            return
        if (self._read(private) or {}).get("owner") != token:
            self._restore(private, guard)
            return
        try:
            private.unlink()
        except OSError:
            pass

    # --- lock -------------------------------------------------------------

    def _take_over(self, seen: dict[str, Any] | None, seen_id: tuple[int, int] | None) -> bool | None:
        """Under the guard, rename the stale lock we read aside and create ours.

        ``True``: we own the lock. ``False``: someone else does (or the guard
        stayed busy). ``None``: the lock vanished meanwhile; try creating again.
        Every rename of a lock (takeover or release) happens under the guard,
        so the re-check and the rename cannot be interleaved with another one.
        """
        token = self._acquire_guard(GUARD_WAIT_SECONDS)
        if token is None:
            return False
        try:
            now_id = self._identity(self.path)
            if now_id is None:
                return None
            if now_id != seen_id or self.info() != seen:
                return False
            stale_owner = str((seen or {}).get("owner") or "unknown")
            aside = self.parent / f"{self.name}.stale-{stale_owner}-{_new_name()}"
            try:
                os.rename(self.path, aside)
            except OSError:
                return False
            if self._read(aside) != seen or self._identity(aside) != seen_id:
                # Only possible if the guard itself was broken as stale meanwhile.
                self._restore(aside, self.path)
                return False
            try:
                aside.unlink()
            except OSError:
                pass
            return self._create()
        finally:
            self._release_guard(token)

    def try_acquire(self) -> bool:
        self.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(5):
            if self._create():
                return True
            seen_id = self._identity(self.path)
            if seen_id is None:
                continue
            seen = self.info()
            now_id = self._identity(self.path)
            if now_id is None:
                continue  # released meanwhile: try creating again
            if now_id != seen_id or not self.is_stale(seen):
                return False
            got = self._take_over(seen, seen_id)
            if got is not None:
                return got
        return False

    def release(self) -> bool:
        """Remove the lock only if we still own it; ``False`` (and ``lost``) otherwise.

        The ownership check and the removal run under the takeover guard, so a
        stale takeover can never slip between them and have its new lock moved.
        """
        if not self.held:
            return False
        self.held = False
        token = self._acquire_guard(self.takeover_stale_seconds + GUARD_WAIT_SECONDS)
        if token is None:
            # The guard is busy and not yet stale: leave our lock; it goes stale like any other.
            return False
        try:
            if (self.info() or {}).get("owner") != self.owner:
                self.lost = True
                return False
            private = self.parent / f"{self.name}.release-{self.owner}"
            try:
                os.rename(self.path, private)
            except OSError:
                self.lost = True
                return False
            if (self._read(private) or {}).get("owner") != self.owner:
                self._restore(private, self.path)
                self.lost = True
                return False
            try:
                private.unlink()
            except OSError:
                pass
            return True
        finally:
            self._release_guard(token)
