#!/usr/bin/env python3
"""Review R4 regressions.

1. Freshness is decided by the content digest: a same-length edit whose
   mtime is restored is never served from a stale fts5, legacy or nanograph
   generation, and ``atlas index show`` reports it stale until rebuilt.
2. ``graph neighbours`` / ``graph edges --from/--to`` refuse an exit-state
   starting page (exit 2) unless ``--include-exits`` is passed, on the native
   and nanograph paths.
3. A failing ignore guard (read-only ``info/exclude``, ``info`` as a file) is
   a reported warning that never changes exit codes; show/status report the
   ignore state.
4. Mesh writes are serialised by ``atlas-mesh.json.lock``: no lost updates,
   stale locks are taken over and a held lock times out with exit 2.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
TEST_CLI = ROOT / "scripts" / "testing" / "atlas_test_cli.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, meshfile, projection  # noqa: E402
from atlas_cli.core.schema import load_schema  # noqa: E402
from test_drivers import write_fake  # noqa: E402
from test_graph import PAGES as GRAPH_PAGES  # noqa: E402
from test_graph import SCHEMA_V1  # noqa: E402

CLEAN_ENV = ("ATLAS_RECALL_ENGINE", "ATLAS_TEST_PLATFORM", "ATLAS_NANOGRAPH_BIN", "ATLAS_PLATFORM_OVERRIDE")

PAGES = {
    "index.md": "# Store\n\n- notes\n",
    "notes/index.md": "# Notes\n\n- a\n- bbb\n- ccc\n",
    "notes/a.md": (
        "---\ntype: decision\ntitle: Alpha page\ncreated: 2026-09-09\n"
        "relates_to:\n  - path: notes/bbb.md\n    kind: related\n---\n\n"
        "## Claim\n\nThe body mentions oldword once for recall.\n"
    ),
    "notes/bbb.md": (
        "---\ntype: decision\ntitle: Bee page\ncreated: 2026-09-09\n---\n\n"
        "## Claim\n\nThe bee page records a decision about hive placement for testing.\n"
    ),
    "notes/ccc.md": (
        "---\ntype: decision\ntitle: Sea page\ncreated: 2026-09-09\n---\n\n"
        "## Claim\n\nThe sea page records a decision about tide tables for testing.\n"
    ),
}

EXIT_PAGES = {
    **GRAPH_PAGES,
    "old/sup.md": (
        "---\ntype: decision\ntitle: Superseded\ncreated: 2026-09-09\nstatus: superseded\n"
        "relates_to:\n  - path: work/hub.md\n    kind: implements\n---\n\nSuperseded.\n"
    ),
    "old/dep.md": (
        "---\ntype: decision\ntitle: Deprecated\ncreated: 2026-09-09\nkva: deprecated\n"
        "relates_to:\n  - path: work/hub.md\n    kind: implements\n---\n\nDeprecated.\n"
    ),
}


def base_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in CLEAN_ENV}


def cli(*args: str, env: dict[str, str] | None = None, test_cli: bool = False) -> tuple[int, dict, str]:
    entry = TEST_CLI if test_cli else ATLAS
    proc = subprocess.run(
        [sys.executable, str(entry), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**base_env(), **(env or {})},
    )
    text = proc.stdout.strip()
    try:
        data = json.loads(text) if text.startswith("{") else {}
    except json.JSONDecodeError:
        data = {}
    return proc.returncode, data, proc.stdout + proc.stderr


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)


def write_pages(store: Path, pages: dict[str, str]) -> None:
    for rel, text in pages.items():
        path = store / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def make_v1(store: Path, pages: dict[str, str] = PAGES) -> Path:
    store.mkdir(parents=True)
    (store / "SCHEMA.json").write_text(json.dumps(SCHEMA_V1, indent=2) + "\n", encoding="utf-8")
    write_pages(store, pages)
    return store


def make_profile(store: Path) -> Path:
    cli("init", "--root", str(store), "--schema-version", "2.0", "--json")
    write_pages(store, PAGES)
    cli("recall", "activate", "--profile", "atlas:ranked", "--root", str(store), "--json")
    return store


def same_size_edit(path: Path, old: str, new: str) -> bool:
    """Replace ``old`` with ``new`` (equal length) and restore the original mtime."""
    assert len(old) == len(new)
    st = path.stat()
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    after = path.stat()
    return after.st_size == st.st_size and after.st_mtime_ns == st.st_mtime_ns


def fingerprint(store: Path) -> str:
    schema, _ = load_schema(store)
    return projection.cheap_fingerprint(store, schema)


def hit_paths(payload: dict) -> list[str]:
    return [h.get("path") for h in payload.get("hits") or []]


def codes(items: Any) -> list[str]:
    return [str(i.get("code") or i.get("id")) for i in items or [] if isinstance(i, dict)]


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    def attempt(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - a crash is a failure of this section
            check(name, False, f"{type(e).__name__}: {e}")

    tmp = Path(tempfile.mkdtemp(prefix="atlas-r4-"))
    saved_env = dict(os.environ)
    fake = write_fake(tmp / "nanograph")
    nano_env = {"ATLAS_TEST_PLATFORM": "darwin-arm64", "ATLAS_NANOGRAPH_BIN": str(fake)}
    try:
        # === 1. content-digest freshness ======================================
        def freshness_profile() -> None:
            store = make_profile(tmp / "fresh-profile")
            code, p, out = cli("compile", "--root", str(store), "--json")
            check("f1-compile-built", code in (0, 1) and (p.get("recall_index") or {}).get("published") is True, out[-400:])
            code, p, out = cli("index", "show", "--root", str(store), "--json")
            check("f1-show-fresh-after-build", (p.get("index") or {}).get("freshness") == "fresh", out[-400:])
            code, p, out = cli("graph", "edges", "--from", "notes/a.md", "--root", str(store), "--json")
            check("f1-graph-before", [e["to"] for e in p.get("edges") or []] == ["notes/bbb.md"] and p.get("fast_path") is True, out[-400:])
            fp_before = fingerprint(store)
            page = store / "notes" / "a.md"
            ok = same_size_edit(page, "oldword", "newword") and same_size_edit(page, "notes/bbb.md", "notes/ccc.md")
            ok = same_size_edit(page, "Alpha page", "Omega page") and ok
            check("f1-edit-keeps-size-and-mtime", ok and fingerprint(store) == fp_before)
            code, p, out = cli("index", "show", "--root", str(store), "--json")
            check("f1-show-stale-before-recall", (p.get("index") or {}).get("freshness") == "stale", out[-400:])
            code, p, out = cli("graph", "edges", "--from", "notes/a.md", "--root", str(store), "--json")
            check("f1-graph-edges-reflect-edit", code == 0 and [e["to"] for e in p.get("edges") or []] == ["notes/ccc.md"], out[-400:])
            code, p, out = cli("graph", "nodes", "--path", "notes/a.md", "--root", str(store), "--json")
            titles = [n.get("title") for n in p.get("nodes") or []]
            check("f1-graph-nodes-reflect-edit", code == 0 and titles == ["Omega page"], out[-400:])
            code, p, out = cli("recall", "run", "newword", "--root", str(store), "--json")
            check("f1-recall-finds-new-text", code == 0 and "notes/a.md" in hit_paths(p), out[-600:])
            code, p, out = cli("recall", "run", "oldword", "--root", str(store), "--json")
            check("f1-recall-drops-old-text", code == 0 and "notes/a.md" not in hit_paths(p), out[-600:])
            code, p, out = cli("index", "show", "--root", str(store), "--json")
            check("f1-show-fresh-after-recall", (p.get("index") or {}).get("freshness") == "fresh", out[-400:])
            code, p, out = cli("recall", "run", "newword", "--root", str(store), "--json")
            check("f1-warm-fast-path-again", (p.get("recall") or {}).get("fast_path") is True and "notes/a.md" in hit_paths(p), out[-400:])

        attempt("f1-profile", freshness_profile)

        def freshness_bm25_engine() -> None:
            store = make_v1(tmp / "fresh-bm25")
            code, p, out = cli("recall", "run", "oldword", "--engine", "bm25", "--root", str(store), "--json")
            check("f2-bm25-built", code == 0 and "notes/a.md" in hit_paths(p), out[-400:])
            fp_before = fingerprint(store)
            check("f2-edit", same_size_edit(store / "notes" / "a.md", "oldword", "newword") and fingerprint(store) == fp_before)
            code, p, out = cli("recall", "run", "newword", "--engine", "bm25", "--root", str(store), "--json")
            check("f2-bm25-finds-new-text", code == 0 and "notes/a.md" in hit_paths(p), out[-400:])
            code, p, out = cli("recall", "run", "oldword", "--engine", "bm25", "--root", str(store), "--json")
            check("f2-bm25-drops-old-text", "notes/a.md" not in hit_paths(p), out[-400:])

        attempt("f2-bm25", freshness_bm25_engine)

        def freshness_legacy() -> None:
            store = make_v1(tmp / "fresh-legacy")
            cli("recall", "run", "oldword", "--engine", "bm25", "--root", str(store), "--json")
            new = index_location.index_dir(store, "fts5")
            legacy = store / ".atlas-index" / "recall"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(new), str(legacy))
            pointer = json.loads((legacy / "current.json").read_text(encoding="utf-8"))
            pointer["db"] = f".atlas-index/recall/{pointer['db']}"
            (legacy / "current.json").write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
            code, p, out = cli("graph", "edges", "--from", "notes/a.md", "--root", str(store), "--json")
            check("f3-legacy-fast-path-used", p.get("fast_path") is True, out[-400:])
            fp_before = fingerprint(store)
            check("f3-edit", same_size_edit(store / "notes" / "a.md", "notes/bbb.md", "notes/ccc.md") and fingerprint(store) == fp_before)
            code, p, out = cli("graph", "edges", "--from", "notes/a.md", "--root", str(store), "--json")
            check("f3-legacy-not-reused-when-stale", [e["to"] for e in p.get("edges") or []] == ["notes/ccc.md"], out[-400:])

        attempt("f3-legacy", freshness_legacy)

        def freshness_nanograph() -> None:
            store = make_v1(tmp / "fresh-nano")
            env = {**nano_env, "ATLAS_RECALL_ENGINE": "nanograph"}
            code, p, out = cli("recall", "run", "oldword", "--engine", "bm25", "--root", str(store), "--json", env=env, test_cli=True)
            check("f4-fts5-built", code == 0, out[-400:])
            code, p, out = cli("recall", "run", "oldword", "--engine", "nanograph", "--root", str(store), "--json", env=env, test_cli=True)
            first_gen = (p.get("nanograph_index") or {}).get("generation")
            check("f4-nanograph-built", p.get("engine_used") == "nanograph" and "notes/a.md" in hit_paths(p), out[-400:])
            code, p, out = cli("index", "show", "--root", str(store), "--json", env=env, test_cli=True)
            check("f4-show-fresh", (p.get("index") or {}).get("freshness") == "fresh", out[-400:])
            fp_before = fingerprint(store)
            check("f4-edit", same_size_edit(store / "notes" / "a.md", "oldword", "newword") and fingerprint(store) == fp_before)
            code, p, out = cli("index", "show", "--root", str(store), "--json", env=env, test_cli=True)
            check("f4-show-stale", (p.get("index") or {}).get("freshness") == "stale", out[-400:])
            code, p, out = cli("recall", "run", "newword", "--engine", "nanograph", "--root", str(store), "--json", env=env, test_cli=True)
            nano = p.get("nanograph_index") or {}
            check(
                "f4-nanograph-rebuilds",
                p.get("engine_used") == "nanograph"
                and "notes/a.md" in hit_paths(p)
                and nano.get("reused") is False
                and nano.get("generation") != first_gen,
                out[-600:],
            )
            code, p, out = cli("index", "show", "--root", str(store), "--json", env=env, test_cli=True)
            check("f4-show-fresh-after", (p.get("index") or {}).get("freshness") == "fresh", out[-400:])

        attempt("f4-nanograph", freshness_nanograph)

        # === 2. exit-state starting page ======================================
        def exit_seeds() -> None:
            store = make_v1(tmp / "exits", EXIT_PAGES)
            r = str(store)
            for seed, state in (("old/dead.md", "terminated"), ("old/sup.md", "superseded"), ("old/dep.md", "deprecated")):
                code, p, out = cli("graph", "neighbours", seed, "--root", r, "--json")
                want = f"starting page {seed} is in exit state {state}; pass --include-exits to traverse from it"
                check(f"x-neighbours-refuses-{state}", code == 2 and p.get("error") == want, out[-400:])
                code, p, out = cli("graph", "neighbours", seed, "--include-exits", "--root", r, "--json")
                check(f"x-neighbours-include-exits-{state}", code == 0 and p.get("seed") == seed and p.get("count", 0) >= 1, out[-400:])
                code, _, out = cli("graph", "neighbours", seed, "--root", r)
                check(f"x-neighbours-text-{state}", code == 2 and want in out, out[-400:])
            code, p, out = cli("graph", "edges", "--from", "old/dead.md", "--root", r, "--json")
            check("x-edges-from-refuses", code == 2 and "starting page old/dead.md is in exit state terminated" in str(p.get("error")), out[-400:])
            code, p, out = cli("graph", "edges", "--to", "old/sup.md", "--root", r, "--json")
            check("x-edges-to-refuses", code == 2 and "page old/sup.md is in exit state superseded" in str(p.get("error")), out[-400:])
            code, p, out = cli("graph", "edges", "--from", "old/dead.md", "--include-exits", "--root", r, "--json")
            check("x-edges-from-include-exits", code == 0 and p.get("count") == 1, out[-400:])
            code, p, out = cli("graph", "edges", "--to", "work/hub.md", "--root", r, "--json")
            check("x-edges-live-to-still-hides-exits", code == 0 and not {"old/sup.md", "old/dep.md"} & {e["from"] for e in p.get("edges") or []}, out[-400:])
            log = tmp / "exit-nano.log"
            env = {**nano_env, "FAKE_NANOGRAPH_LOG": str(log)}
            code, p, out = cli("graph", "neighbours", "old/dead.md", "--driver", "nanograph", "--root", r, "--json", env=env, test_cli=True)
            calls = log.read_text(encoding="utf-8") if log.is_file() else ""
            check(
                "x-nanograph-refuses-before-dispatch",
                code == 2
                and p.get("error") == "starting page old/dead.md is in exit state terminated; pass --include-exits to traverse from it"
                and '"init"' not in calls
                and '"run"' not in calls,
                out[-400:] + calls[-300:],
            )
            code, p, out = cli("graph", "neighbours", "old/sup.md", "--driver", "nanograph", "--root", r, "--json", env=env, test_cli=True)
            check("x-nanograph-refuses-superseded", code == 2 and "exit state superseded" in str(p.get("error")), out[-400:])
            code, p, out = cli("graph", "neighbours", "old/dead.md", "--driver", "nanograph", "--include-exits", "--root", r, "--json", env=env, test_cli=True)
            check("x-nanograph-include-exits", code == 0 and p.get("driver_used") == "nanograph" and p.get("count", 0) >= 1, out[-400:])

        attempt("x-exit-seeds", exit_seeds)

        # === 3. ignore guard failures =========================================
        def ignore_failures() -> None:
            if shutil.which("git") is None:
                print("  [SKIP] git missing; ignore guard failure checks skipped")
                return
            control = tmp / "ig-control"
            control.mkdir()
            git(control, "init", "-q")
            make_profile(control / "kb")
            ccode, cp, cout = cli("compile", "--root", str(control / "kb"), "--json")
            check("ig-control-compile-exit-0", ccode == 0, cout[-600:])

            def assert_failed_run(label: str, repo: Path, exclude_desc: str) -> None:
                store = repo / "kb"
                code, p, out = cli("compile", "--root", str(store), "--json")
                warns = p.get("warnings") or []
                item = next((w for w in warns if w.get("code") == "atlas_indexes_ignore_failed"), {})
                check(f"ig-{label}-compile-exit-unchanged", code == ccode, out[-600:])
                check(
                    f"ig-{label}-compile-warning",
                    item.get("level") == "warning"
                    and str(item.get("message", "")).startswith("could not add /.atlas/indexes/ to ")
                    and str(item.get("message", "")).endswith(
                        "; add it to .gitignore or info/exclude yourself to keep derived indexes out of commits"
                    ),
                    json.dumps(warns)[:600],
                )
                check(f"ig-{label}-legacy-warning", "atlas_index_ignore_failed" in codes(warns), json.dumps(warns)[:600])
                check(f"ig-{label}-not-reported-added", "atlas_indexes_ignored" not in codes(p.get("info")), json.dumps(p.get("info"))[:300])
                built = repo / ".atlas" / "indexes" / "fts5"
                check(f"ig-{label}-index-built", any(built.rglob("current.json")), exclude_desc)
                code, p, out = cli("index", "show", "--root", str(store), "--json")
                ig = p.get("ignore") or {}
                check(f"ig-{label}-show-reports", code == 0 and ig.get("status") in ("missing", "failed") and ig.get("reason"), out[-400:])
                code, _, out = cli("index", "show", "--root", str(store))
                check(f"ig-{label}-show-text", code == 0 and "ignore: missing" in out or "ignore: failed" in out, out[-400:])
                code, p, out = cli("index", "status", "--root", str(store), "--json")
                ig = p.get("ignore") or {}
                check(f"ig-{label}-status-reports", code == 0 and ig.get("status") in ("missing", "failed"), out[-400:])
                code, p, out = cli("index", "build", "--root", str(store), "--json")
                check(f"ig-{label}-index-build-warning", code == 0 and "atlas_indexes_ignore_failed" in codes(p.get("warnings")), out[-600:])
                shutil.rmtree(repo / ".atlas" / "indexes")
                code, p, out = cli("recall", "run", "oldword", "--root", str(store), "--json")
                check(f"ig-{label}-recall-autocreate-warning", code == 0 and "atlas_indexes_ignore_failed" in codes(p.get("warnings")), out[-600:])

            if os.geteuid() == 0:
                print("  [SKIP] running as root: chmod does not stop writes; read-only info/exclude checks skipped")
            else:
                repo = tmp / "ig-readonly"
                repo.mkdir()
                git(repo, "init", "-q")
                make_profile(repo / "kb")
                exclude = repo / ".git" / "info" / "exclude"
                exclude.parent.mkdir(parents=True, exist_ok=True)
                if not exclude.exists():
                    exclude.write_text("# local\n", encoding="utf-8")
                exclude.chmod(0o444)
                try:
                    assert_failed_run("readonly", repo, "info/exclude 0444")
                    log = tmp / "ig-nano.log"
                    env = {**nano_env, "FAKE_NANOGRAPH_LOG": str(log), "ATLAS_RECALL_ENGINE": "nanograph"}
                    v1 = make_v1(repo / "v1")
                    code, p, out = cli("index", "build", "--root", str(v1), "--json", env=env, test_cli=True)
                    check(
                        "ig-readonly-nanograph-build-warning",
                        code == 0 and p.get("status") == "built" and "atlas_indexes_ignore_failed" in codes(p.get("warnings")),
                        out[-600:],
                    )
                finally:
                    exclude.chmod(0o644)
                code, p, out = cli("compile", "--root", str(repo / "kb"), "--json")
                lines = exclude.read_text(encoding="utf-8").splitlines()
                check(
                    "ig-restored-adds-line",
                    code == ccode and "/.atlas/indexes/" in lines and "atlas_indexes_ignored" in codes(p.get("info"))
                    and "atlas_indexes_ignore_failed" not in codes(p.get("warnings")),
                    out[-400:],
                )
                code, p, out = cli("index", "show", "--root", str(repo / "kb"), "--json")
                check("ig-restored-show-ok", (p.get("ignore") or {}).get("status") == "ok", out[-400:])
                code, p, out = cli("index", "status", "--root", str(repo / "kb"), "--json")
                check("ig-restored-status-ok", (p.get("ignore") or {}).get("status") == "ok", out[-400:])

            repo = tmp / "ig-infofile"
            repo.mkdir()
            git(repo, "init", "-q")
            make_profile(repo / "kb")
            info_dir = repo / ".git" / "info"
            if info_dir.is_dir():
                shutil.rmtree(info_dir)
            info_dir.write_text("not a directory\n", encoding="utf-8")
            assert_failed_run("infofile", repo, "info is a file")

        attempt("ig-failures", ignore_failures)

        # === 4. locked mesh writes ============================================
        def mesh_locking() -> None:
            project = tmp / "mesh-project"
            project.mkdir()
            ids = ("github.com/o/a", "github.com/o/b")
            start = {"version": 1, "stores": [{"id": i, "path": i.rsplit("/", 1)[1]} for i in ids]}
            original = meshfile.validate_doc

            def slow_validate(*args: Any, **kwargs: Any) -> list[str]:
                time.sleep(0.03)
                return original(*args, **kwargs)

            lost: list[str] = []
            meshfile.validate_doc = slow_validate
            try:
                for rnd in range(6):
                    (project / meshfile.MESH_NAME).write_text(json.dumps(start, indent=2) + "\n", encoding="utf-8")
                    barrier = threading.Barrier(3)
                    errors: list[str] = []

                    def go(fn: Callable[[], Any]) -> None:
                        barrier.wait()
                        try:
                            fn()
                        except Exception as e:  # noqa: BLE001
                            errors.append(f"{type(e).__name__}: {e}")

                    threads = [
                        threading.Thread(target=go, args=(lambda: meshfile.set_recall_engine(project, ids[0], "bm25"),)),
                        threading.Thread(target=go, args=(lambda: meshfile.set_recall_engine(project, ids[1], "grep"),)),
                        threading.Thread(target=go, args=(lambda: meshfile.upsert(project, {"id": "github.com/o/c", "path": "c"}),)),
                    ]
                    for t in threads:
                        t.start()
                    for t in threads:
                        t.join()
                    doc = json.loads((project / meshfile.MESH_NAME).read_text(encoding="utf-8"))
                    rows = {r["id"]: r for r in doc["stores"]}
                    ok = (
                        not errors
                        and (rows.get(ids[0], {}).get("recall") or {}).get("engine") == "bm25"
                        and (rows.get(ids[1], {}).get("recall") or {}).get("engine") == "grep"
                        and "github.com/o/c" in rows
                    )
                    if not ok:
                        lost.append(f"round {rnd}: {errors} {json.dumps(doc)}")
            finally:
                meshfile.validate_doc = original
            check("mesh-concurrent-writers-no-lost-update", not lost, "; ".join(lost)[:600])
            lock = project / "atlas-mesh.json.lock"
            check("mesh-lock-released", not lock.exists() and not list(project.glob(".atlas-mesh.json.*.tmp")))

            # stale lock: old created_at, dead pid on this host
            lock.write_text(
                json.dumps({"owner": "stale", "pid": 999999, "host": socket.gethostname(), "created_at": time.time() - 3600}) + "\n",
                encoding="utf-8",
            )
            res = meshfile.set_recall_engine(project, ids[0], "nanograph")
            doc = json.loads((project / meshfile.MESH_NAME).read_text(encoding="utf-8"))
            check(
                "mesh-stale-lock-taken-over",
                res.changed and doc["stores"][0]["recall"]["engine"] == "nanograph" and not lock.exists(),
            )

            # fresh lock held by a live process: wait, then time out (exit 2)
            held = {"owner": "other", "pid": os.getpid(), "host": socket.gethostname(), "created_at": time.time()}
            lock.write_text(json.dumps(held) + "\n", encoding="utf-8")
            before = (project / meshfile.MESH_NAME).read_bytes()
            saved_wait = meshfile.MESH_LOCK_WAIT_SECONDS
            meshfile.MESH_LOCK_WAIT_SECONDS = 0.6
            try:
                t0 = time.monotonic()
                try:
                    meshfile.set_recall_engine(project, ids[0], "grep")
                    raised = None
                except meshfile.MeshFileError as e:
                    raised = e
                waited = time.monotonic() - t0
                check(
                    "mesh-held-lock-times-out",
                    isinstance(raised, meshfile.MeshLockTimeout) and waited >= 0.5 and "atlas-mesh.json.lock" in str(raised),
                    f"{raised!r} waited={waited:.2f}",
                )
                check("mesh-held-lock-no-write", (project / meshfile.MESH_NAME).read_bytes() == before)
                from atlas_cli.commands import index as index_cmd

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = index_cmd.run_set("grep", str(project), ids[0], False, False, True)
                payload = json.loads(buf.getvalue() or "{}")
                check("mesh-held-lock-cli-exit-2", code == 2 and "atlas-mesh.json.lock" in str(payload.get("error")), buf.getvalue()[-300:])
                check("mesh-held-lock-cli-no-write", (project / meshfile.MESH_NAME).read_bytes() == before)

                # a writer that waits succeeds once the holder releases
                meshfile.MESH_LOCK_WAIT_SECONDS = 5.0
                timer = threading.Timer(0.3, lambda: lock.unlink())
                timer.start()
                t0 = time.monotonic()
                res = meshfile.set_recall_engine(project, ids[0], "grep")
                timer.join()
                check("mesh-waits-then-writes", res.changed and time.monotonic() - t0 >= 0.25 and not lock.exists())
            finally:
                meshfile.MESH_LOCK_WAIT_SECONDS = saved_wait
                lock.unlink(missing_ok=True)

            # formatting is still preserved under the lock
            fmt = tmp / "mesh-format"
            fmt.mkdir()
            text = json.dumps({"stores": [{"path": "a", "id": ids[0], "ref": "main"}], "version": 1}, indent="\t")
            (fmt / meshfile.MESH_NAME).write_text(text, encoding="utf-8")
            meshfile.set_recall_engine(fmt, ids[0], "bm25")
            after = (fmt / meshfile.MESH_NAME).read_text(encoding="utf-8")
            want = json.dumps(
                {"stores": [{"path": "a", "id": ids[0], "ref": "main", "recall": {"engine": "bm25"}}], "version": 1},
                indent="\t",
            )
            check("mesh-format-preserved", after == want, repr(after))

            # the lock and temp files are kept out of commits by the ignore guard
            if shutil.which("git"):
                repo = tmp / "mesh-git"
                repo.mkdir()
                git(repo, "init", "-q")
                (repo / meshfile.MESH_NAME).write_text(json.dumps(start, indent=2) + "\n", encoding="utf-8")
                meshfile.set_recall_engine(repo, ids[0], "bm25")
                exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
                check("mesh-lock-ignored", "/atlas-mesh.json.lock*" in exclude and "/.atlas-mesh.json.*.tmp" in exclude, str(exclude))
                (repo / "atlas-mesh.json.lock").write_text("{}\n", encoding="utf-8")
                status = git(repo, "status", "--porcelain", "--untracked-files=all").stdout
                check("mesh-lock-untracked", "atlas-mesh.json.lock" not in status, status)
                (repo / "atlas-mesh.json.lock").unlink()

        attempt("mesh-locking", mesh_locking)
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        for path in tmp.rglob("*"):
            with contextlib.suppress(OSError):
                if path.is_file() and not path.is_symlink():
                    path.chmod(path.stat().st_mode | stat.S_IWUSR)
        shutil.rmtree(tmp, ignore_errors=True)

    print("Failed:" if failed else "ok", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
