from __future__ import annotations

import contextvars
import os
import stat
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

RESERVED = frozenset({"index.md", "log.md"})
SCHEMA_NAME = "SCHEMA.json"
# 0.13.0 WRITE model: a store's root type/key contract lives in
# CONTRACT.json instead of SCHEMA.json (a 0.13.0-beta.3, beta.4 or beta.7
# stamp on CONTRACT.json with the same layers shape is still accepted as
# current on read).
# Readers accept exactly one of the two filenames (see
# core.schema.find_contract_path); callers that merely need to know "does
# this directory already have a contract file" should use
# has_contract_file() rather than hard-coding SCHEMA_NAME.
CONTRACT_NAME = "CONTRACT.json"
CONTRACT_FILENAMES = (SCHEMA_NAME, CONTRACT_NAME)
DEFAULT_STAGING = "staging"
SKIP_DIRS = frozenset({"staging", "templates", ".atlas-index", ".atlas", "mesh", "schema.d", ".git"})


def store_root(root: str | None) -> Path:
    if root:
        return Path(root).expanduser().resolve()
    return Path.cwd().resolve()


def has_contract_file(root: Path) -> bool:
    """True when root has exactly one of SCHEMA.json / CONTRACT.json.

    Used by callers (store init/rehost) that only need a presence check,
    not the strict single-file compile gate in core.schema.find_contract_path.
    """
    return any((root / name).is_file() for name in CONTRACT_FILENAMES)


# Mesh-scope page walks set this. Store scope leaves it false, so those walks
# stay byte-identical (ripgrep may still be handed a symlink; ``is_file`` still
# follows a file symlink).
_MESH_WALKS: contextvars.ContextVar[bool] = contextvars.ContextVar("atlas_mesh_walks", default=False)


def skipping_symlinks() -> bool:
    """True while mesh-scope walks must not follow symlinks."""
    return _MESH_WALKS.get()


# Warnings recorded while :func:`mesh_walks` is active. ``None`` outside it.
_MESH_SKIPPED: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "atlas_mesh_skipped_symlinks", default=None
)


@contextmanager
def mesh_walks():
    """Do not follow symlinks for the duration of a mesh-scope page walk.

    Yields the warnings emitted by :func:`note_skipped_symlink` in this
    context. Store scope never enters it, so its walks are unchanged.
    ``with mesh_walks():`` still works when the list is not needed.
    """
    token = _MESH_WALKS.set(True)
    skipped: list[str] = []
    skip_token = _MESH_SKIPPED.set(skipped)
    try:
        yield skipped
    finally:
        _MESH_SKIPPED.reset(skip_token)
        _MESH_WALKS.reset(token)


def is_symlink_entry(path: Path) -> bool:
    """``lstat`` symlink check. Never follows. False when the path cannot be stat-ed.

    Uses ``os.lstat`` directly. ``Path.is_symlink`` reaches ``os.stat`` on
    Python 3.13, which is a following stat to a caller that cannot see
    ``follow_symlinks=False``.
    """
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


def mesh_symlink(path: Path) -> bool:
    """True when mesh scope must not follow ``path`` (``lstat`` only)."""
    return skipping_symlinks() and is_symlink_entry(path)


def regular_file(path: Path) -> bool:
    """True when ``path`` is a regular file. Never follows a symlink."""
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def regular_dir(path: Path) -> bool:
    """True when ``path`` is a real directory. Never follows a symlink."""
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def leading_symlink(path: Path) -> Path | None:
    """First symlink component of ``path``, via ``lstat``. None if none exists.

    The walk stops at the first link, so the target is not stat-ed or opened.
    A missing component is not a symlink.
    """
    raw = Path(path)
    if raw.is_absolute():
        acc = Path(raw.anchor)
        parts = raw.parts[1:]
    else:
        acc = Path()
        parts = raw.parts
    for part in parts:
        acc = acc / part
        if is_symlink_entry(acc):
            return acc
    return None


def note_skipped_symlink(path: Path, kind: str) -> None:
    """Warn that mesh scope skipped a symlink instead of following it.

    Printed to stderr, and recorded on the active :func:`mesh_walks` list
    when one is open. Safe outside that context (discovery and member
    classification): the warning is still printed.
    """
    message = f"warning: mesh scope skipped symlink {kind}: {path}"
    print(message, file=sys.stderr)
    skipped = _MESH_SKIPPED.get()
    if skipped is not None:
        skipped.append(message)


def skip_mesh_symlink(path: Path, kind: str) -> bool:
    """True when mesh scope must skip ``path`` (and has noted it). Never follows.

    A symlink component anywhere on ``path`` counts. Store scope always
    returns False.
    """
    if not skipping_symlinks():
        return False
    link = leading_symlink(path)
    if link is None:
        return False
    note_skipped_symlink(link, kind)
    return True


def has_symlink_component(base: Path, *relatives: str) -> bool:
    """True when a lexical path under ``base`` has a symlink component.

    Absolute parts and ``..`` return False: those are not an in-project
    symlink. The walk stops at the first symlink and uses ``lstat``, so the
    link is not followed and nothing under it is stat-ed or opened.
    """
    lexical = join_under(base, *relatives)
    if lexical is None:
        return False
    acc = base
    for part in lexical.relative_to(base).parts:
        acc = acc / part
        if is_symlink_entry(acc):
            return True
    return False


def join_under(base: Path, *relatives: str) -> Path | None:
    """``base`` joined with each relative part, or None for an absolute part or a ``..`` segment."""
    cur = base
    for rel_part in relatives:
        if not rel_part:
            continue
        part = Path(rel_part)
        if part.is_absolute() or part.drive or ".." in part.parts:
            return None
        cur = cur.joinpath(*part.parts)
    return cur


def contained_root(project: Path, *relatives: str) -> Path | None:
    """``project / relatives`` (normalised) when it stays inside ``project``, else None.

    Rejects an absolute part or a ``..`` segment lexically, then walks the
    components from ``project`` and rejects a symlink that resolves outside
    it. The walk stops at the first escaping link, so nothing under an
    outside target is ever stat-ed or opened.
    """
    lexical = join_under(project, *relatives)
    if lexical is None:
        return None
    try:
        real_project = project.resolve()
    except (OSError, RuntimeError):
        return None
    acc = project
    for part in lexical.relative_to(project).parts:
        acc = acc / part
        if not os.path.islink(acc):
            continue
        try:
            acc.resolve().relative_to(real_project)
        except (OSError, RuntimeError, ValueError):
            return None
    return Path(os.path.normpath(lexical))


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _under_skip(root: Path, path: Path, staging_dir: str) -> bool:
    try:
        rel_parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return False
    if not rel_parts:
        return False
    skip = set(SKIP_DIRS) | {staging_dir}
    return rel_parts[0] in skip


def _contained(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def walk_tops(root: Path, staging_dir: str = DEFAULT_STAGING) -> list[Path]:
    """Top-level entries of ``root`` a walk enters: skipped directories are dropped by name, unlisted.

    Mesh scope (:func:`skipping_symlinks`) also drops symlink entries, and does
    not list a symlinked root, so ripgrep is never handed a symlink path.
    Store scope is unchanged.
    """
    if skipping_symlinks() and is_symlink_entry(root):
        return []
    skip = set(SKIP_DIRS) | {staging_dir}
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    tops = [root / name for name in names if name not in skip]
    if skipping_symlinks():
        tops = [p for p in tops if not is_symlink_entry(p)]
    return tops


def iter_concept_md(root: Path, staging_dir: str = DEFAULT_STAGING):
    """Yield concept markdown files (skip staging, templates, mesh, index artifacts).

    Skipped top-level directories are pruned by name, so nothing inside them
    is listed or stat'ed. Symlinked directories are not followed. Mesh scope
    also skips symlinked files (``lstat`` before ``is_file``) and does not
    open a symlinked walk root. Store scope is unchanged.
    """
    if skipping_symlinks() and is_symlink_entry(root):
        return
    root_res = root.resolve()
    skip = set(SKIP_DIRS) | {staging_dir}
    found: list[Path] = []
    top = True
    mesh = skipping_symlinks()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        if top:
            dirnames[:] = [d for d in dirnames if d not in skip]
            top = False
        if mesh:
            dirnames[:] = [d for d in dirnames if not is_symlink_entry(here / d)]
        found.extend(here / name for name in filenames if name.endswith(".md"))
    for path in sorted(found):
        if mesh and is_symlink_entry(path):
            continue
        if not path.is_file():
            continue
        if not _contained(root_res, path):
            continue
        if _under_skip(root, path, staging_dir):
            continue
        if path.name == SCHEMA_NAME:
            continue
        yield path


def staging_files(root: Path, staging_dir: str = DEFAULT_STAGING) -> list[Path]:
    s = root / staging_dir
    if not s.is_dir():
        return []
    return sorted(p for p in s.rglob("*") if p.is_file())


class UnsafeDestination(OSError):
    """Destination exists and is not a regular file, so a writer must not follow it."""

    def __init__(self, path: Path | str, kind: str) -> None:
        self.kind = kind
        message = f"refusing to write through a {kind}: {path}"
        # OSError.__str__ drops a plain message once .filename is set.
        super().__init__(message)
        self.filename = os.fspath(path)

    def __str__(self) -> str:
        return self.args[0] if self.args else f"refusing to write through a {self.kind}: {self.filename}"


def _nofollow() -> int:
    return getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def exclusive_flags() -> int:
    """``O_CREAT|O_EXCL|O_NOFOLLOW`` so a symlink is ``EEXIST`` and is not followed."""
    return os.O_CREAT | os.O_EXCL | os.O_WRONLY | _nofollow()


def _kind(st: os.stat_result) -> str:
    if stat.S_ISLNK(st.st_mode):
        return "symlink"
    if stat.S_ISDIR(st.st_mode):
        return "directory"
    if stat.S_ISFIFO(st.st_mode):
        return "fifo"
    if stat.S_ISSOCK(st.st_mode):
        return "socket"
    return "non-regular file"


def refuse_non_regular(path: Path) -> None:
    """lstat ``path`` and refuse it when it exists and is not a regular file.

    A missing path is fine. A symlink is refused even when its target is a
    regular file, so callers never follow or replace that directory entry.
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISREG(st.st_mode):
        return
    raise UnsafeDestination(path, _kind(st))


def refuse_symlink(path: Path) -> None:
    """Refuse a symlink (or fifo/socket) at ``path``. A missing path is fine.

    A real directory or regular file is left for the caller (``os.replace`` of
    a directory onto an existing directory still fails as before).
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(st.st_mode) or not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
        raise UnsafeDestination(path, _kind(st))


def ensure_directory(path: Path) -> None:
    """Create ``path`` as a real directory. Refuse a symlinked leaf.

    Ancestors may be symlinks (``/tmp`` often is). Only the leaf is lstat-ed.
    An existing real directory is left alone. ``Path.mkdir(exist_ok=True)`` is
    not used on the leaf, because that follows a symlink to a directory.
    """
    path = Path(path)
    parent = path.parent
    if parent != path:
        try:
            os.lstat(parent)
        except FileNotFoundError:
            parent.mkdir(parents=True, exist_ok=True)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        try:
            os.mkdir(path)
        except FileExistsError:
            st = os.lstat(path)
        else:
            return
    if stat.S_ISLNK(st.st_mode):
        raise UnsafeDestination(path, "symlink")
    if not stat.S_ISDIR(st.st_mode):
        raise UnsafeDestination(path, _kind(st))


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError(f"short write to fd {fd}")
        view = view[written:]


def _fsync_dir(parent: Path) -> None:
    try:
        dir_fd = os.open(os.fspath(parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def atomic_write_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Write ``path`` without following a destination symlink.

    lstat the destination and refuse it when it exists and is not a regular
    file. Write a temp file created with ``O_CREAT|O_EXCL|O_NOFOLLOW`` in the
    same directory, fsync, then ``os.replace`` over the destination (that
    replaces the directory entry, not a symlink target).
    """
    path = Path(path)
    refuse_non_regular(path)
    parent = path.parent
    tmp = parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    fd = os.open(os.fspath(tmp), exclusive_flags(), 0o666)
    try:
        _write_all(fd, data)
        os.fsync(fd)
        if mode is not None:
            try:
                os.fchmod(fd, mode)
            except OSError:
                pass
    except BaseException:
        os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.close(fd)
    try:
        refuse_non_regular(path)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(parent)


def atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    """UTF-8 :func:`atomic_write_bytes`."""
    atomic_write_bytes(path, text.encode("utf-8"), mode=mode)


def append_text(path: Path, text: str) -> None:
    """Append to a regular file, or create one, without following a symlink."""
    path = Path(path)
    data = text.encode("utf-8")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        atomic_write_bytes(path, data)
        return
    if not stat.S_ISREG(st.st_mode):
        raise UnsafeDestination(path, _kind(st))
    fd = os.open(os.fspath(path), os.O_WRONLY | os.O_APPEND | _nofollow())
    try:
        _write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def create_exclusive(path: Path, *, mode: int = 0o644) -> int:
    """Create a new regular file with ``O_CREAT|O_EXCL|O_NOFOLLOW``. Caller owns the fd."""
    return os.open(os.fspath(path), exclusive_flags(), mode)
