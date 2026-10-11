#!/usr/bin/env python3
"""Mesh graph index (packet MB, M5, M6, M8, M9, M10): layout and pointer,
canary privacy, digest freshness, locking, lock order, the compile refresh
hook and determinism.

In-process against a temporary three-store mesh. Linux-safe: no network, no git.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import graph, index_location, index_publish, mesh_graph, mesh_scope, owned_lock  # noqa: E402
from atlas_cli.commands import validate as cmd_validate  # noqa: E402
from test_mesh_graph import (  # noqa: E402
    ALPHA,
    BETA,
    CANARY,
    EXT,
    GAMMA,
    SECRET,
    add_contract_rows,
    build_mesh,
    contract,
    restricted_page,
    write,
)

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if not ok and detail != "" else ""))
    if not ok:
        FAILURES.append(name)


def discover(project: Path) -> mesh_scope.Mesh:
    index_location.clear_cache()
    return mesh_scope.discover(project)


def generations(project: Path) -> list[str]:
    gens = project / ".atlas" / "indexes" / "graph" / "_mesh" / "generations"
    return sorted(p.name for p in gens.iterdir()) if gens.is_dir() else []


def pointer(project: Path) -> dict:
    return json.loads((project / ".atlas" / "indexes" / "graph" / "_mesh" / "current.json").read_text(encoding="utf-8"))


class ViewCounter:
    """Counts mesh graph rebuild loads (each one projects the mesh once).

    A rebuild loads members once and publishes that view under that digest, so
    the counter wraps that load rather than a later reread of the members.
    """

    def __init__(self, delay: float = 0.0) -> None:
        self.calls = 0
        self.delay = delay
        self.original = mesh_graph._load_consistent
        self.lock = threading.Lock()

    def __call__(self, mesh: mesh_scope.Mesh, all_members: list) -> tuple:
        with self.lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return self.original(mesh, all_members)

    def __enter__(self) -> "ViewCounter":
        mesh_graph._load_consistent = self
        return self

    def __exit__(self, *exc: object) -> None:
        mesh_graph._load_consistent = self.original


def add_canaries(project: Path) -> None:
    """Restricted pages in two stores and a canary-named page in the excluded store."""
    write(project / "atlas" / "beta" / "notes" / "secret-b.md", restricted_page())
    write(project / "atlas" / "gamma" / "notes" / "secret-g.md", restricted_page())
    write(project / "atlas" / "secret" / "notes" / f"{CANARY}.md", restricted_page().replace("Restricted", "public"))


def compile_store(store: Path, dry_run: bool = False) -> tuple[int, dict]:
    index_location.clear_cache()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cmd_validate.run(str(store), True, None, None, dry_run)
    return code, json.loads(buf.getvalue())


def mesh_items(result: dict) -> list[dict]:
    return [i for i in [*result.get("warnings", []), *result.get("info", [])] if str(i.get("id", "")).startswith("mesh_graph")]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-graph-index-"))
    saved_hook = owned_lock.before_critical_section
    try:
        run(tmp)
    finally:
        owned_lock.before_critical_section = saved_hook
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILURES:
        print(f"\n{len(FAILURES)} mesh graph index check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("\nAll mesh graph index checks passed")
    return 0


def run(tmp: Path) -> None:
    project = build_mesh(tmp / "a")
    add_canaries(project)
    alpha = project / "atlas" / "alpha"
    root = project / ".atlas" / "indexes" / "graph" / "_mesh"

    print("layout and pointer")
    mesh = discover(project)
    check("not-built-yet", not mesh_graph.exists(project) and mesh_graph.status(mesh)["built"] is False)
    mg = mesh_graph.ensure(mesh)
    gens = generations(project)
    cur = pointer(project)
    check("index-dir", mg.index_dir == root.resolve() or mg.index_dir == root, mg.index_dir)
    check("one-generation", len(gens) == 1 and mg.rebuilt, gens)
    check("pointer-graph-path", cur.get("graph") == f"generations/{gens[0]}/mesh-graph.json", cur.get("graph"))
    check("snapshot-file", (root / "generations" / gens[0] / "mesh-graph.json").is_file())
    check("pointer-digest", cur.get("mesh_digest") == mg.mesh_digest and len(mg.mesh_digest) == 64, cur.get("mesh_digest"))
    rows = cur.get("members") or []
    check("pointer-members", [r["atlas_id"] for r in rows] == sorted([ALPHA, BETA, GAMMA]), rows)
    check("pointer-fingerprints", all(r.get("cheap_fingerprint") and r.get("corpus_digest") for r in rows), rows)
    check("pointer-excluded", cur.get("excluded") == [SECRET], cur.get("excluded"))
    check("no-temp-left", not any(p.name.startswith(".tmp-") for p in root.iterdir()), list(root.iterdir()))
    doc = mg.doc
    node_keys = set().union(*(set(n) for n in doc["nodes"]))
    edge_keys = set().union(*(set(e) for e in doc["edges"]))
    check("node-keys-structure-only", node_keys <= {"id", "atlas_id", "path", "type", *mesh_scope.NODE_SCALARS}, node_keys)
    check("edge-keys", edge_keys <= {"from", "to", "kind", "cross", "resolved", "resolution", "reason", "suggest"}, edge_keys)
    check("no-restricted-node", not any(n["path"].startswith("notes/secret-") or n["path"] == "notes/hidden.md" for n in doc["nodes"]))
    check("no-excluded-node", not any(n["atlas_id"] == SECRET for n in doc["nodes"]))

    print("canary privacy")
    hits = []
    for mesh_dir in (project / ".atlas" / "indexes").glob("*/_mesh"):
        for path in mesh_dir.rglob("*"):
            if path.is_file() and CANARY.lower() in path.read_text(encoding="utf-8", errors="replace").lower():
                hits.append(str(path))
    check("canary-scan-zero", hits == [], hits)
    st = mesh_graph.status(mesh)
    check("status-no-canary", CANARY not in json.dumps(st), st)

    print("freshness")
    with ViewCounter() as counter:
        again = mesh_graph.ensure(discover(project))
        check("fresh-no-rebuild", counter.calls == 0 and not again.rebuilt and again.generation == mg.generation)
        os.utime(alpha / "notes" / "x.md", (time.time() + 5, time.time() + 5))
        again = mesh_graph.ensure(discover(project))
        check("touch-mtime-same-digest-no-rebuild", counter.calls == 0 and again.mesh_digest == mg.mesh_digest)
        page = alpha / "notes" / "x.md"
        page.write_text(page.read_text(encoding="utf-8").replace("type: spec", "type: spec\nkva: V"), encoding="utf-8")
        changed = mesh_graph.ensure(discover(project))
        check("edit-changes-digest", changed.mesh_digest != mg.mesh_digest)
        check("edit-one-rebuild", counter.calls == 1 and changed.rebuilt, counter.calls)
        once_more = mesh_graph.ensure(discover(project))
        check("edit-exactly-one-rebuild", counter.calls == 1 and not once_more.rebuilt, counter.calls)
        check("status-fresh", mesh_graph.status(discover(project))["fresh"] is True)
        page.write_text(page.read_text(encoding="utf-8").replace("kva: V", "kva: K"), encoding="utf-8")
        check("status-stale-after-edit", mesh_graph.status(discover(project))["fresh"] is False)
        base = mesh_graph.ensure(discover(project)).mesh_digest
        mesh_file = project / "atlas-mesh.json"
        original = mesh_file.read_text(encoding="utf-8")
        cfg = json.loads(original)
        cfg["stores"][2]["mesh_member"] = False
        mesh_file.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        excluded = mesh_graph.ensure(discover(project))
        check("membership-change-digest", excluded.mesh_digest != base and GAMMA in (excluded.pointer or {}).get("excluded", []))
        cfg = json.loads(original)
        moved = project / "atlas" / "gamma2"
        shutil.copytree(project / "atlas" / "gamma", moved)
        cfg["stores"][2]["path"] = "atlas/gamma2"
        mesh_file.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        relocated = mesh_graph.ensure(discover(project))
        check("path-change-digest", relocated.mesh_digest not in (base, excluded.mesh_digest))
        mesh_file.write_text(original, encoding="utf-8")
        shutil.rmtree(moved)
        check("config-restored-digest", mesh_graph.ensure(discover(project)).mesh_digest == base)
    check("keeps-two-generations", len(generations(project)) <= mesh_graph.KEEP_GENERATIONS, generations(project))

    print("determinism")
    first = mesh_graph.ensure(discover(project), force=True)
    bytes_a = (root / first.pointer["graph"]).read_bytes()
    second = mesh_graph.ensure(discover(project), force=True)
    bytes_b = (root / second.pointer["graph"]).read_bytes()
    check("determinism-new-generation", first.generation != second.generation)
    check("determinism-byte-identical", bytes_a == bytes_b)

    print("locking")
    project_l = build_mesh(tmp / "lock")
    mesh_l = discover(project_l)
    mesh_graph.ensure(mesh_l)
    note = project_l / "atlas" / "beta" / "notes" / "child.md"
    note.write_text(note.read_text(encoding="utf-8") + "\nMore.\n", encoding="utf-8")
    results: list[mesh_graph.MeshGraph] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def builder() -> None:
        try:
            barrier.wait()
            results.append(mesh_graph.ensure(discover(project_l), wait=10))
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    with ViewCounter(delay=0.4) as counter:
        threads = [threading.Thread(target=builder) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    check("concurrent-no-errors", not errors, errors)
    check("concurrent-publish-once", counter.calls == 1 and sum(r.rebuilt for r in results) == 1, (counter.calls, [r.rebuilt for r in results]))
    check("concurrent-same-generation", len({r.generation for r in results}) == 1 and not any(r.in_memory for r in results))

    lock_root = mesh_graph.index_dir(project_l)
    before = pointer(project_l)
    gens_before = generations(project_l)
    note.write_text(note.read_text(encoding="utf-8") + "\nTakeover.\n", encoding="utf-8")

    def intruder(lock: owned_lock.OwnedLock) -> None:
        info = lock.info() or {}
        info["owner"] = "intruder"
        lock.path.write_text(json.dumps(info), encoding="utf-8")

    owned_lock.before_critical_section = intruder
    try:
        raised = None
        try:
            mesh_graph.ensure(discover(project_l), fallback=False)
        except index_publish.LockLost as e:
            raised = e
    finally:
        owned_lock.before_critical_section = None
    check("takeover-raises-lock-lost", raised is not None)
    check("takeover-pointer-unchanged", pointer(project_l) == before)
    check("takeover-no-new-generation", generations(project_l) == gens_before, (generations(project_l), gens_before))
    (lock_root / index_publish.LOCK_NAME).unlink(missing_ok=True)

    holder = index_publish.BuildLock(lock_root)
    check("holder-acquired", holder.try_acquire())
    try:
        started = time.monotonic()
        busy = mesh_graph.ensure(discover(project_l), wait=0.2)
        elapsed = time.monotonic() - started
        check("busy-reader-in-memory", busy.in_memory and busy.driver_note == mesh_graph.BUSY_NOTE, busy.driver_note)
        check("busy-reader-bounded-wait", elapsed < 3.0, elapsed)
        check("busy-reader-answers", any(n["atlas_id"] == BETA for n in busy.doc["nodes"]))
        check("busy-reader-publishes-nothing", pointer(project_l) == before and generations(project_l) == gens_before)
        check("busy-default-wait-is-5s", mesh_graph.READ_WAIT_SECONDS == 5.0)
        try:
            mesh_graph.ensure(discover(project_l), wait=0.1, fallback=False)
            strict = False
        except index_publish.IndexBusy:
            strict = True
        check("busy-builder-raises", strict)
        item = mesh_graph.refresh_after_compile(project_l / "atlas" / "beta")
        check("busy-compile-warning", item is not None and item["id"] == "mesh_graph_refresh_failed", item)
    finally:
        holder.release()
    check("lock-stale-timeout-10min", index_publish.LOCK_STALE_SECONDS == 600.0)

    print("lock order")
    acquired: list[Path] = []
    original_try = owned_lock.OwnedLock.try_acquire

    def spy(self: owned_lock.OwnedLock) -> bool:
        acquired.append(Path(self.parent).resolve())
        return original_try(self)

    owned_lock.OwnedLock.try_acquire = spy  # type: ignore[method-assign]
    try:
        note.write_text(note.read_text(encoding="utf-8") + "\nOrder.\n", encoding="utf-8")
        mesh_graph.ensure(discover(project_l), force=True)
    finally:
        owned_lock.OwnedLock.try_acquire = original_try  # type: ignore[method-assign]
    check("lock-order-only-mesh-lock", bool(acquired) and set(acquired) == {lock_root.resolve()}, acquired)

    print("compile refresh")
    project_c = build_mesh(tmp / "compile")
    delta_c = project_c / "atlas" / "delta"
    init = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "atlas.py"), "init", "--root", str(delta_c), "--schema-version", "1.0", "--json"],
        capture_output=True, text=True, env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "disabled:"},
    )
    check("compile-init-clean-store", init.returncode == 0, init.stderr)
    write(delta_c / "index.md", "# Delta\n\n- notes\n")
    write(delta_c / "notes" / "index.md", "# Notes\n\n- x\n")
    write(
        delta_c / "notes" / "x.md",
        "---\ntype: lesson\ntitle: Delta lesson\ncreated: 2026-10-10\nrelates_to:\n"
        f"  - path: atlas://{ALPHA}/notes/x.md\n    kind: implements\n---\n\n"
        "## Claim\n\nDelta implements the alpha spec, with enough prose to pass the thin page gate.\n",
    )
    mesh_doc = json.loads((project_c / "atlas-mesh.json").read_text(encoding="utf-8"))
    mesh_doc["stores"].append({"id": "github.com/acme/delta", "path": "atlas/delta"})
    (project_c / "atlas-mesh.json").write_text(json.dumps(mesh_doc, indent=2) + "\n", encoding="utf-8")
    code, result = compile_store(delta_c)
    check("compile-clean-baseline", code in (0, 1) and not result.get("critical"), result.get("critical"))
    check("compile-no-index-no-refresh", not mesh_items(result) and not mesh_graph.exists(project_c), mesh_items(result))
    baseline = code
    first = mesh_graph.ensure(discover(project_c))
    x = delta_c / "notes" / "x.md"
    x.write_text(x.read_text(encoding="utf-8") + "\nCompiled.\n", encoding="utf-8")
    code, result = compile_store(delta_c, dry_run=True)
    check("compile-dry-run-no-refresh", not mesh_items(result) and pointer(project_c)["generation"] == first.generation)
    code, result = compile_store(delta_c)
    items = mesh_items(result)
    check("compile-refreshes", [i["id"] for i in items] == ["mesh_graph_refreshed"] and pointer(project_c)["generation"] != first.generation, items)
    check("compile-exit-unchanged", code == baseline, (code, baseline))
    code, result = compile_store(delta_c)
    check("compile-fresh-info", [i["id"] for i in mesh_items(result)] == ["mesh_graph_fresh"], mesh_items(result))
    saved = mesh_graph.ensure

    def boom(*_a: object, **_k: object) -> mesh_graph.MeshGraph:
        raise RuntimeError("forced failure")

    mesh_graph.ensure = boom  # type: ignore[assignment]
    try:
        code, result = compile_store(delta_c)
    finally:
        mesh_graph.ensure = saved  # type: ignore[assignment]
    failed = [i for i in result.get("warnings", []) if i.get("id") == "mesh_graph_refresh_failed"]
    check("compile-failure-is-warning", len(failed) == 1 and "forced failure" in failed[0]["msg"], result.get("warnings"))
    check("compile-failure-exit-unchanged", code == baseline, (code, baseline))
    solo = tmp / "solo"
    contract(solo, "github.com/acme/solo", "Solo")
    write(solo / "notes" / "a.md", "---\ntype: lesson\ntitle: Solo\n---\n\nBody.\n")
    code, result = compile_store(solo)
    check("compile-standalone-no-item", not mesh_items(result))

    run_invalid_never_read(tmp)


class ReadRecorder:
    """Records every root the mesh graph reads pages, schema or fingerprints from."""

    TARGETS = ((graph, "load_source"), (mesh_graph, "load_schema"), (mesh_graph, "eligible_paths"),
               (mesh_graph, "cheap_fingerprint"), (mesh_graph, "content_digest"))

    def __init__(self) -> None:
        self.roots: list[Path] = []
        self.saved: list[tuple[object, str, object]] = []

    def __enter__(self) -> "ReadRecorder":
        for module, name in self.TARGETS:
            original = getattr(module, name)
            self.saved.append((module, name, original))

            def wrapper(root, *a, _original=original, **k):
                self.roots.append(Path(root))
                return _original(root, *a, **k)

            setattr(module, name, wrapper)
        return self

    def __exit__(self, *exc: object) -> None:
        for module, name, original in self.saved:
            setattr(module, name, original)


def run_invalid_never_read(tmp: Path) -> None:
    print("invalid member never read (MA R2/R4)")
    base = tmp / "invalid"
    project = build_mesh(base)
    add_contract_rows(base, project)
    ext = (base / "ext").resolve()
    with ReadRecorder() as rec:
        mg = mesh_graph.ensure(discover(project), force=True)
        q = mesh_graph.Query(mg, project / "atlas" / "alpha")
        q.nodes_query(wheres=[("created", "2026-10-10")])
        st = mesh_graph.status(discover(project))
        block = mesh_graph.describe_block(discover(project))
        mesh_graph.refresh_after_compile(project / "atlas" / "alpha")
    touched = sorted({str(r) for r in rec.roots if r.resolve() == ext or ext in r.resolve().parents})
    check("invalid-roots-recorded", bool(rec.roots), rec.roots)
    check("invalid-never-read", touched == [], touched)
    status = {m.atlas_id: (m.status, m.reason) for m in mg.members}
    check("invalid-status", status.get(EXT) == (mesh_scope.STATUS_INVALID, mesh_scope.MEMBER_OUTSIDE_PROJECT), status)
    check("invalid-no-nodes", not any(n["atlas_id"] == EXT for n in mg.doc["nodes"]))
    check("invalid-in-pointer", (mg.pointer or {}).get("invalid") == [EXT], mg.pointer)
    check("invalid-in-block", block.get("invalid") == [{"atlas_id": EXT, "reason": "outside_project"}], block.get("invalid"))
    check("invalid-status-fresh", st.get("fresh") is True, st)
    hosts = {e["to"] for e in mg.doc["edges"] if e.get("reason") == mesh_scope.REASON_OUTSIDE}
    check("invalid-link-outside-mesh", f"atlas://{EXT}/notes/e.md" in hosts, hosts)
    for label, call in (("store", lambda: q.store_ids([EXT])), ("page", lambda: q.node(f"atlas://{EXT}/notes/e.md"))):
        try:
            call()
            check(f"invalid-{label}-refused", False, "no error")
        except mesh_scope.MeshScopeError as e:
            check(f"invalid-{label}-refused", "invalid" in str(e) and "outside_project" in str(e), str(e))
    path = project / "atlas-mesh.json"
    original = path.read_text(encoding="utf-8")
    doc = json.loads(original)
    doc["stores"] = [r for r in doc["stores"] if r["id"] != EXT]
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    dropped = mesh_graph.ensure(discover(project))
    check("invalid-change-digest", dropped.rebuilt and dropped.mesh_digest != mg.mesh_digest, (dropped.mesh_digest, mg.mesh_digest))
    path.write_text(original, encoding="utf-8")
    check("invalid-restored-digest", mesh_graph.ensure(discover(project)).mesh_digest == mg.mesh_digest)

    print("page path with # in the index (MA R3)")
    hash_id = f"atlas://{ALPHA}/notes/a%23b.md"
    nodes = {n["id"]: n for n in mg.doc["nodes"]}
    check("hash-index-id", nodes.get(hash_id, {}).get("path") == "notes/a#b.md", sorted(nodes))
    check("hash-index-round-trip", all(mesh_scope.parse_node_id(n["id"]) == (n["atlas_id"], n["path"]) for n in mg.doc["nodes"]))
    to_hash = {e["from"] for e in mg.doc["edges"] if e["to"] == hash_id and e["resolved"]}
    check("hash-index-edges", to_hash == {f"atlas://{ALPHA}/notes/to-hash.md", f"atlas://{BETA}/notes/to-hash.md"}, to_hash)
    check("hash-query-root-path", q.node("notes/a#b.md")["id"] == hash_id and q.node(hash_id)["id"] == hash_id)


if __name__ == "__main__":
    raise SystemExit(main())
