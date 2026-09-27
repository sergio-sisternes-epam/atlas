"""Relation ref: deliberate git recall and tip prune. Not mount ref."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from ..core.gitops import git_root, run_git
from ..core.paths import store_root
from ..core.schema import load_schema, staging_dir_name

SKIP_TOP = frozenset({"templates", ".atlas-index", "mesh", "schema.d", ".git"})
MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
TOP_KEY = re.compile(r"^[A-Za-z_][\w-]*:")
ITEM_START = re.compile(r"^\s*-\s+")
FIELD = re.compile(r"^(\s*(?:-\s*)?)([A-Za-z_][\w-]*):\s*(.*?)\s*$")


class RefError(ValueError):
    pass


def _reject_rev(rev: str) -> None:
    if (
        not rev
        or rev.strip() != rev
        or any(ch.isspace() for ch in rev)
        or rev.startswith("-")
        or ".." in rev
    ):
        raise RefError("ref must be a git rev without whitespace")


def _store_rel(root: Path, raw: str) -> str:
    text = raw.strip().replace("\\", "/")
    if not text or text.startswith(("/", "-")) or text.startswith(("http://", "https://", "atlas://")):
        raise RefError(f"path escapes store root: {raw}")
    cand = (root / text).resolve(strict=False)
    try:
        rel = cand.relative_to(root.resolve())
    except ValueError as e:
        raise RefError(f"path escapes store root: {raw}") from e
    if not rel.parts or any(part == ".." for part in rel.parts):
        raise RefError(f"path escapes store root: {raw}")
    return rel.as_posix()


def _repo(root: Path) -> Path:
    repo = git_root(root)
    if repo is None:
        raise RefError("no git repository contains the store root")
    try:
        root.resolve().relative_to(repo.resolve())
    except ValueError as e:
        raise RefError("store root is not inside its git repository") from e
    return repo


def _git_path(root: Path, repo: Path, store_rel: str) -> str:
    prefix = root.resolve().relative_to(repo.resolve())
    return (prefix / store_rel).as_posix()


def _resolve_commit(repo: Path, rev: str) -> str:
    _reject_rev(rev)
    code, out, err = run_git(
        ["rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}"],
        cwd=repo,
    )
    if code != 0 or not out:
        raise RefError(err or f"rev does not resolve in the store repo: {rev}")
    return out


def _blob_exists(repo: Path, sha: str, gitpath: str) -> bool:
    code, _, _ = run_git(["cat-file", "-e", f"{sha}:{gitpath}"], cwd=repo)
    return code == 0


def _show_bytes(repo: Path, sha: str, gitpath: str) -> bytes:
    proc = subprocess.run(
        ["git", "show", "--end-of-options", f"{sha}:{gitpath}"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RefError(err or f"missing blob {gitpath} at {sha}")
    return proc.stdout


def _fail(as_json: bool, message: str) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": message}))
    else:
        print(f"atlas ref: {message}", file=sys.stderr)
    return 2


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _norm_path(value: str) -> str:
    text = _unquote(value).replace("\\", "/")
    parts: list[str] = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return text
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _item_field(lines: list[str], key: str) -> str | None:
    for line in lines:
        match = FIELD.match(line)
        if match and match.group(2) == key:
            return _norm_path(match.group(3))
    return None


def _has_field(lines: list[str], key: str) -> bool:
    return any(FIELD.match(line) and FIELD.match(line).group(2) == key for line in lines)


def _rewrite_item(lines: list[str], drop: set[str], summary: str, on_summary: bool) -> tuple[list[str] | None, bool]:
    path = _item_field(lines, "path")
    if path is None or path not in drop or _has_field(lines, "ref"):
        return lines, False
    if on_summary:
        return None, True
    rewritten: list[str] = []
    for line in lines:
        match = FIELD.match(line)
        if match and match.group(2) == "path":
            rewritten.append(f"{match.group(1)}path: {summary}")
            continue
        if match and match.group(2) == "ref":
            continue
        rewritten.append(line)
    return rewritten, True


def _rewrite_section(lines: list[str], drop: set[str], summary: str, on_summary: bool) -> tuple[list[str], int]:
    preamble: list[str] = []
    items: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if ITEM_START.match(line):
            if current is not None:
                items.append(current)
            current = [line]
            continue
        if current is not None:
            current.append(line)
        else:
            preamble.append(line)
    if current is not None:
        items.append(current)
    out = list(preamble)
    changed = 0
    for item in items:
        rewritten, did = _rewrite_item(item, drop, summary, on_summary)
        changed += int(did)
        if rewritten:
            out.extend(rewritten)
    return out, changed


def rewrite_relates_to(text: str, drop: set[str], summary: str, on_summary: bool) -> tuple[str, int]:
    if not text.startswith("---"):
        return text, 0
    end = text.find("\n---", 3)
    if end == -1:
        return text, 0
    nl = _newline(text)
    block = text[3:end].strip("\n")
    lines = block.splitlines()
    out: list[str] = []
    changed = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() == "relates_to: []" or re.match(r"^relates_to:\s*$", line):
            out.append(line)
            index += 1
            section: list[str] = []
            while index < len(lines) and not TOP_KEY.match(lines[index]):
                section.append(lines[index])
                index += 1
            rewritten, count = _rewrite_section(section, drop, summary, on_summary)
            changed += count
            out.extend(rewritten)
            continue
        out.append(line)
        index += 1
    body = text[end:]
    joined = nl.join(out)
    return f"---{nl}{joined}{body}", changed


def _existing_ref_paths(text: str) -> set[str]:
    if not text.startswith("---"):
        return set()
    end = text.find("\n---", 3)
    if end == -1:
        return set()
    found: set[str] = set()
    current: list[str] | None = None
    items: list[list[str]] = []
    for line in text[3:end].splitlines():
        if ITEM_START.match(line):
            if current is not None:
                items.append(current)
            current = [line]
        elif current is not None and line.startswith((" ", "\t")):
            current.append(line)
    if current is not None:
        items.append(current)
    for item in items:
        if _has_field(item, "ref"):
            path = _item_field(item, "path")
            if path:
                found.add(path)
    return found


def append_ref_edges(text: str, edges: list[tuple[str, str, str]]) -> str:
    if not edges:
        return text
    if not text.startswith("---"):
        raise RefError("summary page has no frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise RefError("summary page has no closing frontmatter")
    nl = _newline(text)
    block = text[3:end].strip("\n")
    lines = block.splitlines()
    addition = []
    for path, kind, ref in edges:
        addition.extend(
            [
                f"  - path: {path}",
                f"    kind: {kind}",
                f"    ref: {ref}",
            ]
        )
    inserted = False
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() == "relates_to: []":
            out.append("relates_to:")
            out.extend(addition)
            inserted = True
            index += 1
            continue
        if re.match(r"^relates_to:\s*$", line):
            out.append(line)
            index += 1
            while index < len(lines) and not TOP_KEY.match(lines[index]):
                out.append(lines[index])
                index += 1
            out.extend(addition)
            inserted = True
            continue
        out.append(line)
        index += 1
    if not inserted:
        if out and out[-1].strip():
            out.append("relates_to:")
        else:
            out.append("relates_to:")
        out.extend(addition)
    body = text[end:]
    return f"---{nl}{nl.join(out)}{body}"


def _link_hits_drop(root: Path, page: Path, token: str, drop: set[str]) -> bool:
    if not token or token.startswith(("http://", "https://", "mailto:", "atlas://", "#")):
        return False
    parent_path = page.parent / token
    try:
        parent_rel = parent_path.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except ValueError:
        parent_rel = ""
    if parent_path.exists():
        return parent_rel in drop
    root_path = root / token.lstrip("/")
    try:
        root_rel = root_path.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except ValueError:
        return False
    return root_rel in drop


def rewrite_markdown_links(text: str, root: Path, page: Path, drop: set[str], summary_abs: Path) -> tuple[str, int]:
    changed = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        raw = match.group(2)
        token = raw.split()[0].strip("\"'") if raw.strip() else ""
        if not _link_hits_drop(root, page, token, drop):
            return match.group(0)
        href = Path(os.path.relpath(summary_abs, page.parent)).as_posix()
        changed += 1
        return f"[{match.group(1)}]({raw.replace(token, href, 1)})"

    return MD_LINK.sub(repl, text), changed


def _iter_pages(root: Path) -> list[Path]:
    schema, _ = load_schema(root)
    skip = set(SKIP_TOP) | {staging_dir_name(schema)}
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        try:
            parts = current.resolve().relative_to(root.resolve()).parts
        except ValueError:
            dirnames[:] = []
            continue
        if parts and parts[0] in skip:
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if name not in skip]
        for name in filenames:
            if name.endswith(".md"):
                found.append(current / name)
    return sorted(found)


def _worktree_warning(repo: Path, root: Path, store_rel: str, sha: str, gitpath: str) -> str | None:
    path = root / store_rel
    if not path.is_file():
        return f"{store_rel} is absent on tip; history blob is kept at {sha}"
    code, out, _ = run_git(["hash-object", "--", str(path)], cwd=repo)
    blob, _, _ = run_git(["rev-parse", "--verify", "--end-of-options", f"{sha}:{gitpath}"], cwd=repo)
    if code != 0 or not blob or out != blob:
        return f"{store_rel} differs from {sha}"
    return None


def run_show(root: str | None, path: str, rev: str, as_json: bool) -> int:
    try:
        store = store_root(root)
        rel = _store_rel(store, path)
        repo = _repo(store)
        sha = _resolve_commit(repo, rev)
        gitpath = _git_path(store, repo, rel)
        if not _blob_exists(repo, sha, gitpath):
            raise RefError(f"missing blob {rel} at {sha}")
        payload = _show_bytes(repo, sha, gitpath)
    except RefError as e:
        return _fail(as_json, str(e))
    if as_json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "path": rel,
                    "ref": sha,
                    "content": payload.decode("utf-8", errors="replace"),
                }
            )
        )
        return 0
    sys.stdout.buffer.write(payload)
    return 0


def run_prune(
    root: str | None,
    summary: str,
    drops: tuple[str, ...],
    rev: str,
    kind: str,
    as_json: bool,
) -> int:
    try:
        if not kind or kind.strip() != kind or any(ch.isspace() for ch in kind) or kind.startswith("-"):
            raise RefError("kind is required and must not contain whitespace")
        if not drops:
            raise RefError("at least one --drop path is required")
        store = store_root(root)
        summary_rel = _store_rel(store, summary)
        summary_path = store / summary_rel
        if not summary_path.is_file():
            raise RefError(f"summary is not a tip page: {summary_rel}")
        drop_rels = [_store_rel(store, item) for item in drops]
        if summary_rel in drop_rels:
            raise RefError("refusing to drop the summary")
        if len(set(drop_rels)) != len(drop_rels):
            raise RefError("duplicate --drop path")
        repo = _repo(store)
        sha = _resolve_commit(repo, rev)
        warnings: list[str] = []
        for rel in drop_rels:
            gitpath = _git_path(store, repo, rel)
            if not _blob_exists(repo, sha, gitpath):
                raise RefError(f"ref {sha} does not contain {rel}")
            warning = _worktree_warning(repo, store, rel, sha, gitpath)
            if warning:
                warnings.append(warning)
        drop_set = set(drop_rels)
        rewritten: list[str] = []
        pending: list[tuple[Path, str]] = []
        for page in _iter_pages(store):
            rel = _store_rel(store, page.relative_to(store).as_posix())
            if rel in drop_set:
                continue
            original = page.read_text(encoding="utf-8")
            updated, fm_changes = rewrite_relates_to(
                original,
                drop_set,
                summary_rel,
                on_summary=rel == summary_rel,
            )
            updated, link_changes = rewrite_markdown_links(
                updated,
                store,
                page,
                drop_set,
                summary_path,
            )
            if fm_changes or link_changes:
                rewritten.append(rel)
            if rel == summary_rel:
                have = _existing_ref_paths(updated)
                edges = [
                    (item, kind, sha) for item in drop_rels if item not in have
                ]
                updated = append_ref_edges(updated, edges)
            if updated != original:
                pending.append((page, updated))
        for page, updated in pending:
            page.write_text(updated, encoding="utf-8")
        for rel in drop_rels:
            target = store / rel
            if target.is_file():
                target.unlink()
            elif target.exists():
                raise RefError(f"refusing to delete non-file {rel}")
    except RefError as e:
        return _fail(as_json, str(e))
    if as_json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "summary": summary_rel,
                    "ref": sha,
                    "kind": kind,
                    "dropped": drop_rels,
                    "rewritten": rewritten,
                    "warnings": warnings,
                }
            )
        )
    else:
        for warning in warnings:
            print(f"atlas ref prune: warning: {warning}", file=sys.stderr)
        print(f"pruned {len(drop_rels)} page(s) onto {summary_rel} at {sha}")
    return 0
