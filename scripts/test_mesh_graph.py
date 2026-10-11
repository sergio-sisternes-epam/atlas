#!/usr/bin/env python3
"""Mesh graph CLI (packet MB, M5, M13, M14, M16): `atlas graph --scope mesh`,
`atlas index build --mesh`, the `index status` mesh block and `index show --mesh`.

Three-store temporary mesh plus an excluded and an unmounted row. Linux-safe:
no network, no git, no nanograph binary.
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
CLI = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))

ALPHA = "github.com/acme/alpha"
BETA = "github.com/acme/beta"
GAMMA = "github.com/acme/gamma"
SECRET = "github.com/acme/secret"
GONE = "github.com/acme/gone"
ELSEWHERE = "github.com/acme/elsewhere"
EXT = "github.com/acme/ext"
CANARY = "WOMBATTREACLE"
EXT_CANARY = "QUOKKAMARMALADE"

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if not ok and detail != "" else ""))
    if not ok:
        FAILURES.append(name)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def page(title: str, rels: list[tuple[str, str]] | None = None, *, extra: list[str] | None = None, type_: str = "lesson") -> str:
    lines = [
        "---",
        f"type: {type_}",
        f"title: {title} {CANARY} title",
        f"description: {CANARY} description",
        f"tags: [{CANARY.lower()}, {CANARY}]",
        "status: active",
        "kva: K",
        "origin: authored",
        "created: 2026-10-10",
        *(extra or []),
    ]
    if rels:
        lines.append("relates_to:")
        for target, kind in rels:
            lines += [f"  - path: {json.dumps(target)}", f"    kind: {kind}", f"    note: {CANARY} note"]
    lines += ["---", "", f"# {title} {CANARY} heading", "", f"Body {CANARY} text.", ""]
    return "\n".join(lines)


def restricted_page() -> str:
    return "\n".join(
        [
            "---",
            "type: lesson",
            f"title: {CANARY} restricted title",
            f"description: {CANARY} restricted description",
            f"tags: [{CANARY}]",
            f"status: {CANARY}",
            f"origin: {CANARY}",
            f"work_id: {CANARY}",
            "sensitivity: Restricted",
            "relates_to:",
            f"  - path: notes/{CANARY}.md",
            "    kind: related",
            "---",
            "",
            f"{CANARY} restricted body.",
            "",
        ]
    )


def contract(root: Path, atlas_id: str, title: str) -> None:
    write(root / "CONTRACT.json", json.dumps({"schema_version": "1.0", "atlas_id": atlas_id, "title": title}) + "\n")


def build_mesh(tmp: Path, *, graph_scope: str | None = None, graph_driver: str | None = None) -> Path:
    """A project with alpha, beta and gamma members, an excluded store and an unmounted row."""
    project = tmp / "proj"
    alpha = project / "atlas" / "alpha"
    contract(alpha, ALPHA, "Alpha")
    write(alpha / "notes" / "x.md", page("X", type_="spec"))
    write(alpha / "notes" / "hidden.md", restricted_page())
    write(
        alpha / "notes" / "local.md",
        page("Local", [("notes/x.md", "related"), ("notes/missing.md", "related"), ("notes/hidden.md", "related")]),
    )
    write(alpha / "notes" / "old.md", page("Old", [("notes/x.md", "implements")], extra=["kva: terminated"]).replace("kva: K\n", "", 1))
    beta = project / "atlas" / "beta"
    contract(beta, BETA, "Beta")
    write(beta / "notes" / "child.md", page("Child", [(f"atlas://{ALPHA}/notes/x.md", "implements")]))
    write(
        beta / "notes" / "grand.md",
        page(
            "Grand",
            [
                ("notes/child.md", "implements"),
                (f"atlas://{SECRET}/notes/s.md", "related"),
                (f"atlas://{GONE}/notes/g.md", "related"),
                (f"atlas://{ELSEWHERE}/notes/e.md", "related"),
                ("../../../../outside.md", "related"),
                ("atlas://alpha/notes/x.md", "related"),
            ],
        ),
    )
    gamma = project / "atlas" / "gamma"
    contract(gamma, GAMMA, "Gamma")
    write(gamma / "notes" / "g.md", page("Gamma", [("../alpha/notes/x.md", "related")], type_="howto"))
    secret = project / "atlas" / "secret"
    contract(secret, SECRET, f"{CANARY} secret")
    write(secret / "notes" / "s.md", page(f"Secret {CANARY}"))
    doc: dict = {
        "version": 1,
        "stores": [
            {"id": ALPHA, "path": "atlas/alpha"},
            {"id": BETA, "path": "atlas/beta"},
            {"id": GAMMA, "path": "atlas/gamma"},
            {"id": SECRET, "path": "atlas/secret", "mesh_member": False},
            {"id": GONE, "path": "atlas/gone"},
        ],
    }
    graph: dict = {}
    if graph_scope:
        graph["scope"] = graph_scope
    if graph_driver:
        graph["driver"] = graph_driver
    if graph:
        doc["graph"] = graph
    write(project / "atlas-mesh.json", json.dumps(doc, indent=2) + "\n")
    return project


def set_graph_config(project: Path, **values: str) -> None:
    path = project / "atlas-mesh.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    if values:
        doc["graph"] = values
    else:
        doc.pop("graph", None)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def env() -> dict[str, str]:
    e = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_")}
    e["DBUS_SESSION_BUS_ADDRESS"] = "disabled:"
    e["PATH"] = os.environ.get("PATH", "")
    return e


def atlas(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args], capture_output=True, text=True, env=env(), cwd=str(cwd) if cwd else None
    )


def as_json(proc: subprocess.CompletedProcess) -> dict:
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_raw": proc.stdout, "_err": proc.stderr}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-graph-"))
    try:
        run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILURES:
        print(f"\n{len(FAILURES)} mesh graph check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("\nAll mesh graph checks passed")
    return 0


def run(tmp: Path) -> None:
    project = build_mesh(tmp)
    alpha = project / "atlas" / "alpha"
    beta = project / "atlas" / "beta"
    x_id = f"atlas://{ALPHA}/notes/x.md"
    child_id = f"atlas://{BETA}/notes/child.md"
    grand_id = f"atlas://{BETA}/notes/grand.md"

    print("neighbours across stores")
    p = atlas("graph", "neighbours", x_id, "--direction", "in", "--kind", "implements", "--hops", "2",
              "--scope", "mesh", "--root", str(alpha), "--json")
    d = as_json(p)
    ids = {n["id"]: n for n in d.get("nodes") or []}
    check("neighbours-exit-0", p.returncode == 0, p.stderr)
    check("neighbours-scope-mesh", d.get("scope") == "mesh" and bool(d.get("mesh_digest")))
    check("neighbours-seed", d.get("seed") == x_id, d.get("seed"))
    check("neighbours-child-in-beta", ids.get(child_id, {}).get("hop") == 1 and ids[child_id]["atlas_id"] == BETA, ids)
    check("neighbours-grandchild-hop-2", ids.get(grand_id, {}).get("hop") == 2, ids)
    check("neighbours-title-hydrated", ids.get(child_id, {}).get("title", "").startswith("Child"), ids.get(child_id))
    check("neighbours-exit-state-skipped", f"atlas://{ALPHA}/notes/old.md" not in ids)
    check("neighbours-driver-native", d.get("driver_used") == "native-graph" and "driver_note" not in d, d.get("driver_used"))
    cross = [e for e in d.get("edges") or [] if e.get("from") == child_id]
    check("neighbours-cross-edge", bool(cross) and cross[0].get("cross") is True and cross[0].get("to") == x_id, cross)
    p = atlas("graph", "neighbours", x_id, "--direction", "in", "--kind", "implements", "--hops", "2",
              "--include-exits", "--scope", "mesh", "--root", str(alpha), "--json")
    check("neighbours-include-exits", f"atlas://{ALPHA}/notes/old.md" in {n["id"] for n in as_json(p).get("nodes") or []})
    p = atlas("graph", "neighbours", "notes/x.md", "--direction", "in", "--hops", "1", "--max-nodes", "1",
              "--scope", "mesh", "--root", str(alpha), "--json")
    d = as_json(p)
    check("neighbours-root-path-seed", p.returncode == 0 and d.get("seed") == x_id, p.stdout + p.stderr)
    check("neighbours-truncated", d.get("truncated") is True, d.get("truncated"))
    p = atlas("graph", "neighbours", "notes/x.md", "--scope", "mesh", "--root", str(alpha))
    check("neighbours-text", p.returncode == 0 and "scope=mesh" in p.stdout and child_id in p.stdout, p.stdout + p.stderr)
    p = atlas("graph", "neighbours", f"atlas://{SECRET}/notes/s.md", "--scope", "mesh", "--root", str(alpha), "--json")
    check("neighbours-excluded-seed-exit-2", p.returncode == 2 and as_json(p).get("ok") is False, p.stdout)
    p = atlas("graph", "neighbours", f"atlas://{ALPHA}/notes/hidden.md", "--scope", "mesh", "--root", str(alpha), "--json")
    check("neighbours-restricted-seed-exit-2", p.returncode == 2 and CANARY not in p.stdout, p.stdout)

    print("edges")
    p = atlas("graph", "edges", "--all", "--scope", "mesh", "--root", str(alpha), "--json")
    d = as_json(p)
    edges = d.get("edges") or []
    check("edges-exit-0", p.returncode == 0, p.stderr)
    canonical = [e for e in edges if e["from"] == child_id and e["to"] == x_id]
    check(
        "edges-canonical-cross-resolved",
        len(canonical) == 1 and canonical[0]["resolved"] and canonical[0]["cross"] and canonical[0]["resolution"] == "atlas_uri",
        canonical,
    )
    reasons = {e.get("reason") for e in edges if not e.get("resolved")}
    expected = {"unmounted", "excluded_member", "missing_page", "withheld", "outside_mesh", "noncanonical_atlas_uri"}
    check("edges-every-reason", reasons == expected, reasons)
    counts = d.get("unresolved_by_reason") or {}
    check("edges-reason-counts", all(counts.get(r, 0) >= 1 for r in expected) and counts.get("unmounted") == 2, counts)
    check("edges-count-matches", sum(counts.values()) == sum(1 for e in edges if not e["resolved"]), counts)
    short = [e for e in edges if e.get("reason") == "noncanonical_atlas_uri"]
    check("edges-short-form-suggest", short and short[0].get("suggest") == x_id, short)
    mesh_path = [e for e in edges if e.get("resolution") == "mesh_path" and e.get("resolved")]
    check("edges-mesh-path-suggest", mesh_path and mesh_path[0].get("suggest") == x_id, mesh_path)
    check("edges-no-text", CANARY not in p.stdout)
    check("edges-excluded-not-a-node", f"atlas://{SECRET}/notes/s.md" not in {e["from"] for e in edges})
    p = atlas("graph", "edges", "--all", "--store", BETA, "--scope", "mesh", "--root", str(alpha), "--json")
    d = as_json(p)
    check("edges-store-filter", p.returncode == 0 and d.get("edges") and all(e["from"].startswith(f"atlas://{BETA}/") for e in d["edges"]), d)
    p = atlas("graph", "edges", "--to", x_id, "--kind", "implements", "--scope", "mesh", "--root", str(alpha), "--json")
    check("edges-to-filter", {e["from"] for e in as_json(p).get("edges") or []} == {child_id}, p.stdout)
    p = atlas("graph", "edges", "--to", x_id, "--kind", "implements", "--include-exits", "--scope", "mesh", "--root", str(alpha), "--json")
    d = as_json(p)
    check("edges-to-include-exits", {e["from"] for e in d.get("edges") or []} == {child_id, f"atlas://{ALPHA}/notes/old.md"}, d.get("edges"))

    print("nodes")
    p = atlas("graph", "nodes", "--scope", "mesh", "--root", str(alpha), "--json")
    d = as_json(p)
    nids = {n["id"] for n in d.get("nodes") or []}
    check("nodes-three-members", {n["atlas_id"] for n in d.get("nodes") or []} == {ALPHA, BETA, GAMMA}, nids)
    check("nodes-no-restricted", f"atlas://{ALPHA}/notes/hidden.md" not in nids)
    check("nodes-default-hides-exits", f"atlas://{ALPHA}/notes/old.md" not in nids)
    check("nodes-keys", all({"id", "atlas_id", "path", "type", "title"} <= set(n) for n in d.get("nodes") or []))
    p = atlas("graph", "nodes", "--store", GAMMA, "--store", BETA, "--scope", "mesh", "--root", str(alpha), "--json")
    check("nodes-store-filter", {n["atlas_id"] for n in as_json(p).get("nodes") or []} == {BETA, GAMMA}, p.stdout)
    p = atlas("graph", "nodes", "--where", "type=spec", "--scope", "mesh", "--root", str(alpha), "--json")
    check("nodes-where-indexed", [n["id"] for n in as_json(p).get("nodes") or []] == [x_id], p.stdout)
    p = atlas("graph", "nodes", "--where", "created=2026-10-10", "--store", GAMMA, "--scope", "mesh", "--root", str(alpha), "--json")
    check("nodes-where-hydrated", [n["id"] for n in as_json(p).get("nodes") or []] == [f"atlas://{GAMMA}/notes/g.md"], p.stdout)
    p = atlas("graph", "nodes", "--store", "github.com/acme/nope", "--scope", "mesh", "--root", str(alpha), "--json")
    check("nodes-unknown-store-exit-2", p.returncode == 2, p.returncode)
    p = atlas("graph", "nodes", "--store", SECRET, "--scope", "mesh", "--root", str(alpha), "--json")
    check("nodes-excluded-store-exit-2", p.returncode == 2, p.returncode)

    print("scope precedence and refusals")
    store_nodes = atlas("graph", "nodes", "--root", str(alpha), "--json")
    check("default-store-scope", store_nodes.returncode == 0 and "scope" not in as_json(store_nodes), store_nodes.stdout[:200])
    p = atlas("graph", "nodes", "--store", BETA, "--root", str(alpha), "--json")
    check("store-flag-in-store-scope-exit-2", p.returncode == 2 and "--store" in as_json(p).get("error", ""), p.stdout)
    p = atlas("graph", "edges", "--all", "--store", BETA, "--scope", "store", "--root", str(alpha), "--json")
    check("store-flag-explicit-store-exit-2", p.returncode == 2, p.returncode)
    set_graph_config(project, scope="mesh")
    p = atlas("graph", "nodes", "--root", str(alpha), "--json")
    check("config-scope-mesh", as_json(p).get("scope") == "mesh", p.stdout[:200])
    p = atlas("graph", "nodes", "--scope", "store", "--root", str(alpha), "--json")
    check("flag-beats-config", p.returncode == 0 and p.stdout == store_nodes.stdout, p.stdout[:200])
    set_graph_config(project, scope="mesh", driver="nanograph")
    p = atlas("graph", "neighbours", x_id, "--root", str(alpha), "--json")
    d = as_json(p)
    check("config-nanograph-falls-back", p.returncode == 0 and "packet MD" in (d.get("driver_note") or "") and d.get("driver_used") == "native-graph", d)
    set_graph_config(project)
    p = atlas("graph", "neighbours", x_id, "--driver", "nanograph", "--scope", "mesh", "--root", str(alpha), "--json")
    d = as_json(p)
    check("flag-nanograph-falls-back", p.returncode == 0 and "packet MD" in (d.get("driver_note") or ""), d)
    standalone = tmp / "solo"
    contract(standalone, "github.com/acme/solo", "Solo")
    write(standalone / "notes" / "a.md", page("Solo"))
    p = atlas("graph", "nodes", "--scope", "mesh", "--root", str(standalone), "--json")
    check("standalone-mesh-exit-2", p.returncode == 2 and "no atlas-mesh.json lists this store" in as_json(p).get("error", ""), p.stdout)
    p = atlas("graph", "nodes", "--root", str(standalone), "--json")
    check("standalone-store-ok", p.returncode == 0, p.stderr)

    print("export")
    out = tmp / "out"
    p = atlas("graph", "export", "--scope", "mesh", "--format", "json", "--out", str(out), "--root", str(alpha), "--json")
    d = as_json(p)
    check("export-exit-0", p.returncode == 0, p.stdout + p.stderr)
    check("export-receipt-members", d.get("members") == sorted([ALPHA, BETA, GAMMA]) and d.get("excluded") == [SECRET], d)
    check("export-receipt-unresolved", d.get("unresolved") == sum((d.get("unresolved_by_reason") or {}).values()) and d.get("unresolved", 0) > 0, d)
    graph_doc = json.loads((out / "graph.json").read_text(encoding="utf-8"))
    receipt = json.loads((out / "export-receipt.json").read_text(encoding="utf-8"))
    check("export-receipt-file", receipt.get("scope") == "mesh" and receipt.get("structure_only") is True, receipt)
    check("export-structure-only", CANARY not in (out / "graph.json").read_text(encoding="utf-8"))
    check("export-no-title-keys", all("title" not in n and "description" not in n for n in graph_doc.get("nodes") or []))
    for label, bad in (("member-root", beta / "exp"), ("indexes", project / ".atlas" / "indexes" / "exp")):
        p = atlas("graph", "export", "--scope", "mesh", "--format", "json", "--out", str(bad), "--root", str(alpha), "--json")
        check(f"export-refuses-{label}", p.returncode == 2 and not bad.exists(), p.stdout)
    p = atlas("graph", "export", "--scope", "mesh", "--format", "nanograph", "--out", str(tmp / "ng"), "--root", str(alpha), "--json")
    check("export-nanograph-exit-2", p.returncode == 2 and "packet MD" in as_json(p).get("error", ""), p.stdout)

    print("index build/status/show")
    p = atlas("index", "build", "--mesh", "--root", str(project), "--json")
    d = as_json(p)
    check("index-build-mesh", p.returncode == 0 and d.get("mesh", {}).get("status") in ("built", "fresh"), p.stdout + p.stderr)
    p = atlas("index", "build", "--mesh", "--force", "--root", str(project), "--json")
    check("index-build-mesh-force", p.returncode == 0 and as_json(p).get("mesh", {}).get("status") == "built", p.stdout)
    p = atlas("index", "build", "--mesh", "--all", "--root", str(project), "--json")
    d = as_json(p)
    check("index-build-mesh-all", p.returncode == 0 and len(d.get("stores") or []) == 5 and d.get("mesh", {}).get("status") == "fresh", p.stdout[:400])
    p = atlas("index", "build", "--mesh", "--store", ALPHA, "--root", str(project), "--json")
    check("index-build-mesh-store-exit-2", p.returncode == 2, p.returncode)
    p = atlas("index", "build", "--mesh", "--root", str(standalone), "--json")
    check("index-build-mesh-standalone-exit-2", p.returncode == 2, p.returncode)
    p = atlas("index", "status", "--root", str(project), "--json")
    d = as_json(p)
    block = d.get("mesh") or {}
    check("status-mesh-block", set(block) >= {"members", "excluded", "scope", "indexes"}, list(block))
    check("status-members", {m["atlas_id"]: m["status"] for m in block.get("members") or []}.get(GONE) == "unmounted", block.get("members"))
    check("status-excluded", block.get("excluded") == [SECRET], block.get("excluded"))
    check(
        "status-scope",
        block.get("scope") == {"recall": "store", "graph": "store", "source": {"recall": "default", "graph": "default"}},
        block.get("scope"),
    )
    g = (block.get("indexes") or {}).get("graph") or {}
    check("status-graph-index", g.get("dir") == ".atlas/indexes/graph/_mesh" and g.get("fresh") is True and g.get("generation"), g)
    check("status-unresolved", (g.get("unresolved_by_reason") or {}).get("withheld") == 1, g.get("unresolved_by_reason"))
    check("status-nanograph-not-built", (block.get("indexes") or {}).get("nanograph", {}).get("built") is False)
    p = atlas("index", "show", "--mesh", "--root", str(project), "--json")
    d = as_json(p)
    check("show-mesh-block-alone", p.returncode == 0 and set(d) == {"ok", "mesh"} and d["mesh"] == block, list(d))
    p = atlas("index", "show", "--mesh", "--root", str(project))
    check("show-mesh-text", p.returncode == 0 and "mesh graph: .atlas/indexes/graph/_mesh" in p.stdout and "fresh=true" in p.stdout, p.stdout)
    p = atlas("index", "status", "--root", str(project))
    check("status-text-mesh-lines", "mesh members:" in p.stdout, p.stdout)
    set_graph_config(project, scope="mesh")
    d = as_json(atlas("index", "status", "--root", str(project), "--json"))
    check("status-scope-config", (d.get("mesh") or {}).get("scope", {}).get("source", {}).get("graph") == "config", d.get("mesh"))
    set_graph_config(project)

    fresh = tmp / "fresh"
    fresh_project = build_mesh(fresh)
    d = as_json(atlas("index", "status", "--root", str(fresh_project), "--json"))
    check("status-no-block-before-use", "mesh" not in d, list(d))

    run_merged_contract(tmp)


def add_contract_rows(tmp: Path, project: Path) -> None:
    """MA's final contract: an `invalid` row (outside the project) and a page path holding `#`."""
    ext = tmp / "ext"
    contract(ext, EXT, f"{EXT_CANARY} ext")
    write(ext / "notes" / "e.md", page(f"Ext {EXT_CANARY}").replace(CANARY, EXT_CANARY))
    alpha = project / "atlas" / "alpha"
    write(alpha / "notes" / "a#b.md", page("Hash", [("notes/x.md", "related")]))
    write(alpha / "notes" / "to-hash.md", page("ToHash", [("notes/a#b.md", "related"), (f"atlas://{EXT}/notes/e.md", "related")]))
    write(project / "atlas" / "beta" / "notes" / "to-hash.md", page("BetaToHash", [(f"atlas://{ALPHA}/notes/a%23b.md", "implements")]))
    path = project / "atlas-mesh.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["stores"].append({"id": EXT, "path": "../ext"})
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def run_merged_contract(tmp: Path) -> None:
    base = tmp / "contract"
    project = build_mesh(base)
    add_contract_rows(base, project)
    alpha = project / "atlas" / "alpha"
    hash_id = f"atlas://{ALPHA}/notes/a%23b.md"
    ext_id = f"atlas://{EXT}/notes/e.md"

    print("invalid member (MA R2: outside_project) is never read and is reported")
    p = atlas("graph", "nodes", "--scope", "mesh", "--root", str(alpha), "--json")
    d = as_json(p)
    check("invalid-nodes-exit-0", p.returncode == 0, p.stdout + p.stderr)
    check("invalid-no-node", not any(n["atlas_id"] == EXT for n in d.get("nodes") or []), d.get("nodes"))
    check("invalid-no-canary", EXT_CANARY not in p.stdout, p.stdout)
    p = atlas("graph", "edges", "--from", "notes/to-hash.md", "--scope", "mesh", "--root", str(alpha), "--json")
    into = [e for e in as_json(p).get("edges") or [] if e["to"] == ext_id]
    check("invalid-link-outside-mesh", len(into) == 1 and into[0]["resolved"] is False and into[0].get("reason") == "outside_mesh", into)
    for verb in (("nodes",), ("edges", "--all")):
        p = atlas("graph", *verb, "--store", EXT, "--scope", "mesh", "--root", str(alpha), "--json")
        err = as_json(p).get("error", "")
        check(f"invalid-store-flag-{verb[0]}-exit-2", p.returncode == 2 and "invalid" in err and "outside_project" in err, p.stdout)
    p = atlas("graph", "neighbours", ext_id, "--scope", "mesh", "--root", str(alpha), "--json")
    check("invalid-seed-exit-2", p.returncode == 2 and "outside_project" in as_json(p).get("error", "") and EXT_CANARY not in p.stdout, p.stdout)
    out = base / "out"
    p = atlas("graph", "export", "--scope", "mesh", "--format", "json", "--out", str(out), "--root", str(alpha), "--json")
    d = as_json(p)
    check("invalid-export-reported", p.returncode == 0 and d.get("invalid") == [EXT] and EXT not in d.get("members", []), d)
    receipt = json.loads((out / "export-receipt.json").read_text(encoding="utf-8"))
    check("invalid-export-receipt", receipt.get("invalid") == [EXT], receipt)
    check("invalid-export-no-canary", EXT_CANARY not in (out / "graph.json").read_text(encoding="utf-8"))
    p = atlas("index", "build", "--mesh", "--root", str(project), "--json")
    check("invalid-index-build", p.returncode == 0, p.stdout + p.stderr)
    p = atlas("index", "show", "--mesh", "--root", str(project), "--json")
    block = as_json(p).get("mesh") or {}
    rows = {m["atlas_id"]: m for m in block.get("members") or []}
    check("invalid-member-status", rows.get(EXT, {}).get("status") == "invalid" and rows[EXT].get("reason") == "outside_project", rows.get(EXT))
    check("invalid-block-list", block.get("invalid") == [{"atlas_id": EXT, "reason": "outside_project"}], block.get("invalid"))
    check("invalid-not-excluded", block.get("excluded") == [SECRET], block.get("excluded"))
    check("invalid-index-fresh", (block.get("indexes") or {}).get("graph", {}).get("fresh") is True, block.get("indexes"))
    p = atlas("index", "status", "--root", str(project))
    check("invalid-status-text", f"mesh invalid: {EXT} (outside_project)" in p.stdout, p.stdout)
    pointer = json.loads((project / ".atlas" / "indexes" / "graph" / "_mesh" / "current.json").read_text(encoding="utf-8"))
    check("invalid-pointer", pointer.get("invalid") == [EXT], pointer.get("invalid"))
    hits = [str(f) for f in (project / ".atlas" / "indexes").rglob("*") if f.is_file() and EXT_CANARY in f.read_text(encoding="utf-8", errors="replace")]
    check("invalid-index-no-canary", hits == [], hits)
    p = atlas("index", "show", "--mesh", "--root", str(project / "missing"), "--json")
    check("show-mesh-root-not-found", p.returncode == 2 and as_json(p).get("code") == "root_not_found", p.stdout)
    p = atlas("index", "build", "--mesh", "--root", str(project / "missing"), "--json")
    check("build-mesh-root-not-found", p.returncode == 2 and as_json(p).get("code") == "root_not_found", p.stdout)

    print("page path with # (MA R3: percent-encoded node ids)")
    p = atlas("graph", "nodes", "--scope", "mesh", "--store", ALPHA, "--root", str(alpha), "--json")
    nodes = {n["id"]: n for n in as_json(p).get("nodes") or []}
    check("hash-node-encoded", hash_id in nodes and nodes[hash_id]["path"] == "notes/a#b.md", sorted(nodes))
    check("hash-no-raw-id", f"atlas://{ALPHA}/notes/a#b.md" not in nodes, sorted(nodes))
    check("hash-title-hydrated", nodes.get(hash_id, {}).get("title", "").startswith("Hash"), nodes.get(hash_id))
    from atlas_cli.core import mesh_scope

    check("hash-round-trips", mesh_scope.parse_node_id(hash_id) == (ALPHA, "notes/a#b.md") and mesh_scope.node_id(ALPHA, "notes/a#b.md") == hash_id)
    p = atlas("graph", "edges", "--to", hash_id, "--scope", "mesh", "--root", str(alpha), "--json")
    froms = {e["from"]: e for e in as_json(p).get("edges") or []}
    local = froms.get(f"atlas://{ALPHA}/notes/to-hash.md")
    cross = froms.get(f"atlas://{BETA}/notes/to-hash.md")
    check("hash-local-link", local is not None and local["resolved"] and local["resolution"] == "local", froms)
    check("hash-canonical-link", cross is not None and cross["resolved"] and cross["cross"] and cross["resolution"] == "atlas_uri", froms)
    for label, seed in (("uri", hash_id), ("root-path", "notes/a#b.md")):
        p = atlas("graph", "neighbours", seed, "--direction", "out", "--scope", "mesh", "--root", str(alpha), "--json")
        d = as_json(p)
        check(f"hash-seed-{label}", p.returncode == 0 and d.get("seed") == hash_id and f"atlas://{ALPHA}/notes/x.md" in {n["id"] for n in d.get("nodes") or []}, p.stdout + p.stderr)
    p = atlas("graph", "neighbours", hash_id, "--direction", "in", "--scope", "mesh", "--root", str(alpha), "--json")
    ins = {n["id"] for n in as_json(p).get("nodes") or []}
    check("hash-incoming", ins == {f"atlas://{ALPHA}/notes/to-hash.md", f"atlas://{BETA}/notes/to-hash.md"}, ins)
    graph_doc = json.loads((out / "graph.json").read_text(encoding="utf-8"))
    exported = {n["id"]: n["path"] for n in graph_doc.get("nodes") or []}
    check("hash-export-encoded", exported.get(hash_id) == "notes/a#b.md", exported)
    check("hash-export-round-trips", all(mesh_scope.parse_node_id(i) == (n["atlas_id"], n["path"]) for n in graph_doc["nodes"] for i in [n["id"]]))


if __name__ == "__main__":
    raise SystemExit(main())
