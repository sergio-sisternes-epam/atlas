#!/usr/bin/env python3
"""Commit-pinned pointer grammar, resolve guard, and compile regressions."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core.identity import MalformedPinError, ParsedPointer, normalise, parse_pointer

ATLAS = ROOT / "scripts" / "atlas.py"
SHA = "0123456789abcdef" * 2 + "01234567"
ID = "example.com/org/repo"


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args], cwd=ROOT, text=True, capture_output=True
    )


class GrammarTests(unittest.TestCase):
    def test_input_shapes(self) -> None:
        for prefix, atlas_id in (
            ("git@example.com:org/repo", ID),
            ("git@example.com:8443:org/repo", "example.com:8443/org/repo"),
            ("https://user@example.com/org/repo", ID),
            ("https://user@example.com:8443/org/repo", "example.com:8443/org/repo"),
            ("example.com/org/repo", ID),
            ("example.com:8443/org/repo", "example.com:8443/org/repo"),
            ("atlas://example.com/org/repo", ID),
            ("atlas://example.com:8443/org/repo", "example.com:8443/org/repo"),
        ):
            for suffix, commit, fragment in (
                ("", "", ""),
                ("#part@not-a-pin#more", "", "part@not-a-pin#more"),
                (f"@{SHA}", SHA, ""),
                (f"@{SHA}#part@other#more", SHA, "part@other#more"),
            ):
                with self.subTest(prefix=prefix, suffix=suffix):
                    pointer = f"{prefix}/notes/page.md{suffix}"
                    self.assertEqual(
                        parse_pointer(pointer),
                        ParsedPointer(atlas_id, "notes/page.md", fragment, commit),
                    )
                    self.assertEqual(normalise(pointer), atlas_id)

    def test_malformed_and_opaque_fragments(self) -> None:
        for pin in ("abcdef1", "A" * 40, "a" * 64, "z" * 40):
            with self.subTest(pin=pin):
                with self.assertRaises(MalformedPinError):
                    parse_pointer(f"atlas://{ID}/page@{pin}#frag")
        for suffix in (f"/@{SHA}", "/@abcdef1", f"/dir/@{SHA}"):
            with self.subTest(suffix=suffix):
                with self.assertRaises(MalformedPinError):
                    parse_pointer(f"atlas://{ID}{suffix}")
        parsed = parse_pointer(f"atlas://{ID}/page#frag@{SHA}")
        self.assertEqual(parsed.commit, "")
        self.assertEqual(parsed.fragment, f"frag@{SHA}")
        self.assertEqual(parse_pointer(f"atlas://{ID}/name@abc").in_store, "name@abc")
        self.assertEqual(ParsedPointer(ID, "page", "frag").commit, "")

    def test_id_output_is_compatible_and_echoes_pin(self) -> None:
        floating = cli("id", f"atlas://{ID}/page#frag", "--json")
        self.assertEqual(json.loads(floating.stdout), {
            "ok": True, "id": ID, "path": "page", "fragment": "frag"
        })
        pinned = cli("id", f"atlas://{ID}/page@{SHA}#a#b", "--json")
        self.assertEqual(json.loads(pinned.stdout), {
            "ok": True, "id": ID, "path": "page", "fragment": "a#b", "commit": SHA
        })


class CommandTests(unittest.TestCase):
    def test_resolve_guard_and_tip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            mount = project / "store"
            mount.mkdir()
            page = mount / "page.md"
            page.write_text("tip\n", encoding="utf-8")
            (project / "atlas-mesh.json").write_text(json.dumps({
                "version": 1, "stores": [{"id": ID, "path": "store"}]
            }), encoding="utf-8")
            pointer = f"atlas://{ID}/page.md@{SHA}#part@x"
            denied = cli("resolve", pointer, "--cwd", str(project))
            self.assertEqual(denied.returncode, 2)
            self.assertIn("pinned: use atlas link show", denied.stderr)
            denied_json = cli("resolve", pointer, "--cwd", str(project), "--json")
            self.assertEqual(denied_json.returncode, 2)
            self.assertEqual(json.loads(denied_json.stdout)["error"], "pinned: use atlas link show")
            tip = cli("resolve", pointer, "--cwd", str(project), "--tip", "--json")
            self.assertEqual(tip.returncode, 0, tip.stderr)
            self.assertEqual(json.loads(tip.stdout), {
                "ok": True, "path": str(page), "id": ID,
                "resolution": "tip", "commit": SHA, "fragment": "part@x"
            })
            tip_text = cli("resolve", pointer, "--cwd", str(project), "--tip")
            self.assertEqual(tip_text.stdout, f"tip: {page}#part@x\n")
            floating = cli("resolve", f"atlas://{ID}/page.md#part", "--cwd", str(project), "--json")
            self.assertEqual(json.loads(floating.stdout), {"ok": True, "path": str(page), "id": ID})
            floating_tip = cli("resolve", f"atlas://{ID}/page.md#part", "--cwd", str(project), "--tip", "--json")
            self.assertEqual(floating.stdout, floating_tip.stdout)

    def test_compile_finds_malformed_pins_in_frontmatter_and_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp) / "store"
            init = cli("init", "--root", str(store), "--json")
            self.assertEqual(init.returncode, 0, init.stderr)
            notes = store / "notes"
            notes.mkdir()
            (notes / "index.md").write_text("# Notes\n\n- document\n", encoding="utf-8")
            page = notes / "document.md"
            page.write_text(
                "---\ntype: document\ntitle: Test\ncreated: 2026-09-03\n"
                f"source: atlas://{ID}/front@abcdef1\n---\n\n"
                f"Floating atlas://{ID}/page#frag@{SHA}\n\n"
                f"Valid atlas://{ID}/page@{SHA}#frag\n\n"
                f"Bad atlas://{ID}/body@{'A' * 40}\n\n"
                f"Empty atlas://{ID}/@{SHA}\n",
                encoding="utf-8",
            )
            result = cli("compile", "--root", str(store), "--json", "--dry-run")
            payload = json.loads(result.stdout)
            findings = [f for f in payload["critical"] if f["id"] == "atlas_pin_malformed"]
            self.assertEqual(result.returncode, 2, payload)
            self.assertEqual(len(findings), 3, findings)
            self.assertTrue(all(f["severity"] == "critical" for f in findings))
            self.assertTrue(any("atlas_uri_unmounted" == f["id"] for f in payload["warnings"]))
            page.write_text(
                "---\ntype: document\ntitle: Test\ncreated: 2026-09-03\n---\n\n"
                f"Floating atlas://{ID}/page#frag@{SHA}\n\n"
                f"Valid atlas://{ID}/page@{SHA}#frag\n",
                encoding="utf-8",
            )
            result = cli("compile", "--root", str(store), "--json", "--dry-run")
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, payload)
            self.assertFalse(any(f["id"] == "atlas_pin_malformed" for f in payload["critical"]))
            self.assertEqual(
                [f["id"] for f in payload["warnings"]],
                ["atlas_uri_unmounted", "atlas_pin_unverifiable"],
            )


if __name__ == "__main__":
    unittest.main()
