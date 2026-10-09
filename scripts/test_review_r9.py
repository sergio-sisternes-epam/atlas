#!/usr/bin/env python3
"""Review R9 regressions.

The legacy ``<store>/.atlas-index/`` location is read only when no index
exists at the new ``.atlas/indexes/<driver-type>/<atlas-id>/`` location. A
stale new-location index is rebuilt in place; it never loses to a fresh legacy
one, and legacy is never written.

1. nanograph (test-only platform darwin-arm64, fake nanograph): a stale
   new-location generation (recorded version or corpus digest mismatch) next
   to a fresh legacy one makes ``recall --engine nanograph`` and ``graph
   neighbours --driver nanograph`` rebuild the new location (``init``/``load``
   in the fake's argv log, ``current.json`` names the new generation), with no
   ``legacy_index_location`` warning and the legacy files untouched.
2. tgrep (unit level, fake runner): a stale new-location index next to a
   fresh legacy one is rebuilt without reading legacy; legacy is still used
   when the new location holds no index.
3. fts5: the same rule, for a stale pointer (digest mismatch, fast path) and
   an unusable old-format pointer (``ensure_fresh``), plus the shared
   :func:`index_location.choose_source` helper.
4. Mesh writers report ``atlas_mesh_lock_ignore_failed`` when the lock and
   temp-file ignore rules cannot be added (``atlas index set``, ``mount``, the
   ``upsert`` / ``remove_store`` API), never failing the write or changing
   the exit code; a writable ``info/exclude`` gives no warning.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
TEST_CLI = ROOT / "scripts" / "testing" / "atlas_test_cli.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, meshfile, recall_index  # noqa: E402
from atlas_cli.core.drivers import tgrep  # noqa: E402
from atlas_cli.core.recall_config import fts5_available  # noqa: E402
from test_drivers import make_store as make_graph_store  # noqa: E402
from test_drivers import read_log, write_fake  # noqa: E402
from test_index_location import tree_snapshot, warning_codes  # noqa: E402
from test_recall_bm25 import make_store  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
MESH_CODE = "atlas_mesh_lock_ignore_failed"


def cli(*args: str, env: dict[str, str] | None = None, cwd: Path = ROOT) -> tuple[int, dict, str, str]:
    base = {k: v for k, v in os.environ.items() if k != index_location.OVERRIDE_ENV}
    proc = subprocess.run(
        [sys.executable, str(TEST_CLI if "ATLAS_TEST_PLATFORM" in (env or {}) else ATLAS), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        env={**base, **GIT_ENV, **(env or {})},
    )
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    except json.JSONDecodeError:
        payload = {}
    return proc.returncode, payload, proc.stdout, proc.stderr


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, env={**os.environ, **GIT_ENV})


def inits(log: Path) -> int:
    return len([e for e in read_log(log) if e["argv"][:1] == ["init"]])


def loads(log: Path) -> int:
    return len([e for e in read_log(log) if e["argv"][:1] == ["load"]])


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


@contextlib.contextmanager
def broken_exclude(repo: Path) -> Iterator[None]:
    """Make ``<repo>/.git/info/exclude`` unwritable (as root, ``.git/info`` becomes a file)."""
    info_dir = repo / ".git" / "info"
    exclude = info_dir / "exclude"
    saved = info_dir.with_name("info.saved")
    if os.geteuid() == 0:
        # chmod does not stop root: make info a file instead (a real guard failure, no hook).
        shutil.move(str(info_dir), str(saved))
        info_dir.write_text("not a directory\n", encoding="utf-8")
    else:
        info_dir.mkdir(parents=True, exist_ok=True)
        if not exclude.exists():
            exclude.write_text("# local\n", encoding="utf-8")
        exclude.chmod(0o444)
    try:
        yield
    finally:
        if saved.exists():
            info_dir.unlink()
            shutil.move(str(saved), str(info_dir))
        elif exclude.exists():
            exclude.chmod(0o644)


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

    tmp = Path(tempfile.mkdtemp(prefix="atlas-r9-")).resolve()
    saved_env = dict(os.environ)
    os.environ.pop(index_location.OVERRIDE_ENV, None)
    try:
        # === 0. shared selection rule =========================================
        def selection_rule() -> None:
            calls: list[int] = []

            def legacy(value: bool) -> Callable[[], bool]:
                def probe() -> bool:
                    calls.append(1)
                    return value

                return probe

            cs = index_location.choose_source
            check("choose-fresh-new", cs(index_location.FRESH, legacy(True)) == index_location.USE_NEW and not calls)
            check("choose-stale-builds-no-legacy-read", cs(index_location.STALE, legacy(True)) == index_location.BUILD and not calls)
            check("choose-missing-fresh-legacy", cs(index_location.MISSING, legacy(True)) == index_location.USE_LEGACY and calls == [1])
            check("choose-missing-stale-legacy", cs(index_location.MISSING, legacy(False)) == index_location.BUILD)

        attempt("selection-rule", selection_rule)

        # === 1. nanograph =====================================================
        def nanograph_rule() -> None:
            fake = write_fake(tmp / "nanograph")
            log = tmp / "nanograph.log"
            nenv = {"ATLAS_TEST_PLATFORM": "darwin-arm64", "ATLAS_NANOGRAPH_BIN": str(fake), "FAKE_NANOGRAPH_LOG": str(log)}
            gstore = make_graph_store(tmp / "gstore")

            def ncli(*args: str) -> tuple[int, dict, str, str]:
                return cli(*args, "--root", str(gstore), "--json", env=nenv)

            code, p, out, err = ncli("recall", "run", "hub", "--engine", "nanograph")
            gen = (p.get("nanograph_index") or {}).get("generation", "")
            check("nano-seed", code == 0 and p.get("engine_used") == "nanograph" and bool(gen), out + err)
            index_location.clear_cache()
            base = index_location.index_dir(gstore, "nanograph")
            legacy = gstore / ".atlas-index" / "nanograph"
            legacy.mkdir(parents=True)
            shutil.copytree(base / gen, legacy / gen)
            legacy_before = tree_snapshot(legacy)

            def stale_version() -> None:
                current = read_json(base / "current.json")
                gen_dir = base / str(current["generation"])
                ready = read_json(gen_dir / "ready.json")
                write_json(gen_dir / "ready.json", {**ready, "version": "1.2.9"})
                write_json(base / "current.json", {**current, "version": "1.2.9"})

            def stale_digest() -> None:
                current = read_json(base / "current.json")
                gen_dir = base / str(current["generation"])
                ready = read_json(gen_dir / "ready.json")
                write_json(gen_dir / "ready.json", {**ready, "corpus_digest": "f" * 64})
                write_json(base / "current.json", {**current, "corpus_digest": "f" * 64})

            for label, make_stale, args in (
                ("recall", stale_version, ("recall", "run", "hub", "--engine", "nanograph")),
                ("neighbours", stale_digest, ("graph", "neighbours", "work/hub.md", "--driver", "nanograph")),
            ):
                make_stale()
                stale_gen = read_json(base / "current.json")["generation"]
                before_init, before_load = inits(log), loads(log)
                code, p, out, err = ncli(*args)
                used = p.get("engine_used") or p.get("driver_used")
                check(f"nano-{label}-ok", code == 0 and used == "nanograph", out[-600:] + err[-400:])
                check(
                    f"nano-{label}-rebuilt",
                    inits(log) > before_init and loads(log) > before_load,
                    f"init {before_init}->{inits(log)} load {before_load}->{loads(log)}",
                )
                pointer = read_json(base / "current.json")
                new_gen = str(pointer.get("generation"))
                ready = read_json(base / new_gen / "ready.json") if (base / new_gen / "ready.json").is_file() else {}
                check(
                    f"nano-{label}-pointer-new-generation",
                    new_gen != stale_gen and pointer.get("version") == "1.3.0" and ready.get("version") == "1.3.0",
                    f"{stale_gen} -> {pointer}",
                )
                if label == "recall":
                    ni = p.get("nanograph_index") or {}
                    check(
                        "nano-recall-new-location",
                        ni.get("generation") == new_gen
                        and not ni.get("legacy")
                        and str(ni.get("path", "")).startswith(".atlas/indexes/nanograph/"),
                        str(ni),
                    )
                check(f"nano-{label}-no-legacy-warning", "legacy_index_location" not in warning_codes(p), str(p.get("warnings")))
                check(f"nano-{label}-legacy-untouched", tree_snapshot(legacy) == legacy_before)

            # A pointer-less new-location generation also counts as an index (no legacy fallback).
            current = read_json(base / "current.json")
            (base / "current.json").unlink()
            gen_dir = base / str(current["generation"])
            ready = read_json(gen_dir / "ready.json")
            write_json(gen_dir / "ready.json", {**ready, "version": "1.2.9"})
            before_init = inits(log)
            code, p, out, err = ncli("recall", "run", "hub", "--engine", "nanograph")
            check(
                "nano-generation-only-rebuilds",
                code == 0
                and inits(log) > before_init
                and not (p.get("nanograph_index") or {}).get("legacy")
                and "legacy_index_location" not in warning_codes(p),
                out[-600:],
            )
            check("nano-generation-only-legacy-untouched", tree_snapshot(legacy) == legacy_before)

            # Control: with no new-location index at all, the fresh legacy one is still read.
            shutil.rmtree(gstore / ".atlas")
            before_init = inits(log)
            code, p, out, err = ncli("recall", "run", "hub", "--engine", "nanograph")
            check(
                "nano-missing-uses-legacy",
                code == 0
                and (p.get("nanograph_index") or {}).get("legacy") is True
                and "legacy_index_location" in warning_codes(p)
                and inits(log) == before_init,
                out[-600:],
            )
            check("nano-missing-legacy-untouched", tree_snapshot(legacy) == legacy_before)

        attempt("nanograph-rule", nanograph_rule)

        # === 2. tgrep =========================================================
        def tgrep_rule() -> None:
            store = tmp / "tstore"
            store.mkdir()
            (store / "note.md").write_text("# Note\n\nhub text\n", encoding="utf-8")
            digest = "a" * 64
            index_location.clear_cache()
            dest = tgrep.index_dir(store)
            legacy = tgrep.legacy_index_dir(store)
            legacy.mkdir(parents=True)
            write_json(legacy / tgrep.DIGEST_NAME, {"corpus_digest": digest, "complete": True})
            (legacy / "data.bin").write_bytes(b"legacy-index")
            dest.mkdir(parents=True)
            write_json(dest / tgrep.DIGEST_NAME, {"corpus_digest": "b" * 64, "complete": True})
            legacy_before = tree_snapshot(legacy)
            calls: list[list[str]] = []

            def runner(binary: Path, args: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
                calls.append(list(args))
                if args[0] == "index":
                    Path(args[args.index("--index-path") + 1], "data.bin").write_bytes(b"new-index")
                return subprocess.CompletedProcess([str(binary), *args], 0, "", "")

            reads: list[Path] = []
            original = tgrep._load_digest

            def spy(path: Path) -> str | None:
                reads.append(Path(path))
                return original(path)

            tgrep._load_digest = spy
            try:
                got, rebuilt = tgrep.ensure_index(store, digest, binary=Path("/fake/tgrep"), runner=runner)
                check("tgrep-stale-rebuilds-new", got == dest and rebuilt is True, f"{got} {rebuilt}")
                check("tgrep-stale-ran-index", [a[0] for a in calls] == ["index"], str(calls))
                check("tgrep-stale-new-digest", read_json(dest / tgrep.DIGEST_NAME).get("corpus_digest") == digest)
                check("tgrep-stale-no-legacy-read", legacy not in reads, str(reads))
                check("tgrep-stale-legacy-untouched", tree_snapshot(legacy) == legacy_before)

                # search() meta carries no legacy warning for a rebuilt stale index.
                write_json(dest / tgrep.DIGEST_NAME, {"corpus_digest": "c" * 64, "complete": True})
                reads.clear()
                calls.clear()
                _, meta = tgrep.search(store, [], "hub", 5, digest, binary=Path("/fake/tgrep"), runner=runner)
                check(
                    "tgrep-search-stale-rebuilds",
                    meta.get("rebuilt") is True and "legacy_warning" not in meta and legacy not in reads,
                    str(meta),
                )
                check("tgrep-search-legacy-untouched", tree_snapshot(legacy) == legacy_before)

                # Fresh new location: reused, no build, no legacy read.
                reads.clear()
                calls.clear()
                got, rebuilt = tgrep.ensure_index(store, digest, binary=Path("/fake/tgrep"), runner=runner)
                check("tgrep-fresh-new-reused", got == dest and rebuilt is False and not calls and legacy not in reads)

                # Control: no new-location index at all, so the fresh legacy one is read.
                shutil.rmtree(dest)
                calls.clear()
                got, rebuilt = tgrep.ensure_index(store, digest, binary=Path("/fake/tgrep"), runner=runner)
                check("tgrep-missing-uses-legacy", got == legacy and rebuilt is False and not calls, f"{got} {calls}")
                check("tgrep-missing-legacy-untouched", tree_snapshot(legacy) == legacy_before)
            finally:
                tgrep._load_digest = original

        attempt("tgrep-rule", tgrep_rule)

        # === 3. fts5 ===========================================================
        def fts5_rule() -> None:
            if not fts5_available():
                print("  [SKIP] sqlite has no FTS5; fts5 legacy-rule checks skipped")
                return
            store = make_store(tmp / "fstore", "2.0")
            cli("recall", "activate", "--profile", "atlas:ranked", "--root", str(store), "--json")
            code, p, out, err = cli("recall", "index", "build", "--root", str(store), "--json")
            check("fts5-seed", code == 0 and p.get("published") is True, out + err)
            index_location.clear_cache()
            root = recall_index.index_root(store)
            legacy = recall_index.legacy_root(store)
            legacy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(root, legacy, ignore=shutil.ignore_patterns(".lock*", ".tmp-*"))
            pointer = read_json(legacy / "current.json")
            write_json(legacy / "current.json", {**pointer, "db": f".atlas-index/recall/{pointer['db']}"})
            legacy_before = tree_snapshot(legacy)

            for label, mutate in (
                ("digest-stale", lambda cur: {**cur, "corpus_digest": "f" * 64}),
                ("old-format", lambda cur: {**cur, "format": 1}),
            ):
                current = read_json(root / "current.json")
                write_json(root / "current.json", mutate(current))
                code, p, out, err = cli("recall", "run", "ranking", "--root", str(store), "--json")
                after = read_json(root / "current.json")
                check(f"fts5-{label}-served", code == 0 and p.get("count", 0) > 0, out[-500:] + err[-300:])
                check(f"fts5-{label}-no-legacy-warning", "legacy_index_location" not in warning_codes(p), str(p.get("warnings")))
                check(
                    f"fts5-{label}-rebuilt-new",
                    after.get("generation") != current.get("generation")
                    and after.get("corpus_digest") == current.get("corpus_digest")
                    and recall_index.usable_pointer(after),
                    f"{current.get('generation')} -> {after}",
                )
                check(f"fts5-{label}-legacy-untouched", tree_snapshot(legacy) == legacy_before)

            # Status reports the stale new location, not legacy-only.
            current = read_json(root / "current.json")
            write_json(root / "current.json", {**current, "format": 1})
            index_location.clear_cache()
            active = recall_index.active_generation(store)
            check("fts5-active-not-legacy", active is None, str(active))
            write_json(root / "current.json", current)

            # Control: with no new-location index, the fresh legacy one is read.
            shutil.rmtree(store / ".atlas")
            code, p, out, err = cli("recall", "run", "ranking", "--root", str(store), "--json")
            check("fts5-missing-uses-legacy", code == 0 and "legacy_index_location" in warning_codes(p), out[-500:])
            check("fts5-missing-legacy-untouched", tree_snapshot(legacy) == legacy_before)

        attempt("fts5-rule", fts5_rule)

        # === 4. mesh-lock ignore failures =====================================
        sid = "github.com/acme/alpha"

        def mesh_project(name: str) -> Path:
            project = tmp / name
            project.mkdir()
            git(project, "init", "-q")
            make_store(project / "atlas" / "alpha", "1.0")
            write_json(project / "atlas-mesh.json", {"version": 1, "stores": [{"id": sid, "path": "atlas/alpha"}]})
            return project

        def mesh_warnings() -> None:
            good = mesh_project("mesh-good")
            code, p, out, err = cli("index", "set", "bm25", "--store", sid, "--root", str(good), "--json")
            check("mesh-control-ok", code == 0 and p.get("changed") is True, out + err)
            check("mesh-control-no-warning", MESH_CODE not in warning_codes(p), str(p.get("warnings")))
            exclude = (good / ".git" / "info" / "exclude").read_text(encoding="utf-8")
            check("mesh-control-rules-added", "/atlas-mesh.json.lock*" in exclude, exclude)

            bad = mesh_project("mesh-bad")
            with broken_exclude(bad):
                code, p, out, err = cli("index", "set", "bm25", "--store", sid, "--root", str(bad), "--json")
                doc = read_json(bad / "atlas-mesh.json")
                check("mesh-set-exit-0", code == 0 and p.get("ok") is True, out + err)
                check("mesh-set-written", doc["stores"][0].get("recall") == {"engine": "bm25"}, json.dumps(doc))
                items = [w for w in p.get("warnings") or [] if isinstance(w, dict) and w.get("code") == MESH_CODE]
                msg = str((items or [{}])[0].get("message", ""))
                check(
                    "mesh-set-warning",
                    len(items) == 1
                    and items[0].get("level") == "warning"
                    and msg.startswith("could not add atlas-mesh.json.lock* and temp-file rules to ")
                    and "exclude" in msg
                    and msg.endswith("; add them to .gitignore or info/exclude yourself"),
                    str(p.get("warnings")),
                )
                code, p, out, err = cli("index", "unset", "--store", sid, "--root", str(bad))
                doc = read_json(bad / "atlas-mesh.json")
                check("mesh-unset-text-exit-0", code == 0 and "recall" not in doc["stores"][0], out + err)
                check("mesh-unset-text-stderr-once", err.count("could not add atlas-mesh.json.lock*") == 1, err)

                written = meshfile.upsert(bad, {"id": "github.com/acme/beta", "path": "atlas/beta"})
                check(
                    "mesh-upsert-api-warning",
                    [w.get("code") for w in written.warnings] == [MESH_CODE]
                    and any(r.get("id") == "github.com/acme/beta" for r in read_json(bad / "atlas-mesh.json")["stores"]),
                    str(written),
                )
                removed = meshfile.remove_store(bad, "github.com/acme/beta")
                check(
                    "mesh-remove-api-warning",
                    [w.get("code") for w in removed.warnings] == [MESH_CODE]
                    and not any(r.get("id") == "github.com/acme/beta" for r in read_json(bad / "atlas-mesh.json")["stores"]),
                    str(removed),
                )
                res = meshfile.set_recall_engine(bad, sid, "grep")
                check("mesh-recall-api-warning", res.changed and [w.get("code") for w in res.warnings] == [MESH_CODE], str(res))
            ok = meshfile.upsert(good, {"id": "github.com/acme/beta", "path": "atlas/beta"})
            check("mesh-upsert-api-no-warning", ok.warnings == () and ok.path == good / "atlas-mesh.json", str(ok))

        attempt("mesh-warnings", mesh_warnings)

        def mount_warning() -> None:
            remote = tmp / "mounted.git"
            seed = tmp / "seed"
            seed.mkdir()
            git(seed, "init", "-q", "--initial-branch=main")
            (seed / "README.md").write_text("store\n", encoding="utf-8")
            git(seed, "add", "-A")
            git(seed, "commit", "-q", "-m", "seed")
            subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(remote)], check=True, capture_output=True)
            public = "https://github.com/acme/mounted"
            menv = {
                "GIT_ALLOW_PROTOCOL": "file",
                "GIT_CONFIG_COUNT": "1",
                # The clone URL is ``<public>.git``, so the prefix maps onto ``mounted.git``.
                "GIT_CONFIG_KEY_0": f"url.file://{tmp / 'mounted'}.insteadOf",
                "GIT_CONFIG_VALUE_0": public,
                "GH_TOKEN": "",
                "GITHUB_TOKEN": "",
            }
            for name, broken in (("mount-good", False), ("mount-bad", True)):
                parent = tmp / name
                parent.mkdir()
                git(parent, "init", "-q", "--initial-branch=main")
                (parent / ".keep").write_text("", encoding="utf-8")
                git(parent, "add", ".keep")
                git(parent, "commit", "-q", "-m", "parent")
                ctx = broken_exclude(parent) if broken else contextlib.nullcontext()
                with ctx:
                    code, p, out, err = cli("mount", public, "--cwd", str(parent), "--json", env=menv, cwd=parent)
                    rows = read_json(parent / "atlas-mesh.json")["stores"] if (parent / "atlas-mesh.json").is_file() else []
                    check(f"{name}-exit-0", code == 0 and p.get("ok") is True, out + err)
                    check(f"{name}-mesh-written", [r.get("id") for r in rows] == ["github.com/acme/mounted"], str(rows))
                    has = MESH_CODE in warning_codes(p)
                    check(f"{name}-warning", has if broken else not has, str(p.get("warnings")))
                    if broken:
                        code, p, out, err = cli("mount", public, "--cwd", str(parent), env=menv, cwd=parent)
                        check(
                            "mount-bad-text-stderr-once",
                            code == 0 and err.count("could not add atlas-mesh.json.lock*") == 1,
                            out + err,
                        )

        attempt("mount-warning", mount_warning)
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        index_location.clear_cache()
        for path in tmp.rglob("*"):
            with contextlib.suppress(OSError):
                if path.is_file() and not path.is_symlink():
                    path.chmod(path.stat().st_mode | stat.S_IWUSR)
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'FAILED: ' + ', '.join(failed) if failed else 'all review R9 checks passed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
