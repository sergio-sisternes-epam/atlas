from __future__ import annotations

import contextvars
import os
import stat
import sys
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
    """``lstat`` symlink check. Never follows. False when the path cannot be stat-ed."""
    try:
        return Path(path).is_symlink()
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
