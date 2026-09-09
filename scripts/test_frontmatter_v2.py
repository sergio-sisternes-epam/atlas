#!/usr/bin/env python3
"""SCHEMA 2.0 frontmatter parser tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_cli.core.frontmatter import FrontmatterError, split_fm, split_fm_v2


class FrontmatterV2Tests(unittest.TestCase):
    def test_yes_and_dates_stay_strings(self) -> None:
        text = "---\ntitle: yes\ncreated: 2026-09-09\non: on\n---\n\nbody\n"
        meta, body = split_fm_v2(text)
        self.assertEqual(meta["title"], "yes")
        self.assertEqual(meta["created"], "2026-09-09")
        self.assertEqual(meta["on"], "on")
        self.assertIn("body", body)

    def test_nested_relates_to(self) -> None:
        text = (
            "---\ntype: document\ntitle: t\nrelates_to:\n"
            "  - path: work/x.md\n    kind: implements\n---\n\nEnough prose here.\n"
        )
        meta, _ = split_fm_v2(text)
        self.assertEqual(meta["relates_to"][0]["path"], "work/x.md")
        self.assertEqual(meta["relates_to"][0]["kind"], "implements")

    def test_duplicate_keys_fail(self) -> None:
        text = "---\ntitle: a\ntitle: b\n---\n\nx\n"
        with self.assertRaises(FrontmatterError):
            split_fm_v2(text)

    def test_v1_parser_unchanged_for_yes(self) -> None:
        text = "---\ntitle: yes\n---\n\nbody\n"
        meta, _ = split_fm(text)
        self.assertEqual(meta["title"], "yes")


if __name__ == "__main__":
    unittest.main()
