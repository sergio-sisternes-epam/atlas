#!/usr/bin/env python3
"""atlas-optimise helper: plan (dry-run) and apply for one operator-named target.

Operator-chosen only. Never called by install, init, compile, or memory-migrate.
It writes no contract file and invents no text: every repair copies text that
already exists in a store page.

  plan  --root <store> --target <folder|.> [--out-dir DIR] [--subject-folder F:stem]... [--json]
  apply --root <store> --target <folder|.> --plan plan.json [--include-opt-in] [--confirm ID]... [--json]

plan exit: 0 no tasks, 1 tasks listed, 2 refused.
apply exit: 0 applied with no residual tasks, 1 applied with residual tasks, 2 refused.
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_cli import __version__ as PACKAGE_VERSION  # noqa: E402
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


def plan_store(root: Path, target: str, subject_folders: list[tuple[str, str]]) -> dict:
    store = Store(root)
    if store.contract_error:
        raise Refusal(f"contract: {store.contract_error}")
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

    keys = sorted(k for k in store.pages if _in_target(k, target))
    by_folder: dict[str, list[str]] = {}
    for k in store.pages:
        by_folder.setdefault(store.folder(k), []).append(k)

    # --- index files in target: dead cues, layer-skip cues, schema cues
    index_files = [
        p for p in store.md_files
        if p.name == "index.md" and _in_target(_rel(root, p), target) and _is_index_scope(root, p)
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
        for item in _relates(meta):
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
        for item in _relates(meta):
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
        for item in _relates(meta):
            if _kind(item) != "derived_from":
                continue
            mk = store.canonical(str(item.get("path") or ""))
            if mk not in store.pages or store.ptype(mk) != "memory":
                continue
            mpath, mmeta, mbody = store.pages[mk]
            mdesc = mmeta.get("description")
            if desc in mbody or (isinstance(mdesc, str) and desc in mdesc):
                break
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
            break

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
    return {
        "schema": "atlas-optimise-plan/v1",
        "source": {
            "root": str(root),
            "target": target,
            "head": head,
            "dirty": dirty,
            "contract_file": store.contract_file,
            "contract_sha256": _sha(root / store.contract_file) if store.contract_file else None,
            "atlas_release": store.schema.get("atlas_release"),
            "package_version": PACKAGE_VERSION,
        },
        "precondition": precondition,
        "folders": grouped,
        "counts": {"tasks": len(tasks), **counts},
        "unreadable": store.unreadable,
    }


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
        f"target `{source['target']}`; contract `{source['contract_file']}` "
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
    if not any(store.canonical(str(i.get("path") or "")) == gist_key and _kind(i) == "related" for i in _relates(meta)):
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
    for t in selected:
        kind = t["kind"]
        if kind in ("dead-index-cue", "layer-skip-cue"):
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
        applied.append(t["id"])

    if {n: _sha(root / n) for n in CONTRACT_FILENAMES} != contract_before:
        raise Refusal("contract file changed during apply; this helper never writes contracts")
    residual = plan_store(root, target, [])
    return {
        "schema": "atlas-optimise-apply/v1",
        "root": str(root),
        "target": target,
        "applied": applied,
        "residual_counts": residual["counts"],
        "residual": {f: ts for f, ts in residual["folders"].items() if ts},
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
    p_plan.add_argument("--out-dir", help="write plan.json and tasks/<folder>.md here (must be outside the store)")
    p_plan.add_argument("--subject-folder", action="append", default=[],
                        help="operator-named subject folder as <folder>:<stem>; plans confirm-class moves")
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
            plan = plan_store(root, target, subject_folders)
            if args.out_dir:
                written = write_out(plan, out)
            result = {**plan, "written": written} if args.json else {
                "target": target, "counts": plan["counts"],
                "precondition": bool(plan["precondition"]), "written": written,
                "per_folder": {f: len(ts) for f, ts in plan["folders"].items()},
            }
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 1 if plan["counts"]["tasks"] else 0
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        result = apply_plan(root, target, plan, args.include_opt_in, args.confirm)
        print(json.dumps(result if args.json else {
            "applied": result["applied"], "residual_counts": result["residual_counts"]}, indent=2, ensure_ascii=False))
        return 1 if result["residual_counts"]["tasks"] else 0
    except Refusal as e:
        print(json.dumps({"ok": False, "refused": str(e)}), file=sys.stdout)
        print(f"atlas-optimise: refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
