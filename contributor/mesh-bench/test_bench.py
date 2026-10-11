#!/usr/bin/env python3
"""Tests for the mesh retrieval benchmark kit (packet MF) on fixtures/mesh.

Checks labels against the fixture, the query inventory, metric ranges,
determinism, scratch clean-up, that nothing is written inside the fixture,
that no restricted page or excluded store reaches any arm, that the kit
stays outside the shipped skill bundle, and that the Mac harness carries the
pre-registered criteria (benchmark-goodhart). Latency is run with a small
repeat count and never asserted.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURE = ROOT / "fixtures" / "mesh"
QUERIES = HERE / "queries.json"
HARNESS = HERE / "MAC-HARNESS.md"

SPEC = importlib.util.spec_from_file_location("mesh_bench", HERE / "bench.py")
if SPEC is None or SPEC.loader is None:
    raise ImportError("Unable to load bench.py")
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)

M17 = (
    "Mesh scope is promoted beyond opt-in only if, on the multi-Atlas questions, A2 or A3 beats A1 by at "
    "least 5 points of fact accuracy at equal budget, **or** matches A1 within 1 point with at least 15 % "
    "fewer credits, **and** the single-Atlas controls do not drop by more than 2 points. A3 counts as better "
    "than A2 only if it beats A2 by at least 3 points or the graph is used in at least a third of A3 runs. "
    "Anything else is a \"keep opt-in\" result and is recorded as a lesson."
)


def snapshot(base: Path) -> dict[str, tuple[int, int, str]]:
    out = {}
    for path in sorted(base.rglob("*")):
        if path.is_file() or path.is_symlink():
            st = path.lstat()
            out[path.relative_to(base).as_posix()] = (st.st_size, st.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        else:
            out[path.relative_to(base).as_posix() + "/"] = (0, path.lstat().st_mtime_ns, "")
    return out


def mesh_rows() -> list[dict]:
    return json.loads((FIXTURE / "atlas-mesh.json").read_text(encoding="utf-8"))["stores"]


def restricted_uris() -> set[str]:
    out = set()
    for row in mesh_rows():
        root = FIXTURE / row["path"]
        if not root.is_dir():
            continue
        for page in root.rglob("*.md"):
            head = page.read_text(encoding="utf-8").split("\n---", 1)[0]
            if "\nsensitivity: restricted" in head:
                out.add(f"atlas://{row['id']}/{page.relative_to(root).as_posix()}")
    return out


def excluded_ids() -> set[str]:
    return {row["id"] for row in mesh_rows() if row.get("mesh_member") is False}


def info_exclude() -> str | None:
    if shutil.which("git") is None:
        return None
    proc = subprocess.run(["git", "rev-parse", "--git-path", "info/exclude"], cwd=ROOT, text=True, capture_output=True)
    if proc.returncode != 0:
        return None
    path = Path(proc.stdout.strip())
    path = path if path.is_absolute() else ROOT / path
    return path.read_text(encoding="utf-8") if path.exists() else ""


def without_latency(result: dict) -> dict:
    out = copy.deepcopy(result)
    out.pop("latency", None)
    return out


@unittest.skipUnless(bench.fts5_available(), "SQLite FTS5 is not available")
class BenchRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="mesh-bench-test-"))
        cls.before = snapshot(FIXTURE)
        cls.exclude_before = info_exclude()
        cls.observed: list[tuple[str, Path, bool]] = []

        def observe(event: str, path: Path) -> None:
            cls.observed.append((event, path, path.exists()))

        cls.first = bench.run(
            latency=True, repeats=1, latency_queries=2, tmp_parent=cls.tmp, observe=observe
        )
        cls.second = bench.run(tmp_parent=cls.tmp)
        cls.after = snapshot(FIXTURE)
        cls.exclude_after = info_exclude()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_labels_name_eligible_fixture_pages(self):
        self.assertEqual(self.first["label_errors"], [])

    def test_metrics_within_unit_interval(self):
        for arm, block in self.first["arms"].items():
            for subset in bench.SUBSETS:
                for key in ("recall_at_10", "mrr"):
                    value = block[subset][key]
                    self.assertIsNotNone(value, f"{arm} {subset} {key}")
                    self.assertGreaterEqual(value, 0.0)
                    self.assertLessEqual(value, 1.0)
        for row in self.first["per_query"]:
            self.assertEqual(set(row["arms"]), set(bench.ARMS))
            for arm, entry in row["arms"].items():
                self.assertTrue(0.0 <= entry["recall"] <= 1.0 and 0.0 <= entry["rr"] <= 1.0, f"{row['id']} {arm}")
                self.assertLessEqual(len(entry["hits"]), self.first["cutoff"])

    def test_deterministic_across_runs(self):
        self.assertEqual(
            json.dumps(without_latency(self.first), sort_keys=True),
            json.dumps(without_latency(self.second), sort_keys=True),
        )
        self.assertNotIn("latency", self.second)

    def test_scratch_single_index_deleted(self):
        events = {event: (path, existed) for event, path, existed in self.observed}
        built, existed = events["single_index"]
        self.assertTrue(existed, "the single index was built")
        self.assertFalse(events["single_index_removed"][1])
        self.assertFalse(built.exists())
        self.assertFalse(built.parent.exists())
        self.assertEqual(list(self.tmp.iterdir()), [], "every scratch directory is removed")

    def test_nothing_written_inside_fixture(self):
        self.assertEqual(self.before, self.after)
        self.assertFalse((FIXTURE / ".atlas").exists())
        self.assertEqual(self.exclude_before, self.exclude_after, "git info/exclude untouched")

    def test_no_restricted_page_or_excluded_store_in_any_arm(self):
        restricted = restricted_uris()
        excluded = excluded_ids()
        self.assertTrue(restricted, "the fixture has a restricted page")
        self.assertTrue(excluded, "the fixture has an excluded store")
        for result in (self.first, self.second):
            for row in result["per_query"]:
                self.assertTrue(set(row["member_match"]).isdisjoint(excluded))
                for arm, entry in row["arms"].items():
                    for uri in entry["hits"]:
                        self.assertNotIn(uri, restricted, f"{row['id']} {arm}")
                        self.assertFalse(any(uri.startswith(f"atlas://{sid}/") for sid in excluded), f"{row['id']} {arm} {uri}")
                    self.assertNotIn(entry.get("store"), excluded)
        statuses = {m["atlas_id"]: m["status"] for m in self.first["members"]}
        for sid in excluded:
            self.assertEqual(statuses[sid], "excluded")

    def test_tiered_arms_have_no_tier_inversions(self):
        for k in bench.TIERED_KS:
            self.assertEqual(self.first["arms"][f"tiered_rrf_k{k}"]["tier_inversions"], 0)
        self.assertGreater(self.first["arms"]["plain_rrf"]["tier_inversions"], 0, "fixture exercises rrf-interleave-noise")

    def test_unresolved_report_one_per_reason(self):
        self.assertEqual(
            self.first["unresolved_by_reason"],
            {r: 1 for r in ("unmounted", "excluded_member", "missing_page", "withheld", "outside_mesh", "noncanonical_atlas_uri")},
        )
        self.assertEqual(self.first["unresolved_total"], 6)

    def test_latency_shape_only(self):
        latency = self.first["latency"]
        self.assertEqual([row["members"] for row in latency["sizes"]], list(bench.LATENCY_SIZES))
        for row in latency["sizes"]:
            self.assertEqual(row["samples"], 2)
            for block in ("member_ms", "total_ms"):
                self.assertGreaterEqual(row[block]["median"], 0.0)
                self.assertGreaterEqual(row[block]["p95"], row[block]["median"])

    def test_markdown_table_lists_every_arm(self):
        text = bench.render_markdown(self.first)
        self.assertIn("| Arm | Recall@10 | MRR |", text)
        for arm in bench.ARMS:
            self.assertIn(f"| {arm} |", text)
        self.assertIn("Federated latency", text)


class QuerySetTest(unittest.TestCase):
    def setUp(self):
        self.queries = bench.load_queries(QUERIES)
        self.rows = {row["id"]: row for row in mesh_rows()}

    def test_every_label_points_to_an_existing_fixture_page(self):
        restricted = restricted_uris()
        for q in self.queries:
            for uri in q["relevant"]:
                atlas_id, path = bench.mesh_scope.parse_node_id(uri)
                row = self.rows.get(atlas_id)
                self.assertIsNotNone(row, f"{q['id']}: {atlas_id} is not a fixture row")
                self.assertIsNot(row.get("mesh_member"), False, f"{q['id']}: {uri} is in an excluded store")
                self.assertTrue((FIXTURE / row["path"] / path).is_file(), f"{q['id']}: {uri} has no page")
                self.assertNotIn(uri, restricted, f"{q['id']}: {uri} is restricted")

    def test_inventory(self):
        stores = [len(bench.label_stores(q)) for q in self.queries]
        self.assertGreaterEqual(len(self.queries), 30)
        multi = sum(1 for n in stores if n >= 2)
        self.assertGreaterEqual(multi, 30)
        self.assertGreaterEqual(multi * 2, len(self.queries))
        self.assertGreaterEqual(sum(1 for n in stores if n >= 3), 5)
        self.assertGreaterEqual(sum(1 for n in stores if n == 1), 8)
        for q, n in zip(self.queries, stores):
            self.assertEqual(q["kind"], "control" if n == 1 else "multi", q["id"])

    def test_fixture_size_and_hosts(self):
        pages = sorted(FIXTURE.rglob("*.md"))
        self.assertTrue(40 <= len(pages) <= 60, len(pages))
        for row in mesh_rows():
            self.assertTrue(row["id"].startswith("example.invalid/"), row["id"])


class BundleGuardTest(unittest.TestCase):
    """Contributor folders stay out of the shipped skill bundle, the same way for every folder."""

    def test_manifest_includes_only_skill_folders(self):
        manifest = (ROOT / "apm.yml").read_text(encoding="utf-8")
        includes = [line.strip()[2:].strip() for line in manifest.split("includes:", 1)[1].splitlines() if line.strip().startswith("- ")]
        includes = includes[: next((i for i, v in enumerate(includes) if ":" in v), len(includes))]
        self.assertTrue(includes)
        for entry in includes:
            self.assertTrue(entry.startswith(".apm/skills/"), entry)
        self.assertNotIn("contributor", manifest)
        self.assertNotIn("mesh-bench", manifest)

    def test_contributor_files_absent_from_skill_folders(self):
        bundles = [ROOT / ".apm" / "skills", ROOT / ".agents" / "skills"]
        for folder in sorted(p for p in (ROOT / "contributor").iterdir() if p.is_dir()):
            for path in folder.rglob("*"):
                if not path.is_file() or "__pycache__" in path.parts:
                    continue
                rel = path.relative_to(folder)
                for bundle in bundles:
                    self.assertFalse((bundle / folder.name / rel).exists(), f"{bundle / folder.name / rel}")
        for bundle in bundles:
            self.assertFalse((bundle / "mesh-bench").exists())

    def test_shipped_surfaces_never_reference_the_kit(self):
        shipped = [ROOT / "SKILL.md", *sorted((ROOT / "scripts" / "atlas_cli").rglob("*.py")), *sorted((ROOT / ".apm").rglob("*"))]
        for path in shipped:
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("mesh-bench", text, str(path))
                self.assertNotIn("contributor/", text, str(path))


class HarnessSpecTest(unittest.TestCase):
    """benchmark-goodhart: promotion criteria are committed before the benchmark runs."""

    def test_mac_harness_preregisters_criteria(self):
        text = HARNESS.read_text(encoding="utf-8")
        self.assertIn("### Pre-registered success criteria (M17)", text)
        section = text.split("### Pre-registered success criteria (M17)", 1)[1]
        self.assertIn(M17, section)
        self.assertIn("fixed before the benchmark runs", text)
        self.assertIn("\"keep opt-in\" result", text)
        self.assertIn("at most 6 Atlas tool calls and 60k input tokens", text)
        self.assertIn("4 arms × 40 questions × 2 seeds = 320 runs", text)
        for arm in ("A0", "A1", "A2", "A3"):
            self.assertIn(f"| {arm} |", text)
        self.assertIn("30 multi-Atlas questions", text)
        self.assertIn("10 single-Atlas control questions", text)
        self.assertIn("~/scratch/atlas-answer-bench", text)

    def test_scenario_points_at_this_check(self):
        scenario = (ROOT / "references" / "scenarios" / "mesh-index-adversarial-v1.yaml").read_text(encoding="utf-8")
        block = scenario.split("- id: benchmark-goodhart", 1)[1].split("\n  - id:", 1)[0]
        self.assertIn("packet: MF", block)
        self.assertIn("contributor/mesh-bench/MAC-HARNESS.md", block)
        self.assertIn("test_mac_harness_preregisters_criteria", block)


@unittest.skipUnless(bench.fts5_available(), "SQLite FTS5 is not available")
class CliTest(unittest.TestCase):
    def test_cli_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as td:
            md = Path(td) / "table.md"
            proc = subprocess.run(
                [sys.executable, str(HERE / "bench.py"), "--json", "-", "--markdown", str(md)],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["mesh"], "fixtures/mesh")
            self.assertIn("| tiered_rrf_k60 |", md.read_text(encoding="utf-8"))

    def test_cli_missing_mesh_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [sys.executable, str(HERE / "bench.py"), "--mesh", td], cwd=ROOT, text=True, capture_output=True
            )
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertIn("mesh-bench:", proc.stderr)


if __name__ == "__main__":
    unittest.main()
