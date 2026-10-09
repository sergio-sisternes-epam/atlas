#!/usr/bin/env python3
"""Preferred recall engine: precedence, config validation, auto-created and
self-refreshing indexes, atomic publish, locks, fallback and profile stores.

Linux-safe: no network and no real nanograph (the fake binary from
test_drivers is used with ATLAS_PLATFORM_OVERRIDE=darwin-arm64).
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
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.commands import search as search_cmd  # noqa: E402
from atlas_cli.core import engine_preference, index_location, index_publish, recall_index  # noqa: E402
from atlas_cli.core.recall_config import fts5_available  # noqa: E402
from test_drivers import make_store as make_graph_store  # noqa: E402
from test_drivers import read_log, write_fake  # noqa: E402
from test_index_location import to_legacy_fts5, tree_snapshot, warning_codes  # noqa: E402
from test_recall_bm25 import as_json, make_store  # noqa: E402

STORE_ID = "github.com/acme/notes"
CLEAN_ENV = ("ATLAS_RECALL_ENGINE", "ATLAS_INDEX_ROOT", "ATLAS_PLATFORM_OVERRIDE", "ATLAS_NANOGRAPH_BIN")


def cli(*args: str, env: dict[str, str] | None = None) -> tuple[int, dict, str]:
    base = {k: v for k, v in os.environ.items() if k not in CLEAN_ENV}
    proc = subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**base, **(env or {})},
    )
    return proc.returncode, as_json(proc), proc.stdout + proc.stderr


def write_mesh(project: Path, row_recall: object = None, top_recall: object = None, rel: str = "stores/notes") -> Path:
    row: dict = {"id": STORE_ID, "path": rel}
    if row_recall is not None:
        row["recall"] = row_recall
    doc: dict = {"version": 1, "stores": [row]}
    if top_recall is not None:
        doc["recall"] = top_recall
    mesh = project / "atlas-mesh.json"
    mesh.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    index_location.clear_cache()
    return mesh


def fts_base(project: Path) -> Path:
    return project / ".atlas" / "indexes" / "fts5" / Path(*STORE_ID.split("/"))


def pointer(base: Path) -> dict:
    path = base / "current.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def generations(base: Path) -> list[str]:
    gens = base / "generations"
    return sorted(d.name for d in gens.iterdir() if d.is_dir()) if gens.is_dir() else []


def edit(store: Path, rel: str, text: str) -> None:
    path = store / rel
    body = path.read_text(encoding="utf-8")
    path.write_text(body + text, encoding="utf-8")
    later = time.time() + 2
    os.utime(path, (later, later))


@contextlib.contextmanager
def env_set(**values: str | None):
    old = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        index_location.clear_cache()
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        index_location.clear_cache()


def in_process_recall(store: Path, query: str) -> dict:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            search_cmd.run(str(store), query, as_json=True)
        except SystemExit:
            pass
    text = buf.getvalue().strip()
    return json.loads(text) if text.startswith("{") else {}


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    for key in CLEAN_ENV:
        os.environ.pop(key, None)
    tmp = Path(tempfile.mkdtemp(prefix="atlas-engine-pref-"))
    try:
        project = tmp / "proj"
        store = make_store(project / "stores" / "notes", "1.0")

        # --- precedence (one resolver) -----------------------------------------
        def resolved(cli_engine: str | None = None) -> tuple[str, str]:
            index_location.clear_cache()
            pref = engine_preference.resolve_engine(store, cli_engine)
            return pref.requested, pref.source

        write_mesh(project)
        check("default-only", resolved() == ("grep", "default"), str(resolved()))
        write_mesh(project, top_recall={"engine": "nanograph"})
        check("project-only", resolved() == ("nanograph", "project"), str(resolved()))
        write_mesh(project, row_recall={"engine": "bm25"})
        check("store-only", resolved() == ("bm25", "store"), str(resolved()))
        write_mesh(project)
        with env_set(ATLAS_RECALL_ENGINE="bm25"):
            check("env-only", resolved() == ("bm25", "env"), str(resolved()))
        check("cli-only", resolved("nanograph") == ("nanograph", "cli"), str(resolved("nanograph")))

        write_mesh(project, row_recall={"engine": "bm25"}, top_recall={"engine": "nanograph"})
        with env_set(ATLAS_RECALL_ENGINE="grep"):
            check("all-cli-wins", resolved("nanograph") == ("nanograph", "cli"))
            check("all-env-wins", resolved() == ("grep", "env"), str(resolved()))
        check("all-store-wins", resolved() == ("bm25", "store"), str(resolved()))
        write_mesh(project, top_recall={"engine": "nanograph"})
        check("project-beats-default", resolved() == ("nanograph", "project"))

        lone = make_store(tmp / "standalone", "1.0")
        index_location.clear_cache()
        pref = engine_preference.resolve_engine(lone, None)
        check("standalone-default", (pref.requested, pref.source, pref.mesh_file) == ("grep", "default", None), str(pref))
        with env_set(ATLAS_RECALL_ENGINE="bm25"):
            pref = engine_preference.resolve_engine(lone, None)
            check("standalone-env", (pref.requested, pref.source) == ("bm25", "env"), str(pref))

        # Payload fields over the CLI follow the same rule.
        write_mesh(project, row_recall={"engine": "grep"}, top_recall={"engine": "bm25"})
        code, p, out = cli("recall", "run", "ranking", "--root", str(store), "--json")
        check(
            "payload-store-source",
            code == 0 and p.get("engine_requested") == "grep" and p.get("engine_source") == "store" and p.get("engine_used") == "grep",
            out[:400],
        )
        code, p, out = cli("recall", "run", "ranking", "--root", str(store), "--json", env={"ATLAS_RECALL_ENGINE": "grep"})
        check("payload-env-source", p.get("engine_source") == "env", out[:300])
        code, p, out = cli("recall", "run", "ranking", "--root", str(store), "--engine", "grep", "--json")
        check("payload-cli-source", p.get("engine_source") == "cli" and p.get("engine_requested") == "grep", out[:300])

        # --- invalid configuration --------------------------------------------
        mesh = write_mesh(project, row_recall={"engine": "lucene"})
        code, p, out = cli("recall", "run", "ranking", "--root", str(store), "--json")
        err = str(p.get("error") or out)
        check(
            "invalid-store-row",
            code == 2 and str(mesh) in err and f"store {STORE_ID}" in err and "grep, bm25, nanograph" in err,
            out[:400],
        )
        write_mesh(project, top_recall={"engine": "Elastic"})
        code, p, out = cli("recall", "run", "ranking", "--root", str(store), "--json")
        err = str(p.get("error") or out)
        check("invalid-project-default", code == 2 and "project default" in err and "grep, bm25, nanograph" in err, out[:400])
        write_mesh(project, row_recall={"engine": "bm25", "boost": 2})
        code, p, out = cli("recall", "run", "ranking", "--root", str(store), "--json")
        err = str(p.get("error") or out)
        check("unknown-recall-key", code == 2 and "unknown key 'boost'" in err and f"store {STORE_ID}" in err, out[:400])
        write_mesh(project)
        code, p, out = cli("recall", "run", "ranking", "--root", str(store), "--json", env={"ATLAS_RECALL_ENGINE": "faiss"})
        err = str(p.get("error") or out)
        check("invalid-env", code == 2 and "ATLAS_RECALL_ENGINE" in err and "grep, bm25, nanograph" in err, out[:400])

        from atlas_cli.core import meshfile

        bad = {"version": 1, "recall": {"engine": "x"}, "stores": [{"id": STORE_ID, "path": "stores/notes"}]}
        errs = meshfile.validate_doc(bad, source="m.json")
        check("meshfile-validate-names-file", any("m.json: project default" in e for e in errs), str(errs))
        good = {"version": 1, "recall": {"engine": "bm25"}, "stores": [{"id": STORE_ID, "path": "s", "recall": {"engine": "grep"}}]}
        check("meshfile-validate-accepts", meshfile.validate_doc(good) == [], str(meshfile.validate_doc(good)))

        # Mesh without recall: unchanged behaviour (grep, nothing written).
        write_mesh(project)
        code, p, out = cli("recall", "run", "ranking", "--root", str(store), "--json")
        check(
            "no-recall-unchanged",
            code == 0 and p.get("engine_used") == "grep" and p.get("engine_source") == "default" and not (project / ".atlas").exists(),
            out[:300],
        )

        if not fts5_available():
            print("  [SKIP] sqlite3 lacks FTS5; index checks skipped")
            return 1 if failed else 0

        # --- auto-create on first recall ----------------------------------------
        write_mesh(project, row_recall={"engine": "bm25"})
        base = fts_base(project)
        code, p, out = cli("recall", "run", "ranking recall", "--root", str(store), "--json")
        gen1 = pointer(base).get("generation")
        check(
            "auto-create",
            code == 0
            and p.get("engine_used") == "sqlite-fts5"
            and p.get("engine_source") == "store"
            and p.get("ephemeral") is False
            and p.get("index_rebuilt") is True
            and bool(gen1)
            and generations(base) == [gen1]
            and p.get("generation") == gen1,
            out[:500],
        )
        check("no-lock-or-temp-left", not [c.name for c in base.iterdir() if c.name.startswith(".")], str(list(base.iterdir())))

        # --- no change -> no rebuild ---------------------------------------------
        before = tree_snapshot(base / "generations")
        code, p, out = cli("recall", "run", "ranking recall", "--root", str(store), "--json")
        check(
            "unchanged-no-rebuild",
            code == 0 and p.get("generation") == gen1 and p.get("index_rebuilt") is False and tree_snapshot(base / "generations") == before,
            out[:300],
        )

        # --- refresh on edit ----------------------------------------------------
        edit(store, "decisions/beta.md", "\nThe quokka clause applies to ranking.\n")
        code, p, out = cli("recall", "run", "quokka", "--root", str(store), "--json")
        gen2 = pointer(base).get("generation")
        check(
            "edit-rebuilds",
            code == 0
            and p.get("index_rebuilt") is True
            and gen2 not in (None, gen1)
            and [h.get("path") for h in p.get("hits") or []] == ["decisions/beta.md"],
            out[:500],
        )
        check("two-generations-kept", generations(base) == sorted([gen1, gen2]), str(generations(base)))
        edit(store, "decisions/gamma.md", "\nWombat weighting.\n")
        code, p, out = cli("recall", "run", "wombat", "--root", str(store), "--json")
        gen3 = pointer(base).get("generation")
        check(
            "old-generation-pruned",
            gen3 not in (gen1, gen2) and gen1 not in generations(base) and gen3 in generations(base) and len(generations(base)) == 2,
            str(generations(base)),
        )

        # --- compile refreshes the preferred index; exit code unchanged ----------
        control_project = tmp / "control"
        control = make_store(control_project / "stores" / "notes", "1.0")
        write_mesh(control_project)
        ccode, _, _ = cli("compile", "--root", str(control), "--json")
        edit(store, "work/hub.md", "\nNumbat checklist.\n")
        code, p, out = cli("compile", "--root", str(store), "--json")
        infos = [i for i in p.get("info") or [] if str(i.get("id", "")).startswith("preferred_index")]
        gen4 = pointer(base).get("generation")
        check(
            "compile-refreshes",
            code == ccode
            and [i.get("id") for i in infos] == ["preferred_index_refreshed"]
            and infos[0].get("driver") == "sqlite-fts5"
            and infos[0].get("generation") == gen4
            and gen4 != gen3,
            out[:600],
        )
        code, p, out = cli("compile", "--root", str(store), "--json")
        infos = [i.get("id") for i in p.get("info") or [] if str(i.get("id", "")).startswith("preferred_index")]
        check("compile-fresh-info", code == ccode and infos == ["preferred_index_fresh"], out[:400])
        code, p, out = cli("recall", "index", "build", "--root", str(store), "--json")
        check("index-build-reports", code == 0 and "preferred_index_fresh" in out, out[:400])

        # Index build failure during compile is a warning, never an error.
        blocker = tmp / "blocker"
        blocker.write_text("not a directory\n", encoding="utf-8")
        edit(store, "work/hub.md", "\nMore.\n")
        code, p, out = cli("compile", "--root", str(store), "--json", env={"ATLAS_INDEX_ROOT": str(blocker)})
        warns = [w.get("id") for w in p.get("warnings") or []]
        check("compile-index-failure-warning", code == ccode and "preferred_index_failed" in warns, out[:600])
        code, p, out = cli("recall", "run", "numbat", "--root", str(store), "--json", env={"ATLAS_INDEX_ROOT": str(blocker)})
        check(
            "unwritable-ephemeral",
            code == 0
            and p.get("engine_used") == "sqlite-fts5"
            and p.get("ephemeral") is True
            and "temporary index" in str(p.get("driver_note"))
            and bool(p.get("hits")),
            out[:500],
        )

        # --- atomic swap: crash mid-build -----------------------------------------
        cli("recall", "run", "numbat", "--root", str(store), "--json")
        good_gen = pointer(base).get("generation")
        good_dirs = generations(base)
        edit(store, "decisions/alpha.md", "\nPlatypus pending.\n")
        real_write = recall_index._write_sqlite

        def crashing(path: Path, pages, digest):  # type: ignore[no-untyped-def]
            if index_publish.TMP_PREFIX in str(path):
                path.write_bytes(b"partial sqlite")
                raise OSError("simulated crash")
            return real_write(path, pages, digest)

        recall_index._write_sqlite = crashing
        try:
            index_location.clear_cache()
            try:
                recall_index.ensure_fresh(store, json.loads((store / "SCHEMA.json").read_text(encoding="utf-8")))
                crashed = False
            except OSError:
                crashed = True
        finally:
            recall_index._write_sqlite = real_write
        check(
            "crash-keeps-pointer",
            crashed and pointer(base).get("generation") == good_gen and generations(base) == good_dirs,
            str(pointer(base)),
        )
        check("crash-temp-removed", not [c.name for c in base.iterdir() if c.name.startswith(".")], str(list(base.iterdir())))
        # A leftover temp dir from a killed process is ignored by readers and cleaned by the next builder.
        leftover = base / ".tmp-20260101T000000-deadbeef"
        leftover.mkdir()
        (leftover / recall_index.DB_NAME).write_bytes(b"half")
        code, p, out = cli("recall", "run", "platypus", "--root", str(store), "--json")
        check(
            "reader-after-crash",
            code == 0 and p.get("index_rebuilt") is True and [h.get("path") for h in p.get("hits") or []] == ["decisions/alpha.md"],
            out[:400],
        )
        check("leftover-temp-cleaned", not leftover.exists())

        # --- locks ----------------------------------------------------------------
        lock = base / index_publish.LOCK_NAME
        edit(store, "decisions/alpha.md", "\nEchidna.\n")
        lock.write_text(json.dumps({"pid": 999999, "host": "elsewhere", "created": time.time() - 3600}) + "\n", encoding="utf-8")
        code, p, out = cli("recall", "run", "echidna", "--root", str(store), "--json")
        check(
            "stale-lock-broken",
            code == 0 and p.get("index_rebuilt") is True and p.get("ephemeral") is False and not lock.exists(),
            out[:400],
        )
        edit(store, "decisions/alpha.md", "\nBilby.\n")
        held_gen = pointer(base).get("generation")
        lock.write_text(json.dumps({"pid": 999999, "host": "elsewhere", "created": time.time()}) + "\n", encoding="utf-8")
        saved_wait = index_publish.LOCK_WAIT_SECONDS
        index_publish.LOCK_WAIT_SECONDS = 0.3
        try:
            with env_set():
                busy = in_process_recall(store, "bilby")
        finally:
            index_publish.LOCK_WAIT_SECONDS = saved_wait
        check(
            "fresh-lock-ephemeral",
            busy.get("ephemeral") is True
            and "index build in progress" in str(busy.get("driver_note"))
            and [h.get("path") for h in busy.get("hits") or []] == ["decisions/alpha.md"]
            and pointer(base).get("generation") == held_gen
            and lock.exists(),
            json.dumps(busy)[:500],
        )
        lock.unlink()

        # --- atlas index show / set ---------------------------------------------
        code, p, out = cli("index", "show", "--root", str(store), "--json")
        check(
            "index-show",
            code == 0
            and p.get("engine_requested") == "bm25"
            and p.get("engine_source") == "store"
            and p.get("engine_effective") == "bm25"
            and (p.get("index") or {}).get("freshness") == "stale"
            and str((p.get("index") or {}).get("index_dir") or "").startswith(".atlas/indexes/fts5/"),
            out[:500],
        )
        snap = tree_snapshot(base)
        code, p, out = cli("index", "show", "--root", str(store))
        check("index-show-read-only", code == 0 and "bm25" in out and tree_snapshot(base) == snap, out[:300])
        code, p, out = cli("index", "set", "grep", "--default", "--root", str(store), "--json")
        doc = json.loads((project / "atlas-mesh.json").read_text(encoding="utf-8"))
        check("index-set-default", code == 0 and doc.get("recall") == {"engine": "grep"} and doc["stores"][0].get("recall") == {"engine": "bm25"}, out[:300])
        code, p, out = cli("index", "unset", "--root", str(store), "--json")
        doc = json.loads((project / "atlas-mesh.json").read_text(encoding="utf-8"))
        check("index-unset-store", code == 0 and "recall" not in doc["stores"][0], out[:300])
        code, p, out = cli("index", "show", "--root", str(store), "--json")
        check("index-show-after-set", p.get("engine_requested") == "grep" and p.get("engine_source") == "project", out[:300])
        code, p, out = cli("index", "set", "bm25", "--root", str(lone), "--json")
        check("index-set-standalone-error", code == 2 and "atlas mount" in out, out[:300])
        code, p, out = cli("recall", "engine", "--root", str(store))
        check("recall-engine-removed", code == 2 and "No such command" in out, out[:300])

        # --- nanograph preference on Linux falls back -----------------------------
        write_mesh(project, row_recall={"engine": "nanograph"})
        nano_base = project / ".atlas" / "indexes" / "nanograph"
        code, p, out = cli("recall", "run", "ranking", "--root", str(store), "--json", env={"ATLAS_PLATFORM_OVERRIDE": "linux-x86_64"})
        check(
            "linux-nanograph-fallback",
            code == 0
            and p.get("engine_requested") == "nanograph"
            and p.get("engine_used") == "sqlite-fts5"
            and p.get("driver_note") == "preferred engine nanograph unavailable: unavailable on linux-x86_64; used bm25"
            and not nano_base.exists(),
            out[:500],
        )

        # --- nanograph preference with the fake binary ----------------------------
        gproject = tmp / "gproj"
        gstore = make_graph_store(gproject / "stores" / "notes")
        write_mesh(gproject, row_recall={"engine": "nanograph"})
        fake = write_fake(tmp / "nanograph")
        log = tmp / "nano.log"
        nenv = {"ATLAS_PLATFORM_OVERRIDE": "darwin-arm64", "ATLAS_NANOGRAPH_BIN": str(fake), "FAKE_NANOGRAPH_LOG": str(log)}
        gbase = gproject / ".atlas" / "indexes" / "nanograph" / Path(*STORE_ID.split("/"))

        def builds() -> int:
            return len([e for e in read_log(log) if e["argv"][:1] == ["init"]])

        code, p, out = cli("recall", "run", "hub", "--root", str(gstore), "--json", env=nenv)
        ngen1 = pointer(gbase).get("generation")
        check(
            "nanograph-auto-create",
            code == 0 and p.get("engine_used") == "nanograph" and p.get("engine_source") == "store" and bool(ngen1) and builds() == 1,
            out[:500],
        )
        code, p, out = cli("recall", "run", "hub", "--root", str(gstore), "--json", env=nenv)
        loads = [e for e in read_log(log) if e["argv"][:1] == ["load"]]
        check("nanograph-no-rebuild", code == 0 and builds() == 1 and len(loads) == 1 and pointer(gbase).get("generation") == ngen1, out[:300])
        notes = gstore / "notes"
        notes.mkdir(exist_ok=True)
        (notes / "kiwi.md").write_text("---\ntype: lesson\ntitle: Kiwi hub\ncreated: 2026-09-09\n---\n\nKiwi hub note.\n", encoding="utf-8")
        code, p, out = cli("recall", "run", "hub", "--root", str(gstore), "--json", env=nenv)
        ngen2 = pointer(gbase).get("generation")
        check("nanograph-refresh-on-edit", code == 0 and builds() == 2 and ngen2 != ngen1, out[:300])
        code, p, out = cli("recall", "run", "hub", "--root", str(gstore), "--json", env={**nenv, "FAKE_NANOGRAPH_VERSION": "1.4.0"})
        ngen3 = pointer(gbase).get("generation")
        check(
            "nanograph-version-bump-rebuilds",
            code == 0 and p.get("engine_used") == "nanograph" and builds() == 3 and ngen3 != ngen2 and pointer(gbase).get("version") == "1.4.0",
            out[:400],
        )
        kept = sorted(d.name for d in gbase.iterdir() if d.is_dir())
        check("nanograph-keeps-two", len(kept) == 2 and ngen3 in kept, str(kept))
        code, p, out = cli("recall", "index", "build", "--root", str(gstore), "--json", env={**nenv, "FAKE_NANOGRAPH_VERSION": "1.4.0"})
        check("nanograph-index-build-fresh", builds() == 3 and "preferred_index_fresh" in out and '"nanograph"' in out, out[:600])

        # --- legacy .atlas-index with a preference --------------------------------
        lproject = tmp / "lproj"
        lstore = make_store(lproject / "stores" / "notes", "1.0")
        write_mesh(lproject)
        index_location.clear_cache()
        code, _, out = cli("recall", "run", "ranking", "--root", str(lstore), "--json", env={"ATLAS_RECALL_ENGINE": "bm25"})
        index_location.clear_cache()
        legacy = to_legacy_fts5(lstore)
        shutil.rmtree(lproject / ".atlas", ignore_errors=True)
        write_mesh(lproject, row_recall={"engine": "bm25"})
        legacy_snap = tree_snapshot(legacy)
        code, p, out = cli("recall", "run", "ranking recall", "--root", str(lstore), "--json")
        check(
            "legacy-fresh-read-only",
            code == 0
            and p.get("engine_used") == "sqlite-fts5"
            and "legacy_index_location" in warning_codes(p)
            and not (lproject / ".atlas" / "indexes" / "fts5").exists()
            and tree_snapshot(legacy) == legacy_snap,
            out[:500],
        )
        edit(lstore, "decisions/beta.md", "\nDingo detail.\n")
        code, p, out = cli("recall", "run", "dingo", "--root", str(lstore), "--json")
        check(
            "legacy-stale-builds-new",
            code == 0
            and p.get("index_rebuilt") is True
            and "legacy_index_location" not in warning_codes(p)
            and bool(pointer(fts_base(lproject)).get("generation"))
            and tree_snapshot(legacy) == legacy_snap
            and [h.get("path") for h in p.get("hits") or []] == ["decisions/beta.md"],
            out[:500],
        )

        # --- profile-enabled store --------------------------------------------------
        pproject = tmp / "pproj"
        pstore = make_store(pproject / "stores" / "notes", "2.0")
        write_mesh(pproject, row_recall={"engine": "bm25"})
        act, _, out = cli("recall", "activate", "--profile", "atlas:ranked", "--root", str(pstore), "--json")
        check("profile-activate", act == 0, out[:300])
        pbase = fts_base(pproject)
        code, p, out = cli("recall", "run", "ranking recall", "--root", str(pstore), "--json")
        pgen1 = pointer(pbase).get("generation")
        check(
            "profile-bm25-runs-profile",
            code == 0
            and (p.get("recall") or {}).get("preset") == "atlas:ranked"
            and bool(pgen1)
            and (p.get("recall") or {}).get("generation") == pgen1
            and p.get("engine_requested") == "bm25"
            and not [i for i in p.get("info") or [] if i.get("code") == "preferred_engine_ignored"],
            out[:600],
        )
        edit(pstore, "decisions/gamma.md", "\nCassowary rule.\n")
        code, p, out = cli("recall", "run", "cassowary", "--root", str(pstore), "--json")
        pgen2 = pointer(pbase).get("generation")
        check(
            "profile-index-refreshed",
            code == 0
            and pgen2 != pgen1
            and (p.get("recall") or {}).get("index_rebuilt") is True
            and "decisions/gamma.md" in [h.get("path") for h in p.get("hits") or []],
            out[:600],
        )
        edit(pstore, "decisions/gamma.md", "\nMore cassowary.\n")
        code, p, out = cli("compile", "--root", str(pstore), "--json")
        check("profile-compile-refreshes", pointer(pbase).get("generation") not in (pgen1, pgen2), out[:300])

        write_mesh(pproject, row_recall={"engine": "nanograph"})
        code, p, out = cli(
            "recall", "run", "ranking recall", "--root", str(pstore), "--json",
            env={"ATLAS_PLATFORM_OVERRIDE": "darwin-arm64", "ATLAS_NANOGRAPH_BIN": str(fake)},
        )
        notices = [i for i in p.get("info") or [] if i.get("code") == "preferred_engine_ignored"]
        check(
            "profile-nanograph-ignored",
            code == 0
            and len(notices) == 1
            and "is authoritative; preferred engine nanograph from store not applied" in notices[0].get("message", "")
            and not (pproject / ".atlas" / "indexes" / "nanograph").exists(),
            out[:600],
        )
        code, p, out = cli("recall", "run", "ranking", "--root", str(pstore), "--engine", "bm25", "--json")
        err = str(p.get("error") or out)
        check("profile-explicit-engine-exit-2", code == 2 and "--profile" in err and "ignored" in err, out[:400])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} engine preference check(s) failed: {', '.join(failed)}")
        return 1
    print("\nall engine preference checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
