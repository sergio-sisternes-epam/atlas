#!/usr/bin/env python3
"""Receipt-managed schema installs: python3 scripts/test_template_upgrades.py."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from atlas_cli.commands import schema_cmd
from atlas_cli.core.overlay import merge_overlays, receipt_issues


ROOT = Path(__file__).resolve().parents[1]


class TemplateUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.work = ROOT / f".atlas-template-tests-{uuid.uuid4().hex}"
        self.store = self.work / "store"
        self.source = self.work / "contribution"
        self.store.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.work)
        self.core = {
            "schema_version": "1.0",
            "atlas_id": "template-tests",
            "structure": {},
            "compile": {},
            "templates": {"by_type": {}},
        }
        self.overlay = {
            "contribution_id": "example",
            "claimed_folders": [],
            "templates": {
                "by_type": {
                    "sample": {
                        "file": "templates/sample.md",
                        "frontmatter": {"required": ["type", "title"]},
                    }
                }
            },
        }
        self.write_json(self.store / "SCHEMA.json", self.core)
        self.save_overlay()
        self.write(self.source / "templates/sample.md", "original template\n")

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_json(self, path, content):
        self.write(path, json.dumps(content) + "\n")

    def save_overlay(self):
        self.write_json(self.source / "SCHEMA.overlay.json", self.overlay)

    @property
    def receipt_path(self):
        return self.store / "schema.d/example.receipt.json"

    @property
    def target(self):
        return self.store / "templates/sample.md"

    def receipt(self):
        return json.loads(self.receipt_path.read_text())

    def install(self, force=False):
        out = io.StringIO()
        with redirect_stdout(out):
            code = schema_cmd.run_install(str(self.source), str(self.store), force, True)
        return code, json.loads(out.getvalue())

    def uninstall(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = schema_cmd.run_uninstall("example", str(self.store), True)
        return code, json.loads(out.getvalue())

    def snapshot(self):
        return {
            p.relative_to(self.store).as_posix(): (
                ("link", os.readlink(p)) if p.is_symlink()
                else ("directory",) if p.is_dir()
                else ("file", p.read_bytes(), p.stat().st_mode)
            )
            for p in self.store.rglob("*")
        }

    def assert_install_rejected(self, match, force=False):
        before = self.snapshot()
        code, payload = self.install(force)
        self.assertEqual(code, 2, payload)
        self.assertIn(match, payload["error"])
        self.assertEqual(self.snapshot(), before)

    def test_hash_owned_install_repeat_upgrade_and_uninstall(self):
        code, payload = self.install()
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["templates_copied"], ["sample"])
        digest = hashlib.sha256(self.target.read_bytes()).hexdigest()
        receipt = self.receipt()
        self.assertEqual(receipt["template_hashes"], {"templates/sample.md": digest})
        self.assertEqual(receipt["added_types"], ["sample"])
        self.assertEqual(receipt["written"], [
            "schema.d/example.json", "schema.d/example.receipt.json", "templates/sample.md",
        ])
        before = self.snapshot()
        self.assertEqual(self.install()[0], 0)
        self.assertEqual(self.snapshot(), before)
        self.write(self.source / "templates/sample.md", "upgraded template\n")
        code, payload = self.install()
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["templates_updated"], ["sample"])
        self.assertEqual(self.target.read_text(), "upgraded template\n")
        self.assertEqual(self.receipt()["template_hashes"]["templates/sample.md"],
                         hashlib.sha256(self.target.read_bytes()).hexdigest())
        self.assertEqual(self.uninstall()[0], 0)
        self.assertFalse(self.target.exists())
        self.assertTrue((self.store / "SCHEMA.json").exists())

    def test_force_only_bypasses_required_key_compatibility(self):
        self.assertEqual(self.install()[0], 0)
        self.overlay["templates"]["by_type"]["sample"]["frontmatter"]["required"].append("created")
        self.save_overlay()
        self.write(self.source / "templates/sample.md", "new required field\n")
        self.assert_install_rejected("required keys changed")
        self.assertEqual(self.install(force=True)[0], 0)
        self.assertEqual(self.target.read_text(), "new required field\n")
        self.write(self.target, "user edited\n")
        self.assert_install_rejected("user-edited template", force=True)
        self.assert_install_rejected("user-edited template")

    def test_source_matching_user_edit_does_not_reestablish_ownership(self):
        self.assertEqual(self.install()[0], 0)
        self.write(self.target, "user edited\n")
        self.write(self.source / "templates/sample.md", "user edited\n")
        self.assert_install_rejected("user-edited template", force=True)

    def test_unmanaged_identical_template_stays_unowned(self):
        self.write(self.target, "original template\n")
        self.assertEqual(self.install()[0], 0)
        self.assertEqual(self.receipt()["template_hashes"], {})
        self.assertNotIn("templates/sample.md", self.receipt()["written"])
        self.assertEqual(self.install()[0], 0)
        self.assertEqual(self.receipt()["template_hashes"], {})
        self.write(self.source / "templates/sample.md", "different\n")
        self.assert_install_rejected("unowned template", force=True)
        self.assertEqual(self.uninstall()[0], 0)
        self.assertTrue(self.target.exists())

    def test_unmanaged_different_template_blocks_new_install(self):
        self.write(self.target, "user template\n")
        self.assert_install_rejected("unowned template", force=True)

    def test_legacy_receipt_preserved_without_hash_authority(self):
        self.assertEqual(self.install()[0], 0)
        receipt = self.receipt()
        del receipt["template_hashes"]
        receipt["legacy_annotation"] = "preserve"
        self.write_json(self.receipt_path, receipt)
        self.assertEqual(self.install()[0], 0)
        after = self.receipt()
        self.assertEqual(after["template_hashes"], {})
        self.assertEqual(after["written"], receipt["written"])
        self.assertEqual(after["legacy_annotation"], "preserve")
        self.write(self.source / "templates/sample.md", "cannot upgrade legacy\n")
        self.assert_install_rejected("unowned template", force=True)
        code, payload = self.uninstall()
        self.assertEqual(code, 0, payload)
        self.assertTrue(self.target.exists())
        self.assertTrue(any("unhashed" in note for note in payload["notes"]))

    def test_missing_receipt_does_not_authorize_existing_template_upgrade(self):
        self.assertEqual(self.install()[0], 0)
        self.receipt_path.unlink()
        self.assertEqual(self.install()[0], 0)
        self.assertEqual(self.receipt()["template_hashes"], {})
        self.write(self.source / "templates/sample.md", "new\n")
        self.assert_install_rejected("unowned template", force=True)

    def test_missing_legacy_template_can_be_created_and_owned(self):
        self.assertEqual(self.install()[0], 0)
        receipt = self.receipt()
        receipt.pop("template_hashes")
        self.write_json(self.receipt_path, receipt)
        self.target.unlink()
        self.assertEqual(self.install()[0], 0)
        self.assertIn("templates/sample.md", self.receipt()["template_hashes"])

    def test_invalid_shape_rejected_before_any_writes(self):
        variants = [
            ("atlas_id", "clobber", "must not set core key"),
            ("claimed_folders", ["/escape"], "claimed_folders"),
            ("types", {"recommended": [123]}, "types.recommended"),
            ("templates", {"by_type": []}, "templates.by_type"),
            ("templates", {"by_type": {"sample": []}}, "must be an object"),
            ("templates", {"directory": "other", "by_type": {}}, "templates.directory"),
            ("templates", {"by_type": {"work": {}}}, "core type"),
        ]
        baseline = copy.deepcopy(self.overlay)
        for key, value, match in variants:
            with self.subTest(key=key, value=value):
                self.overlay = copy.deepcopy(baseline)
                self.overlay[key] = value
                self.save_overlay()
                self.assert_install_rejected(match, force=True)

    def test_native_declaration_and_budget_preflight(self):
        self.overlay["templates"]["by_type"]["sample"]["frontmatter"]["fields"] = {
            "status": {"enum": []}
        }
        self.save_overlay()
        self.assert_install_rejected("status", force=True)
        self.overlay["templates"]["by_type"]["sample"]["frontmatter"].pop("fields")
        self.save_overlay()
        self.core["compile"]["simplicity_budget"] = {"max_required_frontmatter_keys_per_type": 1}
        self.write_json(self.store / "SCHEMA.json", self.core)
        self.assert_install_rejected("simplicity_budget", force=True)

    def test_invalid_core_contract_preflight(self):
        self.core.pop("atlas_id")
        self.write_json(self.store / "SCHEMA.json", self.core)
        self.assert_install_rejected("atlas_id", force=True)

    def test_malformed_core_templates_rejected_before_merge_can_mask_them(self):
        for templates in ([], "invalid", {"by_type": []}, {"by_type": "invalid"}):
            with self.subTest(templates=templates):
                self.core["templates"] = templates
                self.write_json(self.store / "SCHEMA.json", self.core)
                with patch.object(schema_cmd, "merge_overlays") as merge:
                    self.assert_install_rejected("SCHEMA.templates", force=True)
                merge.assert_not_called()

    def test_no_compile_of_authored_pages_during_schema_install(self):
        self.write(self.store / "notes/broken.md", "A page needing migration without frontmatter.\n")
        self.assertEqual(self.install()[0], 0)

    def add_other_overlay(self, overlay=None, receipt=None):
        other = overlay or {
            "contribution_id": "other", "templates": {"by_type": {}},
        }
        self.write_json(self.store / "schema.d/other.json", other)
        self.write_json(self.store / "schema.d/other.receipt.json",
                        receipt if receipt is not None else {"id": "other", "written": []})

    def test_all_overlay_type_and_file_collisions_rejected(self):
        other = copy.deepcopy(self.overlay)
        other["contribution_id"] = "other"
        self.add_other_overlay(other)
        self.assert_install_rejected("both define type", force=True)
        other["templates"]["by_type"]["other-sample"] = other["templates"]["by_type"].pop("sample")
        self.add_other_overlay(other)
        self.assert_install_rejected("template path collision", force=True)

    def test_case_alias_and_parent_child_template_collisions_preflight(self):
        for path in ("templates/SAMPLE.md", "templates/sample.md/child.md"):
            with self.subTest(path=path):
                self.overlay["templates"]["by_type"]["second"] = {
                    "file": path, "frontmatter": {"required": ["type"]},
                }
                self.save_overlay()
                self.assert_install_rejected("template path collision", force=True)

    def test_later_template_conflict_does_not_partially_update_earlier_template(self):
        self.overlay["templates"]["by_type"]["second"] = {
            "frontmatter": {"required": ["type"]},
        }
        self.save_overlay()
        self.write(self.source / "templates/second.md", "second original\n")
        self.assertEqual(self.install()[0], 0)
        self.write(self.source / "templates/sample.md", "first updated\n")
        self.write(self.store / "templates/second.md", "second edited\n")
        self.assert_install_rejected("user-edited template", force=True)

    def test_other_receipt_validation_precedes_writes(self):
        for receipt in (
            {"id": "other", "written": ["../outside"]},
            {"id": "other", "written": [] , "template_hashes": []},
            {"id": "other", "written": [], "added_types": {}},
        ):
            with self.subTest(receipt=receipt):
                self.add_other_overlay(receipt=receipt)
                before = self.snapshot()
                self.assertEqual(self.install(force=True)[0], 2)
                self.assertEqual(self.snapshot(), before)

    def test_other_receipt_cannot_claim_core_template_in_candidate(self):
        self.add_other_overlay(receipt={
            "id": "other", "written": ["templates/work.md"],
            "template_hashes": {"templates/work.md": hashlib.sha256(b"core\n").hexdigest()},
        })
        self.assert_install_rejected("ownership collision", force=True)

    def test_corrupt_or_invalid_old_receipt_never_discarded_with_force(self):
        self.assertEqual(self.install()[0], 0)
        receipt = self.receipt()
        self.write(self.receipt_path, "{bad json")
        self.assert_install_rejected("receipt unreadable", force=True)
        for key, value in (
            ("template_hashes", {"templates/sample.md": "not-a-sha"}),
            ("template_hashes", None),
            ("written", "templates/sample.md"),
            ("added_types", [None]),
            ("id", "wrong"),
        ):
            with self.subTest(key=key):
                invalid = copy.deepcopy(receipt)
                invalid[key] = value
                self.write_json(self.receipt_path, invalid)
                self.assert_install_rejected("receipt", force=True)

    def test_template_path_containment_and_core_file_protection(self):
        for path in (
            "../outside.md", "/outside.md", "SCHEMA.json", "schema.d/example.json",
            "templates/../README.md", "templates/work.md", "templates/./sample.md",
            "templates\\sample.md",
        ):
            with self.subTest(path=path):
                self.overlay["templates"]["by_type"]["sample"]["file"] = path
                self.save_overlay()
                before = self.snapshot()
                code, payload = self.install(force=True)
                self.assertEqual(code, 2, payload)
                self.assertEqual(self.snapshot(), before)

    def test_nested_declared_path_and_package_parent_layout(self):
        path = "templates/nested/sample.md"
        self.overlay["templates"]["by_type"]["sample"]["file"] = path
        self.save_overlay()
        self.write(self.source / path, "nested\n")
        self.assertEqual(self.install()[0], 0)
        self.assertEqual((self.store / path).read_text(), "nested\n")
        self.assertIn(path, self.receipt()["template_hashes"])
        self.assertEqual(self.uninstall()[0], 0)
        shutil.rmtree(self.source / "templates")
        self.write(self.source.parent / path, "parent package\n")
        self.assertEqual(self.install()[0], 0)
        self.assertEqual((self.store / path).read_text(), "parent package\n")

    def test_source_and_destination_symlinks_rejected(self):
        outside = self.work / "outside.md"
        self.write(outside, "outside\n")
        source_template = self.source / "templates/sample.md"
        source_template.unlink()
        source_template.symlink_to(outside)
        self.assert_install_rejected("symlink", force=True)
        source_template.unlink()
        self.write(source_template, "original template\n")
        self.target.parent.mkdir()
        self.target.symlink_to(outside)
        self.assert_install_rejected("symlink", force=True)
        self.target.unlink()
        self.target.parent.rmdir()
        (self.store / "templates").symlink_to(self.source / "templates", target_is_directory=True)
        self.assert_install_rejected("symlink", force=True)
        self.assertEqual(outside.read_text(), "outside\n")

    def test_dangling_template_directory_symlink_does_not_trigger_parent_fallback(self):
        shutil.rmtree(self.source / "templates")
        (self.source / "templates").symlink_to(self.work / "does-not-exist", target_is_directory=True)
        self.write(self.source.parent / "templates/sample.md", "fallback is not allowed\n")
        self.assert_install_rejected("symlink", force=True)

    def test_metadata_symlink_and_directory_collision_rejected(self):
        (self.store / "schema.d").mkdir()
        target = self.store / "schema.d/example.json"
        target.symlink_to(self.source / "SCHEMA.overlay.json")
        self.assert_install_rejected("symlink", force=True)
        target.unlink()
        target.mkdir()
        self.assert_install_rejected("not a regular file", force=True)

    def test_receipt_cannot_own_core_or_another_contribution_template(self):
        self.assertEqual(self.install()[0], 0)
        core_path = "templates/work.md"
        self.write(self.store / core_path, "core template\n")
        receipt = self.receipt()
        receipt["written"].append(core_path)
        receipt["template_hashes"][core_path] = hashlib.sha256(b"core template\n").hexdigest()
        self.write_json(self.receipt_path, receipt)
        self.assert_install_rejected("receipt cannot own template", force=True)
        self.assertEqual(self.uninstall()[0], 0)
        self.assertEqual((self.store / core_path).read_text(), "core template\n")

    def test_retired_template_ownership_retained_across_repeated_installs(self):
        self.assertEqual(self.install()[0], 0)
        self.overlay["templates"]["by_type"] = {}
        self.save_overlay()
        self.assertEqual(self.install(force=True)[0], 0)
        self.assertEqual(self.install()[0], 0)
        self.assertIn("templates/sample.md", self.receipt()["template_hashes"])
        self.assertIn("sample", self.receipt()["added_types"])
        self.assertEqual(self.uninstall()[0], 0)
        self.assertFalse(self.target.exists())

    def test_uninstall_preserves_edited_template_and_authored_receipt_paths(self):
        self.assertEqual(self.install()[0], 0)
        self.write(self.target, "user edited\n")
        self.write(self.store / "schema.d/unrelated.json", "{}\n")
        self.write(self.store / "schema.d/unrelated.receipt.json", "{}\n")
        receipt = self.receipt()
        receipt["written"].append("schema.d/unrelated.json")
        self.write_json(self.receipt_path, receipt)
        code, payload = self.uninstall()
        self.assertEqual(code, 0, payload)
        self.assertEqual(self.target.read_text(), "user edited\n")
        self.assertTrue((self.store / "schema.d/unrelated.json").exists())
        self.assertTrue(any("user-edited" in note for note in payload["notes"]))

    def test_uninstall_preserves_symlink_in_place_of_owned_template(self):
        self.assertEqual(self.install()[0], 0)
        self.target.unlink()
        self.target.symlink_to(self.source / "templates/sample.md")
        code, payload = self.uninstall()
        self.assertEqual(code, 0, payload)
        self.assertTrue(self.target.is_symlink())
        self.assertTrue(any("unsafe template" in note for note in payload["notes"]))

    def test_new_install_rollback_after_os_failure_removes_new_directories(self):
        before = self.snapshot()
        original = schema_cmd.os.replace
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected replacement failure")
            return original(source, destination)

        with patch.object(schema_cmd.os, "replace", side_effect=fail_second):
            code, payload = self.install()
        self.assertEqual(code, 2, payload)
        self.assertIn("rolled back", payload["error"])
        self.assertEqual(self.snapshot(), before)

    def test_upgrade_rollback_restores_bytes_receipt_and_mode(self):
        self.assertEqual(self.install()[0], 0)
        self.target.chmod(0o640)
        before = self.snapshot()
        self.write(self.source / "templates/sample.md", "new version\n")
        original = schema_cmd.os.replace
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected receipt failure")
            return original(source, destination)

        with patch.object(schema_cmd.os, "replace", side_effect=fail_second):
            code, payload = self.install()
        self.assertEqual(code, 2, payload)
        self.assertEqual(self.snapshot(), before)

    def test_uninstall_os_failure_rolls_back_deleted_templates(self):
        self.assertEqual(self.install()[0], 0)
        before = self.snapshot()
        original = Path.unlink

        def fail_overlay(path, *args, **kwargs):
            if path == self.store / "schema.d/example.json":
                raise OSError("injected uninstall failure")
            return original(path, *args, **kwargs)

        with patch.object(Path, "unlink", fail_overlay):
            code, payload = self.uninstall()
        self.assertEqual(code, 2, payload)
        self.assertEqual(self.snapshot(), before)

    def test_rollback_failure_is_reported_explicitly(self):
        self.assertEqual(self.install()[0], 0)
        self.write(self.source / "templates/sample.md", "new version\n")
        original = schema_cmd.os.replace
        calls = 0

        def fail_after_first(source, destination):
            nonlocal calls
            calls += 1
            if calls >= 2:
                raise OSError("persistent OS failure")
            return original(source, destination)

        with patch.object(schema_cmd.os, "replace", side_effect=fail_after_first):
            code, payload = self.install()
        self.assertEqual(code, 2, payload)
        self.assertIn("rollback incomplete", payload["error"])
        self.assertFalse(list(self.store.rglob("*.atlas-write")))

    def test_candidate_merge_is_pure_and_receipt_validation_accepts_legacy(self):
        core = copy.deepcopy(self.core)
        effective, critical, _ = merge_overlays(
            core, self.store, candidate_overlays={"example": self.overlay}
        )
        self.assertFalse(critical, critical)
        self.assertIn("sample", effective["templates"]["by_type"])
        self.assertEqual(core, self.core)
        self.assertFalse((self.store / "schema.d").exists())
        self.assertEqual(receipt_issues(
            self.store, candidate_overlays={"example": self.overlay},
            candidate_receipts={"example": {"id": "example", "written": ["templates/sample.md"]}},
        ), [])


if __name__ == "__main__":
    unittest.main()
