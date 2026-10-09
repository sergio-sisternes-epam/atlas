#!/usr/bin/env python3
"""Derived index location: ``<project-root>/.atlas/indexes/<driver-type>/<atlas-id>/``.

Covers mesh/standalone resolution, id sanitising, the ATLAS_INDEX_ROOT
override, read-only legacy ``.atlas-index/`` reads (fts5 and nanograph via the
fake binary), the project ignore guard and projection skipping. No network,
no real nanograph.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import ignore_guard, index_location  # noqa: E402
from atlas_cli.core.recall_config import fts5_available  # noqa: E402
from test_drivers import make_store as make_graph_store  # noqa: E402
from test_drivers import read_log, write_fake  # noqa: E402
from test_recall_bm25 import as_json, git, make_store  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def cli(*args: str, env: dict[str, str] | None = None) -> tuple[int, dict, str]:
    proc = subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, **GIT_ENV, **(env or {})},
    )
    data = as_json(proc)
    return proc.returncode, data, proc.stdout + proc.stderr


def git_init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.email", "t@example.invalid")
    git(path, "config", "user.name", "t")
    git(path, "config", "commit.gpgsign", "false")


def commit_all(path: Path) -> None:
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")


def tree_snapshot(base: Path) -> dict[str, tuple[int, int, bytes]]:
    out: dict[str, tuple[int, int, bytes]] = {}
    for p in sorted(base.rglob("*")):
        st = p.lstat()
        data = p.read_bytes() if p.is_file() else b""
        out[p.relative_to(base).as_posix()] = (st.st_mtime_ns, st.st_size, data)
    return out


def warning_codes(payload: dict) -> list[str]:
    return [w.get("code") for w in payload.get("warnings") or [] if isinstance(w, dict)]


def local_id(store: Path) -> str:
    resolved = store.resolve()
    return f"local/{resolved.name}-{hashlib.sha256(str(resolved).encode('utf-8')).hexdigest()[:8]}"


def to_legacy_fts5(store: Path) -> Path:
    """Move a freshly published fts5 index into the pre-0.14 in-store layout."""
    new = index_location.index_dir(store, "fts5")
    legacy = store / ".atlas-index" / "recall"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(new), str(legacy))
    pointer = json.loads((legacy / "current.json").read_text(encoding="utf-8"))
    pointer["db"] = f".atlas-index/recall/{pointer['db']}"
    (legacy / "current.json").write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
    return legacy


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-idxloc-")).resolve()
    saved_env = dict(os.environ)
    os.environ.pop(index_location.OVERRIDE_ENV, None)
    try:
        # --- mesh mode ------------------------------------------------------
        project = tmp / "project"
        git_init(project)
        (project / "README.md").write_text("project\n", encoding="utf-8")
        (project / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        mesh_row = {"id": "github.com/o/r", "path": ".atlas/github.com/o/r", "strategy": "dedicated"}
        (project / "atlas-mesh.json").write_text(json.dumps({"version": 1, "stores": [mesh_row]}) + "\n", encoding="utf-8")
        commit_all(project)
        mstore = make_store(project / ".atlas" / "github.com" / "o" / "r", "2.0")
        git_init(mstore)
        commit_all(mstore)
        gitignore_before = (project / ".gitignore").read_bytes()

        index_location.clear_cache()
        loc = index_location.resolve(mstore)
        check(
            "mesh-resolve",
            loc.mode == "mesh" and loc.project_root == project and loc.atlas_id == "github.com/o/r" and loc.id_source == "mesh",
            str(loc),
        )
        base = project / ".atlas" / "indexes"
        check("mesh-fts5-dir", index_location.index_dir(mstore, "fts5") == base / "fts5" / "github.com" / "o" / "r")
        check("mesh-nanograph-dir", index_location.index_dir(mstore, "nanograph") == base / "nanograph" / "github.com" / "o" / "r")
        check("mesh-tgrep-dir", index_location.index_dir(mstore, "tgrep") == base / "tgrep" / "github.com" / "o" / "r")
        check(
            "mesh-legacy-dir",
            index_location.legacy_dir(mstore, "fts5") == mstore / ".atlas-index" / "recall"
            and index_location.legacy_dir(mstore, "nanograph") == mstore / ".atlas-index" / "nanograph",
        )
        try:
            index_location.index_dir(mstore, "bogus")
            check("unknown-driver-type", False)
        except ValueError:
            check("unknown-driver-type", True)

        # A malformed mesh file nearer the store is skipped, not fatal.
        (project / ".atlas" / "github.com" / "atlas-mesh.json").write_text("{not json", encoding="utf-8")
        index_location.clear_cache()
        check("mesh-malformed-skipped", index_location.resolve(mstore).project_root == project)
        (project / ".atlas" / "github.com" / "atlas-mesh.json").unlink()
        index_location.clear_cache()

        if fts5_available():
            code, p, out = cli("recall", "activate", "--profile", "atlas:ranked", "--root", str(mstore), "--json")
            check("mesh-activate", code == 0, out)
            git(mstore, "add", "-A")
            git(mstore, "commit", "-q", "-m", "activate")
            code, p, out = cli("recall", "index", "build", "--root", str(mstore), "--json")
            check("mesh-build", code == 0 and p.get("published") is True, out)
            check(
                "mesh-build-reports-location",
                p.get("index_dir") == ".atlas/indexes/fts5/github.com/o/r"
                and p.get("index_location") == {"mode": "mesh", "atlas_id": "github.com/o/r", "id_source": "mesh"},
                str({k: p.get(k) for k in ("index_dir", "index_location")}),
            )
            check("mesh-build-wrote-new", (base / "fts5" / "github.com" / "o" / "r" / "current.json").is_file())
            code, p, out = cli("compile", "--root", str(mstore), "--json")
            check("mesh-compile", code == 0, out)
            status = git(mstore, "status", "--porcelain", "--untracked-files=all").stdout
            check("mesh-store-status-clean", status.strip() == "", status)
            check("mesh-no-legacy-created", not (mstore / ".atlas-index").exists() and not (mstore / ".atlas").exists())
            exclude = project / ".git" / "info" / "exclude"
            lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.is_file() else []
            check("mesh-guard-line-once", lines.count("/.atlas/indexes/") == 1, str(lines))
            pstatus = git(project, "status", "--porcelain", "--untracked-files=all").stdout
            check("mesh-project-indexes-ignored", ".atlas/indexes" not in pstatus, pstatus)
            check("mesh-gitignore-untouched", (project / ".gitignore").read_bytes() == gitignore_before)
            code, p, out = cli("recall", "run", "ranking", "--root", str(mstore), "--json")
            check(
                "mesh-recall-fast-path",
                code == 0 and p.get("count", 0) > 0 and "legacy_index_location" not in warning_codes(p),
                out,
            )

        # --- ignore guard (in-process) ---------------------------------------
        index_location.clear_cache()
        check("guard-idempotent", ignore_guard.ensure_indexes_ignored(mstore) is None)
        guarded = tmp / "guarded"
        git_init(guarded)
        (guarded / ".git" / "info").mkdir(parents=True, exist_ok=True)
        (guarded / ".git" / "info" / "exclude").write_text(".atlas/\n", encoding="utf-8")
        (guarded / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
        gi_before = (guarded / ".gitignore").read_bytes()
        info = ignore_guard.ensure_indexes_ignored(guarded)
        check(
            "guard-existing-atlas-line",
            info is None and (guarded / ".git" / "info" / "exclude").read_text(encoding="utf-8") == ".atlas/\n",
            str(info),
        )
        (guarded / ".git" / "info" / "exclude").write_text("", encoding="utf-8")
        index_location.clear_cache()
        info = ignore_guard.ensure_indexes_ignored(guarded)
        info2 = ignore_guard.ensure_indexes_ignored(guarded)
        legacy_info = ignore_guard.ensure_index_ignored(guarded)
        exc_lines = (guarded / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
        check(
            "guard-adds-once",
            (info or {}).get("id") == "atlas_indexes_ignored" and info2 is None and exc_lines.count("/.atlas/indexes/") == 1,
            f"{info} {info2} {exc_lines}",
        )
        check(
            "guard-legacy-still-handled",
            (legacy_info or {}).get("id") == "atlas_index_ignored" and exc_lines.count("/.atlas-index/") == 1,
            f"{legacy_info} {exc_lines}",
        )
        check("guard-gitignore-untouched", (guarded / ".gitignore").read_bytes() == gi_before)
        check("guard-non-git-noop", ignore_guard.ensure_indexes_ignored(tmp / "nope") is None)

        # --- standalone with origin ------------------------------------------
        origin_store = tmp / "origin-store"
        git_init(origin_store)
        git(origin_store, "remote", "add", "origin", "https://github.com/o/s.git")
        index_location.clear_cache()
        loc = index_location.resolve(origin_store)
        check(
            "origin-resolve",
            loc.mode == "standalone" and loc.project_root == origin_store and loc.atlas_id == "github.com/o/s" and loc.id_source == "origin",
            str(loc),
        )
        check(
            "origin-dir",
            index_location.index_dir(origin_store, "fts5") == origin_store / ".atlas" / "indexes" / "fts5" / "github.com" / "o" / "s",
        )

        # --- standalone without git -------------------------------------------
        plain = tmp / "My Store!"
        plain.mkdir()
        index_location.clear_cache()
        loc = index_location.resolve(plain)
        index_location.clear_cache()
        loc2 = index_location.resolve(plain)
        want_id = f"local/My-Store-{hashlib.sha256(str(plain).encode('utf-8')).hexdigest()[:8]}"
        check(
            "local-resolve",
            loc.mode == "standalone" and loc.project_root == plain and loc.id_source == "local" and loc.atlas_id == want_id,
            str(loc),
        )
        check("local-deterministic", loc == loc2)

        # --- sanitising -------------------------------------------------------
        for bad in ("..", "a/../b", "/abs", "a//b", "a\\b", "", ".", "a/b c", "a/\x00b", "-x/y"):
            try:
                index_location.safe_id_path(bad)
                check(f"sanitise-rejects-{bad!r}", False)
            except index_location.IndexLocationError as e:
                check(f"sanitise-rejects-{bad!r}", repr(bad) in str(e) or bad in str(e) or bad == "", str(e))
        check("sanitise-accepts", str(index_location.safe_id_path("github.com/o/r")) == "github.com/o/r")

        sym = tmp / "sym-store"
        sym.mkdir()
        outside = tmp / "outside"
        outside.mkdir()
        (sym / ".atlas" / "indexes").mkdir(parents=True)
        (sym / ".atlas" / "indexes" / "fts5").symlink_to(outside, target_is_directory=True)
        index_location.clear_cache()
        try:
            index_location.index_dir(sym, "fts5")
            check("symlink-escape-rejected", False)
        except index_location.IndexLocationError:
            check("symlink-escape-rejected", True)
        check("symlink-other-type-ok", index_location.index_dir(sym, "nanograph").parent.parent == sym / ".atlas" / "indexes" / "nanograph")

        # --- ATLAS_INDEX_ROOT override ----------------------------------------
        override = tmp / "override-root"
        os.environ[index_location.OVERRIDE_ENV] = str(override)
        index_location.clear_cache()
        loc = index_location.resolve(plain)
        check(
            "override-absolute",
            loc.project_root == override
            and index_location.index_dir(plain, "fts5") == override / ".atlas" / "indexes" / "fts5" / "local" / want_id.split("/", 1)[1],
            str(loc),
        )
        os.environ[index_location.OVERRIDE_ENV] = "relative/root"
        index_location.clear_cache()
        check("override-relative-ignored", index_location.resolve(plain).project_root == plain)
        os.environ.pop(index_location.OVERRIDE_ENV)
        index_location.clear_cache()

        # --- standalone store in its own work tree -----------------------------
        if fts5_available():
            solo = make_store(tmp / "solo", "2.0")
            git_init(solo)
            commit_all(solo)
            cli("recall", "activate", "--profile", "atlas:ranked", "--root", str(solo), "--json")
            commit_all(solo)
            code, p, out = cli("recall", "index", "build", "--root", str(solo), "--json")
            check("solo-build", code == 0 and p.get("published") is True, out)
            check(
                "solo-index-in-worktree",
                p.get("index_location", {}).get("mode") == "standalone"
                and (solo / ".atlas" / "indexes" / "fts5").is_dir()
                and not (solo / ".atlas-index").exists(),
                str(p.get("index_location")),
            )
            status = git(solo, "status", "--porcelain", "--untracked-files=all").stdout
            check("solo-status-clean", status.strip() == "", status)
            code, p, out = cli("graph", "nodes", "--include-exits", "--root", str(solo), "--json")
            paths = [n.get("path", "") for n in p.get("nodes") or []]
            check("solo-not-projected", code == 0 and paths and not any(x.startswith(".atlas") for x in paths), out[:400])
            code, p, out = cli("validate", "--root", str(solo), "--json")
            items = [i for key in ("critical", "warnings", "info") for i in p.get(key) or [] if isinstance(i, dict)]
            check(
                "solo-validate-skips-atlas",
                code == 0 and not any(str(i.get("path") or "").startswith(".atlas") for i in items),
                out[:400],
            )

            # --- legacy fts5 read ---------------------------------------------
            leg = make_store(tmp / "legacy-fts", "2.0")
            cli("recall", "activate", "--profile", "atlas:ranked", "--root", str(leg), "--json")
            code, p, out = cli("recall", "index", "build", "--root", str(leg), "--json")
            check("legacy-seed-build", code == 0 and p.get("published") is True, out)
            index_location.clear_cache()
            legacy = to_legacy_fts5(leg)
            shutil.rmtree(leg / ".atlas")
            before = tree_snapshot(legacy)
            code, p, out = cli("recall", "run", "ranking", "--root", str(leg), "--json")
            check("legacy-read-served", code == 0 and p.get("count", 0) > 0, out)
            check("legacy-read-warning", "legacy_index_location" in warning_codes(p), out)
            msg = next((w["message"] for w in p.get("warnings") or [] if isinstance(w, dict)), "")
            check(
                "legacy-warning-text",
                ".atlas-index/recall" in msg and ".atlas/indexes/fts5/local/" in msg and "0.14.x" in msg,
                msg,
            )
            code, p, out = cli("recall", "run", "ranking", "--root", str(leg))
            check("legacy-warning-stderr", code == 0 and "deprecated index" in out, out[-400:])
            code, p, out = cli("recall", "status", "--root", str(leg), "--json")
            check("legacy-status-warning", code == 0 and "legacy_index_location" in warning_codes(p), out[:400])
            check("legacy-untouched-after-read", tree_snapshot(legacy) == before)
            check("legacy-no-new-dir-on-read", not (leg / ".atlas" / "indexes" / "fts5").exists())

            # bm25 fast path (recall disabled) on a second legacy store.
            leg2 = make_store(tmp / "legacy-bm25", "2.0")
            cli("recall", "activate", "--profile", "atlas:ranked", "--root", str(leg2), "--json")
            cli("compile", "--root", str(leg2), "--json")
            cli("recall", "disable", "--root", str(leg2), "--json")
            index_location.clear_cache()
            to_legacy_fts5(leg2)
            shutil.rmtree(leg2 / ".atlas")
            code, p, out = cli("recall", "run", "ranking", "--engine", "bm25", "--root", str(leg2), "--json")
            check(
                "legacy-bm25-fast-path",
                code == 0
                and p.get("fast_path") is True
                and p.get("count", 0) > 0
                and "legacy_index_location" in warning_codes(p),
                out[:400],
            )
            check("legacy-bm25-no-new-dir", not (leg2 / ".atlas").exists())
            code, p, out = cli("recall", "index", "build", "--root", str(leg), "--json")
            check("legacy-rebuild", code == 0 and p.get("published") is True, out)
            check(
                "legacy-rebuild-new-location",
                (leg / ".atlas" / "indexes" / "fts5" / "local" / local_id(leg).split("/", 1)[1] / "current.json").is_file(),
            )
            check("legacy-untouched-after-build", tree_snapshot(legacy) == before)
            code, p, out = cli("recall", "run", "ranking", "--root", str(leg), "--json")
            check("legacy-warning-gone", code == 0 and p.get("count", 0) > 0 and not warning_codes(p), out)

        # --- legacy nanograph read (fake binary) ------------------------------
        fake = write_fake(tmp / "nanograph")
        gstore = make_graph_store(tmp / "gstore")
        log = tmp / "nanograph.log"
        nenv = {"ATLAS_PLATFORM_OVERRIDE": "darwin-arm64", "ATLAS_NANOGRAPH_BIN": str(fake), "FAKE_NANOGRAPH_LOG": str(log)}

        def ncli(*args: str) -> tuple[int, dict, str]:
            return cli(*args, "--root", str(gstore), "--json", env=nenv)

        code, p, out = ncli("recall", "run", "hub", "--engine", "nanograph")
        check("nano-seed", code == 0 and p.get("engine_used") == "nanograph", out)
        index_location.clear_cache()
        new_base = index_location.index_dir(gstore, "nanograph")
        gen = (p.get("nanograph_index") or {}).get("generation", "")
        nlegacy = gstore / ".atlas-index" / "nanograph"
        nlegacy.mkdir(parents=True)
        shutil.move(str(new_base / gen), str(nlegacy / gen))
        shutil.rmtree(gstore / ".atlas")
        nbefore = tree_snapshot(nlegacy)
        inits = len([e for e in read_log(log) if e["argv"][:1] == ["init"]])
        code, p, out = ncli("recall", "run", "hub", "--engine", "nanograph")
        ni = p.get("nanograph_index") or {}
        check(
            "nano-legacy-read",
            code == 0 and p.get("engine_used") == "nanograph" and ni.get("legacy") is True and ni.get("path") == f".atlas-index/nanograph/{gen}",
            out,
        )
        check("nano-legacy-warning", "legacy_index_location" in warning_codes(p), out)
        check("nano-legacy-no-rebuild", len([e for e in read_log(log) if e["argv"][:1] == ["init"]]) == inits)
        code, p, out = ncli("graph", "neighbours", "work/hub.md", "--driver", "nanograph")
        check("nano-legacy-neighbours", code == 0 and p.get("driver_used") == "nanograph" and "legacy_index_location" in warning_codes(p), out)
        check("nano-legacy-untouched", tree_snapshot(nlegacy) == nbefore)
        check("nano-legacy-no-new-dir", not (gstore / ".atlas").exists())
        (gstore / "notes" / "extra.md").write_text(
            "---\ntype: lesson\ntitle: Extra\ncreated: 2026-09-09\n---\n\nExtra hub note.\n", encoding="utf-8"
        )
        code, p, out = ncli("recall", "run", "hub", "--engine", "nanograph")
        ni = p.get("nanograph_index") or {}
        check(
            "nano-rebuild-new-location",
            code == 0
            and ni.get("reused") is False
            and not ni.get("legacy")
            and str(ni.get("path", "")).startswith(".atlas/indexes/nanograph/local/")
            and (new_base / ni.get("generation", "x") / "ready.json").is_file(),
            out,
        )
        check("nano-warning-gone", "legacy_index_location" not in warning_codes(p), out)
        check("nano-legacy-untouched-after-build", tree_snapshot(nlegacy) == nbefore)
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'FAILED: ' + ', '.join(failed) if failed else 'all index location checks passed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
