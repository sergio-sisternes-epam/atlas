import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATHS = ROOT / "references" / "paths"


class OperatorSkillsTests(unittest.TestCase):
    def test_operator_path_content(self) -> None:
        memorise = (PATHS / "atlas-memorise.md").read_text()
        recall = (PATHS / "atlas-recall.md").read_text()
        forget = (PATHS / "atlas-forget.md").read_text()
        optimise = (PATHS / "atlas-optimise.md").read_text()

        self.assertIn("Not a separate package", memorise)
        self.assertIn("references/paths/remember.md", memorise)
        self.assertIn("Not a memory layer", memorise)

        self.assertIn("references/paths/recall.md", recall)
        self.assertIn("Not a memory layer", recall)
        self.assertNotIn("index → schema → gist → memory", recall)

        for action in ("keep", "vary", "abandon", "kva: terminated"):
            self.assertIn(action, forget)
        self.assertIn("Do not delete the file", forget)

        self.assertIn("Not on install", optimise)
        self.assertIn("Not on compile", optimise)
        self.assertIn("Do not invent gist text", optimise)
        for phrase in (
            "names a target",
            "A missing target",
            "Plan (dry-run, always first)",
            "migration task list per top-level folder",
            "Do not stop early",
            "dead-index-cue",
            "stale-gist-description",
            "Subject clustering",
            "stale plan",
            "scripts/atlas_optimise.py",
            "Do not run memory-migrate from here",
        ):
            self.assertIn(phrase, optimise)

        for content in (memorise, recall, forget, optimise):
            self.assertIn("Not a memory layer", content)

    def test_package_identity_and_cli_surface(self) -> None:
        apm = (ROOT / "apm.yml").read_text()
        self.assertIn("name: atlas\n", apm)
        self.assertFalse((ROOT / "packages").exists())

        cli = (ROOT / "scripts" / "atlas_cli" / "cli.py").read_text()
        for command in (
            "atlas-optimise",
            "atlas-forget",
            "atlas-memorise",
            "atlas-recall",
        ):
            self.assertNotIn(f'command("{command}")', cli)
            self.assertNotIn(f'command("{command}",', cli)


if __name__ == "__main__":
    unittest.main()
