#!/usr/bin/env python3
"""Contract tests for the code-review discovery adapter."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / ".apm" / "skills" / "code-review" / "SKILL.md"
DEPLOYED = ROOT / ".agents" / "skills" / "code-review" / "SKILL.md"
DEPLOYED_PANEL = ROOT / ".agents" / "skills" / "panel-review" / "SKILL.md"


class CodeReviewContractTest(unittest.TestCase):
    def test_adapter_loads_deployed_panel_and_defers_runtime_fallback(self):
        source = SOURCE.read_text(encoding="utf-8")
        deployed = DEPLOYED.read_text(encoding="utf-8")
        self.assertIn("name: code-review", deployed)
        self.assertIn("Execute the loaded panel procedure end-to-end", deployed)
        self.assertIn("Runtime execution fallback remains owned", deployed)

        match = re.search(r"\[panel-review\]\(([^)]+)\)", deployed)
        self.assertIsNotNone(match)
        target = (DEPLOYED.parent / match.group(1)).resolve()
        self.assertTrue(target.is_file())
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            DEPLOYED_PANEL.read_text(encoding="utf-8"),
        )
        self.assertEqual(
            source.replace("../panel-review/SKILL.md", match.group(1)),
            deployed,
        )

    def test_adapter_does_not_duplicate_panel_contract(self):
        body = SOURCE.read_text(encoding="utf-8")
        for panel_detail in (
            "atlas-contract",
            "python-cli",
            "security-gitops",
            "Blocker",
            "Recommended",
            "Nit",
        ):
            self.assertNotIn(panel_detail, body)

    def test_manifest_and_scenario_declare_both_skills(self):
        manifest = (ROOT / "apm.yml").read_text(encoding="utf-8")
        self.assertIn(".apm/skills/code-review/", manifest)
        self.assertIn(".apm/skills/panel-review/", manifest)

        scenario = (
            ROOT / "references" / "scenarios" / "code-review-panel-delegation-v1.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("panel_load_mandatory: true", scenario)
        self.assertIn("missing_panel_fails_closed: true", scenario)
        self.assertIn(
            "unavailable_children_use_sequential_fallback: true",
            scenario,
        )
        self.assertIn("panel_logic_not_duplicated: true", scenario)

    def test_eval_inventory_is_balanced(self):
        evals = json.loads((HERE / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual(len(evals["content_evals"]), 3)
        triggers = evals["trigger_evals"]
        self.assertEqual(len(triggers), 16)
        self.assertEqual(sum(item["should_trigger"] for item in triggers), 8)
        self.assertEqual(sum(not item["should_trigger"] for item in triggers), 8)
        self.assertEqual(sum(item["split"] == "train" for item in triggers), 10)
        self.assertEqual(sum(item["split"] == "validation" for item in triggers), 6)

        panel_evals = json.loads(
            (ROOT / "contributor" / "panel-review" / "evals.json").read_text(
                encoding="utf-8"
            )
        )
        code_routes = {
            item["query"]: item["should_trigger"] for item in triggers
        }
        panel_routes = {
            item["query"]: item["should_trigger"]
            for item in panel_evals["trigger_evals"]
        }
        self.assertTrue(code_routes["Review this PR."])
        self.assertFalse(panel_routes["Review this PR."])
        self.assertFalse(code_routes["Run the panel on PR #7."])
        self.assertTrue(panel_routes["Run the panel on PR #7."])


if __name__ == "__main__":
    unittest.main()
