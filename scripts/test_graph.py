#!/usr/bin/env python3
"""atlas graph nodes|edges|neighbours|export over the shared projection.

Set ATLAS_UPDATE_GOLDEN=1 to rewrite fixtures/graph/ from the SCHEMA 1.0 store.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
GOLDEN = ROOT / "fixtures" / "graph"

PAGES: dict[str, str] = {
    "work/hub.md": (
        "---\ntype: work\ntitle: Graph hub\ncreated: 2026-09-09\nwork_id: hub\npriority: 3\n"
        "tags:\n  - alpha\n  - beta\n---\n\n## Scope\n\nHub page for the graph fixture.\n"
    ),
    "index.md": "# Graph fixture\n\n- work\n",
    "work/index.md": "# Work\n\n- hub\n",
    "notes/child-a.md": (
        "---\ntype: decision\ntitle: Child A\ncreated: 2026-09-09\nwork_id: hub\n"
        "relates_to:\n  - path: work/hub.md\n    kind: implements\n---\n\n## Claim\n\nChild A implements the hub.\n"
    ),
    "notes/child-b.md": (
        "---\ntype: lesson\ntitle: Child B\ndescription: Second child\ncreated: 2026-09-09\n"
        "relates_to:\n  - path: ./work/hub.md\n    kind: implements\n"
        "  - path: notes/missing.md\n    kind: related\n"
        "  - path: atlas://github.com/example/okf-atlas/lessons/remote.md\n    kind: derived_from\n"
        "---\n\n## Claim\n\nChild B implements the hub and cites a missing page.\n"
    ),
    "stars/p1.md": (
        "---\ntype: protostar\ntitle: Star one\ncreated: 2026-09-09\nkva: forming\ngrowth: true\n"
        "relates_to:\n  - path: notes/child-a.md\n    kind: derived_from\n---\n\n## Claim\n\nForming star one.\n"
    ),
    "stars/p2.md": (
        "---\ntype: protostar\ntitle: Star two\ncreated: 2026-09-09\nkva: forming\ngrowth: false\n"
        "relates_to:\n  - path: notes/child-a.md\n    kind: derived_from\n---\n\n## Claim\n\nForming star two.\n"
    ),
    "cycle/c1.md": (
        "---\ntype: document\ntitle: Cycle one\ncreated: 2026-09-09\n"
        "relates_to:\n  - path: cycle/c2.md\n    kind: follows\n---\n\nCycle one body.\n"
    ),
    "cycle/c2.md": (
        "---\ntype: document\ntitle: Cycle two\ncreated: 2026-09-09\n"
        "relates_to:\n  - path: cycle/c3.md\n    kind: follows\n---\n\nCycle two body.\n"
    ),
    "cycle/c3.md": (
        "---\ntype: document\ntitle: Cycle three\ncreated: 2026-09-09\n"
        "relates_to:\n  - path: cycle/c1.md\n    kind: follows\n---\n\nCycle three body.\n"
    ),
    "old/dead.md": (
        "---\ntype: decision\ntitle: Dead end\ncreated: 2026-09-09\nkva: terminated\n"
        "relates_to:\n  - path: notes/child-a.md\n    kind: kva_terminate\n---\n\n## Claim\n\nTerminated frame.\n"
    ),
    "log.md": (
        "---\ntitle: Log\nrelates_to:\n  - path: work/hub.md\n    kind: records\n---\n\n- 2026-09-09 created\n"
    ),
    "staging/draft.md": (
        "---\ntype: decision\ntitle: Draft\nrelates_to:\n  - path: work/hub.md\n    kind: implements\n---\n\nDraft.\n"
    ),
}

SCHEMA_V1 = {
    "schema_version": "1.0",
    "atlas_id": "graph-fixture",
    "title": "Graph fixture",
    "structure": {"staging_dir": "staging"},
    "relations": {"recommended_kinds": ["implements", "derived_from", "supersedes"]},
}

VOLATILE = ("generation", "fast_path", "corpus_digest", "root")


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args], cwd=ROOT, text=True, capture_output=True
    )


def as_json(proc: subprocess.CompletedProcess[str]) -> dict:
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_pages(store: Path) -> None:
    for rel, text in PAGES.items():
        path = store / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def snapshot(store: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(store)): p.read_bytes()
        for p in sorted(store.rglob("*"))
        if p.is_file()
    }


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-graph-"))
    try:
        v1 = tmp / "v1"
        v1.mkdir()
        (v1 / "SCHEMA.json").write_text(json.dumps(SCHEMA_V1, indent=2) + "\n", encoding="utf-8")
        write_pages(v1)
        r1 = str(v1)

        def g(*args: str, root: str = r1) -> tuple[int, dict]:
            proc = run(["graph", *args, "--root", root, "--json"])
            return proc.returncode, as_json(proc)

        before = snapshot(v1)

        # --- nodes ---------------------------------------------------------
        code, p = g("nodes", "--where", "type=protostar", "--where", "kva=forming", "--where", "growth=true")
        check(
            "nodes-where-and",
            code == 0 and [n["path"] for n in p.get("nodes", [])] == ["stars/p1.md"],
            str(p),
        )
        star = (p.get("nodes") or [{}])[0]
        check(
            "nodes-record-shape",
            star.get("growth") is True
            and star.get("kva") == "forming"
            and star.get("fields", {}).get("growth") == "true"
            and "relates_to" not in star.get("fields", {}),
            str(star),
        )
        for key in ("ok", "root", "verb", "generation", "corpus_digest", "fast_path", "complete", "count"):
            check(f"payload-has-{key}", key in p)
        check("payload-not-fast-path", p.get("fast_path") is False and p.get("generation") is None)

        code, p = g("nodes", "--where", "tags=beta")
        check("nodes-list-field", [n["path"] for n in p.get("nodes", [])] == ["work/hub.md"], str(p))
        code, p = g("nodes", "--where", "priority=3")
        check("nodes-number-field", [n["path"] for n in p.get("nodes", [])] == ["work/hub.md"], str(p))
        code, p = g("nodes", "--where", "nonexistent=x")
        check("nodes-missing-field", code == 0 and p.get("count") == 0)

        code, p = g("nodes")
        all_paths = [n["path"] for n in p.get("nodes", [])]
        check("nodes-exit-hidden", "old/dead.md" not in all_paths, str(all_paths))
        check("nodes-log-excluded", "log.md" not in all_paths)
        check("nodes-staging-excluded", not any(x.startswith("staging/") for x in all_paths))
        check("nodes-sorted", all_paths == sorted(all_paths))
        code, p = g("nodes", "--include-exits")
        check("nodes-exit-shown", "old/dead.md" in [n["path"] for n in p.get("nodes", [])])
        code, p = g("nodes", "--where", "kva=terminated")
        check("nodes-exit-asked", [n["path"] for n in p.get("nodes", [])] == ["old/dead.md"], str(p))
        code, p = g("nodes", "--where", "typeprotostar")
        check("nodes-malformed-where", code == 2 and p.get("ok") is False)
        code, p = g("nodes", "--path", "stars", "--limit", "1")
        check(
            "nodes-path-limit",
            [n["path"] for n in p.get("nodes", [])] == ["stars/p1.md"] and p.get("truncated") is True,
            str(p),
        )

        # --- edges ---------------------------------------------------------
        code, p = g("edges", "--to", "work/hub.md", "--kind", "implements")
        check(
            "edges-to-hub",
            code == 0
            and [e["from"] for e in p.get("edges", [])] == ["notes/child-a.md", "notes/child-b.md"]
            and all(e["resolved"] for e in p.get("edges", [])),
            str(p),
        )
        code, p = g("edges", "--from", "notes/child-b.md")
        by_to = {e["to"]: e for e in p.get("edges", [])}
        check(
            "edges-unresolved",
            by_to.get("notes/missing.md", {}).get("resolved") is False
            and "external" not in by_to.get("notes/missing.md", {}),
            str(by_to),
        )
        ext = by_to.get("atlas://github.com/example/okf-atlas/lessons/remote.md", {})
        check("edges-external", ext.get("external") is True and ext.get("resolved") is False, str(ext))
        check("edges-dot-slash", "work/hub.md" in by_to)
        code, p = g("edges", "--to", "notes/child-a.md")
        kinds = sorted(e["kind"] for e in p.get("edges", []))
        check("edges-exit-hidden", kinds == ["derived_from", "derived_from"], str(kinds))
        code, p = g("edges", "--to", "notes/child-a.md", "--include-exits")
        check(
            "edges-exit-shown",
            any(e["kind"] == "kva_terminate" and e["from"] == "old/dead.md" for e in p.get("edges", [])),
        )
        code, p = g("edges")
        check("edges-needs-selector", code == 2)
        code, p = g("edges", "--from", "nope.md")
        check("edges-unknown-from", code == 2)
        code, p = g("edges", "--all")
        check("edges-log-excluded", not any(e["from"] == "log.md" for e in p.get("edges", [])))

        # --- neighbours ----------------------------------------------------
        code, p = g("neighbours", "work/hub.md", "--direction", "in", "--kind", "implements")
        check(
            "neighbours-in-implements",
            code == 0
            and p.get("seed") == "work/hub.md"
            and [n["path"] for n in p.get("nodes", [])] == ["notes/child-a.md", "notes/child-b.md"]
            and all(e["direction"] == "in" and e["to"] == "work/hub.md" for e in p.get("edges", [])),
            str(p),
        )
        code, p = g("neighbours", "work/hub.md", "--direction", "out", "--kind", "implements")
        check("neighbours-out-none", code == 0 and p.get("count") == 0 and p.get("edges") == [], str(p))
        code, p = g("neighbours", "work/hub.md", "--hops", "4")
        check("neighbours-hops-4", code == 2)
        code, p = g("neighbours", "nope.md")
        check("neighbours-unknown", code == 2)
        code, p = g("neighbours", "cycle/c1.md", "--hops", "3")
        paths = [n["path"] for n in p.get("nodes", [])]
        edge_keys = [(e["from"], e["to"], e["kind"]) for e in p.get("edges", [])]
        check(
            "neighbours-cycle",
            paths == ["cycle/c2.md", "cycle/c3.md"]
            and len(edge_keys) == len(set(edge_keys)) == 3
            and "cycle/c1.md" not in paths,
            str(p),
        )
        code, p = g("neighbours", "work/hub.md", "--direction", "in", "--max-nodes", "1")
        check("neighbours-truncated", p.get("truncated") is True and p.get("count") == 1, str(p))
        code, p = g("neighbours", "stars/p1.md", "--direction", "out", "--hops", "2", "--where", "type=work")
        check(
            "neighbours-where-passes-through",
            [(n["path"], n["hop"]) for n in p.get("nodes", [])] == [("work/hub.md", 2)],
            str(p),
        )
        code, p = g("neighbours", "notes/child-a.md", "--direction", "in")
        check(
            "neighbours-exit-hidden",
            "old/dead.md" not in [n["path"] for n in p.get("nodes", [])],
        )
        code, p = g("neighbours", "notes/child-a.md", "--direction", "in", "--include-exits")
        check("neighbours-exit-shown", "old/dead.md" in [n["path"] for n in p.get("nodes", [])])

        human = run(["graph", "edges", "--from", "notes/child-b.md", "--root", r1])
        check(
            "human-output",
            human.returncode == 0 and "notes/child-b.md -[related]-> notes/missing.md unresolved" in human.stdout,
            human.stdout,
        )
        check("store-untouched", snapshot(v1) == before)

        # --- parity across contract shapes and fast path ----------------------
        queries = [
            ("nodes", "--include-exits"),
            ("nodes", "--where", "growth=true"),
            ("edges", "--all", "--include-exits"),
            ("neighbours", "work/hub.md", "--hops", "3", "--include-exits"),
            ("neighbours", "cycle/c2.md", "--hops", "2"),
        ]

        def strip(payload: dict) -> dict:
            return {k: v for k, v in payload.items() if k not in VOLATILE}

        baseline = [strip(g(*q)[1]) for q in queries]

        contract = tmp / "contract"
        run(["init", "--root", str(contract), "--json"])
        write_pages(contract)
        check("contract-shape", (contract / "CONTRACT.json").is_file())

        v2 = tmp / "v2"
        run(["init", "--root", str(v2), "--schema-version", "2.0", "--json"])
        write_pages(v2)
        act = run(["recall", "activate", "--profile", "atlas:scan", "--root", str(v2), "--json"])
        check("v2-activate", act.returncode == 0, act.stdout + act.stderr)
        built = run(["recall", "index", "build", "--root", str(v2), "--json"])
        check("v2-index-build", as_json(built).get("published") is True, built.stdout + built.stderr)

        for label, store, want_fast in (("contract", contract, False), ("v2-recall", v2, True)):
            for q, base in zip(queries, baseline):
                code, p = g(*q, root=str(store))
                check(f"parity-{label}-{' '.join(q[:2])}", strip(p) == base, f"{strip(p)} != {base}")
                check(f"fast-path-{label}-{q[0]}", p.get("fast_path") is want_fast)
        code, p = g("nodes", root=str(v2))
        check("v2-generation", bool(p.get("generation")))

        # --- partial corpus ----------------------------------------------------
        broken = tmp / "broken"
        run(["init", "--root", str(broken), "--schema-version", "2.0", "--json"])
        write_pages(broken)
        (broken / "notes" / "bad.md").write_text("---\ntitle: [unclosed\n---\n\nbad\n", encoding="utf-8")
        code, p = g("nodes", root=str(broken))
        check("partial-refused", code == 2 and p.get("ok") is False, str(p))
        code, p = g("nodes", "--allow-partial", root=str(broken))
        check(
            "partial-allowed",
            code == 1
            and p.get("complete") is False
            and [o["path"] for o in p.get("omitted", [])] == ["notes/bad.md"],
            str(p),
        )

        # --- export --------------------------------------------------------------
        def export(fmt: str, out: Path, root: str = r1) -> tuple[int, dict]:
            proc = run(["graph", "export", "--root", root, "--format", fmt, "--out", str(out), "--json"])
            return proc.returncode, as_json(proc)

        outs = [tmp / "out-a" / "deep", tmp / "out-b"]
        for out in outs:
            for fmt in ("json", "nanograph"):
                code, p = export(fmt, out)
                check(f"export-{fmt}-{out.name}", code == 0 and p.get("ok") is True, str(p))
        for name in ("graph.json", "schema.pg", "seed.jsonl", "export-receipt.json"):
            check(
                f"export-deterministic-{name}",
                (outs[0] / name).read_bytes() == (outs[1] / name).read_bytes(),
            )
        graph_doc = json.loads((outs[0] / "graph.json").read_text(encoding="utf-8"))
        check(
            "export-json-shape",
            graph_doc.get("version") == 1
            and "description" in graph_doc["nodes"][0]
            and any(e["to"] == "notes/missing.md" for e in graph_doc["edges"]),
        )
        receipt = json.loads((outs[0] / "export-receipt.json").read_text(encoding="utf-8"))
        check(
            "export-receipt-unresolved",
            [(e["from"], e["to"]) for e in receipt.get("unresolved", [])]
            == [("notes/child-b.md", "notes/missing.md")]
            and receipt.get("nanograph_schema_grammar") == "1.3.0",
            str(receipt),
        )
        seed = (outs[0] / "seed.jsonl").read_text(encoding="utf-8")
        check("export-seed-no-unresolved", "notes/missing.md" not in seed)
        schema_pg = (outs[0] / "schema.pg").read_text(encoding="utf-8")
        check(
            "export-schema-edge-types",
            "edge KvaTerminate: Page -> Page" in schema_pg
            and "edge DerivedFromExternal: Page -> External" in schema_pg
            and "edge Supersedes: Page -> Page" in schema_pg
            and "@embed" not in schema_pg
            and "Vector" not in schema_pg,
            schema_pg,
        )
        if os.environ.get("ATLAS_UPDATE_GOLDEN") == "1":
            GOLDEN.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(outs[0] / "schema.pg", GOLDEN / "schema.pg")
            shutil.copyfile(outs[0] / "seed.jsonl", GOLDEN / "seed.jsonl")
        for name in ("schema.pg", "seed.jsonl"):
            golden = GOLDEN / name
            check(
                f"export-golden-{name}",
                golden.is_file() and golden.read_bytes() == (outs[0] / name).read_bytes(),
                f"diff against {golden}",
            )
        code, p = export("nanograph", v1 / "exports")
        check("export-inside-store-refused", code == 2 and not (v1 / "exports").exists(), str(p))
        check("store-untouched-after-export", snapshot(v1) == before)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} graph check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll atlas graph checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
