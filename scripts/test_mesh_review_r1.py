#!/usr/bin/env python3
"""Review R1: every atlas id mesh validation accepts round-trips through node
ids and the strict resolver, including hosts without a dot (``localhost``,
``localhost:8080``, a single-label intranet host).

Rule: the first segment after ``atlas://`` is a canonical host when it is
host-shaped on its own (a dot, a ``:port``, an IP literal or ``localhost``)
or it is the host of a mesh row id. Anything else is a short form: it stays
``noncanonical_atlas_uri`` with ``suggest`` only on a unique repo-name match.

Linux-safe: no network, no git, no real mount.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import identity, index_location, mesh_scope, meshfile  # noqa: E402

SRC = "github.com/acme/src"
LOCAL = "localhost/acme/repo"
PORTED = "localhost:8080/acme/ported"
INTRA = "intranet/acme/wiki"
LGONE = "localhost/acme/gone"
LSECRET = "localhost/acme/secret"
NO_DOT_IDS = (LOCAL, PORTED, INTRA, LGONE, LSECRET)

CONTRACT = {"schema_version": "1.0", "atlas_id": "fixture", "title": "Fixture"}

# (target, resolution, reason or None, suggest or None, to)
CASES: list[tuple[str, str, str | None, str | None, str]] = [
    (f"atlas://{LOCAL}/notes/a.md", "atlas_uri", None, None, f"atlas://{LOCAL}/notes/a.md"),
    (f"atlas://{LOCAL}/notes/a.md#claim", "atlas_uri", None, None, f"atlas://{LOCAL}/notes/a.md"),
    ("atlas://LocalHost/Acme/Repo/notes/a.md", "atlas_uri", None, None, f"atlas://{LOCAL}/notes/a.md"),
    (f"atlas://{PORTED}/notes/p.md", "atlas_uri", None, None, f"atlas://{PORTED}/notes/p.md"),
    (f"atlas://{INTRA}/notes/w.md", "atlas_uri", None, None, f"atlas://{INTRA}/notes/w.md"),
    (f"atlas://{LOCAL}/notes/missing.md", "atlas_uri", "missing_page", None, f"atlas://{LOCAL}/notes/missing.md"),
    (f"atlas://{INTRA}/notes/missing.md", "atlas_uri", "missing_page", None, f"atlas://{INTRA}/notes/missing.md"),
    (f"atlas://{LGONE}/notes/x.md", "atlas_uri", "unmounted", None, f"atlas://{LGONE}/notes/x.md"),
    ("atlas://localhost/nobody/else/x.md", "atlas_uri", "unmounted", None, "atlas://localhost/nobody/else/x.md"),
    (f"atlas://{LSECRET}/notes/s.md", "atlas_uri", "excluded_member", None, f"atlas://{LSECRET}/notes/s.md"),
    # Genuine short forms: never an alias, suggest only on a unique repo-name match.
    ("atlas://repo/x.md", "atlas_uri", "noncanonical_atlas_uri", f"atlas://{LOCAL}/x.md", "atlas://repo/x.md"),
    (
        "atlas://repo/notes/sub/a.md",
        "atlas_uri",
        "noncanonical_atlas_uri",
        f"atlas://{LOCAL}/notes/sub/a.md",
        "atlas://repo/notes/sub/a.md",
    ),
    ("atlas://ported/notes/p.md", "atlas_uri", "noncanonical_atlas_uri", f"atlas://{PORTED}/notes/p.md", "atlas://ported/notes/p.md"),
    ("atlas://wiki/notes/w.md", "atlas_uri", "noncanonical_atlas_uri", None, "atlas://wiki/notes/w.md"),
    ("atlas://acme/repo/notes/a.md", "atlas_uri", "noncanonical_atlas_uri", None, "atlas://acme/repo/notes/a.md"),
    ("atlas://nobody/notes/x.md", "atlas_uri", "noncanonical_atlas_uri", None, "atlas://nobody/notes/x.md"),
]


def page(title: str, rels: list[str] | None = None) -> str:
    lines = ["---", "type: lesson", f"title: {title}", "created: 2026-10-10"]
    if rels:
        lines.append("relates_to:")
        for target in rels:
            lines.append(f"  - path: {json.dumps(target)}")
            lines.append("    kind: related")
    lines += ["---", "", f"Body of {title}.", ""]
    return "\n".join(lines)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_store(root: Path, pages: dict[str, str]) -> None:
    write(root / "CONTRACT.json", json.dumps(CONTRACT, indent=2) + "\n")
    for rel, text in pages.items():
        write(root / rel, text)


def build_fixture(tmp: Path) -> Path:
    project = tmp / "proj"
    make_store(project / "atlas" / "src", {"notes/src.md": page("Source", [t for t, *_ in CASES])})
    make_store(project / "atlas" / "local", {"notes/a.md": page("Local A", ["notes/missing-too.md"])})
    make_store(project / "atlas" / "ported", {"notes/p.md": page("Ported")})
    make_store(project / "atlas" / "wiki", {"notes/w.md": page("Wiki")})
    make_store(project / "atlas" / "secret", {"notes/s.md": page("Secret")})
    doc = {
        "version": 1,
        "stores": [
            {"id": SRC, "path": "atlas/src"},
            {"id": LOCAL, "path": "atlas/local"},
            {"id": PORTED, "path": "atlas/ported"},
            {"id": INTRA, "path": "atlas/wiki"},
            {"id": "github.com/other/wiki", "path": "atlas/other-wiki"},
            {"id": LGONE, "path": "atlas/lgone"},
            {"id": LSECRET, "path": "atlas/secret", "mesh_member": False},
        ],
    }
    write(project / "atlas-mesh.json", json.dumps(doc, indent=2) + "\n")
    return project


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-r1-"))
    try:
        index_location.clear_cache()
        project = build_fixture(tmp)
        doc = json.loads((project / "atlas-mesh.json").read_text(encoding="utf-8"))
        errs = meshfile.validate_doc(doc)
        check("mesh-validation-accepts-no-dot-hosts", errs == [], json.dumps(errs))
        for sid in NO_DOT_IDS:
            check(f"identity-accepts {sid}", identity.normalise(sid) == sid, identity.normalise(sid))

        # node_id -> parse_node_id round-trip for every accepted id, with and without mesh hosts.
        hosts = mesh_scope.mesh_hosts(row["id"] for row in doc["stores"])
        for sid in NO_DOT_IDS + (SRC,):
            for rel in ("notes/a.md", "./deep/er/b.md"):
                nid = mesh_scope.node_id(sid, rel)
                try:
                    got = mesh_scope.parse_node_id(nid)
                    with_hosts = mesh_scope.parse_node_id(nid, hosts)
                except mesh_scope.MeshScopeError as e:
                    got = with_hosts = (str(e), "")
                want = (sid, rel.removeprefix("./"))
                check(f"round-trip {nid}", got == want and with_hosts == want, f"{got} {with_hosts}")
                check(f"canonical-host {nid}", mesh_scope.is_canonical_host(nid, hosts))
        for host_shaped in (LOCAL, PORTED, LGONE):
            check(f"host-shaped-without-mesh {host_shaped}", mesh_scope.is_canonical_host(f"atlas://{host_shaped}/x.md"))
        for short in ("atlas://repo/x.md", "atlas://acme/repo/notes/a.md", "atlas://wiki/notes/w.md"):
            check(f"short-form-not-canonical {short}", not mesh_scope.is_canonical_host(short, hosts))
            try:
                mesh_scope.parse_node_id(short, hosts)
                raised = False
            except mesh_scope.MeshScopeError:
                raised = True
            check(f"parse-node-id-with-hosts-rejects {short}", raised)

        # Resolver: canonical links into no-dot-host members resolve; short forms stay strict.
        mesh = mesh_scope.discover(project / "atlas" / "src")
        all_members = mesh_scope.members(mesh)
        statuses = {m.atlas_id: m.status for m in all_members}
        check(
            "member-statuses",
            statuses[LOCAL] == "ok"
            and statuses[PORTED] == "ok"
            and statuses[INTRA] == "ok"
            and statuses[LGONE] == "unmounted"
            and statuses[LSECRET] == "excluded",
            json.dumps(statuses),
        )
        loaded = {m.index: mesh_scope.load_member(m) for m in all_members if m.status == "ok"}
        resolver = mesh_scope.Resolver(mesh, all_members, loaded)
        source = all_members[0]
        for target, resolution, reason, suggest, to in CASES:
            rec = resolver.classify(source, target)
            ok = (
                rec.get("resolution") == resolution
                and rec.get("reason") == reason
                and rec.get("suggest") == suggest
                and rec.get("resolved") is (reason is None)
                and rec.get("to") == to
            )
            check(f"case {target}", ok, json.dumps(rec))

        view = mesh_scope.build_view(mesh)
        node_ids = {n["id"] for n in view["nodes"]}
        for sid, rel in ((LOCAL, "notes/a.md"), (PORTED, "notes/p.md"), (INTRA, "notes/w.md")):
            nid = f"atlas://{sid}/{rel}"
            check(f"view-node {nid}", nid in node_ids)
        resolved_to = {e["to"] for e in view["edges"] if e["resolved"]}
        check(
            "view-edges-reach-no-dot-nodes",
            all(nid in node_ids for nid in resolved_to) and f"atlas://{LOCAL}/notes/a.md" in resolved_to,
            json.dumps(sorted(resolved_to)),
        )
        check(
            "view-every-node-id-parses",
            all(mesh_scope.parse_node_id(nid, hosts)[0] in statuses for nid in node_ids),
        )
        local_edge = [e for e in view["edges"] if e["from"] == f"atlas://{LOCAL}/notes/a.md"]
        check(
            "local-missing-in-no-dot-member",
            len(local_edge) == 1
            and local_edge[0]["resolution"] == "local"
            and local_edge[0].get("reason") == "missing_page"
            and local_edge[0]["to"] == f"atlas://{LOCAL}/notes/missing-too.md",
            json.dumps(local_edge),
        )
        check(
            "no-short-form-resolved",
            not any(e["resolved"] and e["resolution"] == "atlas_uri" and not mesh_scope.is_canonical_host(e["to"], hosts) for e in view["edges"]),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"FAILED {len(failed)}: {', '.join(failed)}")
        return 1
    print("test_mesh_review_r1: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
