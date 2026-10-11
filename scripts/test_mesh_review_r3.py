#!/usr/bin/env python3
"""Review R3: node id path segments are percent-encoded, so every page round-trips.

1. :func:`mesh_scope.node_id` encodes ``%``, ``#``, ``?``, whitespace and
   non-printable characters; :func:`mesh_scope.parse_node_id` decodes them
   back, so ``notes/a#b.md`` and friends round-trip. Ordinary ASCII and
   non-ASCII names are unchanged.
2. :func:`mesh_scope.build_view` gives every such page a unique id that
   parses back to its own path.
3. A canonical link written in encoded form resolves (``atlas_uri``) to that
   page; an unencoded ``#`` still starts a fragment, so
   ``atlas://<id>/notes/a#b.md`` names page ``notes/a``.
4. Compile's atlas:// check (``identity.parse_pointer``) reads the same
   store from the encoded link.

Linux-safe: no network, no git.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, mesh_scope  # noqa: E402
from atlas_cli.core.identity import parse_pointer  # noqa: E402

SRC = "github.com/acme/src"
DST = "github.com/acme/dst"
# (page path, encoded node id path)
ODD: list[tuple[str, str]] = [
    ("notes/a#b.md", "notes/a%23b.md"),
    ("notes/a?b.md", "notes/a%3Fb.md"),
    ("notes/100%.md", "notes/100%25.md"),
    ("notes/with space.md", "notes/with%20space.md"),
    ("notes/café-ñandú.md", "notes/café-ñandú.md"),
]
PLAIN = ["notes/plain.md", "notes/a-b_c.d(1).md"]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def contract(root: Path) -> None:
    write(root / "CONTRACT.json", json.dumps({"schema_version": "1.0", "atlas_id": "fixture", "title": "t"}) + "\n")


def page(root: Path, rel: str, links: list[str] | None = None) -> None:
    lines = ["---", "type: lesson", "title: t", "status: active"]
    if links:
        lines.append("relates_to:")
        lines += [f"  - path: {json.dumps(r, ensure_ascii=False)}\n    kind: related" for r in links]
    lines += ["---", "", "body.", ""]
    write(root / rel, "\n".join(lines))


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    # 1. Pure round-trip.
    for rel, enc in ODD:
        nid = mesh_scope.node_id(DST, rel)
        check(f"node-id-encoded {rel}", nid == f"atlas://{DST}/{enc}", nid)
        try:
            back = mesh_scope.parse_node_id(nid)
        except mesh_scope.MeshScopeError as e:
            back = (repr(e), "")
        check(f"round-trip {rel}", back == (DST, rel), str(back))
    for rel in PLAIN:
        check(f"plain-unchanged {rel}", mesh_scope.node_id(DST, rel) == f"atlas://{DST}/{rel}")
    for raw in ("a\tb.md", "a\nb.md", "a\x7fb.md", "a\u00a0b.md", "a\u2028b.md"):
        nid = mesh_scope.node_id(DST, raw)
        check(f"control-encoded {raw!r}", raw not in nid and mesh_scope.parse_node_id(nid) == (DST, raw), nid)
    check(
        "unencoded-hash-is-fragment",
        mesh_scope.parse_node_id(f"atlas://{DST}/notes/a#b.md") == (DST, "notes/a"),
    )
    enc, dec = getattr(mesh_scope, "encode_path", None), getattr(mesh_scope, "decode_path", None)
    check("encode-decode-pair", bool(enc and dec) and dec(enc("x/%2F#?.md")) == "x/%2F#?.md")

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-r3-"))
    try:
        project = tmp / "proj"
        src = project / "atlas" / "src"
        dst = project / "atlas" / "dst"
        contract(src)
        contract(dst)
        for rel, _ in ODD:
            page(dst, rel)
        page(dst, "notes/plain.md")
        links = [f"atlas://{DST}/{enc}" for _, enc in ODD] + [
            f"atlas://{DST}/notes/a#b.md",
            f"atlas://{DST}/notes/with%20space.md#sec",
        ]
        page(src, "x.md", links)
        write(
            project / "atlas-mesh.json",
            json.dumps({"version": 1, "stores": [{"id": SRC, "path": "atlas/src"}, {"id": DST, "path": "atlas/dst"}]})
            + "\n",
        )
        index_location.clear_cache()
        view = mesh_scope.build_view(mesh_scope.discover(project))

        # 2. Unique ids that parse back to their own path.
        ids = [n["id"] for n in view["nodes"]]
        check("ids-unique", len(ids) == len(set(ids)), json.dumps(ids))
        paths = {n["path"]: n["id"] for n in view["nodes"] if n["atlas_id"] == DST}
        for rel, enc in ODD:
            nid = paths.get(rel)
            check(f"view-node {rel}", nid == f"atlas://{DST}/{enc}", str(nid))
        for n in view["nodes"]:
            got = mesh_scope.parse_node_id(n["id"])
            check(f"view-parse {n['path']}", got == (n["atlas_id"], n["path"]), str(got))

        # 3. Encoded links resolve; an unencoded # is a fragment.
        edges = {e["to"]: e for e in view["edges"] if e["from"] == f"atlas://{SRC}/x.md"}
        for rel, enc in ODD:
            rec = edges.get(f"atlas://{DST}/{enc}") or {}
            check(
                f"encoded-link-resolves {rel}",
                rec.get("resolved") is True and rec.get("resolution") == "atlas_uri" and rec.get("cross") is True,
                str(rec),
            )
        rec = edges.get(f"atlas://{DST}/notes/a") or {}
        check("unencoded-hash-missing", rec.get("reason") == "missing_page" and rec.get("resolved") is False, str(rec))
        check("fragment-nowhere", not any("#" in to for to in edges), json.dumps(sorted(edges)))
        check("edge-count", len(edges) == len(ODD) + 1, json.dumps(sorted(edges)))

        # 4. Compile's check reads the same store from the encoded and unencoded forms.
        for link in links:
            check(f"compile-same-store {link}", parse_pointer(link).atlas_id == DST)
    finally:
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} mesh review R3 check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll mesh review R3 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
