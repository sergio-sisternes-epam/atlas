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
    parts: list[str] = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise RefError(f"path escapes store root: {raw}")
        parts.append(part)
    if not parts:
        raise RefError(f"path escapes store root: {raw}")
    cursor = root
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RefError(f"refusing to follow symlink {raw}")
    lexical = "/".join(parts)
    cand = (root / lexical).resolve(strict=False)
    try:
        rel = cand.relative_to(root.resolve())
    except ValueError as e:
        raise RefError(f"path escapes store root: {raw}") from e
    if not rel.parts or rel.as_posix() != lexical:
        raise RefError(f"refusing to follow symlink {raw}")
    return lexical


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
            rewritten.append(f"{match.group(1)}path: {_yaml_scalar(summary)}")
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


def _balanced_flow(text: str) -> bool:
    square = curly = 0
    quote = None
    escaped = False
    for ch in text:
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch == "[":
            square += 1
        elif ch == "]":
            square -= 1
        elif ch == "{":
            curly += 1
        elif ch == "}":
            curly -= 1
        if square < 0 or curly < 0:
            return False
    return square == 0 and curly == 0 and quote is None


def _yaml_scalar(value: str) -> str:
    if not value or value.strip() != value or any(ch in value for ch in ":#{}[]&*!|>%@`,\"'"):
        return json.dumps(value)
    return value


def _parse_relation_value(blob: str) -> list[dict[str, str]]:
    try:
        import yaml
    except ImportError as e:
        raise RefError("PyYAML is required to parse inline relates_to") from e
    try:
        value = yaml.safe_load(blob)
    except yaml.YAMLError as e:
        raise RefError(f"cannot parse relates_to: {e}") from e
    if value is None:
        value = []
    if not isinstance(value, list):
        raise RefError("relates_to must be a list")
    parsed: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise RefError("relates_to item must be a mapping")
        clean: dict[str, str] = {}
        for key, field in item.items():
            if not isinstance(key, str) or not isinstance(field, str):
                raise RefError("relates_to fields must be strings")
            clean[key] = field
        parsed.append(clean)
    return parsed


def _emit_relates_block(items: list[dict[str, str]]) -> list[str]:
    if not items:
        return ["relates_to: []"]
    lines = ["relates_to:"]
    for item in items:
        first = True
        for key, value in item.items():
            scalar = _yaml_scalar(value)
            lines.append(f"  - {key}: {scalar}" if first else f"    {key}: {scalar}")
            first = False
    return lines


def _expand_flow_relates(text: str, drop: set[str] | None = None, *, force: bool = False) -> tuple[str, bool]:
    """Turn a flow-style relates_to list into the block form the rewriter edits."""
    if not text.startswith("---"):
        return text, False
    end = text.find("\n---", 3)
    if end == -1:
        return text, False
    nl = _newline(text)
    lines = text[3:end].strip("\n").splitlines()
    out: list[str] = []
    index = 0
    changed = False
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^relates_to:\s*(\S.*)$", line)
        if not match:
            out.append(line)
            index += 1
            continue
        raw_lines = [line]
        value_lines = [match.group(1)]
        index += 1
        while not _balanced_flow("\n".join(value_lines)) and index < len(lines) and not TOP_KEY.match(lines[index]):
            raw_lines.append(lines[index])
            value_lines.append(lines[index])
            index += 1
        blob = "\n".join(value_lines).strip()
        if not _balanced_flow(blob):
            raise RefError("unclosed relates_to value")
        parsed = _parse_relation_value(blob)
        names_drop = drop is not None and any(_norm_path(item.get("path", "")) in drop for item in parsed)
        if not force and not names_drop:
            out.extend(raw_lines)
            continue
        out.extend(_emit_relates_block(parsed))
        changed = True
    if not changed:
        return text, False
    return f"---{nl}{nl.join(out)}{text[end:]}", True


def rewrite_relates_to(text: str, drop: set[str], summary: str, on_summary: bool) -> tuple[str, int]:
    text, expanded = _expand_flow_relates(text, drop, force=on_summary)
    if not text.startswith("---"):
        return text, int(expanded)
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
    return f"---{nl}{joined}{body}", changed + int(expanded)


def _existing_ref_edges(text: str) -> set[tuple[str, str, str]]:
    if not text.startswith("---"):
        return set()
    end = text.find("\n---", 3)
    if end == -1:
        return set()
    found: set[tuple[str, str, str]] = set()
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
            ref = _item_field(item, "ref")
            if path and ref:
                found.add((path, _item_field(item, "kind"), ref))
    return found


def append_ref_edges(text: str, edges: list[tuple[str, str, str]]) -> str:
    text, _expanded = _expand_flow_relates(text, force=True)
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
                f"  - path: {_yaml_scalar(path)}",
                f"    kind: {_yaml_scalar(kind)}",
                f"    ref: {_yaml_scalar(ref)}",
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
            if not name.endswith(".md"):
                continue
            page = current / name
            if page.is_symlink():
                continue
            try:
                page.resolve().relative_to(root.resolve())
            except ValueError:
                continue
            found.append(page)
    return sorted(found)


def _managed_top(store: Path, rel: str) -> str | None:
    schema, _ = load_schema(store)
    top = rel.split("/", 1)[0]
    if top in SKIP_TOP or top == staging_dir_name(schema):
        return top
    return None


def _require_summary_page(store: Path, rel: str, path: Path) -> None:
    if _managed_top(store, rel):
        raise RefError(f"refusing Atlas-managed path {rel}")
    walked = {page.relative_to(store).as_posix() for page in _iter_pages(store)}
    if rel not in walked or not path.is_file():
        raise RefError(f"summary is not an eligible tip page: {rel}")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---") or text.find("\n---", 3) == -1:
        raise RefError("summary page has no frontmatter")


def _drop_not_file(store: Path, rel: str) -> str | None:
    target = store / rel
    if target.is_symlink() or (target.exists() and not target.is_file()):
        return f"refusing to delete non-file {rel}"
    return None


def _worktree_warning(repo: Path, root: Path, store_rel: str, sha: str, gitpath: str) -> str | None:
    path = root / store_rel
    if not path.is_file():
        return f"{store_rel} is absent on tip; history blob is kept at {sha}"
    code, out, _ = run_git(["hash-object", "--", str(path)], cwd=repo)
    blob_code, blob, _ = run_git(["rev-parse", "--verify", "--end-of-options", f"{sha}:{gitpath}"], cwd=repo)
    if code != 0 or blob_code != 0 or not blob or out != blob:
        raise RefError(f"refusing to drop dirty {store_rel}; commit it before prune or choose a rev that matches the worktree")
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
        _require_summary_page(store, summary_rel, summary_path)
        drop_rels = [_store_rel(store, item) for item in drops]
        for rel in drop_rels:
            managed = _managed_top(store, rel)
            if managed:
                raise RefError(f"refusing Atlas-managed path {rel}")
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
        for rel in drop_rels:
            problem = _drop_not_file(store, rel)
            if problem:
                raise RefError(problem)
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
                have = _existing_ref_edges(updated)
                edges = [
                    (item, kind, sha)
                    for item in drop_rels
                    if (item, kind, sha) not in have
                ]
                updated = append_ref_edges(updated, edges)
            if updated != original:
                pending.append((page, updated))
        snapshots = [(page, page.read_text(encoding="utf-8")) for page, _ in pending]
        removed: list[tuple[Path, bytes]] = []
        try:
            for page, updated in pending:
                page.write_text(updated, encoding="utf-8")
            for rel in drop_rels:
                problem = _drop_not_file(store, rel)
                if problem:
                    raise RefError(problem)
                target = store / rel
                if target.is_file():
                    removed.append((target, target.read_bytes()))
                    target.unlink()
        except Exception:
            for page, original in snapshots:
                page.write_text(original, encoding="utf-8")
            for target, data in removed:
                target.write_bytes(data)
            raise
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
