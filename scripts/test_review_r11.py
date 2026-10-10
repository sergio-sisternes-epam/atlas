#!/usr/bin/env python3
"""Review R11 regressions: the freshness inputs are the overlay bytes the projection reads.

``merge_overlays`` follows a symlinked ``schema.d`` and symlinked ``*.json``
overlays, so the corpus digest must cover the same files (one shared
enumeration) and hash the bytes behind each link, and the cheap fingerprint
must stat the link target. Editing an external overlay (or a symlinked
SCHEMA.json target), even with a same-length edit whose mtime is restored,
changes ``content_digest`` / ``inputs_digest`` and the next bm25 recall
publishes a new generation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import overlay, projection  # noqa: E402
from atlas_cli.core.schema import load_schema  # noqa: E402
from test_graph import SCHEMA_V1  # noqa: E402

CLEAN_ENV = ("ATLAS_RECALL_ENGINE", "ATLAS_TEST_PLATFORM", "ATLAS_NANOGRAPH_BIN", "ATLAS_PLATFORM_OVERRIDE")

PAGES = {
    "index.md": "# Store\n\n- notes\n",
    "notes/index.md": "# Notes\n\n- a\n",
    "notes/a.md": (
        "---\ntype: decision\ntitle: Alpha page\ncreated: 2026-09-09\n---\n\n"
        "## Claim\n\nThe body mentions oldword once for recall.\n"
    ),
}


def overlay_text(value: str) -> str:
    return json.dumps({"contribution_id": "ext-notes", "ext_notes": {"marker": value}}, indent=2) + "\n"


def cli(*args: str) -> tuple[int, dict, str]:
    env = {k: v for k, v in os.environ.items() if k not in CLEAN_ENV}
    proc = subprocess.run([sys.executable, str(ATLAS), *args], cwd=ROOT, text=True, capture_output=True, env=env)
    text = proc.stdout.strip()
    try:
        data = json.loads(text) if text.startswith("{") else {}
    except json.JSONDecodeError:
        data = {}
    return proc.returncode, data, proc.stdout + proc.stderr


def make_store(store: Path, *, schema: bool = True) -> Path:
    store.mkdir(parents=True)
    if schema:
        (store / "SCHEMA.json").write_text(json.dumps(SCHEMA_V1, indent=2) + "\n", encoding="utf-8")
    for rel, text in PAGES.items():
        path = store / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return store


def edit(path: Path, old: str, new: str, *, keep_mtime: bool) -> bool:
    st = path.stat()
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")
    if keep_mtime:
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
        after = path.stat()
        return after.st_size == st.st_size and after.st_mtime_ns == st.st_mtime_ns
    return True


def state(store: Path) -> tuple[str | None, str, str]:
    schema, _ = load_schema(store)
    return (
        projection.content_digest(store, schema),
        projection.inputs_digest(store),
        projection.cheap_fingerprint(store, schema),
    )


def recall(store: Path) -> tuple[int, dict, str]:
    return cli("recall", "run", "oldword", "--engine", "bm25", "--root", str(store), "--json")


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

    tmp = Path(tempfile.mkdtemp(prefix="atlas-r11-"))
    try:

        def edits_rebuild(label: str, store: Path, target: Path, old: str, mid: str, new: str) -> None:
            """Build, then a different-length and a same-length (mtime kept) edit of ``target`` must each rebuild."""
            code, p, out = recall(store)
            gen = p.get("generation")
            check(f"{label}-built", code == 0 and bool(gen) and "notes/a.md" in [h.get("path") for h in p.get("hits") or []], out[-400:])
            code, p, out = recall(store)
            check(f"{label}-warm-reused", code == 0 and p.get("generation") == gen and not p.get("index_rebuilt"), out[-400:])
            for step, (a, b, keep) in enumerate(((old, mid, False), (mid, new, True)), start=1):
                content, inputs, fp = state(store)
                ok = edit(target, a, b, keep_mtime=keep)
                after = state(store)
                check(f"{label}-edit{step}-applied", ok)
                check(f"{label}-edit{step}-content-digest-changes", after[0] != content and after[0] is not None)
                check(f"{label}-edit{step}-inputs-digest-changes", after[1] != inputs)
                if not keep:
                    check(f"{label}-edit{step}-fingerprint-changes", after[2] != fp)
                code, p, out = recall(store)
                new_gen = p.get("generation")
                check(f"{label}-edit{step}-recall-rebuilds", code == 0 and bool(new_gen) and new_gen != gen, out[-400:])
                gen = new_gen
                code, p, out = recall(store)
                check(f"{label}-edit{step}-then-reused", code == 0 and p.get("generation") == gen, out[-400:])

        # === symlinked schema.d =============================================
        def symlinked_dir() -> None:
            ext = tmp / "ext-dir"
            ext.mkdir()
            (ext / "ext-notes.json").write_text(overlay_text("aaaa"), encoding="utf-8")
            (ext / "ext-notes.receipt.json").write_text("{}\n", encoding="utf-8")
            store = make_store(tmp / "dir-store")
            os.symlink(ext, store / "schema.d")
            inputs = projection.projection_inputs(store)
            check(
                "dir-inputs-match-merge",
                [p.name for p in inputs] == ["SCHEMA.json", "ext-notes.json"]
                and inputs[1:] == overlay.overlay_files(store)
                and overlay.list_overlays(store) == ["ext-notes"],
                repr(inputs),
            )
            edits_rebuild("dir", store, ext / "ext-notes.json", "aaaa", "bbbbbb", "cccccc")
            content, inputs_d, _ = state(store)
            (ext / "ext-notes.receipt.json").write_text('{"changed": true}\n', encoding="utf-8")
            check("dir-receipt-excluded", state(store)[:2] == (content, inputs_d))

        attempt("dir", symlinked_dir)

        # === symlinked overlay file =========================================
        def symlinked_file() -> None:
            ext = tmp / "ext-file"
            ext.mkdir()
            target = ext / "shared-overlay.json"
            target.write_text(overlay_text("aaaa"), encoding="utf-8")
            store = make_store(tmp / "file-store")
            (store / "schema.d").mkdir()
            os.symlink(target, store / "schema.d" / "ext-notes.json")
            check("file-listed", [p.name for p in projection.projection_inputs(store)] == ["SCHEMA.json", "ext-notes.json"])
            edits_rebuild("file", store, target, "aaaa", "bbbbbb", "cccccc")

        attempt("file", symlinked_file)

        # === symlinked SCHEMA.json ==========================================
        def symlinked_schema() -> None:
            ext = tmp / "ext-schema"
            ext.mkdir()
            target = ext / "SCHEMA.json"
            target.write_text(json.dumps({**SCHEMA_V1, "title": "Store aaaa"}, indent=2) + "\n", encoding="utf-8")
            store = make_store(tmp / "schema-store", schema=False)
            os.symlink(target, store / "SCHEMA.json")
            for step, (a, b, keep) in enumerate((("aaaa", "bbbbbb", False), ("bbbbbb", "cccccc", True)), start=1):
                content, inputs, fp = state(store)
                check(f"schema-edit{step}-applied", edit(target, a, b, keep_mtime=keep))
                after = state(store)
                check(f"schema-edit{step}-content-digest-changes", after[0] != content and after[0] is not None)
                check(f"schema-edit{step}-inputs-digest-changes", after[1] != inputs)
                if not keep:
                    check(f"schema-edit{step}-fingerprint-changes", after[2] != fp)

        attempt("schema", symlinked_schema)

        # === dangling links: stable marker, distinct from content ===========
        def dangling() -> None:
            store = make_store(tmp / "dangling-store")
            (store / "schema.d").mkdir()
            link = store / "schema.d" / "ext-notes.json"
            os.symlink(tmp / "missing.json", link)
            check("dangling-listed", link in projection.projection_inputs(store) and overlay.list_overlays(store) == ["ext-notes"])
            first = state(store)
            check("dangling-stable", state(store) == first and first[0] is not None)
            marker = projection._input_digest(link)
            check("dangling-marker-not-a-digest", marker.startswith("unreadable"), marker)
            (tmp / "missing.json").write_text("", encoding="utf-8")
            check("dangling-differs-from-empty-content", state(store)[1] != first[1])

        attempt("dangling", dangling)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll review R11 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
