from __future__ import annotations

from pathlib import Path

RESERVED = frozenset({"index.md", "log.md"})
SCHEMA_NAME = "SCHEMA.json"
DEFAULT_STAGING = "staging"
SKIP_DIRS = frozenset({"staging", "templates", ".atlas-index", "mesh", "schema.d", ".git"})


def store_root(root: str | None) -> Path:
    if root:
        return Path(root).expanduser().resolve()
    return Path.cwd().resolve()


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


def iter_concept_md(root: Path, staging_dir: str = DEFAULT_STAGING):
    """Yield concept markdown files (skip staging, templates, mesh, index artifacts)."""
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
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
