#!/usr/bin/env python3
"""Strict cross-store resolver (M4, M21): every relates_to target in mesh scope
is classified once, with ``resolution``, ``reason`` and ``suggest`` as pinned.

Linux-safe: no network, no git, no real mount.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, mesh_scope  # noqa: E402

ALPHA = "github.com/acme/alpha"
BETA = "github.com/acme/beta"
MONO = "github.com/acme/mono"
DELTA = "github.com/acme/delta"
SECRET = "github.com/acme/secret"
GONE = "github.com/acme/gone"
GONE2 = "github.com/other/gone"
CARTO = "github.com/acme/atlas-cartograph-atlas"

CONTRACT = {"schema_version": "1.0", "atlas_id": "fixture", "title": "Fixture"}


def page(title: str, rels: list[tuple[str, str]] | None = None, extra: str = "") -> str:
    lines = ["---", "type: lesson", f"title: {title}", "created: 2026-10-10"]
    if extra:
        lines.append(extra)
    if rels:
        lines.append("relates_to:")
        for target, kind in rels:
            lines.append(f"  - path: {json.dumps(target)}")
            lines.append(f"    kind: {kind}")
    lines += ["---", "", f"Body of {title}.", ""]
    return "\n".join(lines)


# (target, kind, expected resolution, expected reason or None, expected suggest or None, expected to or None, cross)
CASES: list[tuple[str, str, str, str | None, str | None, str | None, bool]] = [
    ("work/hub.md", "implements", "local", None, None, f"atlas://{ALPHA}/work/hub.md", False),
    ("notes/missing.md", "related", "local", "missing_page", None, f"atlas://{ALPHA}/notes/missing.md", False),
    ("notes/private.md", "related", "local", "withheld", None, f"atlas://{ALPHA}/notes/private.md", False),
    (f"atlas://{BETA}/notes/peer.md", "derived_from", "atlas_uri", None, None, f"atlas://{BETA}/notes/peer.md", True),
    (f"atlas://{BETA}/notes/peer.md#claim", "follows", "atlas_uri", None, None, f"atlas://{BETA}/notes/peer.md", True),
    ("atlas://GitHub.com/Acme/Beta/notes/peer.md", "supports", "atlas_uri", None, None, f"atlas://{BETA}/notes/peer.md", True),
    ("../beta/notes/peer.md", "related", "mesh_path", None, f"atlas://{BETA}/notes/peer.md", f"atlas://{BETA}/notes/peer.md", True),
    (f".atlas/{DELTA}/notes/d.md", "related", "mesh_path", None, f"atlas://{DELTA}/notes/d.md", f"atlas://{DELTA}/notes/d.md", True),
    ("atlas://beta/notes/peer.md", "related", "atlas_uri", "noncanonical_atlas_uri", f"atlas://{BETA}/notes/peer.md", "atlas://beta/notes/peer.md", True),
    ("atlas://atlas-cartograph-atlas/x.md", "related", "atlas_uri", "noncanonical_atlas_uri", f"atlas://{CARTO}/x.md", "atlas://atlas-cartograph-atlas/x.md", True),
    ("atlas://atlas-skill-memory/notes/x.md", "related", "atlas_uri", "noncanonical_atlas_uri", None, "atlas://atlas-skill-memory/notes/x.md", True),
    ("atlas://gone/notes/x.md", "related", "atlas_uri", "noncanonical_atlas_uri", None, "atlas://gone/notes/x.md", True),
    ("atlas://github.com/acme", "related", "atlas_uri", "noncanonical_atlas_uri", None, "atlas://github.com/acme", True),
    (f"atlas://{GONE}/notes/x.md", "related", "atlas_uri", "unmounted", None, f"atlas://{GONE}/notes/x.md", True),
    ("atlas://github.com/nobody/else/x.md", "related", "atlas_uri", "unmounted", None, "atlas://github.com/nobody/else/x.md", True),
    (f"atlas://{SECRET}/notes/s.md", "related", "atlas_uri", "excluded_member", None, f"atlas://{SECRET}/notes/s.md", True),
    ("../secret/notes/s.md", "related", "mesh_path", "excluded_member", None, "../secret/notes/s.md", True),
    ("../gone/notes/x.md", "related", "mesh_path", "unmounted", None, "../gone/notes/x.md", True),
    (f"atlas://{BETA}/notes/nope.md", "related", "atlas_uri", "missing_page", None, f"atlas://{BETA}/notes/nope.md", True),
    ("../beta/notes/nope.md", "related", "mesh_path", "missing_page", None, f"atlas://{BETA}/notes/nope.md", True),
    (f"atlas://{BETA}/notes/locked.md", "related", "atlas_uri", "withheld", None, f"atlas://{BETA}/notes/locked.md", True),
    ("../beta/linked/page.md", "related", "mesh_path", "outside_mesh", None, "../beta/linked/page.md", True),
    ("../../outside.md", "related", "mesh_path", "outside_mesh", None, "../../outside.md", True),
    ("../mono/README.md", "related", "mesh_path", "outside_mesh", None, "../mono/README.md", True),
    (f"atlas://{MONO}/guide/m.md", "related", "atlas_uri", None, None, f"atlas://{MONO}/guide/m.md", True),
    ("../mono/docs/guide/m.md", "related", "mesh_path", None, f"atlas://{MONO}/guide/m.md", f"atlas://{MONO}/guide/m.md", True),
    (f"atlas://{ALPHA}/work/hub.md", "related", "atlas_uri", None, None, f"atlas://{ALPHA}/work/hub.md", False),
]

BETA_RELS = [(f"atlas://{ALPHA}/notes/src.md", "related"), ("notes/locked.md", "related")]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_store(root: Path, pages: dict[str, str]) -> Path:
    write(root / "CONTRACT.json", json.dumps(CONTRACT, indent=2) + "\n")
    for rel, text in pages.items():
        write(root / rel, text)
    return root


def build_fixture(tmp: Path) -> tuple[Path, dict[str, int]]:
    """A five-row mesh plus two unmounted rows; returns the project and authored edge counts."""
    project = tmp / "proj"
    make_store(
        project / "atlas" / "alpha",
        {
            "work/hub.md": page("Hub"),
            "notes/src.md": page("Source", [(t, k) for t, k, *_ in CASES]),
            "notes/private.md": page("Private", [("work/hub.md", "related")], "sensitivity: restricted"),
        },
    )
    make_store(
        project / "atlas" / "beta",
        {
            "notes/peer.md": page("Peer", BETA_RELS),
            "notes/locked.md": page("Locked", [("notes/peer.md", "related")], "sensitivity: ' Restricted '"),
        },
    )
    outside = tmp / "elsewhere"
    write(outside / "page.md", page("Outside"))
    (project / "atlas" / "beta" / "linked").symlink_to(outside, target_is_directory=True)
    write(project / "outside.md", page("Project file"))
    write(project / "atlas" / "mono" / "README.md", "# mono repo\n")
    make_store(project / "atlas" / "mono" / "docs", {"guide/m.md": page("Mono guide", [("guide/m.md", "related")])})
    make_store(project / ".atlas" / "github.com" / "acme" / "delta", {"notes/d.md": page("Delta")})
    make_store(project / "atlas" / "secret", {"notes/s.md": page("Secret")})
    doc = {
        "version": 1,
        "stores": [
            {"id": ALPHA, "path": "atlas/alpha"},
            {"id": BETA, "path": "atlas/beta"},
            {"id": MONO, "path": "atlas/mono", "subpath": "docs"},
            {"id": DELTA},
            {"id": SECRET, "path": "atlas/secret", "mesh_member": False},
            {"id": GONE, "path": "atlas/gone"},
            {"id": GONE2, "path": "atlas/gone2"},
            {"id": CARTO, "path": "atlas/carto"},
        ],
    }
    write(project / "atlas-mesh.json", json.dumps(doc, indent=2) + "\n")
    # Authored relates_to on included, non-restricted pages only.
    authored = {"alpha": len(CASES), "beta": len(BETA_RELS), "mono": 1}
    return project, authored


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-resolver-"))
    try:
        index_location.clear_cache()
        project, authored = build_fixture(tmp)
        mesh = mesh_scope.discover(project / "atlas" / "alpha")
        view = mesh_scope.build_view(mesh)
        src = f"atlas://{ALPHA}/notes/src.md"
        from_src = [e for e in view["edges"] if e["from"] == src]

        resolver_members = mesh_scope.members(mesh)
        loaded = {m.index: mesh_scope.load_member(m) for m in resolver_members if m.status == "ok"}
        resolver = mesh_scope.Resolver(mesh, resolver_members, loaded)
        alpha_member = resolver_members[0]
        for target, kind, resolution, reason, suggest, to, cross in CASES:
            rec = resolver.classify(alpha_member, target)
            in_view = {"from": src, "kind": kind, **rec}
            present = sum(1 for e in from_src if e == mesh_scope._ordered(in_view))
            ok = (
                rec.get("resolution") == resolution
                and rec.get("reason") == reason
                and rec.get("suggest") == suggest
                and rec.get("resolved") is (reason is None)
                and rec.get("to") == to
                and rec.get("cross") is cross
                and present == 1
            )
            check(f"case {target} [{kind}]", ok, json.dumps(rec))

        total_authored = sum(authored.values())
        check("edge-count-equals-authored", len(view["edges"]) == total_authored, f"{len(view['edges'])} != {total_authored}")
        counts = view["unresolved_by_reason"]
        expected_counts = {r: 0 for r in mesh_scope.REASONS}
        for _t, _k, _res, reason, *_ in CASES:
            if reason:
                expected_counts[reason] += 1
        expected_counts["withheld"] += 1  # beta/notes/peer.md is fine; beta's own link to locked.md is withheld
        check("unresolved-by-reason", counts == expected_counts, f"{counts} vs {expected_counts}")
        check(
            "unresolved-total",
            sum(counts.values()) == sum(1 for e in view["edges"] if not e["resolved"]),
        )
        check("every-edge-has-reason-or-resolved", all(e["resolved"] != ("reason" in e) for e in view["edges"]))
        warn = [w for w in view["warnings"] if w["code"] == "noncanonical_cross_store_link"]
        check(
            "noncanonical-warnings",
            sorted(w["target"] for w in warn)
            == sorted(["../beta/notes/peer.md", f".atlas/{DELTA}/notes/d.md", "../mono/docs/guide/m.md"])
            and all(w["suggest"].startswith("atlas://github.com/") for w in warn),
            json.dumps(warn)[:400],
        )
        check(
            "edges-sorted",
            view["edges"] == sorted(view["edges"], key=lambda e: (e["from"], e["to"], e["kind"])),
        )
        check(
            "restricted-source-edges-absent",
            not any(e["from"].endswith("/notes/private.md") or e["from"].endswith("/notes/locked.md") for e in view["edges"]),
        )
        check(
            "excluded-and-unmounted-produce-no-nodes",
            not any(n["atlas_id"] in (SECRET, GONE, GONE2) for n in view["nodes"]),
        )
        check(
            "subpath-member-node-ids",
            any(n["id"] == f"atlas://{MONO}/guide/m.md" for n in view["nodes"])
            and any(e["from"] == f"atlas://{MONO}/guide/m.md" and e["resolution"] == "local" and e["resolved"] for e in view["edges"]),
        )
        check("no-alias-resolution", all(not (e["to"].startswith("atlas://beta/") and e["resolved"]) for e in view["edges"]))

        # node id helpers
        check("node-id", mesh_scope.node_id(BETA, "./notes/peer.md") == f"atlas://{BETA}/notes/peer.md")
        check("parse-node-id", mesh_scope.parse_node_id(f"atlas://{BETA}/notes/peer.md#x") == (BETA, "notes/peer.md"))
        for bad in ("atlas://beta/notes/peer.md", f"atlas://{BETA}", "notes/peer.md", f"atlas://{BETA}/"):
            try:
                mesh_scope.parse_node_id(bad)
                raised = False
            except mesh_scope.MeshScopeError:
                raised = True
            check(f"parse-node-id-rejects {bad}", raised)

        # no-auto-mount: an unmounted id is reported, never mounted; no git or network call.
        small = tmp / "small"
        make_store(small / "atlas" / "alpha", {"a.md": page("A", [(f"atlas://{GONE}/x.md", "related"), ("../gone/x.md", "related")])})
        write(small / "atlas-mesh.json", json.dumps({"version": 1, "stores": [{"id": ALPHA, "path": "atlas/alpha"}, {"id": GONE, "path": "atlas/gone"}]}) + "\n")
        index_location.clear_cache()
        calls: list[str] = []

        def forbid(name: str):
            def _f(*a, **k):
                calls.append(name)
                raise AssertionError(f"{name} called in mesh scope")
            return _f

        saved = {
            (subprocess, "run"): subprocess.run,
            (subprocess, "Popen"): subprocess.Popen,
            (subprocess, "check_output"): subprocess.check_output,
            (os, "system"): os.system,
            (socket, "socket"): socket.socket,
            (socket, "create_connection"): socket.create_connection,
            (urllib.request, "urlopen"): urllib.request.urlopen,
        }
        try:
            for (mod, name) in saved:
                setattr(mod, name, forbid(f"{mod.__name__}.{name}"))
            small_view = mesh_scope.build_view(mesh_scope.discover(small))
        finally:
            for (mod, name), fn in saved.items():
                setattr(mod, name, fn)
        reasons = sorted(e.get("reason") for e in small_view["edges"])
        check(
            "no-auto-mount",
            reasons == ["unmounted", "unmounted"]
            and not calls
            and not (small / "atlas" / "gone").exists()
            and small_view["members"][1]["status"] == "unmounted",
            f"{reasons} {calls}",
        )
    finally:
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} mesh resolver check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll mesh resolver checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
