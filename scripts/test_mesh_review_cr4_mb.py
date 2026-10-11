#!/usr/bin/env python3
"""Copilot review CR4 for packet MB (native mesh graph).

``mesh_digest`` must cover every serialised member record the snapshot writes,
not only ids of excluded, unmounted and invalid rows. Changing an excluded
row's path, an unmounted row's subpath, or an invalid row's reason-causing
field (still the same status, a different reason) must make the next read
stale: a new digest and generation, and snapshot/export members that show the
new metadata. An unchanged mesh still reuses the snapshot. No read under any
non-ok root (row metadata comes from ``atlas-mesh.json`` only).

In-process against a temporary mesh. Linux-safe: no network, no git.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, mesh_graph, mesh_scope  # noqa: E402
from test_mesh_graph import EXT, GONE, SECRET, build_mesh, contract, write  # noqa: E402

FAILURES: list[str] = []
CANARY = "CR4MBCANARY"
INVALID_ID = "/acme/ext"
RELOCATED = "atlas/secret-relocated"
NESTED = "nested"
_STAT = frozenset({"stat", "lstat", "access"})
_CONTRACTS = frozenset({"SCHEMA.json", "CONTRACT.json"})


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if not ok and detail != "" else ""))
    if not ok:
        FAILURES.append(name)


def discover(project: Path) -> mesh_scope.Mesh:
    index_location.clear_cache()
    return mesh_scope.discover(project)


def edit_row(project: Path, atlas_id: str, **fields: object) -> None:
    path = project / "atlas-mesh.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    for row in doc["stores"]:
        if row.get("id") == atlas_id:
            row.update(fields)
            break
    else:
        raise AssertionError(f"no row {atlas_id}")
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def live_records(project: Path) -> list[dict]:
    """The records a snapshot should persist, without calling a digest helper."""
    return [member.as_dict() for member in mesh_scope.members(discover(project))]


def published_members(project: Path) -> list[dict]:
    root = mesh_graph.index_dir(project)
    pointer = mesh_graph.read_pointer(root) or {}
    graph = root / str(pointer.get("graph") or "")
    doc = json.loads(graph.read_text(encoding="utf-8"))
    return list(doc.get("members") or [])


class AccessGuard:
    """Record and refuse filesystem calls under non-ok roots.

    An unmounted root may be stat-ed (and its contract filenames stat-ed) so
    status can stay ``unmounted``. Nothing is opened or listed, and an
    excluded or invalid root is not touched at all.
    """

    def __init__(self, unread: list[Path], classify: list[Path]) -> None:
        self.unread = [self._forms(path) for path in unread]
        self.classify = [self._forms(path) for path in classify]
        self.hits: list[str] = []
        self.saved: list[tuple[object, str, object]] = []

    @staticmethod
    def _forms(path: Path) -> frozenset[str]:
        text = os.path.normpath(os.path.abspath(path))
        forms = {text}
        try:
            forms.add(os.path.realpath(text))
        except OSError:
            pass
        return frozenset(forms)

    def _kind(self, path: object) -> str | None:
        if isinstance(path, int):
            return None
        try:
            text = os.fsdecode(os.fspath(path))
        except (TypeError, ValueError):
            return None
        absolute = os.path.normpath(os.path.abspath(text))
        if any(absolute == root or absolute.startswith(root + os.sep) for forms in self.unread for root in forms):
            return "unread"
        if any(absolute == root or absolute.startswith(root + os.sep) for forms in self.classify for root in forms):
            return "classify"
        return None

    def _allowed(self, name: str, path: object) -> bool:
        if name not in _STAT:
            return False
        try:
            text = os.path.normpath(os.path.abspath(os.fsdecode(os.fspath(path))))
        except (TypeError, ValueError):
            return False
        if any(text == root for forms in self.classify for root in forms):
            return True
        if os.path.basename(text) not in _CONTRACTS:
            return False
        parent = os.path.dirname(text)
        return any(parent == root for forms in self.classify for root in forms)

    def _wrap(self, owner: object, name: str) -> None:
        original = getattr(owner, name)
        guard = self

        def wrapped(*args: object, **kwargs: object) -> object:
            target = args[0] if args else kwargs.get("path")
            kind = guard._kind(target)
            if kind == "unread" or (kind == "classify" and not guard._allowed(name, target)):
                guard.hits.append(f"{name}({target})")
                raise PermissionError(f"non-ok root touched: {name} {target}")
            return original(*args, **kwargs)

        self.saved.append((owner, name, original))
        setattr(owner, name, wrapped)

    def __enter__(self) -> "AccessGuard":
        for name in ("stat", "lstat", "open", "listdir", "scandir", "readlink", "access", "walk"):
            self._wrap(os, name)
        self._wrap(builtins, "open")
        self._wrap(io, "open")
        return self

    def __exit__(self, *exc: object) -> None:
        for owner, name, original in reversed(self.saved):
            setattr(owner, name, original)


def row_of(members: list[dict], atlas_id: str) -> dict:
    return next((row for row in members if row.get("atlas_id") == atlas_id), {})


def run_reuse(project: Path, previous: mesh_graph.MeshGraph, unread: list[Path], classify: list[Path], label: str) -> None:
    with AccessGuard(unread, classify) as guard:
        try:
            again = mesh_graph.ensure(discover(project))
            error = ""
        except Exception as exc:  # noqa: BLE001 - the guard must surface as a failed check
            again, error = None, repr(exc)
    check(f"{label}-reuse-unread", not guard.hits and not error, (guard.hits[:3], error))
    if again is None:
        check(f"{label}-reuse", False, error)
        return
    check(
        f"{label}-reuse",
        again.generation == previous.generation and again.mesh_digest == previous.mesh_digest and not again.rebuilt,
        (previous.generation, again.generation, again.rebuilt),
    )


def run_change(
    project: Path,
    *,
    label: str,
    previous: mesh_graph.MeshGraph,
    unread: list[Path],
    classify: list[Path],
    atlas_id: str,
    expect: dict[str, object],
) -> mesh_graph.MeshGraph | None:
    print(label)
    out = project.parent / f"export-{label}"
    with AccessGuard(unread, classify) as guard:
        try:
            fresh = mesh_graph.status(discover(project)).get("fresh")
            status_error = ""
        except Exception as exc:  # noqa: BLE001
            fresh, status_error = None, repr(exc)
        try:
            result = mesh_graph.ensure(discover(project))
            mesh_graph.export_json(result, out)
            exported = json.loads((out / "graph.json").read_text(encoding="utf-8")).get("members")
            error = ""
        except Exception as exc:  # noqa: BLE001
            result, exported, error = None, None, repr(exc)
    check(f"{label}-unread", not guard.hits and not error and not status_error, (guard.hits[:3], error, status_error))
    check(f"{label}-read-stale", fresh is False, fresh)
    if result is None or exported is None:
        check(f"{label}-rebuilt", False, error)
        return None
    check(
        f"{label}-new-generation",
        bool(result.generation) and result.generation != previous.generation and result.rebuilt and not result.in_memory,
        (previous.generation, result.generation, result.rebuilt, result.in_memory),
    )
    check(f"{label}-new-digest", result.mesh_digest != previous.mesh_digest)
    live = live_records(project)
    on_disk = published_members(project)
    check(f"{label}-snapshot-members", result.doc.get("members") == live == on_disk, result.doc.get("members"))
    check(f"{label}-export-members", exported == live, exported)
    check(f"{label}-no-canary", CANARY not in json.dumps(result.doc) and CANARY not in json.dumps(exported))
    got = row_of(live, atlas_id)
    ok = all(got.get(key) == value for key, value in expect.items())
    if expect.get("reason") is None:
        ok = ok and "reason" not in got
    check(f"{label}-metadata", ok, got)
    run_reuse(project, result, unread, classify, label)
    return result


def run(tmp: Path) -> None:
    project = build_mesh(tmp / "mesh")
    ext = tmp / "ext"
    contract(ext, EXT, "Ext")
    write(ext / "notes" / "e.md", f"---\ntype: lesson\ntitle: Ext\n---\n\n{CANARY}\n")
    write(project / "atlas" / "gone" / "notes" / "g.md", f"{CANARY} gone\n")
    path = project / "atlas-mesh.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["stores"].append({"id": EXT, "path": "../ext"})
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    secret = project / "atlas" / "secret"
    gone = project / "atlas" / "gone"
    unread = [secret, ext]
    classify = [gone]

    with AccessGuard([secret], []) as probe:
        try:
            (secret / "CONTRACT.json").read_text(encoding="utf-8")
        except PermissionError:
            pass
    check("guard-bites", bool(probe.hits), probe.hits)

    print("unchanged mesh reuses the snapshot")
    first = mesh_graph.ensure(discover(project))
    check("built", bool(first.generation) and first.rebuilt and not first.in_memory, first.generation)
    statuses = {row["atlas_id"]: (row["status"], row.get("reason")) for row in first.doc["members"]}
    check(
        "fixture-statuses",
        statuses.get(SECRET) == ("excluded", None)
        and statuses.get(GONE) == ("unmounted", None)
        and statuses.get(EXT) == ("invalid", "outside_project"),
        statuses,
    )
    run_reuse(project, first, unread, classify, "unchanged")

    edit_row(project, SECRET, path=RELOCATED)
    write(project / "atlas" / "secret-relocated" / "notes" / "s.md", f"{CANARY} relocated\n")
    relocated = run_change(
        project,
        label="excluded-path",
        previous=first,
        unread=[project / "atlas" / "secret-relocated", ext],
        classify=[gone],
        atlas_id=SECRET,
        expect={"atlas_id": SECRET, "path": RELOCATED, "subpath": "", "status": "excluded", "reason": None},
    )
    if relocated is None:
        return

    edit_row(project, GONE, subpath=NESTED)
    nested = project / "atlas" / "gone" / NESTED
    write(nested / "notes" / "g.md", f"{CANARY} nested\n")
    moved = run_change(
        project,
        label="unmounted-subpath",
        previous=relocated,
        unread=[project / "atlas" / "secret-relocated", ext],
        classify=[nested],
        atlas_id=GONE,
        expect={"atlas_id": GONE, "path": "atlas/gone", "subpath": NESTED, "status": "unmounted", "reason": None},
    )
    if moved is None:
        return

    edit_row(project, EXT, id=INVALID_ID)
    run_change(
        project,
        label="invalid-reason",
        previous=moved,
        unread=[project / "atlas" / "secret-relocated", ext],
        classify=[nested],
        atlas_id=INVALID_ID,
        expect={
            "atlas_id": INVALID_ID,
            "path": "../ext",
            "subpath": "",
            "status": "invalid",
            "reason": "invalid_atlas_id",
        },
    )


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr4-"))
    try:
        run(tmp)
    finally:
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILURES:
        print(f"\n{len(FAILURES)} mesh review CR4 check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("\nAll mesh review CR4 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
