#!/usr/bin/env python3
"""Structure mode and recall receipt regressions."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.commands.init import DEFAULT_CONTRACT  # noqa: E402
from test_memory_layers import init_legacy  # noqa: E402

CLAIM = "The archive keeps the reference record with its supporting notes."


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args], cwd=ROOT, text=True, capture_output=True
    )


def write_page(path: Path, kind: str, body: str, extra: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntype: {kind}\ntitle: Topic\ncreated: 2000-01-01\n{extra}---\n\n"
        f"## Content\n\n{body}\n",
        encoding="utf-8",
    )


def ids(payload: dict, bucket: str) -> set[str]:
    return {item["id"] for item in payload[bucket]}


class StructureModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def init_store(self, version: str = "1.0") -> Path:
        root = self.base / f"store-{version}"
        result = run("init", "--root", str(root), "--schema-version", version, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        return root

    def contract(self, root: Path) -> dict:
        name = "CONTRACT.json" if (root / "CONTRACT.json").exists() else "SCHEMA.json"
        return json.loads((root / name).read_text(encoding="utf-8"))

    def save_contract(self, root: Path, contract: dict) -> None:
        name = "CONTRACT.json" if (root / "CONTRACT.json").exists() else "SCHEMA.json"
        (root / name).write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    def compile(self, root: Path, *args: str) -> tuple[int, dict]:
        result = run("compile", "--root", str(root), "--dry-run", "--json", *args)
        self.assertTrue(result.stdout, result.stderr)
        return result.returncode, json.loads(result.stdout)

    def cue_fixture(self, root: Path) -> None:
        notes = root / "notes"
        write_page(notes / "record.md", "memory", CLAIM)
        write_page(
            notes / "topics.schema.md", "schema",
            "This schema describes the kinds of records contained in the notes folder.",
        )
        (notes / "index.md").write_text(
            "# Notes\n\n"
            f"- [Notes schema](topics.schema.md) - notes: memory pages. {CLAIM}\n",
            encoding="utf-8",
        )
        (root / "index.md").write_text(
            "# Store\n\n## Folder schemas\n"
            f"- [Notes schema](notes/topics.schema.md) - notes: memory pages. {CLAIM}\n",
            encoding="utf-8",
        )

    def test_init_default_and_absent_mode_for_both_store_versions(self) -> None:
        for version in ("1.0", "2.0"):
            with self.subTest(version=version):
                root = self.init_store(version)
                self.cue_fixture(root)
                contract = self.contract(root)
                self.assertEqual(contract["compile"]["structure"], {"mode": "off"})
                code, baseline = self.compile(root)
                self.assertEqual(code, 0, baseline)
                self.assertIn("missing_gist", ids(baseline, "info"))
                self.assertNotIn("schema_cue_claim", ids(baseline, "warnings") | ids(baseline, "critical"))
                for structure in ({}, None):
                    if structure is None:
                        contract["compile"].pop("structure", None)
                    else:
                        contract["compile"]["structure"] = structure
                    self.save_contract(root, contract)
                    actual_code, actual = self.compile(root)
                    self.assertEqual(actual_code, code)
                    for bucket in ("info", "warnings", "critical"):
                        self.assertEqual(actual[bucket], baseline[bucket])

    def test_warning_error_and_memory_rung_are_independent(self) -> None:
        root = self.init_store()
        self.cue_fixture(root)
        contract = self.contract(root)
        for mode, bucket, expected_code in (("warn", "warnings", 1), ("error", "critical", 2)):
            with self.subTest(mode=mode):
                contract["compile"]["structure"]["mode"] = mode
                self.save_contract(root, contract)
                code, result = self.compile(root)
                findings = [item for item in result[bucket] if item["id"] == "schema_cue_claim"]
                self.assertEqual(code, expected_code, result)
                self.assertEqual({item["path"] for item in findings}, {"index.md", "notes/index.md"})
                self.assertEqual({item["severity"] for item in findings}, {
                    "warning" if mode == "warn" else "critical"
                })
                self.assertNotIn(CLAIM, json.dumps(findings))
                self.assertIn("missing_gist", ids(result, "info"))
                other = "critical" if bucket == "warnings" else "warnings"
                self.assertNotIn("schema_cue_claim", ids(result, other))

        contract["memory"]["rung"] = "warn"
        self.save_contract(root, contract)
        _, result = self.compile(root)
        self.assertIn("schema_cue_claim", ids(result, "critical"))
        self.assertIn("missing_gist", ids(result, "warnings"))
        contract["compile"]["structure"]["mode"] = "off"
        contract["memory"]["rung"] = "error"
        self.save_contract(root, contract)
        _, result = self.compile(root)
        self.assertIn("missing_gist", ids(result, "critical"))
        self.assertNotIn("schema_cue_claim", ids(result, "critical") | ids(result, "warnings"))

    def test_shipped_cue_format_is_clean_in_warn_and_error(self) -> None:
        for version in ("1.0", "2.0"):
            root = self.init_store(version)
            notes = root / "notes"
            write_page(notes / "record.md", "memory", CLAIM)
            write_page(
                notes / "topic.gist.md", "gist", CLAIM,
                "relates_to:\n  - path: notes/record.md\n    kind: derived_from\n",
            )
            write_page(
                notes / "topics.schema.md", "schema",
                "This schema describes the kinds of records contained in the notes folder.",
                "relates_to:\n  - path: notes/topic.gist.md\n    kind: related\n",
            )
            (root / "index.md").write_text(
                "# Store\n\n## Folder schemas\n"
                "- [Notes schema](notes/topics.schema.md) - notes: gist, memory pages\n",
                encoding="utf-8",
            )
            (notes / "index.md").write_text(
                "# Notes\n\n"
                "- [Notes schema](topics.schema.md) - notes: gist, memory pages\n",
                encoding="utf-8",
            )
            contract = self.contract(root)
            for mode in ("warn", "error"):
                with self.subTest(version=version, mode=mode):
                    contract["compile"]["structure"]["mode"] = mode
                    self.save_contract(root, contract)
                    code, result = self.compile(root)
                    self.assertEqual(code, 0, result)
                    for bucket in ("info", "warnings", "critical"):
                        self.assertNotIn("schema_cue_claim", ids(result, bucket))

    def test_valid_and_invalid_modes_in_both_versions(self) -> None:
        for version in ("1.0", "2.0"):
            root = self.init_store(version)
            self.cue_fixture(root)
            contract = self.contract(root)
            for mode in ("off", "warn", "error"):
                with self.subTest(version=version, mode=mode):
                    contract["compile"]["structure"] = {"mode": mode}
                    self.save_contract(root, contract)
                    _, result = self.compile(root)
                    self.assertNotIn("schema_v2", ids(result, "critical"))
                    self.assertNotIn("structure_mode", ids(result, "critical"))
            for structure in (None, [], {"mode": None}, {"mode": False}, {"mode": ""}, {"mode": "info"}):
                with self.subTest(version=version, structure=structure):
                    contract["compile"]["structure"] = structure
                    self.save_contract(root, contract)
                    code, result = self.compile(root)
                    self.assertEqual(code, 2)
                    self.assertIn("structure_mode", ids(result, "critical"))
                    self.assertNotIn("schema_cue_claim", ids(result, "warnings") | ids(result, "critical"))

    def test_cues_are_integrity_checks_not_completeness_checks(self) -> None:
        root = self.init_store()
        self.cue_fixture(root)
        contract = self.contract(root)
        contract["compile"]["structure"]["mode"] = "warn"
        self.save_contract(root, contract)
        (root / "notes" / "index.md").write_text(
            "# Notes\n\n- [Notes schema](topics.schema.md) - notes: memory pages\n"
            f"\n```markdown\n- [Notes schema](topics.schema.md) - {CLAIM}\n```\n",
            encoding="utf-8",
        )
        (root / "index.md").write_text("# Store\n\nNo folder list yet.\n", encoding="utf-8")
        code, result = self.compile(root)
        self.assertEqual(code, 0, result)
        self.assertNotIn("schema_cue_claim", ids(result, "warnings"))

        (root / "notes" / "index.md").write_text(
            f"# Notes\n\n- [Notes schema](topics.schema.md) - {CLAIM}\n"
            "<!-- atlas-ignore: schema_cue_claim -->\n",
            encoding="utf-8",
        )
        _, result = self.compile(root)
        self.assertNotIn("schema_cue_claim", ids(result, "warnings"))
        contract["compile"]["allow_inline_ignores"] = False
        self.save_contract(root, contract)
        _, result = self.compile(root, "--path", "notes")
        self.assertIn("schema_cue_claim", ids(result, "warnings"))
        _, result = self.compile(root, "--type", "schema")
        self.assertIn("schema_cue_claim", ids(result, "warnings"))
        _, result = self.compile(root, "--path", "notes/topics.schema.md")
        self.assertIn("schema_cue_claim", ids(result, "warnings"))
        _, result = self.compile(root, "--type", "memory")
        self.assertNotIn("schema_cue_claim", ids(result, "warnings"))
        _, result = self.compile(root, "--path", "notes/record.md")
        self.assertNotIn("schema_cue_claim", ids(result, "warnings"))

    def test_long_fences_hide_claims_and_cue_examples(self) -> None:
        root = self.init_store()
        self.cue_fixture(root)
        contract = self.contract(root)
        contract["compile"]["structure"]["mode"] = "warn"
        self.save_contract(root, contract)
        notes = root / "notes"

        write_page(
            notes / "record.md",
            "memory",
            f"````markdown\n```\n{CLAIM}\n``` info\n````",
        )
        for index, schema_link in (
            (root / "index.md", "notes/topics.schema.md"),
            (notes / "index.md", "topics.schema.md"),
        ):
            index.write_text(
                f"# Index\n\n- [Notes schema]({schema_link}) - notes: memory pages. {CLAIM}\n",
                encoding="utf-8",
            )
        _, result = self.compile(root)
        self.assertNotIn("schema_cue_claim", ids(result, "warnings"))

        write_page(notes / "record.md", "memory", CLAIM)
        for index, schema_link in (
            (root / "index.md", "notes/topics.schema.md"),
            (notes / "index.md", "topics.schema.md"),
        ):
            index.write_text(
                "# Index\n\n````markdown\n```\n"
                f"- [Notes schema]({schema_link}) - notes: memory pages. {CLAIM}\n"
                "``` info\n````\n",
                encoding="utf-8",
            )
        _, result = self.compile(root)
        self.assertNotIn("schema_cue_claim", ids(result, "warnings"))

    def test_list_nested_fences_hide_claims_and_cues(self) -> None:
        root = self.init_store()
        self.cue_fixture(root)
        contract = self.contract(root)
        contract["compile"]["structure"]["mode"] = "error"
        self.save_contract(root, contract)
        notes = root / "notes"
        (root / "index.md").write_text("# Store\n", encoding="utf-8")
        for marker, indent in (("-", "  "), ("1.", "   ")):
            with self.subTest(marker=marker):
                example = (
                    f"{marker} ````markdown\n{indent}```\n"
                    f"{indent}- [Notes schema](topics.schema.md) - {CLAIM}\n"
                    f"{indent}````\n"
                )
                write_page(notes / "record.md", "memory", CLAIM)
                (notes / "index.md").write_text("# Notes\n\n" + example, encoding="utf-8")
                _, result = self.compile(root)
                self.assertNotIn("schema_cue_claim", ids(result, "critical"))

                write_page(notes / "record.md", "memory", example)
                (notes / "index.md").write_text(
                    f"# Notes\n\n- [Notes schema](topics.schema.md) - {CLAIM}\n",
                    encoding="utf-8",
                )
                _, result = self.compile(root)
                self.assertNotIn("schema_cue_claim", ids(result, "critical"))

    def test_comments_hide_cues_and_claims(self) -> None:
        root = self.init_store()
        self.cue_fixture(root)
        contract = self.contract(root)
        contract["compile"]["structure"]["mode"] = "error"
        self.save_contract(root, contract)
        notes = root / "notes"
        (root / "index.md").write_text("# Store\n", encoding="utf-8")
        (notes / "index.md").write_text(
            f"# Notes\n\n<!-- hidden\n- [Notes schema](topics.schema.md) - {CLAIM}\n-->\n",
            encoding="utf-8",
        )
        _, result = self.compile(root)
        self.assertNotIn("schema_cue_claim", ids(result, "critical"))

        write_page(notes / "record.md", "memory", f"<!-- hidden\n{CLAIM}\n-->")
        (notes / "index.md").write_text(
            f"# Notes\n\n- [Notes schema](topics.schema.md) - {CLAIM}\n",
            encoding="utf-8",
        )
        _, result = self.compile(root)
        self.assertNotIn("schema_cue_claim", ids(result, "critical"))

    def test_wrapped_cue_reports_first_line(self) -> None:
        root = self.init_store()
        self.cue_fixture(root)
        contract = self.contract(root)
        contract["compile"]["structure"]["mode"] = "error"
        self.save_contract(root, contract)
        (root / "index.md").write_text("# Store\n", encoding="utf-8")
        (root / "notes" / "index.md").write_text(
            "# Notes\n\n<!-- hidden\nignored\n-->\n"
            "- [Notes schema](topics.schema.md) -\n"
            f"  {CLAIM}\n",
            encoding="utf-8",
        )
        _, result = self.compile(root)
        findings = [item for item in result["critical"] if item["id"] == "schema_cue_claim"]
        self.assertEqual(len(findings), 1, result)
        self.assertIn("line 6", findings[0]["msg"])

    def test_existing_findings_remain_without_structure_block(self) -> None:
        root = self.init_store()
        notes = root / "notes"
        write_page(notes / "record.md", "memory", CLAIM)
        write_page(notes / "legacy.md", "document", CLAIM)
        write_page(notes / "orphan.gist.md", "gist", CLAIM)
        write_page(
            notes / "topic.gist.md", "gist", CLAIM,
            "description: This description deliberately differs from the memory page.\n"
            "relates_to:\n  - path: notes/record.md\n    kind: derived_from\n",
        )
        write_page(
            notes / "topic.schema.md", "schema", CLAIM,
            "relates_to:\n  - path: notes/topic.gist.md\n    kind: related\n",
        )
        (notes / "index.md").write_text("# Notes\n", encoding="utf-8")
        contract = self.contract(root)
        _, baseline = self.compile(root)
        self.assertTrue({"schema_folder", "schema_missing_from_index", "stale_upper_page"}
                        <= ids(baseline, "critical"))
        self.assertTrue({"legacy_document", "missing_gist", "gist_parent"} <= ids(baseline, "info"))
        for structure in (None, {"mode": "warn"}, {"mode": "error"}):
            if structure is None:
                contract["compile"].pop("structure", None)
            else:
                contract["compile"]["structure"] = structure
            self.save_contract(root, contract)
            _, result = self.compile(root)
            for bucket in ("info", "warnings", "critical"):
                self.assertEqual(result[bucket], baseline[bucket])

        legacy = self.base / "legacy"
        self.assertEqual(init_legacy(legacy).returncode, 0)
        write_page(legacy / "notes" / "record.md", "document", CLAIM)
        write_page(legacy / "notes" / "orphan.gist.md", "gist", CLAIM)
        (legacy / "notes" / "index.md").write_text("# Notes\n", encoding="utf-8")
        _, before = self.compile(legacy)
        self.assertTrue({"frame_members", "gist_parent", "missing_gist", "legacy_document"}
                        <= ids(before, "info"))
        old_contract = self.contract(legacy)
        old_contract["compile"]["structure"] = {"mode": "off"}
        self.save_contract(legacy, old_contract)
        _, after = self.compile(legacy)
        for bucket in ("info", "warnings", "critical"):
            self.assertEqual(after[bucket], before[bucket])

    def test_public_defaults_and_documented_receipt_examples(self) -> None:
        defaults = json.dumps(DEFAULT_CONTRACT)
        self.assertNotIn('"warn"', defaults)
        self.assertNotIn("write_gate", defaults)
        self.assertNotIn("escalate_at", defaults)
        self.assertIsNone(re.search(r"\b\d{4}-\d{2}-\d{2}\b", defaults))

        recall = (ROOT / "references" / "paths" / "recall.md").read_text(encoding="utf-8")
        self.assertRegex(
            recall, r"## Folder schemas\n\s*- \[Notes schema\]\(notes/topics\.schema\.md\)"
                    r" - notes: decisions and memories"
        )
        rows = [line for line in recall.splitlines() if "| correct |" in line]
        examples = [tuple(cell.strip() for cell in row.strip("|").split("|")) for row in rows]
        for stop in ("memory", "recall_hit"):
            self.assertIn((
                "Fact not on opened schema/gist; answer from memory snippet", "correct",
                "schema, gist", stop, "miss: memory page not opened",
            ), examples)
        self.assertIn(("Answer from opened memory page", "correct",
                       "schema, gist, memory", "memory", "hit"), examples)
        self.assertIn(("Answer from opened memory page", "correct",
                       "memory", "recall_hit", "hit"), examples)
        for layer in ("schema", "gist"):
            self.assertIn((
                f"Opened {layer} states the fact; memory page also exists",
                "correct", layer, layer, "hit",
            ), examples)
        self.assertIn(("Answer from recall-hit media or work pointer", "correct",
                       "none", "recall_hit", "hit"), examples)
        for hidden_term in ("gold expected stop", "accepted evidence path", "Gold stop",
                            "accepted memory", "miss: wrong stop"):
            self.assertNotIn(hidden_term, recall)
        self.assertIn(
            "Stop at the schema or relevant gist if the page you opened states the fact",
            recall,
        )
        self.assertIn(
            "A schema or gist stop remains valid when that opened page states the fact",
            recall,
        )
        self.assertIn("The memory-page receipt obligation applies when the fact is not stated", recall)
        self.assertIn("regardless of the `stopped_at` label", recall)
        self.assertIn("do not copy memory claims or pin every gist", recall)
        self.assertIn("A hub is never a stop", recall)


if __name__ == "__main__":
    unittest.main()
