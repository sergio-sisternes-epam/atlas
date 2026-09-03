#!/usr/bin/env python3
"""Contract tests for the Atlas CI activation path and GitHub adapters."""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COPY = ROOT / "references/ci/github-actions.compile.yml"
CALLER = ROOT / "references/ci/github-actions.caller.yml"
REUSABLE = ROOT / ".github/workflows/atlas-compile.yml"
PATH_CI = ROOT / "references/paths/ci.md"
SCENARIO = ROOT / "references/scenarios/ci-activation-adversarial-v1.yaml"
CI_REQUIREMENTS = ROOT / "scripts/requirements-ci.txt"


class CiActivationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.copy = COPY.read_text(encoding="utf-8")
        cls.caller = CALLER.read_text(encoding="utf-8")
        cls.reusable = REUSABLE.read_text(encoding="utf-8")
        cls.path_ci = PATH_CI.read_text(encoding="utf-8")
        cls.scenario = SCENARIO.read_text(encoding="utf-8")
        cls.ci_requirements = CI_REQUIREMENTS.read_text(encoding="utf-8")

    def test_path_and_router_are_distinct_from_compile_path(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("| **ci** |", skill)
        self.assertIn(
            "path: query | remember | work | landscape | schema | ci", skill
        )
        self.assertIn("`path: compile` is the agent-session", self.path_ci)

    def test_version_is_consistent(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        manifest = (ROOT / "apm.yml").read_text(encoding="utf-8")
        self.assertIn("version: 0.8.13", skill)
        self.assertIn("version: 0.8.13", manifest)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/atlas.py"), "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual("atlas, version 0.8.13", result.stdout.strip())

    def test_gate_is_unfocused(self) -> None:
        compile_gate = re.compile(
            r'atlas\.py"?\s+compile\s+(?:\\\s*)?'
            r'--root\s+"?\$ROOT"?\s+--json\b'
        )
        for workflow in (self.copy, self.reusable):
            self.assertRegex(workflow, compile_gate)
            self.assertNotIn("--path", workflow)
            self.assertNotIn("--type", workflow)

    def test_exit_one_warns_and_exit_two_fails(self) -> None:
        for workflow in (self.copy, self.reusable):
            self.assertIn('if [ "$status" -ge 2 ]', workflow)
            self.assertIn('if [ "$status" -eq 1 ]', workflow)
            self.assertNotIn("continue-on-error", workflow)
            self.assertIn("python3 -m json.tool atlas-compile.json", workflow)

    def test_missing_schema_fails_closed(self) -> None:
        for workflow in (self.copy, self.reusable):
            self.assertIn('test -f "$ROOT/SCHEMA.json"', workflow)

    def test_cli_is_acquired_outside_workspace(self) -> None:
        for workflow in (self.copy, self.reusable):
            self.assertIn('$RUNNER_TEMP/atlas-cli.', workflow)
            self.assertNotIn("$GITHUB_WORKSPACE", workflow)

    def test_cli_downloads_use_configured_token(self) -> None:
        token_env = (
            "ATLAS_TOKEN: ${{ secrets.ATLAS_CLI_TOKEN || github.token }}"
        )
        auth_header = '--header "Authorization: Bearer $ATLAS_TOKEN"'
        for workflow in (self.copy, self.reusable):
            self.assertIn(token_env, workflow)
            self.assertEqual(2, workflow.count(auth_header))

    def test_cli_dependencies_are_exactly_locked(self) -> None:
        requirements = self.ci_requirements.splitlines()
        self.assertTrue(requirements)
        for requirement in requirements:
            self.assertRegex(requirement, r"^[A-Za-z0-9_.-]+==[^\s]+$")
        self.assertTrue(any(line.startswith("click==") for line in requirements))
        self.assertTrue(
            any(line.startswith("jsonschema==") for line in requirements)
        )
        for workflow in (self.copy, self.reusable):
            self.assertIn("scripts/requirements-ci.txt", workflow)
            self.assertNotIn(
                'pip install -r "$ATLAS_CLI/scripts/requirements.txt"',
                workflow,
            )

    def test_cli_archive_ref_is_encoded_and_temp_file_is_unique(self) -> None:
        for workflow in (self.copy, self.reusable):
            self.assertIn(
                'urllib.parse.quote(os.environ["ATLAS_REF"], safe="")', workflow
            )
            self.assertIn(
                '"https://api.github.com/repos/$ATLAS_REPO/tarball/$archive_ref"',
                workflow,
            )
            self.assertIn(
                'archive="$(mktemp "$RUNNER_TEMP/atlas-cli.XXXXXX")"', workflow
            )
            self.assertNotIn(
                'archive="$RUNNER_TEMP/atlas-cli.tar.gz"', workflow
            )

    def test_cli_default_ref_is_not_a_floating_branch(self) -> None:
        floating_env_ref = re.compile(
            r"^\s*ATLAS_REF:\s*(?:main|master)\s*$", re.MULTILINE
        )
        floating_input_default = re.compile(
            r"^\s*default:\s*(?:main|master)\s*$", re.MULTILINE
        )
        for workflow in (self.copy, self.reusable):
            self.assertIn(
                "ATLAS_REF must be a tag or 40-character commit SHA", workflow
            )
        self.assertNotRegex(self.copy, floating_env_ref)
        self.assertNotRegex(self.reusable, floating_input_default)

    def test_cli_ref_normalizes_tags_and_rejects_other_qualified_refs(self) -> None:
        for workflow in (self.copy, self.reusable):
            self.assertIn(
                'ATLAS_REF="${ATLAS_REF#refs/tags/}"', workflow
            )
            self.assertIn("refs/*)", workflow)

    def test_third_party_actions_are_sha_pinned(self) -> None:
        external_use = re.compile(r"^\s*uses:\s+(?!\./)(\S+)", re.MULTILINE)
        sha_pinned = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
        for workflow in (self.copy, self.reusable):
            refs = external_use.findall(workflow)
            self.assertTrue(refs)
            for ref in refs:
                self.assertRegex(ref, sha_pinned)

    def test_reusable_and_caller_have_separate_triggers(self) -> None:
        self.assertIn("workflow_call:", self.reusable)
        self.assertNotIn("  pull_request:", self.reusable)
        self.assertNotIn("  push:", self.reusable)
        self.assertIn("  pull_request:", self.caller)
        self.assertIn("  push:", self.caller)
        self.assertIn("@v0.8.13", self.caller)

    def test_adversarial_contract_names_all_approved_smokes(self) -> None:
        for smoke in (
            "not-path-compile",
            "focused-compile-forbidden-in-ci",
            "exit-2-fails-exit-1-does-not",
            "missing-schema-not-success",
            "floating-main-pin-forbidden",
            "dependency-closure-locked",
            "skill-pytest-not-mount-ci",
            "cli-not-in-workspace-root",
        ):
            self.assertIn(f"id: {smoke}", self.scenario)


if __name__ == "__main__":
    unittest.main()
