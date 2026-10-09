"""Owner-token lock file shared by index builders and mesh writers.

A holder creates ``<parent>/<name>`` with ``O_CREAT | O_EXCL`` and writes JSON
with a per-acquisition ``owner`` token, pid, host and ``created_at``. A lock
older than ``stale_seconds``, or whose pid is gone on this host, is stale: a
new holder renames it aside to ``<name>.stale-<owner>-<rand>`` (atomic; losing
that race means retrying) and then creates its own. Takeovers are serialised by
a short-lived ``<name>.takeover`` guard. Only the owner releases a lock, and a
holder checks it still owns the lock before publishing anything.

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

        Takeovers are serialised by a short-lived ``<name>.takeover`` guard
        (``O_EXCL``), so only one builder renames a stale lock at a time. Under
        the guard the lock is re-checked; after the rename the moved file must
        still be the one we judged stale, or it is put back.
        """
        guard = self.parent / f"{self.name}.takeover"
        try:
            fd = os.open(str(guard), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                abandoned = time.time() - guard.stat().st_mtime > self.takeover_stale_seconds
            except OSError:
                abandoned = False
            if abandoned:
                aside = self.parent / f"{self.name}.takeover-stale-{_new_name()}"
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
            aside = self.parent / f"{self.name}.stale-{stale_owner}-{_new_name()}"
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
        private = self.parent / f"{self.name}.release-{self.owner}"
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
