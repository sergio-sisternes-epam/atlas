#!/usr/bin/env python3
"""atlas-dream helper regressions. Run: python3 scripts/test_atlas_dream.py"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DREAM = ROOT / "scripts" / "atlas_dream.py"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(DREAM), *args], cwd=ROOT, text=True, capture_output=True)


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def page(root: Path, key: str, front: str, body: str) -> None:
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{front.strip()}\n---\n\n{body.strip()}\n", encoding="utf-8")


def store(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SCHEMA.json").write_text('{"schema_version": "1.0"}\n', encoding="utf-8")
    page(root, "notes/index.md", "type: index\ntitle: Notes", "- [a](a.md)")
    # number conflict across two live pages
    page(root, "notes/cadence-a.md", 'type: lesson\ntitle: Cadence A\ncreated: "2026-01-01"',
         "Run the nightly backup job every 15 minutes on the shared runner pool.")
    page(root, "notes/cadence-b.md", 'type: lesson\ntitle: Cadence B\ncreated: "2026-02-01"',
         "Run the nightly backup job every 5 minutes on the shared runner pool.")
    # polarity conflict
    page(root, "notes/push-a.md", 'type: lesson\ntitle: Push A\ncreated: "2026-01-01"',
         "Release agents push directly to the protected main branch after a review.")
    page(root, "notes/push-b.md", 'type: lesson\ntitle: Push B\ncreated: "2026-02-01"',
         "Release agents never push directly to the protected main branch after a review.")
    # supersede edge whose target is still live
    page(root, "notes/old-rule.md", 'type: decision\ntitle: Old rule\ncreated: "2026-01-01"\nstatus: stable',
         "The archive is rotated by hand at the end of every quarter by the operator.")
    page(root, "notes/new-rule.md",
         'type: decision\ntitle: New rule\ncreated: "2026-03-01"\nrelates_to:\n  - path: notes/old-rule.md\n    kind: supersedes',
         "The archive is rotated automatically by the scheduler on the first day of each month.")
    # supersede edge whose target is already marked: no finding
    page(root, "notes/gone.md", 'type: decision\ntitle: Gone\ncreated: "2026-01-01"\nstatus: superseded',
         "Weekly status digests are mailed to every subscriber on Friday afternoon.")
    page(root, "notes/kept.md",
         'type: decision\ntitle: Kept\ncreated: "2026-03-01"\nrelates_to:\n  - path: notes/gone.md\n    kind: supersedes',
         "Status changes are posted to the shared channel only when something changes.")
    # same title, no edge, and identical bodies
    body = "Keep one canonical owner for every durable decision and link the others to it."
    page(root, "notes/owner-1.md", 'type: lesson\ntitle: Owner rule\ncreated: "2026-01-01"', body)
    page(root, "notes/owner-2.md", 'type: lesson\ntitle: Owner rule\ncreated: "2026-02-01"', body)


class DreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "store"
        self.out = Path(self.tmp.name) / "out"
        store(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def report(self, *extra: str) -> tuple[int, dict]:
        res = run("report", "--root", str(self.root), "--json", *extra)
        self.assertIn(res.returncode, (0, 1), res.stderr)
        return res.returncode, json.loads(res.stdout)

    def test_finds_each_kind_with_verbatim_quotes(self) -> None:
        before = tree_hash(self.root)
        code, rep = self.report("--out-dir", str(self.out))
        self.assertEqual(code, 1)
        self.assertEqual(tree_hash(self.root), before, "the store must not change")
        kinds = {(f["kind"], f.get("reason")) for f in rep["findings"]}
        for want in (("conflict-candidate", "number"), ("conflict-candidate", "polarity"),
                     ("supersede-unmarked", None), ("same-title", None),
                     ("duplicate-page", None), ("duplicate-claim", None)):
            self.assertIn(want, kinds)
        for f in rep["findings"]:
            for q in f["quotes"]:
                lines = (self.root / q["path"]).read_text(encoding="utf-8").split("\n")
                self.assertEqual(lines[q["line"] - 1].rstrip(), q["text"])
        self.assertTrue((self.out / "dream.json").is_file())
        self.assertIn("conflict-candidate", (self.out / "dream.md").read_text(encoding="utf-8"))

    def test_marked_supersede_and_index_pages_are_quiet(self) -> None:
        _, rep = self.report()
        unmarked = [f for f in rep["findings"] if f["kind"] == "supersede-unmarked"]
        self.assertEqual([f["pages"] for f in unmarked], [["notes/new-rule.md", "notes/old-rule.md"]])
        self.assertFalse(any("notes/gone.md" in f["pages"] for f in rep["findings"]))
        self.assertFalse(any("notes/index.md" in f["pages"] for f in rep["findings"]))

    def test_clean_target_exits_zero(self) -> None:
        clean = self.root / "clean"
        page(self.root, "clean/only.md", "type: lesson\ntitle: Only", "A single page cannot disagree with itself here.")
        code, rep = self.report("--target", "clean")
        self.assertEqual((code, rep["findings"], rep["pages"]), (0, [], 1))
        self.assertTrue(clean.is_dir())

    def test_refusals_write_nothing(self) -> None:
        before = tree_hash(self.root)
        inside = run("report", "--root", str(self.root), "--out-dir", str(self.root / "out"))
        self.assertEqual(inside.returncode, 2)
        self.assertIn("outside the store", inside.stderr)
        ceiling = run("report", "--root", str(self.root), "--cost-ceiling", "2")
        self.assertEqual(ceiling.returncode, 2)
        not_store = run("report", "--root", str(self.out.parent))
        self.assertEqual(not_store.returncode, 2)
        self.assertEqual(tree_hash(self.root), before)


if __name__ == "__main__":
    unittest.main()
