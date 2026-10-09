#!/usr/bin/env python3
"""Review R7 regressions.

A-C. Publishers commit under the lock's takeover guard. A publisher whose lock
   went stale and was taken over between its last ownership check and its
   write used to overwrite the new owner's result. Each test interleaves the
   takeover deterministically in that window (just after the old-style final
   ``still_owned()`` check, or just before ``owned_critical_section`` takes the
   guard) and asserts that the new owner's result survives and the old owner
   reports ``lock_lost``:
   A. nanograph ``current.json`` + pruning (test-only platform darwin-arm64,
      fake nanograph);
   B. ``atlas-mesh.json`` replace (exit 2 through the CLI);
   C. fts5 ``current.json`` + pruning, direct and through ``atlas index build``
      on a profile store.
   Plus: a held critical section blocks a takeover, which waits on the guard
   and then proceeds.
D. Freshness covers the projection inputs: a schema-only change (SCHEMA 1.0 to
   2.0, no Markdown change) makes ``atlas index show`` report stale, and
   recall, graph and nanograph rebuild with the new parse; an unrelated file
   outside the projection inputs keeps the index fresh.
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
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
TEST_CLI = ROOT / "scripts" / "testing" / "atlas_test_cli.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import (
    driver_overlay,
    graph,
    index_location,
    index_publish,
    meshfile,
    owned_lock,
    projection,
    recall_index,
)
from atlas_cli.core.drivers.nanograph import NanographDriver
from atlas_cli.core.owned_lock import OwnedLock
from atlas_cli.core.schema import load_schema
from test_drivers import make_store, write_fake
from test_graph import SCHEMA_V1

CLEAN_ENV = ("ATLAS_RECALL_ENGINE", "ATLAS_TEST_PLATFORM", "ATLAS_NANOGRAPH_BIN", "ATLAS_PLATFORM_OVERRIDE")

PAGES = {
    "a.md": "---\ntype: document\ntitle: Alpha\ncreated: 2026-10-09\n---\n\nAlpha body about ranking.\n",
    "b.md": "---\ntype: document\ntitle: Beta\ncreated: 2026-10-09\n---\n\nBeta body about ranking.\n",
}

# SCHEMA 1.0 parses this description as ">-" and relates_to as a string; 2.0
# (YAML) parses the folded description and one implements edge.
SCHEMA_PAGES = {
    "a.md": (
        "---\ntype: document\ntitle: Alpha\ncreated: 2026-10-09\n"
        "description: >-\n  quokkaword folded\n"
        "relates_to: [{path: b.md, kind: implements}]\n---\n\nAlpha body.\n"
    ),
    "b.md": "---\ntype: document\ntitle: Beta\ncreated: 2026-10-09\n---\n\nBeta body.\n",
}


def base_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in CLEAN_ENV}


def cli(*args: str, env: dict[str, str] | None = None, test_cli: bool = False) -> tuple[int, dict, str]:
    proc = subprocess.run(  # noqa: PLW1510
        [sys.executable, str(TEST_CLI if test_cli else ATLAS), *args],
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


def force_stale(path: Path) -> None:
    info = json.loads(path.read_text(encoding="utf-8"))
    info["created_at"] = time.time() - 3600
    path.write_text(json.dumps(info) + "\n", encoding="utf-8")


def owner_of(path: Path) -> str | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("owner")
    except (OSError, ValueError):
        return None


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class Interleave:
    """Run ``other`` (the new owner's publish) inside the old owner's publish window.

    The window is the old owner's ``trigger``-th successful ``still_owned()``
    call (the pre-R7 final check before its write) or, with R7, the moment just
    before its critical section takes the takeover guard, whichever comes
    first. The old owner's lock is forced stale first, so ``other`` takes it
    over. Fires once; calls made by ``other`` itself are not counted.
    """

    def __init__(self, trigger: int, other: Callable[[], Any]) -> None:
        self.trigger = trigger
        self.other = other
        self.calls = 0
        self.fired = False
        self.result: Any = None
        self.error: BaseException | None = None
        self._saved: Any = None
        self._saved_hook: Any = None

    def _fire(self, lock: OwnedLock) -> None:
        self.fired = True
        force_stale(lock.path)
        try:
            self.result = self.other()
        except BaseException as e:  # noqa: BLE001 - reported by the test
            self.error = e

    def __enter__(self) -> Interleave:
        original = OwnedLock.still_owned
        self._saved = original

        def still_owned(lock: OwnedLock) -> bool:
            owned = original(lock)
            if owned and not self.fired:
                self.calls += 1
                if self.calls == self.trigger:
                    self._fire(lock)
            return owned

        def hook(lock: OwnedLock) -> None:
            if not self.fired:
                self._fire(lock)

        OwnedLock.still_owned = still_owned  # type: ignore[method-assign]
        self._saved_hook = getattr(owned_lock, "before_critical_section", None)
        owned_lock.before_critical_section = hook
        return self

    def __exit__(self, *exc: object) -> None:
        OwnedLock.still_owned = self._saved  # type: ignore[method-assign]
        owned_lock.before_critical_section = self._saved_hook


def generation_dirs(base: Path) -> list[str]:
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))


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

    tmp = Path(tempfile.mkdtemp(prefix="atlas-r7-")).resolve()
    saved_env = dict(os.environ)
    for key in CLEAN_ENV:
        os.environ.pop(key, None)
    fake = write_fake(tmp / "nanograph")
    nano_env = {"ATLAS_TEST_PLATFORM": "darwin-arm64", "ATLAS_NANOGRAPH_BIN": str(fake)}
    try:
        # === A. nanograph pointer publication ================================
        def nanograph_publish() -> None:
            driver_overlay.set_platform_provider_for_tests(lambda: ("darwin", "arm64"))
            os.environ["ATLAS_NANOGRAPH_BIN"] = str(fake)
            try:
                store = make_store(tmp / "nano" / "kb", PAGES)
                base = NanographDriver.index_base(store)
                # An older published generation G0, which readers may still be using.
                g0 = NanographDriver().ensure_index(store, graph.load_source(store)).name

                def b_publish() -> str:
                    return NanographDriver().ensure_index(store, graph.load_source(store), force=True).name

                a_error = ""
                with Interleave(2, b_publish) as race:
                    try:
                        NanographDriver().ensure_index(store, graph.load_source(store), force=True)
                    except driver_overlay.DriverError as e:
                        a_error = str(e)
                g2 = race.result
                pointer = read_json(base / "current.json")
                check("a-nano-hook-fired", race.fired and race.error is None and isinstance(g2, str), f"{race.error!r}")
                check("a-nano-pointer-is-g2", pointer.get("generation") == g2, f"pointer={pointer.get('generation')} g2={g2}")
                check("a-nano-g2-not-pruned", bool(g2) and (base / str(g2)).is_dir(), str(generation_dirs(base)))
                check("a-nano-old-owner-lock-lost", "lock_lost" in a_error, a_error or "no error")
                check("a-nano-unpublished-g1-removed-g0-kept", generation_dirs(base) == sorted([g0, str(g2)]), str(generation_dirs(base)))
                check("a-nano-no-guard-left", not list(base.glob(".lock*")), str(sorted(p.name for p in base.iterdir())))
            finally:
                driver_overlay.reset_platform_provider()
                os.environ.pop("ATLAS_NANOGRAPH_BIN", None)

        attempt("a-nanograph", nanograph_publish)

        # === B. mesh write ownership =========================================
        def mesh_publish() -> None:
            project = tmp / "mesh"
            project.mkdir()
            ids = ("github.com/o/a", "github.com/o/b")
            start = {"version": 1, "stores": [{"id": i, "path": i.rsplit("/", 1)[1]} for i in ids]}
            fp = project / meshfile.MESH_NAME
            fp.write_text(json.dumps(start, indent=2) + "\n", encoding="utf-8")
            new_row = {"id": "github.com/o/c", "path": "c"}

            # Direct API.
            a_error: BaseException | None = None
            with Interleave(1, lambda: meshfile.upsert(project, new_row)) as race:
                try:
                    meshfile.set_recall_engine(project, ids[0], "bm25")
                except meshfile.MeshFileError as e:
                    a_error = e
            doc = read_json(fp)
            rows = {r["id"]: r for r in doc.get("stores") or []}
            check("b-mesh-hook-fired", race.fired and race.error is None, f"{race.error!r}")
            check("b-mesh-keeps-new-owner-change", "github.com/o/c" in rows, json.dumps(doc))
            check("b-mesh-old-owner-not-written", "recall" not in rows.get(ids[0], {}), json.dumps(doc))
            check("b-mesh-old-owner-error", a_error is not None and "lock_lost" in str(a_error), repr(a_error))

            # CLI: exit 2 with a clear message.
            from atlas_cli.commands import index as index_cmd

            fp.write_text(json.dumps(start, indent=2) + "\n", encoding="utf-8")
            buf = io.StringIO()
            with Interleave(1, lambda: meshfile.upsert(project, new_row)) as race, contextlib.redirect_stdout(buf):
                code = index_cmd.run_set("grep", str(project), ids[0], False, False, True)
            payload = json.loads(buf.getvalue() or "{}")
            doc = read_json(fp)
            rows = {r["id"]: r for r in doc.get("stores") or []}
            check("b-mesh-cli-exit-2", code == 2 and "lock_lost" in str(payload.get("error")), buf.getvalue()[-300:])
            check("b-mesh-cli-keeps-new-owner-change", "github.com/o/c" in rows and "recall" not in rows.get(ids[0], {}), json.dumps(doc))
            check("b-mesh-no-lock-left", not list(project.glob("atlas-mesh.json.lock*")), str(sorted(p.name for p in project.iterdir())))

        attempt("b-mesh", mesh_publish)

        # === C. fts5 pointer publication ======================================
        def fts5_publish() -> None:
            store = make_store(tmp / "fts" / "kb", PAGES)
            schema, _ = load_schema(store)
            root = recall_index.index_root(store)
            # An older published generation, so pruning has something to consider.
            g0 = str(recall_index.ensure_fresh(store, schema, allow_legacy=False, force=True).generation.pointer["generation"])

            def b_publish() -> str:
                fresh = recall_index.ensure_fresh(store, schema, allow_legacy=False, force=True)
                return str(fresh.generation.pointer["generation"])

            a_error: BaseException | None = None
            with Interleave(2, b_publish) as race:
                try:
                    recall_index.ensure_fresh(store, schema, allow_legacy=False, force=True)
                except index_publish.IndexBusy as e:
                    a_error = e
            g2 = race.result
            pointer = read_json(root / "current.json")
            gens = generation_dirs(root / "generations")
            check("c-fts5-hook-fired", race.fired and race.error is None and isinstance(g2, str), f"{race.error!r}")
            check("c-fts5-pointer-is-g2", pointer.get("generation") == g2, f"pointer={pointer.get('generation')} g2={g2}")
            check("c-fts5-g2-not-pruned", bool(g2) and g2 in gens, str(gens))
            check("c-fts5-old-owner-lock-lost", getattr(a_error, "code", None) == "lock_lost", repr(a_error))
            check("c-fts5-unpublished-g1-removed-g0-kept", gens == sorted([g0, str(g2)]), str(gens))
            check("c-fts5-no-temp-left", not [p.name for p in root.iterdir() if p.name.startswith(".tmp-")], str(sorted(p.name for p in root.iterdir())))

        attempt("c-fts5", fts5_publish)

        def fts5_profile_build() -> None:
            from atlas_cli.commands import index as index_cmd

            store = tmp / "profile" / "kb"
            cli("init", "--root", str(store), "--schema-version", "2.0", "--json")
            for rel, text in PAGES.items():
                (store / rel).write_text(text, encoding="utf-8")
            code, _, out = cli("recall", "activate", "--profile", "atlas:ranked", "--root", str(store), "--json")
            check("c-profile-activated", code == 0, out[-300:])

            def ref() -> Any:
                return index_cmd._root_store(index_cmd.locate(str(store)), need_row=False)

            def b_publish() -> str:
                return str(index_cmd.build_store(ref(), force=True).get("generation"))

            with Interleave(2, b_publish) as race:
                res = index_cmd.build_store(ref(), force=True)
            root = recall_index.index_root(store)
            pointer = read_json(root / "current.json")
            g2 = race.result
            check("c-profile-hook-fired", race.fired and race.error is None, f"{race.error!r}")
            check("c-profile-pointer-is-g2", bool(g2) and pointer.get("generation") == g2, f"pointer={pointer.get('generation')} g2={g2}")
            check("c-profile-g2-not-pruned", bool(g2) and g2 in generation_dirs(root / "generations"))
            check(
                "c-profile-build-reports-lock-lost",
                res.get("status") == "failed" and "lock_lost" in str(res.get("error")),
                json.dumps(res)[:400],
            )

        attempt("c-fts5-profile", fts5_profile_build)

        def critical_section_blocks_takeover() -> None:
            parent = tmp / "cs"
            x = OwnedLock(parent, "x.lock", 600)
            check("cs-x-acquires", x.try_acquire())
            entered = threading.Event()
            state: dict[str, Any] = {}

            def hold() -> None:
                try:
                    with x.owned_critical_section():
                        entered.set()
                        time.sleep(0.6)
                        state["owner_during"] = owner_of(x.path)
                    state["ok"] = True
                except Exception as e:  # noqa: BLE001
                    state["error"] = e
                    entered.set()

            t = threading.Thread(target=hold)
            t.start()
            entered.wait(5)
            force_stale(x.path)
            y = OwnedLock(parent, "x.lock", 600)
            started = time.monotonic()
            got = y.try_acquire()
            waited = time.monotonic() - started
            t.join(10)
            check("cs-section-completes", state.get("ok") is True and state.get("owner_during") == x.owner, str(state))
            check("cs-takeover-waited-then-proceeded", got and waited >= 0.4 and owner_of(x.path) == y.owner, f"got={got} waited={waited:.2f}")
            try:
                with x.owned_critical_section():
                    entered_after = True
            except owned_lock.OwnershipLost:
                entered_after = False
            check("cs-old-owner-refused", not entered_after and x.lost)
            check("cs-new-owner-enters", _enters(y))
            check("cs-release", y.release() and sorted(p.name for p in parent.iterdir()) == [], str(list(parent.iterdir())))

        def _enters(lock: OwnedLock) -> bool:
            try:
                with lock.owned_critical_section():
                    return True
            except owned_lock.OwnershipLost:
                return False

        attempt("cs-blocks-takeover", critical_section_blocks_takeover)

        # === D. schema-aware freshness ========================================
        def schema_only_change() -> None:
            store = make_store(tmp / "schema" / "kb", SCHEMA_PAGES)
            env = {"ATLAS_RECALL_ENGINE": "bm25"}
            schema1, _ = load_schema(store)
            d1 = projection.content_digest(store, schema1)
            check("d-digest-matches-projection", d1 == projection.project_store(store, schema1)["corpus_digest"])
            check("d-projection-version", isinstance(getattr(projection, "PROJECTION_VERSION", None), int))

            code, p, out = cli("recall", "run", "quokkaword", "--root", str(store), "--json", env=env)
            check("d-v1-no-hit", code == 0 and not p.get("hits"), out[-300:])
            code, p, out = cli("index", "show", "--root", str(store), "--json", env=env)
            idx = p.get("index") or {}
            gen1 = idx.get("generation")
            check("d-show-fresh-v1", idx.get("freshness") == "fresh" and gen1, out[-300:])
            code, p, out = cli("graph", "edges", "--from", "a.md", "--root", str(store), "--json")
            check("d-graph-v1-no-edge", code == 0 and not p.get("edges"), out[-300:])

            # Schema-only change: no Markdown file touched.
            pages_before = {r: (store / r).read_bytes() for r in SCHEMA_PAGES}
            (store / "SCHEMA.json").write_text(json.dumps({**SCHEMA_V1, "schema_version": "2.0"}, indent=2) + "\n", encoding="utf-8")
            schema2, _ = load_schema(store)
            check("d-digest-changes", projection.content_digest(store, schema2) != d1)
            code, p, out = cli("index", "show", "--root", str(store), "--json", env=env)
            check("d-show-stale-after-schema-change", (p.get("index") or {}).get("freshness") == "stale", out[-300:])
            code, p, out = cli("recall", "run", "quokkaword", "--root", str(store), "--json", env=env)
            check("d-recall-new-parse", code == 0 and [h.get("path") for h in p.get("hits") or []] == ["a.md"], out[-400:])
            code, p, out = cli("index", "show", "--root", str(store), "--json", env=env)
            idx = p.get("index") or {}
            gen2 = idx.get("generation")
            check("d-recall-rebuilt", idx.get("freshness") == "fresh" and gen2 and gen2 != gen1, out[-300:])
            code, p, out = cli("graph", "edges", "--from", "a.md", "--root", str(store), "--json")
            edges = [(e.get("to"), e.get("kind")) for e in p.get("edges") or []]
            check("d-graph-new-parse", code == 0 and edges == [("b.md", "implements")], out[-400:])
            check("d-pages-untouched", all((store / r).read_bytes() == b for r, b in pages_before.items()))

            # Files outside the projection inputs do not mark the index stale.
            (store / "notes.txt").write_text("not a page\n", encoding="utf-8")
            (store / "templates").mkdir(exist_ok=True)
            (store / "templates" / "extra.md").write_text("# template\n", encoding="utf-8")
            code, p, out = cli("index", "show", "--root", str(store), "--json", env=env)
            idx = p.get("index") or {}
            check("d-unrelated-change-still-fresh", idx.get("freshness") == "fresh" and idx.get("generation") == gen2, out[-300:])
            cli("recall", "run", "quokkaword", "--root", str(store), "--json", env=env)
            code, p, out = cli("index", "show", "--root", str(store), "--json", env=env)
            check("d-unrelated-change-no-rebuild", (p.get("index") or {}).get("generation") == gen2, out[-300:])

        attempt("d-schema-only", schema_only_change)

        def schema_only_change_nanograph() -> None:
            store = make_store(tmp / "schema-nano" / "kb", SCHEMA_PAGES)
            env = {**nano_env, "ATLAS_RECALL_ENGINE": "nanograph"}
            code, p, out = cli("recall", "run", "quokkaword", "--engine", "nanograph", "--root", str(store), "--json", env=env, test_cli=True)
            check("d-nano-built-v1", code == 0 and p.get("engine_used") == "nanograph", out[-300:])
            code, p, out = cli("index", "show", "--root", str(store), "--json", env=env, test_cli=True)
            idx = p.get("index") or {}
            gen1 = idx.get("generation")
            check("d-nano-show-fresh-v1", idx.get("freshness") == "fresh" and gen1, out[-300:])

            (store / "SCHEMA.json").write_text(json.dumps({**SCHEMA_V1, "schema_version": "2.0"}, indent=2) + "\n", encoding="utf-8")
            code, p, out = cli("index", "show", "--root", str(store), "--json", env=env, test_cli=True)
            check("d-nano-show-stale", (p.get("index") or {}).get("freshness") == "stale", out[-300:])
            code, p, out = cli("recall", "run", "quokkaword", "--engine", "nanograph", "--root", str(store), "--json", env=env, test_cli=True)
            check(
                "d-nano-recall-new-parse",
                code == 0 and p.get("engine_used") == "nanograph" and "a.md" in [h.get("path") for h in p.get("hits") or []],
                out[-400:],
            )
            code, p, out = cli("index", "show", "--root", str(store), "--json", env=env, test_cli=True)
            idx = p.get("index") or {}
            check("d-nano-rebuilt", idx.get("freshness") == "fresh" and idx.get("generation") not in (None, gen1), out[-300:])
            code, p, out = cli("graph", "neighbours", "a.md", "--driver", "nanograph", "--root", str(store), "--json", env=env, test_cli=True)
            check(
                "d-nano-graph-new-parse",
                code == 0 and p.get("driver_used") == "nanograph" and "b.md" in [n.get("path") for n in p.get("nodes") or []],
                out[-400:],
            )

        attempt("d-schema-only-nanograph", schema_only_change_nanograph)
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} review R7 check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll review R7 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
