#!/usr/bin/env python3
"""Copilot review CR3 for packet MB (native mesh graph).

1. A member edit between the digest read and the later view read must not be
   published: the graph and its digest come from the same loaded bytes. The
   edit is injected by a ``Path.read_bytes`` hook on the first read of the
   page, not by sleeping.
2. ``index_location.pinned`` is context-local. Overlapping pins of the same
   store (one thread exits while the other is still inside) each see only
   their own location, and the store is not left pinned afterwards.

In-process against a temporary mesh. Linux-safe: no network, no git.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, index_publish, mesh_graph, mesh_scope  # noqa: E402
from test_mesh_graph import ALPHA, build_mesh  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if not ok and detail != "" else ""))
    if not ok:
        FAILURES.append(name)


def discover(project: Path) -> mesh_scope.Mesh:
    index_location.clear_cache()
    return mesh_scope.discover(project)


def node_type(doc: dict, node_id: str) -> str | None:
    return next((n.get("type") for n in doc.get("nodes") or [] if n.get("id") == node_id), None)


def digest_now(project: Path) -> str:
    mesh = discover(project)
    members = mesh_scope.members(mesh)
    states = mesh_graph.member_states(members)
    mesh_graph.fill_digests(states)
    return mesh_graph.mesh_digest(states, members)


def install_edit(target: Path, edited: bytes) -> tuple[object, dict[str, int]]:
    """After the first byte read of ``target``, replace it on disk.

    The caller already holds the first read's bytes, so a later read sees the
    edit and an earlier hash does not. No sleep.
    """
    real = Path.read_bytes
    fired = {"n": 0}
    target_r = target.resolve()

    def patched(self: Path, *args: object, **kwargs: object) -> bytes:
        data = real(self, *args, **kwargs)
        try:
            hit = Path(self).resolve() == target_r
        except OSError:
            hit = False
        if hit and fired["n"] == 0:
            fired["n"] = 1
            target.write_bytes(edited)
        return data

    Path.read_bytes = patched  # type: ignore[method-assign]
    return real, fired


def pair_matches(published_type: str | None, published_digest: str, pre: str, post: str) -> bool:
    """A view built from the edited bytes must carry the edited digest, and vice versa."""
    if published_type == "note":
        return published_digest == post
    if published_type == "spec":
        return published_digest == pre
    return False


def run_consistent_publish(tmp: Path) -> None:
    print("published mesh graph matches the digest of the bytes it was built from")
    project = build_mesh(tmp / "publish")
    target = project / "atlas" / "alpha" / "notes" / "x.md"
    node_id = f"atlas://{ALPHA}/notes/x.md"
    original = target.read_bytes()
    edited = original.replace(b"type: spec\n", b"type: note\n", 1)
    check("publish-edit-ready", edited != original and len(edited) == len(original) and b"type: spec\n" in original)
    pre = digest_now(project)
    real, fired = install_edit(target, edited)
    try:
        result = mesh_graph.ensure(discover(project), force=True)
    finally:
        Path.read_bytes = real  # type: ignore[method-assign]
    post = digest_now(project)
    published = node_type(result.doc, node_id)
    check("publish-hook-fired", fired["n"] == 1, fired)
    check("publish-digests-differ", pre != post, (pre, post))
    check(
        "publish-pair-matches",
        pair_matches(published, result.mesh_digest, pre, post),
        {"type": published, "digest_is_pre": result.mesh_digest == pre, "digest_is_post": result.mesh_digest == post},
    )
    check("publish-not-memory", not result.in_memory and bool(result.generation), (result.in_memory, result.generation))
    pointer_path = result.index_dir / mesh_graph.CURRENT_NAME
    pointer = json.loads(pointer_path.read_text(encoding="utf-8")) if pointer_path.is_file() else {}
    graph_rel = pointer.get("graph")
    on_disk = json.loads((result.index_dir / graph_rel).read_text(encoding="utf-8")) if graph_rel else {}
    check(
        "publish-disk-pair-matches",
        pair_matches(node_type(on_disk, node_id), str(on_disk.get("mesh_digest") or ""), pre, post)
        and on_disk.get("mesh_digest") == pointer.get("mesh_digest") == result.mesh_digest,
        {"disk_type": node_type(on_disk, node_id), "pointer": pointer.get("mesh_digest"), "doc": result.mesh_digest},
    )


def run_consistent_fallback(tmp: Path) -> None:
    print("in-memory busy fallback also pairs the view with the digest of the same load")
    project = build_mesh(tmp / "fallback")
    target = project / "atlas" / "alpha" / "notes" / "x.md"
    node_id = f"atlas://{ALPHA}/notes/x.md"
    edited = target.read_bytes().replace(b"type: spec\n", b"type: note\n", 1)
    pre = digest_now(project)
    real, fired = install_edit(target, edited)
    saved = index_publish.BuildLock.try_acquire
    index_publish.BuildLock.try_acquire = lambda self: False  # type: ignore[method-assign]
    try:
        result = mesh_graph.ensure(discover(project), force=True, wait=0, fallback=True)
    finally:
        Path.read_bytes = real  # type: ignore[method-assign]
        index_publish.BuildLock.try_acquire = saved  # type: ignore[method-assign]
    post = digest_now(project)
    published = node_type(result.doc, node_id)
    check("fallback-hook-fired", fired["n"] == 1, fired)
    check("fallback-busy", result.in_memory and result.driver_note == mesh_graph.BUSY_NOTE, (result.in_memory, result.driver_note))
    check(
        "fallback-pair-matches",
        pair_matches(published, result.mesh_digest, pre, post),
        {"type": published, "digest_is_pre": result.mesh_digest == pre, "digest_is_post": result.mesh_digest == post},
    )
    check("fallback-wrote-nothing", not (mesh_graph.index_dir(project) / mesh_graph.CURRENT_NAME).exists())


def try_id(store: Path) -> str | None:
    try:
        return index_location.resolve(store).atlas_id
    except index_location.NotAStoreError:
        return None


def run_pin_isolation(tmp: Path) -> None:
    print("overlapping pins of one store stay in the caller's context")
    store = tmp / "pin" / "store"
    other = tmp / "pin" / "other"
    store.mkdir(parents=True)
    other.mkdir()
    project_a = tmp / "pin" / "proj-a"
    project_b = tmp / "pin" / "proj-b"
    project_a.mkdir()
    project_b.mkdir()
    loc_a = index_location.IndexLocation(store, project_a, "github.com/acme/alpha", "mesh", "mesh")
    loc_b = index_location.IndexLocation(store, project_b, "github.com/acme/beta", "mesh", "mesh")
    loc_other = index_location.IndexLocation(other, project_b, "github.com/acme/gamma", "mesh", "mesh")
    match_a = index_location.MeshMatch(project_a, {"id": loc_a.atlas_id, "path": "atlas/alpha"}, {"version": 1, "stores": []})
    match_b = index_location.MeshMatch(project_b, {"id": loc_b.atlas_id, "path": "atlas/beta"}, {"version": 1, "stores": []})

    index_location.clear_cache()
    barrier = threading.Barrier(2, timeout=10)
    seen: dict[str, str | None] = {}
    errors: list[BaseException] = []

    def thread_a() -> None:
        with index_location.pinned(loc_a, match_a):
            barrier.wait()
            barrier.wait()
            seen["a_during"] = index_location.resolve(store).atlas_id
            seen["a_match"] = getattr(index_location.mesh_match(store), "row", {}).get("id")
            barrier.wait()
        barrier.wait()

    def thread_b() -> None:
        barrier.wait()
        with index_location.pinned(loc_b, match_b):
            barrier.wait()
            seen["b_during"] = index_location.resolve(store).atlas_id
            seen["b_match"] = getattr(index_location.mesh_match(store), "row", {}).get("id")
            barrier.wait()
            barrier.wait()
            seen["b_after_a"] = index_location.resolve(store).atlas_id
            seen["b_match_after_a"] = getattr(index_location.mesh_match(store), "row", {}).get("id")

    def guarded(fn) -> None:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=guarded, args=(fn,)) for fn in (thread_a, thread_b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    check("pin-threads-finished", all(not thread.is_alive() for thread in threads) and not errors, errors or "timed out")
    check("pin-a-sees-own", seen.get("a_during") == loc_a.atlas_id, seen)
    check("pin-b-sees-own", seen.get("b_during") == loc_b.atlas_id, seen)
    check("pin-a-match-own", seen.get("a_match") == loc_a.atlas_id, seen)
    check("pin-b-match-own", seen.get("b_match") == loc_b.atlas_id, seen)
    check("pin-b-after-a-exit", seen.get("b_after_a") == loc_b.atlas_id, seen)
    check("pin-b-match-after-a-exit", seen.get("b_match_after_a") == loc_b.atlas_id, seen)
    check("pin-not-left-pinned", try_id(store) is None, try_id(store))
    check("pin-match-not-left", index_location.mesh_match(store) is None, index_location.mesh_match(store))

    # A pin held on this thread is invisible to a thread that has not pinned.
    leaked: dict[str, str | None] = {}

    def outsider() -> None:
        leaked["before"] = try_id(store)
        with index_location.pinned(loc_b):
            leaked["inside"] = index_location.resolve(store).atlas_id
        leaked["after"] = try_id(store)

    with index_location.pinned(loc_a):
        worker = threading.Thread(target=outsider)
        worker.start()
        worker.join(10)
        leaked["main"] = index_location.resolve(store).atlas_id
    check("pin-outsider-blind", leaked.get("before") is None and leaked.get("after") is None, leaked)
    check("pin-outsider-own", leaked.get("inside") == loc_b.atlas_id, leaked)
    check("pin-main-unaffected", leaked.get("main") == loc_a.atlas_id and try_id(store) is None, leaked)

    with index_location.pinned(loc_a, match_a):
        check("pin-nested-outer", index_location.resolve(store).atlas_id == loc_a.atlas_id)
        check("pin-nested-outer-match", index_location.mesh_match(store) is match_a)
        with index_location.pinned(loc_b):
            # An inner pin that omits match keeps the outer row (packet MC).
            check("pin-nested-inner-id", index_location.resolve(store).atlas_id == loc_b.atlas_id)
            check("pin-nested-inner-keeps-match", index_location.mesh_match(store) is match_a)
            with index_location.pinned(loc_other):
                check("pin-other-store", index_location.resolve(other).atlas_id == loc_other.atlas_id)
                check("pin-other-does-not-hide", index_location.resolve(store).atlas_id == loc_b.atlas_id)
            check("pin-other-restored", try_id(other) is None)
        with index_location.pinned(loc_a, match_b):
            check("pin-nested-replaced-match", index_location.mesh_match(store) is match_b)
        check("pin-nested-match-restored", index_location.mesh_match(store) is match_a)
        check("pin-nested-id-restored", index_location.resolve(store).atlas_id == loc_a.atlas_id)
    check("pin-nested-cleared", try_id(store) is None and index_location.mesh_match(store) is None)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr3-"))
    old_root = os.environ.pop(index_location.OVERRIDE_ENV, None)
    try:
        run_consistent_publish(tmp)
        run_consistent_fallback(tmp)
        run_pin_isolation(tmp)
    finally:
        if old_root is not None:
            os.environ[index_location.OVERRIDE_ENV] = old_root
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILURES:
        print(f"\n{len(FAILURES)} mesh review CR3 check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("\nAll mesh review CR3 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
