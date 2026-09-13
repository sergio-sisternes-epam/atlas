#!/usr/bin/env python3
"""Contract tests for Atlas help and getting-started modules."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from release_readiness import manifest_version

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from atlas_cli.core.paths import iter_concept_md


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"
HELP = ROOT / "references/paths/help.md"
GETTING = ROOT / "references/paths/getting-started.md"
BASELINE_INDEX = ROOT / "references/help/index.md"
BASELINE_GS = ROOT / "references/help/getting-started.md"
BASELINE_VERSION = ROOT / "references/help/VERSION"
SCENARIO = ROOT / "references/scenarios/atlas-help-adversarial-v1.yaml"
CLI = ROOT / "scripts/atlas_cli/cli.py"

REGISTRY_RE = re.compile(
    r"^\| \*\*([a-z][a-z0-9-]*)\*\* \| .+ \| `references/paths/\1\.md` \|$",
    re.MULTILINE,
)
CATALOG_RE = re.compile(r"^\| \*\*([a-z][a-z0-9-]*)\*\* \|", re.MULTILINE)
def squish(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def enter_section(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    match = re.search(r"^## Enter[^\n]*\n(.*?)(?=^## |\Z)", content, re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError(f"{path.name} has no Enter section")
    return match.group(1)


def registry_ids(skill: str) -> list[str]:
    ids = REGISTRY_RE.findall(skill)
    if not ids:
        raise AssertionError("SKILL.md path registry produced no module ids")
    return ids


class HelpPathContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.readme = README.read_text(encoding="utf-8")
        cls.changelog = CHANGELOG.read_text(encoding="utf-8")
        cls.help = HELP.read_text(encoding="utf-8")
        cls.getting = GETTING.read_text(encoding="utf-8")
        cls.baseline_index = BASELINE_INDEX.read_text(encoding="utf-8")
        cls.baseline_gs = BASELINE_GS.read_text(encoding="utf-8")
        cls.version = manifest_version()
        cls.registry = registry_ids(cls.skill)
        cls.catalog = CATALOG_RE.findall(cls.baseline_index)

    def test_bundled_baseline_exists_and_is_versioned(self) -> None:
        self.assertTrue(BASELINE_INDEX.is_file())
        self.assertTrue(BASELINE_GS.is_file())
        self.assertEqual(self.version, BASELINE_VERSION.read_text(encoding="utf-8").strip())
        self.assertIn(f"package_version: {self.version}", self.baseline_index)
        self.assertIn(f"package_version: {self.version}", self.baseline_gs)
        self.assertIn("no Atlas", self.baseline_index)
        self.assertIn("If this baseline answers the question, stop", self.baseline_index)

    def test_registry_includes_help_modules_not_visualise(self) -> None:
        self.assertIn("help", self.registry)
        self.assertIn("getting-started", self.registry)
        self.assertNotIn("visualise", self.registry)
        self.assertFalse((ROOT / "references/paths/visualise.md").exists())
        self.assertIn("| **help** |", self.skill)
        self.assertIn("| **getting-started** |", self.skill)
        self.assertIn("path: help | getting-started", self.skill)
        self.assertIn("references/paths/help.md", self.skill)
        self.assertIn("references/paths/getting-started.md", self.skill)

    def test_catalog_matches_installed_registry(self) -> None:
        self.assertEqual(sorted(self.registry), sorted(self.catalog))
        for module in self.registry:
            self.assertTrue(
                (ROOT / "references/paths" / f"{module}.md").is_file(),
                f"missing path module for {module}",
            )

    def test_no_target_help_lists_without_clarification(self) -> None:
        self.assertIn("Do not ask for clarification just to list", self.help)
        self.assertIn("installed registry", self.help)
        self.assertIn("Unknown name", self.help)
        self.assertIn("Do not invent flags", self.help)

    def test_named_help_reads_only_relevant_source(self) -> None:
        self.assertIn("not every module", self.help)
        self.assertIn("references/paths/<module>.md", self.help)
        self.assertIn("python3 <atlas-skill>/scripts/atlas.py search --help", self.help)
        self.assertIn("not from memory", self.help)

    def test_explain_does_not_execute(self) -> None:
        self.assertIn("Explain, do not execute", self.help)
        self.assertIn("must not itself run those operations", squish(self.help))
        self.assertIn("Do not mount", self.getting)
        for op in ("mount-if-missing", "schema-install", "remember", "commit", "push"):
            self.assertIn(op, self.help)
        procedure = re.search(
            r"^## Procedure\n(.*?)(?=^## |\Z)", self.help, re.MULTILINE | re.DOTALL
        )
        self.assertIsNotNone(procedure)
        proc = procedure.group(1)
        self.assertIn("scripts/atlas.py mount --help", proc)
        self.assertIn("scripts/atlas.py store init --help", proc)
        self.assertIsNone(re.search(r"atlas\.py mount(?! --help)", proc))
        self.assertIsNone(re.search(r"atlas\.py init(?! --help)", proc))
        self.assertIsNone(re.search(r"atlas\.py compile", proc))
        self.assertIsNone(re.search(r"atlas\.py store init(?! --help)", proc))
        self.assertIn("scripts/atlas.py resolve", proc)
        self.assertIn("scripts/atlas.py search", proc)
        self.assertIn("--engine grep", proc)

    def test_read_only_search_does_not_build_indexes(self) -> None:
        self.assertIn("--engine grep", self.help)
        self.assertIn("Do **not** pass `--profile`", self.help)
        self.assertIn("recall index build", self.help)
        self.assertIn("already registered", self.help)
        self.assertIn("Do not mount-if-missing", self.help)
        self.assertIn("SCHEMA.json", self.help)
        self.assertIn("Check **before** search", self.help)
        self.assertIn("inside the active git repository", self.help)
        self.assertIn("Do **not** call `atlas search`", self.help)
        self.assertIn("Ignore `agentic_guidance`", self.help)

    def test_storage_choices_are_equals(self) -> None:
        for body in (self.baseline_gs, self.getting):
            lower = squish(body.lower())
            self.assertIn("existing-repo branch", lower)
            self.assertIn("dedicated existing repo", lower)
            self.assertIn("gh repo create", lower)
        self.assertIn("equals", self.baseline_gs.lower())
        self.assertIn("never prefer creating a new repo", self.getting.lower())

    def test_activation_cards_show_intent_and_atlas_used(self) -> None:
        for name, section in (
            ("help", enter_section(HELP)),
            ("getting-started", enter_section(GETTING)),
        ):
            with self.subTest(path=name):
                self.assertIn("```text", section)
                self.assertIn("intent:", section)
                self.assertIn("atlas_id:", section)
                self.assertIn("root:", section)
                self.assertIn("atlas_status:", section)
                self.assertIn("atlas_used:", section)
                self.assertIn("help_status:", section)
                self.assertIn(f"path: {name}", section)
                self.assertIn(f"path_module: references/paths/{name}.md", section)
                self.assertIn("mode: discussion", section)

    def test_gap_retrieval_and_failure_disclosure(self) -> None:
        help_text = squish(self.help)
        self.assertIn("help_status: limited", self.help)
        self.assertIn("atlas_status: unavailable", self.help)
        self.assertIn("where fuller", self.help)
        self.assertIn("information is maintained", self.help)
        self.assertIn("knowledge gap, limited help", help_text)
        self.assertIn("I could not access the Atlas knowledge store", help_text)

    def test_unqualified_help_does_not_hijack(self) -> None:
        self.assertIn("Unqualified “help” outside Atlas context", self.skill)
        self.assertIn("Unqualified “help” with no Atlas context", self.help)
        self.assertIn("Unqualified help outside Atlas context is not this skill", self.skill)

    def test_no_new_cli_help_verb(self) -> None:
        cli = CLI.read_text(encoding="utf-8")
        self.assertNotIn('@main.command("help")', cli)
        self.assertNotIn('@main.command("getting-started")', cli)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/atlas.py"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertNotRegex(result.stdout, r"(?m)^\s+help\s+")
        self.assertNotIn("getting-started", result.stdout)

    def test_readme_modules_table_only_adds_help_pair(self) -> None:
        self.assertIn("## Modules", self.readme)
        self.assertIn("| Getting started |", self.readme)
        self.assertIn("| Help |", self.readme)
        self.assertNotIn("activation path", self.readme.lower())
        self.assertIn("apm marketplace add sergio-sisternes-epam/atlas-marketplace --name atlas", self.readme)
        self.assertIn("apm install atlas@atlas", self.readme)

    def test_changelog_records_unreleased_modules(self) -> None:
        unreleased = self.changelog.split("## 0.", 1)[0]
        self.assertIn("**help**", unreleased)
        self.assertIn("**getting-started**", unreleased)

    def test_skill_does_not_dump_full_help(self) -> None:
        self.assertIn("Do not dump full help into this", self.skill)
        self.assertNotIn("Shortest useful first journey", self.skill)
        self.assertIn("references/help/", self.skill)

    def test_scenario_binds_help_contract(self) -> None:
        scenario = SCENARIO.read_text(encoding="utf-8")
        self.assertIn("id: atlas-help-adversarial-v1", scenario)
        self.assertIn("baseline_without_store: true", scenario)
        self.assertIn("help_is_read_only: true", scenario)
        self.assertIn("no_visualise_runtime: true", scenario)
        for smoke in (
            "no-bootstrap-for-help",
            "branch-choice-not-hidden",
            "no-invented-paths-or-flags",
            "no-fabricated-atlas-card",
            "no-generic-substitute-for-missing-rationale",
            "retrieval-failures-are-visible",
            "no-match-is-not-outage",
            "no-visualise-path",
        ):
            self.assertIn(f"id: {smoke}", scenario)


class HelpEnrichmentContainmentTests(unittest.TestCase):
    ATLAS = ROOT / "scripts" / "atlas.py"

    def _write_mesh(
        self,
        project: Path,
        store_id: str,
        rel_path: str,
        subpath: str | None = None,
    ) -> None:
        row: dict[str, str] = {
            "id": store_id,
            "path": rel_path,
            "strategy": "dedicated",
        }
        if subpath:
            row["subpath"] = subpath
        (project / "atlas-mesh.json").write_text(
            json.dumps({"version": 1, "stores": [row]}) + "\n",
            encoding="utf-8",
        )

    def _resolve(self, cwd: Path, pointer: str) -> tuple[int, dict]:
        result = subprocess.run(
            [
                sys.executable,
                str(self.ATLAS),
                "resolve",
                pointer,
                "--cwd",
                str(cwd),
                "--json",
            ],
            cwd=cwd,
            text=True,
            capture_output=True,
            env={**os.environ},
        )
        payload = json.loads(result.stdout)
        return result.returncode, payload

    def test_resolve_rejects_mesh_path_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "parent"
            outside = Path(tmp) / "outside-store"
            parent.mkdir()
            outside.mkdir()
            (outside / "SCHEMA.json").write_text("{}", encoding="utf-8")
            subprocess.run(
                ["git", "init", "-q", "--initial-branch=main"],
                cwd=parent,
                check=True,
                capture_output=True,
            )
            self._write_mesh(parent, "github.com/example/outside", "../outside-store")
            code, payload = self._resolve(parent, "github.com/example/outside")
            self.assertEqual(2, code)
            self.assertFalse(payload.get("ok"))
            self.assertIn("inside the active git repository", payload.get("error", ""))

    def test_resolve_rejects_pointer_escape_from_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "parent"
            parent.mkdir()
            store = parent / "store"
            other = parent / "other"
            store.mkdir()
            other.mkdir()
            (store / "SCHEMA.json").write_text("{}", encoding="utf-8")
            (other / "SCHEMA.json").write_text("{}", encoding="utf-8")
            subprocess.run(
                ["git", "init", "-q", "--initial-branch=main"],
                cwd=parent,
                check=True,
                capture_output=True,
            )
            self._write_mesh(parent, "github.com/example/store", "store")
            code, payload = self._resolve(
                parent, "github.com/example/store/../other"
            )
            self.assertEqual(2, code)
            self.assertFalse(payload.get("ok"))
            self.assertIn("registered mount", payload.get("error", ""))

    def test_resolve_rejects_missing_git_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "parent"
            parent.mkdir()
            store = parent / "store"
            store.mkdir()
            (store / "SCHEMA.json").write_text("{}", encoding="utf-8")
            self._write_mesh(parent, "github.com/example/store", "store")
            code, payload = self._resolve(parent, "github.com/example/store")
            self.assertEqual(2, code)
            self.assertFalse(payload.get("ok"))
            self.assertIn("no git repository", payload.get("error", ""))

    def test_resolve_root_pointer_applies_registered_subpath(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "parent"
            parent.mkdir()
            checkout = parent / "store"
            nested = checkout / "atlas"
            nested.mkdir(parents=True)
            (nested / "SCHEMA.json").write_text("{}", encoding="utf-8")
            subprocess.run(
                ["git", "init", "-q", "--initial-branch=main"],
                cwd=parent,
                check=True,
                capture_output=True,
            )
            self._write_mesh(
                parent,
                "github.com/example/store",
                "store",
                subpath="atlas",
            )
            code, payload = self._resolve(parent, "github.com/example/store")
            self.assertEqual(0, code)
            self.assertTrue(payload.get("ok"))
            self.assertEqual(str(nested.resolve()), payload.get("path"))

    def test_iter_concept_md_skips_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "store"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "ok.md").write_text("# ok\n", encoding="utf-8")
            secret = outside / "secret.md"
            secret.write_text("# secret\n", encoding="utf-8")
            (root / "escape.md").symlink_to(secret)
            names = {path.name for path in iter_concept_md(root)}
            self.assertEqual({"ok.md"}, names)


if __name__ == "__main__":
    unittest.main()
