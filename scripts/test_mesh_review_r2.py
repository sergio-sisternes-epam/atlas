#!/usr/bin/env python3
"""Review R2: mesh rows are contained to the project, and canonical
``atlas://`` targets drop their fragment on every branch.

1. A row whose ``path`` or ``subpath`` is absolute, has a ``..`` segment or
   crosses a symlink that resolves outside the project is ``invalid`` with
   reason ``outside_project``. Nothing under the outside target is stat-ed,
   opened or projected, and links into it are unresolved ``outside_mesh``.
2. ``atlas://<id>/<path>#h`` reports ``to`` without ``#h`` whether the id is
   unknown, unmounted, excluded, invalid or a member with a missing page.

Linux-safe: no network, no git.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, mesh_scope  # noqa: E402
from test_mesh_members import Guard  # noqa: E402

CANARY = "WOMBATCHUTNEY"
SRC = "github.com/acme/src"
ABS = "github.com/acme/abs"
DOTDOT = "github.com/acme/dotdot"
SUB = "github.com/acme/sub"
LINK = "github.com/acme/link"
LINKMID = "github.com/acme/linkmid"
INLINK = "github.com/acme/inlink"
GONE = "github.com/acme/gone"
SECRET = "github.com/acme/secret"
UNKNOWN = "github.com/nobody/else"
ESCAPING = (ABS, DOTDOT, SUB, LINK, LINKMID)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def store(root: Path, rels: list[str] | None = None) -> None:
    write(root / "CONTRACT.json", json.dumps({"schema_version": "1.0", "atlas_id": "fixture", "title": CANARY}) + "\n")
    lines = ["---", "type: lesson", f"title: {CANARY}", "status: active"]
    if rels:
        lines.append("relates_to:")
        lines += [f"  - path: {json.dumps(r)}\n    kind: related" for r in rels]
    lines += ["---", "", f"{CANARY} body.", ""]
    write(root / "x.md", "\n".join(lines))


class RealGuard(Guard):
    """:class:`Guard` that also fails a call whose real path (through symlinks) is strictly inside ``root``."""

    busy = False  # shared, so nested guards never recurse through each other's realpath

    def __init__(self, root: Path, allow: str | None = None) -> None:
        super().__init__(root)
        self.allow = allow

    def _inside(self, path: object) -> bool:
        if self.allow is not None and not isinstance(path, int) and os.fsdecode(os.fspath(path)) == self.allow:
            return False
        if super()._inside(path):
            return True
        if RealGuard.busy or isinstance(path, int):
            return False
        RealGuard.busy = True
        try:
            real = os.path.realpath(os.fsdecode(os.fspath(path)))
        except (TypeError, OSError, ValueError):
            return False
        finally:
            RealGuard.busy = False
        return real.startswith(self.root + os.sep)


# Fragment cases on a clean mesh: (target, reason or None, to).
FRAGMENTS: list[tuple[str, str | None, str]] = [
    (f"atlas://{GONE}/x.md#h", "unmounted", f"atlas://{GONE}/x.md"),
    (f"atlas://{UNKNOWN}/x.md#h", "unmounted", f"atlas://{UNKNOWN}/x.md"),
    (f"atlas://{SECRET}/x.md#h", "excluded_member", f"atlas://{SECRET}/x.md"),
    (f"atlas://{SRC}/missing.md#h", "missing_page", f"atlas://{SRC}/missing.md"),
    (f"atlas://{SRC}/x.md#h", None, f"atlas://{SRC}/x.md"),
    (f"atlas://{SRC}#h", "missing_page", f"atlas://{SRC}"),
    (f"atlas://{SRC}/../x.md#h", "outside_mesh", f"atlas://{SRC}/../x.md"),
]


def build_fixture(tmp: Path) -> tuple[Path, dict[str, Path], dict[str, dict]]:
    project = tmp / "proj"
    outside = tmp / "outside"
    targets = {sid: outside / sid.rsplit("/", 1)[-1] for sid in ESCAPING}
    for sid in (ABS, DOTDOT, SUB, LINK):
        store(targets[sid])
    store(targets[LINKMID] / "docs")
    links = [t for t, _, _ in FRAGMENTS] + [f"atlas://{sid}/x.md#h" for sid in (*ESCAPING, INLINK)] + ["../link/x.md"]
    store(project / "atlas" / "src", links)
    store(project / "atlas" / "secret")
    store(project / "real" / "inside")
    (project / "atlas" / "mono").mkdir(parents=True)
    os.symlink(targets[LINK], project / "atlas" / "link")
    os.symlink(targets[LINKMID], project / "atlas" / "linkmid")
    os.symlink(project / "real" / "inside", project / "atlas" / "inlink")
    rows = {
        SRC: {"id": SRC, "path": "atlas/src"},
        ABS: {"id": ABS, "path": str(targets[ABS])},
        DOTDOT: {"id": DOTDOT, "path": "../outside/dotdot"},
        SUB: {"id": SUB, "path": "atlas/mono", "subpath": "../../../outside/sub"},
        LINK: {"id": LINK, "path": "atlas/link"},
        LINKMID: {"id": LINKMID, "path": "atlas/linkmid/docs"},
        INLINK: {"id": INLINK, "path": "atlas/inlink"},
        GONE: {"id": GONE, "path": "atlas/gone"},
        SECRET: {"id": SECRET, "path": "atlas/secret", "mesh_member": False},
    }
    return project, targets, rows


def use_mesh(project: Path, rows: list[dict]) -> mesh_scope.Mesh:
    write(project / "atlas-mesh.json", json.dumps({"version": 1, "stores": rows}, indent=2) + "\n")
    index_location.clear_cache()
    return mesh_scope.discover(project)


def guarded(targets: dict[str, Path], fn, allow: dict[str, str] | None = None) -> tuple[object, list[str], str]:
    with contextlib.ExitStack() as stack:
        guards = [stack.enter_context(RealGuard(t, (allow or {}).get(sid))) for sid, t in targets.items()]
        try:
            result, error = fn(), ""
        except Exception as e:  # noqa: BLE001
            result, error = None, repr(e)
    return result, [hit for g in guards for hit in g.hits], error


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-r2-"))
    try:
        project, targets, rows = build_fixture(tmp)
        src_node = f"atlas://{SRC}/x.md"

        with RealGuard(targets[LINK]) as probe:
            try:
                (project / "atlas" / "link" / "CONTRACT.json").read_text()
            except PermissionError:
                pass
        check("guard-bites-through-symlink", bool(probe.hits))

        # 2. Fragments: every canonical target drops #h, whatever the branch.
        mesh = use_mesh(project, [rows[SRC], rows[GONE], rows[SECRET]])
        view = mesh_scope.build_view(mesh)
        edges = {e["to"]: e for e in view["edges"] if e["from"] == src_node}
        for target, reason, to in FRAGMENTS:
            rec = edges.get(to)
            ok = rec is not None and rec.get("reason") == reason and rec.get("resolved") is (reason is None)
            check(f"fragment-dropped {target}", ok, f"{to}: {rec}")
        check("fragment-nowhere", not any("#" in e["to"] for e in view["edges"]), json.dumps(sorted(edges)))

        # 1. Containment, one escaping row at a time; then all together.
        for sid in ESCAPING:
            mesh = use_mesh(project, [rows[SRC], rows[sid]])
            got, hits, error = guarded(targets, lambda: mesh_scope.members(mesh))
            check(f"members-untouched {sid}", not hits and not error, f"{hits[:3]} {error}")
            status = {m.atlas_id: (m.status, m.reason) for m in got or []}
            check(f"member-invalid {sid}", status.get(sid) == ("invalid", "outside_project"), str(status.get(sid)))
            # Index location (index_location.mesh_match, outside mesh scope) realpath-resolves each
            # row path while locating the valid member's index; for the mid-path link that lstats
            # the literal row path only. Nothing under it is stat-ed, opened or projected.
            allow = {LINKMID: str(targets[LINKMID] / "docs")}
            view, hits, error = guarded(targets, lambda: mesh_scope.build_view(mesh), allow)
            check(f"view-untouched {sid}", not hits and not error, f"{hits[:3]} {error}")
            view = view or {}
            row = next((m for m in view.get("members", []) if m["atlas_id"] == sid), {})
            check(f"view-member-reason {sid}", row.get("status") == "invalid" and row.get("reason") == "outside_project", str(row))
            check(f"no-outside-nodes {sid}", [n["id"] for n in view.get("nodes", [])] == [src_node])
            link = next((e for e in view.get("edges", []) if e["to"] == f"atlas://{sid}/x.md"), {})
            check(f"link-outside-mesh {sid}", link.get("reason") == "outside_mesh" and link.get("resolved") is False, str(link))
        mesh = use_mesh(project, [rows[SRC], rows[LINK]])
        rel = next((e for e in mesh_scope.build_view(mesh)["edges"] if e["to"] == "../link/x.md"), {})
        check("mesh-path-into-invalid-outside-mesh", rel.get("reason") == "outside_mesh", str(rel))

        mesh = use_mesh(project, list(rows.values()))
        allow = {LINKMID: str(targets[LINKMID] / "docs")}
        view, hits, error = guarded(targets, lambda: mesh_scope.build_view(mesh), allow)
        check("all-rows-untouched", not hits and not error, f"{hits[:3]} {error}")
        statuses = {m["atlas_id"]: (m["status"], m.get("reason")) for m in (view or {}).get("members", [])}
        check(
            "all-rows-statuses",
            all(statuses.get(sid) == ("invalid", "outside_project") for sid in ESCAPING)
            and statuses.get(INLINK) == ("ok", None)
            and statuses.get(SRC) == ("ok", None)
            and statuses.get(GONE) == ("unmounted", None)
            and statuses.get(SECRET) == ("excluded", None),
            json.dumps(statuses),
        )
        check("inside-symlink-resolves", any(e["to"] == f"atlas://{INLINK}/x.md" and e["resolved"] for e in (view or {}).get("edges", [])))
        check("canary-absent", CANARY not in json.dumps(view))
        index_location.clear_cache()
        check("discover-inside-store", mesh_scope.discover(project / "atlas" / "src").project == project.resolve())
    finally:
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} mesh review R2 check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll mesh review R2 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
