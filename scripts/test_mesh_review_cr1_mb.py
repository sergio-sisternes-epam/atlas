#!/usr/bin/env python3
"""Copilot review CR1 for packet MB (native mesh graph).

1. ``atlas index build --mesh --all`` builds only ``ok`` members. Excluded,
   ``invalid`` (absolute or ``..`` is ``outside_project``; an in-project
   symlink component is ``symlinked_root``, even when the target is outside
   or the row is ``mesh_member: false``) and unmounted rows are reported as
   skipped, and their roots are never resolved or built.
2. ``graph export --scope mesh`` refuses an ``--out`` that reaches an excluded
   or ``invalid`` member through a symlinked root (or a link into one),
   without resolving that root.
3. A build lock lost mid-build takes the reader fallback (in-memory graph with
   ``driver_note: mesh_index_busy``); ``fallback=False`` still raises.

In-process against a temporary mesh. Linux-safe: no network, no git.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.commands import index as cmd_index  # noqa: E402
from atlas_cli.core import index_location, index_publish, mesh_graph, mesh_scope, owned_lock  # noqa: E402
from test_mesh_graph import ALPHA, BETA, EXT, GAMMA, GONE, SECRET, add_contract_rows, build_mesh, contract  # noqa: E402

FAILURES: list[str] = []
ABS = "github.com/acme/absolute"
LINKED = "github.com/acme/linked"


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if not ok and detail != "" else ""))
    if not ok:
        FAILURES.append(name)


def discover(project: Path) -> mesh_scope.Mesh:
    index_location.clear_cache()
    return mesh_scope.discover(project)


def add_rows(project: Path, rows: list[dict]) -> None:
    path = project / "atlas-mesh.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["stores"].extend(rows)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def run_build_all(tmp: Path) -> None:
    print("index build --mesh --all builds only ok members")
    base = tmp / "build-all"
    project = build_mesh(base)
    add_contract_rows(base, project)
    outside = (base / "abs").resolve()
    contract(outside, ABS, "Absolute")
    linked = (base / "linked-target").resolve()
    contract(linked, LINKED, "Linked")
    (project / "atlas" / "linked").symlink_to(linked, target_is_directory=True)
    add_rows(project, [{"id": ABS, "path": str(outside)}, {"id": LINKED, "path": "atlas/linked"}])
    statuses = {m.atlas_id: m.status for m in mesh_scope.members(discover(project))}
    check(
        "fixture-statuses",
        statuses
        == {
            ALPHA: "ok", BETA: "ok", GAMMA: "ok", SECRET: "excluded", GONE: "unmounted",
            EXT: "invalid", ABS: "invalid", LINKED: "invalid",
        },
        statuses,
    )

    built: list[str] = []
    original = cmd_index.build_store

    def recorder(ref, force=False):
        built.append(ref.store_id)
        return original(ref, force)

    cmd_index.build_store = recorder
    buf = io.StringIO()
    try:
        index_location.clear_cache()
        with contextlib.redirect_stdout(buf):
            code = cmd_index.run_build_mesh(str(project), None, True, False, True)
    finally:
        cmd_index.build_store = original
    out = json.loads(buf.getvalue())
    stores = {s["store_id"]: s for s in out.get("stores") or []}
    check("all-exit-0", code == 0, buf.getvalue()[:400])
    check("all-builds-only-ok", sorted(built) == sorted([ALPHA, BETA, GAMMA]), built)
    check("all-reports-every-row", len(stores) == 8, sorted(stores))
    for sid, status in ((SECRET, "excluded"), (GONE, "unmounted"), (EXT, "invalid"), (ABS, "invalid"), (LINKED, "invalid")):
        s = stores.get(sid) or {}
        check(f"all-skipped-{status}-{sid.rsplit('/', 1)[-1]}", s.get("status") == "skipped" and s.get("member_status") == status, s)
        check(f"all-no-root-{sid.rsplit('/', 1)[-1]}", "root" not in s and "generation" not in s, s)
    for sid in (EXT, ABS):
        check(f"all-invalid-reason-{sid.rsplit('/', 1)[-1]}", (stores.get(sid) or {}).get("reason") == "outside_project", stores.get(sid))
    # An in-project symlink is not resolved, so it is symlinked_root rather than outside_project.
    check("all-invalid-reason-linked", (stores.get(LINKED) or {}).get("reason") == "symlinked_root", stores.get(LINKED))
    for label, root in (("ext", base / "ext"), ("abs", outside), ("linked", linked), ("secret", project / "atlas" / "secret")):
        check(f"all-nothing-written-{label}", not (root / ".atlas").exists(), sorted(p.name for p in root.iterdir()))
    leaked = sorted(p.name for p in (project / ".atlas" / "indexes").rglob("*") if SECRET.rsplit("/", 1)[-1] in p.name or "ext" == p.name)
    check("all-no-excluded-index", not leaked, leaked)
    check("all-mesh-built", (out.get("mesh") or {}).get("status") == "built", out.get("mesh"))


def run_export_symlink(tmp: Path) -> None:
    print("export --out through a symlinked excluded or invalid root")
    base = tmp / "export"
    project = build_mesh(base)
    secret = project / "atlas" / "secret"
    real = (base / "secret-real").resolve()
    shutil.move(str(secret), str(real))
    secret.symlink_to(real, target_is_directory=True)
    evil_target = (base / "evil-target").resolve()
    evil_target.mkdir()
    (project / "atlas" / "evil").symlink_to(evil_target, target_is_directory=True)
    add_rows(project, [{"id": EXT, "path": "atlas/evil"}])
    (base / "link-to-secret").symlink_to(secret, target_is_directory=True)
    mesh = discover(project)
    statuses = {m.atlas_id: (m.status, m.reason) for m in mesh_scope.members(mesh)}
    check(
        "export-fixture",
        statuses.get(SECRET) == ("invalid", "symlinked_root") and statuses.get(EXT) == ("invalid", "symlinked_root"),
        statuses,
    )

    resolved: list[str] = []
    original_resolve = Path.resolve

    def spy(self, *a, **k):
        if sys._getframe(1).f_globals.get("__name__") == mesh_graph.__name__:
            resolved.append(os.path.abspath(self))
        return original_resolve(self, *a, **k)

    cases = (
        ("excluded-through-root", secret / "exp", SECRET),
        ("excluded-through-link", base / "link-to-secret" / "exp", SECRET),
        ("excluded-root-itself", secret, SECRET),
        ("invalid-through-root", project / "atlas" / "evil" / "exp", EXT),
    )
    for label, out, sid in cases:
        Path.resolve = spy
        try:
            mesh_graph.check_export_out(mesh, str(out))
            refused = ""
        except mesh_graph.MeshGraphError as e:
            refused = str(e)
        finally:
            Path.resolve = original_resolve
        check(f"export-refuses-{label}", f"inside member {sid}" in refused, refused or "accepted")
    under = lambda root: [r for r in resolved if r == str(root) or r.startswith(str(root) + os.sep)]  # noqa: E731
    check("export-never-resolves-excluded-root", not under(secret) and not under(base / "link-to-secret"), resolved)
    check("export-never-resolves-invalid-root", not under(project / "atlas" / "evil"), resolved)
    for label, out in (("outside", base / "out"), ("sibling-target", evil_target.parent / "elsewhere")):
        try:
            got = mesh_graph.check_export_out(mesh, str(out))
            ok = got == original_resolve(out)
        except mesh_graph.MeshGraphError as e:
            ok = False
            got = e
        check(f"export-allows-{label}", ok, got)
    with contextlib.suppress(mesh_graph.MeshGraphError):
        mesh_graph.check_export_out(mesh, str(secret / "exp"))
    check("export-nothing-written-in-target", not (real / "exp").exists())


def run_lock_lost(tmp: Path) -> None:
    print("lock lost mid-build takes the reader fallback")
    project = build_mesh(tmp / "lock")
    lock_file = mesh_graph.index_dir(project) / index_publish.LOCK_NAME

    def intruder(lock: owned_lock.OwnedLock) -> None:
        info = lock.info() or {}
        info["owner"] = "intruder"
        lock.path.write_text(json.dumps(info), encoding="utf-8")

    def lose_in_build(lock) -> None:
        raise index_publish.LockLost("index build lock lost (lock_lost); generation not published")

    for label in ("critical-section", "before-publish"):
        saved_hook, saved_owned = owned_lock.before_critical_section, index_publish.ensure_owned
        if label == "critical-section":
            owned_lock.before_critical_section = intruder
        else:
            index_publish.ensure_owned = lose_in_build
        try:
            try:
                mg = mesh_graph.ensure(discover(project), force=True)
                got = (mg.in_memory, mg.driver_note, any(n["atlas_id"] == BETA for n in mg.doc["nodes"]))
            except Exception as e:  # noqa: BLE001 - the regression is an uncaught exception
                got = repr(e)
            check(f"lock-lost-{label}-fallback", got == (True, mesh_graph.BUSY_NOTE, True), got)
            lock_file.unlink(missing_ok=True)
            try:
                mesh_graph.ensure(discover(project), force=True, fallback=False)
                strict = "no error"
            except index_publish.LockLost:
                strict = "LockLost"
            check(f"lock-lost-{label}-strict-raises", strict == "LockLost", strict)
        finally:
            owned_lock.before_critical_section, index_publish.ensure_owned = saved_hook, saved_owned
            lock_file.unlink(missing_ok=True)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr1-mb-"))
    try:
        run_build_all(tmp)
        run_export_symlink(tmp)
        run_lock_lost(tmp)
    finally:
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILURES:
        print(f"\n{len(FAILURES)} CR1 check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("\nAll CR1 checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
