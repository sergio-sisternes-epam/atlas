#!/usr/bin/env python3
"""Contract tests for Atlas activation-card presentation."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATHS = (
    "mount",
    "init",
    "migrate",
    "query",
    "remember",
    "work",
    "landscape",
    "schema",
    "configure",
    "ci",
)


def enter_section(path: str) -> str:
    content = (ROOT / "references" / "paths" / f"{path}.md").read_text(
        encoding="utf-8"
    )
    match = re.search(r"^## Enter[^\n]*\n(.*?)(?=^## |\Z)", content, re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError(f"{path} has no Enter section")
    return match.group(1)


class ActivationCardContractTests(unittest.TestCase):
    def test_router_requires_fenced_text_output(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(
            "Render every activation card in the assistant response as a fenced Markdown",
            skill,
        )
        self.assertIn("`text` info string", skill)
        self.assertIn("an unfenced field list is incomplete", skill)

    def test_every_path_enter_uses_one_fenced_text_card(self) -> None:
        for path in PATHS:
            with self.subTest(path=path):
                section = enter_section(path)
                blocks = re.findall(r"```text\n(.*?)\n```", section, re.DOTALL)
                self.assertEqual(1, len(blocks))

    def test_operational_cards_have_canonical_fields(self) -> None:
        for path in ("query", "remember", "work", "landscape", "schema", "configure", "ci"):
            with self.subTest(path=path):
                section = enter_section(path)
                for field in (
                    "skill: atlas",
                    "skill_path:",
                    "mode:",
                    "subject:",
                    f"path: {path}",
                    f"path_module: references/paths/{path}.md",
                    "intent:",
                    "root:",
                ):
                    self.assertIn(field, section)


if __name__ == "__main__":
    unittest.main()
