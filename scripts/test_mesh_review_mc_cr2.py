#!/usr/bin/env python3
"""Copilot review CR2 for federated recall (MC): overlapping member roots are ``invalid``.

A row whose root equals or contains another row's root is ``invalid`` with
reason ``overlapping_root`` and is never read, decided lexically before any
file access; the contained row keeps its own status. Otherwise an included
store at ``atlas/`` would read (and return) the pages of a
``mesh_member: false`` store at ``atlas/secret/``.

Covers grep and bm25 federated recall (in process, file access under the
nested excluded store patched), the variant where the nested row is
included, :func:`mesh_scope.build_view` and links into the overlapping
member (``outside_mesh``). Linux-safe: no network, no git.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.commands import search as search_cmd  # noqa: E402
from atlas_cli.core import index_location, mesh_scope  # noqa: E402
from test_mesh_members import Guard  # noqa: E402
from test_mesh_recall import page, schema, write  # noqa: E402

TOP = "github.com/acme/top"
NESTED = "github.com/acme/nested"
SIDE = "github.com/acme/side"
QUERY = "graph export"
CANARY = "nestedcanaryqx"


def build(tmp: Path, *, nested_member: bool) -> tuple[Path, Path]:
    """top at ``atlas/``, nested at ``atlas/secret/`` (excluded unless ``nested_member``), side at ``side/``."""
    project = tmp / "proj"
    top = project / "atlas"
    nested = top / "secret"
    side = project / "side"
    schema(top)
    write(top / "notes" / "top.md", page("Graph export top", "Graph export in top", "Graph export top body."))
    schema(nested)
    write(
        nested / "notes" / "hidden.md",
        page(f"Graph export {CANARY}", f"Graph export {CANARY}", f"Graph export {CANARY} body."),
    )
    schema(side)
    write(
        side / "notes" / "side.md",
        page(
            "Graph export side",
            "Graph export in side",
            "Graph export side body.",
            extra=(
                "relates_to:\n"
                f"  - path: atlas://{TOP}/notes/top.md\n    kind: related\n"
                "  - path: ../atlas/notes/top.md\n    kind: related\n"
            ),
        ),
    )
    stores = [
        {"id": TOP, "path": "atlas"},
        {"id": NESTED, "path": "atlas/secret", "mesh_member": nested_member},
        {"id": SIDE, "path": "side"},
    ]
    write(project / "atlas-mesh.json", json.dumps({"version": 1, "stores": stores}, indent=2) + "\n")
    return project, nested


def run_mesh(project: Path, engine: str, guard_root: Path | None) -> tuple[int, dict, list[str], str]:
    index_location.clear_cache()
    buf, ebuf = io.StringIO(), io.StringIO()
    guard = Guard(guard_root) if guard_root is not None else contextlib.nullcontext()
    with guard, contextlib.redirect_stdout(buf), contextlib.redirect_stderr(ebuf):
        code = search_cmd.run_scoped(str(project), QUERY, 10, True, engine, False, None, False, "mesh", None)
    index_location.clear_cache()
    hits = guard.hits if isinstance(guard, Guard) else []
    try:
        payload = json.loads(buf.getvalue())
    except ValueError:
        payload = {"_raw": buf.getvalue()}
    return code, payload, hits, ebuf.getvalue()


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr2-"))
    try:
        for nested_member in (False, True):
            label = "included" if nested_member else "excluded"
            project, nested = build(tmp / label, nested_member=nested_member)

            statuses = [(m.atlas_id, m.status, m.reason) for m in mesh_scope.members(mesh_scope.discover(project))]
            nested_status = ("ok", None) if nested_member else ("excluded", None)
            check(
                f"{label}-members",
                statuses == [(TOP, "invalid", "overlapping_root"), (NESTED, *nested_status), (SIDE, "ok", None)],
                str(statuses),
            )

            for engine in ("grep", "bm25"):
                name = f"{label}-{engine}"
                code, payload, touched, err = run_mesh(project, engine, None if nested_member else nested)
                members = {m["atlas_id"]: m for m in payload.get("members", [])}
                hits = payload.get("hits", [])
                uris = [h.get("uri", "") for h in hits]
                text = json.dumps(payload)
                check(f"{name}-exit-0", code == 0, f"{code} {err[:300]} {text[:300]}")
                check(f"{name}-file-access-never-made", touched == [], str(touched[:5]))
                top = members.get(TOP, {})
                check(
                    f"{name}-ancestor-invalid-overlapping",
                    top.get("status") == "invalid" and top.get("reason") == "overlapping_root" and top.get("hits") == 0,
                    str(top),
                )
                check(f"{name}-no-hit-from-ancestor", not any(u.startswith(f"atlas://{TOP}/") for u in uris), str(uris))
                check(f"{name}-side-hit", f"atlas://{SIDE}/notes/side.md" in uris, str(uris))
                if nested_member:
                    canary_uris = [h["uri"] for h in hits if CANARY in json.dumps(h)]
                    check(
                        f"{name}-nested-hit-only-from-own-store",
                        canary_uris == [f"atlas://{NESTED}/notes/hidden.md"],
                        str(canary_uris),
                    )
                    check(f"{name}-count", payload.get("count") == 2, str(payload.get("count")))
                else:
                    check(f"{name}-no-canary-in-output", CANARY not in text and CANARY not in err, text[:400])
                    check(f"{name}-no-secret-path", not any("secret" in u for u in uris), str(uris))
                    check(f"{name}-count", payload.get("count") == 1, str(payload.get("count")))
                    check(f"{name}-nested-excluded", members.get(NESTED, {}).get("status") == "excluded", str(members))

            index_location.clear_cache()
            guard_root = None if nested_member else nested
            guard = Guard(guard_root) if guard_root is not None else contextlib.nullcontext()
            view: dict = {}
            with guard:
                try:
                    view = mesh_scope.build_view(mesh_scope.discover(project))
                except Exception as e:  # noqa: BLE001 - reported as a failed check
                    view = {"_error": repr(e)}
            index_location.clear_cache()
            touched = guard.hits if isinstance(guard, Guard) else []
            check(f"{label}-view-built", "_error" not in view, str(view.get("_error")))
            check(f"{label}-view-file-access-never-made", touched == [], str(touched[:5]))
            node_ids = [n["id"] for n in view.get("nodes", [])]
            check(f"{label}-view-no-ancestor-node", not any(i.startswith(f"atlas://{TOP}/") for i in node_ids), str(node_ids))
            if nested_member:
                check(f"{label}-view-nested-node", f"atlas://{NESTED}/notes/hidden.md" in node_ids, str(node_ids))
            else:
                check(
                    f"{label}-view-no-nested-node",
                    not any(i.startswith(f"atlas://{NESTED}/") or "secret" in i for i in node_ids),
                    str(node_ids),
                )
            view_top = next((m for m in view.get("members", []) if m["atlas_id"] == TOP), {})
            check(
                f"{label}-view-ancestor-invalid",
                view_top.get("status") == "invalid" and view_top.get("reason") == "overlapping_root",
                str(view_top),
            )
            side_edges = [e for e in view.get("edges", []) if e["from"] == f"atlas://{SIDE}/notes/side.md"]
            check(
                f"{label}-links-into-overlapping-are-outside-mesh",
                len(side_edges) == 2 and all(e.get("reason") == "outside_mesh" and not e["resolved"] for e in side_edges),
                str(side_edges),
            )
    finally:
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"FAILED: {len(failed)} check(s): {', '.join(failed)}")
        return 1
    print("OK: mesh review MC CR2 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
