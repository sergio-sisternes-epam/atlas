#!/usr/bin/env python3
"""Live nanograph check: runs only on macOS arm64 with a real nanograph >= 1.3.0.

Skips (exit 0) everywhere else. No overrides are honoured: the test refuses to
run while the test harness platform (ATLAS_TEST_PLATFORM or an injected
platform provider) is active, clears ATLAS_NANOGRAPH_BIN and looks for
`nanograph` on PATH through the production entry scripts/atlas.py.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))

os.environ.pop("ATLAS_NANOGRAPH_BIN", None)

from atlas_cli.core import driver_overlay, index_location  # noqa: E402
from atlas_cli.core.driver_overlay import normalise_machine  # noqa: E402
from atlas_cli.core.drivers.nanograph import NanographDriver  # noqa: E402
from test_graph import PAGES, SCHEMA_V1  # noqa: E402


def skip(reason: str) -> int:
    print(f"SKIP: {reason}")
    return 0


def main() -> int:
    if os.environ.get("ATLAS_TEST_PLATFORM") or not driver_overlay.platform_provider_is_real():
        print("REFUSED: the live nanograph test must not run under the test harness platform (unset ATLAS_TEST_PLATFORM)")
        return 2
    real = (sys.platform, normalise_machine(platform.machine()))
    if real != ("darwin", "arm64"):
        return skip(f"nanograph live test needs darwin-arm64, this is {real[0]}-{real[1]}")
    det = NanographDriver().detect()
    if not det.available:
        return skip(det.reason)

    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-nanograph-live-"))
    try:
        store = tmp / "store"
        store.mkdir()
        (store / "SCHEMA.json").write_text(json.dumps(SCHEMA_V1, indent=2) + "\n", encoding="utf-8")
        for rel, text in PAGES.items():
            (store / rel).parent.mkdir(parents=True, exist_ok=True)
            (store / rel).write_text(text, encoding="utf-8")

        def cli(*args: str) -> tuple[int, dict, str]:
            proc = subprocess.run(
                [sys.executable, str(ATLAS), *args, "--root", str(store), "--json"],
                cwd=ROOT, text=True, capture_output=True, env=dict(os.environ),
            )
            try:
                return proc.returncode, json.loads(proc.stdout), proc.stdout + proc.stderr
            except json.JSONDecodeError:
                return proc.returncode, {}, proc.stdout + proc.stderr

        print(f"nanograph {det.version} at {det.binary}")
        runs = [cli("recall", "run", "hub", "--engine", "nanograph") for _ in range(2)]
        code, p, out = runs[0]
        check("recall-live", code == 0 and p.get("engine_used") == "nanograph" and p.get("hits"), out)
        check("recall-live-deterministic", runs[0][1].get("hits") == runs[1][1].get("hits"))

        for q in (
            ("work/hub.md", "--direction", "in"),
            ("cycle/c1.md", "--hops", "3"),
            ("notes/child-a.md", "--hops", "2", "--include-exits"),
        ):
            label = " ".join(q)
            first = cli("graph", "neighbours", *q, "--driver", "nanograph")
            second = cli("graph", "neighbours", *q, "--driver", "nanograph")
            native = cli("graph", "neighbours", *q)
            nano = first[1]
            check(f"neighbours-live-{label}", first[0] == 0 and nano.get("driver_used") == "nanograph" and nano.get("nodes"), first[2])
            check(f"neighbours-live-deterministic-{label}", first[1] == second[1])
            strip = lambda d: {k: v for k, v in d.items() if k != "driver_used"}  # noqa: E731
            check(f"neighbours-live-parity-{label}", strip(nano) == strip(native[1]), f"{nano} != {native[1]}")
        check("no-env-nano", not list(store.rglob(".env.nano")))
        # nanograph init scaffolds nanograph.toml as well; a published generation never keeps it.
        gens = [p.parent for p in index_location.indexes_base(store).rglob("ready.json")]
        check("generation-published", bool(gens))
        leftovers = [str(p) for g in gens for p in g.rglob("*") if p.name in (".env.nano", ".env", "nanograph.toml")]
        check("no-nanograph-toml-in-generation", not leftovers, str(leftovers))
        check("no-nanograph-toml", not list(store.rglob("nanograph.toml")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} live nanograph check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll live nanograph checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
