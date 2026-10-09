#!/usr/bin/env python3
"""atlas-optimise helper regressions. Run: python3 scripts/test_atlas_optimise.py"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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

    def test_history_edge_does_not_cover_gist(self) -> None:
        root = shared_parent_store(self.base)
        notes = root / "notes"
        (notes / "index.md").write_text(
            "# Notes\n\n- [Topic gist](topic.gist.md)\n- [Notes schema](./schema.schema.md)\n",
            encoding="utf-8",
        )
        page(notes / "extra.gist.md", f"""
type: gist
title: Extra gist
created: 2026-10-05
description: {MEM_DESC}
relates_to:
  - path: notes/topic.md
    kind: derived_from
""", "## Content\n\nA second gist of the same memory, long enough for the body check.")
        schema = notes / "schema.schema.md"
        schema.write_text(
            schema.read_text(encoding="utf-8").replace(
                "    kind: related\n",
                "    kind: related\n  - path: notes/extra.gist.md\n    kind: related\n    ref: abcdef1234567890\n",
                1,
            ),
            encoding="utf-8",
        )
        _code, planned = plan(root, self.base / "out")
        uncovered = [
            task for task in tasks(planned)
            if task["kind"] == "uncovered-gist" and "notes/extra.gist.md" in task["paths"]
        ]
        self.assertTrue(uncovered, planned)

    def test_referrer_rewrite_keeps_history_edge(self) -> None:
        import atlas_optimise as opt

        root = init_store(self.base)
        page(
            root / "old.md",
            "type: document\ntitle: Old\ncreated: 2026-10-05\nrelates_to: []",
            "## Content\n\nOld page body has enough prose for a concept page.",
        )
        page(
            root / "history-only.md",
            """
type: document
title: History only
created: 2026-10-05
relates_to:
  - path: old.md
    kind: related
    ref: abcdef1234567890
""",
            "## Content\n\nHistory only page has enough prose and no live link.",
        )
        page(
            root / "keeper.md",
            """
type: document
title: Keeper
created: 2026-10-05
relates_to:
  - path: old.md
    kind: related
    ref: abcdef1234567890
  - path: old.md
    kind: related
""",
            "## Content\n\nSee [old](old.md). This keeper page has enough prose.",
        )
        store = opt.Store(root)
        refs = opt._referrers(store, "old.md")
        self.assertNotIn("history-only.md", refs)
        self.assertIn("keeper.md", refs)
        opt._rewrite_refs(store, "old.md", "new.md", refs)
        history_only = (root / "history-only.md").read_text(encoding="utf-8")
        keeper = (root / "keeper.md").read_text(encoding="utf-8")
        self.assertIn("path: old.md", history_only)
        self.assertIn("ref: abcdef1234567890", history_only)
        self.assertNotIn("new.md", history_only)
        history_item, live_item = keeper.split("ref: abcdef1234567890", 1)
        self.assertIn("path: old.md", history_item)
        self.assertNotIn("path: new.md", history_item)
        self.assertIn("path: new.md", live_item)
        self.assertNotIn("(old.md)", keeper)
        self.assertIn("new.md", keeper.split("## Content", 1)[1])

    def test_quoted_ref_key_keeps_history_edge(self) -> None:
        import atlas_optimise as opt

        root = init_store(self.base)
        page(
            root / "old.md",
            "type: document\ntitle: Old\ncreated: 2026-10-05\nrelates_to: []",
            "## Content\n\nOld page body has enough prose for a concept page.",
        )
        page(
            root / "history-only.md",
            """
type: document
title: History only
created: 2026-10-05
relates_to:
  - path: old.md
    kind: related
    'ref': abcdef1234567890
""",
            "## Content\n\nHistory only page has enough prose and no live link.",
        )
        store = opt.Store(root)
        self.assertNotIn("history-only.md", opt._referrers(store, "old.md"))
        opt._rewrite_refs(store, "old.md", "new.md", ["history-only.md"])
        history_only = (root / "history-only.md").read_text(encoding="utf-8")
        self.assertIn("path: old.md", history_only)
        self.assertIn("'ref': abcdef1234567890", history_only)
        self.assertNotIn("new.md", history_only)

    def test_nested_ref_text_does_not_freeze_live_path(self) -> None:
        import atlas_optimise as opt

        root = init_store(self.base)
        page(
            root / "old.md",
            "type: document\ntitle: Old\ncreated: 2026-10-05\nrelates_to: []",
            "## Content\n\nOld page body has enough prose for a concept page.",
        )
        page(
            root / "keeper.md",
            """
type: document
title: Keeper
created: 2026-10-05
relates_to:
  - path: old.md
    kind: related
    note: |
      see ref: not-a-history-edge
  - path: old.md
    kind: related
    meta:
      ref: nested-only
""",
            "## Content\n\nSee [old](old.md). This keeper page has enough prose.",
        )
        store = opt.Store(root)
        self.assertIn("keeper.md", opt._referrers(store, "old.md"))
        opt._rewrite_refs(store, "old.md", "new.md", ["keeper.md"])
        keeper = (root / "keeper.md").read_text(encoding="utf-8")
        self.assertNotIn("path: old.md", keeper)
        self.assertIn("path: new.md", keeper)
        self.assertIn("see ref: not-a-history-edge", keeper)
        self.assertIn("ref: nested-only", keeper)
        self.assertNotIn("(old.md)", keeper)

    def test_no_contract_write_and_stamp(self) -> None:
        self.assertEqual(CURRENT_RELEASE, "0.13.0")
        root = shared_parent_store(self.base)
        contract = (root / "CONTRACT.json").read_bytes()
        self.assertEqual(json.loads(contract)["atlas_release"], "0.13.0")
        plan(root, self.base / "out")
        run(OPT, "apply", "--root", str(root), "--target", ".", "--plan", str(self.base / "out" / "plan.json"))
        self.assertEqual((root / "CONTRACT.json").read_bytes(), contract)

    def test_beta7_and_final_stamps_are_accepted_alike(self) -> None:
        results = {}
        for stamp in ("0.13.0-beta.7", "0.13.0"):
            with self.subTest(stamp=stamp):
                base = self.base / stamp
                base.mkdir()
                root = shared_parent_store(base)
                contract_path = root / "CONTRACT.json"
                contract = json.loads(contract_path.read_text())
                contract["atlas_release"] = stamp
                contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
                before = contract_path.read_bytes()
                code, p = plan(root, base / "out")
                self.assertIsNone(p["precondition"], p["precondition"])
                self.assertIn(("dead-index-cue", "auto"), {(t["kind"], t["class"]) for t in tasks(p)})
                applied = run(
                    OPT, "apply", "--root", str(root), "--target", ".",
                    "--plan", str(base / "out" / "plan.json"),
                )
                report = json.loads(applied.stdout)
                self.assertIn("dead-index-cue:notes/index.md:frame.md", report["applied"])
                self.assertEqual(contract_path.read_bytes(), before)
                results[stamp] = (code, sorted(t["id"] for t in tasks(p)), applied.returncode, report["applied"])
        self.assertEqual(results["0.13.0-beta.7"], results["0.13.0"])

    def test_not_wired_into_install_or_compile(self) -> None:
        help_text = run(ATLAS, "--help").stdout
        self.assertNotIn("optimise", help_text)
        for src in (ROOT / "scripts" / "atlas_cli").rglob("*.py"):
            self.assertNotIn("atlas_optimise", src.read_text(encoding="utf-8"), str(src))
        self.assertNotIn("atlas_optimise", (ROOT / "scripts" / "atlas.py").read_text())


SECRET = "AKIAIOSFODNN7EXAMPLE"
LONG = "Topic memory holds the durable claim about the topic."


def init_store(base: Path) -> Path:
    root = base / "store"
    root.mkdir()
    assert run(ATLAS, "init", "--root", str(root)).returncode == 0
    return root


def git_commit(root: Path, hours_ago: int, message: str, *, author_hours_ago: int | None = None) -> None:
    author_hours = hours_ago if author_hours_ago is None else author_hours_ago
    now = datetime.now(timezone.utc)
    env = os.environ.copy()
    env["GIT_COMMITTER_DATE"] = (now - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    env["GIT_AUTHOR_DATE"] = (now - timedelta(hours=author_hours)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=test@example.com", "-c", "user.name=Test",
         "commit", "-m", message],
        check=True, env=env, capture_output=True, text=True,
    )


def ensure_git(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    git_commit(root, 200, "init")


def memory_page(folder: Path, name: str, *, ptype: str = "memory", description: str | None = LONG,
                body: str | None = None, sensitivity: str | None = None) -> None:
    extra = f"sensitivity: {sensitivity}\n" if sensitivity else ""
    desc = f"description: {description}\n" if description else ""
    page(folder / name, f"""
type: {ptype}
title: {name}
created: 2026-10-06
{desc}{extra}""", body or "## Content\n\nThe parent page states one durable claim with enough body text to pass compile.")


class OptimiseVNextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_path_fills_by_default_and_tidy_only_skips_fill(self) -> None:
        root = init_store(self.base)
        memory_page(root / "notes", "topic.md")
        direct = run(OPT, "plan", "--root", str(root), "--target", "notes", "--json")
        self.assertEqual(direct.returncode, 1, direct.stdout + direct.stderr)
        kinds = {t["kind"] for t in tasks(json.loads(direct.stdout))}
        self.assertIn("missing-gist-fill", kinds)
        tidy = run(OPT, "plan", "--root", str(root), "--target", "notes", "--tidy-only", "--json")
        self.assertNotIn("missing-gist-fill", {t["kind"] for t in tasks(json.loads(tidy.stdout))})
        self.assertNotIn("schema-fill", {t["kind"] for t in tasks(json.loads(tidy.stdout))})

    def test_verbatim_fill_is_confirm_unless_auto_verbatim(self) -> None:
        root = init_store(self.base)
        memory_page(root / "notes", "topic.md")
        parent = (root / "notes" / "topic.md").read_bytes()
        planned = run(OPT, "plan", "--root", str(root), "--target", "notes", "--out-dir", str(self.base / "out"), "--json")
        data = json.loads(planned.stdout)
        fill = next(t for t in tasks(data) if t["kind"] == "missing-gist-fill")
        self.assertEqual(fill["class"], "confirm")
        self.assertEqual(fill["evidence"]["extract"], LONG)
        self.assertEqual(fill["evidence"]["excerpt_rule"], "parent-description")
        applied = run(OPT, "apply", "--root", str(root), "--target", "notes", "--plan", str(self.base / "out" / "plan.json"))
        self.assertFalse((root / "notes" / "topic.gist.md").exists())
        self.assertEqual((root / "notes" / "topic.md").read_bytes(), parent)
        opted = run(OPT, "plan", "--root", str(root), "--target", "notes", "--auto-verbatim",
                    "--out-dir", str(self.base / "out2"), "--json")
        opted_data = json.loads(opted.stdout)
        self.assertEqual(next(t["class"] for t in tasks(opted_data) if t["kind"] == "missing-gist-fill"), "auto")
        applied = run(OPT, "apply", "--root", str(root), "--target", "notes", "--plan", str(self.base / "out2" / "plan.json"))
        self.assertIn(applied.returncode, (0, 1), applied.stdout + applied.stderr)
        gist = (root / "notes" / "topic.gist.md").read_text()
        self.assertIn(f"description: {LONG}\n", gist)
        self.assertEqual((root / "notes" / "topic.md").read_bytes(), parent)
        info = json.loads(run(ATLAS, "compile", "--root", str(root), "--dry-run", "--json").stdout)
        missing = [item["path"] for item in info.get("info", []) if item["id"] == "missing_gist"]
        self.assertNotIn("notes/topic.md", missing)

    def test_gist_body_enrich_copies_the_claim_line(self) -> None:
        root = init_store(self.base)
        notes = root / "notes"
        claim = "The bare memory states one durable claim long enough to copy up verbatim."
        memory_page(notes, "bare.md", description=None, body=f"## Content\n\n{claim}")
        page(notes / "bare.gist.md", """
type: gist
title: Bare gist
created: 2026-10-06
description: Words that the bare memory never says.
relates_to:
  - path: notes/bare.md
    kind: derived_from
""", "## Content\n\nGist of the bare memory with enough words for the body check.")
        parent = (notes / "bare.md").read_bytes()
        planned = run(OPT, "plan", "--root", str(root), "--target", "notes", "--out-dir", str(self.base / "out"), "--json")
        data = json.loads(planned.stdout)
        enrich = next(t for t in tasks(data) if t["kind"] == "gist-body-enrich")
        stale = next(t for t in tasks(data) if t["id"] == "stale-gist-description:notes/bare.gist.md")
        self.assertEqual(enrich["class"], "confirm")
        self.assertEqual(enrich["evidence"]["extract"], claim)
        self.assertEqual(stale["class"], "handoff")
        applied = run(OPT, "apply", "--root", str(root), "--target", "notes", "--plan", str(self.base / "out" / "plan.json"),
                      "--confirm", enrich["id"])
        self.assertIn(applied.returncode, (0, 1), applied.stdout + applied.stderr)
        gist = (notes / "bare.gist.md").read_text()
        self.assertIn(f"description: {claim}\n", gist)
        self.assertIn(claim, gist.split("---", 2)[-1])
        self.assertNotIn("Words that the bare memory never says", gist)
        self.assertEqual((notes / "bare.md").read_bytes(), parent)

    def test_empty_parent_is_handoff_and_residual_does_not_fail(self) -> None:
        root = init_store(self.base)
        memory_page(root / "notes", "empty.md", description=None, body="## Content\n\n")
        before = tree_hash(root)
        planned = run(OPT, "plan", "--root", str(root), "--target", "notes", "--out-dir", str(self.base / "out"), "--json")
        self.assertEqual(planned.returncode, 1, planned.stdout + planned.stderr)
        data = json.loads(planned.stdout)
        fill = next(t for t in tasks(data) if t["id"] == "missing-gist-fill:notes/empty.md")
        self.assertEqual(fill["class"], "handoff")
        self.assertFalse(fill["evidence"]["sufficient"])
        receipt = data["receipt"]
        self.assertFalse(receipt["gates"]["run_failed"])
        self.assertFalse(receipt["residuals"]["missing_gist_fails_run"])
        self.assertGreaterEqual(receipt["residuals"]["missing_gist"], 1)
        self.assertIn("fetch_ok", receipt)
        self.assertIn("tip", receipt)
        applied = run(OPT, "apply", "--root", str(root), "--target", "notes", "--plan", str(self.base / "out" / "plan.json"))
        self.assertNotEqual(applied.returncode, 2, applied.stdout + applied.stderr)
        self.assertFalse((root / "notes" / "empty.gist.md").exists())
        self.assertEqual(tree_hash(root), before)

    def test_paraphrase_and_stale_evidence_refuse(self) -> None:
        root = init_store(self.base)
        memory_page(root / "notes", "topic.md")
        before = tree_hash(root)
        run(OPT, "plan", "--root", str(root), "--target", "notes", "--out-dir", str(self.base / "out"), "--json")
        plan_path = self.base / "out" / "plan.json"
        plan_data = json.loads(plan_path.read_text())
        for folder_tasks in plan_data["folders"].values():
            for task in folder_tasks:
                if task["kind"] == "missing-gist-fill":
                    task["evidence"]["extract"] = "Invented wording that the parent never used."
                    task["evidence"]["proposed"]["description"] = task["evidence"]["extract"]
        plan_path.write_text(json.dumps(plan_data), encoding="utf-8")
        refused = run(OPT, "apply", "--root", str(root), "--target", "notes", "--plan", str(plan_path),
                      "--confirm", "missing-gist-fill:notes/topic.md")
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertEqual(tree_hash(root), before)
        run(OPT, "plan", "--root", str(root), "--target", "notes", "--auto-verbatim", "--out-dir", str(self.base / "out2"))
        topic = root / "notes" / "topic.md"
        topic.write_text(topic.read_text() + "\nEdited after plan.\n", encoding="utf-8")
        stale = run(OPT, "apply", "--root", str(root), "--target", "notes", "--plan", str(self.base / "out2" / "plan.json"))
        self.assertEqual(stale.returncode, 2)
        self.assertFalse((root / "notes" / "topic.gist.md").exists())

    def test_all_missing_gist_types_and_not_protostar(self) -> None:
        root = init_store(self.base)
        types = ["experience", "decision", "lesson", "recipe", "document", "memory", "page", "protostar"]
        for ptype in types:
            memory_page(root / "notes", f"{ptype}.md", ptype=ptype)
        data = json.loads(run(OPT, "plan", "--root", str(root), "--target", "notes", "--json").stdout)
        filled = {t["evidence"]["parent_type"] for t in tasks(data) if t["kind"] == "missing-gist-fill"}
        self.assertEqual(filled, {"experience", "decision", "lesson", "recipe", "document", "memory", "page"})
        self.assertNotIn("protostar", filled)

    def test_schema_fill_is_minimal_prose(self) -> None:
        root = init_store(self.base)
        notes = root / "notes"
        memory_page(notes, "topic.md")
        page(notes / "topic.gist.md", f"""
type: gist
title: Topic gist
created: 2026-10-06
description: {LONG}
relates_to:
  - path: notes/topic.md
    kind: derived_from
""", f"## Content\n\n{LONG}")
        (notes / "index.md").write_text("# Notes\n", encoding="utf-8")
        thin = notes / "thin"
        page(thin / "tiny.gist.md", """
type: gist
title: Hi
created: 2026-10-06
description: Hi
relates_to:
  - path: notes/topic.md
    kind: derived_from
""", "## Content\n\nHi is too short to be a schema blurb on its own here.")
        planned = run(OPT, "plan", "--root", str(root), "--target", ".", "--out-dir", str(self.base / "out"), "--json")
        data = json.loads(planned.stdout)
        schema = next(t for t in tasks(data) if t["id"] == "schema-fill:notes")
        thin_schema = next(t for t in tasks(data) if t["id"] == "schema-fill:notes/thin")
        self.assertEqual(schema["class"], "confirm")
        self.assertEqual(thin_schema["class"], "handoff")
        body = schema["evidence"]["proposed"]["body"]
        self.assertIn(LONG, body)
        self.assertNotIn("## Provenance", body)
        self.assertLess(body.count("\n"), 3)
        applied = run(OPT, "apply", "--root", str(root), "--target", ".", "--plan", str(self.base / "out" / "plan.json"),
                      "--confirm", "schema-fill:notes")
        self.assertIn(applied.returncode, (0, 1), applied.stdout + applied.stderr)
        text = (notes / "schema.schema.md").read_text()
        self.assertIn("kind: related", text)
        self.assertIn("path: notes/topic.gist.md", text)
        self.assertIn(LONG, text)
        self.assertEqual(text.count("## "), 1)
        self.assertFalse((thin / "schema.schema.md").exists())
        compiled = json.loads(run(ATLAS, "compile", "--root", str(root), "--dry-run", "--json").stdout)
        uncovered = [item["path"] for item in compiled.get("critical", []) if item["id"] == "schema_folder"]
        missing_cue = [item["path"] for item in compiled.get("critical", []) if item["id"] == "schema_missing_from_index"]
        self.assertNotIn("notes/topic.gist.md", uncovered)
        self.assertFalse(any(path.startswith("notes/") for path in missing_cue))

    def test_security_scan_blocks_secret_and_restricted(self) -> None:
        root = init_store(self.base)
        memory_page(root / "notes", "secret.md", description=f"{LONG} {SECRET}")
        memory_page(root / "notes", "restricted.md", sensitivity="restricted")
        before = tree_hash(root)
        planned = run(OPT, "plan", "--root", str(root), "--target", "notes", "--out-dir", str(self.base / "out"), "--json")
        self.assertNotIn(SECRET, planned.stdout)
        data = json.loads(planned.stdout)
        by_id = {t["id"]: t for t in tasks(data)}
        self.assertEqual(by_id["missing-gist-fill:notes/secret.md"]["class"], "blocked")
        self.assertEqual(by_id["missing-gist-fill:notes/restricted.md"]["class"], "blocked")
        self.assertEqual(data["receipt"]["security"]["status"], "blocked")
        self.assertGreater(data["receipt"]["security"]["new_critical_or_high"], 0)
        self.assertFalse(data["receipt"]["security"]["secrets_promoted"])
        applied = run(OPT, "apply", "--root", str(root), "--target", "notes", "--plan", str(self.base / "out" / "plan.json"))
        self.assertNotEqual(applied.returncode, 2)
        self.assertFalse((root / "notes" / "secret.gist.md").exists())
        self.assertEqual(tree_hash(root), before)
        plan_data = json.loads((self.base / "out" / "plan.json").read_text())
        for folder_tasks in plan_data["folders"].values():
            for task in folder_tasks:
                if task["id"] == "missing-gist-fill:notes/secret.md":
                    task["class"] = "auto"
        (self.base / "out" / "plan.json").write_text(json.dumps(plan_data), encoding="utf-8")
        forced = run(OPT, "apply", "--root", str(root), "--target", "notes", "--plan", str(self.base / "out" / "plan.json"))
        self.assertEqual(forced.returncode, 2)
        self.assertFalse((root / "notes" / "secret.gist.md").exists())

    def test_modes_and_cost_ceiling(self) -> None:
        root = init_store(self.base)
        memory_page(root / "notes", "topic.md")
        memory_page(root / "other", "topic.md")
        full = run(OPT, "plan", "--root", str(root), "--target", "notes", "--optimise-mode", "full")
        self.assertEqual(full.returncode, 2)
        self.assertIn("serial only", full.stderr)
        custom_missing = run(OPT, "plan", "--root", str(root), "--target", ".", "--optimise-mode", "custom")
        self.assertEqual(custom_missing.returncode, 2)
        conflict = run(OPT, "plan", "--root", str(root), "--target", ".", "--custom-tree", "notes")
        self.assertEqual(conflict.returncode, 2)
        hours = run(OPT, "plan", "--root", str(root), "--target", ".", "--since-hours", "12")
        self.assertEqual(hours.returncode, 2)
        custom = json.loads(run(
            OPT, "plan", "--root", str(root), "--target", ".", "--optimise-mode", "custom",
            "--custom-tree", "notes", "--json",
        ).stdout)
        parents = {t["evidence"].get("parent") for t in tasks(custom) if t["kind"] == "missing-gist-fill"}
        self.assertEqual(parents, {"notes/topic.md"})
        ceiling = run(OPT, "plan", "--root", str(root), "--target", ".", "--cost-ceiling", "0")
        self.assertEqual(ceiling.returncode, 2)
        self.assertIn("cost ceiling", ceiling.stdout)

    def test_incremental_uses_committer_clock_and_skips_dirty(self) -> None:
        root = init_store(self.base)
        ensure_git(root)
        memory_page(root / "notes", "old.md")
        git_commit(root, 72, "old")
        memory_page(root / "notes", "recent.md")
        memory_page(root / "other", "other.md")
        memory_page(root / "notes", "dirty.md")
        git_commit(root, 2, "recent")
        memory_page(root / "notes", "author.md")
        git_commit(root, 72, "author-recent-committer-old", author_hours_ago=1)
        dirty = root / "notes" / "dirty.md"
        dirty.write_text(dirty.read_text() + "\nDirty edit.\n", encoding="utf-8")
        memory_page(root / "notes", "untracked.md")
        data = json.loads(run(
            OPT, "plan", "--root", str(root), "--target", ".", "--optimise-mode", "incremental", "--json",
        ).stdout)
        fills = {t["id"] for t in tasks(data) if t["kind"] == "missing-gist-fill"}
        self.assertIn("missing-gist-fill:notes/recent.md", fills)
        self.assertIn("missing-gist-fill:other/other.md", fills)
        self.assertNotIn("missing-gist-fill:notes/old.md", fills)
        self.assertNotIn("missing-gist-fill:notes/dirty.md", fills)
        self.assertNotIn("missing-gist-fill:notes/untracked.md", fills)
        self.assertNotIn("missing-gist-fill:notes/author.md", fills)
        self.assertEqual(data["source"]["since_hours"], 24)
        self.assertTrue(data["receipt"]["fetch_ok"])
        self.assertTrue(data["receipt"]["tip"])
        wider = json.loads(run(
            OPT, "plan", "--root", str(root), "--target", ".", "--optimise-mode", "incremental",
            "--since-hours", "96", "--custom-tree", "notes", "--json",
        ).stdout)
        wider_fills = {t["id"] for t in tasks(wider) if t["kind"] == "missing-gist-fill"}
        self.assertIn("missing-gist-fill:notes/old.md", wider_fills)
        self.assertIn("missing-gist-fill:notes/recent.md", wider_fills)
        self.assertNotIn("missing-gist-fill:other/other.md", wider_fills)
        self.assertNotIn("missing-gist-fill:notes/dirty.md", wider_fills)

    def test_receipt_and_docs_carry_the_locked_gates(self) -> None:
        root = init_store(self.base)
        memory_page(root / "notes", "topic.md")
        data = json.loads(run(
            OPT, "plan", "--root", str(root), "--target", "notes", "--pilot", "--out-dir", str(self.base / "out"), "--json",
        ).stdout)
        receipt = data["receipt"]
        self.assertEqual(receipt["schema"], "atlas-optimise-receipt/v1")
        self.assertEqual(receipt["gates"]["spot_check_n"], 10)
        self.assertEqual(receipt["gates"]["disagreement_rate"], "informational")
        self.assertFalse(receipt["fleet_ready"])
        self.assertTrue(receipt["serial_full_only"])
        self.assertIn("cost", receipt)
        self.assertTrue((self.base / "out" / "receipt.json").is_file())
        help_text = run(OPT, "plan", "--help").stdout
        for flag in (
            "--optimise-mode", "--since-hours", "--custom-tree", "--tidy-only",
            "--auto-verbatim", "--fill-sensible", "--cost-ceiling",
        ):
            self.assertIn(flag, help_text)
        self.assertNotIn("--force-gist", help_text)
        self.assertNotIn("cascade-fill", help_text)
        path = (ROOT / "references" / "paths" / "atlas-optimise.md").read_text()
        scenario = (ROOT / "references" / "scenarios" / "atlas-optimise-vnext-adversarial-v1.yaml").read_text()
        for phrase in (
            "fill", "tidy", "sleep", "interim", "serial", "pilot", "N=10",
            "fetch", "Disagreement", "missing_gist", "--auto-verbatim", "--tidy-only",
        ):
            self.assertIn(phrase, path)
        self.assertNotIn("cascade-fill", path.lower())
        self.assertNotIn("plumbing", path.lower())
        for smoke in (
            "no-invent-empty-parent", "verbatim-auto-only-opt-in", "no-parent-rewrite",
            "stale-evidence-refuse", "mode-full-requires-root-target", "incremental-committer-24h",
            "path-fill-default-tidy-only", "all-missing-gist-types", "schema-minimal-prose",
            "security-scan-gate", "residual-missing-gist-not-fail", "no-install-compile-hook",
            "pilot-before-fleet-language", "sleep-boundary-stated", "tidy-regression",
        ):
            self.assertIn(smoke, scenario)

    def test_residual_missing_gist_is_not_a_fleet_bar(self) -> None:
        root = init_store(self.base)
        memory_page(root / "notes", "empty.md", description=None, body="## Content\n\n")
        (root / "notes" / "index.md").write_text("# Notes\n\n- [Empty](empty.md)\n", encoding="utf-8")
        compiled = json.loads(run(ATLAS, "compile", "--root", str(root), "--dry-run", "--json").stdout)
        info = [item["path"] for item in compiled.get("info", []) if item["id"] == "missing_gist"]
        critical = [item["id"] for item in compiled.get("critical", [])]
        self.assertIn("notes/empty.md", info)
        self.assertNotIn("missing_gist", critical)
        planned = run(OPT, "plan", "--root", str(root), "--target", "notes", "--fill-sensible", "--json")
        self.assertEqual(planned.returncode, 1, planned.stdout + planned.stderr)
        data = json.loads(planned.stdout)
        self.assertFalse(data["receipt"]["residuals"]["missing_gist_fails_run"])
        self.assertFalse(data["receipt"]["gates"]["residual_missing_gist_fails_run"])
        self.assertGreaterEqual(data["receipt"]["residuals"]["missing_gist"], 1)
        self.assertNotIn("shell_fills", data["receipt"])
        self.assertNotIn("indexed_missing_gist_after", data["receipt"])
        self.assertTrue(data["receipt"]["fill_sensible"])
        self.assertNotIn("gist_kind", (ROOT / "scripts" / "atlas_optimise.py").read_text(encoding="utf-8"))

    def test_shared_same_folder_gist_and_cut2_refusal(self) -> None:
        root = init_store(self.base)
        notes = root / "notes"
        other = root / "other"
        page(notes / "alpha.md", f"""
type: memory
title: Alpha
created: 2026-10-06
description: {LONG}
relates_to:
  - path: notes/beta.md
    kind: related
""", "## Content\n\nAlpha states one durable claim with enough body text to pass compile.")
        page(notes / "beta.md", f"""
type: memory
title: Beta
created: 2026-10-06
description: Peer memory holds a second durable claim about the same subject.
relates_to:
  - path: notes/alpha.md
    kind: related
""", "## Content\n\nBeta states one durable claim with enough body text to pass compile.")
        page(notes / "near.md", f"""
type: memory
title: Near
created: 2026-10-06
description: {LONG}
relates_to:
  - path: other/far.md
    kind: related
""", "## Content\n\nNear states one durable claim with enough body text to pass compile.")
        page(other / "far.md", f"""
type: memory
title: Far
created: 2026-10-06
description: {LONG}
relates_to:
  - path: notes/near.md
    kind: related
""", "## Content\n\nFar states one durable claim with enough body text to pass compile.")
        (notes / "index.md").write_text("# Notes\n", encoding="utf-8")
        (other / "index.md").write_text("# Other\n", encoding="utf-8")
        planned = run(OPT, "plan", "--root", str(root), "--target", ".", "--out-dir", str(self.base / "out"), "--json")
        self.assertEqual(planned.returncode, 1, planned.stdout + planned.stderr)
        data = json.loads(planned.stdout)
        fills = [t for t in tasks(data) if t["kind"] == "missing-gist-fill"]
        by_parents = {tuple(t["evidence"]["parents"]): t for t in fills}
        shared = by_parents[("notes/alpha.md", "notes/beta.md")]
        self.assertEqual(shared["evidence"]["cluster_size"], 2)
        self.assertEqual(shared["evidence"]["extract"], LONG)
        self.assertNotIn("stub", shared["action"])
        self.assertEqual(by_parents[("notes/near.md",)]["evidence"]["cluster_size"], 1)
        self.assertEqual(by_parents[("other/far.md",)]["evidence"]["cluster_size"], 1)
        self.assertEqual(data["receipt"]["shared_gist_count"], 1)
        self.assertEqual(data["receipt"]["cluster_size_hist"], {"2": 1})
        self.assertGreaterEqual(data["receipt"]["body_fills"], 1)
        self.assertNotIn("shell_fills", data["receipt"])
        note_fills = [
            t["id"] for t in fills
            if t["evidence"]["parents"][0].startswith("notes/") and t["class"] == "confirm"
        ]
        applied = run(
            OPT, "apply", "--root", str(root), "--target", ".",
            "--plan", str(self.base / "out" / "plan.json"),
            *[arg for tid in note_fills for arg in ("--confirm", tid)],
            "--confirm", "schema-fill:notes",
        )
        self.assertIn(applied.returncode, (0, 1), applied.stdout + applied.stderr)
        gist = (notes / "alpha.gist.md").read_text(encoding="utf-8")
        self.assertIn("path: notes/alpha.md", gist)
        self.assertIn("path: notes/beta.md", gist)
        self.assertIn("kind: derived_from", gist)
        self.assertIn(LONG, gist)
        schema = (notes / "schema.schema.md").read_text(encoding="utf-8")
        self.assertIn("kind: related", schema)
        self.assertNotIn("path: notes/alpha.md", schema)
        self.assertNotIn("path: notes/beta.md", schema)
        compiled = json.loads(run(ATLAS, "compile", "--root", str(root), "--dry-run", "--json").stdout)
        missing = [item["path"] for item in compiled.get("info", []) if item["id"] == "missing_gist"]
        self.assertNotIn("notes/alpha.md", missing)
        self.assertNotIn("notes/beta.md", missing)
        gist_parents = [item["path"] for item in compiled.get("info", []) + compiled.get("critical", []) if item["id"] == "gist_parent"]
        self.assertFalse(any(path.startswith("notes/") and path.endswith(".gist.md") for path in gist_parents))

    def test_multicluster_optional_enrich_and_no_stub(self) -> None:
        root = init_store(self.base)
        notes = root / "notes"
        pairs = (("one", "two"), ("three", "four"))
        for left, right in pairs:
            page(notes / f"{left}.md", f"""
type: memory
title: {left}
created: 2026-10-06
description: {LONG}
work_id: cluster-{left}
relates_to:
  - path: notes/{right}.md
    kind: related
""", "## Content\n\nThe parent page states one durable claim with enough body text to pass compile.")
            page(notes / f"{right}.md", f"""
type: memory
title: {right}
created: 2026-10-06
description: {LONG}
work_id: cluster-{left}
""", "## Content\n\nThe parent page states one durable claim with enough body text to pass compile.")
        page(notes / "rich.md", f"""
type: memory
title: Rich
created: 2026-10-06
description: {LONG}
relates_to:
  - path: notes/thin.md
    kind: related
""", "## Content\n\nThe parent page states one durable claim with enough body text to pass compile.")
        page(notes / "thin.md", """
type: memory
title: Thin
created: 2026-10-06
relates_to:
  - path: notes/rich.md
    kind: related
""", "## Content\n\n")
        data = json.loads(run(OPT, "plan", "--root", str(root), "--target", "notes", "--json").stdout)
        fills = [t for t in tasks(data) if t["kind"] == "missing-gist-fill" and t["class"] == "confirm"]
        sizes = sorted(t["evidence"]["cluster_size"] for t in fills)
        self.assertEqual(sizes, [2, 2, 2])
        enrich = next(t for t in fills if "notes/thin.md" in t["evidence"]["parents"])
        self.assertTrue(enrich["evidence"]["enrich_optional"])
        self.assertEqual(enrich["evidence"]["extract"], LONG)
        self.assertNotIn("notes/thin.md", enrich["evidence"]["body"])
        self.assertEqual(data["receipt"]["shared_gist_count"], 3)
        self.assertEqual(data["receipt"]["enrich_optional_count"], 1)
        self.assertFalse(any(t["class"] == "auto" and "stub" in t["action"] for t in tasks(data)))
        self.assertFalse((notes / "thin.gist.md").exists())

    def test_non_memory_page_is_index_first_class(self) -> None:
        root = init_store(self.base)
        memory_page(root / "notes", "seen.md", ptype="experience")
        (root / "notes" / "index.md").write_text("# Notes\n\n- [Seen](seen.md)\n", encoding="utf-8")
        compiled = json.loads(run(ATLAS, "compile", "--root", str(root), "--dry-run", "--json").stdout)
        self.assertEqual(
            [item["path"] for item in compiled.get("critical", []) if item["id"] == "missing_gist"],
            [],
        )
        self.assertIn("notes/seen.md", [item["path"] for item in compiled.get("info", []) if item["id"] == "missing_gist"])
        self.assertNotIn("schema_folder", {item["id"] for item in compiled.get("critical", [])})
        before = tree_hash(root)
        planned = run(OPT, "plan", "--root", str(root), "--target", "notes", "--out-dir", str(self.base / "out"), "--json")
        data = json.loads(planned.stdout)
        kinds = {t["kind"] for t in tasks(data)}
        self.assertNotIn("frame", kinds)
        self.assertFalse(any("extension" in t["kind"] for t in tasks(data)))
        applied = run(OPT, "apply", "--root", str(root), "--target", "notes", "--plan", str(self.base / "out" / "plan.json"))
        self.assertNotEqual(applied.returncode, 2, applied.stdout + applied.stderr)
        self.assertEqual(tree_hash(root), before)
        self.assertFalse((root / "notes" / "seen.gist.md").exists())
        self.assertFalse(list((root / "notes").glob("*.schema.md")))

    def test_booking_manage_reference_is_handoff_not_promoted(self) -> None:
        root = init_store(self.base)
        memory_page(root / "notes", "booked.md", description=f"{LONG} BMR-44021")
        before = tree_hash(root)
        planned = run(OPT, "plan", "--root", str(root), "--target", "notes", "--out-dir", str(self.base / "out"), "--json")
        self.assertNotIn("BMR-44021", planned.stdout)
        data = json.loads(planned.stdout)
        fill = next(t for t in tasks(data) if t["id"] == "missing-gist-fill:notes/booked.md")
        self.assertEqual(fill["class"], "handoff")
        self.assertIsNone(fill["evidence"]["extract"])
        hits = data["receipt"]["scan_hits"]
        self.assertTrue(hits)
        self.assertEqual(set(hits[0]), {"path", "type", "severity"})
        self.assertEqual(hits[0]["severity"], "medium")
        self.assertEqual(hits[0]["path"], "notes/booked.md")
        self.assertTrue(data["receipt"]["zero_crit_high_promoted"])
        self.assertEqual(data["receipt"]["scan_gate_refuse_count"], 0)
        applied = run(OPT, "apply", "--root", str(root), "--target", "notes", "--plan", str(self.base / "out" / "plan.json"))
        self.assertNotEqual(applied.returncode, 2, applied.stdout + applied.stderr)
        self.assertEqual(tree_hash(root), before)
        plan_data = json.loads((self.base / "out" / "plan.json").read_text())
        for folder_tasks in plan_data["folders"].values():
            for task in folder_tasks:
                if task["id"] == "missing-gist-fill:notes/booked.md":
                    task["class"] = "auto"
        (self.base / "out" / "plan.json").write_text(json.dumps(plan_data), encoding="utf-8")
        forced = run(OPT, "apply", "--root", str(root), "--target", "notes", "--plan", str(self.base / "out" / "plan.json"))
        self.assertEqual(forced.returncode, 2)
        self.assertFalse((root / "notes" / "booked.gist.md").exists())


if __name__ == "__main__":
    unittest.main()
