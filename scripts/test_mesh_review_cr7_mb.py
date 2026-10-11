#!/usr/bin/env python3
"""Copilot review CR7 for packet MB (native mesh graph).

``atlas index status`` in mesh mode must describe each ``ok`` member from its
classified root, not ``_ref(row)``. A pathless row is mounted at
``.atlas/<atlas-id>``; a subpath row is mounted at ``path/subpath`` and reports
that root's page count and index, not the parent store that holds it. No
``git`` subprocess and no standalone index-id fallback.

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
from atlas_cli.core import ignore_guard, index_location, recall_index  # noqa: E402
from atlas_cli.core.overlay import merge_overlays  # noqa: E402
from atlas_cli.core.projection import eligible_paths  # noqa: E402
from atlas_cli.core.schema import load_schema  # noqa: E402
from test_mesh_graph import contract, page, write  # noqa: E402

FAILURES: list[str] = []
PATHLESS = "github.com/acme/pathless"
SUB = "github.com/acme/sub"
PARENT = "github.com/acme/parent"


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if not ok and detail != "" else ""))
    if not ok:
        FAILURES.append(name)


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


def page_count(root: Path) -> int:
    """Eligible pages of a store root. A missing root counts as zero (never mounted)."""
    if not root.is_dir():
        return 0
    schema, err = load_schema(root)
    if schema is None or err:
        return 0
    merged, critical, _ = merge_overlays(schema, root)
    if critical:
        return 0
    return len(eligible_paths(root, merged))


def publish(root: Path, project: Path, sid: str) -> dict:
    """Publish this root's own fts5 index under ``.atlas/indexes/fts5/<sid>/``."""
    index_location.clear_cache()
    loc = index_location.IndexLocation(root.resolve(), project.resolve(), sid, "mesh", "mesh")
    schema, err = load_schema(root)
    if schema is None:
        return {"published": False, "error": err}
    merged, critical, _ = merge_overlays(schema, root)
    if critical:
        return {"published": False, "error": "; ".join(item["msg"] for item in critical)}
    with index_location.pinned(loc):
        return recall_index.publish_fts5(root, merged)


def index_dir(project: Path, sid: str) -> Path:
    return project / ".atlas" / "indexes" / "fts5" / Path(*sid.split("/"))


def pointer(index: Path) -> dict:
    return json.loads((index / "current.json").read_text(encoding="utf-8"))


def run(tmp: Path) -> None:
    print("mesh status describes pathless and subpath members from their own roots")
    project = tmp / "proj"
    pathless = project / ".atlas" / "github.com" / "acme" / "pathless"
    parent = project / "atlas" / "parent"
    inner = parent / "inner"
    contract(pathless, PATHLESS, "Pathless")
    write(pathless / "notes" / "only.md", page("PathlessOnly"))
    contract(parent, PARENT, "Parent")
    for name in ("p1", "p2", "p3"):
        write(parent / "notes" / f"{name}.md", page(f"Parent{name}"))
    contract(inner, SUB, "Inner")
    write(inner / "notes" / "a.md", page("InnerA"))
    write(inner / "notes" / "b.md", page("InnerB"))
    write(
        project / "atlas-mesh.json",
        json.dumps(
            {"version": 1, "stores": [{"id": PATHLESS}, {"id": SUB, "path": "atlas/parent", "subpath": "inner"}]},
            indent=2,
        )
        + "\n",
    )
    pathless_n, sub_n, parent_n = page_count(pathless), page_count(inner), page_count(parent)
    check("fixture-page-counts", pathless_n == 1 and sub_n == 2 and parent_n == 5, (pathless_n, sub_n, parent_n))

    guard_git = ignore_guard._run_git
    ignore_guard._run_git = lambda *_a, **_k: None
    published: dict[str, dict] = {}
    try:
        for sid, root in ((PATHLESS, pathless), (SUB, inner), (PARENT, parent)):
            published[sid] = publish(root, project, sid)
    finally:
        ignore_guard._run_git = guard_git
        index_location.clear_cache()
    indexes = {sid: index_dir(project, sid) for sid in (PATHLESS, SUB, PARENT)}
    generations = {}
    for sid, res in published.items():
        check(f"published-{sid.rsplit('/', 1)[-1]}", res.get("published") is True, res)
        if indexes[sid].joinpath("current.json").is_file():
            generations[sid] = pointer(indexes[sid]).get("generation")
            check(
                f"published-count-{sid.rsplit('/', 1)[-1]}",
                pointer(indexes[sid]).get("count") == page_count(root_for(sid, pathless, inner, parent)),
                pointer(indexes[sid]).get("count"),
            )
    check("published-generations-differ", len(set(generations.values())) == 3, generations)

    described: list[tuple[str, Path]] = []
    standalone: list[str] = []
    git_calls: list[list[str]] = []
    original_describe = cmd_index.describe_store
    original_standalone = index_location._standalone

    def recording_describe(ref, doc):
        described.append((ref.store_id, Path(ref.path)))
        return original_describe(ref, doc)

    def refuse_standalone(store):
        standalone.append(str(store))
        raise RuntimeError(f"_standalone refused in test: {store}")

    cmd_index.describe_store = recording_describe
    index_location._standalone = refuse_standalone
    ignore_guard._run_git = lambda *_a, **_k: None
    old_env = os.environ.get("ATLAS_RECALL_ENGINE")
    os.environ["ATLAS_RECALL_ENGINE"] = "bm25"
    buf = io.StringIO()
    code = None
    try:
        index_location.clear_cache()
        with no_git(git_calls), contextlib.redirect_stdout(buf):
            code = cmd_index.run_status(str(project), True)
    except Exception as e:  # noqa: BLE001 - reported as a failed check
        check("status-ran", False, repr(e))
    finally:
        cmd_index.describe_store = original_describe
        index_location._standalone = original_standalone
        ignore_guard._run_git = guard_git
        if old_env is None:
            os.environ.pop("ATLAS_RECALL_ENGINE", None)
        else:
            os.environ["ATLAS_RECALL_ENGINE"] = old_env
        index_location.clear_cache()
    if code is None:
        return
    try:
        out = json.loads(buf.getvalue())
    except ValueError:
        out = {}
    stores = {row.get("store_id"): row for row in out.get("stores") or []}
    check("status-exit-0", code == 0 and out.get("ok") is True, buf.getvalue()[:800])
    check("status-no-git", not git_calls, git_calls)
    check("status-no-standalone", not standalone, standalone)
    check("status-no-missing-path", not (project / ".atlas-missing-path").exists())
    check("status-two-members", set(stores) == {PATHLESS, SUB}, set(stores))

    by_id = {sid: path for sid, path in described}
    for sid, root, n, label in (
        (PATHLESS, pathless, pathless_n, "pathless"),
        (SUB, inner, sub_n, "sub"),
    ):
        row = stores.get(sid) or {}
        got = by_id.get(sid)
        counted = page_count(got) if got is not None else None
        rel = indexes[sid].relative_to(project).as_posix()
        check(f"status-mounted-{label}", row.get("mounted") is True, row.get("mounted"))
        check(f"status-root-{label}", got is not None and got.resolve() == root.resolve(), got)
        check(f"status-pages-{label}", counted == n and counted != parent_n, (counted, n, parent_n))
        check(f"status-index-{label}", row.get("index_dir") == rel, row.get("index_dir"))
        check(
            f"status-generation-{label}",
            row.get("generation") == generations.get(sid) and row.get("generation") != generations.get(PARENT),
            (row.get("generation"), generations.get(sid), generations.get(PARENT)),
        )
        check(f"status-fresh-{label}", row.get("freshness") == "fresh", row.get("freshness"))
        reported_rel = row.get("index_dir")
        reported = project / reported_rel if isinstance(reported_rel, str) else None
        reported_n = pointer(reported).get("count") if reported is not None and (reported / "current.json").is_file() else None
        check(f"status-index-pages-{label}", reported_n == n and reported_n != parent_n, (reported_n, n, parent_n))
    check("status-not-parent-index", all((stores.get(sid) or {}).get("index_dir") != indexes[PARENT].relative_to(project).as_posix() for sid in (PATHLESS, SUB)))


def root_for(sid: str, pathless: Path, inner: Path, parent: Path) -> Path:
    return {PATHLESS: pathless, SUB: inner, PARENT: parent}[sid]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr7-"))
    old_root = os.environ.pop(index_location.OVERRIDE_ENV, None)
    try:
        run(tmp)
    finally:
        if old_root is not None:
            os.environ[index_location.OVERRIDE_ENV] = old_root
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILURES:
        print(f"\n{len(FAILURES)} mesh review CR7 check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("\nAll mesh review CR7 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
