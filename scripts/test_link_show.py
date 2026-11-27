#!/usr/bin/env python3
"""Pinned link inspection, compile provenance checks, and optimise move gates."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
OPTIMISE = ROOT / "scripts" / "atlas_optimise.py"
sys.path.insert(0, str(ROOT / "scripts"))

from test_atlas_optimise import page, shared_parent_store  # noqa: E402

ATLAS_ID = "example.com/org/target"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def optimise(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(OPTIMISE), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class LinkShowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.project)], check=True)
        git(self.project, "config", "user.name", "Atlas Test")
        git(self.project, "config", "user.email", "atlas-test@example.invalid")
        init = cli("init", "--root", str(self.project), "--json")
        self.assertEqual(init.returncode, 0, init.stderr)
        self.target = self.project / "target"
        self.target.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.target)], check=True)
        git(self.target, "config", "user.name", "Atlas Test")
        git(self.target, "config", "user.email", "atlas-test@example.invalid")
        self.page = self.target / "notes" / "fact.md"
        self.page.parent.mkdir()
        self.page.write_text(
            "---\ntype: document\ntitle: Fact\ncreated: 2026-01-01\n---\n\n"
            "## Content\n\nfirst cited text and supporting context for this fact.\n",
            encoding="utf-8",
        )
        self.first = self.commit(self.target, "initial")
        (self.project / "atlas-mesh.json").write_text(json.dumps({
            "version": 1,
            "stores": [{"id": ATLAS_ID, "path": "target", "ref": "main"}],
        }), encoding="utf-8")
        self.source = self.project / "source.md"
        self.set_source(f"atlas://{ATLAS_ID}/notes/fact.md@{self.first}")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def commit(repo: Path, message: str) -> str:
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message], check=True)
        return git(repo, "rev-parse", "HEAD")

    def set_source(self, uri: str) -> None:
        self.source.write_text(
            "---\ntype: document\ntitle: Citation\ncreated: 2026-01-01\n---\n\n"
            "## Content\n\nThis citation has enough supporting context for compile.\n\n"
            f"See {uri}\n",
            encoding="utf-8",
        )

    def show(self, uri: str | None = None, *flags: str) -> tuple[int, dict]:
        result = cli(
            "link", "show",
            uri or f"atlas://{ATLAS_ID}/notes/fact.md@{self.first}",
            "--cwd", str(self.project), "--json", *flags,
        )
        return result.returncode, json.loads(result.stdout)

    def compile_findings(self) -> tuple[int, dict]:
        result = cli("compile", "--root", str(self.project), "--dry-run", "--json")
        return result.returncode, json.loads(result.stdout)

    def test_unchanged_blob_despite_unrelated_commits(self) -> None:
        (self.target / "other.md").write_text("unrelated\n", encoding="utf-8")
        self.commit(self.target, "unrelated change")
        code, result = self.show()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "unchanged")
        self.assertFalse(result["changed"])
        self.assertEqual(result["cited_blob"], result["tip_blob"])
        self.assertTrue(result["cited_reachable_from_tip"])
        self.assertEqual(result["commits_since"], 1)

    def test_changed_returns_cited_text_and_scoped_diff(self) -> None:
        self.page.write_text(
            "---\ntype: document\ntitle: Fact\ncreated: 2026-01-01\n---\n\n"
            "## Content\n\nnew current text\n",
            encoding="utf-8",
        )
        self.commit(self.target, "overwrite")
        code, result = self.show(None, "--show", "--diff")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "changed")
        self.assertTrue(result["changed"])
        self.assertIn("first cited text", result["text"])
        self.assertIn("-first cited text", result["diff"])
        self.assertIn("+new current text", result["diff"])

    def test_show_and_diff_are_size_capped(self) -> None:
        self.page.write_text("x" * (300 * 1024), encoding="utf-8")
        cited = self.commit(self.target, "large page")
        self.page.write_text("small tip\n", encoding="utf-8")
        self.commit(self.target, "small page")
        code, result = self.show(
            f"atlas://{ATLAS_ID}/notes/fact.md@{cited}", "--show", "--diff"
        )
        self.assertEqual(code, 0)
        for field in ("text", "diff"):
            self.assertLessEqual(len(result[field].encode("utf-8")), 256 * 1024)
            self.assertIn("[truncated at 262144 bytes]", result[field])

    def test_renamed_and_deleted_targets(self) -> None:
        renamed = self.target / "notes" / "renamed.md"
        git(self.target, "mv", "notes/fact.md", "notes/renamed.md")
        self.commit(self.target, "rename")
        code, result = self.show()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "renamed")
        self.assertEqual(result["renamed_to"], "notes/renamed.md")
        self.assertEqual(result["tip_path"], "notes/renamed.md")
        git(self.target, "rm", "notes/renamed.md")
        self.commit(self.target, "delete")
        code, result = self.show()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "deleted")
        self.assertTrue(result["deleted"])
        self.assertTrue(result["changed"])

    def test_tip_unavailable_and_cited_commit_missing_fail_closed(self) -> None:
        mesh = json.loads((self.project / "atlas-mesh.json").read_text())
        mesh["stores"][0]["ref"] = "missing-tip"
        (self.project / "atlas-mesh.json").write_text(json.dumps(mesh), encoding="utf-8")
        code, result = self.show(None, "--show")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "tip_unavailable")
        self.assertIsNone(result["changed"])
        self.assertIn("first cited text", result["text"])
        missing = "f" * 40
        code, result = self.show(f"atlas://{ATLAS_ID}/notes/fact.md@{missing}", "--show")
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "cited_unavailable")
        self.assertEqual(result["reason"], "commit_missing")
        self.assertNotIn("text", result)

    def test_shallow_and_unmounted_fail_closed(self) -> None:
        source = self.base / "source-repo"
        source.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(source)], check=True)
        git(source, "config", "user.name", "Atlas Test")
        git(source, "config", "user.email", "atlas-test@example.invalid")
        (source / "notes").mkdir()
        (source / "notes" / "fact.md").write_text("one\n", encoding="utf-8")
        old = self.commit(source, "one")
        (source / "notes" / "fact.md").write_text("two\n", encoding="utf-8")
        self.commit(source, "two")
        shallow = self.base / "shallow"
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", "--no-local", str(source), str(shallow)],
            check=True,
        )
        (self.project / "target").rename(self.project / "target-original")
        shutil.move(str(shallow), str(self.project / "target"))
        code, result = self.show(f"atlas://{ATLAS_ID}/notes/fact.md@{old}", "--show")
        self.assertEqual(code, 2)
        self.assertEqual(result["reason"], "shallow_clone")
        mesh = json.loads((self.project / "atlas-mesh.json").read_text())
        mesh["stores"] = []
        (self.project / "atlas-mesh.json").write_text(json.dumps(mesh), encoding="utf-8")
        code, result = self.show()
        self.assertEqual(code, 2)
        self.assertEqual(result["reason"], "store_not_mounted")

    def test_link_pin_uri_and_path(self) -> None:
        uri = f"atlas://{ATLAS_ID}/notes/fact.md"
        result = cli("link", "pin", uri, "--cwd", str(self.project), "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["uri"], f"{uri}@{self.first}")
        result = cli("link", "pin", "notes/fact.md", "--cwd", str(self.project), "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["uri"], f"{uri}@{self.first}")

    def test_link_pin_store_relative_path_without_mesh_row(self) -> None:
        store = self.base / "standalone"
        store.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(store)], check=True)
        git(store, "config", "user.name", "Atlas Test")
        git(store, "config", "user.email", "atlas-test@example.invalid")
        git(store, "remote", "add", "origin", "https://example.com/org/standalone.git")
        (store / "CONTRACT.json").write_text("{}\n", encoding="utf-8")
        (store / "page.md").write_text("standalone\n", encoding="utf-8")
        tip = self.commit(store, "standalone")
        result = cli("link", "pin", "page.md", "--cwd", str(store), "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["uri"], f"atlas://example.com/org/standalone/page.md@{tip}")

    def test_floating_show_has_no_impact_pair(self) -> None:
        code, result = self.show(f"atlas://{ATLAS_ID}/notes/fact.md")
        self.assertEqual(code, 0)
        self.assertFalse(result["pinned"])
        self.assertEqual(result["status"], "floating")
        self.assertIsNone(result["changed"])
        self.assertIsNone(result["cited_sha"])
        self.assertIsNone(result["diff_stat"])

    def test_compile_pin_findings_and_severity(self) -> None:
        code, payload = self.compile_findings()
        self.assertFalse(any(f["id"].startswith("atlas_pin_") for f in payload["critical"] + payload["warnings"]))
        self.assertNotEqual(code, 2)

        missing = "e" * 40
        self.set_source(f"atlas://{ATLAS_ID}/notes/fact.md@{missing}")
        _, payload = self.compile_findings()
        broken = [f for f in payload["critical"] if f["id"] == "atlas_pin_broken"]
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0]["severity"], "critical")

        self.set_source(f"atlas://{ATLAS_ID}/notes/missing.md@{self.first}")
        _, payload = self.compile_findings()
        broken = [f for f in payload["critical"] if f["id"] == "atlas_pin_broken"]
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0]["severity"], "critical")

        mesh = json.loads((self.project / "atlas-mesh.json").read_text())
        mesh["stores"] = []
        (self.project / "atlas-mesh.json").write_text(json.dumps(mesh), encoding="utf-8")
        self.set_source(f"atlas://{ATLAS_ID}/notes/fact.md@{self.first}")
        _, payload = self.compile_findings()
        unverifiable = [f for f in payload["warnings"] if f["id"] == "atlas_pin_unverifiable"]
        self.assertEqual(len(unverifiable), 1)
        self.assertEqual(unverifiable[0]["severity"], "warning")

    def test_compile_shallow_and_unreachable_warnings(self) -> None:
        side = git(self.target, "rev-parse", "HEAD")
        git(self.target, "checkout", "-q", "-b", "side")
        self.page.write_text("side-only\n", encoding="utf-8")
        side = self.commit(self.target, "side change")
        git(self.target, "checkout", "-q", "main")
        self.set_source(f"atlas://{ATLAS_ID}/notes/fact.md@{side}")
        _, payload = self.compile_findings()
        finding = [f for f in payload["warnings"] if f["id"] == "atlas_pin_unreachable"]
        self.assertEqual(len(finding), 1)
        self.assertEqual(finding[0]["severity"], "warning")

        shallow_source = self.base / "deep"
        shallow_source.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(shallow_source)], check=True)
        git(shallow_source, "config", "user.name", "Atlas Test")
        git(shallow_source, "config", "user.email", "atlas-test@example.invalid")
        (shallow_source / "notes").mkdir()
        (shallow_source / "notes" / "fact.md").write_text("old\n", encoding="utf-8")
        old = self.commit(shallow_source, "old")
        (shallow_source / "notes" / "fact.md").write_text("new\n", encoding="utf-8")
        self.commit(shallow_source, "new")
        shallow = self.base / "shallow-store"
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", "--no-local", str(shallow_source), str(shallow)],
            check=True,
        )
        (self.project / "target").rename(self.project / "target-original")
        shutil.move(str(shallow), str(self.project / "target"))
        mesh = json.loads((self.project / "atlas-mesh.json").read_text())
        mesh["stores"][0]["ref"] = "main"
        (self.project / "atlas-mesh.json").write_text(json.dumps(mesh), encoding="utf-8")
        self.set_source(f"atlas://{ATLAS_ID}/notes/fact.md@{old}")
        _, payload = self.compile_findings()
        finding = [f for f in payload["warnings"] if f["id"] == "atlas_pin_unverifiable_shallow"]
        self.assertEqual(len(finding), 1)
        self.assertEqual(finding[0]["severity"], "warning")
        self.assertFalse(any(f["id"] == "atlas_pin_broken" for f in payload["critical"]))

    def test_floating_links_still_block_optimise_but_pins_do_not(self) -> None:
        (self.base / "optimise").mkdir()
        root = shared_parent_store(self.base / "optimise")
        referrer = root / "notes" / "pointer.md"
        page(
            referrer,
            "type: decision\ntitle: Pointer\ncreated: 2026-10-05",
            f"See atlas://{ATLAS_ID}/notes/topic.md.",
        )
        floating = optimise("plan", "--root", str(root), "--target", ".", "--json")
        self.assertEqual(floating.returncode, 1)
        tasks = [task for folder in json.loads(floating.stdout)["folders"].values() for task in folder]
        self.assertEqual(next(task for task in tasks if task["kind"] == "layer-suffix")["class"], "blocked")
        page(
            referrer,
            "type: decision\ntitle: Pointer\ncreated: 2026-10-05",
            f"See atlas://{ATLAS_ID}/notes/topic.md@{'a' * 40}.",
        )
        pinned = optimise("plan", "--root", str(root), "--target", ".", "--json")
        self.assertEqual(pinned.returncode, 1)
        tasks = [task for folder in json.loads(pinned.stdout)["folders"].values() for task in folder]
        self.assertEqual(next(task for task in tasks if task["kind"] == "layer-suffix")["class"], "opt-in")


if __name__ == "__main__":
    unittest.main()
