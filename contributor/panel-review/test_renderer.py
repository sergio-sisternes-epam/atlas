#!/usr/bin/env python3
"""Specification tests for panel receipts and recommendation rendering."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE_SKILL = ROOT / ".apm" / "skills" / "panel-review"
SKILL = ROOT / ".agents" / "skills" / "panel-review"
SPEC = importlib.util.spec_from_file_location(
    "panel_renderer", HERE / "render_summary.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load panel renderer specification")
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


def load_fixture(name: str):
    return json.loads((HERE / "fixtures" / name).read_text(encoding="utf-8"))


class RendererSpecTest(unittest.TestCase):
    def test_clean_fixture_has_useful_nonempty_lens_detail(self):
        payload = load_fixture("clean.json")
        rendered = renderer.render_summary(payload)
        self.assertEqual(rendered, renderer.render_summary(payload))
        self.assertIn("## Atlas panel: ship now", rendered)
        self.assertEqual(rendered.count("<details>"), 2)
        self.assertEqual(rendered.count("No findings after the checks above."), 2)
        self.assertIn("Verified staging remains excluded", rendered)
        self.assertNotIn("### Top items", rendered)
        self.assertNotIn("### Dissent", rendered)
        self.assertNotIn("|  |", rendered)

    def test_needs_rework_preserves_dissent_and_inline_location(self):
        payload = load_fixture("needs-rework.json")
        rendered = renderer.render_summary(payload)
        self.assertIn("## Atlas panel: needs rework", rendered)
        self.assertIn("### Dissent", rendered)
        self.assertIn("### Top items", rendered)
        self.assertIn("`scripts/atlas_cli/compile.py:88`", rendered)
        self.assertLessEqual(len(payload["synthesizer"]["top_items"]), 3)
        self.assertEqual(len(renderer.inline_findings(payload)), 1)

    def test_malformed_receipt_is_rejected(self):
        payload = load_fixture("malformed-receipt.json")
        with self.assertRaisesRegex(ValueError, "lens_id"):
            renderer.validate_payload(payload)
        payload["panelists"][0]["lens_id"] = "atlas-contract"
        with self.assertRaisesRegex(ValueError, "summary"):
            renderer.validate_payload(payload)

    def test_finding_without_evidence_is_rejected(self):
        payload = load_fixture("needs-rework.json")
        del payload["panelists"][0]["findings"][0]["evidence"]
        with self.assertRaisesRegex(ValueError, "finding fields"):
            renderer.validate_payload(payload)

    def test_coverage_accepts_schema_maximum_length(self):
        payload = load_fixture("clean.json")
        payload["panelists"][0]["coverage"][0] = "x" * 240
        renderer.validate_payload(payload)

    def test_duplicate_panelist_evidence_is_rejected(self):
        for field in ("coverage", "limitations"):
            with self.subTest(field=field):
                payload = load_fixture("clean.json")
                item = (
                    payload["panelists"][0][field][0]
                    if field == "coverage"
                    else "No material limitations."
                )
                payload["panelists"][0][field] = [item, item]
                with self.assertRaisesRegex(ValueError, "unique"):
                    renderer.validate_payload(payload)

    def test_runtime_schema_and_template_contract(self):
        self.assertEqual(
            (SOURCE_SKILL / "SKILL.md").read_text(),
            (SKILL / "SKILL.md").read_text(),
        )
        panelist = json.loads(
            (SKILL / "assets" / "panelist-receipt.schema.json").read_text()
        )
        synthesizer = json.loads(
            (SKILL / "assets" / "synthesizer-receipt.schema.json").read_text()
        )
        template = (SKILL / "assets" / "recommendation-template.md").read_text()
        self.assertIn("summary", panelist["required"])
        self.assertGreaterEqual(panelist["properties"]["summary"]["minLength"], 1)
        self.assertEqual(panelist["properties"]["coverage"]["minItems"], 1)
        self.assertEqual(panelist["properties"]["coverage"]["items"]["maxLength"], 240)
        self.assertIn(
            "evidence",
            panelist["$defs"]["finding"]["required"],
        )
        self.assertEqual(synthesizer["properties"]["top_items"]["maxItems"], 3)
        self.assertIn("| Lens | Blocker | Recommended | Nits | Takeaway |", template)
        self.assertIn("Retry only a malformed slot once", (SKILL / "SKILL.md").read_text())
        self.assertIn(
            "do not infer absence from a partial diff",
            (SKILL / "SKILL.md").read_text(),
        )
        self.assertIn(
            "validated receipts + deterministic checks only",
            (SKILL / "SKILL.md").read_text(),
        )
        self.assertIn(
            "Never report errors in a",
            (SKILL / "SKILL.md").read_text(),
        )
        self.assertIn(
            "full reviewer capable of cross-file reasoning",
            (SKILL / "SKILL.md").read_text(),
        )

    def test_lenses_bound_page_and_nested_skill_rules(self):
        atlas_lens = (
            SKILL / "references" / "lenses" / "atlas-contract.md"
        ).read_text()
        skill_lens = (
            SKILL / "references" / "lenses" / "skill-agent-contract.md"
        ).read_text()
        self.assertIn("YAML scenario/eval fixtures are not OKF pages", atlas_lens)
        self.assertIn("Nested skills use their own local references/assets", skill_lens)
        self.assertIn("Do not request a", skill_lens)
        self.assertIn("`version` field", skill_lens)
        self.assertIn("Contributor panel evals stay outside", skill_lens)

    def test_contributor_eval_inventory_and_split(self):
        evals = json.loads((HERE / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual(len(evals["content_evals"]), 3)
        triggers = evals["trigger_evals"]
        self.assertEqual(len(triggers), 16)
        self.assertEqual(sum(item["should_trigger"] for item in triggers), 8)
        self.assertEqual(
            sum(not item["should_trigger"] for item in triggers),
            8,
        )
        self.assertEqual(sum(item["split"] == "train" for item in triggers), 10)
        self.assertEqual(
            sum(item["split"] == "validation" for item in triggers),
            6,
        )


if __name__ == "__main__":
    unittest.main()
