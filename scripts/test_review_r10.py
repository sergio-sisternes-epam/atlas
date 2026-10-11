#!/usr/bin/env python3
"""Review R10 regressions.

1. tgrep subprocesses get the allow-listed external-driver environment. A fake
   ``tgrep`` (a script that records its argv and environment) is run through
   the real :func:`tgrep.run_argv` for the index build and the search, with
   fake ``GITHUB_TOKEN``, ``GH_TOKEN``, ``COPILOT_GITHUB_TOKEN`` and
   ``AWS_SECRET_ACCESS_KEY`` in the parent environment. None of them reach
   either call; ``PATH`` still does. A static check also requires every
   ``subprocess`` call under ``core/drivers/`` to pass
   ``env=external_driver_env(...)`` (never ``os.environ.copy()``, never
   omitted).
2. and 3. ``atlas recall profiles`` and ``atlas recall status`` turn an
   :class:`IndexLocationError` into a structured exit 2: with ``--json``,
   ``{"ok": false, "error": {"code": "index_location_error", ...}, "root":
   ...}``; in text mode, one ``error: ...`` line on stderr; never a traceback.
   The trigger is realistic: an ``atlas-mesh.json`` above the store whose
   duplicate store ids include the store's row (no monkeypatching).
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
DRIVERS = ROOT / "scripts" / "atlas_cli" / "core" / "drivers"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, meshfile  # noqa: E402
from atlas_cli.core.drivers import tgrep  # noqa: E402
from atlas_cli.core.projection import ProjectedPage  # noqa: E402
from test_recall_bm25 import make_store  # noqa: E402

SECRETS = {
    "GITHUB_TOKEN": "ghp_r10_fake_github_token",
    "GH_TOKEN": "gho_r10_fake_gh_token",
    "COPILOT_GITHUB_TOKEN": "r10_fake_copilot_token",
    "AWS_SECRET_ACCESS_KEY": "r10_fake_aws_secret",
}
CLEAN_ENV = ("ATLAS_RECALL_ENGINE", "ATLAS_INDEX_ROOT", "ATLAS_TEST_PLATFORM", "ATLAS_NANOGRAPH_BIN")
SUBPROCESS_CALLS = {"run", "Popen", "call", "check_call", "check_output"}

FAKE_TGREP = """#!{python}
import json, os, sys
with open({log!r}, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({{"argv": sys.argv[1:], "env": dict(os.environ)}}) + "\\n")
sys.exit(1 if sys.argv[1:2] == ["search"] else 0)
"""


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in CLEAN_ENV}
    return subprocess.run([sys.executable, str(ATLAS), *args], cwd=ROOT, text=True, capture_output=True, env=env)


def static_env_violations() -> list[str]:
    """Every subprocess call under core/drivers/ must pass env=external_driver_env(...)."""
    out: list[str] = []
    for path in sorted(DRIVERS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr in SUBPROCESS_CALLS
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            ):
                continue
            where = f"{path.name}:{node.lineno}"
            env = next((kw.value for kw in node.keywords if kw.arg == "env"), None)
            if env is None:
                out.append(f"{where} omits env=")
                continue
            text = ast.unparse(env)
            if "os.environ" in text:
                out.append(f"{where} passes {text}")
            elif not (isinstance(env, ast.Call) and isinstance(env.func, ast.Name) and env.func.id == "external_driver_env"):
                out.append(f"{where} passes {text}, not external_driver_env()")
    return out


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-r10-"))
    saved = {k: os.environ.get(k) for k in (*SECRETS, index_location.OVERRIDE_ENV)}
    try:
        # --- 1. tgrep subprocess environment ------------------------------------
        violations = static_env_violations()
        check("drivers-static-env-allow-list", not violations, "; ".join(violations))

        if os.name == "nt":
            print("  [SKIP] fake tgrep script needs a POSIX shebang")
        else:
            log = tmp / "tgrep-calls.jsonl"
            fake = tmp / "bin" / "tgrep"
            fake.parent.mkdir()
            fake.write_text(FAKE_TGREP.format(python=sys.executable, log=str(log)), encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            os.environ.update(SECRETS)
            os.environ.pop(index_location.OVERRIDE_ENV, None)
            index_location.clear_cache()
            store = tmp / "tgrep-store"
            store.mkdir()
            (store / "SCHEMA.json").write_text("{}\n", encoding="utf-8")
            (store / "hub.md").write_text("# hub\n", encoding="utf-8")
            pages = [ProjectedPage("hub", "hub.md", "concept", "d", {}, "hub", "hub", "")]
            tgrep.search(store, pages, "hub", 5, "a" * 64, binary=fake)
            calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []
            kinds = [c["argv"][0] for c in calls]
            check("tgrep-index-and-search-called", kinds == ["index", "search"], str(kinds))
            for call in calls:
                kind = call["argv"][0]
                leaked = sorted(k for k in SECRETS if k in call["env"])
                values = sorted(k for k, v in SECRETS.items() if v in json.dumps(call["env"]))
                check(f"tgrep-{kind}-no-secrets", not leaked and not values, f"leaked {leaked or values}")
                check(f"tgrep-{kind}-keeps-path", bool(call["env"].get("PATH")), str(sorted(call["env"])))
            for k in SECRETS:
                os.environ.pop(k, None)

        # --- 2./3. recall profiles/status: structured index-location errors ------
        project = tmp / "dup"
        store_a = make_store(project / "stores" / "a", "1.0")
        make_store(project / "stores" / "b", "1.0")
        (project / meshfile.MESH_NAME).write_text(
            json.dumps(
                {
                    "version": 1,
                    "stores": [{"id": "github.com/o/r", "path": "stores/a"}, {"id": "github.com/O/R", "path": "stores/b"}],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        for sub in ("profiles", "status"):
            proc = cli("recall", sub, "--root", str(store_a), "--json")
            try:
                body = json.loads(proc.stdout)
            except json.JSONDecodeError:
                body = {}
            err = body.get("error") if isinstance(body.get("error"), dict) else {}
            check(f"recall-{sub}-json-exit-2", proc.returncode == 2, f"exit {proc.returncode}")
            check(
                f"recall-{sub}-json-shape",
                body.get("ok") is False
                and err.get("code") == "index_location_error"
                and "duplicate store id" in str(err.get("message"))
                and body.get("root") == str(store_a.resolve()),
                proc.stdout[:400],
            )
            check(f"recall-{sub}-json-no-traceback", "Traceback" not in proc.stderr, proc.stderr[-400:])

            proc = cli("recall", sub, "--root", str(store_a))
            lines = proc.stderr.strip().splitlines()
            check(f"recall-{sub}-text-exit-2", proc.returncode == 2, f"exit {proc.returncode}")
            check(f"recall-{sub}-text-no-traceback", "Traceback" not in proc.stderr, proc.stderr[-400:])
            check(
                f"recall-{sub}-text-one-error-line",
                len(lines) == 1 and lines[0].startswith("error: ") and "duplicate store id" in lines[0],
                repr(proc.stderr[-400:]),
            )

        # A healthy store is unaffected.
        healthy = make_store(tmp / "healthy", "1.0")
        for sub in ("profiles", "status"):
            proc = cli("recall", sub, "--root", str(healthy), "--json")
            body = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
            check(f"recall-{sub}-healthy", proc.returncode == 0 and body.get("ok") is True and "tgrep" in body, proc.stdout[:300])
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} review R10 check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll review R10 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
