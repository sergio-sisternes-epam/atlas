"""Read-only Git history for Atlas pages and repository snapshots."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class HistoryError(ValueError):
    """Git history is unavailable or cannot be read."""

    def __init__(self, message: str, reason: str = "history_unavailable") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Version:
    commit: str
    recorded_at: str
    timestamp: int
    blob: str | None
    availability: str
    reason: str | None = None


def parse_as_of(value: str) -> datetime:
    """Parse an ISO date (end of day UTC) or ISO datetime."""
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            parsed = datetime.fromisoformat(value).replace(
                hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc
            )
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HistoryError("date must be an ISO date or datetime", "invalid_date") from exc
    return parsed.astimezone(timezone.utc)


def recorded_time(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _git(args: list[str], cwd: Path, *, binary: bool = False):
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            check=False,
            text=not binary,
        )
    except OSError as exc:
        raise HistoryError(f"cannot run git: {exc}") from exc
    if result.returncode:
        stderr = result.stderr.decode(errors="replace") if binary else result.stderr
        raise HistoryError(stderr.strip() or "git history command failed")
    return result.stdout


def _repo_and_path(root: Path, page: str) -> tuple[Path, str, str]:
    repo, store_relative = _repo_location(root)
    raw = Path(page)
    if raw.is_absolute() or ".." in raw.parts or not page.strip():
        raise HistoryError("page must be a store-relative path", "invalid_path")
    relative = raw.as_posix()
    if relative.startswith("./"):
        relative = relative[2:]
    if not relative or relative == ".":
        raise HistoryError("page must be a store-relative path", "invalid_path")
    repo_page = f"{store_relative}/{relative}" if store_relative != "." else relative
    return repo, store_relative, repo_page


def _repo_location(root: Path) -> tuple[Path, str]:
    repo_text = _git(["rev-parse", "--show-toplevel"], root).strip()
    repo = Path(repo_text).resolve()
    try:
        store_relative = root.resolve().relative_to(repo).as_posix()
    except ValueError as exc:
        raise HistoryError("store is outside its Git repository") from exc
    return repo, store_relative


def _blob_at(repo: Path, commit: str, path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{commit}:{path}"],
            cwd=repo,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise HistoryError(f"cannot inspect Git object: {exc}") from exc
    blob = result.stdout.strip() if result.returncode == 0 else None
    return blob if blob and re.fullmatch(r"[0-9a-f]{40,64}", blob) else None


def _version_at_path(repo: Path, commit: str, timestamp: int, path: str) -> Version:
    blob = _blob_at(repo, commit, path)
    if blob:
        try:
            exists = subprocess.run(
                ["git", "cat-file", "-e", blob],
                cwd=repo,
                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise HistoryError(f"cannot inspect Git object: {exc}") from exc
        if exists.returncode == 0:
            return Version(commit, recorded_time(timestamp), timestamp, blob, "available")
        return Version(commit, recorded_time(timestamp), timestamp, blob, "unavailable", "missing_object")
    return Version(commit, recorded_time(timestamp), timestamp, None, "unavailable", "path_absent")


def blob_at_commit(root: Path, commit: str, page: str) -> str | None:
    """Return a page's blob id in one locally available commit."""
    repo, _, repo_page = _repo_and_path(root, page)
    return _blob_at(repo, commit, repo_page)


def list_versions(root: Path, page: str) -> list[Version]:
    """List a page's commits newest first, following Git-detected renames."""
    repo, _, repo_page = _repo_and_path(root, page)
    output = _git(
        [
            "log",
            "--follow",
            "--find-renames",
            "--format=%H%x00%ct",
            "--name-status",
            "--",
            repo_page,
        ],
        repo,
    )
    commits: list[tuple[str, int, str]] = []
    current_path = repo_page
    pending: tuple[str, int] | None = None
    pending_older_path: str | None = None
    for line in output.splitlines():
        if "\x00" in line:
            if pending is not None:
                commits.append((pending[0], pending[1], current_path))
                if pending_older_path is not None:
                    current_path = pending_older_path
            fields = line.split("\x00")
            try:
                pending = (fields[0], int(fields[1]))
            except (IndexError, ValueError) as exc:
                raise HistoryError("cannot parse git history") from exc
            pending_older_path = None
            continue
        fields = line.split("\t")
        if fields and fields[0].startswith("R") and len(fields) == 3:
            pending_older_path = fields[1]
    if pending is not None:
        commits.append((pending[0], pending[1], current_path))
    return [
        _version_at_path(repo, commit, timestamp, path)
        for commit, timestamp, path in commits
    ]


def repository_version_at(root: Path, at: datetime) -> tuple[Path, str, str]:
    """Choose the reachable repository commit with the latest committer time <= at."""
    repo, store_relative = _repo_location(root)
    output = _git(["log", "--format=%H%x00%ct", "HEAD"], repo)
    candidates: list[tuple[int, str]] = []
    for line in output.splitlines():
        if "\x00" not in line:
            continue
        commit, raw_time = line.split("\x00", 1)
        try:
            timestamp = int(raw_time)
        except ValueError as exc:
            raise HistoryError("cannot parse repository history") from exc
        if timestamp <= int(at.timestamp()):
            candidates.append((timestamp, commit))
    if not candidates:
        shallow = _git(["rev-parse", "--is-shallow-repository"], repo).strip() == "true"
        reason = "shallow_history" if shallow else "no_commit_at_date"
        raise HistoryError("no locally available repository version at that date", reason)
    _, commit = max(candidates)
    return repo, store_relative, commit


def materialize_store(root: Path, commit: str, destination: Path) -> Path:
    """Materialize tracked regular files from one commit without checking out or fetching."""
    repo, store_relative = _repo_location(root)
    try:
        output = _git(["ls-tree", "-rz", "--full-tree", commit], repo, binary=True)
    except HistoryError as exc:
        raise HistoryError(str(exc), "missing_object") from exc
    prefix = "" if store_relative == "." else store_relative.rstrip("/") + "/"
    store = destination / store_relative if store_relative != "." else destination
    entries = output.split(b"\0")
    for entry in entries:
        if not entry:
            continue
        try:
            metadata, raw_path = entry.split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split(" ")
            repo_path = os.fsdecode(raw_path)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HistoryError("cannot parse repository tree", "missing_object") from exc
        if kind != "blob" or mode not in {"100644", "100755"} or not repo_path.startswith(prefix):
            continue
        relative = repo_path[len(prefix) :] if prefix else repo_path
        if not relative:
            continue
        try:
            content = _git(["cat-file", "blob", oid], repo, binary=True)
        except HistoryError as exc:
            raise HistoryError(str(exc), "missing_object") from exc
        target = store / relative
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        except OSError as exc:
            raise HistoryError(f"cannot materialize repository version: {exc}") from exc
    if not store.is_dir():
        store.mkdir(parents=True)
    return store


def is_shallow(root: Path) -> bool:
    repo, _ = _repo_location(root)
    return _git(["rev-parse", "--is-shallow-repository"], repo).strip() == "true"


def version_for_date(
    root: Path, page: str, at: datetime, blob: str | None = None
) -> Version | None:
    """Return the newest page version recorded by the requested date."""
    versions = list_versions(root, page)
    return next(
        (
            version
            for version in versions
            if version.timestamp <= int(at.timestamp())
            and (blob is None or version.blob == blob)
        ),
        None,
    )
