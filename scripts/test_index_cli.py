#!/usr/bin/env python3
"""`atlas index set|unset|show|status|build`: target resolution, safe mesh
writes, availability warnings, freshness, builds and the deprecated
`atlas recall index build` alias.

Linux-safe: no network and no real nanograph (the fake binary from
test_drivers runs through the test-only scripts/testing/atlas_test_cli.py
with ATLAS_TEST_PLATFORM=darwin-arm64).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core.recall_config import fts5_available  # noqa: E402
from test_drivers import make_store as make_graph_store  # noqa: E402
from test_drivers import read_log, write_fake  # noqa: E402
from test_engine_preference import cli, edit, generations, pointer  # noqa: E402
from test_recall_bm25 import make_store  # noqa: E402

A = "github.com/acme/alpha"
B = "github.com/o/r"
C = "github.com/acme/gone"


def id_path(sid: str) -> Path:
    return Path(*sid.split("/"))


def idx(project: Path, kind: str, sid: str) -> Path:
    return project / ".atlas" / "indexes" / kind / id_path(sid)


def mesh_doc(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_mesh(project: Path, doc: dict, indent: int | str = 2, newline: bool = True) -> Path:
    mesh = project / "atlas-mesh.json"
    mesh.write_text(json.dumps(doc, indent=indent) + ("\n" if newline else ""), encoding="utf-8")
    return mesh


def without_recall(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k != "recall"}
    out["stores"] = [{k: v for k, v in r.items() if k != "recall"} for r in doc["stores"]]
    return out


def warning_codes(p: dict) -> list[str]:
    return [str(w.get("code")) for w in p.get("warnings") or [] if isinstance(w, dict)]


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-index-cli-"))
    try:
        project = tmp / "proj"
        sa = make_store(project / "atlas" / "alpha", "1.0")
        sb = make_store(project / "atlas" / "r", "1.0")
        base_doc = {
            "version": 1,
            "stores": [
                {"id": A, "path": "atlas/alpha"},
                {"id": B, "path": "atlas/r"},
                {"id": C, "path": "atlas/gone"},
            ],
        }
        mesh = write_mesh(project, base_doc)

        # --- set: targets -----------------------------------------------------------
        code, p, out = cli("index", "set", "bm25", "--root", str(sa), "--json")
        doc = mesh_doc(mesh)
        check(
            "set-root-store",
            code == 0
            and p.get("changed") is True
            and p.get("target") == A
            and p.get("previous") is None
            and p.get("value") == "bm25"
            and p.get("mesh_file") == "atlas-mesh.json"
            and doc["stores"][0].get("recall") == {"engine": "bm25"}
            and "recall" not in doc
            and "recall" not in doc["stores"][1],
            out[:400],
        )
        code, p, out = cli("index", "set", "grep", "--store", "https://github.com/O/R.git", "--root", str(project), "--json")
        check("set-store-normalised", code == 0 and p.get("target") == B and mesh_doc(mesh)["stores"][1].get("recall") == {"engine": "grep"}, out[:400])
        code, p, out = cli("index", "set", "bm25", "--default", "--root", str(sb), "--json")
        check("set-default", code == 0 and p.get("target") == "default" and mesh_doc(mesh).get("recall") == {"engine": "bm25"}, out[:400])
        code, p, out = cli("index", "set", "bm25", "--default", "--store", A, "--root", str(project), "--json")
        check("set-store-and-default-exit-2", code == 2 and "mutually exclusive" in str(p.get("error")), out[:300])
        code, p, out = cli("index", "set", "lucene", "--root", str(sa), "--json")
        check("set-invalid-value-exit-2", code == 2 and "grep, bm25, nanograph" in str(p.get("error")), out[:300])
        code, p, out = cli("index", "set", "bm25", "--store", "github.com/no/such", "--root", str(project), "--json")
        err = str(p.get("error"))
        check("set-unknown-store-exit-2", code == 2 and A in err and B in err and C in err, out[:300])
        code, p, out = cli("index", "set", "bm25", "--root", str(project), "--json")
        check("set-project-root-needs-target", code == 2 and "--store" in str(p.get("error")), out[:300])
        lone = make_store(tmp / "lone", "1.0")
        code, p, out = cli("index", "set", "bm25", "--root", str(lone), "--json")
        check(
            "set-standalone-exit-2",
            code == 2 and "atlas mount" in str(p.get("error")) and not (lone / "atlas-mesh.json").exists() and not (tmp / "atlas-mesh.json").exists(),
            out[:300],
        )
        code, p, out = cli("index", "set", "bm25", "--default", "--root", str(lone), "--json")
        check("set-default-standalone-exit-2", code == 2 and not (lone / "atlas-mesh.json").exists(), out[:300])

        # --- unset ----------------------------------------------------------------------
        code, p, out = cli("index", "unset", "--root", str(sa), "--json")
        doc = mesh_doc(mesh)
        check(
            "unset-removes-key",
            code == 0 and p.get("changed") is True and p.get("previous") == "bm25" and "recall" not in doc["stores"][0]
            and ".atlas/indexes/" in str(p.get("note")),
            out[:400],
        )
        code, p, out = cli("index", "unset", "--root", str(sa), "--json")
        check("unset-idempotent", code == 0 and p.get("changed") is False, out[:300])
        code, p, out = cli("index", "unset", "--default", "--root", str(sa))
        check("unset-default-text", code == 0 and "recall" not in mesh_doc(mesh) and "deleted by hand" in out, out[:300])
        cli("index", "unset", "--store", B, "--root", str(project))
        check("unset-all-clean", mesh_doc(mesh) == base_doc, mesh.read_text())

        # --- formatting preservation --------------------------------------------------------
        fproject = tmp / "fmt"
        fproject.mkdir()
        # The mesh schema forbids unknown keys, so preservation is exercised with
        # every optional row key in a non-canonical order; unknown keys are refused below.
        fdoc = {
            "stores": [
                {"path": "atlas/r", "strategy": "shared", "ref": "atlas", "id": B},
                {"id": A, "subpath": "kb", "path": "atlas/alpha"},
                {"id": C, "path": "atlas/gone", "strategy": "dedicated"},
            ],
            "version": 1,
        }
        fmesh = write_mesh(fproject, fdoc, indent=4, newline=True)
        for args in (("set", "nanograph", "--store", A), ("set", "bm25", "--default"), ("unset", "--store", A), ("set", "grep", "--store", C)):
            code, p, out = cli("index", *args, "--root", str(fproject), "--json")
            raw = fmesh.read_text(encoding="utf-8")
            now = json.loads(raw)
            check(
                f"format-{'-'.join(args[:2])}",
                code == 0
                and without_recall(now) == fdoc
                and list(now) == (["stores", "version", "recall"] if "recall" in now else list(fdoc))
                and [list(r) for r in without_recall(now)["stores"]] == [list(r) for r in fdoc["stores"]]
                and [r["id"] for r in now["stores"]] == [B, A, C]
                and raw.splitlines()[1].startswith("    \"")
                and not raw.splitlines()[1].startswith("     ")
                and raw.endswith("}\n"),
                raw[:400],
            )
        check("format-values", mesh_doc(fmesh).get("recall") == {"engine": "bm25"} and mesh_doc(fmesh)["stores"][2].get("recall") == {"engine": "grep"} and "recall" not in mesh_doc(fmesh)["stores"][1])
        before_bytes = fmesh.read_bytes()
        os.utime(fmesh, (1_000_000_000, 1_000_000_000))
        mtime = fmesh.stat().st_mtime_ns
        code, p, out = cli("index", "set", "grep", "--store", C, "--root", str(fproject), "--json")
        check("noop-untouched", code == 0 and p.get("changed") is False and fmesh.stat().st_mtime_ns == mtime and fmesh.read_bytes() == before_bytes, out[:300])
        check("no-temp-left", sorted(c.name for c in fproject.iterdir()) == ["atlas-mesh.json"], str(list(fproject.iterdir())))
        nproject = tmp / "nonl"
        nproject.mkdir()
        nmesh = write_mesh(nproject, base_doc, indent="\t", newline=False)
        cli("index", "set", "bm25", "--store", A, "--root", str(nproject))
        raw = nmesh.read_text(encoding="utf-8")
        check("format-tabs-no-newline", raw.splitlines()[1].startswith("\t\"") and not raw.endswith("\n") and mesh_doc(nmesh)["stores"][0]["recall"] == {"engine": "bm25"}, raw[:200])
        bad = fproject / "atlas-mesh.json"
        bad.write_text('{"version": 1, "stores": [ {"id": "github.com/o/r", "path": "atlas/r"}, ]}\n', encoding="utf-8")
        bad_bytes = bad.read_bytes()
        code, p, out = cli("index", "set", "bm25", "--store", B, "--root", str(fproject), "--json")
        check("invalid-json-refused", code == 2 and bad.read_bytes() == bad_bytes, out[:300])
        code, p, out = cli("index", "set", "bm25", "--default", "--root", str(fproject), "--json")
        check("invalid-json-refused-default", code == 2 and bad.read_bytes() == bad_bytes, out[:300])
        bad.write_text(json.dumps({"version": 1, "stores": [{"id": "GitHub.com/O/R", "path": "x"}]}, indent=2) + "\n", encoding="utf-8")
        bad_bytes = bad.read_bytes()
        code, p, out = cli("index", "set", "bm25", "--default", "--root", str(fproject), "--json")
        check("invalid-doc-refused", code == 2 and bad.read_bytes() == bad_bytes, out[:300])
        bad.write_text(json.dumps({"version": 1, "x-owner": "docs", "stores": [{"id": B, "path": "x"}]}, indent=4) + "\n", encoding="utf-8")
        bad_bytes = bad.read_bytes()
        code, p, out = cli("index", "set", "bm25", "--default", "--root", str(fproject), "--json")
        check("unknown-key-refused", code == 2 and "x-owner" in str(p.get("error")) and bad.read_bytes() == bad_bytes, out[:300])

        # --- unavailable warning (Linux) ---------------------------------------------
        linux = {"ATLAS_TEST_PLATFORM": "linux-x86_64"}
        code, p, out = cli("index", "set", "nanograph", "--root", str(sa), "--json", env=linux)
        warn = [w for w in p.get("warnings") or [] if w.get("code") == "engine_unavailable_here"]
        check(
            "warn-unavailable",
            code == 0
            and mesh_doc(mesh)["stores"][0].get("recall") == {"engine": "nanograph"}
            and len(warn) == 1
            and warn[0].get("message") == "nanograph unavailable on linux-x86_64; recall here will fall back to bm25",
            out[:400],
        )
        code, p, out = cli("index", "set", "nanograph", "--root", str(sa), env=linux)
        check("warn-unavailable-stderr", code == 0 and "warning: nanograph unavailable on linux-x86_64" in out, out[:300])
        code, p, out = cli("index", "show", "--root", str(sa), "--json", env=linux)
        check(
            "show-linux-fallback",
            code == 0
            and p.get("engine_requested") == "nanograph"
            and p.get("engine_effective") == "bm25"
            and p.get("fallback") == [{"engine": "nanograph", "reason": "unavailable on linux-x86_64"}]
            and (p.get("index") or {}).get("driver_type") == "fts5"
            and not (project / ".atlas" / "indexes" / "nanograph").exists(),
            out[:500],
        )

        if not fts5_available():
            print("  [SKIP] sqlite3 lacks FTS5; build checks skipped")
            return 1 if failed else 0

        # --- show: precedence and freshness ----------------------------------------
        write_mesh(project, {**base_doc, "recall": {"engine": "grep"}, "stores": [{**base_doc["stores"][0], "recall": {"engine": "bm25"}}, *base_doc["stores"][1:]]})
        code, p, out = cli("index", "show", "--root", str(sa), "--json", env={"ATLAS_RECALL_ENGINE": "nanograph", **linux})
        check(
            "show-precedence",
            code == 0
            and p.get("levels") == {"env": "nanograph", "store": "bm25", "project": "grep", "default": "grep"}
            and p.get("engine_requested") == "nanograph"
            and p.get("engine_source") == "env"
            and p.get("engine_effective") == "bm25",
            out[:500],
        )
        code, p, out = cli("index", "show", "--root", str(sa), "--json")
        check("show-store-wins", p.get("engine_source") == "store" and (p.get("index") or {}).get("freshness") == "missing", out[:400])
        code, p, out = cli("index", "show", "--root", str(sa))
        check("show-text", code == 0 and "store row:        bm25" in out and "missing" in out, out[:500])
        code, p, out = cli("index", "set", "bm25", "--build", "--root", str(sa), "--json")
        fa = idx(project, "fts5", A)
        gen1 = pointer(fa).get("generation")
        b = (p.get("builds") or [{}])[0]
        check(
            "set-build-bm25",
            code == 0 and p.get("changed") is False and bool(gen1) and b.get("status") == "built" and b.get("generation") == gen1
            and b.get("engine_effective") == "bm25" and b.get("index_dir") == f".atlas/indexes/fts5/{A}",
            out[:500],
        )
        code, p, out = cli("index", "show", "--root", str(sa), "--json")
        ix = p.get("index") or {}
        check("show-fresh", ix.get("freshness") == "fresh" and ix.get("generation") == gen1 and len(str(ix.get("digest"))) == 12, out[:400])
        edit(sa, "decisions/beta.md", "\nKoala clause.\n")
        code, p, out = cli("index", "show", "--root", str(sa), "--json")
        check("show-stale", (p.get("index") or {}).get("freshness") == "stale" and pointer(fa).get("generation") == gen1, out[:400])
        cli("recall", "run", "koala", "--root", str(sa), "--json")
        code, p, out = cli("index", "show", "--root", str(sa), "--json")
        gen2 = pointer(fa).get("generation")
        check("show-fresh-after-recall", (p.get("index") or {}).get("freshness") == "fresh" and gen2 != gen1, out[:400])

        # --- index build ------------------------------------------------------------------
        code, p, out = cli("index", "build", "--root", str(sa), "--json")
        check("build-fresh-not-rebuilt", code == 0 and p.get("status") == "fresh" and p.get("rebuilt") is False and pointer(fa).get("generation") == gen2, out[:400])
        edit(sa, "decisions/gamma.md", "\nWallaby.\n")
        code, p, out = cli("index", "build", "--root", str(sa), "--json")
        gen3 = pointer(fa).get("generation")
        check("build-stale-rebuilt", code == 0 and p.get("status") == "built" and gen3 not in (gen1, gen2), out[:400])
        code, p, out = cli("index", "build", "--root", str(sa), "--force", "--json")
        gen4 = pointer(fa).get("generation")
        check("build-force", code == 0 and p.get("rebuilt") is True and gen4 != gen3 and len(generations(fa)) == 2, out[:400])
        code, p, out = cli("recall", "index", "build", "--root", str(sa), "--json")
        check(
            "recall-index-build-deprecated",
            code == 0 and p.get("status") == "fresh" and p.get("generation") == gen4 and "deprecated_command" in warning_codes(p)
            and "atlas index build" in json.dumps(p.get("warnings")),
            out[:400],
        )
        code, p, out = cli("recall", "index", "build", "--root", str(sa))
        check("recall-index-build-stderr", code == 0 and "warning: `atlas recall index build` is deprecated" in out, out[:300])

        # --- status ---------------------------------------------------------------------
        write_mesh(project, {"version": 1, "recall": {"engine": "bm25"}, "stores": [
            {"id": A, "path": "atlas/alpha", "recall": {"engine": "grep"}},
            {"id": B, "path": "atlas/r"},
            {"id": C, "path": "atlas/gone"},
        ]})
        code, p, out = cli("index", "status", "--root", str(project), "--json")
        rows = {r["store_id"]: r for r in p.get("stores") or []}
        check(
            "status-rows",
            code == 0
            and p.get("default") == "bm25"
            and [r["store_id"] for r in p.get("stores") or []] == [A, B, C]
            and rows[A]["configured"] == "grep" and rows[A]["configured_source"] == "store"
            and rows[A]["engine_effective"] == "grep" and rows[A]["freshness"] is None
            and rows[B]["configured"] == "bm25" and rows[B]["configured_source"] == "project"
            and rows[B]["engine_effective"] == "bm25" and rows[B]["freshness"] == "missing"
            and rows[B]["index_dir"] == f".atlas/indexes/fts5/{B}"
            and rows[C]["mounted"] is False and rows[C]["freshness"] is None,
            out[:800],
        )
        code, p, out = cli("index", "status", "--root", str(sb))
        check("status-text", code == 0 and C in out and "no" in out and "missing" in out, out[:600])
        code, p, out = cli("index", "status", "--root", str(lone), "--json")
        check("status-standalone", code == 0 and p.get("mode") == "standalone" and len(p.get("stores") or []) == 1 and p["stores"][0]["mounted"] is True, out[:400])

        # --- --default --build only builds inheriting rows; --all ------------------------------
        shutil.rmtree(project / ".atlas")
        code, p, out = cli("index", "set", "bm25", "--default", "--build", "--root", str(project), "--json")
        builds = {b["store_id"]: b for b in p.get("builds") or []}
        check(
            "default-build-inheriting-only",
            code == 0
            and sorted(builds) == sorted([B, C])
            and builds[B]["status"] == "built"
            and builds[C]["status"] == "skipped" and builds[C]["message"] == "skipped: store not mounted"
            and not idx(project, "fts5", A).exists()
            and bool(pointer(idx(project, "fts5", B)).get("generation")),
            json.dumps({k: {x: v.get(x) for x in ("status", "message", "error")} for k, v in builds.items()}),
        )
        code, p, out = cli("index", "set", "grep", "--store", A, "--build", "--root", str(project), "--json")
        b = (p.get("builds") or [{}])[0]
        check("set-grep-build-no-index", code == 0 and b.get("status") == "no_index_needed" and b.get("message") == "no index needed (grep)", out[:400])
        code, p, out = cli("index", "build", "--all", "--root", str(project), "--json")
        st = {r["store_id"]: r["status"] for r in p.get("stores") or []}
        check("build-all", code == 0 and st == {A: "no_index_needed", B: "fresh", C: "skipped"}, out[:600])
        code, p, out = cli("index", "build", "--store", C, "--root", str(project), "--json")
        check("build-store-unmounted-skipped", code == 0 and p.get("status") == "skipped", out[:300])

        # --- nanograph with the fake binary (darwin override) ---------------------------------
        gproject = tmp / "gproj"
        g1 = make_graph_store(gproject / "atlas" / "one")
        make_graph_store(gproject / "atlas" / "two")
        gmesh = write_mesh(gproject, {"version": 1, "stores": [{"id": A, "path": "atlas/one"}, {"id": B, "path": "atlas/two"}]})
        fake = write_fake(tmp / "nanograph")
        log = tmp / "nano.log"
        nenv = {"ATLAS_TEST_PLATFORM": "darwin-arm64", "ATLAS_NANOGRAPH_BIN": str(fake), "FAKE_NANOGRAPH_LOG": str(log)}
        code, p, out = cli("index", "set", "nanograph", "--build", "--root", str(g1), "--json", env=nenv)
        b = (p.get("builds") or [{}])[0]
        nbase = idx(gproject, "nanograph", A)
        check(
            "set-build-nanograph",
            code == 0 and not p.get("warnings") and b.get("status") == "built" and b.get("engine_effective") == "nanograph"
            and bool(pointer(nbase).get("generation")) and b.get("generation") == pointer(nbase).get("generation"),
            out[:500],
        )
        code, p, out = cli("recall", "run", "hub", "--root", str(g1), "--json", env=nenv)
        check("e2e-nanograph-default", code == 0 and p.get("engine_used") == "nanograph" and p.get("engine_source") == "store", out[:400])
        code, p, out = cli("recall", "run", "hub", "--root", str(g1), "--engine", "grep", "--json", env=nenv)
        check("e2e-engine-override", code == 0 and p.get("engine_used") == "grep" and p.get("engine_source") == "cli", out[:400])
        code, p, out = cli("index", "show", "--root", str(g1), "--json", env=nenv)
        check("show-nanograph-fresh", code == 0 and (p.get("index") or {}).get("freshness") == "fresh", out[:400])
        cli("index", "set", "bm25", "--store", B, "--root", str(gproject), env=nenv)
        shutil.rmtree(gproject / ".atlas")
        code, p, out = cli("index", "build", "--all", "--root", str(gproject), "--json", env={**nenv, "FAKE_NANOGRAPH_FAIL": "init"})
        st = {r["store_id"]: r for r in p.get("stores") or []}
        check(
            "build-all-failure-exit-1",
            code == 1
            and st[A]["status"] == "failed" and "init failed" in str(st[A].get("error"))
            and st[B]["status"] == "built"
            and bool(pointer(idx(gproject, "fts5", B)).get("generation")),
            out[:600],
        )
        code, p, out = cli("index", "build", "--all", "--root", str(gproject), env={**nenv, "FAKE_NANOGRAPH_FAIL": "init"})
        check("build-all-failure-text", code == 1 and "FAILED" in out and "1 build(s) failed" in out, out[:400])
        check("gmesh-intact", [r["id"] for r in mesh_doc(gmesh)["stores"]] == [A, B])
        check("nanograph-built-once-per-build", len([e for e in read_log(log) if e['argv'][:1] == ['init']]) == 3, str(read_log(log))[:300])

        # --- profile-enabled store -----------------------------------------------------------
        pproject = tmp / "pproj"
        ps = make_store(pproject / "atlas" / "p", "2.0")
        write_mesh(pproject, {"version": 1, "stores": [{"id": A, "path": "atlas/p"}]})
        act, _, out = cli("recall", "activate", "--profile", "atlas:ranked", "--root", str(ps), "--json")
        check("profile-activate", act == 0, out[:300])
        code, p, out = cli("index", "set", "nanograph", "--root", str(ps), "--json", env=nenv)
        check("profile-set-info", code == 0 and "preferred_engine_ignored" in json.dumps(p.get("info")), out[:400])
        code, p, out = cli("index", "show", "--root", str(ps), "--json", env=nenv)
        check(
            "profile-show-ignored",
            code == 0 and p.get("profile") == "atlas:ranked" and p.get("preference_ignored") is True
            and p.get("engine_effective") == "profile:atlas:ranked" and (p.get("index") or {}).get("freshness") == "missing",
            out[:500],
        )
        code, p, out = cli("index", "build", "--root", str(ps), "--json", env=nenv)
        pbase = idx(pproject, "fts5", A)
        check(
            "profile-build-fts5",
            code == 0 and p.get("status") == "built" and p.get("published") is True
            and bool(pointer(pbase).get("generation")) and not (pproject / ".atlas" / "indexes" / "nanograph").exists(),
            out[:500],
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} index CLI check(s) failed: {', '.join(failed)}")
        return 1
    print("\nall index CLI checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
