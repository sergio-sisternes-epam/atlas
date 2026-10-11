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

A contained root that the containing row's own walks never reach (its
relative path starts in a directory every walk skips, such as ``.atlas/`` or
``templates/``) does not make the containing row overlap: a store at the
project root beside stores mounted under ``.atlas/<host>/<org>/<repo>/``
stays ``ok`` and still never reads the excluded store.
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
from atlas_cli.core import index_location, mesh_scope, paths  # noqa: E402
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


ROOT_ID = "github.com/acme/project"
EXCL = "github.com/acme/excl"
INCL = "github.com/acme/incl"
TPL = "github.com/acme/tpl"


def build_root_layout(tmp: Path) -> tuple[Path, Path]:
    """Root store at ``.``; excluded and included stores at their default ``.atlas/<id>/`` mounts."""
    project = tmp / "proj"
    schema(project)
    write(project / "notes" / "root.md", page("Graph export root", "Graph export in root", "Graph export root body."))
    excl = project / ".atlas" / "github.com" / "acme" / "excl"
    schema(excl)
    write(excl / "notes" / "hidden.md", page(f"Graph export {CANARY}", f"Graph export {CANARY}", f"Graph export {CANARY} body."))
    incl = project / ".atlas" / "github.com" / "acme" / "incl"
    schema(incl)
    write(incl / "notes" / "incl.md", page("Graph export incl", "Graph export in incl", "Graph export incl body."))
    stores = [{"id": ROOT_ID, "path": "."}, {"id": EXCL, "mesh_member": False}, {"id": INCL}]
    write(project / "atlas-mesh.json", json.dumps({"version": 1, "stores": stores}, indent=2) + "\n")
    return project, excl


def build_templates_layout(tmp: Path) -> tuple[Path, Path]:
    """top at ``atlas/``; an excluded store at ``atlas/templates/x/``, which no walk of top reaches."""
    project = tmp / "proj"
    top = project / "atlas"
    schema(top)
    write(top / "notes" / "top.md", page("Graph export top", "Graph export in top", "Graph export top body."))
    nested = top / "templates" / "x"
    schema(nested)
    write(nested / "notes" / "hidden.md", page(f"Graph export {CANARY}", f"Graph export {CANARY}", f"Graph export {CANARY} body."))
    stores = [{"id": TOP, "path": "atlas"}, {"id": TPL, "path": "atlas/templates/x", "mesh_member": False}]
    write(project / "atlas-mesh.json", json.dumps({"version": 1, "stores": stores}, indent=2) + "\n")
    return project, nested


def statuses_of(project: Path) -> list[tuple[str, str, str | None]]:
    return [(m.atlas_id, m.status, m.reason) for m in mesh_scope.members(mesh_scope.discover(project))]


def lexical_statuses(tmp: Path, stores: list[dict]) -> list[tuple[str, str, str | None]]:
    """Statuses for a mesh file alone (no store directories exist)."""
    project = tmp / "proj"
    write(project / "atlas-mesh.json", json.dumps({"version": 1, "stores": stores}, indent=2) + "\n")
    return statuses_of(project)


def view_under_guard(project: Path, guard_root: Path) -> tuple[dict, list[str]]:
    index_location.clear_cache()
    view: dict = {}
    with Guard(guard_root) as guard:
        try:
            view = mesh_scope.build_view(mesh_scope.discover(project))
        except Exception as e:  # noqa: BLE001 - reported as a failed check
            view = {"_error": repr(e)}
    index_location.clear_cache()
    return view, guard.hits


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

        # (a) A root store at ``.`` beside stores under ``.atlas/<host>/<org>/<repo>/`` is ``ok``.
        project, excl = build_root_layout(tmp / "root-layout")
        statuses = statuses_of(project)
        check(
            "root-layout-members",
            statuses == [(ROOT_ID, "ok", None), (EXCL, "excluded", None), (INCL, "ok", None)],
            str(statuses),
        )
        for engine in ("grep", "bm25"):
            name = f"root-layout-{engine}"
            code, payload, touched, err = run_mesh(project, engine, excl)
            members = {m["atlas_id"]: m for m in payload.get("members", [])}
            hits = payload.get("hits", [])
            uris = sorted(h.get("uri", "") for h in hits)
            text = json.dumps(payload)
            check(f"{name}-exit-0", code == 0, f"{code} {err[:300]} {text[:300]}")
            check(f"{name}-file-access-never-made", touched == [], str(touched[:5]))
            check(f"{name}-root-ok", members.get(ROOT_ID, {}).get("status") == "ok", str(members.get(ROOT_ID)))
            check(
                f"{name}-hits-root-and-included",
                uris == [f"atlas://{INCL}/notes/incl.md", f"atlas://{ROOT_ID}/notes/root.md"],
                str(uris),
            )
            check(f"{name}-count", payload.get("count") == 2, str(payload.get("count")))
            check(f"{name}-no-canary-in-output", CANARY not in text and CANARY not in err, text[:400])
            check(f"{name}-no-excluded-path", not any("excl" in u for u in uris), str(uris))
            check(
                f"{name}-no-title-from-excluded",
                all(CANARY not in str(h.get("title", "")) for h in hits),
                str([h.get("title") for h in hits]),
            )
            check(f"{name}-excluded-member", members.get(EXCL, {}).get("status") == "excluded", str(members.get(EXCL)))
        view, touched = view_under_guard(project, excl)
        node_ids = sorted(n["id"] for n in view.get("nodes", []))
        check("root-layout-view-built", "_error" not in view, str(view.get("_error")))
        check("root-layout-view-file-access-never-made", touched == [], str(touched[:5]))
        check(
            "root-layout-view-nodes",
            node_ids == [f"atlas://{INCL}/notes/incl.md", f"atlas://{ROOT_ID}/notes/root.md"],
            str(node_ids),
        )
        check("root-layout-view-no-canary", CANARY not in json.dumps(view), json.dumps(view)[:400])
        view_root = next((m for m in view.get("members", []) if m["atlas_id"] == ROOT_ID), {})
        check("root-layout-view-root-ok", view_root.get("status") == "ok", str(view_root))

        # (c) A store under ``<ancestor>/templates/x/`` is not reached by the ancestor's walks.
        project, nested = build_templates_layout(tmp / "templates-layout")
        statuses = statuses_of(project)
        check("templates-members", statuses == [(TOP, "ok", None), (TPL, "excluded", None)], str(statuses))
        for engine in ("grep", "bm25"):
            name = f"templates-{engine}"
            code, payload, touched, err = run_mesh(project, engine, nested)
            uris = [h.get("uri", "") for h in payload.get("hits", [])]
            text = json.dumps(payload)
            check(f"{name}-exit-0", code == 0, f"{code} {err[:300]} {text[:300]}")
            check(f"{name}-file-access-never-made", touched == [], str(touched[:5]))
            check(f"{name}-only-top-hit", uris == [f"atlas://{TOP}/notes/top.md"], str(uris))
            check(f"{name}-no-canary-in-output", CANARY not in text and CANARY not in err, text[:400])
        tops = [p.name for p in paths.walk_tops(project / "atlas")]
        check("templates-rg-targets-skip-templates", "templates" not in tops and "notes" in tops, str(tops))
        index_location.clear_cache()
        buf = io.StringIO()
        with Guard(nested) as guard, contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = search_cmd.run_scoped(str(project), CANARY, 10, True, "grep", False, None, False, "mesh", None)
        index_location.clear_cache()
        check("templates-grep-single-token-no-canary-hit", code == 0 and json.loads(buf.getvalue()).get("count") == 0, buf.getvalue()[:300])
        check("templates-grep-single-token-file-access-never-made", guard.hits == [], str(guard.hits[:5]))
        view, touched = view_under_guard(project, nested)
        node_ids = [n["id"] for n in view.get("nodes", [])]
        check("templates-view-file-access-never-made", touched == [], str(touched[:5]))
        check("templates-view-nodes", node_ids == [f"atlas://{TOP}/notes/top.md"], str(node_ids))

        # Walks still reach these contained roots, so the containing row overlaps.
        reached = {
            "deeper-templates": "atlas/notes/templates/x",
            "staging": "atlas/staging/x",
            "dot-atlas-sibling": "atlas/.atlasx/x",
        }
        for label, path in reached.items():
            statuses = lexical_statuses(
                tmp / f"lexical-{label}",
                [{"id": TOP, "path": "atlas"}, {"id": TPL, "path": path, "mesh_member": False}],
            )
            check(f"lexical-{label}-overlapping", statuses[0] == (TOP, "invalid", "overlapping_root"), str(statuses))
        # Index locations the root store reads directly are never inside an unreached root.
        for label, path in {
            "project-indexes": ".atlas/indexes/fts5/github.com/acme/x",
            "legacy-index": ".atlas-index/recall",
            "dot-atlas-itself": ".atlas",
        }.items():
            statuses = lexical_statuses(
                tmp / f"lexical-{label}",
                [{"id": ROOT_ID, "path": "."}, {"id": TPL, "path": path, "mesh_member": False}],
            )
            check(f"lexical-{label}-overlapping", statuses[0] == (ROOT_ID, "invalid", "overlapping_root"), str(statuses))
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
