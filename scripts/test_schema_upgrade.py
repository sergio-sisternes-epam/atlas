#!/usr/bin/env python3
"""SCHEMA 1.0 -> 2.0 upgrade tests."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-upgrade-"))
    store = tmp / "store"
    r = run(["init", "--root", str(store), "--json"])
    check("init-1.0", r.returncode == 0)
    schema = json.loads((store / "SCHEMA.json").read_text())
    check("init-default-1.0", schema.get("schema_version") == "1.0" and "recall" not in schema)

    schema["relations"] = {"authoritative": "frontmatter"}
    (store / "SCHEMA.json").write_text(json.dumps(schema, indent=2) + "\n")
    preview = run(["schema", "upgrade", "--root", str(store), "--json"])
    payload = json.loads(preview.stdout) if preview.stdout.strip().startswith("{") else {}
    check("upgrade-preview", payload.get("ok") is True and payload.get("to") == "2.0", preview.stdout[:200])

    applied = run(["schema", "upgrade", "--apply", "--root", str(store), "--json"])
    payload = json.loads(applied.stdout) if applied.stdout.strip().startswith("{") else {}
    schema = json.loads((store / "SCHEMA.json").read_text())
    check(
        "upgrade-apply",
        applied.returncode == 0 and schema.get("schema_version") == "2.0",
        applied.stderr[:200] or applied.stdout[:200],
    )
    check("upgrade-does-not-enable", schema.get("recall", {}).get("enabled") is False)
    check("compat-overlay", (store / "schema.d" / "atlas-compat-v1.json").is_file())

    search = run(["search", "Initialised", "--root", str(store), "--json"])
    sp = json.loads(search.stdout) if search.stdout.strip().startswith("{") else {}
    check("legacy-search-until-opt-in", search.returncode == 0 and "recall" not in sp)

    act = run(["recall", "activate", "--profile", "atlas:scan", "--root", str(store), "--json"])
    check("activate-scan", act.returncode == 0, act.stderr[:200] or act.stdout[:200])
    tgrep = run(["recall", "activate", "--profile", "atlas:tgrep", "--root", str(store), "--json"])
    check("tgrep-activate", tgrep.returncode == 0, tgrep.stderr[:200] or tgrep.stdout[:200])
    tsearch = run(["search", "Initialised", "--root", str(store), "--profile", "atlas:tgrep", "--json"])
    tp = json.loads(tsearch.stdout) if tsearch.stdout.strip().startswith("{") else {}
    if shutil.which("tgrep"):
        check(
            "tgrep-search-honest",
            tsearch.returncode in (0, 1, 2) and "serve" not in str(tp.get("error") or "").lower(),
            str(tp.get("error") or tp.get("engine_used")),
        )
    else:
        check(
            "tgrep-search-needs-binary",
            tsearch.returncode == 2 and "tgrep_binary_missing" in str(tp.get("error") or tsearch.stderr),
            str(tp.get("error") or tsearch.stderr[:200]),
        )

    v2 = tmp / "v2"
    r = run(["init", "--root", str(v2), "--schema-version", "2.0", "--json"])
    schema = json.loads((v2 / "SCHEMA.json").read_text())
    check("init-2.0-disabled", r.returncode == 0 and schema.get("recall", {}).get("enabled") is False)

    print("Failed:" if failed else "ok", ", ".join(failed))
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
