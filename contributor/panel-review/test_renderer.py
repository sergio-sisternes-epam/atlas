#!/usr/bin/env python3
"""Specification tests for panel receipts and recommendation rendering."""

from __future__ import annotations

import importlib.util
import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE_SKILL = ROOT / ".apm" / "skills" / "panel-review"
SKILL = ROOT / ".agents" / "skills" / "panel-review"
SPEC = importlib.util.spec_from_file_location(
    "panel_renderer", HERE / "render_summary.py"
)
if SPEC is None or SPEC.loader is None:
    raise ImportError("Unable to load panel renderer specification")
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

    def test_multiline_summary_stays_inside_html_summary(self):
        payload = load_fixture("clean.json")
        payload["panelists"][0]["summary"] = "First line\nSecond line"
        rendered = renderer.render_summary(payload)
        self.assertIn(
            "<summary>atlas-contract - First line Second line</summary>",
            rendered,
        )

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

    def test_non_posix_finding_paths_are_rejected(self):
        for path in (
            r"..\secret.py",
            r"C:\repo\file.py",
            r"src\file.py",
            "src/\nfile.py",
        ):
            with self.subTest(path=path):
                payload = load_fixture("needs-rework.json")
                payload["panelists"][0]["findings"][0]["path"] = path
                with self.assertRaisesRegex(ValueError, "repo-relative"):
                    renderer.validate_payload(payload)

    def test_finding_path_uses_safe_markdown_code_span(self):
        payload = load_fixture("needs-rework.json")
        payload["panelists"][0]["findings"][0]["path"] = "src/odd`name.py"
        rendered = renderer.render_summary(payload)
        self.assertIn("``src/odd`name.py:88``", rendered)

    def test_runtime_schemas_accept_multiline_text(self):
        payload = load_fixture("needs-rework.json")
        panelist = payload["panelists"][0]
        panelist["summary"] = "First line\nSecond line"
        panelist["coverage"][0] = "First check\nSecond check"
        panelist["limitations"] = ["First limit\nSecond limit"]
        finding = panelist["findings"][0]
        for field in ("title", "rationale", "follow_up", "evidence"):
            finding[field] = f"First {field}\nSecond {field}"

        panelist_schema = json.loads(
            (
                SKILL / "assets" / "panelist-receipt.schema.json"
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator(panelist_schema).validate(panelist)

        synthesizer = payload["synthesizer"]
        for field in ("headline", "synthesis", "dissent"):
            synthesizer[field] = f"First {field}\nSecond {field}"
        synthesizer["top_items"][0]["title"] = finding["title"]
        synthesizer["top_items"][0]["why"] = "First reason\nSecond reason"
        synthesizer["ship_recommendation"]["rationale"] = (
            "First recommendation\nSecond recommendation"
        )
        synthesizer_schema = json.loads(
            (
                SKILL / "assets" / "synthesizer-receipt.schema.json"
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator(synthesizer_schema).validate(synthesizer)

    def test_runtime_schema_and_template_contract(self):
        self.assertEqual(
            (SOURCE_SKILL / "SKILL.md").read_text(encoding="utf-8"),
            (SKILL / "SKILL.md").read_text(encoding="utf-8"),
        )
        panelist = json.loads(
            (SKILL / "assets" / "panelist-receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        synthesizer = json.loads(
            (SKILL / "assets" / "synthesizer-receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        template = (SKILL / "assets" / "recommendation-template.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("summary", panelist["required"])
        self.assertGreaterEqual(panelist["properties"]["summary"]["minLength"], 1)
        self.assertEqual(panelist["properties"]["coverage"]["minItems"], 1)
        self.assertEqual(panelist["properties"]["coverage"]["items"]["maxLength"], 240)
        self.assertIn(
            "evidence",
            panelist["$defs"]["finding"]["required"],
        )
        path_pattern = panelist["$defs"]["finding"]["properties"]["path"]["pattern"]
        self.assertIsNotNone(re.fullmatch(path_pattern, "src/module.py"))
        for path in (
            r"..\secret.py",
            r"C:\repo\file.py",
            r"src\file.py",
            "src/\nfile.py",
        ):
            self.assertIsNone(re.fullmatch(path_pattern, path))
        self.assertEqual(synthesizer["properties"]["top_items"]["maxItems"], 3)
        self.assertIn("| Lens | Blocker | Recommended | Nits | Takeaway |", template)
        skill_body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Retry only a malformed slot once", skill_body)
        self.assertIn(
            "do not infer absence from a partial diff",
            skill_body,
        )
        self.assertIn(
            "validated receipts + deterministic checks only",
            skill_body,
        )
        self.assertIn(
            "Never report errors in a",
            skill_body,
        )
        self.assertRegex(
            skill_body,
            r"full\s+reviewer capable of cross-file reasoning",
        )
        self.assertRegex(
            skill_body,
            r"execution mode to\s+`sequential fallback`",
        )
        self.assertIn(
            "Sequential fallback: no child context isolation",
            skill_body,
        )
        self.assertIn("synthesize locally", skill_body)

    def test_lenses_bound_page_and_nested_skill_rules(self):
        atlas_lens = (
            SKILL / "references" / "lenses" / "atlas-contract.md"
        ).read_text(encoding="utf-8")
        skill_lens = (
            SKILL / "references" / "lenses" / "skill-agent-contract.md"
        ).read_text(encoding="utf-8")
        self.assertIn("YAML scenario/eval fixtures are not OKF pages", atlas_lens)
        self.assertIn("Nested skills use their own local references/assets", skill_lens)
        self.assertIn("Do not request a", skill_lens)
        self.assertIn("`version` field", skill_lens)
        self.assertIn("Contributor panel evals stay outside", skill_lens)

    def test_contributor_eval_inventory_and_split(self):
        evals = json.loads((HERE / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual(len(evals["content_evals"]), 4)
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
