#!/usr/bin/env python3
"""Copilot review CR8 for packet MB.

A mesh index safety refusal (an ``OSError`` such as a pre-existing symlink at
``_mesh/current.json``) must fail the CLI cleanly with the structured exit-2
payload, not an uncaught exception. Linux-safe: no network.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from test_mesh_graph import ALPHA, as_json, atlas, contract, write  # noqa: E402

FAILURES: list[str] = []
CANARY = "CR8MB-PAGE-CANARY\n"


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if not ok and detail != "" else ""))
    if not ok:
        FAILURES.append(name)


def run(tmp: Path) -> None:
    project = tmp / "proj"
    alpha = project / "atlas" / "alpha"
    contract(alpha, ALPHA, "Alpha")
    page = alpha / "notes" / "page.md"
    write(page, CANARY)
    (project / "atlas-mesh.json").write_text(
        json.dumps({"version": 1, "stores": [{"id": ALPHA, "path": "atlas/alpha"}]}, indent=2) + "\n",
        encoding="utf-8",
    )
    before = page.read_bytes()
    pointer_dir = project / ".atlas" / "indexes" / "graph" / "_mesh"
    pointer_dir.mkdir(parents=True)
    (pointer_dir / "current.json").symlink_to(page)

    p = atlas("graph", "edges", "--all", "--scope", "mesh", "--root", str(alpha), "--json")
    payload = as_json(p)
    check("exit-2", p.returncode == 2, (p.returncode, p.stderr[-400:]))
    check("no-traceback", "Traceback" not in p.stderr, p.stderr[-400:])
    check("structured-payload", payload.get("ok") is False and payload.get("scope") == "mesh", payload)
    check("page-unchanged", page.read_bytes() == before)
    check("symlink-left", (pointer_dir / "current.json").is_symlink())


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr8-"))
    try:
        run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {', '.join(FAILURES)}")
        return 1
    print("OK: mesh review MB CR8 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
