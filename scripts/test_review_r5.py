#!/usr/bin/env python3
"""Review R5 regressions (test-only harness platform darwin-arm64, fake nanograph).

1. nanograph never sees the user's or project's env files and never leaves
   scaffolding behind: every subprocess runs in a private, empty, 0700
   ``atlas-nanograph-*`` temporary directory that is removed afterwards;
   ``init`` reads a private schema copy; ``nanograph.toml`` / ``.env.nano``
   written by ``init`` into an inferred project directory are removed unless
   they were already there; a published generation never contains
   ``.env.nano``, ``.env`` or ``nanograph.toml``.
2. ``graph neighbours --driver nanograph`` reports nanograph build warnings
   (``atlas_indexes_ignore_failed``) like recall does, without changing the
   exit code.
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
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
TEST_CLI = ROOT / "scripts" / "testing" / "atlas_test_cli.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location  # noqa: E402
from atlas_cli.core.drivers import nanograph as nano_mod  # noqa: E402
from test_drivers import read_log, write_fake  # noqa: E402
from test_graph import PAGES, SCHEMA_V1  # noqa: E402

CLEAN_ENV = ("ATLAS_RECALL_ENGINE", "ATLAS_TEST_PLATFORM", "ATLAS_NANOGRAPH_BIN", "ATLAS_PLATFORM_OVERRIDE", "TMPDIR")
SCAFFOLD = (".env.nano", ".env", "nanograph.toml")
USER_ENV_NANO = "USER_NANO_SETTING=from-user-env-nano\n"
USER_DOTENV = "OPENAI_API_KEY=sk-fake-not-real-secret\nUSER_DOTENV_SETTING=1\n"
PATH_OPTIONS = ("--db", "--schema", "--data", "--query")


def base_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in CLEAN_ENV}


def cli(*args: str, env: dict[str, str]) -> tuple[int, dict, str, str]:
    proc = subprocess.run(
        [sys.executable, str(TEST_CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**base_env(), **env},
    )
    text = proc.stdout.strip()
    try:
        data = json.loads(text) if text.startswith("{") else {}
    except json.JSONDecodeError:
        data = {}
    return proc.returncode, data, proc.stdout + proc.stderr, proc.stderr


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)


def make_project(project: Path, use_git: bool) -> Path:
    project.mkdir(parents=True)
    if use_git:
        git(project, "init", "-q")
    store = project / "kb"
    store.mkdir()
    (store / "SCHEMA.json").write_text(json.dumps(SCHEMA_V1, indent=2) + "\n", encoding="utf-8")
    for rel, text in PAGES.items():
        (store / rel).parent.mkdir(parents=True, exist_ok=True)
        (store / rel).write_text(text, encoding="utf-8")
    return store


def scaffolding(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.name in SCAFFOLD)


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

    tmp = Path(tempfile.mkdtemp(prefix="atlas-r5-")).resolve()
    fake = write_fake(tmp / "nanograph")
    nano_env = {"ATLAS_TEST_PLATFORM": "darwin-arm64", "ATLAS_NANOGRAPH_BIN": str(fake)}
    system_tmp = Path(tempfile.gettempdir()).resolve()

    def build_both(store: Path, env: dict[str, str]) -> list[tuple[int, dict, str]]:
        runs = []
        code, p, out, _ = cli("graph", "neighbours", "work/hub.md", "--driver", "nanograph", "--root", str(store), "--json", env=env)
        runs.append((code, p, out))
        code, p, out, _ = cli("recall", "run", "hub", "--engine", "nanograph", "--root", str(store), "--json", env=env)
        runs.append((code, p, out))
        return runs

    def check_calls(label: str, entries: list[dict], tmp_root: Path) -> None:
        check(f"{label}-calls-logged", any(e["argv"][:1] == ["init"] for e in entries) and any(e["argv"][:1] == ["run"] for e in entries), str(len(entries)))
        bad = [
            (e["argv"][:1], e["cwd"], e["env_in_cwd"])
            for e in entries
            if not Path(e["cwd"]).name.startswith(nano_mod.PRIVATE_PREFIX)
            or Path(e["cwd"]).parent != tmp_root
            or e["cwd_mode"] != 0o700
            or e["env_in_cwd"]
        ]
        check(f"{label}-cwd-private-and-clean", not bad, str(bad[:4]))
        check(f"{label}-cwd-unique", len({e["cwd"] for e in entries}) == len(entries))
        left = sorted({e["cwd"] for e in entries if Path(e["cwd"]).exists()})
        check(f"{label}-cwd-removed", not left, str(left))
        check(f"{label}-no-env-loaded", not any(e["loaded"] for e in entries), str([e["loaded"] for e in entries if e["loaded"]]))
        relative = [
            a for e in entries for i, a in enumerate(e["argv"][1:], 1) if e["argv"][i - 1] in PATH_OPTIONS and not Path(a).is_absolute()
        ]
        check(f"{label}-argv-absolute", not relative, str(relative))
        inits = [e for e in entries if e["argv"][:1] == ["init"]]
        check(
            f"{label}-init-private-schema",
            bool(inits) and all(e["argv"][4] == str(Path(e["cwd"]) / "schema.pg") and e["cwd_entries"] == ["schema.pg"] for e in inits),
            str(inits[:1]),
        )

    try:
        # === 1a. clean project: nothing is scaffolded anywhere =================
        def clean_project() -> None:
            project = tmp / "clean"
            store = make_project(project, use_git=shutil.which("git") is not None)
            log = tmp / "clean.log"
            env = {**nano_env, "FAKE_NANOGRAPH_LOG": str(log)}
            for code, p, out in build_both(store, env):
                check("clean-run-ok", code == 0 and (p.get("driver_used") or p.get("engine_used")) == "nanograph", out[-500:])
            check("clean-no-scaffolding-in-project", not scaffolding(project), str(scaffolding(project)))
            indexes = index_location.indexes_base(store)
            check("clean-indexes-built", any(indexes.rglob("ready.json")), str(indexes))
            check("clean-no-scaffolding-in-indexes", not scaffolding(indexes), str(scaffolding(indexes)))
            check("clean-no-scaffolding-in-store", not scaffolding(store), str(scaffolding(store)))
            check_calls("clean", read_log(log), system_tmp)

        attempt("clean-project", clean_project)

        # === 1b. user env files in the project root and store are never read =====
        def user_env_files() -> None:
            project = tmp / "userenv"
            store = make_project(project, use_git=shutil.which("git") is not None)
            for where in (project, store):
                (where / ".env.nano").write_text(USER_ENV_NANO, encoding="utf-8")
                (where / ".env").write_text(USER_DOTENV, encoding="utf-8")
            log = tmp / "userenv.log"
            env = {**nano_env, "FAKE_NANOGRAPH_LOG": str(log)}
            for code, p, out in build_both(store, env):
                check("userenv-run-ok", code == 0, out[-500:])
            entries = read_log(log)
            check_calls("userenv", entries, system_tmp)
            for where in (project, store):
                kept = (where / ".env.nano").read_text(encoding="utf-8") == USER_ENV_NANO and (where / ".env").read_text(encoding="utf-8") == USER_DOTENV
                check(f"userenv-files-kept-{where.name}", kept)
            check("userenv-no-toml", not (project / "nanograph.toml").exists() and not (store / "nanograph.toml").exists())
            indexes = index_location.indexes_base(store)
            check("userenv-no-scaffolding-in-indexes", not scaffolding(indexes), str(scaffolding(indexes)))
            check("userenv-secret-not-in-env", not any("OPENAI_API_KEY" in e["env_keys"] for e in entries))

        attempt("user-env-files", user_env_files)

        # === 1c. TMPDIR inside the project: init scaffolds into the project root ==
        def tmpdir_inside(pre_existing: bool) -> None:
            label = "inside-kept" if pre_existing else "inside-clean"
            project = tmp / label
            store = make_project(project, use_git=False)
            # Non-git: the store is its own project root, so .atlas/indexes and TMPDIR share it.
            project_root = index_location.resolve(store).project_root
            inner_tmp = project_root / "tmp"
            inner_tmp.mkdir()
            if pre_existing:
                (project_root / ".env.nano").write_text(USER_ENV_NANO, encoding="utf-8")
            log = tmp / f"{label}.log"
            env = {**nano_env, "FAKE_NANOGRAPH_LOG": str(log), "TMPDIR": str(inner_tmp)}
            code, p, out, _ = cli("graph", "neighbours", "work/hub.md", "--driver", "nanograph", "--root", str(store), "--json", env=env)
            check(f"{label}-run-ok", code == 0 and p.get("driver_used") == "nanograph", out[-500:])
            entries = read_log(log)
            check_calls(label, entries, inner_tmp.resolve())
            inits = [e for e in entries if e["argv"][:1] == ["init"]]
            inferred = nano_mod.infer_init_project_dir(Path(inits[0]["cwd"]), inits[0]["argv"][2], inits[0]["argv"][4]) if inits else None
            check(f"{label}-init-inferred-project-root", inferred == project_root.resolve(), f"{inferred} != {project_root}")
            check(f"{label}-toml-removed", not (project_root / "nanograph.toml").exists())
            if pre_existing:
                check(f"{label}-user-env-nano-kept", (project_root / ".env.nano").read_text(encoding="utf-8") == USER_ENV_NANO)
                note = str(p.get("driver_note") or "")
                check(f"{label}-driver-note", ".env.nano" in note and str(project_root.resolve()) in note and "nanograph.toml" not in note, note)
            else:
                check(f"{label}-env-nano-removed", not (project_root / ".env.nano").exists())
                check(f"{label}-no-driver-note", not p.get("driver_note"), str(p.get("driver_note")))
                check(f"{label}-no-scaffolding-anywhere", not scaffolding(project_root), str(scaffolding(project_root)))
            indexes = index_location.indexes_base(store)
            check(f"{label}-no-scaffolding-in-indexes", not scaffolding(indexes), str(scaffolding(indexes)))
            check(f"{label}-tmp-empty", not any(inner_tmp.iterdir()), str(list(inner_tmp.iterdir())))

        attempt("tmpdir-inside-clean", lambda: tmpdir_inside(False))
        attempt("tmpdir-inside-kept", lambda: tmpdir_inside(True))

        # === 1d. unit: inference and the generation scrub ======================
        def units() -> None:
            cwd = Path("/private/cwd")
            check("infer-root-falls-back", nano_mod.infer_init_project_dir(cwd, "/a/db", "/b/schema.pg") == cwd)
            check("infer-common", nano_mod.infer_init_project_dir(cwd, "/p/x/db", "/p/y/s.pg") == Path("/p"))
            check("infer-relative", nano_mod.infer_init_project_dir(cwd, "db", "s.pg") == cwd)
            gen = tmp / "scrub"
            (gen / "atlas.nano" / "sub").mkdir(parents=True)
            for rel in (".env.nano", ".env", "nanograph.toml", "atlas.nano/.env", "atlas.nano/sub/nanograph.toml", "keep.json"):
                (gen / rel).write_text("x", encoding="utf-8")
            removed = nano_mod.scrub_generation(gen)
            check("scrub-recursive", sorted(removed) == [".env", ".env.nano", "atlas.nano/.env", "atlas.nano/sub/nanograph.toml", "nanograph.toml"], str(removed))
            check("scrub-keeps-others", (gen / "keep.json").is_file() and not scaffolding(gen))

        attempt("units", units)

        # === 2. graph neighbours surfaces nanograph build warnings =============
        def graph_warnings() -> None:
            if shutil.which("git") is None:
                print("  [SKIP] git missing; graph build-warning checks skipped")
                return
            control = tmp / "gw-control"
            make_project(control, use_git=True)
            env = {**nano_env}
            ccode, cp, cout, _ = cli("graph", "neighbours", "work/hub.md", "--driver", "nanograph", "--root", str(control / "kb"), "--json", env=env)
            check("gw-control-ok", ccode == 0 and cp.get("driver_used") == "nanograph" and "atlas_indexes_ignore_failed" not in codes(cp.get("warnings")), cout[-500:])

            repo = tmp / "gw-broken"
            store = make_project(repo, use_git=True)
            info_dir = repo / ".git" / "info"
            exclude = info_dir / "exclude"
            if os.geteuid() == 0:
                # chmod does not stop root: make info a file instead (a real guard failure, no hook).
                print("  [NOTE] running as root: using .git/info as a file instead of a read-only info/exclude")
                shutil.rmtree(info_dir, ignore_errors=True)
                info_dir.write_text("not a directory\n", encoding="utf-8")
            else:
                info_dir.mkdir(parents=True, exist_ok=True)
                if not exclude.exists():
                    exclude.write_text("# local\n", encoding="utf-8")
                exclude.chmod(0o444)
            try:
                code, p, out, _ = cli("graph", "neighbours", "work/hub.md", "--driver", "nanograph", "--root", str(store), "--json", env=env)
                check(
                    "gw-json-warning",
                    p.get("driver_used") == "nanograph" and "atlas_indexes_ignore_failed" in codes(p.get("warnings")),
                    out[-800:],
                )
                check("gw-json-exit-unchanged", code == ccode, f"{code} != {ccode}")
                check("gw-json-warning-once", codes(p.get("warnings")).count("atlas_indexes_ignore_failed") == 1, str(codes(p.get("warnings"))))
                shutil.rmtree(repo / ".atlas" / "indexes")
                code, _, out, err = cli("graph", "neighbours", "work/hub.md", "--driver", "nanograph", "--root", str(store), env=env)
                check("gw-text-exit-unchanged", code == ccode, out[-500:])
                check("gw-text-stderr-once", err.count("could not add /.atlas/indexes/") == 1, err[-800:])
            finally:
                if exclude.exists() and not exclude.is_symlink() and info_dir.is_dir():
                    exclude.chmod(0o644)

        attempt("graph-warnings", graph_warnings)
    finally:
        for path in tmp.rglob("*"):
            with contextlib.suppress(OSError):
                if path.is_file() and not path.is_symlink():
                    path.chmod(path.stat().st_mode | stat.S_IWUSR)
        shutil.rmtree(tmp, ignore_errors=True)

    print("Failed:" if failed else "ok", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
