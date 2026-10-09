"""Keep `.atlas-index/` out of git via the repository's local exclude file."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

INDEX_DIR = ".atlas-index"
_GLOB_SPECIAL = re.compile(r"([*?\[\]\\])")


def _git(store: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(store),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _normalise(line: str) -> str:
    text = line.strip()
    if text.startswith("**/"):
        text = text[3:]
    return text.rstrip("/")


def _covered(lines: list[str], rel_posix: str) -> bool:
    """True when an existing exclude line already ignores the store's index dir."""
    target = f"{rel_posix}/{INDEX_DIR}" if rel_posix else INDEX_DIR
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        norm = _normalise(line)
        if norm == INDEX_DIR:
            return True
        if norm.lstrip("/") == target:
            return True
    return False


def ensure_index_ignored(store: Path) -> dict[str, Any] | None:
    """Append `.atlas-index/` to `info/exclude` when needed.

    Returns an info item only when a line was added. Never raises.
    """
    try:
        if shutil.which("git") is None or not store.is_dir():
            return None
        if _git(store, "rev-parse", "--is-inside-work-tree") != "true":
            return None
        top = _git(store, "rev-parse", "--show-toplevel")
        exclude_raw = _git(store, "rev-parse", "--git-path", "info/exclude")
        if not top or not exclude_raw:
            return None
        top_path = Path(top).resolve()
        try:
            rel_path = store.resolve().relative_to(top_path)
        except ValueError:
            return None
        rel_posix = rel_path.as_posix()
        if rel_posix == ".":
            rel_posix = ""
        exclude = Path(exclude_raw)
        if not exclude.is_absolute():
            exclude = (store / exclude).resolve()
        existing = ""
        if exclude.is_file():
            existing = exclude.read_text(encoding="utf-8", errors="replace")
        if _covered(existing.splitlines(), rel_posix):
            return None
        escaped = _GLOB_SPECIAL.sub(r"\\\1", rel_posix)
        line = f"/{escaped}/{INDEX_DIR}/" if escaped else f"/{INDEX_DIR}/"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        with exclude.open("a", encoding="utf-8") as fh:
            fh.write(f"{prefix}{line}\n")
        return {
            "id": "atlas_index_ignored",
            "path": str(exclude),
            "msg": f"added '{line}' to git info/exclude so the recall index stays untracked",
            "line": line,
        }
    except Exception:
        return None
