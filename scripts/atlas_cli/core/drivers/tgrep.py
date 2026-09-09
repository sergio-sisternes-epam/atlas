"""tgrep coarse driver: argv subprocess, Atlas-owned on-disk index, never serve."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable

from .scan import tokenise
from ..projection import ProjectedPage, SKIP_TOP
from ..schema import staging_dir_name

PIN = "d55b022023518646c90742f4761488dc95633b73"
MISSING = "unsupported_capability: tgrep_binary_missing"
SERVE_FORBIDDEN = "tgrep_serve_forbidden"
SERVE_DETECTED = "tgrep_serve_detected"
NO_INDEX_FORBIDDEN = "tgrep_no_index_forbidden"
TIMEOUT = "tgrep_timeout"
INDEX_NAME = "tgrep"
DIGEST_NAME = "generation.json"
INDEX_TIMEOUT_SEC = 120
SEARCH_TIMEOUT_SEC = 30
FORBIDDEN_TOKENS = frozenset({"serve", "--no-index"})
Runner = Callable[..., subprocess.CompletedProcess[str]]


class TgrepError(RuntimeError):
    pass


def find_binary() -> Path | None:
    found = shutil.which("tgrep")
    return Path(found) if found else None


def capability(binary: Path | None | object = ...) -> dict[str, Any]:
    resolved = find_binary() if binary is ... else binary
    present = bool(resolved)
    return {
        "id": "tgrep",
        "stages": ["coarse"],
        "supported": True,
        "pin": PIN,
        "binary": str(resolved) if resolved else None,
        "requires": ["disk_only_indexed_search", "tgrep_binary"],
        "serve": False,
        "index": f".atlas-index/{INDEX_NAME}",
        "reason": "ok" if present else "tgrep binary not on PATH",
    }


def index_dir(store: Path) -> Path:
    return store / ".atlas-index" / INDEX_NAME


def _rel(store: Path, raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(store.resolve()).as_posix()
        except ValueError:
            return None
    return path.as_posix().lstrip("./")


def _guard_args(args: Iterable[str]) -> list[str]:
    out = [str(a) for a in args]
    for token in out:
        if token in FORBIDDEN_TOKENS or Path(token).name == "serve":
            if token == "--no-index":
                raise TgrepError(NO_INDEX_FORBIDDEN)
            raise TgrepError(SERVE_FORBIDDEN)
    return out


def run_argv(
    binary: Path,
    args: list[str],
    *,
    cwd: Path,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    argv = _guard_args(args)
    return subprocess.run(
        [str(binary), *argv],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=os.environ.copy(),
    )


def _detect_serve(store: Path, dest: Path) -> None:
    for path in (store / ".tgrep" / "serve.json", dest / "serve.json"):
        if path.is_file():
            raise TgrepError(SERVE_DETECTED)


def _excludes(schema: dict[str, Any] | None) -> list[str]:
    skip = set(SKIP_TOP) | {staging_dir_name(schema), ".git"}
    args: list[str] = []
    for name in sorted(skip):
        args.extend(["--exclude", name])
    return args


def _load_digest(dest: Path) -> str | None:
    meta = dest / DIGEST_NAME
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("complete"):
        return None
    digest = data.get("corpus_digest")
    return str(digest) if digest else None


def ensure_index(
    store: Path,
    digest: str,
    *,
    schema: dict[str, Any] | None = None,
    binary: Path | None = None,
    runner: Runner | None = None,
) -> tuple[Path, bool]:
    dest = index_dir(store)
    _detect_serve(store, dest)
    if _load_digest(dest) == digest:
        return dest, False
    resolved = binary or find_binary()
    if resolved is None:
        raise TgrepError(MISSING)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    args = ["index", str(store), "--index-path", str(dest), "--hidden", "--no-ignore", *_excludes(schema)]
    try:
        proc = (runner or run_argv)(resolved, args, cwd=store, timeout=INDEX_TIMEOUT_SEC)
    except subprocess.TimeoutExpired as e:
        raise TgrepError(TIMEOUT) from e
    if proc.returncode != 0:
        raise TgrepError(f"tgrep_index_failed: {(proc.stderr or proc.stdout or '')[:240]}")
    _detect_serve(store, dest)
    (dest / DIGEST_NAME).write_text(
        json.dumps({"corpus_digest": digest, "complete": True}, indent=2) + "\n",
        encoding="utf-8",
    )
    return dest, True


def _parse_hits(stdout: str, store: Path, admitted: set[str]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    snippets: dict[str, str] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "match":
            continue
        data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
        raw_path = data.get("path")
        if isinstance(raw_path, dict):
            raw_path = raw_path.get("text") or raw_path.get("path")
        rel = _rel(store, str(raw_path or ""))
        if not rel or rel not in admitted:
            continue
        counts[rel] = counts.get(rel, 0) + 1
        if rel not in snippets:
            lines = data.get("lines") if isinstance(data.get("lines"), dict) else {}
            snippets[rel] = str(lines.get("text") or "").replace("\n", " ").strip()[:160]
    hits = [
        {
            "path": path,
            "score": float(count),
            "score_orientation": "higher_better",
            "snippet": snippets.get(path, ""),
            "driver": "tgrep",
            "terms": [],
        }
        for path, count in counts.items()
    ]
    hits.sort(key=lambda h: (-h["score"], h["path"]))
    return hits


def search(
    store: Path,
    pages: list[ProjectedPage],
    query: str,
    limit: int,
    digest: str,
    *,
    schema: dict[str, Any] | None = None,
    binary: Path | None = None,
    runner: Runner | None = None,
    finder: Callable[[], Path | None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    resolved = binary if binary is not None else (finder or find_binary)()
    if resolved is None:
        raise TgrepError(MISSING)
    dest, rebuilt = ensure_index(
        store, digest, schema=schema, binary=resolved, runner=runner
    )
    tokens = tokenise(query)
    if not tokens:
        return [], {
            "rebuilt": rebuilt,
            "index": str(dest.relative_to(store)),
            "binary": str(resolved),
            "ephemeral": rebuilt,
        }
    pattern = "|".join(re.escape(t) for t in tokens)
    admitted = {p.path for p in pages if p.role != "log"}
    args = [
        "--json",
        "-i",
        "--hidden",
        "--no-ignore",
        "--index-path",
        str(dest),
        "--",
        pattern,
        str(store),
    ]
    try:
        proc = (runner or run_argv)(resolved, args, cwd=store, timeout=SEARCH_TIMEOUT_SEC)
    except subprocess.TimeoutExpired as e:
        raise TgrepError(TIMEOUT) from e
    if proc.returncode not in (0, 1):
        raise TgrepError(f"tgrep_search_failed: {(proc.stderr or proc.stdout or '')[:240]}")
    hits = _parse_hits(proc.stdout or "", store, admitted)
    if limit:
        hits = hits[:limit]
    return hits, {
        "rebuilt": rebuilt,
        "index": str(dest.relative_to(store)),
        "binary": str(resolved),
        "ephemeral": rebuilt,
    }
