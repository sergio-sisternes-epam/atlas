#!/usr/bin/env python3
"""SKILL.md recall/graph routing and per-verb `atlas index` synopsis."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.cli import index_group  # noqa: E402

SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
RECALL = (ROOT / "references" / "paths" / "recall.md").read_text(encoding="utf-8")

_SENTENCE = re.compile(r"[^.\n]+(?:\.(?!\w)|\n|$)")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.findall(text) if s.strip()]


class RoutingTests(unittest.TestCase):
    def test_no_every_lookup_rule_without_graph(self) -> None:
        for line in SKILL.splitlines():
            if "recall run" not in line or not re.search(r"\blookup", line, re.IGNORECASE):
                continue
            with self.subTest(line=line[:80]):
                self.assertIn("atlas graph", line)
        for sentence in sentences(SKILL):
            if re.search(r"\b(every|all|always)\b", sentence, re.IGNORECASE) and re.search(
                r"\blookups?\b", sentence, re.IGNORECASE
            ) and "atlas recall run" in sentence:
                with self.subTest(sentence=sentence[:80]):
                    self.assertIn("atlas graph", sentence)

    def test_hard_rule_and_cli_note_agree(self) -> None:
        rule = next(line for line in SKILL.splitlines() if line.startswith("1. **Formal lookup"))
        note = next(line for line in SKILL.splitlines() if line.startswith("Routing (hard rule 1)"))
        for text in (rule, note):
            with self.subTest(text=text[:40]):
                self.assertIn("`atlas recall run`", text)
                self.assertIn("atlas graph nodes|edges|neighbours", text)
        self.assertIn("references/paths/recall.md", rule)
        self.assertIn("path `recall`", note)

    def test_recall_path_routes_structural_questions_to_graph(self) -> None:
        self.assertIn("atlas graph nodes|edges|neighbours", RECALL)
        self.assertIn("references/graph.md", RECALL)
        self.assertNotIn("The process is always `atlas recall run`", RECALL)


class IndexSynopsisTests(unittest.TestCase):
    COMMON = {"--root", "--json"}

    def test_one_line_per_subcommand_matching_click(self) -> None:
        self.assertNotIn("index set|unset", SKILL)
        lines = {
            m.group(1): m.group(2)
            for m in re.finditer(r"^python3 \S+/atlas\.py index (\w+)(.*)$", SKILL, re.MULTILINE)
        }
        self.assertEqual(sorted(lines), sorted(index_group.commands))
        self.assertIn("[--root <dir>] [--json]", SKILL)
        for name, command in index_group.commands.items():
            with self.subTest(verb=name):
                want = {
                    opt
                    for param in command.params
                    for opt in getattr(param, "opts", [])
                    if opt.startswith("--")
                } - self.COMMON
                got = set(re.findall(r"--[a-z-]+", lines[name]))
                self.assertEqual(want, got)
                has_arg = any(p.param_type_name == "argument" for p in command.params)
                self.assertEqual(has_arg, "<grep|bm25|nanograph>" in lines[name])


if __name__ == "__main__":
    unittest.main()
