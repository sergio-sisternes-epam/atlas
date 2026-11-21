#!/usr/bin/env python3
"""atlas-dream helper: a read-only consolidation report for one store target.

Operator-chosen only. Never called by install, init, compile, or memory-migrate.
It writes nothing in the store. It reads live pages and lists candidates for a
reviewer: duplicates, possible contradictions, and superseded pages that are not
marked. Every finding quotes the source lines verbatim with path:line, so a
reviewer can check it without trusting the helper. It never applies a fix.

  report --root <store> [--target <folder|.>] [--out-dir DIR] [--json]
         [--page-similarity F] [--claim-similarity F] [--min-claim-chars N]
         [--cost-ceiling PAGES] [--max-findings N per kind]

Finding kinds:
  duplicate-page      two live pages with near-identical bodies
  duplicate-claim     the same claim line in two places
  supersede-unmarked  a live page is the target of a `supersedes` edge
  same-title          two live pages share a title and no `supersedes` edge
  conflict-candidate  two similar claims that differ in polarity or in a number

Exit: 0 no findings, 1 findings listed, 2 refused (nothing written).
With --json the report goes to stdout; diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_cli import __version__ as PACKAGE_VERSION  # noqa: E402
from atlas_cli.core.frontmatter import read_page  # noqa: E402
from atlas_cli.core.paths import RESERVED, has_contract_file, iter_concept_md  # noqa: E402

EXIT_STATES = frozenset({"terminated", "deprecated", "superseded"})
NEGATIONS = frozenset({"never", "not", "cannot", "dont", "doesnt", "isnt", "wont", "mustnt", "shouldnt"})
STOPWORDS = frozenset(
    "the and for are but with this that from into onto than then they them their there "
    "its was were has have had been being will would should could can may might must "
    "each every all any one two our your you his her who whom which what when where why "
    "how also only just more most less such per via".split()
)
WORD = re.compile(r"[a-z0-9]+")
# Identifiers are not quantities: issue refs, dates, times, versions, hashes, long ids.
IDENTIFIER = re.compile(r"#\d+|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}(?::\d{2})?\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2}\b|\bv?\d+(?:\.\d+){2,}\b|\b[0-9a-f]*\d[0-9a-f]{6,}\b|\b\d{4,}\b", re.I)
QUANTITY = re.compile(r"\b\d+(?:\.\d+)?\b")
LINK_TARGET = re.compile(r"\]\([^)]*\)|<?https?://\S+")
COUNT_CELL = re.compile(r"\|\s*\d+(?:\.\d+)?\s*(?=\|)")
MAX_QUANTITIES = 2  # lines with more numbers are tallies or snapshots, not rules
MIN_CONTENT_WORDS = 4  # shorter lines (hashes, headers, boilerplate) are not claims worth deduplicating
NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
DEFAULTS = {"page_similarity": 0.8, "claim_similarity": 0.7, "min_claim_chars": 30, "cost_ceiling": 400, "max_findings": 200}


class Refusal(Exception):
    pass


def _git_head(root: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return out.stdout.strip() or None


def _words(text: str) -> list[str]:
    return WORD.findall(text.lower().replace("'", ""))


def _content(words: list[str]) -> frozenset[str]:
    return frozenset(w for w in words if len(w) > 2 and w not in STOPWORDS and w not in NEGATIONS and not NUMBER.match(w))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _is_live(meta: dict) -> bool:
    return not any(str(meta.get(k) or "").strip().lower() in EXIT_STATES for k in ("kva", "status"))


def _claims(text: str, min_chars: int) -> list[dict]:
    """Prose and table lines after the frontmatter, with 1-based file line numbers."""
    lines = text.split("\n")
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    out, fenced = [], False
    for i in range(start, len(lines)):
        raw = lines[i]
        s = raw.strip()
        if s.startswith("```") or s.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced or not s or s.startswith("#") or s.startswith("<!--") or re.fullmatch(r"[|:\-\s]+", s):
            continue
        prose = LINK_TARGET.sub("]", s)
        words = _words(prose)
        norm = " ".join(words)
        if len(norm) < min_chars:
            continue
        nums = frozenset(QUANTITY.findall(IDENTIFIER.sub(" ", COUNT_CELL.sub("|", prose))))
        out.append({"line": i + 1, "text": raw.rstrip(), "norm": norm, "words": words, "content": _content(words), "nums": nums})
    return out


class Page:
    def __init__(self, root: Path, path: Path, min_chars: int):
        self.key = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        self.meta, _ = read_page(path)
        self.title = str(self.meta.get("title") or "").strip()
        self.created = str(self.meta.get("created") or "").strip()
        self.live = _is_live(self.meta)
        self.claims = _claims(text, min_chars)
        self.shingles = frozenset(zip(*(" ".join(c["norm"] for c in self.claims).split()[k:] for k in range(3))))
        self.supersedes = [
            str(item.get("path") or "").strip().removeprefix("./")
            for item in (self.meta.get("relates_to") or [])
            if isinstance(item, dict) and str(item.get("kind") or "").strip() == "supersedes"
        ]


def _quote(page: Page, claim: dict) -> dict:
    return {"path": page.key, "line": claim["line"], "text": claim["text"]}


def _title_line(root: Path, page: Page) -> dict:
    for n, raw in enumerate((root / page.key).read_text(encoding="utf-8", errors="replace").split("\n"), 1):
        if raw.strip().startswith("title:"):
            return {"path": page.key, "line": n, "text": raw.rstrip()}
    return {"path": page.key, "line": 1, "text": ""}


def _load(root: Path, target: str, args) -> list[Page]:
    base = root if target == "." else root / target
    paths = [p for p in iter_concept_md(root) if p.name not in RESERVED and (base == root or base in p.parents)]
    if len(paths) > args.cost_ceiling:
        raise Refusal(f"{len(paths)} pages exceed --cost-ceiling {args.cost_ceiling}; narrow --target or raise the ceiling")
    return [Page(root, p, args.min_claim_chars) for p in paths]


def _find(root: Path, pages: list[Page], args) -> list[dict]:
    live = [p for p in pages if p.live]
    by_key = {p.key: p for p in pages}
    found: list[dict] = []

    # supersede-unmarked: an edge says B is superseded, but B is still live.
    for page in live:
        for target in page.supersedes:
            old = by_key.get(target)
            if old is not None and old.live:
                found.append({
                    "kind": "supersede-unmarked", "pages": [page.key, old.key],
                    "quotes": [_title_line(root, page), _title_line(root, old)],
                    "suggestion": f"Mark {old.key} as superseded (status: superseded, or path atlas-forget), keep the file, and link it back to {page.key}.",
                })

    edges = {(p.key, t) for p in pages for t in p.supersedes}

    def linked(a: Page, b: Page) -> bool:
        return (a.key, b.key) in edges or (b.key, a.key) in edges

    # same-title and duplicate-page, pairwise over live pages.
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            if linked(a, b):
                continue
            newer, older = (a, b) if a.created >= b.created else (b, a)
            hint = f"If {newer.key} replaces {older.key}, add relates_to {{path: {older.key}, kind: supersedes}} to {newer.key} and mark {older.key} superseded; otherwise retitle one."
            if a.title and a.title.lower() == b.title.lower():
                found.append({"kind": "same-title", "pages": [a.key, b.key], "quotes": [_title_line(root, a), _title_line(root, b)], "suggestion": hint})
            sim = _jaccard(a.shingles, b.shingles)
            if sim >= args.page_similarity:
                found.append({"kind": "duplicate-page", "pages": [a.key, b.key], "similarity": round(sim, 2),
                              "quotes": [_title_line(root, a), _title_line(root, b)], "suggestion": "Merge into one page; " + hint})

    # duplicate-claim: identical normalised claim lines.
    groups: dict[str, list[tuple[Page, dict]]] = defaultdict(list)
    for page in live:
        for claim in page.claims:
            if len(claim["content"]) >= MIN_CONTENT_WORDS:
                groups[claim["norm"]].append((page, claim))
    for members in groups.values():
        if len(members) > 1 and len({p.key for p, _ in members}) > 1:
            found.append({"kind": "duplicate-claim", "pages": sorted({p.key for p, _ in members}),
                          "quotes": [_quote(p, c) for p, c in members],
                          "suggestion": "Keep the claim in one canonical page and point to it from the others."})

    # conflict-candidate: similar claims that differ in polarity or in a number.
    claims = [(p, c) for p in live for c in p.claims if c["content"]]
    index: dict[str, list[int]] = defaultdict(list)
    for n, (_, c) in enumerate(claims):
        for w in c["content"]:
            index[w].append(n)
    common = max(50, len(claims) // 20)
    seen: set[tuple[int, int]] = set()
    for n, (pa, ca) in enumerate(claims):
        shared: dict[int, int] = defaultdict(int)
        for w in ca["content"]:
            if len(index[w]) <= common:
                for m in index[w]:
                    if m > n:
                        shared[m] += 1
        for m, count in shared.items():
            if count < 3 or (n, m) in seen:
                continue
            pb, cb = claims[m]
            if ca["norm"] == cb["norm"] or _jaccard(ca["content"], cb["content"]) < args.claim_similarity:
                continue
            neg_a, neg_b = bool(NEGATIONS & set(ca["words"])), bool(NEGATIONS & set(cb["words"]))
            nums_a, nums_b = ca["nums"], cb["nums"]
            counted = 0 < len(nums_a) <= MAX_QUANTITIES and 0 < len(nums_b) <= MAX_QUANTITIES
            # A number that differs inside one page is usually a dated tally, so only compare across pages.
            numeric = counted and nums_a != nums_b and pa.key != pb.key
            reason = "polarity" if neg_a != neg_b else ("number" if numeric else None)
            if reason:
                seen.add((n, m))
                found.append({"kind": "conflict-candidate", "reason": reason, "pages": sorted({pa.key, pb.key}),
                              "quotes": [_quote(pa, ca), _quote(pb, cb)],
                              "suggestion": "Review both lines. If one replaces the other, amend or supersede it and record which wins and when; if both hold, state their different scopes."})

    order = ("supersede-unmarked", "conflict-candidate", "same-title", "duplicate-page", "duplicate-claim")
    found.sort(key=lambda f: (order.index(f["kind"]), f["pages"]))
    kept, per_kind = [], defaultdict(int)
    for item in found:
        per_kind[item["kind"]] += 1
        if per_kind[item["kind"]] <= args.max_findings:
            kept.append(item)
    for n, item in enumerate(kept, 1):
        item["id"] = f"D-{n:03d}"
    return kept


def _markdown(report: dict) -> str:
    out = [f"# Atlas dream report: {report['target']}", "",
           f"Root: {report['root']} at {report['head'] or 'no git HEAD'}. Read-only; nothing was changed.",
           "Every item is a candidate for review, not a verdict.", "", "| Kind | Count |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in report["counts"].items()]
    for f in report["findings"]:
        out += ["", f"## {f['id']} {f['kind']}" + (f" ({f['reason']})" if f.get("reason") else ""), ""]
        out += [f"- `{q['path']}:{q['line']}`: {q['text'].strip()}" for q in f["quotes"]]
        out += ["", f"Suggestion: {f['suggestion']}"]
    return "\n".join(out) + "\n"


def report(args) -> tuple[int, dict]:
    root = Path(args.root).resolve()
    if not root.is_dir() or not has_contract_file(root):
        raise Refusal(f"not an Atlas store (no contract file): {root}")
    target = args.target.strip("/") or "."
    base = (root / target).resolve()
    if not base.is_dir() or (base != root and root not in base.parents):
        raise Refusal(f"target is not a folder inside the store: {args.target}")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else None
    if out_dir is not None and (out_dir == root or root in out_dir.parents):
        raise Refusal("--out-dir must be outside the store")
    pages = _load(root, target, args)
    findings = _find(root, pages, args)
    counts: dict[str, int] = defaultdict(int)
    for f in findings:
        counts[f["kind"]] += 1
    result = {"helper": "atlas-dream", "version": PACKAGE_VERSION, "root": str(root), "head": _git_head(root),
              "target": target, "pages": len(pages), "counts": dict(counts), "findings": findings}
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "dream.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (out_dir / "dream.md").write_text(_markdown(result), encoding="utf-8")
    return (1 if findings else 0), result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="atlas-dream helper (operator-chosen; read-only; never on install or compile).")
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="read-only consolidation report; writes nothing in the store")
    rep.add_argument("--root", required=True, help="Atlas store root")
    rep.add_argument("--target", default=".", help="folder inside the store, or . for the whole store")
    rep.add_argument("--out-dir", help="write dream.json and dream.md here (must be outside the store)")
    rep.add_argument("--json", action="store_true", help="print the full JSON report")
    rep.add_argument("--page-similarity", type=float, default=DEFAULTS["page_similarity"], help="duplicate-page threshold (word 3-shingle Jaccard)")
    rep.add_argument("--claim-similarity", type=float, default=DEFAULTS["claim_similarity"], help="conflict-candidate threshold (content-word Jaccard)")
    rep.add_argument("--min-claim-chars", type=int, default=DEFAULTS["min_claim_chars"], help="ignore shorter lines")
    rep.add_argument("--cost-ceiling", type=int, default=DEFAULTS["cost_ceiling"], help="refuse above this many pages")
    rep.add_argument("--max-findings", type=int, default=DEFAULTS["max_findings"], help="cap each finding kind")
    args = parser.parse_args(argv)
    try:
        code, result = report(args)
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        summary = ", ".join(f"{k} {v}" for k, v in result["counts"].items()) or "no findings"
        print(f"atlas-dream: {result['pages']} pages in {result['target']}: {summary}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
