# Multi-Atlas answer benchmark: harness specification

This is the specification handed to the multi-Atlas answer benchmark that
runs on Sergio's Mac, in the harness at `~/scratch/atlas-answer-bench`. The
harness is not in this repository, and its corpus, questions, transcripts and
results are never committed here. This file is the contract the harness
implements. It is the Mac half of the evaluation in the mesh-level indexing
plan (packet MF); the box half is `bench.py` in this folder.

The benchmark decides whether mesh scope is promoted beyond opt-in (M17). It
does not tune the product. Everything in [Pre-registration](#pre-registration)
is fixed before the first run.

## Baseline

The earlier 225-run benchmark on Warden of the North's 333-page Atlas found
that tools barely changed quality (91–94 % facts), Atlas setups cut credits by
15–20 %, and the graph was rarely used (13/45 and 7/45 runs). This benchmark
is meant to be harder and to give the mesh a fair test.

## Corpus

- Warden of the North's Atlas plus at least two other mounted Atlases, all in
  one mesh (one `atlas-mesh.json` in the harness project).
- Canonical `atlas://<host>/<org>/<repo>/<path>` cross-links are fixed in the
  stores first (open question 2), so the graph has edges to cross. Before the
  first run, record `bench.py --mesh <harness project>`'s unresolved-link
  report in the harness; it should show no `noncanonical_atlas_uri` links
  between the benchmark stores.
- Record each store's commit SHA in the harness before the first run. The
  corpus does not change during the 320 runs.

## Questions

- 40 questions in total:
  - 30 multi-Atlas questions, each needing facts from pages in at least two
    Atlases: 20 need two Atlases and 10 need three;
  - 10 single-Atlas control questions.
- Each question has:
  - a fact checklist: the atomic facts a correct answer must state, each
    scored present or absent;
  - the expected source atlas ids (and, where known, the expected page URIs).
- Questions, checklists and expected sources are written from the corpus
  before any run, by reading the stores, not by running any arm. They are not
  edited after the first run. A question found to be broken after the first
  run is dropped from every arm and reported as dropped, never rewritten.
- Question file shape (in the harness, not here):

  ```json
  {"id": "m01", "kind": "multi", "atlases_needed": 2,
   "question": "...",
   "facts": ["...", "..."],
   "expected_sources": ["<atlas id>", "<atlas id>"]}
  ```

- Before the first run, record the sha256 of the question file in the
  harness run log. Every run records the same hash. A run with a different
  hash is not counted.

## Budget

Fixed per run: at most 6 Atlas tool calls and 60k input tokens. A run that
hits the budget is scored on what it answered.

## Arms

| Arm | Atlas tools available |
|---|---|
| A0 | None (no Atlas tools) |
| A1 | Per-store tools as shipped in PR #61; the agent must pick `--root` |
| A2 | A1 plus `atlas recall run --scope mesh` (packet MC) |
| A3 | A2 plus `atlas graph ... --scope mesh` (packet MB) |

A3 needs packet MB merged; until then, run A0–A2 and record A3 as not run.
Mesh scope is passed by flag (`--scope mesh`), never by environment variable
or by editing `atlas-mesh.json` between arms (M14).

## Runs

4 arms × 40 questions × 2 seeds = 320 runs, with the same model and harness
settings as the 225-run benchmark. Arm order is interleaved per question, so
a slow drift in the model or the machine does not favour one arm.

## Metrics

- Fact accuracy: the share of checklist facts present, per run.
- Source-id correctness: whether the answer cites the expected atlas ids.
- Credits and tokens per run.
- Budget-exhaustion rate.
- Tool calls by kind.
- Graph-use rate: the share of runs that call any `graph` verb.

Report each metric per arm, separately for the 30 multi-Atlas questions and
the 10 controls.

## Pre-registration

The criteria below are copied verbatim from the approved plan.
They are fixed before the benchmark runs. They are not changed after seeing any result. A
result that misses them is a "keep opt-in" result: mesh scope stays opt-in,
the skill docs do not recommend `scope: mesh`, and the miss is recorded as a
lesson. This is the `benchmark-goodhart` smoke of
`references/scenarios/mesh-index-adversarial-v1.yaml`: the target is fixed
before the measure can be optimised.

### Pre-registered success criteria (M17)

Mesh scope is promoted beyond opt-in only if, on the multi-Atlas questions, A2 or A3 beats A1 by at least 5 points of fact accuracy at equal budget, **or** matches A1 within 1 point with at least 15 % fewer credits, **and** the single-Atlas controls do not drop by more than 2 points. A3 counts as better than A2 only if it beats A2 by at least 3 points or the graph is used in at least a third of A3 runs. Anything else is a "keep opt-in" result and is recorded as a lesson.

## Secondary evidence

A recall-path trajectory check that an agent asked a two-Atlas question uses
one `--scope mesh` call rather than one call per store. Never the only
evidence.

## Reporting

The harness writes its summary to the plan's work item, not to this
repository: the arms table (fact accuracy, source-id correctness, credits,
tokens, budget exhaustion, graph use) for the multi-Atlas questions and for
the controls, the question-file hash, the store SHAs and the verdict against
the criteria above ("promote" or "keep opt-in").
