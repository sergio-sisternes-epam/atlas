from __future__ import annotations

from pathlib import Path

RESERVED = frozenset({"index.md", "log.md"})
SCHEMA_NAME = "SCHEMA.json"
# 0.13.0-beta.7 WRITE model: a store's root type/key contract lives in
# CONTRACT.json instead of SCHEMA.json (a 0.13.0-beta.3 or beta.4 stamp on
# CONTRACT.json with the same layers shape is still accepted as current).
# Readers accept exactly one of the two filenames (see
# core.schema.find_contract_path); callers that merely need to know "does
# this directory already have a contract file" should use
# has_contract_file() rather than hard-coding SCHEMA_NAME.
CONTRACT_NAME = "CONTRACT.json"
CONTRACT_FILENAMES = (SCHEMA_NAME, CONTRACT_NAME)
DEFAULT_STAGING = "staging"
SKIP_DIRS = frozenset({"staging", "templates", ".atlas-index", "mesh", "schema.d", ".git"})


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


def iter_concept_md(root: Path, staging_dir: str = DEFAULT_STAGING):
    """Yield concept markdown files (skip staging, templates, mesh, index artifacts)."""
    root_res = root.resolve()
    for path in sorted(root.rglob("*.md")):
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
