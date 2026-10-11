#!/usr/bin/env python3
"""Mesh retrieval benchmark kit (packet MF). Contributor-only; never shipped.

Scores federated recall arms against a labelled query set over a mesh
(default ``fixtures/mesh``) and reports Recall@10 and MRR per arm, overall,
for the multi-store queries and for the single-store controls. Standard
library plus the in-repo Atlas CLI library, run in process.

Arms (every member answers with ``--engine bm25`` semantics, restricted
pages withheld before ranking, exactly as ``recall run --scope mesh`` does):

- ``best_single_store``: the one member whose own top 10 scores best for
  that query (an oracle choice no agent could make in advance);
- ``plain_rrf``: RRF with k = 60 over the member lists, ignoring tiers;
- ``tiered_rrf_k10|k60|k100``: the shipped fusion, ``mesh_recall.federate``;
- ``bm25_score_merge``: member hits merged on raw FTS5 BM25 scores;
- ``single_index``: one scratch FTS5 index over every included member's
  eligible pages, built in a temporary directory and deleted after the run.
  It measures what counter C2 (cross-index scores are not comparable) costs
  and is never shipped.

Nothing is written inside the mesh: per-member indexes go to a temporary
``ATLAS_INDEX_ROOT`` that is removed afterwards. The excluded member is never
read; the latency mode copies included members only.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import math
import os
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from atlas_cli.commands import search as search_cmd  # noqa: E402
from atlas_cli.core import index_location, mesh_recall, mesh_scope, recall_index  # noqa: E402
from atlas_cli.core.drivers import fts5 as fts5_driver  # noqa: E402
from atlas_cli.core.projection import project_store  # noqa: E402
from atlas_cli.core.recall_config import DEFAULT_WEIGHTS, fts5_available  # noqa: E402
from atlas_cli.core.schema import load_schema  # noqa: E402

DEFAULT_MESH = ROOT / "fixtures" / "mesh"
DEFAULT_QUERIES = HERE / "queries.json"
CUTOFF = 10
ENGINE = "bm25"
PLAIN_K = 60
TIERED_KS = (10, 60, 100)
LATENCY_SIZES = (2, 5, 10)
LATENCY_ID_PREFIX = "example.invalid/mesh-bench/member-"
ARMS = (
    "best_single_store",
    "plain_rrf",
    *(f"tiered_rrf_k{k}" for k in TIERED_KS),
    "bm25_score_merge",
    "single_index",
)
# Arms whose hits keep their member tier, so tier inversions can be counted.
TIERED_PROVENANCE = ("plain_rrf", *(f"tiered_rrf_k{k}" for k in TIERED_KS), "bm25_score_merge")
SUBSETS = ("overall", "multi_store", "three_store", "controls")
ENV_CLEAR = ("ATLAS_RECALL_ENGINE", "ATLAS_NANOGRAPH_BIN", "ATLAS_TEST_PLATFORM")


class BenchError(RuntimeError):
    """The benchmark cannot run (no FTS5, no mesh, bad query file)."""


# --- environment ---------------------------------------------------------------


@contextlib.contextmanager
def scratch_index_root(path: Path) -> Iterator[None]:
    """Send every per-member index to ``path`` (``ATLAS_INDEX_ROOT``), then restore the environment."""
    path.mkdir(parents=True, exist_ok=True)
    saved = {key: os.environ.get(key) for key in (index_location.OVERRIDE_ENV, *ENV_CLEAR)}
    os.environ[index_location.OVERRIDE_ENV] = str(path.resolve())
    for key in ENV_CLEAR:
        os.environ.pop(key, None)
    index_location.clear_cache()
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        index_location.clear_cache()


# --- queries and labels ------------------------------------------------------------


def load_queries(path: Path) -> list[dict[str, Any]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BenchError(f"cannot read {path}: {e}") from e
    queries = doc.get("queries") if isinstance(doc, dict) else None
    if not isinstance(queries, list) or not queries:
        raise BenchError(f"{path}: expected a non-empty 'queries' list")
    seen: set[str] = set()
    for q in queries:
        if not isinstance(q, dict) or not q.get("id") or not q.get("query") or not q.get("relevant"):
            raise BenchError(f"{path}: every query needs id, query and a non-empty relevant list")
        if q["id"] in seen:
            raise BenchError(f"{path}: duplicate query id {q['id']}")
        seen.add(q["id"])
    return queries


def label_stores(query: dict[str, Any]) -> list[str]:
    """Distinct atlas ids of a query's relevant pages, in label order."""
    out: list[str] = []
    for uri in query["relevant"]:
        atlas_id, _ = mesh_scope.parse_node_id(uri)
        if atlas_id not in out:
            out.append(atlas_id)
    return out


def subsets_of(query: dict[str, Any]) -> list[str]:
    stores = len(label_stores(query))
    out = ["overall"]
    if stores >= 2:
        out.append("multi_store")
    if stores >= 3:
        out.append("three_store")
    if stores == 1:
        out.append("controls")
    return out


# --- metrics -------------------------------------------------------------------


def recall_at(hits: list[str], relevant: list[str], cutoff: int = CUTOFF) -> float:
    rel = set(relevant)
    return len(rel.intersection(hits[:cutoff])) / len(rel) if rel else 0.0


def reciprocal_rank(hits: list[str], relevant: list[str], cutoff: int = CUTOFF) -> float:
    rel = set(relevant)
    for rank, uri in enumerate(hits[:cutoff], 1):
        if uri in rel:
            return 1.0 / rank
    return 0.0


def tier_inversions(tiers: list[int]) -> int:
    """Pairs where a tier 2 (any-word) hit ranks above a tier 1 hit."""
    seen_any = 0
    count = 0
    for tier in tiers:
        if tier == mesh_recall.TIER_ANY:
            seen_any += 1
        else:
            count += seen_any
    return count


def _r(value: float) -> float:
    return round(value, 4)


def percentile(samples: list[float], pct: float) -> float:
    """Nearest-rank percentile."""
    ordered = sorted(samples)
    if not ordered:
        return 0.0
    index = max(0, math.ceil(pct / 100.0 * len(ordered)) - 1)
    return ordered[index]


# --- member answers ----------------------------------------------------------------


class MemberCache:
    """Each member answers each query once (2 x cutoff hits); every arm reuses the answer."""

    def __init__(self) -> None:
        self.answers: dict[tuple[str, str], mesh_recall.MemberAnswer] = {}
        self.errors: dict[tuple[str, str], str] = {}

    def search(self, root: Path, query: str, limit: int, engine: str | None, include_exits: bool) -> mesh_recall.MemberAnswer:
        key = (str(root), query)
        if key in self.errors:
            raise mesh_recall.MemberError(self.errors[key])
        if key not in self.answers:
            try:
                self.answers[key] = mesh_recall.store_search(root, query, limit, engine, include_exits)
            except Exception as e:  # noqa: BLE001 - recorded, then re-raised for federate to report
                self.errors[key] = str(e) or type(e).__name__
                raise
        return self.answers[key]


def _score_key(hit: dict[str, Any]) -> float:
    score = float(hit.get("score") or 0.0)
    return score if hit.get("score_orientation", "lower_better") == "lower_better" else -score


# --- scratch single index (counter C2 measuring stick) ---------------------------------


def build_single_index(members: list[mesh_scope.Member], directory: Path) -> Path:
    """One FTS5 database over every included member's eligible pages, page ids = node URIs."""
    pages = []
    for member in members:
        schema, err = load_schema(member.root)
        if schema is None:
            raise BenchError(f"store {member.atlas_id}: {err or 'missing schema'}")
        projection = project_store(member.root, schema, allow_partial=False)
        for page in projection["pages"]:
            if not search_cmd._bm25_eligible(member.root, page, {}, None, False, mesh_recall.withhold):
                continue
            uri = mesh_scope.node_id(member.atlas_id, page.path)
            pages.append(dataclasses.replace(page, page_id=uri, path=uri))
    directory.mkdir(parents=True, exist_ok=True)
    db = directory / "single-index.sqlite"
    recall_index._write_sqlite(db, pages, "mesh-bench-scratch")
    return db


def single_index_search(db: Path, query: str, cutoff: int) -> list[str]:
    _, text = search_cmd._split_filters(query)
    conn = sqlite3.connect(str(db))
    try:
        hits, _ = fts5_driver.search_eligible(conn, text, cutoff, dict(DEFAULT_WEIGHTS), None)
    finally:
        conn.close()
    return [str(h["path"]) for h in hits]


# --- one query ----------------------------------------------------------------------


def score_query(
    query: dict[str, Any],
    mesh: mesh_scope.Mesh,
    included: list[mesh_scope.Member],
    cache: MemberCache,
    single_db: Path,
    cutoff: int,
) -> dict[str, Any]:
    text = query["query"]
    relevant = list(query["relevant"])
    per_member = cutoff * mesh_recall.OVERFETCH
    answers: list[tuple[mesh_scope.Member, mesh_recall.MemberAnswer]] = []
    for member in included:
        try:
            answers.append((member, cache.search(member.root, text, per_member, ENGINE, False)))
        except Exception:  # noqa: BLE001 - reported per member below
            continue
    tier_by_store = {m.atlas_id: mesh_recall.tier_of(a.match) for m, a in answers}

    arms: dict[str, dict[str, Any]] = {}

    def record(arm: str, uris: list[str], tiers: list[int] | None = None, **extra: Any) -> None:
        uris = uris[:cutoff]
        entry: dict[str, Any] = {
            "hits": uris,
            "recall": _r(recall_at(uris, relevant, cutoff)),
            "rr": _r(reciprocal_rank(uris, relevant, cutoff)),
        }
        if tiers is not None:
            entry["tier_inversions"] = tier_inversions(tiers[:cutoff])
        entry.update(extra)
        arms[arm] = entry

    # Oracle: the single member whose own top list scores best (recall, then RR, then row order).
    best: tuple[tuple[float, float, int], str, list[str]] | None = None
    for member, answer in answers:
        uris = [mesh_scope.node_id(member.atlas_id, h["path"]) for h in answer.hits[:cutoff]]
        key = (recall_at(uris, relevant, cutoff), reciprocal_rank(uris, relevant, cutoff), -member.index)
        if best is None or key > best[0]:
            best = (key, member.atlas_id, uris)
    record("best_single_store", best[2] if best else [], store=best[1] if best else None)

    flat = [
        mesh_recall.RankedList(m.index, m.atlas_id, mesh_recall.TIER_ALL, str(a.engine_used or ""), list(a.hits))
        for m, a in answers
    ]
    plain = mesh_recall.fuse(flat, PLAIN_K, cutoff)
    record("plain_rrf", [h["uri"] for h in plain], [tier_by_store[h["atlas_id"]] for h in plain])

    for k in TIERED_KS:
        settings = mesh_recall.Settings("mesh", "cli", k, "cli", mesh)
        payload, _ = mesh_recall.federate(settings, text, limit=cutoff, engine_override=ENGINE, search=cache.search)
        record(f"tiered_rrf_k{k}", [h["uri"] for h in payload["hits"]], [h["tier"] for h in payload["hits"]])

    merged = sorted(
        ((_score_key(h), m.index, str(h["path"]), m.atlas_id) for m, a in answers for h in a.hits),
        key=lambda t: (t[0], t[1], t[2]),
    )
    record(
        "bm25_score_merge",
        [mesh_scope.node_id(sid, path) for _, _, path, sid in merged],
        [tier_by_store[sid] for _, _, _, sid in merged],
    )

    record("single_index", single_index_search(single_db, text, cutoff))

    return {
        "id": query["id"],
        "query": text,
        "kind": query.get("kind") or ("control" if len(label_stores(query)) == 1 else "multi"),
        "stores_needed": len(label_stores(query)),
        "relevant": relevant,
        "member_match": {m.atlas_id: a.match for m, a in answers},
        "arms": arms,
    }


def aggregate(per_query: list[dict[str, Any]], queries: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {q["id"]: q for q in queries}
    out: dict[str, Any] = {}
    for arm in ARMS:
        block: dict[str, Any] = {}
        for subset in SUBSETS:
            rows = [r for r in per_query if subset in subsets_of(by_id[r["id"]])]
            if not rows:
                block[subset] = {"queries": 0, "recall_at_10": None, "mrr": None}
                continue
            block[subset] = {
                "queries": len(rows),
                "recall_at_10": _r(statistics.fmean(r["arms"][arm]["recall"] for r in rows)),
                "mrr": _r(statistics.fmean(r["arms"][arm]["rr"] for r in rows)),
            }
        if arm in TIERED_PROVENANCE:
            block["tier_inversions"] = sum(r["arms"][arm]["tier_inversions"] for r in per_query)
        out[arm] = block
    return out


# --- latency --------------------------------------------------------------------------


def latency_run(
    included: list[mesh_scope.Member],
    queries: list[dict[str, Any]],
    work: Path,
    *,
    sizes: tuple[int, ...] = LATENCY_SIZES,
    repeats: int = 5,
    n_queries: int = 5,
    cutoff: int = CUTOFF,
) -> dict[str, Any]:
    """Per-member and total federated latency, with included members duplicated into a temporary mesh.

    Timings depend on the machine: they are reported, never asserted.
    """
    if not included:
        raise BenchError("latency mode needs at least one included member")
    texts = [q["query"] for q in queries[: max(1, n_queries)]]
    results: list[dict[str, Any]] = []
    for size in sizes:
        base = work / f"latency-{size}"
        project = base / "mesh"
        rows = []
        for i in range(size):
            source = included[i % len(included)]
            name = f"member-{i + 1:02d}"
            shutil.copytree(source.root, project / "stores" / name, symlinks=True)
            rows.append({"id": f"{LATENCY_ID_PREFIX}{i + 1:02d}", "path": f"stores/{name}"})
        (project / "atlas-mesh.json").write_text(json.dumps({"version": 1, "stores": rows}, indent=2) + "\n", encoding="utf-8")
        member_ms: list[float] = []
        total_ms: list[float] = []
        with scratch_index_root(base / "indexes"):
            mesh = mesh_scope.discover(project)
            settings = mesh_recall.Settings("mesh", "cli", PLAIN_K, "cli", mesh)
            timing = [False]

            def timed(root: Path, query: str, limit: int, engine: str | None, include_exits: bool) -> mesh_recall.MemberAnswer:
                start = time.perf_counter()
                try:
                    return mesh_recall.store_search(root, query, limit, engine, include_exits)
                finally:
                    if timing[0]:
                        member_ms.append((time.perf_counter() - start) * 1000.0)

            for text in texts:  # warm-up: builds each member's index once
                mesh_recall.federate(settings, text, limit=cutoff, engine_override=ENGINE, search=timed)
            timing[0] = True
            for _ in range(max(1, repeats)):
                for text in texts:
                    start = time.perf_counter()
                    payload, _ = mesh_recall.federate(settings, text, limit=cutoff, engine_override=ENGINE, search=timed)
                    total_ms.append((time.perf_counter() - start) * 1000.0)
                    if not payload["complete"]:
                        raise BenchError(f"latency mesh of {size} members did not answer completely")
        shutil.rmtree(base, ignore_errors=True)
        results.append(
            {
                "members": size,
                "samples": len(total_ms),
                "member_ms": {"median": round(statistics.median(member_ms), 2), "p95": round(percentile(member_ms, 95), 2)},
                "total_ms": {"median": round(statistics.median(total_ms), 2), "p95": round(percentile(total_ms, 95), 2)},
            }
        )
    return {
        "note": "Environment-dependent; reported only, never asserted. Warm per-member indexes; one warm-up pass is discarded.",
        "repeats": max(1, repeats),
        "queries": len(texts),
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "sizes": results,
    }


# --- run --------------------------------------------------------------------------------


def mesh_label(mesh_dir: Path) -> str:
    resolved = mesh_dir.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return f"<scratch mesh: {resolved.name}>"


def run(
    mesh_dir: Path = DEFAULT_MESH,
    queries_path: Path = DEFAULT_QUERIES,
    *,
    cutoff: int = CUTOFF,
    latency: bool = False,
    repeats: int = 5,
    latency_queries: int = 5,
    sizes: tuple[int, ...] = LATENCY_SIZES,
    tmp_parent: Path | None = None,
    observe: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    """Run the benchmark; every scratch file lives under one temporary directory that is removed."""
    if not fts5_available():
        raise BenchError("this Python's sqlite3 lacks FTS5; the BM25 arms cannot run")
    queries = load_queries(Path(queries_path))
    try:
        mesh = mesh_scope.discover(Path(mesh_dir))
    except mesh_scope.MeshScopeError as e:
        raise BenchError(str(e)) from e
    all_members = mesh_scope.members(mesh)
    included = [m for m in all_members if m.status == mesh_scope.STATUS_OK]
    work = Path(tempfile.mkdtemp(prefix="atlas-mesh-bench-", dir=str(tmp_parent) if tmp_parent else None))
    try:
        view = mesh_scope.build_view(mesh)
        node_ids = {n["id"] for n in view["nodes"]}
        label_errors = [
            f"{q['id']}: {uri} is not an eligible page of an included member"
            for q in queries
            for uri in q["relevant"]
            if uri not in node_ids
        ]
        single_db = build_single_index(included, work / "single-index")
        if observe is not None:
            observe("single_index", single_db)
        cache = MemberCache()
        with scratch_index_root(work / "indexes"):
            per_query = [score_query(q, mesh, included, cache, single_db, cutoff) for q in queries]
        shutil.rmtree(single_db.parent)
        if observe is not None:
            observe("single_index_removed", single_db)
        member_rows = []
        for m in all_members:
            row: dict[str, Any] = {"atlas_id": m.atlas_id, "status": m.status}
            if m.status == mesh_scope.STATUS_OK:
                row["any_word_queries"] = sum(1 for r in per_query if r["member_match"].get(m.atlas_id) == "any")
                row["errors"] = sum(1 for (root, _), _ in cache.errors.items() if root == str(m.root))
            member_rows.append(row)
        counts = {
            "total": len(queries),
            "multi_store": sum(1 for q in queries if len(label_stores(q)) >= 2),
            "three_store": sum(1 for q in queries if len(label_stores(q)) >= 3),
            "controls": sum(1 for q in queries if len(label_stores(q)) == 1),
        }
        summary = aggregate(per_query, queries)
        result: dict[str, Any] = {
            "kit": "atlas-mesh-bench",
            "format": 1,
            "mesh": mesh_label(Path(mesh_dir)),
            "engine": ENGINE,
            "cutoff": cutoff,
            "plain_rrf_k": PLAIN_K,
            "members": member_rows,
            "queries": counts,
            "label_errors": label_errors,
            "arms": summary,
            "c2_gap_points": {
                subset: _r(
                    100.0
                    * ((summary["single_index"][subset]["recall_at_10"] or 0.0) - (summary["tiered_rrf_k60"][subset]["recall_at_10"] or 0.0))
                )
                for subset in ("overall", "multi_store")
            },
            "unresolved_by_reason": dict(view["unresolved_by_reason"]),
            "unresolved_total": sum(view["unresolved_by_reason"].values()),
            "per_query": per_query,
        }
        if latency:
            result["latency"] = latency_run(
                included, queries, work, sizes=sizes, repeats=repeats, n_queries=latency_queries, cutoff=cutoff
            )
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --- output ------------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_markdown(result: dict[str, Any]) -> str:
    q = result["queries"]
    lines = [
        f"## Mesh retrieval benchmark ({result['mesh']})",
        "",
        f"{q['total']} queries: {q['multi_store']} multi-store ({q['three_store']} need three stores), "
        f"{q['controls']} single-store controls. Engine {result['engine']}, cutoff {result['cutoff']}.",
        "",
        "| Arm | Recall@10 | MRR | Recall@10 multi | MRR multi | Recall@10 controls | MRR controls | Tier inversions |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for arm in ARMS:
        a = result["arms"][arm]
        inv = a.get("tier_inversions")
        lines.append(
            f"| {arm} | {_fmt(a['overall']['recall_at_10'])} | {_fmt(a['overall']['mrr'])} "
            f"| {_fmt(a['multi_store']['recall_at_10'])} | {_fmt(a['multi_store']['mrr'])} "
            f"| {_fmt(a['controls']['recall_at_10'])} | {_fmt(a['controls']['mrr'])} "
            f"| {'n/a' if inv is None else inv} |"
        )
    gap = result["c2_gap_points"]
    lines += [
        "",
        f"C2 gap (single_index minus tiered_rrf_k60, Recall@10 points): overall {gap['overall']:+.1f}, "
        f"multi-store {gap['multi_store']:+.1f}. Revisit C2 if this exceeds +5.",
        "",
        "Unresolved links by reason: "
        + ", ".join(f"{k} {v}" for k, v in result["unresolved_by_reason"].items())
        + f" (total {result['unresolved_total']}).",
    ]
    if result["label_errors"]:
        lines += ["", f"Label errors: {len(result['label_errors'])} (see JSON)."]
    lat = result.get("latency")
    if lat:
        lines += [
            "",
            f"### Federated latency (ms; {lat['repeats']} repeats x {lat['queries']} queries; not asserted)",
            "",
            "| Members | Per-member median | Per-member p95 | Total median | Total p95 |",
            "|---|---|---|---|---|",
        ]
        for row in lat["sizes"]:
            lines.append(
                f"| {row['members']} | {row['member_ms']['median']:.2f} | {row['member_ms']['p95']:.2f} "
                f"| {row['total_ms']['median']:.2f} | {row['total_ms']['p95']:.2f} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mesh retrieval benchmark (contributor-only).")
    parser.add_argument("--mesh", type=Path, default=DEFAULT_MESH, help="project directory holding atlas-mesh.json (default fixtures/mesh)")
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES, help="labelled query file (default queries.json beside this script)")
    parser.add_argument("--json", dest="json_out", help="write the JSON result to this path ('-' for stdout instead of markdown)")
    parser.add_argument("--markdown", type=Path, help="also write the markdown table to this path")
    parser.add_argument("--latency", action="store_true", help="also measure federated latency at 2, 5 and 10 members")
    parser.add_argument("--repeats", type=int, default=5, help="latency repeats per query (default 5)")
    parser.add_argument("--latency-queries", type=int, default=5, help="queries per latency repeat (default 5)")
    args = parser.parse_args(argv)
    try:
        result = run(args.mesh, args.queries, latency=args.latency, repeats=args.repeats, latency_queries=args.latency_queries)
    except BenchError as e:
        print(f"mesh-bench: {e}", file=sys.stderr)
        return 2
    markdown = render_markdown(result)
    text = json.dumps(result, indent=2, sort_keys=False) + "\n"
    if args.json_out == "-":
        sys.stdout.write(text)
    else:
        if args.json_out:
            Path(args.json_out).write_text(text, encoding="utf-8")
        sys.stdout.write(markdown)
    if args.markdown:
        args.markdown.write_text(markdown, encoding="utf-8")
    return 1 if result["label_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
