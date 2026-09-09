#!/usr/bin/env python3
"""Executable opt-in schema contracts; discovered by scripts/run_tests.py."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_cli.commands.init import DEFAULT_SCHEMA
from atlas_cli.commands.schema_config import configure
from atlas_cli.core.frontmatter import split_fm
from atlas_cli.core.schema import validate_schema_shape
from atlas_cli.core.type_rules import declaration_errors, h2_sections, page_rule_errors

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "native-schema"
OVERLAY = json.loads((FIXTURE / "SCHEMA.overlay.json").read_text())
BLOCK = OVERLAY["templates"]["by_type"]["sample-record"]


class NativeSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atlas-native-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "store"
        self.cli("init", expected=0)

    def cli(self, *args, expected=None):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/atlas.py"), *args, "--root", str(self.root), "--json"],
            capture_output=True, text=True,
        )
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def install(self):
        self.cli("schema", "configure", "--max-required-sections-per-type", "7", expected=0)
        self.cli("schema", "install", str(FIXTURE), expected=0)
        (self.root / "source.md").write_text((FIXTURE / "source.md").read_text())

    def test_fixtures_executable_and_focus(self):
        self.install()
        page = self.root / "record.md"
        page.write_text((FIXTURE / "missing-category.md").read_text())
        failure = json.loads(self.cli("compile", expected=2).stdout)
        self.assertIn("required_sections", [x["id"] for x in failure["critical"]])
        page.write_text((FIXTURE / "passing.md").read_text())
        self.cli("compile", expected=0)
        self.cli("validate", "--type", "sample-record", expected=0)
        self.cli("compile", "--path", "record.md", expected=0)

    def test_executable_field_date_and_link_failures(self):
        self.install()
        original = (FIXTURE / "passing.md").read_text()
        cases = [
            (original.replace("score: 0", "score: 11"), "field_contract"),
            (original.replace("ended: Unknown.", "ended: 2026-02-30"), "field_contract"),
            (original.replace("ended: Unknown.", "ended: 2026-08-31"), "date_order"),
            (original.replace("path: source.md", "path: templates/document.md"), "typed_relates_to"),
            (original.replace("kind: records", "role: records"), "typed_relates_to"),
        ]
        for text, issue in cases:
            with self.subTest(issue=issue):
                (self.root / "record.md").write_text(text)
                result = json.loads(self.cli("compile", "--type", "sample-record", expected=2).stdout)
                self.assertIn(issue, [i["id"] for i in result["critical"]])

    def test_budget_atomicity_preservation_default(self):
        path = self.root / "SCHEMA.json"
        initial = json.loads(path.read_bytes())
        initial["custom_settings"] = {"untouched": ["yes", {"nested": 42}]}
        path.write_text(json.dumps(initial))
        original = path.read_bytes()
        self.cli("schema", "install", str(FIXTURE), expected=2)
        self.assertFalse((self.root / "schema.d/sample-contract.json").exists())
        self.assertEqual(path.read_bytes(), original)
        self.install()
        before = json.loads(original)
        after = json.loads(path.read_bytes())
        after["compile"]["simplicity_budget"]["max_required_sections_per_type"] = 6
        self.assertEqual(before, after)
        installed = path.read_bytes()
        self.cli("schema", "configure", "--max-required-sections-per-type", "6", expected=2)
        self.assertEqual(installed, path.read_bytes())
        self.cli("schema", "configure", "--max-required-sections-per-type", "-1", expected=2)
        self.assertEqual(installed, path.read_bytes())
        self.assertEqual(DEFAULT_SCHEMA["compile"]["simplicity_budget"]["max_required_sections_per_type"], 6)
        with patch("atlas_cli.commands.schema_config.os.replace", side_effect=OSError("synthetic write failure")):
            self.assertEqual(configure(str(self.root), 8, True), 2)
        self.assertEqual(installed, path.read_bytes())
        self.assertEqual(list(self.root.glob(".SCHEMA-*.tmp")), [])

    def test_configure_rejects_symlink_and_malformed_budgets(self):
        path = self.root / "SCHEMA.json"
        original = path.read_bytes()
        moved = self.root.parent / "core.json"
        path.rename(moved)
        path.symlink_to(moved)
        self.cli("schema", "configure", "--max-required-sections-per-type", "7", expected=2)
        self.assertEqual(moved.read_bytes(), original)
        path.unlink()
        for budget in ([], None, {"max_required_sections_per_type": "7"}, {"max_required_sections_per_type": True}):
            schema = json.loads(original)
            schema["compile"]["simplicity_budget"] = budget
            path.write_text(json.dumps(schema))
            before = path.read_bytes()
            self.cli("schema", "configure", "--max-required-sections-per-type", "7", expected=2)
            self.cli("compile", expected=2)
            self.assertEqual(path.read_bytes(), before)

    def test_core_override_forbidden(self):
        overlay = copy.deepcopy(OVERLAY)
        overlay["compile"] = {"simplicity_budget": {"max_required_sections_per_type": 100}}
        source = self.root.parent / "override.json"
        source.write_text(json.dumps(overlay))
        original = (self.root / "SCHEMA.json").read_bytes()
        self.cli("schema", "install", str(source), "--force", expected=2)
        self.assertEqual((self.root / "SCHEMA.json").read_bytes(), original)
        self.assertFalse((self.root / "schema.d/sample-contract.json").exists())

    def test_capability_receipt(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/atlas.py"), "schema", "capabilities", "--json"],
            capture_output=True, text=True, check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["capability_version"], 1)
        self.assertTrue(payload["atlas_version"])
        self.assertEqual(set(payload["features"]), {
            "required_h2_sections", "scalar_date_rules", "date_order_rules",
            "typed_local_relates_to", "core_section_budget_configure", "receipt_hash_template_upgrades",
        })
        self.assertTrue(all(value == 1 for value in payload["features"].values()))

    def test_heading_parser_adversarial(self):
        block = {"sections": {"enforce": True, "required": ["Evidence"], "require_content": True}}
        cases = [
            ("## Evidence\nUnknown.", True),
            ("## Evidence ###\nUnknown.\n## Extra\nExtra.", True),
            ("## Evidence\n<!-- comment\nonly -->\n", False),
            ("## Evidence\n### Child\n", False),
            ("## Evidence\n# New top\nUnrelated content", False),
            ("## Evidence\n\n## Extra\nUnrelated content", False),
            ("## Evidence\nUnknown.\n## Evidence\nAgain", False),
            ("## evidence\nWrong case", False),
            ("### Evidence\nWrong level", False),
            ("    ## Evidence\nIndented code", False),
            ("```\n## Evidence\nUnknown.\n```\n", False),
            ("~~~~lang\n## Evidence\n~~~\nStill fenced\n~~~~\n", False),
            ("<!--\n## Evidence\nUnknown.\n-->", False),
            ("## Evidence\n```text\n## Evidence\nUnknown.\n```\n", True),
            ("## Evidence\n```\n```\n", False),
            ("## Evidence\n~~~\n<!-- literal code comment\n~~~\n", True),
        ]
        for body, succeeds in cases:
            with self.subTest(body=body):
                self.assertEqual(not page_rule_errors(self.root, {}, body, block), succeeds)
        self.assertEqual(h2_sections("## Evidence\nUnknown.\n"), {"Evidence": ["Unknown."]})
        self.assertEqual(page_rule_errors(self.root, {}, "", {"sections": {"required": ["Evidence"]}}), [])

    def test_malformed_declarations(self):
        cases = [
            {"sections": {"enforce": "true", "required": ["Evidence"]}},
            {"sections": {"enforce": True}},
            {"sections": {"enforce": True, "required": "Evidence"}},
            {"sections": {"required": ["Evidence", "Evidence"]}},
            {"sections": {"required": [None]}},
            {"sections": {"required": ["Evidence\nOther"]}},
            {"sections": {"require_content": True}},
            {"sections": {"enforce": True, "required": [], "requre_content": True}},
            {"frontmatter": {"fields": []}},
            {"frontmatter": {"fields": {"x": {"type": []}}}},
            {"frontmatter": {"fields": {"x": {"type": "integer", "minimum": True}}}},
            {"frontmatter": {"fields": {"x": {"type": "string", "minimum": 1}}}},
            {"frontmatter": {"fields": {"x": {"type": "integer", "minimum": 4, "maximum": 1}}}},
            {"frontmatter": {"fields": {"x": {"type": "date", "unknown": "Unknown."}}}},
            {"frontmatter": {"date_order": [{"before": "x", "after": "y"}]}},
            {"relates_to": [{"kind": "records", "target_types": ["x"], "min": -1}]},
            {"relates_to": [{"kind": "records", "target_types": ["x"], "min": 2, "max": 1}]},
            {"relates_to": [{"kind": "records", "target_types": []}]},
            {"relates_to": [{"kind": "records", "target_types": ["x"], "minimum": 2}]},
            {"sections": None}, {"frontmatter": None}, {"relates_to": None},
        ]
        for block in cases:
            with self.subTest(block=block):
                self.assertTrue(declaration_errors("sample", block))
                schema = copy.deepcopy(DEFAULT_SCHEMA)
                schema["templates"]["by_type"]["sample"] = block
                self.assertTrue(validate_schema_shape(schema))
                (self.root / "SCHEMA.json").write_text(json.dumps(schema))
                self.cli("compile", expected=2)

    def test_scalar_dates_order(self):
        block = {"frontmatter": BLOCK["frontmatter"]}
        for start, end, expected in [
            ("2024-02-29", "2024-02-29", True),
            ("2023-02-29", "2024-03-01", False),
            ("2026-09-02", "2026-09-01", False),
            ("2026-09-01", "Unknown.", True),
            ("Unknown.", "2026-09-01", True),
            ("Unknown", "2026-09-01", False),
            ("20260901", "2026-09-01", False),
            ("2026-9-1", "2026-09-01", False),
            ("2026-09-01T00:00:00Z", "2026-09-01", False),
        ]:
            meta = {"started": start, "ended": end}
            with self.subTest(meta=meta):
                self.assertEqual(not page_rule_errors(self.root, meta, "", block), expected)
        strict = copy.deepcopy(block)
        strict["frontmatter"]["date_order"][0]["allow_equal"] = False
        self.assertTrue(page_rule_errors(self.root, {"started": "2024-02-29", "ended": "2024-02-29"}, "", strict))
        for score, success in [("0", True), ("10", True), ("-1", False), ("11", False), ("1.5", False), ([], False), ("", False)]:
            self.assertEqual(not page_rule_errors(self.root, {"score": score}, "", block), success)
        for kind, good, bad in [("boolean", "false", "False"), ("number", "1.25e2", "NaN"), ("integer", "-120", "1e2")]:
            rule = {"frontmatter": {"fields": {"value": {"type": kind}}}}
            self.assertEqual(page_rule_errors(self.root, {"value": good}, "", rule), [])
            self.assertTrue(page_rule_errors(self.root, {"value": bad}, "", rule))
        number_rule = {"frontmatter": {"fields": {"value": {"type": "number"}}}}
        self.assertTrue(page_rule_errors(self.root, {"value": "1e" + "9" * 100}, "", number_rule))
        number_rule["frontmatter"]["fields"]["value"].update(minimum=1.1, maximum=1.1)
        self.assertEqual(page_rule_errors(self.root, {"value": "1.1"}, "", number_rule), [])
        self.assertTrue(page_rule_errors(self.root, {"status": "bad"}, "", block))
        self.assertEqual(page_rule_errors(self.root, {}, "", block), [])

    def test_links_local_typed_and_bounds(self):
        block = {"relates_to": BLOCK["relates_to"]}
        (self.root / "source.md").write_text((FIXTURE / "source.md").read_text())
        (self.root / "wrong.md").write_text("---\ntype: different\n---\nContent.")
        (self.root / "folder").mkdir()
        (self.root / "alias.md").symlink_to(self.root / "source.md")
        outside = self.root.parent / "outside.md"
        outside.write_text((FIXTURE / "source.md").read_text())
        (self.root / "escape.md").symlink_to(outside)
        for target, valid in [
            ("source.md", True), ("alias.md", True), ("wrong.md", False), ("missing.md", False),
            ("folder", False), ("index.md", False), ("templates/document.md", False),
            ("../outside.md", False), ("escape.md", False),
            ("https://example.test/source.md", False), ("atlas://example.test/org/repo/source.md", False),
            (str(outside), False),
        ]:
            meta = {"relates_to": [{"path": target, "kind": "records"}]}
            with self.subTest(target=target):
                self.assertEqual(not page_rule_errors(self.root, meta, "", block), valid)
        self.assertTrue(page_rule_errors(self.root, {}, "", block))
        self.assertTrue(page_rule_errors(self.root, {"relates_to": [{"path": "source.md", "role": "records"}]}, "", block))
        duplicate = {"relates_to": [{"path": "source.md", "kind": "records"}, {"path": "alias.md", "kind": "records"}]}
        self.assertTrue(page_rule_errors(self.root, duplicate, "", block))
        unbounded = {"relates_to": [{"kind": "records", "target_types": ["sample-source"]}]}
        self.assertEqual(page_rule_errors(self.root, {}, "", unbounded), [])
        (self.root / "second.md").write_text((FIXTURE / "source.md").read_text())
        two = {"relates_to": [{"path": "source.md", "kind": "records"}, {"path": "second.md", "kind": "records"}]}
        self.assertEqual(page_rule_errors(self.root, two, "", unbounded), [])
        self.assertTrue(page_rule_errors(self.root, two, "", block))
        extra = {"relates_to": [{"path": "source.md", "kind": "records"}, {"path": "wrong.md", "kind": "related"}]}
        self.assertEqual(page_rule_errors(self.root, extra, "", block), [])

    def test_no_inline_bypass_and_legacy_compatibility(self):
        self.install()
        text = (FIXTURE / "missing-category.md").read_text()
        (self.root / "record.md").write_text(text + "\n<!-- atlas-ignore: required_sections -->\n")
        self.cli("compile", expected=2)
        (self.root / "record.md").write_text("---\ntype: arbitrary-unregistered\n---\n" + "Legacy custom types remain legal. " * 3)
        self.cli("compile", expected=0)
        meta, _ = split_fm("---\nscore: 0\nflag: false\nended: Unknown.\n---\n")
        self.assertEqual(meta, {"score": "0", "flag": "false", "ended": "Unknown."})


if __name__ == "__main__":
    unittest.main()
