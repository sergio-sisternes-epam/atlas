"""Keep derived indexes out of git via the repository's local exclude file.

Primary guard: ``/.atlas/indexes/`` in the project root's repository
(:func:`ensure_indexes_ignored`). Legacy guard: ``.atlas-index/`` in the
store's repository (:func:`ensure_index_ignored`), kept for 0.14.x while the
deprecated in-store location is still read. Only ``info/exclude`` is ever
edited; committed ``.gitignore`` files are never touched.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

INDEX_DIR = ".atlas-index"
INDEXES_DIR = ".atlas/indexes"
_GLOB_SPECIAL = re.compile(r"([*?\[\]\\])")

IGNORED_ADDED = "ignored_added"
ALREADY_IGNORED = "already_ignored"
NOT_GIT = "not_git"
FAILED = "failed"


@dataclass(frozen=True)
class GuardResult:
    """Outcome of an ignore guard: ``status`` is one of the module constants.

    ``failed`` is never treated as already ignored: callers surface
    :meth:`item` as a warning and carry on (the command's exit code is unchanged).
    """

    status: str
    code: str
    pattern: str
    path: str | None = None
    line: str | None = None
    reason: str | None = None
    note: str = ""

    def item(self) -> dict[str, Any] | None:
        """Info item when a line was added, warning item on failure, else ``None``."""
        if self.status == IGNORED_ADDED:
            return {
                "id": self.code.replace("_ignore_failed", "_ignored"),
                "path": self.path,
                "msg": f"added '{self.line}' to git info/exclude so {self.note} untracked",
                "line": self.line,
            }
        if self.status == FAILED:
            target = self.path or "info/exclude"
            message = (
                f"could not add {self.line or self.pattern} to {target}: {self.reason}; "
                "add it to .gitignore or info/exclude yourself to keep derived indexes out of commits"
            )
            return {
                "code": self.code,
                "id": self.code,
                "level": "warning",
                "path": target,
                "reason": self.reason,
                "message": message,
                "msg": message,
            }
        return None


def is_warning(item: dict[str, Any] | None) -> bool:
    return bool(item) and item.get("level") == "warning"


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _git(store: Path, *args: str) -> str | None:
    proc = _run_git(store, *args)
    if proc is None or proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _git_error(proc: subprocess.CompletedProcess[str] | None, what: str) -> str:
    if proc is None:
        return f"{what} could not run"
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return f"{what} failed (exit {proc.returncode}{': ' + detail[-1] if detail else ''})"


def _os_reason(e: OSError) -> str:
    return e.strerror or str(e)


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


def _covers_indexes(lines: list[str], rel_posix: str) -> bool:
    """True when an existing exclude line already ignores ``<rel>/.atlas/indexes/``."""
    names = (".atlas", INDEXES_DIR)
    targets = {f"{rel_posix}/{n}" if rel_posix else n for n in names}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        anywhere = line.startswith("**/")
        norm = _normalise(line)
        bare = norm.lstrip("/")
        if (anywhere or "/" not in norm) and bare in names:
            return True
        if bare in targets:
            return True
    return False


def _check_ignored(cwd: Path, probe: Path) -> int | None:
    """``git check-ignore -q`` exit code for ``probe`` (0 ignored, 1 not, other error); argv only."""
    proc = _run_git(cwd, "check-ignore", "-q", "--", str(probe))
    return None if proc is None else proc.returncode


def _guard(
    anchor: Path,
    *,
    subdir: str,
    code: str,
    note: str,
    covered: Any,
) -> GuardResult:
    pattern = f"/{subdir}/"

    def failed(reason: str, path: Path | None = None, line: str | None = None) -> GuardResult:
        return GuardResult(FAILED, code, pattern, str(path) if path else None, line, reason, note)

    if shutil.which("git") is None or not anchor.is_dir():
        return GuardResult(NOT_GIT, code, pattern, note=note)
    if _git(anchor, "rev-parse", "--is-inside-work-tree") != "true":
        return GuardResult(NOT_GIT, code, pattern, note=note)
    top_proc = _run_git(anchor, "rev-parse", "--show-toplevel")
    if top_proc is None or top_proc.returncode != 0 or not top_proc.stdout.strip():
        return failed(_git_error(top_proc, "git rev-parse --show-toplevel"))
    path_proc = _run_git(anchor, "rev-parse", "--git-path", "info/exclude")
    if path_proc is None or path_proc.returncode != 0 or not path_proc.stdout.strip():
        return failed(_git_error(path_proc, "git rev-parse --git-path info/exclude"))
    try:
        rel_path = anchor.resolve().relative_to(Path(top_proc.stdout.strip()).resolve())
    except ValueError:
        return failed("the directory is outside the git work tree reported by git")
    rel_posix = rel_path.as_posix()
    if rel_posix == ".":
        rel_posix = ""
    exclude = Path(path_proc.stdout.strip())
    if not exclude.is_absolute():
        exclude = (anchor / exclude).resolve()
    escaped = _GLOB_SPECIAL.sub(r"\\\1", rel_posix)
    line = f"/{escaped}/{subdir}/" if escaped else pattern
    existing = ""
    try:
        if exclude.exists() or exclude.is_symlink():
            existing = exclude.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return failed(f"cannot read it ({_os_reason(e)})", exclude, line)
    if covered(existing.splitlines(), rel_posix):
        return GuardResult(ALREADY_IGNORED, code, pattern, str(exclude), line, note=note)
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a", encoding="utf-8") as fh:
            fh.write(f"{prefix}{line}\n")
    except OSError as e:
        # Unwritable exclude: fine only when git already ignores the directory another way.
        if _check_ignored(anchor, anchor / subdir / ".atlas-probe") == 0:
            return GuardResult(ALREADY_IGNORED, code, pattern, str(exclude), line, note=note)
        return failed(f"cannot write it ({_os_reason(e)})", exclude, line)
    return GuardResult(IGNORED_ADDED, code, pattern, str(exclude), line, note=note)


def guard_index(store: Path) -> GuardResult:
    """Legacy guard: ``.atlas-index/`` in the store's repository. Never raises."""
    try:
        return _guard(
            store,
            subdir=INDEX_DIR,
            code="atlas_index_ignore_failed",
            note="the recall index stays",
            covered=_covered,
        )
    except Exception as e:  # noqa: BLE001 - a guard never fails the command
        return GuardResult(FAILED, "atlas_index_ignore_failed", f"/{INDEX_DIR}/", reason=str(e) or type(e).__name__)


def guard_indexes(store: Path) -> GuardResult:
    """Primary guard: ``/.atlas/indexes/`` (anchored at the work-tree top) in ``info/exclude``.

    Uses the repository that contains the store's index project root (see
    core/index_location.py); a project root outside git is ``not_git``. Never raises.
    """
    try:
        from .index_location import resolve

        project = resolve(store).project_root
        return _guard(
            project,
            subdir=INDEXES_DIR,
            code="atlas_indexes_ignore_failed",
            note="derived indexes stay",
            covered=_covers_indexes,
        )
    except Exception as e:  # noqa: BLE001 - a guard never fails the command
        return GuardResult(FAILED, "atlas_indexes_ignore_failed", f"/{INDEXES_DIR}/", reason=str(e) or type(e).__name__)


MESH_PATTERNS = ("atlas-mesh.json.lock*", ".atlas-mesh.json.*.tmp")


def ensure_mesh_lock_ignored(project: Path) -> GuardResult:
    """Append the mesh write lock and temp-file patterns to ``info/exclude``.

    ``atlas-mesh.json.lock`` (and its ``.takeover`` / ``.stale-*`` siblings)
    and ``.atlas-mesh.json.*.tmp`` are short-lived, but a crash can leave
    one behind; this keeps them out of commits. Anchored at the project
    directory. Never raises; callers treat ``failed`` as a warning.
    """
    code = "atlas_mesh_lock_ignore_failed"
    pattern = "/" + MESH_PATTERNS[0]
    try:
        if shutil.which("git") is None or not project.is_dir():
            return GuardResult(NOT_GIT, code, pattern)
        if _git(project, "rev-parse", "--is-inside-work-tree") != "true":
            return GuardResult(NOT_GIT, code, pattern)
        top = _git(project, "rev-parse", "--show-toplevel")
        exclude_raw = _git(project, "rev-parse", "--git-path", "info/exclude")
        if not top or not exclude_raw:
            return GuardResult(FAILED, code, pattern, reason="git rev-parse failed")
        rel_posix = project.resolve().relative_to(Path(top).resolve()).as_posix()
        rel_posix = "" if rel_posix == "." else rel_posix
        exclude = Path(exclude_raw)
        if not exclude.is_absolute():
            exclude = (project / exclude).resolve()
        escaped = _GLOB_SPECIAL.sub(r"\\\1", rel_posix)
        prefix_dir = f"/{escaped}/" if escaped else "/"
        wanted = [prefix_dir + name for name in MESH_PATTERNS]
        existing = exclude.read_text(encoding="utf-8", errors="replace") if exclude.exists() else ""
        have = {line.strip() for line in existing.splitlines()}
        missing = [line for line in wanted if line not in have]
        if not missing:
            return GuardResult(ALREADY_IGNORED, code, pattern, str(exclude))
        exclude.parent.mkdir(parents=True, exist_ok=True)
        lead = "" if not existing or existing.endswith("\n") else "\n"
        with exclude.open("a", encoding="utf-8") as fh:
            fh.write(lead + "".join(f"{line}\n" for line in missing))
        return GuardResult(IGNORED_ADDED, code, pattern, str(exclude), missing[0])
    except Exception as e:  # noqa: BLE001 - a guard never fails the command
        return GuardResult(FAILED, code, pattern, reason=str(e) or type(e).__name__)


def ensure_index_ignored(store: Path) -> dict[str, Any] | None:
    """Append ``.atlas-index/`` to ``info/exclude`` when needed.

    Returns an info item when a line was added, a warning item
    (``atlas_index_ignore_failed``) when the guard failed, else ``None``.
    """
    return guard_index(store).item()


def ensure_indexes_ignored(store: Path) -> dict[str, Any] | None:
    """Append ``/.atlas/indexes/`` to ``info/exclude`` when needed.

    Returns an info item when a line was added, a warning item
    (``atlas_indexes_ignore_failed``) when the guard failed, else ``None``.
    """
    return guard_indexes(store).item()


def indexes_ignore_status(store: Path | None, project: Path | None = None) -> dict[str, Any]:
    """Read-only: is ``.atlas/indexes/`` actually ignored? ``status`` ok | missing | failed | n/a.

    Asks git itself (``git check-ignore -q`` on a path under the project's
    ``.atlas/indexes/``), so ``.gitignore`` and global excludes count too.
    """
    if project is None:
        try:
            from .index_location import resolve

            project = resolve(store).project_root
        except Exception as e:  # noqa: BLE001 - status is advisory
            return {"status": FAILED, "reason": str(e) or type(e).__name__}
    if shutil.which("git") is None or not project.is_dir():
        return {"status": "n/a", "reason": "not in a git work tree"}
    if _git(project, "rev-parse", "--is-inside-work-tree") != "true":
        return {"status": "n/a", "reason": "not in a git work tree"}
    probe = project / INDEXES_DIR / ".atlas-probe"
    proc = _run_git(project, "check-ignore", "-q", "--", str(probe))
    if proc is not None and proc.returncode == 0:
        return {"status": "ok", "reason": None}
    if proc is not None and proc.returncode == 1:
        return {"status": "missing", "reason": f"{INDEXES_DIR}/ is not ignored by .gitignore or info/exclude"}
    return {"status": FAILED, "reason": _git_error(proc, "git check-ignore")}
