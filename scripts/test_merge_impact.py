#!/usr/bin/env python3
"""Local, read-only merge impact reports."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
ID = "example.com/org/store"


class MergeImpactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        self.git("config", "user.name", "Atlas Test")
        self.git("config", "user.email", "atlas-test@example.invalid")
        self.git("remote", "add", "origin", "https://example.com/org/store.git")
        self.page = self.repo / "fact.md"
        self.page.write_text("first claim\ncontext\n", encoding="utf-8")
        self.first = self.commit("first")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def impact(self, since: str, *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            [sys.executable, str(ATLAS), "link", "impact", "--root", str(self.repo),
             "--since", since, "--json", *args],
            capture_output=True, text=True, check=False,
        )
        return result, json.loads(result.stdout)

    def test_changed_page_and_pin_use_until_snapshot(self) -> None:
        (self.repo / "citation.md").write_text(
            f"See atlas://{ID}/fact.md@{self.first}#claim\n", encoding="utf-8"
        )
        baseline = self.commit("cite")
        self.page.write_text("new claim\ncontext\n", encoding="utf-8")
        end = self.commit("change")
        self.page.write_text("uncommitted content\n", encoding="utf-8")
        before = self.git("status", "--porcelain")
        result, payload = self.impact(baseline, "--until", end)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertEqual(payload["until"], end)
        change = payload["changes"][0]
        self.assertEqual((change["path"], change["kind"]), ("fact.md", "M"))
        self.assertEqual(change["old_blob"], self.git("rev-parse", f"{baseline}:fact.md"))
        self.assertEqual(change["new_blob"], self.git("rev-parse", f"{end}:fact.md"))
        self.assertEqual(change["diff_stat"], {"insertions": 1, "deletions": 1})
        pin = change["pins"][0]
        self.assertEqual((pin["source"], pin["status"], pin["tip_sha"]), ("citation.md", "changed", end))
        self.assertEqual(pin["fragment"], "claim")
        self.assertEqual(pin["verdict"], "unknown")
        self.assertEqual(pin["verdict_basis"], ["fragment_unavailable"])

    def test_no_pins_and_explicit_identity(self) -> None:
        self.page.write_text("different\n", encoding="utf-8")
        self.commit("change")
        result, payload = self.impact(self.first, "--atlas-id", ID)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["changes"][0]["pins"], [])

    def test_numeric_decision_verdict_in_impact(self) -> None:
        self.page.write_text("## Decision\n\nThe fare is 10.\n", encoding="utf-8")
        cited = self.commit("decision")
        (self.repo / "citation.md").write_text(
            f"atlas://{ID}/fact.md@{cited}#decision\n", encoding="utf-8"
        )
        baseline = self.commit("cite")
        self.page.write_text("## Decision\n\nThe fare is 20.\n", encoding="utf-8")
        self.commit("change number")
        result, payload = self.impact(baseline)
        self.assertEqual(result.returncode, 0, result.stderr)
        pin = next(change for change in payload["changes"] if change["path"] == "fact.md")["pins"][0]
        self.assertEqual(pin["verdict"], "contradicts")
        self.assertEqual(pin["verdict_basis"], ["replaced_numbers"])

    def test_rename_and_delete_with_citations(self) -> None:
        (self.repo / "citation.md").write_text(
            f"atlas://{ID}/fact.md@{self.first}\n", encoding="utf-8"
        )
        baseline = self.commit("cite")
        self.git("mv", "fact.md", "renamed.md")
        rename = self.commit("rename")
        result, payload = self.impact(baseline)
        self.assertEqual(result.returncode, 0, result.stderr)
        change = payload["changes"][0]
        self.assertEqual((change["kind"], change["old_path"], change["path"]), ("R", "fact.md", "renamed.md"))
        self.assertEqual(change["diff_stat"], {"insertions": 0, "deletions": 0})
        self.assertEqual(change["pins"][0]["status"], "renamed")
        self.git("rm", "renamed.md")
        self.commit("delete")
        result, payload = self.impact(rename)
        self.assertEqual(result.returncode, 0, result.stderr)
        change = payload["changes"][0]
        self.assertEqual((change["kind"], change["path"], change["new_blob"]), ("D", "renamed.md", None))
        self.assertEqual(change["pins"][0]["status"], "deleted")
        self.assertEqual(change["pins"][0]["verdict"], "contradicts")
        result, payload = self.impact(baseline)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["changes"][0]["pins"][0]["status"], "deleted")

    def test_unavailable_citation_and_invalid_ref_fail_closed(self) -> None:
        (self.repo / "citation.md").write_text(
            f"atlas://{ID}/fact.md@{'f' * 40}\n", encoding="utf-8"
        )
        baseline = self.commit("cite")
        self.page.write_text("changed\n", encoding="utf-8")
        self.commit("change")
        result, payload = self.impact(baseline)
        self.assertEqual(result.returncode, 0, result.stderr)
        pin = payload["changes"][0]["pins"][0]
        self.assertEqual((pin["status"], pin["reason"]), ("cited_unavailable", "commit_missing"))
        self.assertEqual(pin["verdict"], "unknown")
        self.assertNotIn("text", pin)
        result, payload = self.impact("missing-ref")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(payload["ok"])

    def test_substore_and_literal_paths(self) -> None:
        store = self.repo / "store"
        store.mkdir()
        page = store / "[claim].md"
        page.write_text("before\n", encoding="utf-8")
        baseline = self.commit("substore")
        page.write_text("after\n", encoding="utf-8")
        self.commit("update")
        result = subprocess.run(
            [sys.executable, str(ATLAS), "link", "impact", "--root", str(store),
             "--atlas-id", ID, "--since", baseline, "--json"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        change = json.loads(result.stdout)["changes"][0]
        self.assertEqual(change["path"], "[claim].md")
        self.assertEqual(change["diff_stat"], {"insertions": 1, "deletions": 1})


if __name__ == "__main__":
    unittest.main()
