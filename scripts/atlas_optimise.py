#!/usr/bin/env python3
"""atlas-optimise helper: plan (dry-run) and apply for one operator-named target.

Operator-chosen only. Never called by install, init, compile, or memory-migrate.
It writes no contract file and invents no text.

Tidy repairs copy text that already exists (beta.10). Fill creates or enriches
gist and schema pages only from an evidence pack, when that pack is useful.
Same-folder peers that already relate (or share a work_id) can share one gist.
Cross-folder relates_to does not join them. A residual missing_gist is OK.
Full mode is serial only: do not run Full on two stores at once.

  plan  --root <store> --target <folder|.> [--optimise-mode path|full|custom|incremental]
        [--since-hours N] [--custom-tree PREFIX]... [--tidy-only] [--auto-verbatim]
        [--fill-sensible] [--cost-ceiling PAGES] [--pilot] [--out-dir DIR]
        [--subject-folder F:stem]... [--json]
  apply --root <store> --target <folder|.> --plan plan.json [--include-opt-in] [--confirm ID]... [--json]

plan exit: 0 no tasks, 1 tasks listed, 2 refused.
apply exit: 0 applied with no residual tasks, 1 applied with residual tasks, 2 refused.
Residual missing_gist after an evidence handoff is not a refusal.
Structured JSON goes to stdout; diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_cli import __version__ as PACKAGE_VERSION  # noqa: E402
from atlas_cli.commands.validate import GIST_PARENT_TYPES, MISSING_GIST_TYPES  # noqa: E402
from atlas_cli.core.frontmatter import FrontmatterError, read_page  # noqa: E402
from atlas_cli.core.paths import CONTRACT_FILENAMES, CONTRACT_NAME, RESERVED  # noqa: E402
from atlas_cli.core.recall_config import schema_version  # noqa: E402
from atlas_cli.core.schema import (  # noqa: E402
    BETA3_LAYERS,
    CURRENT_STAMPS,
    contract_filename,
    load_schema,
)

MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)((?:\s+[^)]*)?)\)")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
ATLAS_URI = re.compile(r"atlas://\S+")
REMOTE_PREFIXES = ("http://", "https://", "mailto:", "atlas://", "#")
LAYER_SUFFIX = {"gist": ".gist.md", "schema": ".schema.md", "memory": ".memory.md"}
LAYER_TYPES = frozenset(LAYER_SUFFIX)
NON_CONCEPT_DIRS = frozenset({".git", "staging", "templates", "schema.d", "mesh", ".atlas-index"})
CLASS_ORDER = ("blocked", "handoff", "auto", "opt-in", "confirm", "report")
APPLY_ORDER = (
    "missing-gist-fill",
    "gist-body-enrich",
    "schema-fill",
    "dead-index-cue",
    "layer-skip-cue",
    "dead-schema-member",
    "uncovered-gist",
    "stale-gist-description",
    "schema-index-cue",
    "layer-suffix",
    "subject-cluster",
    "work-cluster",
)
OPTIMISE_MODES = ("full", "custom", "incremental", "path")
FILL_KINDS = ("missing-gist-fill", "gist-body-enrich", "schema-fill")
PROMOTION_KINDS = FILL_KINDS + ("stale-gist-description",)
DEFAULT_SINCE_HOURS = 24
DEFAULT_COST_CEILING = 200
MIN_CLAIM_CHARS = 12
MIN_PROSE_CHARS = 40
WORK_ID = "2026-10-06-atlas-optimise-vnext"
FOLLOW_ON_WORK_ID = "2026-10-06-atlas-force-gist-compile-green"
BOILERPLATE_SECTIONS = frozenset({"provenance", "related", "see also"})
SECRET_RULES = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "assigned-secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\b\s*[=:]\s*['\"]?[A-Za-z0-9/+=_\-]{8,}"
        ),
    ),
)
PII_RULES = (
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    (
        "credit-card",
        re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b"),
    ),
)
# Gate 7: medium booking/manage references are a handoff, not a refuse and
# not an auto-applied gist. Crit/High rules above still refuse promotion.
MEDIUM_RULES = (
    (
        "booking_manage_reference",
        re.compile(r"(?i)(?<![A-Za-z0-9])booking_manage_reference(?![A-Za-z0-9])|\bBMR-\d{4,}\b"),
    ),
)


class Refusal(Exception):
    """Fail closed; nothing written."""


# ---------------------------------------------------------------------------
# store reading


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _rel(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def _head(root: Path) -> tuple[str | None, bool | None]:
    head = _git(root, "rev-parse", "HEAD")
    if head is None:
        return None, None
    status = _git(root, "status", "--porcelain")
    return head, bool(status)


def _all_md(root: Path) -> list[Path]:
    out = []
    for path in sorted(root.rglob("*.md")):
        parts = path.relative_to(root).parts
        if parts and parts[0] == ".git":
            continue
        if path.is_file() and not path.is_symlink():
            out.append(path)
    return out


def _is_concept(root: Path, path: Path) -> bool:
    parts = path.relative_to(root).parts
    return bool(parts) and parts[0] not in NON_CONCEPT_DIRS and path.name not in RESERVED


def _claimed_folders(root: Path) -> list[str]:
    claimed: list[str] = []
    overlay_dir = root / "schema.d"
    if not overlay_dir.is_dir():
        return claimed
    for f in sorted(overlay_dir.glob("*.json")):
        if f.name.endswith(".receipt.json"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for folder in data.get("claimed_folders") or []:
            if isinstance(folder, str) and folder.strip("/"):
                claimed.append(folder.strip("/"))
    return claimed


class Store:
    def __init__(self, root: Path):
        self.root = root
        schema, err = load_schema(root)
        self.contract_error = err
        self.schema = schema or {}
        self.contract_file = contract_filename(root)
        self.version = schema_version(schema) if schema else "1.0"
        self.claimed = _claimed_folders(root)
        self.pages: dict[str, tuple[Path, dict, str]] = {}
        self.unreadable: list[str] = []
        self.md_files = _all_md(root)
        for path in self.md_files:
            if not _is_concept(root, path):
                continue
            try:
                meta, body = read_page(path, self.version)
            except (FrontmatterError, OSError):
                self.unreadable.append(_rel(root, path))
                continue
            if meta:
                self.pages[_rel(root, path)] = (path, meta, body)

    def ptype(self, key: str) -> str:
        return str(self.pages[key][1].get("type") or "").strip()

    def folder(self, key: str) -> str:
        return key.rsplit("/", 1)[0] if "/" in key else "."

    def in_claimed(self, key: str) -> bool:
        return any(key == c or key.startswith(c + "/") for c in self.claimed)

    def is_current_contract(self) -> bool:
        if self.contract_file != CONTRACT_NAME or self.contract_error:
            return False
        layers = (self.schema.get("memory") or {}).get("layers")
        return self.schema.get("atlas_release") in CURRENT_STAMPS and list(layers or []) == list(
            BETA3_LAYERS
        )

    def resolve_local(self, from_file: Path, target: str) -> Path | None:
        target = target.split("#", 1)[0].split("?", 1)[0]
        if not target or target.startswith(REMOTE_PREFIXES):
            return None
        cand = (from_file.parent / target).resolve()
        if cand.exists():
            return cand
        cand2 = (self.root / target.lstrip("/")).resolve()
        if cand2.exists():
            return cand2
        return (from_file.parent / target).resolve()

    def canonical(self, target: str) -> str | None:
        target = (target or "").strip()
        if not target or target.startswith(REMOTE_PREFIXES):
            return None
        cand = (self.root / target).resolve()
        try:
            return _rel(self.root, cand)
        except ValueError:
            return None


def _local_links(line: str) -> list[str]:
    return [m.group(2) for m in MD_LINK.finditer(line) if not m.group(2).startswith(REMOTE_PREFIXES)]


def _relates(meta: dict) -> list[dict]:
    rel = meta.get("relates_to")
    return [r for r in rel if isinstance(r, dict)] if isinstance(rel, list) else []


def _live_relates(meta: dict) -> list[dict]:
    """Tip relations only. A ref-bearing item is history and satisfies no live contract."""
    return [item for item in _relates(meta) if not str(item.get("ref") or "").strip()]


def _kind(item: dict) -> str:
    return str(item.get("kind") or item.get("role") or "").strip().lower()


# ---------------------------------------------------------------------------
# frontmatter text editing (line-level, verified by re-read)


def _fm_bounds(text: str) -> tuple[int, int] | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return 0, end


def _fm_lines(text: str) -> tuple[list[str], str] | None:
    bounds = _fm_bounds(text)
    if bounds is None:
        return None
    end = bounds[1]
    block = text[: end + 1]
    return block.splitlines(keepends=True), text[end + 1 :]


def _single_line_value(lines: list[str], key: str) -> tuple[int, str] | None:
    """Index and raw value text of a top-level one-line `key: value` entry."""
    for i, line in enumerate(lines):
        if re.match(rf"^{re.escape(key)}:", line):
            raw = line.split(":", 1)[1].strip()
            if not raw or raw[0] in "|>":
                return None
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt.startswith((" ", "\t")) and nxt.strip() and not nxt.lstrip().startswith("-"):
                return None
            return i, raw
    return None


def _relates_block(lines: list[str]) -> tuple[int, int] | None:
    for i, line in enumerate(lines):
        if re.match(r"^relates_to:\s*$", line):
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "\t", "-")) or not lines[j].strip()):
                if lines[j].strip() == "---":
                    break
                j += 1
            return i, j
    return None


def _item_spans(lines: list[str], start: int, end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    item_indent: int | None = None
    for i in range(start + 1, end):
        m = re.match(r"^(\s*)-\s", lines[i])
        if m and (item_indent is None or len(m.group(1)) == item_indent):
            item_indent = len(m.group(1))
            if spans:
                spans[-1] = (spans[-1][0], i)
            spans.append((i, end))
    return spans


def _item_path(lines: list[str], span: tuple[int, int]) -> str | None:
    for i in range(*span):
        m = re.match(r"^\s*-?\s*path:\s*(.+?)\s*$", lines[i])
        if m:
            v = m.group(1)
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            return v
    return None


# ---------------------------------------------------------------------------
# planning


def _task(kind, cls, paths, action, evidence, store: Store, extra_hash: list[str] | None = None, tid=None):
    hashed = sorted(set(paths) | set(extra_hash or []))
    return {
        "id": tid or f"{kind}:{paths[0]}",
        "kind": kind,
        "class": cls,
        "folder": paths[0].split("/", 1)[0] if "/" in paths[0] else ".",
        "paths": paths,
        "hashes": {p: _sha(store.root / p) for p in hashed},
        "action": action,
        "evidence": evidence,
    }


def _in_target(key: str, target: str) -> bool:
    return target == "." or key == target or key.startswith(target + "/")


def _atlas_mentions(store: Store, key: str) -> list[str]:
    hits = []
    for path in store.md_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in ATLAS_URI.finditer(text):
            if m.group(0).rstrip(").,>`'\"").endswith("/" + key):
                hits.append(_rel(store.root, path))
                break
    return hits


def _referrers(store: Store, key: str) -> list[str]:
    """Files whose relates_to path or relative link resolves to key."""
    target_file = (store.root / key).resolve()
    refs = []
    for path in store.md_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hit = False
        for m in re.finditer(r"^\s*-?\s*path:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", text, re.M):
            if store.canonical(m.group(1)) == key:
                hit = True
                break
        if not hit:
            for link in _local_links(text):
                if store.resolve_local(path, link) == target_file:
                    hit = True
                    break
        if hit and path.resolve() != target_file:
            refs.append(_rel(store.root, path))
    return refs


def _move_gates(store: Store, key: str, new_key: str) -> list[str]:
    reasons = []
    if store.in_claimed(key) or store.in_claimed(new_key):
        reasons.append("overlay-claimed folder")
    if (store.root / new_key).exists():
        reasons.append(f"{new_key} already exists")
    if not (store.root / new_key).parent.is_dir():
        reasons.append(f"target folder {store.folder(new_key)} does not exist")
    mentions = _atlas_mentions(store, key)
    if mentions:
        reasons.append("atlas:// mention in " + ", ".join(mentions))
    if (store.root / key).is_symlink():
        reasons.append("source is a symlink")
    return reasons


# ---------------------------------------------------------------------------
# fill scope, evidence, security, receipt


def _git_text(root: Path, *args: str) -> str | None:
    """Git stdout without stripping leading spaces (status lines need them)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.replace("\r\n", "\n")


def _repo_root(root: Path) -> Path | None:
    top = _git(root, "rev-parse", "--show-toplevel")
    return Path(top) if top else None


def _store_rel_paths(root: Path, repo_paths: set[str]) -> set[str]:
    repo = _repo_root(root)
    if repo is None:
        return set()
    out: set[str] = set()
    for rel_repo in repo_paths:
        try:
            out.add(_rel(root, (repo / rel_repo).resolve()))
        except ValueError:
            continue
    return out


def _dirty_paths(root: Path) -> set[str]:
    text = _git_text(root, "status", "--porcelain")
    if text is None:
        return set()
    repo_paths: set[str] = set()
    for line in text.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if path:
            repo_paths.add(path)
    return _store_rel_paths(root, repo_paths)


def _committed_paths(root: Path, since_hours: int) -> set[str] | None:
    """Paths touched by commits whose committer timestamp is inside the window.

    Committer timestamps are read from ``git log`` and compared here. A date
    filter inside git stops walking at an older commit, which hides a newer
    parent when committer dates are not monotonic. Returns None when git
    history cannot be read.
    """
    text = _git_text(
        root,
        "log",
        "--pretty=format:COMMIT %cI",
        "--name-only",
        "--diff-filter=ACMR",
    )
    if text is None:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    include = False
    repo_paths: set[str] = set()
    for line in text.splitlines():
        if line.startswith("COMMIT "):
            stamp = line[len("COMMIT "):].strip()
            try:
                when = datetime.fromisoformat(stamp)
            except ValueError:
                include = False
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            include = when >= cutoff
            continue
        if include and line.strip():
            repo_paths.add(line.strip())
    return _store_rel_paths(root, repo_paths)


def _under_prefixes(key: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return True
    return any(key == prefix or key.startswith(prefix + "/") for prefix in prefixes)


def _normalize_prefix(root: Path, raw: str) -> str:
    text = raw.strip().strip("/")
    if not text or text == ".":
        raise Refusal("--custom-tree must name a path prefix inside the store, not the root")
    if text.startswith(("/", "\\")) or ".." in Path(text).parts:
        raise Refusal(f"--custom-tree {raw!r} is not a store-relative path prefix")
    try:
        return _rel(root, (root / text).resolve())
    except ValueError as e:
        raise Refusal(f"--custom-tree {raw!r} escapes the store root") from e


def _index_keys(store: Store) -> list[str]:
    keys = []
    for path in store.md_files:
        if path.name != "index.md" or not _is_index_scope(store.root, path):
            continue
        keys.append(_rel(store.root, path))
    return keys


class Scope:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _build_scope(
    store: Store,
    target: str,
    mode: str,
    custom_trees: list[str],
    since_hours: int | None,
    cost_ceiling: int,
) -> Scope:
    if mode not in OPTIMISE_MODES:
        raise Refusal(f"unknown optimise_mode {mode!r}")
    if mode == "incremental" and since_hours is None:
        since_hours = DEFAULT_SINCE_HOURS
    use_git = mode == "incremental" or (mode == "custom" and since_hours is not None)
    if use_git and (since_hours is None or since_hours < 1):
        raise Refusal("--since-hours must be a positive integer")
    prefixes = [_normalize_prefix(store.root, item) for item in custom_trees]
    committed: set[str] = set()
    dirty: set[str] = set()
    if use_git:
        committed_paths = _committed_paths(store.root, since_hours or DEFAULT_SINCE_HOURS)
        if committed_paths is None:
            raise Refusal(
                "incremental window reads git commit history (committer clock); "
                "this store has no usable git history"
            )
        committed = committed_paths
        dirty = _dirty_paths(store.root)

    def selected(key: str) -> bool:
        if not _in_target(key, target) or not _under_prefixes(key, prefixes):
            return False
        if use_git and key not in committed:
            return False
        return True

    page_keys = {key for key in store.pages if selected(key)}
    indexes = set(_index_keys(store))
    index_keys = {key for key in indexes if selected(key)}
    eligible = {key for key in page_keys if store.ptype(key) in MISSING_GIST_TYPES}
    if use_git:
        fill_parents = {key for key in eligible if key not in dirty}
    else:
        fill_parents = set(eligible)
    if use_git:
        for parent in list(fill_parents):
            page_keys.add(parent)
            folder = store.folder(parent)
            for key in store.pages:
                if store.folder(key) != folder:
                    continue
                if store.ptype(key) == "schema":
                    page_keys.add(key)
                elif store.ptype(key) == "gist" and parent in (_gist_parent_keys(store, key) or []):
                    page_keys.add(key)
            index_key = "index.md" if folder == "." else f"{folder}/index.md"
            if index_key in indexes or (store.root / index_key).is_file():
                index_keys.add(index_key)
    projected = len(page_keys) + len(index_keys)
    return Scope(
        mode=mode,
        target=target,
        custom_trees=prefixes,
        since_hours=since_hours if use_git else None,
        use_git=use_git,
        page_keys=page_keys,
        index_keys=index_keys,
        fill_parents=fill_parents,
        committed=sorted(committed),
        dirty=sorted(dirty),
        projected=projected,
        cost_ceiling=cost_ceiling,
    )


def _gist_parent_keys(store: Store, gist_key: str) -> list[str] | None:
    """Canonical parents of a well-formed gist, matching compile's coverage rule.

    N>=1 derived_from parents, each a gist-parent type in the same folder.
    Cross-folder parents, duplicates, and gist-of-gist return None so they
    do not clear missing_gist.
    """
    if gist_key not in store.pages or store.ptype(gist_key) != "gist":
        return None
    parents = [item for item in _live_relates(store.pages[gist_key][1]) if _kind(item) == "derived_from"]
    if not parents:
        return None
    canons: list[str] = []
    folders: list[str] = []
    for item in parents:
        canonical = store.canonical(str(item.get("path") or ""))
        if canonical not in store.pages or store.ptype(canonical) not in GIST_PARENT_TYPES:
            return None
        if canonical in canons:
            return None
        canons.append(canonical)
        folders.append(store.folder(canonical))
    if len(set(folders)) != 1:
        return None
    return canons


def _parents_with_gist(store: Store) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for key in store.pages:
        for parent in _gist_parent_keys(store, key) or []:
            found.setdefault(parent, []).append(key)
    return found


def _scan_findings(text: str) -> list[dict]:
    findings = []
    for rule, pattern in SECRET_RULES:
        if text and pattern.search(text):
            findings.append({"class": "secret", "severity": "high", "rule": rule, "type": "secret"})
    for rule, pattern in PII_RULES:
        if text and pattern.search(text):
            findings.append({"class": "pii", "severity": "high", "rule": rule, "type": "pii"})
    for rule, pattern in MEDIUM_RULES:
        if text and pattern.search(text):
            findings.append({
                "class": "booking",
                "severity": "medium",
                "rule": rule,
                "type": "booking_manage_reference",
            })
    return findings


def _claim_prose(line: str) -> str:
    text = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", line.strip())
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[\[[^\]]+\]\]", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _claim_lines(body: str) -> list[dict]:
    """Deterministic claim lines. Link-only, heading, and boilerplate lines are skipped."""
    content: list[dict] = []
    other: list[dict] = []
    section = ""
    for number, line in enumerate(body.splitlines(), 1):
        if line.lstrip().startswith("#"):
            section = re.sub(r"^#+\s*", "", line.strip()).strip().lower()
            continue
        raw = line.strip()
        if not raw or raw.startswith("<!--"):
            continue
        if section in BOILERPLATE_SECTIONS:
            continue
        prose = _claim_prose(raw)
        if len(prose) < MIN_CLAIM_CHARS:
            continue
        item = {"line": number, "text": raw, "section": section}
        (content if section == "content" else other).append(item)
    return content or other


def _plain_description(store: Store, key: str) -> str | None:
    path, meta, _ = store.pages[key]
    desc = meta.get("description")
    if not isinstance(desc, str) or not desc.strip() or "\n" in desc:
        return None
    parsed = _fm_lines(path.read_text(encoding="utf-8", errors="replace"))
    if parsed is None or _single_line_value(parsed[0], "description") is None:
        return None
    return desc.strip()


def _yaml_scalar(value: str) -> str | None:
    """One-line YAML scalar that the package reader round-trips without escapes."""
    if not value or value != value.strip() or "\n" in value or "\r" in value:
        return None
    if any(ch in value for ch in "\"'\\"):
        return None
    if re.match(r"^[A-Za-z0-9]", value) and not re.search(r"[:#\[\]\{\},&*!|>%@`]", value):
        if value.lower() not in {"true", "false", "null", "yes", "no"}:
            return value
    if any(ch in value for ch in ":#[]{},&*!|>%@"):
        return None
    return f'"{value}"'


def _grounded(text: str, meta: dict, body: str) -> bool:
    if not isinstance(text, str) or not text:
        return False
    desc = meta.get("description")
    return text in body or (isinstance(desc, str) and text in desc)


def _evidence_pack(store: Store, parent_key: str) -> dict:
    """Extractive pack for one parent. Secret text is not copied into the pack."""
    _path, meta, body = store.pages[parent_key]
    sensitivity = str(meta.get("sensitivity") or "").strip().lower()
    description = _plain_description(store, parent_key)
    claims = _claim_lines(body)
    live = "\n".join(part for part in (description or "", body, str(meta.get("title") or "")) if part)
    findings = _scan_findings(live)
    if sensitivity == "restricted":
        findings.append({"class": "sensitivity", "severity": "high", "rule": "restricted", "type": "sensitivity"})
    for item in findings:
        item.setdefault("path", parent_key)
        item.setdefault("page_type", store.ptype(parent_key))
    blocked = any(item["severity"] in ("critical", "high") for item in findings)
    medium = any(item.get("rule") == "booking_manage_reference" for item in findings)
    extract = None
    extract_kind = None
    excerpt_rule = None
    sufficient = False
    reason = "insufficient evidence: no plain description and no claim sentences"
    if description:
        extract = description
        extract_kind = "description"
        excerpt_rule = "parent-description"
        sufficient = True
        reason = "plain parent description"
    elif claims:
        extract = claims[0]["text"]
        extract_kind = "excerpt"
        excerpt_rule = "first-claim-line"
        sufficient = True
        reason = "first claim line"
    prose = _gist_body_prose(extract, [item["text"] for item in claims]) if extract else None
    if sufficient and (prose is None or _yaml_scalar(extract or "") is None):
        sufficient = False
        reason = "evidence cannot be written as minimal prose without invention"
        extract_out = None
        prose = None
    else:
        extract_out = extract
    if blocked:
        return {
            "parent": parent_key,
            "parent_type": store.ptype(parent_key),
            "sensitivity": sensitivity,
            "sufficient": False,
            "reason": "security scan blocked promotion",
            "extract": None,
            "extract_kind": None,
            "excerpt_rule": None,
            "body": None,
            "auto_eligible": False,
            "security_blocked": True,
            "findings": findings,
            "sources": [{"path": parent_key, "sha256": _sha(store.root / parent_key), "redacted": True}],
        }
    if medium:
        return {
            "parent": parent_key,
            "parent_type": store.ptype(parent_key),
            "sensitivity": sensitivity,
            "sufficient": False,
            "reason": "booking_manage_reference handoff",
            "extract": None,
            "extract_kind": None,
            "excerpt_rule": None,
            "body": None,
            "auto_eligible": False,
            "security_blocked": False,
            "findings": findings,
            "sources": [{"path": parent_key, "sha256": _sha(store.root / parent_key), "redacted": True}],
        }
    spans = [{"line": item["line"], "text": item["text"]} for item in claims] if not blocked else []
    fields = {"description": description} if description else {}
    return {
        "parent": parent_key,
        "parent_type": store.ptype(parent_key),
        "sensitivity": sensitivity,
        "sufficient": sufficient,
        "reason": reason,
        "extract": extract_out,
        "extract_kind": extract_kind if sufficient else None,
        "excerpt_rule": excerpt_rule if sufficient else None,
        "body": prose,
        "auto_eligible": bool(sufficient and extract_kind in ("description", "excerpt")),
        "security_blocked": False,
        "findings": findings,
        "sources": [{
            "path": parent_key,
            "sha256": _sha(store.root / parent_key),
            "fields": fields,
            "spans": spans,
        }],
    }


def _gist_body_prose(extract: str | None, claim_texts: list[str]) -> str | None:
    if not extract:
        return None
    parts = [extract]
    if len(_claim_prose(extract)) < MIN_PROSE_CHARS:
        for text in claim_texts:
            if text not in parts:
                parts.append(text)
            if len(_claim_prose("\n\n".join(parts))) >= MIN_PROSE_CHARS:
                break
    prose = "\n\n".join(parts)
    if len(_claim_prose(prose)) < MIN_PROSE_CHARS:
        return None
    return prose


def _fill_class(pack: dict, auto_verbatim: bool) -> str:
    if pack["security_blocked"]:
        return "blocked"
    if not pack["sufficient"]:
        return "handoff"
    if pack["auto_eligible"] and auto_verbatim:
        return "auto"
    return "confirm"


def _gist_title(meta: dict, parent_key: str) -> str:
    title = str(meta.get("title") or "").strip()
    if not title:
        title = Path(parent_key).stem
    return f"{title} gist"


def _new_gist_key(store: Store, parent_key: str) -> str | None:
    folder = store.folder(parent_key)
    stem = Path(parent_key).name[:-3] if parent_key.endswith(".md") else Path(parent_key).name
    for suffix in (".memory", ".gist", ".schema"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    name = f"{stem}.gist.md"
    rel = name if folder == "." else f"{folder}/{name}"
    if rel == parent_key or rel in store.pages or (store.root / rel).exists():
        return None
    return rel


def _created_day(meta: dict) -> str:
    created = str(meta.get("created") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", created):
        return created
    return date.today().isoformat()


def _promotion_blob(task: dict) -> str:
    evidence = task.get("evidence") or {}
    parts = [
        str(evidence.get("extract") or ""),
        str(evidence.get("body") or ""),
        str((evidence.get("proposed") or {}).get("description") or ""),
        str((evidence.get("proposed") or {}).get("body") or ""),
        str((evidence.get("proposed") or {}).get("title") or ""),
    ]
    for source in evidence.get("sources") or []:
        fields = source.get("fields") or {}
        if isinstance(fields, dict):
            parts.extend(str(value) for value in fields.values())
        for span in source.get("spans") or []:
            parts.append(str(span.get("text") or ""))
    for member in evidence.get("members") or []:
        parts.append(str(member.get("title") or ""))
        parts.append(str(member.get("description") or ""))
    return "\n".join(parts)


def _gate_security(tasks: list[dict]) -> None:
    for task in tasks:
        if task["kind"] not in PROMOTION_KINDS:
            continue
        evidence = task.setdefault("evidence", {})
        findings = list(evidence.get("findings") or [])
        findings.extend(_scan_findings(_promotion_blob(task)))
        if str(evidence.get("sensitivity") or "") == "restricted":
            findings.append({
                "class": "sensitivity",
                "severity": "high",
                "rule": "restricted",
                "type": "sensitivity",
                "path": evidence.get("parent") or "",
                "page_type": evidence.get("parent_type") or "",
            })
        for item in findings:
            item.setdefault("path", evidence.get("parent") or "")
            item.setdefault("page_type", evidence.get("parent_type") or "")
        dedup = []
        seen = set()
        for item in findings:
            key = (item.get("path"), item.get("class"), item.get("rule"))
            if key in seen:
                continue
            seen.add(key)
            dedup.append(item)
        blocked = any(item.get("severity") in ("critical", "high") for item in dedup)
        medium = any(
            item.get("rule") == "booking_manage_reference" and item.get("severity") == "medium"
            for item in dedup
        )
        evidence["security"] = {
            "status": "blocked" if blocked else ("handoff" if medium else "pass"),
            "findings": dedup,
            "promoted": False,
        }
        if blocked or medium:
            if blocked and task["class"] in ("auto", "opt-in", "confirm", "handoff"):
                task["class"] = "blocked"
            elif medium and task["class"] in ("auto", "opt-in", "confirm"):
                task["class"] = "handoff"
            evidence["extract"] = None
            evidence["body"] = None
            evidence["proposed"] = None
            evidence["gist_description"] = None
            evidence["memory_description"] = None
            evidence["sufficient"] = False
            evidence["reason"] = (
                "security scan blocked promotion" if blocked else "booking_manage_reference handoff"
            )
            for member in evidence.get("members") or []:
                member["title"] = None
                member["description"] = None
            for source in evidence.get("sources") or []:
                source.pop("fields", None)
                source.pop("spans", None)
                source["redacted"] = True


def _security_summary(tasks: list[dict]) -> dict:
    findings = []
    for task in tasks:
        for item in ((task.get("evidence") or {}).get("security") or {}).get("findings") or []:
            findings.append({"task": task["id"], **item})
    high = [item for item in findings if item.get("severity") in ("critical", "high")]
    medium = [item for item in findings if item.get("severity") == "medium"]
    if high:
        status = "blocked"
    elif medium:
        status = "handoff"
    else:
        status = "pass"
    return {
        "status": status,
        "findings": findings,
        "new_critical_or_high": len(high),
        "secrets_promoted": False,
    }


def _residuals(store: Store, scope: Scope, tasks: list[dict]) -> dict:
    covered = set(_parents_with_gist(store))
    missing = [
        key for key in sorted(scope.fill_parents)
        if store.ptype(key) in MISSING_GIST_TYPES and key not in covered
    ]
    insufficient = [
        task for task in tasks
        if task["kind"] in ("missing-gist-fill", "gist-body-enrich")
        and task["class"] in ("handoff", "blocked")
    ]
    return {
        "missing_gist": len(missing),
        "insufficient_evidence": len(insufficient),
        "handoff": sum(1 for task in tasks if task["class"] == "handoff"),
        "stale_upper_page_tasks": sum(1 for task in tasks if task["kind"] == "stale-gist-description"),
        "missing_gist_fails_run": False,
    }


def _plan_tasks(plan: dict) -> list[dict]:
    return [task for tasks in (plan.get("folders") or {}).values() for task in tasks]


def _fill_guard(plan: dict) -> dict:
    """Additive receipt rows for fills that happen. Residual missing_gist stays OK."""
    tasks = _plan_tasks(plan)
    useful = [
        task for task in tasks
        if task["kind"] in ("missing-gist-fill", "gist-body-enrich") and task["class"] in ("auto", "confirm")
    ]
    shared = [
        task for task in useful
        if task["kind"] == "missing-gist-fill" and len((task.get("evidence") or {}).get("parents") or []) > 1
    ]
    hist: dict[str, int] = {}
    for task in shared:
        size = str(len(task["evidence"]["parents"]))
        hist[size] = hist.get(size, 0) + 1
    enrich = sum(1 for task in useful if (task.get("evidence") or {}).get("enrich_optional"))
    refuse = 0
    promoted_high = False
    hits = []
    seen = set()
    for task in tasks:
        evidence = task.get("evidence") or {}
        findings = ((evidence.get("security") or {}).get("findings")) or evidence.get("findings") or []
        high = [item for item in findings if item.get("severity") in ("critical", "high")]
        if task["kind"] in PROMOTION_KINDS and task["class"] == "blocked" and high:
            refuse += 1
        if task["kind"] in PROMOTION_KINDS and task["class"] in ("auto", "confirm") and high:
            promoted_high = True
        for item in findings:
            if item.get("severity") not in ("critical", "high", "medium"):
                continue
            hit = {
                "path": item.get("path") or evidence.get("parent") or (task["paths"][0] if task.get("paths") else ""),
                "type": item.get("page_type") or evidence.get("parent_type") or "",
                "severity": item["severity"],
            }
            key = (hit["path"], hit["type"], hit["severity"])
            if key in seen:
                continue
            seen.add(key)
            hits.append(hit)
    return {
        "scan_gate_refuse_count": refuse,
        "body_fills": len(useful),
        "shared_gist_count": len(shared),
        "cluster_size_hist": hist,
        "enrich_optional_count": enrich,
        "zero_crit_high_promoted": not promoted_high,
        "scan_hits": hits,
    }


def _receipt(plan: dict, *, phase: str, applied: list[str] | None = None, parent_edits: int = 0) -> dict:
    source = plan["source"]
    security = plan["security_summary"]
    guard = _fill_guard(plan)
    return {
        "schema": "atlas-optimise-receipt/v1",
        "work_id": WORK_ID,
        "follow_on_work_id": FOLLOW_ON_WORK_ID,
        "phase": phase,
        "fetch_ok": bool(source.get("fetch_ok")),
        "tip": source.get("head"),
        "optimise_mode": source.get("optimise_mode"),
        "target": source.get("target"),
        "since_hours": source.get("since_hours"),
        "custom_tree": list(source.get("custom_tree") or []),
        "tidy_only": bool(source.get("tidy_only")),
        "auto_verbatim": bool(source.get("auto_verbatim")),
        "pilot": bool(source.get("pilot")),
        "fill_sensible": not bool(source.get("tidy_only")),
        "serial_full_only": True,
        "fleet_ready": False,
        "package_version": PACKAGE_VERSION,
        "counts": plan["counts"],
        "applied": list(applied or []),
        "residuals": plan["residuals"],
        "security": security,
        "cost": plan["cost"],
        **guard,
        "gates": {
            "auto_text_is_verbatim_substring": True,
            "parent_edits": parent_edits,
            "zero_parent_edits": parent_edits == 0,
            "writes_limited_to_selected_task_paths": True,
            "missing_gist_drop_only_via_evidence": True,
            "spot_check_n": 10,
            "spot_check": "operator",
            "security_scan": security["status"],
            "new_critical_or_high_secret_class": security["new_critical_or_high"],
            "disagreement_rate": "informational",
            "residual_missing_gist_fails_run": False,
            "zero_crit_high_promoted": guard["zero_crit_high_promoted"],
            "run_failed": False,
            "pilot_before_fleet": True,
            "serial_full_only": True,
            "day_one_scope": [
                "all MISSING_GIST_TYPES",
                "schema minimal prose",
                "path fill by default",
                "incremental 24h committer",
                "security scan",
                "cost ceiling",
                "durable receipt",
            ],
        },
    }


def _fill_clusters(store: Store, parents: list[str]) -> list[list[str]]:
    """Same-folder clusters among parents chosen for fill.

    Join only when co-located peers already have a relates_to edge or share
    a work_id. Cross-folder relates_to does not join. Unrelated neighbours
    stay separate clusters, including singletons.
    """
    by_folder: dict[str, list[str]] = {}
    for parent in parents:
        by_folder.setdefault(store.folder(parent), []).append(parent)
    clusters: list[list[str]] = []
    for folder, members in by_folder.items():
        member_set = set(members)
        link = {member: member for member in members}

        def find(key: str) -> str:
            while link[key] != key:
                link[key] = link[link[key]]
                key = link[key]
            return key

        def union(left: str, right: str) -> None:
            root_left, root_right = find(left), find(right)
            if root_left != root_right:
                link[root_right] = root_left

        for member in members:
            for item in _live_relates(store.pages[member][1]):
                target = store.canonical(str(item.get("path") or ""))
                if target in member_set and target != member and store.folder(target) == folder:
                    union(member, target)
        by_work: dict[str, list[str]] = {}
        for member in members:
            work_id = str(store.pages[member][1].get("work_id") or "").strip()
            if work_id:
                by_work.setdefault(work_id, []).append(member)
        for group in by_work.values():
            if len(group) < 2:
                continue
            head = group[0]
            for other in group[1:]:
                union(head, other)
        grouped: dict[str, list[str]] = {}
        for member in members:
            grouped.setdefault(find(member), []).append(member)
        for group in grouped.values():
            clusters.append(sorted(group))
    clusters.sort(key=lambda group: group[0])
    return clusters


def _cluster_pack(store: Store, parents: list[str]) -> dict:
    """Union evidence pack. The written gist stays verbatim from at least one parent."""
    packs = [_evidence_pack(store, parent) for parent in parents]
    findings: list[dict] = []
    seen = set()
    for pack in packs:
        for item in pack.get("findings") or []:
            key = (item.get("path"), item.get("class"), item.get("rule"))
            if key in seen:
                continue
            seen.add(key)
            findings.append(item)
    blocked = any(pack["security_blocked"] for pack in packs)
    medium = any(item.get("rule") == "booking_manage_reference" for item in findings)
    sensitivity = next(
        (pack["sensitivity"] for pack in packs if pack["sensitivity"] == "restricted"),
        packs[0]["sensitivity"],
    )
    base = {
        "parents": list(parents),
        "parent": parents[0],
        "parent_type": store.ptype(parents[0]),
        "sensitivity": sensitivity,
        "findings": findings,
        "security_blocked": blocked,
        "cluster_size": len(parents),
        "enrich_optional": False,
        "extract_parent": None,
    }

    def redacted() -> list[dict]:
        return [
            {"path": pack["parent"], "sha256": _sha(store.root / pack["parent"]), "redacted": True}
            for pack in packs
        ]

    def empty(reason: str, *, sources: list[dict] | None = None) -> dict:
        return {
            **base,
            "sufficient": False,
            "reason": reason,
            "extract": None,
            "extract_kind": None,
            "excerpt_rule": None,
            "body": None,
            "auto_eligible": False,
            "sources": sources if sources is not None else redacted(),
        }

    if blocked:
        return empty("security scan blocked promotion")
    if medium:
        return empty("booking_manage_reference handoff")
    sufficient = [pack for pack in packs if pack["sufficient"]]
    if not sufficient:
        reason = packs[0]["reason"]
        if len(packs) > 1:
            reason = "insufficient evidence: no plain description and no claim sentences"
        sources = []
        for pack in packs:
            sources.extend(pack.get("sources") or [])
        return empty(reason, sources=sources)
    chosen = sufficient[0]
    claim_texts: list[str] = []
    for pack in sufficient:
        for source in pack.get("sources") or []:
            for span in source.get("spans") or []:
                text = span.get("text")
                if text and text not in claim_texts:
                    claim_texts.append(text)
    prose = _gist_body_prose(chosen["extract"], claim_texts)
    if prose is None or _yaml_scalar(chosen["extract"] or "") is None:
        return empty("evidence cannot be written as minimal prose without invention")
    sources = []
    for pack in packs:
        sources.extend(pack.get("sources") or [])
    reason = chosen["reason"] if len(parents) == 1 else f"shared cluster evidence ({chosen['reason']})"
    return {
        **base,
        "parent": chosen["parent"],
        "parent_type": chosen["parent_type"],
        "sufficient": True,
        "reason": reason,
        "extract": chosen["extract"],
        "extract_kind": chosen["extract_kind"],
        "excerpt_rule": chosen["excerpt_rule"],
        "body": prose,
        "auto_eligible": bool(chosen["auto_eligible"]),
        "sources": sources,
        "extract_parent": chosen["parent"],
        "enrich_optional": len(parents) > 1 and any(not pack["sufficient"] for pack in packs),
    }


def _fill_evidence(pack: dict, cls: str, *, proposed: dict | None, new_path: str | None) -> dict:
    keep = cls in ("auto", "confirm")
    return {
        "parent": pack["parent"],
        "parents": list(pack.get("parents") or [pack["parent"]]),
        "parent_type": pack["parent_type"],
        "new_path": new_path,
        "sensitivity": pack["sensitivity"],
        "sufficient": bool(pack["sufficient"] and keep),
        "reason": pack["reason"],
        "extract": pack.get("extract") if keep else None,
        "extract_kind": pack.get("extract_kind") if keep else None,
        "excerpt_rule": pack.get("excerpt_rule") if keep else None,
        "body": pack.get("body") if keep else None,
        "auto_eligible": pack.get("auto_eligible", False),
        "findings": pack.get("findings") or [],
        "sources": pack.get("sources") or [],
        "proposed": proposed,
        "cluster_size": pack.get("cluster_size") or 1,
        "enrich_optional": bool(pack.get("enrich_optional")),
        "extract_parent": pack.get("extract_parent"),
    }


def _plan_fills(store: Store, scope: Scope, tasks: list[dict], auto_verbatim: bool, tidy_only: bool) -> None:
    if tidy_only:
        return
    covered = _parents_with_gist(store)
    uncovered = [
        parent for parent in sorted(scope.fill_parents)
        if store.ptype(parent) in MISSING_GIST_TYPES and not covered.get(parent)
    ]
    for parents in _fill_clusters(store, uncovered):
        pack = _cluster_pack(store, parents)
        anchor = pack.get("extract_parent") or parents[0]
        new_key = _new_gist_key(store, anchor)
        cls = _fill_class(pack, auto_verbatim)
        if new_key is None and cls in ("auto", "confirm"):
            cls = "handoff"
            pack = {**pack, "sufficient": False, "reason": "gist filename is already taken"}
        _path, meta, _body = store.pages[anchor]
        proposed = None
        if cls in ("auto", "confirm") and new_key and pack.get("extract") and pack.get("body"):
            proposed = {
                "path": new_key,
                "title": _gist_title(meta, anchor),
                "created": _created_day(meta),
                "description": pack["extract"],
                "body": pack["body"],
                "sensitivity": pack["sensitivity"] if pack["sensitivity"] in ("public", "internal") else "internal",
                "parents": parents,
            }
        label = parents[0] if len(parents) == 1 else ", ".join(parents)
        action = (
            f"create gist for {label} from the evidence pack ({pack['reason']})"
            if cls in ("auto", "confirm")
            else f"no gist written for {label}: {pack['reason']}"
        )
        tid = f"missing-gist-fill:{parents[0]}" if len(parents) == 1 else "missing-gist-fill:" + "+".join(parents)
        tasks.append(_task(
            "missing-gist-fill", cls, [new_key or parents[0], *parents], action,
            _fill_evidence(pack, cls, proposed=proposed, new_path=new_key),
            store, tid=tid,
        ))

    for gist in sorted(key for key in scope.page_keys if store.ptype(key) == "gist"):
        parents = _gist_parent_keys(store, gist)
        if not parents or not any(parent in scope.fill_parents for parent in parents):
            continue
        if not any(store.ptype(parent) in MISSING_GIST_TYPES for parent in parents):
            continue
        _gpath, gmeta, _gbody = store.pages[gist]
        desc = gmeta.get("description")
        if isinstance(desc, str) and desc and any(
            _grounded(desc, store.pages[parent][1], store.pages[parent][2]) for parent in parents
        ):
            continue
        if any(
            task["kind"] == "stale-gist-description" and task["class"] == "auto" and gist in task["paths"]
            for task in tasks
        ):
            continue
        pack = _cluster_pack(store, parents)
        cls = _fill_class(pack, auto_verbatim)
        anchor = pack.get("extract_parent") or parents[0]
        _ppath, pmeta, _pbody = store.pages[anchor]
        proposed = None
        if cls in ("auto", "confirm") and pack.get("extract") and pack.get("body"):
            proposed = {
                "path": gist,
                "title": str(gmeta.get("title") or _gist_title(pmeta, anchor)),
                "description": pack["extract"],
                "body": pack["body"],
                "parents": parents,
            }
        tasks.append(_task(
            "gist-body-enrich", cls, [gist, *parents],
            (
                f"rewrite {gist} description from the evidence pack ({pack['reason']}); parent text is not edited"
                if cls in ("auto", "confirm")
                else f"no gist rewrite for {gist}: {pack['reason']}"
            ),
            _fill_evidence(pack, cls, proposed=proposed, new_path=gist),
            store, tid=f"gist-body-enrich:{gist}",
        ))

    folders: set[str] = set()
    for key in scope.page_keys:
        if store.ptype(key) == "gist" or key in scope.fill_parents:
            folders.add(store.folder(key))
    for task in list(tasks):
        if task["kind"] == "missing-gist-fill" and task["class"] in ("auto", "confirm"):
            new_path = (task.get("evidence") or {}).get("new_path")
            if new_path:
                folders.add(store.folder(new_path))
    for folder in sorted(folders):
        if any(store.folder(key) == folder and store.ptype(key) == "schema" for key in store.pages):
            continue
        members = _schema_members(store, folder, tasks)
        _plan_schema_fill(store, folder, members, tasks)


def _schema_members(store: Store, folder: str, tasks: list[dict]) -> list[dict]:
    members = []
    for key in sorted(store.pages):
        if store.folder(key) != folder or store.ptype(key) != "gist":
            continue
        meta = store.pages[key][1]
        title = str(meta.get("title") or "").strip()
        desc = meta.get("description")
        description = desc.strip() if isinstance(desc, str) else ""
        if not title and not description:
            continue
        if str(meta.get("sensitivity") or "").strip().lower() == "restricted":
            continue
        if _scan_findings(f"{title}\n{description}"):
            continue
        members.append({
            "path": key,
            "title": title,
            "description": description,
            "planned": False,
        })
    known = {member["path"] for member in members}
    for task in tasks:
        if task["kind"] != "missing-gist-fill" or task["class"] not in ("auto", "confirm"):
            continue
        proposed = (task.get("evidence") or {}).get("proposed") or {}
        path = proposed.get("path")
        if not path or store.folder(path) != folder or path in known:
            continue
        title = str(proposed.get("title") or "").strip()
        description = str(proposed.get("description") or "").strip()
        if not title and not description:
            continue
        members.append({
            "path": path,
            "title": title,
            "description": description,
            "planned": True,
        })
    return members


def _minimal_schema_prose(members: list[dict]) -> str | None:
    bits = []
    for member in members:
        title = member.get("title") or ""
        description = member.get("description") or ""
        if title and description:
            bits.append(f"{title}. {description}")
        elif description:
            bits.append(description)
        elif title:
            bits.append(title)
    text = " ".join(bits).strip()
    if len(_claim_prose(text)) < MIN_PROSE_CHARS:
        return None
    return text


def _new_schema_key(store: Store, folder: str) -> str | None:
    candidates = ["schema.schema.md"]
    stem = "folder" if folder == "." else folder.split("/")[-1]
    candidates.append(f"{stem}.schema.md")
    for name in candidates:
        rel = name if folder == "." else f"{folder}/{name}"
        if rel not in store.pages and not (store.root / rel).exists():
            return rel
    return None


def _plan_schema_fill(store: Store, folder: str, members: list[dict], tasks: list[dict]) -> None:
    schema_key = _new_schema_key(store, folder)
    prose = _minimal_schema_prose(members)
    index_key = "index.md" if folder == "." else f"{folder}/index.md"
    label = next((member["title"] for member in members if member.get("title")), "")
    description = next((member["description"] for member in members if member.get("description")), "")
    findings = _scan_findings(f"{prose or ''}\n{description}")
    if schema_key and prose and members and not findings:
        title = f"{label} schema" if label else "Schema"
        if _yaml_scalar(title) is None or (description and _yaml_scalar(description) is None):
            cls = "handoff"
            reason = "schema title or description cannot be written without invention"
            proposed = None
        else:
            cls = "confirm"
            reason = "minimal prose cited from gist title or description"
            proposed = {
                "path": schema_key,
                "title": title,
                "created": date.today().isoformat(),
                "description": description or None,
                "body": prose,
                "index": index_key,
            }
    else:
        cls = "blocked" if findings else "handoff"
        if findings:
            reason = "security scan blocked schema promotion"
        elif not members:
            reason = "no gist title or description to cite"
        elif prose is None:
            reason = "gist titles and descriptions are too thin for minimal schema prose"
        else:
            reason = "schema filename is already taken"
        proposed = None
        schema_key = schema_key or (f"{folder}/schema.schema.md" if folder != "." else "schema.schema.md")
    paths = [schema_key, index_key, *[member["path"] for member in members]]
    tasks.append(_task(
        "schema-fill", cls, paths,
        (
            f"create {schema_key} with minimal prose and relates_to for {len(members)} gist(s)"
            if cls == "confirm"
            else f"no schema written in {folder}: {reason}"
        ),
        {
            "folder": folder,
            "members": members,
            "body": prose if cls == "confirm" else None,
            "reason": reason,
            "sufficient": cls == "confirm",
            "findings": findings,
            "sensitivity": "",
            "proposed": proposed,
            "sources": [
                {"path": member["path"], "sha256": _sha(store.root / member["path"]), "redacted": bool(findings)}
                for member in members
                if not member.get("planned")
            ],
        },
        store, tid=f"schema-fill:{folder}",
    ))


def _live_promotion_text(store: Store, task: dict) -> str:
    evidence = task.get("evidence") or {}
    kind = task["kind"]
    if kind == "stale-gist-description" and len(task["paths"]) > 1 and task["paths"][1] in store.pages:
        return str(store.pages[task["paths"][1]][1].get("description") or "")
    parts = []
    for parent in _task_parents(task):
        if parent in store.pages:
            meta, body = store.pages[parent][1], store.pages[parent][2]
            parts.extend([str(meta.get("title") or ""), str(meta.get("description") or ""), body])
    if parts:
        return "\n".join(parts)
    parts = []
    for member in evidence.get("members") or []:
        path = member.get("path")
        if path in store.pages:
            meta = store.pages[path][1]
            parts.append(str(meta.get("title") or ""))
            parts.append(str(meta.get("description") or ""))
        else:
            parts.append(str(member.get("title") or ""))
            parts.append(str(member.get("description") or ""))
    return "\n".join(parts)


def _live_restricted(store: Store, task: dict) -> bool:
    evidence = task.get("evidence") or {}
    for parent in _task_parents(task):
        if parent in store.pages and str(store.pages[parent][1].get("sensitivity") or "").strip().lower() == "restricted":
            return True
    if len(task["paths"]) > 1 and task["paths"][1] in store.pages:
        if str(store.pages[task["paths"][1]][1].get("sensitivity") or "").strip().lower() == "restricted":
            return True
    for member in evidence.get("members") or []:
        path = member.get("path")
        if path in store.pages and str(store.pages[path][1].get("sensitivity") or "").strip().lower() == "restricted":
            return True
    return False


def plan_store(
    root: Path,
    target: str,
    subject_folders: list[tuple[str, str]],
    *,
    mode: str = "path",
    custom_trees: list[str] | None = None,
    since_hours: int | None = None,
    tidy_only: bool = False,
    auto_verbatim: bool = False,
    cost_ceiling: int = DEFAULT_COST_CEILING,
    pilot: bool = False,
    enforce_ceiling: bool = True,
) -> dict:
    store = Store(root)
    if store.contract_error:
        raise Refusal(f"contract: {store.contract_error}")
    if cost_ceiling < 0:
        raise Refusal("--cost-ceiling must be zero or a positive integer")
    scope = _build_scope(store, target, mode, list(custom_trees or []), since_hours, cost_ceiling)
    if enforce_ceiling and scope.projected > cost_ceiling:
        raise Refusal(
            f"cost ceiling exceeded: projected {scope.projected} pages > ceiling {cost_ceiling}"
        )
    tasks: list[dict] = []

    frames = sorted(k for k in store.pages if store.ptype(k) == "frame")
    precondition = None
    if not store.is_current_contract() or frames:
        precondition = {
            "id": "contract-precondition:.",
            "kind": "contract-precondition",
            "class": "handoff",
            "folder": ".",
            "paths": [store.contract_file or "SCHEMA.json", *frames],
            "hashes": {},
            "action": (
                "Operator-chosen path memory-migrate with --batch contract-file, then re-run "
                "atlas-optimise plan. Optimise does not run memory-migrate and apply refuses "
                "until this clears."
            ),
            "evidence": {
                "contract_file": store.contract_file,
                "atlas_release": store.schema.get("atlas_release"),
                "frame_pages": frames,
            },
        }
        tasks.append(precondition)

    keys = sorted(scope.page_keys)
    by_folder: dict[str, list[str]] = {}
    for k in store.pages:
        by_folder.setdefault(store.folder(k), []).append(k)

    # --- index files in target: dead cues, layer-skip cues, schema cues
    index_files = [
        p for p in store.md_files
        if p.name == "index.md" and _rel(root, p) in scope.index_keys and _is_index_scope(root, p)
    ]
    for idx in index_files:
        ikey = _rel(root, idx)
        folder = store.folder(ikey)
        folder_schemas = [k for k in by_folder.get(folder, []) if store.ptype(k) == "schema"]
        lines = idx.read_text(encoding="utf-8", errors="replace").splitlines()
        for n, line in enumerate(lines, 1):
            links = _local_links(line)
            if not links:
                continue
            dead = [l for l in links if not store.resolve_local(idx, l).exists()]
            if dead:
                cls = "auto" if (LIST_ITEM.match(line) and len(links) == 1) else "confirm"
                if not LIST_ITEM.match(line):
                    cls = "report"
                tasks.append(_task(
                    "dead-index-cue", cls, [ikey],
                    f"remove line {n} of {ikey}: cue target {dead[0]} does not exist",
                    {"line": line, "dead": dead}, store, tid=f"dead-index-cue:{ikey}:{dead[0]}"))
                continue
            if folder_schemas and LIST_ITEM.match(line) and len(links) == 1:
                tgt = store.resolve_local(idx, links[0])
                try:
                    tkey = _rel(root, tgt)
                except ValueError:
                    continue
                if tkey in store.pages and store.folder(tkey) == folder and store.ptype(tkey) in ("gist", "memory"):
                    tasks.append(_task(
                        "layer-skip-cue", "confirm", [ikey],
                        f"remove line {n} of {ikey}: index cues {store.ptype(tkey)} page {tkey} "
                        "directly; recall reaches it through the folder schema",
                        {"line": line, "target_type": store.ptype(tkey)}, store,
                        tid=f"layer-skip-cue:{ikey}:{links[0]}"))

    # --- schema pages: index cue + dead members
    for k in keys:
        if store.ptype(k) != "schema":
            continue
        path, meta, _ = store.pages[k]
        idx = path.parent / "index.md"
        cued = False
        if idx.is_file():
            for link in _local_links(idx.read_text(encoding="utf-8", errors="replace")):
                if store.resolve_local(idx, link) == path.resolve():
                    cued = True
                    break
        if not cued:
            title = str(meta.get("title") or "").strip() or path.name
            tasks.append(_task(
                "schema-index-cue", "auto", [k, _rel(root, idx) if idx.exists() else store.folder(k) + "/index.md"],
                f"append a cue for {path.name} to {store.folder(k)}/index.md labelled with the schema title",
                {"title": title}, store))
        for item in _live_relates(meta):
            if _kind(item) != "related":
                continue
            ck = store.canonical(str(item.get("path") or ""))
            if ck is not None and not (root / ck).exists():
                tasks.append(_task(
                    "dead-schema-member", "auto", [k],
                    f"remove relates_to entry {item.get('path')} from {k}: target missing",
                    {"member": item.get("path")}, store, tid=f"dead-schema-member:{k}:{ck}"))

    # --- gists: coverage + stale description
    covered: set[str] = set()
    for k, (path, meta, _) in store.pages.items():
        if store.ptype(k) != "schema":
            continue
        for item in _live_relates(meta):
            ck = store.canonical(str(item.get("path") or ""))
            if _kind(item) == "related" and ck in store.pages and store.folder(ck) == store.folder(k):
                covered.add(ck)
    for k in keys:
        if store.ptype(k) != "gist":
            continue
        path, meta, _ = store.pages[k]
        folder = store.folder(k)
        if k not in covered:
            schemas = sorted(s for s in by_folder.get(folder, []) if store.ptype(s) == "schema")
            if len(schemas) == 1:
                tasks.append(_task(
                    "uncovered-gist", "auto", [schemas[0], k],
                    f"add {k} to relates_to (kind related) of the only folder schema {schemas[0]}",
                    {"schema": schemas[0]}, store, tid=f"uncovered-gist:{k}"))
            else:
                why = "no schema in folder: path memory-migrate --batch contract-file or path remember" if not schemas \
                    else "several schemas in folder: operator picks the owning schema, then path remember"
                tasks.append(_task("uncovered-gist", "handoff", [k], why, {"schemas": schemas}, store,
                                   tid=f"uncovered-gist:{k}"))
        desc = meta.get("description")
        if not isinstance(desc, str) or not desc:
            continue
        memory_parents = []
        for item in _live_relates(meta):
            if _kind(item) != "derived_from":
                continue
            mk = store.canonical(str(item.get("path") or ""))
            if mk not in store.pages or store.ptype(mk) != "memory":
                continue
            memory_parents.append(mk)
        if not memory_parents:
            continue
        if any(
            desc in store.pages[mk][2]
            or (isinstance(store.pages[mk][1].get("description"), str) and desc in store.pages[mk][1]["description"])
            for mk in memory_parents
        ):
            continue
        mk = memory_parents[0]
        if len(memory_parents) > 1:
            tasks.append(_task(
                "stale-gist-description", "handoff", [k, *memory_parents],
                "shared gist description is not a substring of any derived_from memory parent; "
                "path remember chooses an exact sentence. Optimise writes nothing here.",
                {"gist_description": desc, "parents": memory_parents}, store,
                tid=f"stale-gist-description:{k}"))
            continue
        mpath, mmeta, _mbody = store.pages[mk]
        mdesc = mmeta.get("description")
        mlines = _fm_lines(mpath.read_text(encoding="utf-8", errors="replace"))
        glines = _fm_lines(path.read_text(encoding="utf-8", errors="replace"))
        raw = _single_line_value(mlines[0], "description") if mlines else None
        graw = _single_line_value(glines[0], "description") if glines else None
        if isinstance(mdesc, str) and mdesc.strip() and raw and graw:
            tasks.append(_task(
                "stale-gist-description", "auto", [k, mk],
                f"set gist description of {k} to the memory description of {mk} verbatim "
                "(copy up; the memory page is not edited)",
                {"gist_description": desc, "memory_description": mdesc}, store))
        else:
            tasks.append(_task(
                "stale-gist-description", "handoff", [k, mk],
                "memory has no plain one-line description to copy up; path remember chooses "
                "an exact sentence of the memory body. Optimise writes nothing here.",
                {"gist_description": desc}, store))

    # --- suffixes (opt-in)
    for k in keys:
        t = store.ptype(k)
        if t not in LAYER_TYPES or k.endswith(LAYER_SUFFIX[t]):
            continue
        base = k[:-3] if k.endswith(".md") else k
        for other in LAYER_SUFFIX.values():
            if base.endswith(other[:-3]):
                base = base[: -len(other[:-3])]
        new_key = base + LAYER_SUFFIX[t]
        reasons = _move_gates(store, k, new_key)
        refs = _referrers(store, k)
        tasks.append(_task(
            "layer-suffix", "blocked" if reasons else "opt-in", [k],
            f"rename {k} -> {new_key} and rewrite {len(refs)} referring file(s)",
            {"new_path": new_key, "referrers": refs, "blocked_by": reasons,
             "note": "stores outside this root are not scanned"},
            store, extra_hash=refs))

    # --- clustering by subject naming
    groups: dict[str, list[str]] = {}
    for k in keys:
        t = store.ptype(k)
        if t in ("schema", "gist", "frame", "work") or store.in_claimed(k) or Path(k).name == "hub.md":
            continue
        stem = Path(k).name[:-3]
        for suf in (".memory", ".gist", ".schema"):
            if stem.endswith(suf):
                stem = stem[: -len(suf)]
        groups.setdefault(stem, []).append(k)
    operator = {stem: folder.strip("/") or "." for folder, stem in subject_folders}
    for stem, members in sorted(groups.items()):
        folders = sorted({store.folder(m) for m in members})
        if stem in operator:
            dest = operator[stem]
            for m in members:
                if store.folder(m) == dest:
                    continue
                new_key = (dest + "/" if dest != "." else "") + Path(m).name
                reasons = _move_gates(store, m, new_key)
                if store.ptype(m) in LAYER_TYPES:
                    reasons.append("layer page: schema coverage changes; use path remember")
                refs = _referrers(store, m)
                tasks.append(_task(
                    "subject-cluster", "blocked" if reasons else "confirm", [m],
                    f"move {m} -> {new_key} (operator subject folder) and rewrite {len(refs)} referring file(s)",
                    {"subject": stem, "new_path": new_key, "referrers": refs, "blocked_by": reasons},
                    store, extra_hash=refs, tid=f"subject-cluster:{m}"))
        elif len(folders) > 1:
            tasks.append(_task(
                "subject-cluster", "report", sorted(members),
                f"subject '{stem}' appears in {', '.join(folders)}; no move proposed (no operator "
                "subject folder; same filename cannot share one folder). Name one with "
                f"--subject-folder <folder>:{stem} to plan moves.",
                {"subject": stem, "folders": folders}, store, tid=f"subject-cluster:{stem}"))
    for k in keys:
        path, meta, _ = store.pages[k]
        wid = str(meta.get("work_id") or "").strip()
        t = store.ptype(k)
        if not wid or t == "work" or t in LAYER_TYPES or "/" in wid or ":" in wid:
            continue
        dest = f"work/{wid}"
        if not (root / dest).is_dir() or store.folder(k) == dest or Path(k).name == "hub.md":
            continue
        new_key = f"{dest}/{Path(k).name}"
        reasons = _move_gates(store, k, new_key)
        refs = _referrers(store, k)
        tasks.append(_task(
            "work-cluster", "blocked" if reasons else "confirm", [k],
            f"move {k} -> {new_key} (its work_id folder) and rewrite {len(refs)} referring file(s)",
            {"work_id": wid, "new_path": new_key, "referrers": refs, "blocked_by": reasons},
            store, extra_hash=refs))

    _plan_fills(store, scope, tasks, auto_verbatim, tidy_only)
    _gate_security(tasks)

    if precondition:
        for t in tasks:
            if t is not precondition and t["class"] in ("auto", "opt-in", "confirm"):
                t["class_after_precondition"] = t["class"]
                t["class"] = "blocked"
                t.setdefault("evidence", {})["blocked_by_precondition"] = True

    # --- per top-level folder grouping
    head, dirty = _head(root)
    folders = _top_folders(root, target)
    grouped: dict[str, list[dict]] = {f: [] for f in folders}
    for t in tasks:
        grouped.setdefault(t["folder"], []).append(t)
    for f in grouped:
        grouped[f].sort(key=lambda t: (CLASS_ORDER.index(t["class"]), t["kind"], t["id"]))
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t["class"]] = counts.get(t["class"], 0) + 1
    security_summary = _security_summary(tasks)
    residuals = _residuals(store, scope, tasks)
    cost = {
        "unit": "pages",
        "projected": scope.projected,
        "ceiling": cost_ceiling,
        "within_ceiling": scope.projected <= cost_ceiling,
        "note": "pages examined in the resolved scope (concept pages and index files)",
    }
    plan = {
        "schema": "atlas-optimise-plan/v1",
        "source": {
            "root": str(root),
            "target": target,
            "head": head,
            "dirty": dirty,
            "fetch_ok": head is not None,
            "optimise_mode": mode,
            "since_hours": scope.since_hours,
            "custom_tree": list(scope.custom_trees),
            "tidy_only": tidy_only,
            "auto_verbatim": auto_verbatim,
            "fill_sensible": not tidy_only,
            "cost_ceiling": cost_ceiling,
            "pilot": pilot,
            "serial_full_only": True,
            "contract_file": store.contract_file,
            "contract_sha256": _sha(root / store.contract_file) if store.contract_file else None,
            "atlas_release": store.schema.get("atlas_release"),
            "package_version": PACKAGE_VERSION,
        },
        "precondition": precondition,
        "folders": grouped,
        "counts": {"tasks": len(tasks), **counts},
        "unreadable": store.unreadable,
        "security_summary": security_summary,
        "residuals": residuals,
        "cost": cost,
    }
    plan["receipt"] = _receipt(plan, phase="plan")
    return plan


def _is_index_scope(root: Path, path: Path) -> bool:
    parts = path.relative_to(root).parts
    return not parts or parts[0] not in NON_CONCEPT_DIRS


def _top_folders(root: Path, target: str) -> list[str]:
    if target != ".":
        return [target.split("/", 1)[0]]
    out = ["."]
    for d in sorted(root.iterdir()):
        if d.is_dir() and d.name not in (".git", "staging") and any(d.rglob("*.md")):
            out.append(d.name)
    return out


# ---------------------------------------------------------------------------
# task list rendering


def render_folder(folder: str, tasks: list[dict], source: dict, mentions: list[dict] | None = None) -> str:
    name = "store root" if folder == "." else folder + "/"
    lines = [
        f"# atlas-optimise tasks: {name}",
        "",
        f"Source: `{source['root']}` at `{source['head']}` (dirty: {source['dirty']}); "
        f"target `{source['target']}`; mode `{source.get('optimise_mode', 'path')}`; "
        f"contract `{source['contract_file']}` "
        f"`{source['atlas_release']}`; helper {source['package_version']}.",
        "",
        "Classes: auto = apply does it; opt-in = needs --include-opt-in; confirm = needs "
        "--confirm <id>; handoff = another path does it; report = information; blocked = "
        "a gate failed.",
        "",
    ]
    if folder in NON_CONCEPT_DIRS:
        lines.append("Not a concept folder (templates, overlays, staging). Optimise does not edit it.")
    if not tasks:
        lines.append("No optimise tasks.")
    for t in tasks:
        box = "[ ]" if t["class"] in ("auto", "opt-in", "confirm", "handoff") else "[-]"
        after = f" (after precondition: {t['class_after_precondition']})" if t.get("class_after_precondition") else ""
        lines.append(f"- {box} **{t['class']}**{after} `{t['id']}`")
        lines.append(f"  - {t['action']}")
        blocked = (t.get("evidence") or {}).get("blocked_by")
        if blocked:
            lines.append(f"  - blocked by: {'; '.join(blocked)}")
    for t in mentions or []:
        lines.append(f"- [-] see `{t['folder']}` list: **{t['class']}** `{t['id']}` also names this folder")
    return "\n".join(lines) + "\n"


def write_out(plan: dict, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tasks").mkdir(exist_ok=True)
    written = []
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append(str(out_dir / "plan.json"))
    all_tasks = [t for ts in plan["folders"].values() for t in ts]
    for folder, tasks in plan["folders"].items():
        fname = "root.md" if folder == "." else folder.replace("/", "__") + ".md"
        path = out_dir / "tasks" / fname
        mentions = [
            t for t in all_tasks
            if t["folder"] != folder and any(p.split("/", 1)[0] == folder for p in t["paths"] if "/" in p)
        ]
        path.write_text(render_folder(folder, tasks, plan["source"], mentions), encoding="utf-8")
        written.append(str(path))
    if plan.get("receipt") is not None:
        receipt_path = out_dir / "receipt.json"
        receipt_path.write_text(
            json.dumps(plan["receipt"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written.append(str(receipt_path))
    return written


# ---------------------------------------------------------------------------
# apply


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _remove_line(path: Path, line: str) -> bool:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    for i, l in enumerate(lines):
        if l.rstrip("\r\n") == line:
            del lines[i]
            _write(path, "".join(lines))
            return True
    return False


def _apply_stale_gist(store: Store, t: dict) -> None:
    gkey, mkey = t["paths"]
    gpath, mpath = store.root / gkey, store.root / mkey
    gtext = gpath.read_text(encoding="utf-8")
    glines, grest = _fm_lines(gtext)
    mlines, _ = _fm_lines(mpath.read_text(encoding="utf-8"))
    gi, _ = _single_line_value(glines, "description")
    _, mraw = _single_line_value(mlines, "description")
    old = glines[gi]
    glines[gi] = "description: " + mraw + ("\n" if old.endswith("\n") else "")
    _write(gpath, "".join(glines) + grest)
    gmeta, _ = read_page(gpath, store.version)
    mmeta, mbody = read_page(mpath, store.version)
    new = gmeta.get("description")
    if not (isinstance(new, str) and new and (new in mbody or new in str(mmeta.get("description") or ""))):
        _write(gpath, gtext)
        raise Refusal(f"{gkey}: copied description did not round-trip; reverted")


def _apply_relates_add(store: Store, schema_key: str, gist_key: str) -> None:
    path = store.root / schema_key
    text = path.read_text(encoding="utf-8")
    lines, rest = _fm_lines(text)
    blk = _relates_block(lines)
    entry_style = ("  - path: ", "    kind: related\n")
    if blk:
        spans = _item_spans(lines, *blk)
        if spans:
            first = lines[spans[0][0]]
            indent = re.match(r"^(\s*)-", first).group(1)
            entry_style = (f"{indent}- path: ", f"{indent}  kind: related\n")
        insert_at = spans[-1][1] if spans else blk[0] + 1
        while insert_at > blk[0] + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        new = [entry_style[0] + gist_key + "\n", entry_style[1]]
        lines[insert_at:insert_at] = new
    else:
        lines[-1:-1] = []
        lines.append("relates_to:\n")
        lines.append(entry_style[0] + gist_key + "\n")
        lines.append(entry_style[1])
    _write(path, "".join(lines) + rest)
    meta, _ = read_page(path, store.version)
    if not any(store.canonical(str(i.get("path") or "")) == gist_key and _kind(i) == "related" for i in _live_relates(meta)):
        _write(path, text)
        raise Refusal(f"{schema_key}: relates_to edit did not round-trip; reverted")


def _apply_relates_remove(store: Store, schema_key: str, member: str) -> None:
    path = store.root / schema_key
    text = path.read_text(encoding="utf-8")
    lines, rest = _fm_lines(text)
    blk = _relates_block(lines)
    if not blk:
        return
    for span in reversed(_item_spans(lines, *blk)):
        if _item_path(lines, span) == member:
            del lines[span[0]:span[1]]
            break
    _write(path, "".join(lines) + rest)


def _apply_schema_cue(store: Store, t: dict) -> None:
    skey = t["paths"][0]
    spath = store.root / skey
    idx = spath.parent / "index.md"
    title = t["evidence"]["title"].replace("[", "(").replace("]", ")")
    text = idx.read_text(encoding="utf-8") if idx.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    _write(idx, text + f"- [{title}](./{spath.name})\n")


def _rewrite_refs(store: Store, old_key: str, new_key: str, referrers: list[str]) -> None:
    old_file = (store.root / old_key).resolve()
    new_file = (store.root / new_key).resolve()
    for rkey in referrers:
        rpath = store.root / rkey
        text = rpath.read_text(encoding="utf-8")

        def fm_sub(m: re.Match) -> str:
            val = m.group(3)
            if store.canonical(val) == old_key:
                return m.group(1) + m.group(2) + new_key + m.group(4)
            return m.group(0)

        text = re.sub(r"^(\s*-?\s*path:\s*)([\"']?)([^\"'\n]+?)([\"']?\s*)$", fm_sub, text, flags=re.M)

        def link_sub(m: re.Match) -> str:
            target = m.group(2)
            if target.startswith(REMOTE_PREFIXES):
                return m.group(0)
            base, sep, frag = target.partition("#")
            if store.resolve_local(rpath, base) != old_file:
                return m.group(0)
            new_rel = os.path.relpath(new_file, rpath.parent).replace("\\", "/")
            if base.startswith("./") and not new_rel.startswith("."):
                new_rel = "./" + new_rel
            return f"[{m.group(1)}]({new_rel}{sep}{frag}{m.group(3)})"

        text = MD_LINK.sub(link_sub, text)
        _write(rpath, text)


def _apply_move(store: Store, t: dict) -> None:
    old_key = t["paths"][0]
    new_key = t["evidence"]["new_path"]
    old_path, new_path = store.root / old_key, store.root / new_key
    referrers = _referrers(store, old_key)
    _rewrite_refs(store, old_key, new_key, referrers)
    text = old_path.read_text(encoding="utf-8")

    def own_link(m: re.Match) -> str:
        target = m.group(2)
        if target.startswith(REMOTE_PREFIXES):
            return m.group(0)
        base, sep, frag = target.partition("#")
        resolved = store.resolve_local(old_path, base)
        if resolved is None or not resolved.exists():
            return m.group(0)
        new_rel = os.path.relpath(resolved, new_path.parent).replace("\\", "/")
        return f"[{m.group(1)}]({new_rel}{sep}{frag}{m.group(3)})"

    if old_path.parent != new_path.parent:
        text = MD_LINK.sub(own_link, text)
    new_path.write_text(text, encoding="utf-8")
    old_path.unlink()


def _render_gist(proposed: dict, parent_keys: list[str]) -> str:
    description = _yaml_scalar(proposed["description"])
    title = _yaml_scalar(proposed["title"])
    if description is None or title is None:
        raise Refusal("gist text cannot be written as a one-line scalar")
    if not parent_keys:
        raise Refusal("gist has no derived_from parent")
    if len(set(parent_keys)) != len(parent_keys):
        raise Refusal("gist derived_from parents must be unique")
    sensitivity = proposed.get("sensitivity") or "internal"
    if sensitivity not in ("public", "internal"):
        sensitivity = "internal"
    body = str(proposed["body"]).rstrip() + "\n"
    relates = "".join(f"  - path: {parent_key}\n    kind: derived_from\n" for parent_key in parent_keys)
    return (
        "---\n"
        "type: gist\n"
        f"title: {title}\n"
        f"created: {proposed['created']}\n"
        f"description: {description}\n"
        "origin: derived\n"
        f"sensitivity: {sensitivity}\n"
        "relates_to:\n"
        f"{relates}"
        "---\n"
        "\n"
        "## Content\n"
        "\n"
        f"{body}"
    )


def _render_schema(proposed: dict, members: list[dict]) -> str:
    title = _yaml_scalar(proposed["title"])
    if title is None:
        raise Refusal("schema title cannot be written as a one-line scalar")
    description = proposed.get("description") or ""
    desc_line = ""
    if description:
        scalar = _yaml_scalar(description)
        if scalar is None:
            raise Refusal("schema description cannot be written as a one-line scalar")
        desc_line = f"description: {scalar}\n"
    rels = "".join(
        f"  - path: {member['path']}\n    kind: related\n" for member in members
    )
    body = str(proposed["body"]).rstrip() + "\n"
    return (
        "---\n"
        "type: schema\n"
        f"title: {title}\n"
        f"created: {proposed['created']}\n"
        f"{desc_line}"
        "origin: derived\n"
        "sensitivity: internal\n"
        "relates_to:\n"
        f"{rels}"
        "---\n"
        "\n"
        "## Content\n"
        "\n"
        f"{body}"
    )


def _task_parents(task: dict) -> list[str]:
    evidence = task.get("evidence") or {}
    parents = list(evidence.get("parents") or [])
    if not parents and evidence.get("parent"):
        parents = [evidence["parent"]]
    return parents


def _assert_extract_matches(store: Store, task: dict) -> dict:
    parents = _task_parents(task)
    if not parents or any(parent not in store.pages for parent in parents):
        raise Refusal(f"{task['id']}: evidence parent missing")
    if len({store.folder(parent) for parent in parents}) != 1:
        raise Refusal(f"{task['id']}: shared gist parents must stay in one folder")
    pack = _cluster_pack(store, parents)
    if pack["security_blocked"] or not pack["sufficient"]:
        raise Refusal(f"{task['id']}: evidence insufficient or blocked at apply")
    if task["evidence"].get("extract") != pack["extract"]:
        raise Refusal(
            f"{task['id']}: proposed gist text is not the evidence-pack extract"
        )
    anchor = pack.get("extract_parent") or parents[0]
    meta, body = store.pages[anchor][1], store.pages[anchor][2]
    if not _grounded(pack["extract"], meta, body):
        raise Refusal(f"{task['id']}: extract is not a verbatim substring of the parent")
    if len(_claim_prose(str(pack.get("body") or ""))) < MIN_PROSE_CHARS:
        raise Refusal(f"{task['id']}: gist body is not evidence-grade")
    return pack


def _apply_missing_gist(store: Store, task: dict) -> None:
    pack = _assert_extract_matches(store, task)
    proposed = task["evidence"].get("proposed") or {}
    new_key = task["evidence"].get("new_path")
    parents = _task_parents(task)
    if not new_key or proposed.get("description") != pack["extract"]:
        raise Refusal(f"{task['id']}: proposed gist text is not the evidence-pack extract")
    dest = store.root / new_key
    if dest.exists():
        raise Refusal(f"{new_key} appeared after plan")
    if pack.get("body") != proposed.get("body"):
        raise Refusal(f"{task['id']}: proposed gist body is not the evidence pack")
    text = _render_gist({**proposed, "description": pack["extract"], "body": pack["body"]}, parents)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write(dest, text)
    try:
        gmeta, gbody = read_page(dest, store.version)
    except FrontmatterError as e:
        dest.unlink(missing_ok=True)
        raise Refusal(f"{new_key}: gist did not round-trip") from e
    anchor = pack.get("extract_parent") or parents[0]
    ameta, abody = store.pages[anchor][1], store.pages[anchor][2]
    if gmeta.get("description") != pack["extract"] or not _grounded(pack["extract"], ameta, abody):
        dest.unlink(missing_ok=True)
        raise Refusal(f"{new_key}: copied description did not round-trip; removed")
    if pack["extract"] not in gbody and pack["extract"] not in str(gmeta.get("description") or ""):
        dest.unlink(missing_ok=True)
        raise Refusal(f"{new_key}: gist body dropped the evidence extract; removed")


def _set_description_line(lines: list[str], value: str) -> None:
    scalar = _yaml_scalar(value)
    if scalar is None:
        raise Refusal("description cannot be written as a one-line scalar")
    rendered = f"description: {scalar}\n"
    found = _single_line_value(lines, "description")
    if found:
        lines[found[0]] = rendered
        return
    for index, line in enumerate(lines):
        if re.match(r"^relates_to:\s*$", line):
            lines.insert(index, rendered)
            return
    if lines and lines[-1].strip() == "---":
        lines.insert(len(lines) - 1, rendered)
    else:
        lines.append(rendered)


def _apply_gist_enrich(store: Store, task: dict) -> None:
    pack = _assert_extract_matches(store, task)
    proposed = task["evidence"].get("proposed") or {}
    gist_key = task["paths"][0]
    if proposed.get("description") != pack["extract"]:
        raise Refusal(f"{task['id']}: proposed gist text is not the evidence-pack extract")
    gpath = store.root / gist_key
    original = gpath.read_text(encoding="utf-8")
    parsed = _fm_lines(original)
    if parsed is None:
        raise Refusal(f"{gist_key}: missing frontmatter")
    lines, _rest = parsed
    if pack.get("body") != proposed.get("body"):
        raise Refusal(f"{task['id']}: proposed gist body is not the evidence pack")
    _set_description_line(lines, pack["extract"])
    _write(gpath, "".join(lines) + "---\n\n## Content\n\n" + str(pack["body"]).rstrip() + "\n")
    try:
        gmeta, gbody = read_page(gpath, store.version)
    except FrontmatterError as e:
        _write(gpath, original)
        raise Refusal(f"{gist_key}: enrich did not round-trip; reverted") from e
    if gmeta.get("description") != pack["extract"] or pack["extract"] not in gbody:
        _write(gpath, original)
        raise Refusal(f"{gist_key}: enrich did not round-trip; reverted")


def _apply_schema_fill(store: Store, task: dict) -> None:
    proposed = task["evidence"].get("proposed") or {}
    members = list(task["evidence"].get("members") or [])
    schema_key = proposed.get("path")
    if not schema_key or not members:
        raise Refusal(f"{task['id']}: schema fill has no evidence")
    prose = _minimal_schema_prose(members)
    if prose is None or prose != proposed.get("body"):
        raise Refusal(f"{task['id']}: schema prose is not the minimal evidence blurb")
    for member in members:
        path = store.root / member["path"]
        if not path.is_file():
            raise Refusal(f"{task['id']}: schema member {member['path']} missing at apply")
        try:
            meta, _body = read_page(path, store.version)
        except FrontmatterError as e:
            raise Refusal(f"{task['id']}: unreadable schema member") from e
        title = str(meta.get("title") or "").strip()
        desc = meta.get("description")
        description = desc.strip() if isinstance(desc, str) else ""
        if title != member.get("title") or description != (member.get("description") or ""):
            raise Refusal(f"{task['id']}: schema evidence does not match {member['path']}")
        blob = f"{title}\n{description}"
        if _scan_findings(blob) or str(meta.get("sensitivity") or "").strip().lower() == "restricted":
            raise Refusal(f"{task['id']}: security scan blocked schema promotion")
    if _scan_findings(prose):
        raise Refusal(f"{task['id']}: security scan blocked schema promotion")
    dest = store.root / schema_key
    if dest.exists():
        raise Refusal(f"{schema_key} appeared after plan")
    text = _render_schema(proposed, members)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write(dest, text)
    try:
        meta, body = read_page(dest, store.version)
    except FrontmatterError as e:
        dest.unlink(missing_ok=True)
        raise Refusal(f"{schema_key}: schema did not round-trip") from e
    related = {
        store.canonical(str(item.get("path") or ""))
        for item in _live_relates(meta)
        if _kind(item) == "related"
    }
    if any(member["path"] not in related for member in members) or prose not in body:
        dest.unlink(missing_ok=True)
        raise Refusal(f"{schema_key}: schema prose did not round-trip; removed")
    _cue_schema(store.root, schema_key, str(meta.get("title") or proposed["title"]))


def _cue_schema(root: Path, schema_key: str, title: str) -> None:
    spath = root / schema_key
    idx = spath.parent / "index.md"
    label = title.replace("[", "(").replace("]", ")")
    link = f"- [{label}](./{spath.name})\n"
    if idx.exists():
        text = idx.read_text(encoding="utf-8")
        if f"](./{spath.name})" in text or f"]({spath.name})" in text:
            return
        if text and not text.endswith("\n"):
            text += "\n"
        _write(idx, text + link)
        return
    _write(idx, f"# {spath.parent.name}\n\n{link}")


def _parent_snapshot(root: Path, store: Store, selected: list[dict]) -> dict[str, bytes]:
    parents: set[str] = set()
    for task in selected:
        evidence = task.get("evidence") or {}
        for parent in _task_parents(task):
            parents.add(parent)
        if task["kind"] == "stale-gist-description" and len(task["paths"]) > 1:
            parents.add(task["paths"][1])
    snapshot = {}
    for key in parents:
        path = root / key
        if path.is_file():
            snapshot[key] = path.read_bytes()
    return snapshot


def _preflight_apply(root: Path, store: Store, selected: list[dict]) -> None:
    for task in selected:
        if task["kind"] not in PROMOTION_KINDS:
            continue
        if _scan_findings(_live_promotion_text(store, task)) or _live_restricted(store, task):
            raise Refusal(f"{task['id']}: security scan blocked promotion")
        if task["kind"] != "schema-fill":
            continue
        for member in (task.get("evidence") or {}).get("members") or []:
            path = member.get("path")
            exists = bool(path) and (root / path).exists()
            created = any(
                other["kind"] == "missing-gist-fill" and (other.get("evidence") or {}).get("new_path") == path
                for other in selected
            )
            if not exists and not created:
                raise Refusal(
                    f"{task['id']}: schema member {path} is not on disk and is not created by this apply"
                )


def _invocation(plan: dict) -> dict:
    source = plan.get("source") or {}
    return {
        "mode": source.get("optimise_mode") or "path",
        "custom_trees": list(source.get("custom_tree") or []),
        "since_hours": source.get("since_hours"),
        "tidy_only": bool(source.get("tidy_only")),
        "auto_verbatim": bool(source.get("auto_verbatim")),
        "cost_ceiling": source.get("cost_ceiling") if source.get("cost_ceiling") is not None else DEFAULT_COST_CEILING,
        "pilot": bool(source.get("pilot")),
    }


def apply_plan(root: Path, target: str, plan: dict, include_opt_in: bool, confirm: list[str]) -> dict:
    src = plan.get("source") or {}
    if Path(src.get("root", "")).resolve() != root:
        raise Refusal("plan was made for a different root")
    if src.get("target") != target:
        raise Refusal(f"plan target {src.get('target')!r} differs from --target {target!r}")
    if plan.get("precondition"):
        raise Refusal("contract precondition open: run path memory-migrate (operator-chosen) and re-plan")
    head, _ = _head(root)
    if src.get("head") and head != src.get("head"):
        raise Refusal(f"stale plan: HEAD {head} != planned {src.get('head')}; re-run plan")
    contract_before = {n: _sha(root / n) for n in CONTRACT_FILENAMES}

    all_tasks = [t for ts in plan["folders"].values() for t in ts]
    known = {t["id"] for t in all_tasks}
    unknown = [c for c in confirm if c not in known]
    if unknown:
        raise Refusal("unknown --confirm id(s): " + ", ".join(unknown))
    selected = [
        t for t in all_tasks
        if t["class"] == "auto"
        or (t["class"] == "opt-in" and include_opt_in)
        or (t["class"] == "confirm" and t["id"] in confirm)
    ]
    bad_confirm = [t["id"] for t in all_tasks if t["id"] in confirm and t["class"] != "confirm"]
    if bad_confirm:
        raise Refusal("--confirm only accepts confirm-class tasks: " + ", ".join(bad_confirm))
    for t in selected:
        for p, h in t["hashes"].items():
            if _sha(root / p) != h:
                raise Refusal(f"stale plan: {p} changed since plan; re-run plan")
    selected.sort(key=lambda t: (APPLY_ORDER.index(t["kind"]), t["id"]))

    applied = []
    store = Store(root)
    _preflight_apply(root, store, selected)
    parents_before = _parent_snapshot(root, store, selected)
    for t in selected:
        kind = t["kind"]
        if kind == "missing-gist-fill":
            _apply_missing_gist(store, t)
        elif kind == "gist-body-enrich":
            _apply_gist_enrich(store, t)
        elif kind == "schema-fill":
            _apply_schema_fill(store, t)
        elif kind in ("dead-index-cue", "layer-skip-cue"):
            _remove_line(root / t["paths"][0], t["evidence"]["line"])
        elif kind == "dead-schema-member":
            _apply_relates_remove(store, t["paths"][0], t["evidence"]["member"])
        elif kind == "uncovered-gist":
            _apply_relates_add(store, t["paths"][0], t["paths"][1])
        elif kind == "stale-gist-description":
            _apply_stale_gist(store, t)
        elif kind == "schema-index-cue":
            _apply_schema_cue(store, t)
        elif kind in ("layer-suffix", "subject-cluster", "work-cluster"):
            store = Store(root)
            reasons = _move_gates(store, t["paths"][0], t["evidence"]["new_path"])
            if reasons:
                raise Refusal(f"{t['id']}: gate failed at apply: {'; '.join(reasons)}")
            _apply_move(store, t)
            store = Store(root)
        else:
            raise Refusal(f"{t['id']}: unknown task kind {kind}")
        applied.append(t["id"])

    parent_edits = 0
    for key, blob in parents_before.items():
        if (root / key).read_bytes() != blob:
            parent_edits += 1
    if parent_edits:
        raise Refusal("optimise edited parent claim text")
    if {n: _sha(root / n) for n in CONTRACT_FILENAMES} != contract_before:
        raise Refusal("contract file changed during apply; this helper never writes contracts")
    options = _invocation(plan)
    residual = plan_store(
        root, target, [], enforce_ceiling=False, **options,
    )
    receipt = _receipt(residual, phase="apply", applied=applied, parent_edits=parent_edits)
    return {
        "schema": "atlas-optimise-apply/v1",
        "root": str(root),
        "target": target,
        "applied": applied,
        "residual_counts": residual["counts"],
        "residual": {f: ts for f, ts in residual["folders"].items() if ts},
        "receipt": receipt,
    }


# ---------------------------------------------------------------------------
# CLI


def _resolve_target(root: Path, target: str) -> str:
    t = target.strip().strip("/") or "."
    if t == ".":
        return "."
    path = root / t
    if path.is_symlink() or not path.is_dir():
        raise Refusal(f"target {target!r} is not a directory inside the store")
    try:
        return _rel(root, path)
    except ValueError as e:
        raise Refusal(f"target {target!r} escapes the store root") from e


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="atlas_optimise.py",
        description="atlas-optimise helper (operator-chosen; never on install or compile).",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_plan = sub.add_parser("plan", help="dry-run: list tasks per top-level folder; writes nothing in the store")
    p_apply = sub.add_parser("apply", help="apply auto tasks (+ opt-in / confirmed) from a plan.json")
    for p in (p_plan, p_apply):
        p.add_argument("--root", required=True, help="Atlas store root")
        p.add_argument("--target", required=True, help="folder inside the store, or . for the store root")
        p.add_argument("--json", action="store_true", help="print the full JSON result")
    p_plan.add_argument("--out-dir", help="write plan.json, receipt.json, and tasks/<folder>.md here (must be outside the store)")
    p_plan.add_argument("--subject-folder", action="append", default=[],
                        help="operator-named subject folder as <folder>:<stem>; plans confirm-class moves")
    p_plan.add_argument("--optimise-mode", default="path", choices=OPTIMISE_MODES,
                        help="path (default, fill on), full (target must be .; serial only), "
                             "custom (--custom-tree prefixes), or incremental (git commit window)")
    p_plan.add_argument("--since-hours", type=int, default=None,
                        help="incremental committer-clock window in hours (default 24). "
                             "Also filters custom mode. Refused on path and full.")
    p_plan.add_argument("--custom-tree", action="append", default=[],
                        help="custom mode path prefix inside the store; repeatable. "
                             "Refused on path and full. With incremental, intersects the git window.")
    p_plan.add_argument("--tidy-only", action="store_true",
                        help="tidy repairs only; do not plan fill tasks")
    p_plan.add_argument("--auto-verbatim", action="store_true",
                        help="opt in: verbatim evidence-pack fill may be auto. Confirm stays the default.")
    p_plan.add_argument("--fill-sensible", action="store_true",
                        help="name the default posture: useful same-folder gists when evidence supports; "
                             "residual missing_gist stays OK. Does not force every indexed page.")
    p_plan.add_argument("--cost-ceiling", type=int, default=DEFAULT_COST_CEILING,
                        help=f"max pages examined in the resolved scope (default {DEFAULT_COST_CEILING})")
    p_plan.add_argument("--pilot", action="store_true",
                        help="record this run as a pilot. The receipt still does not authorize fleet apply.")
    p_apply.add_argument("--plan", required=True, help="plan.json produced by plan")
    p_apply.add_argument("--include-opt-in", action="store_true", help="also apply opt-in tasks (suffix renames)")
    p_apply.add_argument("--confirm", action="append", default=[], help="apply this confirm-class task id")
    args = ap.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    try:
        if not root.is_dir():
            raise Refusal(f"root {args.root!r} is not a directory")
        target = _resolve_target(root, args.target)
        if args.cmd == "plan":
            subject_folders = []
            for spec in args.subject_folder:
                if ":" not in spec:
                    raise Refusal(f"--subject-folder expects <folder>:<stem>, got {spec!r}")
                folder, stem = spec.split(":", 1)
                subject_folders.append((folder, stem))
            written: list[str] = []
            if args.out_dir:
                out = Path(args.out_dir).expanduser().resolve()
                if out == root or root in out.parents:
                    raise Refusal("--out-dir must be outside the store root (plan never writes in the store)")
            mode = args.optimise_mode
            if mode == "full" and target != ".":
                raise Refusal(
                    "optimise_mode=full requires --target . so whole-store cost is never accidental; "
                    "Full is serial only"
                )
            if mode == "custom" and not args.custom_tree:
                raise Refusal("optimise_mode=custom requires at least one --custom-tree path prefix")
            if mode in ("path", "full") and args.custom_tree:
                raise Refusal(f"--custom-tree conflicts with optimise_mode={mode}")
            if mode in ("path", "full") and args.since_hours is not None:
                raise Refusal(f"--since-hours conflicts with optimise_mode={mode}")
            if args.since_hours is not None and args.since_hours < 1:
                raise Refusal("--since-hours must be a positive integer")
            if mode == "full":
                print(
                    "atlas-optimise: Full is serial only; do not start another Full "
                    "on any store until this one finishes.",
                    file=sys.stderr,
                )
            since_hours = DEFAULT_SINCE_HOURS if mode == "incremental" and args.since_hours is None else args.since_hours
            plan = plan_store(
                root, target, subject_folders,
                mode=mode,
                custom_trees=args.custom_tree,
                since_hours=since_hours,
                tidy_only=args.tidy_only,
                auto_verbatim=args.auto_verbatim,
                cost_ceiling=args.cost_ceiling,
                pilot=args.pilot,
            )
            if args.out_dir:
                written = write_out(plan, out)
            result = {**plan, "written": written} if args.json else {
                "target": target, "counts": plan["counts"],
                "optimise_mode": mode,
                "precondition": bool(plan["precondition"]), "written": written,
                "per_folder": {f: len(ts) for f, ts in plan["folders"].items()},
                "receipt": plan["receipt"],
            }
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 1 if plan["counts"]["tasks"] else 0
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        result = apply_plan(root, target, plan, args.include_opt_in, args.confirm)
        plan_path = Path(args.plan).expanduser().resolve()
        if plan_path.parent != root and root not in plan_path.parents:
            receipt_path = plan_path.parent / "receipt-apply.json"
            receipt_path.write_text(
                json.dumps(result["receipt"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        print(json.dumps(result if args.json else {
            "applied": result["applied"], "residual_counts": result["residual_counts"],
            "receipt": result["receipt"]}, indent=2, ensure_ascii=False))
        return 1 if result["residual_counts"]["tasks"] else 0
    except Refusal as e:
        print(json.dumps({"ok": False, "refused": str(e)}), file=sys.stdout)
        print(f"atlas-optimise: refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
