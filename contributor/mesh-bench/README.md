# Mesh retrieval benchmark kit

Contributor tooling for the mesh-level indexing plan (packet MF). Nothing in
this folder is part of the shipped skill bundle: `apm.yml` includes only
`.apm/skills/...`, and `test_bench.py` guards that.

| File | Purpose |
|---|---|
| `bench.py` | Scores federated recall arms on a mesh: Recall@10 and MRR, federated latency, unresolved-link counts |
| `queries.json` | 41 labelled queries over `fixtures/mesh`: 31 multi-store (9 need three stores) and 10 single-store controls |
| `MAC-HARNESS.md` | Specification for the multi-Atlas answer benchmark on Sergio's Mac, with the pre-registered success criteria (M17) |
| `test_bench.py` | Runs the kit on `fixtures/mesh` (picked up by `python3 scripts/run_tests.py`) |

The fixture is `fixtures/mesh/`: a synthetic mesh of a fictional ferry operator
with three included stores (platform, ops, research), an excluded store
(`mesh_member: false`) and an unmounted row, all under the reserved host
`example.invalid`. All of its content is invented. It has one restricted page
and exactly one cross-store link for each unresolved reason.

## Run

```bash
python3 contributor/mesh-bench/bench.py                    # markdown table on stdout
python3 contributor/mesh-bench/bench.py --json out.json    # also write the full JSON
python3 contributor/mesh-bench/bench.py --json -           # JSON on stdout instead
python3 contributor/mesh-bench/bench.py --latency --repeats 5
python3 contributor/mesh-bench/bench.py --mesh <project dir> --queries <labelled file>
```

`--mesh` points at any project directory holding an `atlas-mesh.json`, for
example a scratch project that mounts real stores. Give it a query file whose
labels are page URIs in that mesh. Exit codes: 0 ok, 1 when a label does not
name an eligible page of an included member, 2 when the kit cannot run (no
mesh, a bad query file or no SQLite FTS5).

**Results on real stores must not be committed**, and neither may query
files, labels or excerpts drawn from them. Keep them in the scratch project.
Only `fixtures/mesh` results belong in this repository, and only in a PR
description, not as files.

## What the kit does

Every member answers each query once, in process, through its own
`recall run` pipeline with `--engine bm25` semantics (`mesh_recall.store_search`),
asking for 2 × 10 hits. Restricted pages leave each member's eligible set
before ranking, and the excluded member is never read. Every arm reuses
those answers:

| Arm | Meaning |
|---|---|
| `best_single_store` | The one member whose own top 10 scores best for that query. An oracle: no agent knows the best store in advance |
| `plain_rrf` | RRF with k = 60 over member lists, ignoring tiers. The `rrf-interleave-noise` baseline |
| `tiered_rrf_k10`, `_k60`, `_k100` | The shipped fusion (`mesh_recall.federate`): all-words lists before any-word retries, then RRF with that k |
| `bm25_score_merge` | Member hits merged on their raw FTS5 BM25 scores, which are not comparable across indexes (counter C2) |
| `single_index` | One scratch FTS5 index over every included member's eligible pages, built in a temporary directory and deleted after the run. A measuring stick for counter C2; never shipped |

Metrics per arm: Recall@10 and MRR (reciprocal rank of the first relevant hit
in the top 10), overall, for the multi-store queries and for the controls.
The JSON adds the three-store subset, per-query hits, tier inversions (a
tier-2 hit ranked above a tier-1 hit; tiered arms must have none) and the C2
gap (single index minus tiered k = 60, in Recall@10 points; the plan revisits
C2 above +5).

`--latency` copies the included members into a temporary mesh of 2, 5 and 10
members (the copies get ids under `example.invalid/mesh-bench/`). It runs one
discarded warm-up pass, then reports the median and p95 of per-member and
total federated latency over `--repeats` × `--latency-queries` calls. Timings
depend on the machine, so they are reported and never asserted.

The unresolved-link report counts cross-store link failures by reason with
`mesh_scope.build_view` on the chosen mesh.

Output is deterministic for the same mesh and query file, apart from the
latency block.

## Isolation

- Per-member indexes go to a temporary `ATLAS_INDEX_ROOT`. Nothing is written
  inside the mesh or its stores, and no git `info/exclude` is touched.
- All scratch files (indexes, the single index and latency copies) live under
  one temporary `atlas-mesh-bench-*` directory, which is removed at the end.
- The latency mesh copies included members only. Excluded stores are never
  read.

## Labels

The labels in `queries.json` were written by reading the fixture pages under
`fixtures/mesh/stores` before `bench.py` was run on them. They were not tuned
to any arm's output, and misses are kept as measured. To change the fixture,
relabel from the page text, then rerun the test.

## Mac benchmark

`MAC-HARNESS.md` is the specification for the 320-run answer benchmark at
`~/scratch/atlas-answer-bench`. Its success criteria are fixed before the
first run. A miss is recorded as a "keep opt-in" lesson, never fixed by
changing the criteria.
