"""Relation ref: deliberate git recall and tip prune. Not mount ref."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from ..core.gitops import git_root, run_git
from ..core.overlay import merge_overlays
from .validate import concept_page_errors
from ..core.paths import RESERVED, store_root
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
    code, out, _ = run_git(["cat-file", "-t", f"{sha}:{gitpath}"], cwd=repo)
    return code == 0 and out == "blob"


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


def _yaml_scalar_text(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if text[0] in ("'", '"'):
        quote = text[0]
        out: list[str] = []
        escaped = False
        for ch in text[1:]:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\" and quote == '"':
                escaped = True
                continue
            if ch == quote:
                return "".join(out)
        return text
    comment = re.search(r"\s+#", text)
    if comment:
        text = text[: comment.start()]
    return text.strip()


def _unquote(value: str) -> str:
    return _yaml_scalar_text(value)


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


def _parse_relation_item(blob: str) -> dict[str, str]:
    wrapped = blob.strip()
    if not wrapped.startswith("["):
        wrapped = f"[{wrapped}]"
    items = _parse_relation_value(wrapped)
    if len(items) != 1:
        raise RefError("relates_to item must be one mapping")
    return items[0]


def _emit_relation_item(item: dict[str, str], indent: str = "  ") -> list[str]:
    lines: list[str] = []
    first = True
    for key, value in item.items():
        scalar = _yaml_scalar(value)
        lines.append(f"{indent}- {key}: {scalar}" if first else f"{indent}  {key}: {scalar}")
        first = False
    return lines


def _expand_flow_map_items(text: str, drop: set[str] | None = None, *, force: bool = False) -> tuple[str, bool]:
    """Turn ` - {path, kind}` items inside a block relates_to into field lines."""
    if not text.startswith("---"):
        return text, False
    end = text.find("\n---", 3)
    if end == -1:
        return text, False
    nl = _newline(text)
    lines = text[3:end].strip("\n").splitlines()
    out: list[str] = []
    index = 0
    in_relates = False
    changed = False
    while index < len(lines):
        line = lines[index]
        if TOP_KEY.match(line):
            in_relates = bool(re.match(r"^relates_to:\s*$", line))
            out.append(line)
            index += 1
            continue
        if not in_relates or not re.match(r"^\s*-\s*\{", line):
            out.append(line)
            index += 1
            continue
        indent = re.match(r"^(\s*)", line).group(1)
        raw_lines = [line]
        blob = line.split("-", 1)[1]
        index += 1
        while not _balanced_flow(blob) and index < len(lines) and not TOP_KEY.match(lines[index]):
            raw_lines.append(lines[index])
            blob += "\n" + lines[index]
            index += 1
        if not _balanced_flow(blob):
            raise RefError("unclosed relates_to item")
        parsed = _parse_relation_item(blob)
        names_drop = drop is not None and _norm_path(parsed.get("path", "")) in drop
        if not force and not names_drop:
            out.extend(raw_lines)
            continue
        out.extend(_emit_relation_item(parsed, indent or "  "))
        changed = True
    if not changed:
        return text, False
    return f"---{nl}{nl.join(out)}{text[end:]}", True


def rewrite_relates_to(text: str, drop: set[str], summary: str, on_summary: bool) -> tuple[str, int]:
    text, expanded = _expand_flow_relates(text, drop, force=on_summary)
    text, map_expanded = _expand_flow_map_items(text, drop, force=on_summary)
    if not text.startswith("---"):
        return text, int(expanded) + int(map_expanded)
    end = text.find("\n---", 3)
    if end == -1:
        return text, int(expanded) + int(map_expanded)
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
    return f"---{nl}{joined}{body}", changed + int(expanded) + int(map_expanded)


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
    text, _map_expanded = _expand_flow_map_items(text, force=True)
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


def _url_path(token: str) -> tuple[str, str]:
    cut = len(token)
    for sep in ("#", "?"):
        idx = token.find(sep)
        if idx != -1:
            cut = min(cut, idx)
    return token[:cut], token[cut:]


def _link_hits_drop(root: Path, page: Path, token: str, drop: set[str]) -> bool:
    token, _suffix = _url_path(token)
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
        _path_token, suffix = _url_path(token)
        href = Path(os.path.relpath(summary_abs, page.parent)).as_posix() + suffix
        changed += 1
        return f"[{match.group(1)}]({raw.replace(token, href, 1)})"

    return MD_LINK.sub(repl, text), changed


def _open_store_parent(root: Path, rel: str) -> tuple[int, str]:
    """Open the parent of a store-relative path without following any component."""
    parts = [part for part in rel.split("/") if part]
    if not parts or any(part in (".", "..") for part in parts):
        raise RefError(f"path escapes store root: {rel}")
    dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            try:
                nextfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dirfd)
            except OSError as e:
                raise RefError(f"refusing to follow symlink {rel}") from e
            os.close(dirfd)
            dirfd = nextfd
        return dirfd, parts[-1]
    except Exception:
        os.close(dirfd)
        raise


def _read_dir_file(dirfd: int, name: str, label: str) -> bytes:
    try:
        info = os.lstat(name, dir_fd=dirfd)
    except OSError as e:
        raise RefError(f"refusing to read missing page {label}") from e
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RefError(f"refusing to read non-regular page {label}")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dirfd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise RefError(f"refusing to read non-regular page {label}")
        os.set_blocking(fd, True)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _read_store(root: Path, rel: str) -> bytes:
    dirfd, name = _open_store_parent(root, rel)
    try:
        return _read_dir_file(dirfd, name, rel)
    finally:
        os.close(dirfd)


def _rewrite_dir_file(dirfd: int, name: str, data: bytes, label: str, *, must_exist: bool) -> None:
    if must_exist:
        try:
            info = os.lstat(name, dir_fd=dirfd)
        except OSError as e:
            raise RefError(f"refusing to rewrite missing page {label}") from e
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise RefError(f"refusing to rewrite non-regular page {label}")
        if info.st_nlink > 1:
            raise RefError(f"refusing to rewrite hard-linked page {label}")
    tmp = f".atlas-prune-{os.getpid()}-{abs(hash(label)) & 0xFFFFFFF:x}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dirfd)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        if must_exist:
            info = os.lstat(name, dir_fd=dirfd)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise RefError(f"refusing to rewrite non-regular page {label}")
            if info.st_nlink > 1:
                raise RefError(f"refusing to rewrite hard-linked page {label}")
        os.rename(tmp, name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
        tmp = ""
    finally:
        if tmp:
            try:
                os.unlink(tmp, dir_fd=dirfd)
            except OSError:
                pass


def _rewrite_store(root: Path, rel: str, data: bytes, *, must_exist: bool = True) -> None:
    dirfd, name = _open_store_parent(root, rel)
    try:
        _rewrite_dir_file(dirfd, name, data, rel, must_exist=must_exist)
    finally:
        os.close(dirfd)


def _unlink_store(root: Path, rel: str) -> bytes | None:
    dirfd, name = _open_store_parent(root, rel)
    try:
        try:
            info = os.lstat(name, dir_fd=dirfd)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise RefError(f"refusing to delete non-file {rel}")
        data = _read_dir_file(dirfd, name, rel)
        os.unlink(name, dir_fd=dirfd)
        return data
    finally:
        os.close(dirfd)


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
            try:
                info = page.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            rel = page.relative_to(root).as_posix()
            try:
                dirfd, _name = _open_store_parent(root, rel)
            except (RefError, OSError):
                continue
            os.close(dirfd)
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
    if Path(rel).name in RESERVED:
        raise RefError(f"summary is not an eligible tip page: {rel}")
    walked = {page.relative_to(store).as_posix() for page in _iter_pages(store)}
    if rel not in walked or not path.is_file():
        raise RefError(f"summary is not an eligible tip page: {rel}")
    problems = concept_page_errors(store, path)
    if problems:
        raise RefError(f"summary would fail compile: {problems[0]}")
    _require_summary_index(store, rel)


def _require_summary_index(store: Path, rel: str) -> None:
    schema, err = load_schema(store)
    if err or not schema:
        return
    merged, _, _ = merge_overlays(schema, store)
    structure = merged.get("structure") or {}
    if not bool(structure.get("require_index_in_folders", True)):
        return
    parent = Path(rel).parent.as_posix()
    index_rel = "index.md" if parent == "." else f"{parent}/index.md"
    try:
        _read_store(store, index_rel)
    except RefError as e:
        raise RefError(f"summary folder has no index.md: {rel}") from e


def _require_drop_page(rel: str) -> None:
    if not rel.endswith(".md") or Path(rel).name in RESERVED:
        raise RefError(f"drop is not an eligible markdown page: {rel}")


def _replace_nofollow(path: Path, data: bytes) -> None:
    """Replace a directory entry. rename does not follow a final symlink."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".atlas-prune-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(tmp, path)
        tmp = None
    finally:
        if fd >= 0:
            os.close(fd)
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def _rewrite_regular(path: Path, data: bytes, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as e:
        raise RefError(f"refusing to rewrite missing page {label}") from e
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
        raise RefError(f"refusing to rewrite non-regular page {label}")
    _replace_nofollow(path, data)


def _hard_linked(path: Path) -> bool:
    try:
        return path.stat().st_nlink > 1
    except OSError as e:
        raise RefError(f"cannot stat {path}") from e


def _drop_not_file(store: Path, rel: str) -> str | None:
    target = store / rel
    if target.is_symlink() or (target.exists() and not target.is_file()):
        return f"refusing to delete non-file {rel}"
    return None


def _worktree_warning(repo: Path, root: Path, store_rel: str, sha: str, gitpath: str) -> str | None:
    try:
        data = _read_store(root, store_rel)
    except RefError as e:
        if "missing page" in str(e):
            return f"{store_rel} is absent on tip; history blob is kept at {sha}"
        raise
    if not _blob_exists(repo, _resolve_commit(repo, "HEAD"), gitpath):
        raise RefError(f"refusing to delete untracked {store_rel}")
    hashed = subprocess.run(
        ["git", "hash-object", "--stdin"],
        cwd=repo,
        input=data,
        capture_output=True,
        check=False,
    )
    out = hashed.stdout.decode("utf-8", errors="replace").strip() if hashed.returncode == 0 else ""
    blob_code, blob, _ = run_git(["rev-parse", "--verify", "--end-of-options", f"{sha}:{gitpath}"], cwd=repo)
    if hashed.returncode != 0 or blob_code != 0 or not blob or out != blob:
        raise RefError(f"refusing to drop dirty {store_rel}; commit it before prune or choose a rev that matches the worktree")
    return None


def run_show(root: str | None, path: str, rev: str, as_json: bool) -> int:
    try:
        store = store_root(root)
        rel = _store_rel(store, path)
        if _managed_top(store, rel):
            raise RefError(f"refusing Atlas-managed path {rel}")
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
            _require_drop_page(rel)
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
        pending: list[tuple[str, str]] = []
        for page in _iter_pages(store):
            rel = _store_rel(store, page.relative_to(store).as_posix())
            if rel in drop_set:
                continue
            original = _read_store(store, rel).decode("utf-8")
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
                pending.append((rel, updated))
        snapshots = [(rel, _read_store(store, rel)) for rel, _ in pending]
        removed: list[tuple[str, bytes]] = []
        try:
            for rel, updated in pending:
                _rewrite_store(store, rel, updated.encode("utf-8"))
            for rel in drop_rels:
                data = _unlink_store(store, rel)
                if data is not None:
                    removed.append((rel, data))
        except Exception:
            for rel, original in snapshots:
                _rewrite_store(store, rel, original, must_exist=False)
            for rel, data in removed:
                _rewrite_store(store, rel, data, must_exist=False)
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
