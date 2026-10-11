#!/usr/bin/env python3
"""Tiered RRF fusion (M11): hand-computed scores, tier order, over-fetch, ties, truncation.

Pure: :func:`mesh_recall.fuse` needs no store. The over-fetch check runs
:func:`mesh_recall.federate` over a two-row temp mesh with an injected member
search, so no engine runs. Linux-safe: no network, no git.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, mesh_recall  # noqa: E402
from atlas_cli.core.mesh_recall import MemberAnswer, RankedList, fuse  # noqa: E402

A = "github.com/acme/alpha"
B = "github.com/acme/beta"
C = "github.com/acme/gamma"


def hits(*paths: str) -> list[dict]:
    return [{"path": p, "title": p.upper()} for p in paths]


def two_lists() -> list[RankedList]:
    return [
        RankedList(0, A, 1, "sqlite-fts5", hits("a1.md", "a2.md", "a3.md")),
        RankedList(1, B, 1, "grep", hits("b1.md", "b2.md")),
    ]


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    # Hand-computed scores: 1 / (k + rank), 1-based rank, for k = 1, 60, 1000.
    for k in (1, 60, 1000):
        out = fuse(two_lists(), k, 0)
        order = [(h["atlas_id"], h["path"]) for h in out]
        want_order = [(A, "a1.md"), (B, "b1.md"), (A, "a2.md"), (B, "b2.md"), (A, "a3.md")]
        check(f"k{k}-order-interleaves-by-rank-then-row", order == want_order, str(order))
        want = {"a1.md": 1, "b1.md": 1, "a2.md": 2, "b2.md": 2, "a3.md": 3}
        exact = all(abs(Fraction(h["rrf_score"]) - Fraction(1, k + want[h["path"]])) < Fraction(1, 10**15) for h in out)
        check(f"k{k}-scores-hand-computed", exact, str([(h["path"], h["rrf_score"]) for h in out]))
        check(f"k{k}-member-rank", [h["member_rank"] for h in out] == [1, 1, 2, 2, 3])
    k1 = fuse(two_lists(), 1, 0)
    check("k1-values", [h["rrf_score"] for h in k1] == [1 / 2, 1 / 2, 1 / 3, 1 / 3, 1 / 4], str([h["rrf_score"] for h in k1]))
    k60 = fuse(two_lists(), 60, 0)
    check("k60-values", [h["rrf_score"] for h in k60] == [1 / 61, 1 / 61, 1 / 62, 1 / 62, 1 / 63])
    k1000 = fuse(two_lists(), 1000, 0)
    check("k1000-values", [h["rrf_score"] for h in k1000] == [1 / 1001, 1 / 1001, 1 / 1002, 1 / 1002, 1 / 1003])

    # Hit fields (M12) and URI form.
    first = k60[0]
    check(
        "hit-fields",
        list(first) == ["atlas_id", "path", "uri", "title", "member_rank", "tier", "rrf_score", "engine_used"],
        str(list(first)),
    )
    check("hit-uri", first["uri"] == f"atlas://{A}/a1.md", first["uri"])
    check("hit-title-from-member", first["title"] == "A1.MD")
    check("hit-engine-used", first["engine_used"] == "sqlite-fts5" and k60[1]["engine_used"] == "grep")

    # The same page in two lists of one member sums its contributions (the general formula).
    multi = fuse(
        [RankedList(0, A, 1, "x", hits("p.md", "q.md")), RankedList(0, A, 1, "y", hits("z.md", "q.md"))], 60, 0
    )
    q = next(h for h in multi if h["path"] == "q.md")
    check("rrf-sums-over-lists", Fraction(q["rrf_score"]) == Fraction(1 / 62 + 1 / 62), str(q["rrf_score"]))
    check("rrf-sum-ranks-first", multi[0]["path"] == "q.md", str([h["path"] for h in multi]))

    # Tier beats score: a tier-2 rank 1 never outranks a tier-1 rank 5, for any k.
    for k in (1, 60, 1000):
        out = fuse(
            [
                RankedList(0, A, 1, "sqlite-fts5", hits("a1.md", "a2.md", "a3.md", "a4.md", "a5.md")),
                RankedList(1, B, 2, "sqlite-fts5", hits("b1.md", "b2.md")),
            ],
            k,
            0,
        )
        tiers = [h["tier"] for h in out]
        check(f"k{k}-tier-1-before-tier-2", tiers == [1, 1, 1, 1, 1, 2, 2], str(tiers))
        b1 = next(h for h in out if h["path"] == "b1.md")
        a5 = next(h for h in out if h["path"] == "a5.md")
        check(f"k{k}-tier-beats-score", b1["rrf_score"] > a5["rrf_score"] and out.index(a5) < out.index(b1))
    check("tier-of", (mesh_recall.tier_of("any"), mesh_recall.tier_of("all"), mesh_recall.tier_of(None)) == (2, 1, 1))

    # Deterministic ties: equal tier and score -> mesh row order, then path.
    rows = fuse(
        [RankedList(1, A, 1, "g", hits("a.md")), RankedList(0, B, 1, "g", hits("z.md"))], 60, 0
    )
    check("tie-row-order-beats-path-and-id", [h["path"] for h in rows] == ["z.md", "a.md"], str([h["path"] for h in rows]))
    paths = fuse(
        [RankedList(0, A, 1, "g", hits("x.md")), RankedList(0, A, 1, "g", hits("w.md"))], 60, 0
    )
    check("tie-path-order", [h["path"] for h in paths] == ["w.md", "x.md"], str([h["path"] for h in paths]))
    three = [
        RankedList(2, C, 1, "g", hits("c1.md")),
        RankedList(0, A, 2, "g", hits("a1.md")),
        RankedList(1, B, 1, "g", hits("b1.md", "b2.md")),
    ]
    once = json.dumps(fuse(three, 60, 0), sort_keys=True)
    check("deterministic-json", once == json.dumps(fuse(list(reversed(three)), 60, 0), sort_keys=True))

    # Truncation to limit; 0 keeps everything.
    check("truncate-limit-3", [h["path"] for h in fuse(two_lists(), 60, 3)] == ["a1.md", "b1.md", "a2.md"])
    check("truncate-limit-1", len(fuse(two_lists(), 60, 1)) == 1)
    check("limit-0-keeps-all", len(fuse(two_lists(), 60, 0)) == 5)
    check("empty-lists", fuse([], 60, 10) == [])

    # k out of range is invalid input.
    for bad in (0, 1001, -1, True, 60.0):
        try:
            fuse(two_lists(), bad, 10)  # type: ignore[arg-type]
            check(f"fuse-rejects-k-{bad!r}", False)
        except mesh_recall.MeshRecallError:
            check(f"fuse-rejects-k-{bad!r}", True)
    for raw, want in (("1", 1), ("60", 60), ("1000", 1000), (" 7 ", 7)):
        check(f"parse-rrf-k-{raw.strip()}", mesh_recall.parse_rrf_k(raw) == want)
    for raw in ("0", "1001", "abc", "6.5", "", "-3", "1e2"):
        try:
            mesh_recall.parse_rrf_k(raw)
            check(f"parse-rrf-k-rejects-{raw!r}", False)
        except mesh_recall.MeshRecallError:
            check(f"parse-rrf-k-rejects-{raw!r}", True)

    # Over-fetch: each member is asked for 2 x limit, and its whole list feeds fusion.
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-rrf-"))
    try:
        project = tmp / "proj"
        for name in ("alpha", "beta"):
            store = project / "atlas" / name
            store.mkdir(parents=True)
            (store / "SCHEMA.json").write_text(json.dumps({"schema_version": "1.0"}) + "\n", encoding="utf-8")
        doc = {"version": 1, "stores": [{"id": A, "path": "atlas/alpha"}, {"id": B, "path": "atlas/beta"}]}
        (project / "atlas-mesh.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        index_location.clear_cache()
        settings = mesh_recall.resolve_settings(project, "mesh", None)
        asked: list[tuple[str, int]] = []

        def fake(root, query, limit, engine, include_exits):
            asked.append((Path(root).name, limit))
            prefix = Path(root).name[0]
            match = "any" if prefix == "b" else "all"
            count = min(limit, 4)
            return MemberAnswer(hits(*[f"{prefix}{i}.md" for i in range(1, count + 1)]), match, "bm25", "sqlite-fts5", None)

        payload, code = mesh_recall.federate(settings, "q", limit=3, search=fake)
        check("overfetch-2x-limit", asked == [("alpha", 6), ("beta", 6)], str(asked))
        check("overfetch-member-counts", [m["hits"] for m in payload["members"]] == [4, 4])
        check("overfetch-truncated-to-limit", payload["count"] == 3 and len(payload["hits"]) == 3)
        check("overfetch-tier-1-fills-first", [h["path"] for h in payload["hits"]] == ["a1.md", "a2.md", "a3.md"])
        check("federate-exit-0", code == 0 and payload["complete"] is True)
        asked.clear()
        payload7, _ = mesh_recall.federate(settings, "q", limit=7, search=fake)
        check("overfetch-2x-limit-7", asked == [("alpha", 14), ("beta", 14)], str(asked))
        got = [(h["path"], h["tier"]) for h in payload7["hits"]]
        want = [("a1.md", 1), ("a2.md", 1), ("a3.md", 1), ("a4.md", 1), ("b1.md", 2), ("b2.md", 2), ("b3.md", 2)]
        check("tier-2-fills-remaining-slots", got == want, str(got))
        check("k-default-60", payload["rrf_k"] == 60 and payload["rrf_k_source"] == "default")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} mesh RRF check(s) failed: {', '.join(failed[:10])}")
        return 1
    print("\nAll mesh RRF checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
