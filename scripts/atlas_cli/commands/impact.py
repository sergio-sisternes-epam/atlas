"""Read-only review data for changes between two local Git commits."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..core.identity import IdentityError, parse_pointer
from ..core.paths import store_root
from . import link


class ImpactError(ValueError):
    pass


def _git(repo: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1"},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
    except OSError as exc:
        raise ImpactError(f"cannot run git: {exc}") from exc
    if result.returncode:
        raise ImpactError(result.stderr.decode("utf-8", errors="replace").strip() or "git failed")
    return result.stdout


def _commit(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode().strip()


def _identity(repo: Path, atlas_id: str | None) -> str:
    if atlas_id is None:
        try:
            atlas_id = _git(repo, "remote", "get-url", "origin").decode().strip()
        except ImpactError as exc:
            raise ImpactError("store identity unavailable; provide --atlas-id") from exc
    try:
        parsed = parse_pointer(atlas_id)
    except IdentityError as exc:
        raise ImpactError(f"invalid store identity: {exc}") from exc
    if parsed.in_store or parsed.commit or parsed.fragment:
        raise ImpactError("--atlas-id must identify a store, not a page")
    return parsed.atlas_id


def _stat(repo: Path, since: str, until: str, paths: list[str]) -> dict[str, int | None]:
    fields = _git(repo, "diff", "--numstat", "-z", "--no-ext-diff", "--no-textconv",
                  "--find-renames", since, until, "--",
                  *(f":(literal){path}" for path in paths)).split(b"\0")
    additions = deletions = 0
    index = 0
    while index < len(fields) and fields[index]:
        parts = fields[index].split(b"\t", 2)
        if len(parts) != 3:
            raise ImpactError("cannot parse Git diff stat")
        if parts[0] == b"-" or parts[1] == b"-":
            return {"insertions": None, "deletions": None}
        try:
            additions += int(parts[0])
            deletions += int(parts[1])
        except ValueError as exc:
            raise ImpactError("cannot parse Git diff stat") from exc
        index += 3 if not parts[2] else 1
    return {"insertions": additions, "deletions": deletions}


def _changes(repo: Path, prefix: str, since: str, until: str) -> list[dict[str, Any]]:
    data = _git(repo, "diff", "--raw", "-z", "--no-abbrev", "--no-ext-diff",
                "--no-textconv", "--find-renames", since, until).split(b"\0")
    changes: list[dict[str, Any]] = []
    i = 0
    while i < len(data) and data[i]:
        header = data[i].decode("ascii").split()
        if len(header) != 5 or not header[0].startswith(":"):
            raise ImpactError("cannot parse Git diff")
        kind = header[4][0]
        old_path = os.fsdecode(data[i + 1])
        new_path = os.fsdecode(data[i + 2]) if kind in {"R", "C"} else old_path
        i += 3 if kind in {"R", "C"} else 2
        old_in = old_path.startswith(prefix) and old_path.endswith(".md")
        new_in = new_path.startswith(prefix) and new_path.endswith(".md")
        if not old_in and not new_in:
            continue
        if kind in {"R", "C"} and old_in != new_in:
            kind = "D" if old_in else "A"
        path = (new_path if new_in and kind != "D" else old_path)[len(prefix):]
        old_blob = header[2] if kind != "A" else None
        new_blob = header[3] if kind != "D" else None
        changes.append({
            "path": path, "kind": kind,
            "old_path": old_path[len(prefix):] if old_in and kind in {"R", "C"} else None,
            "old_blob": old_blob, "new_blob": new_blob,
            "diff_stat": _stat(repo, since, until, list(dict.fromkeys([old_path, new_path]))),
            "pins": [],
        })
    return changes


def _citations(repo: Path, prefix: str, until: str, atlas_id: str) -> list[tuple[str, str, str]]:
    entries = _git(repo, "ls-tree", "-rz", "--full-tree", until, "--",
                   f":(literal){prefix.rstrip('/')}" if prefix else ".").split(b"\0")
    citations: list[tuple[str, str, str]] = []
    for entry in entries:
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        path = os.fsdecode(raw_path)
        if mode not in {"100644", "100755"} or kind != "blob" or not path.startswith(prefix) or not path.endswith(".md"):
            continue
        text = _git(repo, "cat-file", "blob", oid).decode("utf-8", errors="strict")
        for match in re.finditer(r"atlas://[^\s)\]\"']+", text):
            uri = match.group().rstrip(".,;`'\"")
            try:
                pointer = parse_pointer(uri)
            except IdentityError:
                continue
            if pointer.commit and pointer.atlas_id == atlas_id:
                citations.append((path[len(prefix):], pointer.in_store, uri))
    return citations


def run(root: str | None, since: str, until: str, atlas_id: str | None, as_json: bool) -> int:
    store = store_root(root)
    try:
        location = link._repo_and_store_path(store)
        if location is None or not store.is_dir():
            raise ImpactError("store is not in a local Git repository")
        repo, prefix = location
        identity = _identity(repo, atlas_id)
        first, last = _commit(repo, since), _commit(repo, until)
        changes = _changes(repo, prefix, first, last)
        citations = _citations(repo, prefix, last, identity)
        inspected: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for change in changes:
            paths = {path for path in (change["path"], change["old_path"]) if path is not None}
            for source, cited_path, uri in citations:
                if source in paths:
                    continue
                if uri not in inspected:
                    inspected[uri] = (
                        link.inspect(uri, str(store), target=(store, first)),
                        link.inspect(uri, str(store), target=(store, last)),
                    )
                previous, current = inspected[uri]
                if cited_path in paths or previous.get("tip_path") in paths:
                    change["pins"].append({"source": source, **current})
        payload = {"ok": True, "atlas_id": identity, "since": first, "until": last, "changes": changes}
    except (ImpactError, OSError, UnicodeError) as exc:
        if as_json:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"atlas link impact: {exc}", file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Changes {first}..{last} ({identity}):")
        for change in changes:
            stat = change["diff_stat"]
            print(f"{change['kind']} {change['path']} old={change['old_blob']} new={change['new_blob']} "
                  f"+{stat['insertions']} -{stat['deletions']}")
            if change["old_path"]:
                print(f"  from {change['old_path']}")
            for pin in change["pins"]:
                print(f"  {pin['source']}: {pin['status']} {pin['uri']}")
    return 0
