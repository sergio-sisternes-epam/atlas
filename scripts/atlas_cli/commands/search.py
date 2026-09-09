from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from ..core.frontmatter import read_page
from ..core.overlay import merge_overlays
from ..core.paths import RESERVED, iter_concept_md, rel, store_root
from ..core.recall import run_recall
from ..core.recall_config import recall_enabled
from ..core.schema import load_schema, staging_dir_name

EXIT_STATES = frozenset({"terminated", "deprecated", "superseded"})
RELATES_CAP = 5

AGENTIC_GUIDANCE = """
Agentic search pattern (grep mode):
  Protocol is path query (B17 card). Engine is atlas search. Do not merge the names.
  1. Formal lookup: Enter card path=query, load references/paths/query.md, then run this command.
  2. Use these ranked hits as the candidate map — do not run unbounded whole-tree grep/rg/find.
  3. Select with traffic on the hit (type, kva, status, work_id). Exit states are not current guidance.
  4. Read 1–3 pages, including a spine or work hub when it ranks. Expand via frontmatter relates_to.
  5. At most one glossary-alias rewrite search (query path step). Do not invent synonyms.
  6. Never treat staging/ as an answer source. Gap if nothing relevant.
""".strip()

DISCIPLINE = {
    "path": "query",
    "engine": "atlas search",
    "primary": "atlas search",
    "forbidden_primary": ["grep", "rg", "find"],
    "next": [
        "select by type/kva/status/work_id; prefer spine/work hub",
        "read 1-3 pages",
        "hop relates_to",
        "at most one glossary rewrite search",
    ],
}

_FIELD_TOKEN = re.compile(
    r"(?:^|\s)(type|kva|status|work_id|path):([^\s]+)",
    re.I,
)


def _search_engine(schema: dict | None) -> str:
    if not schema:
        return "grep"
    query = schema.get("query") or {}
    eng = str(query.get("search_engine") or "grep").strip().lower()
    if eng in ("grep", "bm25", "rg"):
        return "grep" if eng == "rg" else eng
    return "grep"


def _tokenise(q: str) -> list[str]:
    return [t for t in re.split(r"[^\w]+", q.lower()) if len(t) > 1]


def _split_filters(query: str) -> tuple[dict[str, str], str]:
    filters: dict[str, str] = {}
    for m in _FIELD_TOKEN.finditer(query):
        filters[m.group(1).lower()] = m.group(2)
    rest = _FIELD_TOKEN.sub(" ", query)
    rest = re.sub(r"\s+", " ", rest).strip()
    return filters, rest


def _score_doc(text: str, tokens: list[str]) -> tuple[int, list[str]]:
    low = text.lower()
    score = 0
    hit_terms: list[str] = []
    for t in tokens:
        c = low.count(t)
        if c:
            score += c
            hit_terms.append(t)
    return score, hit_terms


def _snippet(text: str, tokens: list[str], width: int = 120) -> str:
    low = text.lower()
    pos = -1
    for t in tokens:
        pos = low.find(t)
        if pos >= 0:
            break
    if pos < 0:
        return re.sub(r"\s+", " ", text)[:width].strip()
    start = max(0, pos - 40)
    frag = text[start : start + width]
    return re.sub(r"\s+", " ", frag).strip()


def _is_exit(meta: dict) -> bool:
    for key in ("kva", "status"):
        val = str(meta.get(key) or "").strip().lower()
        if val in EXIT_STATES:
            return True
    return False


def _relates_preview(meta: dict) -> list[dict]:
    raw = meta.get("relates_to") or []
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        kind = str(item.get("kind") or "").strip()
        edge = {"path": path}
        if kind:
            edge["kind"] = kind
        out.append(edge)
        if len(out) >= RELATES_CAP:
            break
    return out


def _present(meta: dict, key: str):
    val = meta.get(key)
    if val is None:
        return None
    if isinstance(val, str) and not val.strip():
        return None
    return val


def _path_constraint(root: Path, raw: str | None) -> tuple[Path | None, str | None]:
    if not raw:
        return None, None
    candidate = Path(raw)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root / raw).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None, f"path: escapes --root ({raw}); constraint skipped"
    return resolved, None


def _under_prefix(page: Path, prefix: Path) -> bool:
    try:
        page.resolve().relative_to(prefix)
        return True
    except ValueError:
        return page.resolve() == prefix


def _grep_search(
    root: Path,
    query: str,
    staging_dir: str,
    limit: int,
    include_exits: bool,
) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    filters, rest = _split_filters(query)
    tokens = _tokenise(rest)
    filter_only = bool(filters) and not tokens
    if not tokens and not filters:
        return [], warnings

    prefix, path_warn = _path_constraint(root, filters.get("path"))
    if path_warn:
        warnings.append(path_warn)
    if prefix is not None and not prefix.exists():
        return [], warnings

    results: list[dict] = []
    paths = list(iter_concept_md(root, staging_dir))
    if prefix is not None:
        paths = [p for p in paths if _under_prefix(p, prefix)]

    use_rg = shutil.which("rg") is not None and len(tokens) == 1
    if use_rg:
        try:
            proc = subprocess.run(
                [
                    "rg",
                    "-l",
                    "-i",
                    "--glob",
                    "*.md",
                    "--glob",
                    f"!{staging_dir}/**",
                    tokens[0],
                    str(root),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            rg_paths = []
            for line in proc.stdout.splitlines():
                p = Path(line.strip())
                if p.is_file():
                    rg_paths.append(p)
            if rg_paths:
                allowed = {p.resolve() for p in paths}
                paths = [p for p in rg_paths if p.resolve() in allowed]
        except (subprocess.TimeoutExpired, OSError):
            pass

    for path in paths:
        if path.name in RESERVED and path.name == "log.md":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, body = read_page(path)
        if filters.get("type") and str(meta.get("type") or "").strip() != filters["type"]:
            continue
        if filters.get("kva") and str(meta.get("kva") or "").strip() != filters["kva"]:
            continue
        if filters.get("status") and str(meta.get("status") or "").strip() != filters["status"]:
            continue
        if filters.get("work_id") and str(meta.get("work_id") or "").strip() != filters["work_id"]:
            continue
        asked_exit = (
            str(filters.get("kva") or "").lower() in EXIT_STATES
            or str(filters.get("status") or "").lower() in EXIT_STATES
        )
        if not include_exits and not asked_exit and _is_exit(meta):
            continue

        title = str(meta.get("title") or "")
        desc = str(meta.get("description") or "")
        score_parts = {"terms": 0, "title": 0, "description": 0, "work_id": 0}
        hit_terms: list[str] = []

        if filter_only:
            score = 1
        else:
            blob = f"{title}\n{desc}\n{body}"
            score, hit_terms = _score_doc(blob, tokens)
            score_parts["terms"] = score
            for t in tokens:
                if t in title.lower():
                    score += 5
                    score_parts["title"] += 5
                if t in desc.lower():
                    score += 2
                    score_parts["description"] += 2
            fm_work = str(meta.get("work_id") or "").strip().lower()
            if fm_work and fm_work in tokens:
                score += 8
                score_parts["work_id"] = 8
            if score <= 0:
                continue

        hit = {
            "path": rel(root, path),
            "score": score,
            "score_parts": score_parts,
            "title": title or path.stem,
            "type": str(meta.get("type") or ""),
            "terms": hit_terms,
            "snippet": _snippet(body or text, tokens or [next(iter(filters.values()), "")]),
            "relates_to": _relates_preview(meta),
        }
        for key in ("kva", "status", "work_id", "growth"):
            val = _present(meta, key)
            if val is not None:
                hit[key] = val
        results.append(hit)

    if filter_only:
        results.sort(key=lambda x: x["path"])
    else:
        results.sort(key=lambda x: (-x["score"], x["path"]))
    return results[:limit], warnings


def _bm25_search(root: Path, query: str, staging_dir: str, limit: int) -> tuple[list[dict], str | None]:
    index_dir = root / ".atlas-index"
    if not index_dir.is_dir():
        return [], "BM25 index not present (.atlas-index/); falling back to grep-mode search"
    return [], "BM25 engine not yet implemented in this CLI build; falling back to grep-mode search"


def run(
    root: str | None,
    query: str,
    limit: int = 10,
    as_json: bool = False,
    engine_override: str | None = None,
    include_exits: bool = False,
    profile: str | None = None,
    allow_partial: bool = False,
) -> int:
    r = store_root(root)
    schema, _ = load_schema(r)
    effective = schema
    if schema is not None:
        merged, crit, _ = merge_overlays(schema, r)
        if not crit:
            effective = merged
    if engine_override and profile:
        payload = {
            "ok": False,
            "error": "conflicting flags: --engine and --profile",
            "root": str(r),
            "query": query,
        }
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(payload["error"])
        return 2
    use_smr = bool(profile) or recall_enabled(effective)
    if use_smr:
        payload, code = run_recall(
            r,
            query,
            profile=profile,
            allow_partial=allow_partial,
            include_exits=include_exits,
            limit=limit,
        )
        if not payload.get("legacy"):
            if as_json:
                print(json.dumps(payload, indent=2, default=str))
            else:
                if not payload.get("ok"):
                    print(f"atlas search — FAIL: {payload.get('error')}")
                else:
                    print(f"atlas search — root={r}")
                    print(f"query: {query}")
                    rec = payload.get("recall") or {}
                    print(
                        f"engine: configured={payload.get('engine_configured')} used={payload.get('engine_used')} complete={rec.get('complete')}"
                    )
                    hits = payload.get("hits") or []
                    if not hits:
                        print("no hits")
                    for i, h in enumerate(hits, 1):
                        typ = f" [{h['type']}]" if h.get("type") else ""
                        print(f"{i}. {h['path']}  score={h['score']}{typ}")
                        if h.get("title"):
                            print(f"   title: {h['title']}")
            return code
    if allow_partial and not use_smr:
        if as_json:
            print(json.dumps({"ok": False, "error": "--allow-partial requires SCHEMA 2.0 recall", "root": str(r)}))
        else:
            print("--allow-partial requires SCHEMA 2.0 recall")
        return 2
    staging_name = staging_dir_name(schema)
    engine = (engine_override or _search_engine(schema)).lower()
    if engine not in ("grep", "bm25"):
        engine = "grep"

    warning: str | None = None
    extra_warnings: list[str] = []
    mode_used = engine

    if engine == "bm25":
        hits, warning = _bm25_search(r, query, staging_name, limit)
        if warning:
            mode_used = "grep"
            hits, extra_warnings = _grep_search(
                r, query, staging_name, limit, include_exits
            )
    else:
        hits, extra_warnings = _grep_search(
            r, query, staging_name, limit, include_exits
        )

    all_warnings = [w for w in [warning, *extra_warnings] if w]

    payload = {
        "root": str(r),
        "query": query,
        "engine_configured": engine,
        "engine_used": mode_used,
        "warning": all_warnings[0] if all_warnings else None,
        "warnings": all_warnings,
        "include_exits": include_exits,
        "count": len(hits),
        "hits": hits,
        "agentic_guidance": AGENTIC_GUIDANCE if mode_used == "grep" else None,
        "discipline": DISCIPLINE if mode_used == "grep" else None,
    }

    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"atlas search — root={r}")
        print(f"query: {query}")
        print(f"engine: configured={engine} used={mode_used}")
        if include_exits:
            print("include_exits: yes")
        for w in all_warnings:
            print(f"WARNING: {w}")
        if not hits:
            print("no hits")
        else:
            for i, h in enumerate(hits, 1):
                typ = f" [{h['type']}]" if h.get("type") else ""
                print(f"{i}. {h['path']}  score={h['score']}{typ}")
                if h.get("title"):
                    print(f"   title: {h['title']}")
                signals = []
                for key in ("kva", "status", "work_id"):
                    if h.get(key) not in (None, ""):
                        signals.append(f"{key}={h[key]}")
                if signals:
                    print(f"   {' '.join(signals)}")
                if h.get("relates_to"):
                    kinds = ", ".join(
                        f"{e.get('kind') or 'related'}:{e['path']}"
                        for e in h["relates_to"][:3]
                    )
                    print(f"   relates_to: {kinds}")
                if h.get("snippet"):
                    print(f"   {h['snippet'][:100]}")
        if mode_used == "grep":
            print()
            print(AGENTIC_GUIDANCE)

    return 0
