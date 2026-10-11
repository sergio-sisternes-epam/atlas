#!/usr/bin/env python3
"""Copilot review CR6 for packet MB.

1. ``atlas graph export`` (store scope) refuses ``--out out-link`` when that
   leaf is a symlink to an outside directory. Containment uses the resolved
   path; the writer is given the lexical path and does not follow the link.
2. The same refusal for ``atlas graph export --scope mesh``.
3. A recall sqlite placeholder swapped for a symlink between creation and
   ``sqlite3.connect`` is refused. The link target stays byte-identical.
4. ``atlas graph edges --to`` accepts a canonical ``atlas://`` URI whose store
   is not a mesh row, so an unresolved edge from ``edges --all`` can be
   filtered. A non-canonical ``--to`` still errors. ``--from`` and neighbour
   seeds stay strict.

Linux-safe: no network, no git.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core.recall_index import _write_sqlite  # noqa: E402
from atlas_cli.core import recall_index  # noqa: E402
from test_mesh_graph import ALPHA, BETA, ELSEWHERE, build_mesh, contract, page, write  # noqa: E402

FAILURES: list[str] = []
GRAPH_BYTES = b'{"canary":"graph-cr6"}\n'
RECEIPT_BYTES = b'{"canary":"receipt-cr6"}\n'


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if not ok and detail != "" else ""))
    if not ok:
        FAILURES.append(name)


def env() -> dict[str, str]:
    kept = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_")}
    kept["DBUS_SESSION_BUS_ADDRESS"] = "disabled:"
    kept["PATH"] = os.environ.get("PATH", "")
    return kept


def atlas(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        env=env(),
    )


def as_json(proc: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_raw": proc.stdout, "_err": proc.stderr}


def _seed_target(target: Path) -> None:
    target.mkdir(parents=True)
    (target / "graph.json").write_bytes(GRAPH_BYTES)
    (target / "export-receipt.json").write_bytes(RECEIPT_BYTES)


def _unchanged(target: Path) -> bool:
    return (target / "graph.json").read_bytes() == GRAPH_BYTES and (
        target / "export-receipt.json"
    ).read_bytes() == RECEIPT_BYTES


def test_cli_export_refuses_out_link(tmp: Path, *, scope: str, root: Path) -> None:
    target = tmp / "target"
    _seed_target(target)
    work = tmp / "work"
    work.mkdir(parents=True)
    link = work / "out-link"
    link.symlink_to(target, target_is_directory=True)
    proc = atlas(
        "graph",
        "export",
        "--scope",
        scope,
        "--format",
        "json",
        "--out",
        "out-link",
        "--root",
        str(root),
        "--json",
        cwd=work,
    )
    payload = as_json(proc)
    error = str(payload.get("error") or proc.stderr or proc.stdout)
    check(
        f"export-{scope}-out-link-refused",
        proc.returncode == 2
        and payload.get("ok") is False
        and "symlink" in error.lower()
        and "out-link" in error
        and _unchanged(target)
        and link.is_symlink(),
        (proc.returncode, error, (target / "graph.json").read_bytes()[:40]),
    )


def test_store_export(tmp: Path) -> None:
    print("store export refuses a symlinked --out leaf")
    store = tmp / "store"
    contract(store, ALPHA, "Alpha")
    write(store / "notes" / "page.md", page("Page"))
    test_cli_export_refuses_out_link(tmp, scope="store", root=store)


def test_mesh_export(tmp: Path) -> None:
    print("mesh export refuses a symlinked --out leaf")
    project = build_mesh(tmp)
    alpha = project / "atlas" / "alpha"
    test_cli_export_refuses_out_link(tmp / "cli", scope="mesh", root=alpha)


def test_sqlite_swap(tmp: Path) -> None:
    print("recall sqlite refuses a symlink swapped in before connect")
    tmp.mkdir(parents=True, exist_ok=True)
    victim = tmp / "victim"
    victim.write_bytes(b"")
    before = victim.read_bytes()
    placeholder = tmp / "projection.sqlite"
    swapped = {"n": 0}
    real_connect = recall_index.sqlite3.connect

    def hooked(*args: object, **kwargs: object) -> object:
        if swapped["n"] == 0:
            swapped["n"] = 1
            if placeholder.is_symlink() or placeholder.exists():
                placeholder.unlink()
            placeholder.symlink_to(victim)
        return real_connect(*args, **kwargs)

    recall_index.sqlite3.connect = hooked  # type: ignore[assignment]
    try:
        try:
            _write_sqlite(placeholder, [], "digest")
            error = ""
        except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
            error = str(exc)
    finally:
        recall_index.sqlite3.connect = real_connect
    after = victim.read_bytes()
    check(
        "sqlite-swap-refused",
        swapped["n"] == 1
        and bool(error)
        and "symlink" in error.lower()
        and after == before
        and not after.startswith(b"SQLite format 3")
        and placeholder.is_symlink(),
        (error, after[:24], swapped["n"]),
    )


def test_edges_to_non_member(tmp: Path) -> None:
    print("edges --to filters an unresolved canonical non-member target")
    project = build_mesh(tmp)
    alpha = project / "atlas" / "alpha"
    elsewhere = f"atlas://{ELSEWHERE}/notes/e.md"
    grand = f"atlas://{BETA}/notes/grand.md"
    listed = atlas("graph", "edges", "--all", "--scope", "mesh", "--root", str(alpha), "--json")
    unresolved = [e for e in as_json(listed).get("edges") or [] if e.get("to") == elsewhere]
    check("fixture-unresolved-non-member", listed.returncode == 0 and len(unresolved) == 1, unresolved or listed.stdout[:300])
    if not unresolved:
        return
    want = unresolved[0]
    filtered = atlas("graph", "edges", "--to", elsewhere, "--scope", "mesh", "--root", str(alpha), "--json")
    got = [
        e
        for e in as_json(filtered).get("edges") or []
        if e.get("from") == want.get("from") and e.get("to") == want.get("to") and e.get("kind") == want.get("kind")
    ]
    check(
        "edges-to-non-member",
        filtered.returncode == 0 and len(got) == 1 and got[0].get("resolved") is False and got[0].get("from") == grand,
        (filtered.returncode, as_json(filtered).get("error"), got),
    )
    fragment = atlas(
        "graph", "edges", "--to", f"{elsewhere}#section", "--scope", "mesh", "--root", str(alpha), "--json"
    )
    frag_to = {e.get("to") for e in as_json(fragment).get("edges") or []}
    check(
        "edges-to-normalised",
        fragment.returncode == 0 and elsewhere in frag_to,
        (fragment.returncode, as_json(fragment).get("error"), frag_to),
    )
    short = atlas("graph", "edges", "--to", "atlas://elsewhere/notes/e.md", "--scope", "mesh", "--root", str(alpha), "--json")
    check(
        "edges-to-noncanonical-errors",
        short.returncode == 2 and as_json(short).get("ok") is False,
        short.stdout[:300],
    )
    frm = atlas("graph", "edges", "--from", elsewhere, "--scope", "mesh", "--root", str(alpha), "--json")
    check("edges-from-non-member-still-errors", frm.returncode == 2 and as_json(frm).get("ok") is False, frm.stdout[:300])
    seed = atlas("graph", "neighbours", elsewhere, "--scope", "mesh", "--root", str(alpha), "--json")
    check("neighbours-non-member-still-errors", seed.returncode == 2 and as_json(seed).get("ok") is False, seed.stdout[:300])


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr6-"))
    try:
        test_store_export(tmp / "store")
        test_mesh_export(tmp / "mesh")
        test_sqlite_swap(tmp / "sqlite")
        test_edges_to_non_member(tmp / "edges")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILURES:
        print(f"\n{len(FAILURES)} mesh review CR6 check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("\nAll mesh review CR6 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
