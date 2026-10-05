#!/usr/bin/env python3
"""atlas-optimise helper regressions. Run: python3 scripts/test_atlas_optimise.py"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
OPT = ROOT / "scripts" / "atlas_optimise.py"

sys.path.insert(0, str(ROOT / "scripts"))
from atlas_cli.core.schema import CURRENT_RELEASE  # noqa: E402


def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script), *args], cwd=ROOT, text=True, capture_output=True)


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def page(path: Path, front: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{front.strip()}\n---\n\n{body.strip()}\n", encoding="utf-8")


MEM_DESC = "Topic memory holds the durable claim about the topic."


def shared_parent_store(base: Path) -> Path:
    """Pages already share one parent; index still cues a deleted frame.md; gist is stale."""
    root = base / "store"
    root.mkdir()
    assert run(ATLAS, "init", "--root", str(root)).returncode == 0
    notes = root / "notes"
    page(notes / "topic.md", f"""
type: memory
title: Topic memory
created: 2026-10-05
description: {MEM_DESC}
""", "## Content\n\nThe topic memory records one durable claim with enough body text to pass.")
    page(notes / "topic.gist.md", """
type: gist
title: Topic gist
created: 2026-10-05
description: A shorter wording that is not in the memory page.
relates_to:
  - path: notes/topic.md
    kind: derived_from
""", "## Content\n\nGist of the topic memory with enough body text for compile checks.\n\n- [Topic](topic.md)")
    page(notes / "schema.schema.md", """
type: schema
title: Notes schema
created: 2026-10-05
relates_to:
  - path: notes/topic.gist.md
    kind: related
""", "## Content\n\nSchema for the notes folder gists, long enough to satisfy body checks.")
    (notes / "index.md").write_text(
        "# Notes\n\n- [Topic gist](topic.gist.md)\n- [Folder frame](frame.md)\n- [Notes schema](./schema.schema.md)\n",
        encoding="utf-8",
    )
    with (root / "index.md").open("a", encoding="utf-8") as f:
        f.write("\n- [Notes](notes/index.md)\n")
    return root


def plan(root: Path, out: Path | None = None, *extra: str) -> tuple[int, dict]:
    args = ["plan", "--root", str(root), "--target", ".", "--json", *extra]
    if out is not None:
        args += ["--out-dir", str(out)]
    r = run(OPT, *args)
    return r.returncode, json.loads(r.stdout)


def tasks(p: dict) -> list[dict]:
    return [t for ts in p["folders"].values() for t in ts]


def compile_findings(root: Path) -> tuple[int, set[str]]:
    r = run(ATLAS, "compile", "--root", str(root), "--dry-run", "--json")
    data = json.loads(r.stdout)
    return r.returncode, {f["id"] for f in data.get("critical", [])}


class OptimiseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_target_required(self) -> None:
        root = shared_parent_store(self.base)
        before = tree_hash(root)
        self.assertEqual(run(OPT, "plan", "--root", str(root)).returncode, 2)
        self.assertEqual(run(OPT, "apply", "--root", str(root), "--plan", "x.json").returncode, 2)
        self.assertEqual(run(OPT, "plan", "--root", str(root), "--target", "missing").returncode, 2)
        self.assertEqual(tree_hash(root), before)

    def test_shared_parent_does_not_stop_early(self) -> None:
        root = shared_parent_store(self.base)
        self.assertIn("stale_upper_page", compile_findings(root)[1])
        before = tree_hash(root)
        code, p = plan(root, self.base / "out")
        self.assertEqual(code, 1)
        self.assertEqual(tree_hash(root), before, "plan must not write in the store")
        by_kind = {(t["kind"], t["class"]) for t in tasks(p)}
        self.assertIn(("dead-index-cue", "auto"), by_kind)
        self.assertIn(("stale-gist-description", "auto"), by_kind)
        self.assertTrue((self.base / "out" / "tasks" / "notes.md").is_file())
        self.assertTrue((self.base / "out" / "tasks" / "root.md").is_file())
        r = run(OPT, "apply", "--root", str(root), "--target", ".", "--plan", str(self.base / "out" / "plan.json"))
        self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
        self.assertNotIn("frame.md", (root / "notes" / "index.md").read_text())
        code, crit = compile_findings(root)
        self.assertNotIn("stale_upper_page", crit)
        self.assertNotIn("schema_missing_from_index", crit)
        self.assertNotIn("schema_folder", crit)

    def test_no_invented_gist_text(self) -> None:
        root = shared_parent_store(self.base)
        notes = root / "notes"
        page(notes / "bare.md", """
type: memory
title: Bare memory
created: 2026-10-05
""", "## Content\n\nA memory page without any description field at all, long enough.")
        page(notes / "bare.gist.md", """
type: gist
title: Bare gist
created: 2026-10-05
description: Words that the bare memory never says.
relates_to:
  - path: notes/bare.md
    kind: derived_from
""", "## Content\n\nGist of the bare memory with enough words for the body check.")
        memory_before = (notes / "topic.md").read_bytes()
        bare_gist_before = (notes / "bare.gist.md").read_bytes()
        code, p = plan(root, self.base / "out")
        stale = {t["paths"][0]: t["class"] for t in tasks(p) if t["kind"] == "stale-gist-description"}
        self.assertEqual(stale["notes/topic.gist.md"], "auto")
        self.assertEqual(stale["notes/bare.gist.md"], "handoff")
        run(OPT, "apply", "--root", str(root), "--target", ".", "--plan", str(self.base / "out" / "plan.json"))
        self.assertEqual((notes / "topic.md").read_bytes(), memory_before, "memory page must not be edited")
        self.assertEqual((notes / "bare.gist.md").read_bytes(), bare_gist_before, "handoff gist untouched")
        gist = (notes / "topic.gist.md").read_text()
        self.assertIn(f"description: {MEM_DESC}\n", gist)
        self.assertIn(MEM_DESC, (notes / "topic.md").read_text())

    def test_out_dir_inside_store_refused(self) -> None:
        root = shared_parent_store(self.base)
        before = tree_hash(root)
        r = run(OPT, "plan", "--root", str(root), "--target", ".", "--out-dir", str(root / "staging" / "x"))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(tree_hash(root), before)

    def test_stale_plan_refused(self) -> None:
        root = shared_parent_store(self.base)
        plan(root, self.base / "out")
        gist = root / "notes" / "topic.gist.md"
        gist.write_text(gist.read_text() + "\nEdited after plan.\n", encoding="utf-8")
        before = tree_hash(root)
        r = run(OPT, "apply", "--root", str(root), "--target", ".", "--plan", str(self.base / "out" / "plan.json"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("stale plan", r.stdout)
        self.assertEqual(tree_hash(root), before)

    def test_precondition_blocks_and_does_not_migrate(self) -> None:
        root = shared_parent_store(self.base)
        contract = json.loads((root / "CONTRACT.json").read_text())
        contract.pop("atlas_release", None)
        contract.pop("memory", None)
        (root / "CONTRACT.json").unlink()
        (root / "SCHEMA.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
        page(root / "notes" / "frame.md", """
type: frame
title: Old frame
created: 2026-10-04
""", "## Content\n\nLegacy folder frame that memory-migrate would convert into a schema page.")
        code, p = plan(root, self.base / "out")
        self.assertEqual(code, 1)
        self.assertIsNotNone(p["precondition"])
        self.assertEqual(p["precondition"]["class"], "handoff")
        page(root / "other" / "frame.md", """
type: frame
title: Other frame
created: 2026-10-04
""", "## Content\n\nA second legacy frame in another folder; not a subject cluster.")
        code, p = plan(root, self.base / "out")
        self.assertNotIn("subject-cluster:frame", {t["id"] for t in tasks(p)})
        others = [t for t in tasks(p) if t["kind"] != "contract-precondition"]
        self.assertTrue(others, "other findings are still listed")
        self.assertTrue(all(t["class"] in ("blocked", "handoff", "report") for t in others))
        before = tree_hash(root)
        r = run(OPT, "apply", "--root", str(root), "--target", ".", "--plan", str(self.base / "out" / "plan.json"))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(tree_hash(root), before)
        self.assertFalse((root / "CONTRACT.json").exists())

    def test_suffix_rename_is_opt_in_and_rewrites_links(self) -> None:
        root = shared_parent_store(self.base)
        code, p = plan(root, self.base / "out")
        suffix = [t for t in tasks(p) if t["kind"] == "layer-suffix"]
        self.assertEqual([t["class"] for t in suffix], ["opt-in"])
        run(OPT, "apply", "--root", str(root), "--target", ".", "--plan", str(self.base / "out" / "plan.json"))
        self.assertTrue((root / "notes" / "topic.md").exists(), "no rename without --include-opt-in")
        plan(root, self.base / "out2")
        r = run(OPT, "apply", "--root", str(root), "--target", ".", "--plan",
                str(self.base / "out2" / "plan.json"), "--include-opt-in")
        self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
        self.assertFalse((root / "notes" / "topic.md").exists())
        self.assertTrue((root / "notes" / "topic.memory.md").exists())
        gist = (root / "notes" / "topic.gist.md").read_text()
        self.assertIn("path: notes/topic.memory.md", gist)
        self.assertIn("(topic.memory.md)", gist)
        code, crit = compile_findings(root)
        self.assertNotIn("internal_links", crit)
        self.assertNotIn("stale_upper_page", crit)

    def test_atlas_uri_mention_blocks_rename(self) -> None:
        root = shared_parent_store(self.base)
        page(root / "notes" / "pointer.md", """
type: decision
title: Pointer
created: 2026-10-05
""", "## Content\n\nSee atlas://example/store/notes/topic.md for the claim; long enough body.")
        code, p = plan(root)
        suffix = [t for t in tasks(p) if t["kind"] == "layer-suffix"]
        self.assertEqual(suffix[0]["class"], "blocked")
        self.assertTrue(any("atlas://" in r for r in suffix[0]["evidence"]["blocked_by"]))

    def test_cluster_moves_only_on_confirm(self) -> None:
        root = shared_parent_store(self.base)
        for folder in ("decisions", "follow-ups"):
            page(root / folder / "hold-pr-1.md", f"""
type: {'decision' if folder == 'decisions' else 'follow-up'}
title: Hold PR 1 {folder}
created: 2026-10-05
""", "## Content\n\nHold the pull request until the maintainer answers; long enough body.")
            (root / folder / "index.md").write_text(f"# {folder}\n\n- [Hold](hold-pr-1.md)\n", encoding="utf-8")
        page(root / "decisions" / "cites.md", """
type: decision
title: Cites
created: 2026-10-05
relates_to:
  - path: follow-ups/hold-pr-1.md
    kind: related
""", "## Content\n\nThis decision cites the follow-up page by path; enough words.\n\n- [f](../follow-ups/hold-pr-1.md)")
        code, p = plan(root)
        report = [t for t in tasks(p) if t["kind"] == "subject-cluster"]
        self.assertEqual([t["class"] for t in report], ["report"])
        (root / "subjects").mkdir()
        (root / "subjects" / "index.md").write_text("# Subjects\n", encoding="utf-8")
        code, p = plan(root, self.base / "out", "--subject-folder", "subjects:hold-pr-1")
        moves = {t["id"]: t["class"] for t in tasks(p) if t["kind"] == "subject-cluster"}
        self.assertEqual(set(moves.values()), {"confirm"})
        planfile = str(self.base / "out" / "plan.json")
        run(OPT, "apply", "--root", str(root), "--target", ".", "--plan", planfile)
        self.assertTrue((root / "follow-ups" / "hold-pr-1.md").exists(), "no move without --confirm")
        code, p = plan(root, self.base / "out2", "--subject-folder", "subjects:hold-pr-1")
        r = run(OPT, "apply", "--root", str(root), "--target", ".", "--plan",
                str(self.base / "out2" / "plan.json"), "--confirm", "subject-cluster:follow-ups/hold-pr-1.md")
        self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
        self.assertTrue((root / "subjects" / "hold-pr-1.md").exists())
        self.assertTrue((root / "decisions" / "hold-pr-1.md").exists(), "unconfirmed sibling stays")
        cites = (root / "decisions" / "cites.md").read_text()
        self.assertIn("path: subjects/hold-pr-1.md", cites)
        self.assertIn("(../subjects/hold-pr-1.md)", cites)

    def test_schema_cue_and_single_schema_coverage(self) -> None:
        root = shared_parent_store(self.base)
        notes = root / "notes"
        (notes / "index.md").write_text("# Notes\n\n- [Topic gist](topic.gist.md)\n", encoding="utf-8")
        page(notes / "extra.gist.md", f"""
type: gist
title: Extra gist
created: 2026-10-05
description: {MEM_DESC}
relates_to:
  - path: notes/topic.md
    kind: derived_from
""", "## Content\n\nA second gist of the same memory, long enough for the body check.")
        code, p = plan(root, self.base / "out")
        kinds = {(t["kind"], t["class"]) for t in tasks(p)}
        self.assertIn(("schema-index-cue", "auto"), kinds)
        self.assertIn(("uncovered-gist", "auto"), kinds)
        run(OPT, "apply", "--root", str(root), "--target", ".", "--plan", str(self.base / "out" / "plan.json"))
        self.assertIn("(./schema.schema.md)", (notes / "index.md").read_text())
        self.assertIn("path: notes/extra.gist.md", (notes / "schema.schema.md").read_text())
        code, crit = compile_findings(root)
        self.assertNotIn("schema_folder", crit)
        self.assertNotIn("schema_missing_from_index", crit)

    def test_no_contract_write_and_stamp(self) -> None:
        self.assertEqual(CURRENT_RELEASE, "0.13.0-beta.7")
        root = shared_parent_store(self.base)
        contract = (root / "CONTRACT.json").read_bytes()
        plan(root, self.base / "out")
        run(OPT, "apply", "--root", str(root), "--target", ".", "--plan", str(self.base / "out" / "plan.json"))
        self.assertEqual((root / "CONTRACT.json").read_bytes(), contract)

    def test_not_wired_into_install_or_compile(self) -> None:
        help_text = run(ATLAS, "--help").stdout
        self.assertNotIn("optimise", help_text)
        for src in (ROOT / "scripts" / "atlas_cli").rglob("*.py"):
            self.assertNotIn("atlas_optimise", src.read_text(encoding="utf-8"), str(src))
        self.assertNotIn("atlas_optimise", (ROOT / "scripts" / "atlas.py").read_text())


if __name__ == "__main__":
    unittest.main()
