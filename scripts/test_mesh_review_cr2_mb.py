#!/usr/bin/env python3
"""Copilot review CR2 for packet MB (native mesh graph).

1. ``atlas index build --mesh --all`` builds each ``ok`` member at its own
   root: ``.atlas/<atlas-id>`` for a row with no ``path`` and ``path/subpath``
   for a subpath row (never the parent store holding it), with the member's
   row id as its index location and no ``git`` subprocess.
2. The mesh graph's freshness is decided by content (PR #61 rule R4): a
   same-length page edit that keeps its original mtime leaves every cheap
   fingerprint unchanged, yet the next mesh read rebuilds and answers from the
   new bytes.

In-process against a temporary mesh. Linux-safe: no network, no git.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.commands import index as cmd_index  # noqa: E402
from atlas_cli.core import ignore_guard, index_location, mesh_graph, mesh_scope, recall_index  # noqa: E402
from atlas_cli.core.projection import cheap_fingerprint, eligible_paths  # noqa: E402
from test_mesh_graph import ALPHA, build_mesh, contract, page, write  # noqa: E402

FAILURES: list[str] = []
PATHLESS = "github.com/acme/pathless"
SUB = "github.com/acme/sub"
PARENT = "github.com/acme/parent"


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if not ok and detail != "" else ""))
    if not ok:
        FAILURES.append(name)


def discover(project: Path) -> mesh_scope.Mesh:
    index_location.clear_cache()
    return mesh_scope.discover(project)


@contextlib.contextmanager
def no_git(calls: list[list[str]]):
    """Every ``git`` subprocess is recorded and refused (a non-OSError, so nothing swallows it)."""
    saved = {name: getattr(subprocess, name) for name in ("run", "Popen", "check_output", "check_call", "call")}

    def guard(name):
        real = saved[name]

        def wrapper(args, *a, **k):
            argv = [args] if isinstance(args, (str, bytes)) else list(args)
            if argv and os.path.basename(str(argv[0])) == "git":
                calls.append([str(x) for x in argv])
                raise RuntimeError(f"git subprocess refused in test: {argv}")
            return real(args, *a, **k)

        return wrapper

    for name in saved:
        setattr(subprocess, name, guard(name))
    try:
        yield
    finally:
        for name, real in saved.items():
            setattr(subprocess, name, real)


def built_pages(store: Path, location: index_location.IndexLocation) -> list[str]:
    with index_location.pinned(location):
        gens = recall_index._candidates(store)
        return sorted(p.path for p in recall_index.pages_from_db(gens[0].db)) if gens else []


def run_build_all_roots(tmp: Path) -> None:
    print("index build --mesh --all builds pathless and subpath members at their own roots")
    project = tmp / "roots" / "proj"
    pathless = project / ".atlas" / "github.com" / "acme" / "pathless"
    contract(pathless, PATHLESS, "Pathless")
    write(pathless / "notes" / "p.md", page("Pathless"))
    parent = project / "atlas" / "parent"
    contract(parent, PARENT, "Parent")
    write(parent / "notes" / "parent-only.md", page("ParentOnly"))
    inner = parent / "inner"
    contract(inner, SUB, "Inner")
    write(inner / "notes" / "inner.md", page("Inner"))
    write(
        project / "atlas-mesh.json",
        json.dumps({"version": 1, "stores": [{"id": PATHLESS}, {"id": SUB, "path": "atlas/parent", "subpath": "inner"}]}, indent=2)
        + "\n",
    )
    members = {m.atlas_id: m for m in mesh_scope.members(discover(project))}
    check("roots-fixture-ok", {k: m.status for k, m in members.items()} == {PATHLESS: "ok", SUB: "ok"}, members)

    git_calls: list[list[str]] = []
    built_roots: dict[str, Path] = {}
    original = cmd_index.build_store
    guard_git = ignore_guard._run_git

    def recorder(ref, force=False):
        built_roots[ref.store_id] = Path(ref.path)
        return original(ref, force)

    cmd_index.build_store = recorder
    # The P22 ignore guard edits info/exclude through git by design; only its
    # own git runner is stubbed ("not a git work tree"), so any git lookup of
    # an index location (walk-up, standalone id) is still refused and recorded.
    ignore_guard._run_git = lambda *_a, **_k: None
    old_env = os.environ.get("ATLAS_RECALL_ENGINE")
    os.environ["ATLAS_RECALL_ENGINE"] = "bm25"
    buf = io.StringIO()
    try:
        index_location.clear_cache()
        with no_git(git_calls), contextlib.redirect_stdout(buf):
            code = cmd_index.run_build_mesh(str(project), None, True, False, True)
    finally:
        cmd_index.build_store = original
        ignore_guard._run_git = guard_git
        if old_env is None:
            os.environ.pop("ATLAS_RECALL_ENGINE", None)
        else:
            os.environ["ATLAS_RECALL_ENGINE"] = old_env
        index_location.clear_cache()
    try:
        out = json.loads(buf.getvalue())
    except ValueError:
        out = {}
    stores = {s.get("store_id"): s for s in out.get("stores") or []}
    check("roots-exit-0", code == 0, buf.getvalue()[:600])
    check("roots-no-git", not git_calls, git_calls)
    check("roots-no-missing-path", not (project / ".atlas-missing-path").exists())
    for sid, want in ((PATHLESS, pathless), (SUB, inner)):
        tag = sid.rsplit("/", 1)[-1]
        res = stores.get(sid) or {}
        check(f"roots-built-{tag}", res.get("status") == "built", res)
        check(f"roots-own-root-{tag}", built_roots.get(sid) == want, built_roots.get(sid))
        loc = res.get("index_location") or {}
        check(f"roots-row-id-location-{tag}", loc.get("atlas_id") == sid and loc.get("mode") == "mesh", loc)
        check(f"roots-index-dir-{tag}", res.get("index_dir") == f".atlas/indexes/fts5/{sid}", res.get("index_dir"))
        check(f"roots-index-exists-{tag}", (project / ".atlas" / "indexes" / "fts5" / sid / "current.json").is_file())
        check(f"roots-index-under-project-{tag}", not (want / ".atlas").exists(), sorted(p.name for p in want.iterdir()))
    location = members[SUB].location()
    assert location is not None
    pages = built_pages(inner, location)
    check("roots-sub-own-corpus", pages == ["notes/inner.md"], pages)
    location = members[PATHLESS].location()
    assert location is not None
    pages = built_pages(pathless, location)
    check("roots-pathless-own-corpus", pages == ["notes/p.md"], pages)
    check("roots-parent-not-built", PARENT not in built_roots and not (parent / ".atlas").exists())


def node_type(mg: mesh_graph.MeshGraph, node_id: str) -> str | None:
    return next((n.get("type") for n in mg.doc.get("nodes") or [] if n.get("id") == node_id), None)


def run_same_stat_edit(tmp: Path) -> None:
    print("a same-length edit with the original mtime is seen by the next mesh read")
    project = build_mesh(tmp / "stat")
    alpha = project / "atlas" / "alpha"
    target = alpha / "notes" / "x.md"
    node_id = f"atlas://{ALPHA}/notes/x.md"
    first = mesh_graph.ensure(discover(project))
    check("stat-first-spec", node_type(first, node_id) == "spec", node_type(first, node_id))
    check("stat-first-generation", bool(first.generation), first.generation)

    alpha_member = next(m for m in mesh_scope.members(discover(project)) if m.atlas_id == ALPHA)
    schema = mesh_graph._member_schema(alpha_member)
    before_fp = cheap_fingerprint(alpha, schema, eligible_paths(alpha, schema))
    st = target.stat()
    raw = target.read_bytes()
    edited = raw.replace(b"type: spec\n", b"type: note\n", 1)
    check("stat-edit-same-length", edited != raw and len(edited) == len(raw))
    target.write_bytes(edited)
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
    after_fp = cheap_fingerprint(alpha, schema, eligible_paths(alpha, schema))
    check("stat-fingerprint-unchanged", before_fp == after_fp, (before_fp, after_fp))

    status = mesh_graph.status(discover(project))
    check("stat-status-stale", status.get("fresh") is False, status)
    second = mesh_graph.ensure(discover(project))
    check("stat-read-note", node_type(second, node_id) == "note", node_type(second, node_id))
    check("stat-new-generation", bool(second.generation) and second.generation != first.generation, (first.generation, second.generation))
    check("stat-rebuilt", second.rebuilt and not second.in_memory, (second.rebuilt, second.in_memory))
    check("stat-new-digest", second.mesh_digest != first.mesh_digest)
    third = mesh_graph.ensure(discover(project))
    check("stat-then-fresh", not third.rebuilt and third.generation == second.generation, (third.rebuilt, third.generation))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr2-"))
    old_root = os.environ.pop(index_location.OVERRIDE_ENV, None)
    try:
        run_build_all_roots(tmp)
        run_same_stat_edit(tmp)
    finally:
        if old_root is not None:
            os.environ[index_location.OVERRIDE_ENV] = old_root
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILURES:
        print(f"\n{len(FAILURES)} mesh review CR2 check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("\nAll mesh review CR2 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
