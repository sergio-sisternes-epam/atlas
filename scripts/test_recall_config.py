#!/usr/bin/env python3
"""Recall contract and capability tests."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_cli.commands.recall import run_validate
from atlas_cli.core.jsonutil import StrictJsonError, loads_strict
from atlas_cli.core.recall_config import (
    default_recall_block,
    list_profiles,
    resolve_profile,
    validate_against,
    validate_store_v2,
)
from atlas_cli.core.drivers import tgrep as tgrep_driver


class RecallConfigTests(unittest.TestCase):
    def test_duplicate_json_keys(self) -> None:
        with self.assertRaises(StrictJsonError):
            loads_strict('{"a": 1, "a": 2}')

    def test_validate_config_rejects_duplicate_keys(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="atlas-val-"))
        cfg = tmp / "recall.json"
        cfg.write_text('{"version": 1, "version": 1, "enabled": false}', encoding="utf-8")
        self.assertEqual(run_validate(str(tmp), str(cfg), as_json=True), 2)

    def test_unknown_recall_key(self) -> None:
        errs = validate_against(
            "recall-v1.schema.json",
            {"version": 1, "enabled": False, "mystery": True},
        )
        self.assertTrue(errs)

    def test_ceilings_clamp(self) -> None:
        resolved = resolve_profile(
            {
                "recall": {
                    "version": 1,
                    "enabled": True,
                    "preset": "atlas:scan",
                    "overrides": {"limits": {"max_hits": 9999}},
                    "ceilings": {"max_hits": 100},
                }
            }
        )
        self.assertEqual(resolved["effective"]["limits"]["max_hits"], 100)
        self.assertTrue(resolved["notes"])

    def test_install_is_not_activation(self) -> None:
        profiles = list_profiles({"presets": {"demo:explore": {"coarse": {"driver": "scan"}}}})
        self.assertIn("demo:explore", profiles)
        resolved = resolve_profile({"recall": default_recall_block(), "presets": profiles})
        self.assertNotEqual(resolved["preset"], "demo:explore")
        self.assertEqual(resolved["preset"], "atlas:ranked")
        self.assertIn("default:atlas:ranked", resolved["provenance"])

    def test_tgrep_preset_resolves(self) -> None:
        resolved = resolve_profile({"recall": {"version": 1, "enabled": True, "preset": "atlas:tgrep"}})
        self.assertEqual(resolved["preset"], "atlas:tgrep")
        self.assertEqual(resolved["effective"]["coarse"]["driver"], "tgrep")

    def test_tgrep_missing_binary(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="atlas-tgrep-"))
        page = SimpleNamespace(path="decisions/alpha.md", role="page")
        with self.assertRaises(tgrep_driver.TgrepError) as ctx:
            tgrep_driver.search(tmp, [page], "ranking", 20, "digest", finder=lambda: None)
        self.assertEqual(str(ctx.exception), tgrep_driver.MISSING)

    def test_tgrep_never_serve(self) -> None:
        with self.assertRaises(tgrep_driver.TgrepError) as ctx:
            tgrep_driver.run_argv(Path("/bin/echo"), ["serve", "."], cwd=Path("."), timeout=1)
        self.assertEqual(str(ctx.exception), tgrep_driver.SERVE_FORBIDDEN)
        with self.assertRaises(tgrep_driver.TgrepError) as ctx2:
            tgrep_driver.run_argv(Path("/bin/echo"), ["--no-index", "q"], cwd=Path("."), timeout=1)
        self.assertEqual(str(ctx2.exception), tgrep_driver.NO_INDEX_FORBIDDEN)
        guarded = tgrep_driver._guard_args(
            ["search", "-e", "serve", "/tmp/workspace/serve"]
        )
        self.assertEqual(guarded[0], "search")
        self.assertIn("serve", guarded)

    def test_tgrep_digest_index_and_filter(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="atlas-tgrep-"))
        store = tmp / "store"
        store.mkdir()
        page = SimpleNamespace(path="decisions/alpha.md", role="page")
        calls: list[list[str]] = []

        def runner(binary, args, *, cwd, timeout):
            calls.append(list(args))
            if args and args[0] == "index":
                dest = Path(args[args.index("--index-path") + 1])
                dest.mkdir(parents=True, exist_ok=True)
                return subprocess.CompletedProcess(args, 0, "", "")
            match = {
                "type": "match",
                "data": {
                    "path": {"text": "decisions/alpha.md"},
                    "lines": {"text": "Ranking contract"},
                },
            }
            staging = {
                "type": "match",
                "data": {"path": {"text": "staging/secret.md"}, "lines": {"text": "nope"}},
            }
            return subprocess.CompletedProcess(
                args, 0, json.dumps(match) + "\n" + json.dumps(staging) + "\n", ""
            )

        hits, meta = tgrep_driver.search(
            store,
            [page],
            "ranking",
            20,
            "digest-1",
            binary=Path("/bin/echo"),
            runner=runner,
        )
        self.assertEqual([h["path"] for h in hits], ["decisions/alpha.md"])
        self.assertTrue(meta["rebuilt"])
        self.assertTrue(any(c and c[0] == "index" for c in calls))
        calls.clear()
        hits2, meta2 = tgrep_driver.search(
            store,
            [page],
            "ranking",
            20,
            "digest-1",
            binary=Path("/bin/echo"),
            runner=runner,
        )
        self.assertEqual([h["path"] for h in hits2], ["decisions/alpha.md"])
        self.assertFalse(meta2["rebuilt"])
        self.assertFalse(any(c and c[0] == "index" for c in calls))
        self.assertTrue(any(c and c[0] == "search" for c in calls))
        self.assertTrue(any("-i" in c and "-F" not in c for c in calls))

    def test_tgrep_serve_json_detected(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="atlas-tgrep-"))
        store = tmp / "store"
        (store / ".tgrep").mkdir(parents=True)
        (store / ".tgrep" / "serve.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(tgrep_driver.TgrepError) as ctx:
            tgrep_driver.ensure_index(store, "digest", binary=Path("/bin/echo"))
        self.assertEqual(str(ctx.exception), tgrep_driver.SERVE_DETECTED)

    def test_store_v2_disabled_tgrep_preset_ok(self) -> None:
        data = {
            "schema_version": "2.0",
            "atlas_id": "x",
            "structure": {},
            "compile": {},
            "recall": {"version": 1, "enabled": False, "preset": "atlas:scan"},
        }
        self.assertFalse(validate_store_v2(data))

    def test_pointer_db_rejects_escape(self) -> None:
        from atlas_cli.core import recall_index

        tmp = Path(tempfile.mkdtemp(prefix="atlas-ptr-"))
        store = tmp / "store"
        (store / ".atlas-index" / "recall").mkdir(parents=True)
        evil = tmp / "evil.sqlite"
        evil.write_bytes(b"not-a-db")
        pointer = {
            "complete": True,
            "corpus_digest": "digest-x",
            "cheap_fingerprint": "fp",
            "db": str(evil),
        }
        (store / ".atlas-index" / "recall" / "current.json").write_text(
            json.dumps(pointer), encoding="utf-8"
        )
        self.assertIsNone(recall_index.matching_generation(store, "digest-x"))
        pointer["db"] = "../evil.sqlite"
        (store / ".atlas-index" / "recall" / "current.json").write_text(
            json.dumps(pointer), encoding="utf-8"
        )
        self.assertIsNone(recall_index.matching_generation(store, "digest-x"))
        outside = tmp / "outside-index"
        (outside / "recall").mkdir(parents=True)
        (outside / "recall" / "evil.sqlite").write_bytes(b"not-a-db")
        (store / ".atlas-index").rename(store / ".atlas-index.bak")
        (store / ".atlas-index").symlink_to(outside)
        pointer["db"] = ".atlas-index/recall/evil.sqlite"
        (outside / "recall" / "current.json").write_text(
            json.dumps(pointer), encoding="utf-8"
        )
        self.assertIsNone(recall_index.matching_generation(store, "digest-x"))

    def test_publish_rejects_symlinked_index_root(self) -> None:
        from atlas_cli.core import recall_index

        tmp = Path(tempfile.mkdtemp(prefix="atlas-idx-"))
        store = tmp / "store"
        store.mkdir()
        outside = tmp / "outside-index"
        outside.mkdir()
        (store / ".atlas-index").symlink_to(outside)
        schema = {
            "schema_version": "2.0",
            "recall": {"version": 1, "enabled": True, "preset": "atlas:scan"},
        }
        with self.assertRaises(recall_index.IndexError_):
            recall_index.publish_generation(
                store,
                schema,
                focused=False,
                projection={"complete": True, "corpus_digest": "x", "pages": []},
            )

    def test_grep_search_skips_frontmatter_error(self) -> None:
        from atlas_cli.commands.search import _grep_search

        tmp = Path(tempfile.mkdtemp(prefix="atlas-grep-"))
        store = tmp / "store"
        (store / "decisions").mkdir(parents=True)
        (store / "decisions" / "bad.md").write_text(
            "---\ntitle: a\ntitle: b\n---\n\nRanking duplicate\n", encoding="utf-8"
        )
        (store / "decisions" / "ok.md").write_text(
            "---\ntype: decision\ntitle: Ranking contract\n---\n\nRanking contract body.\n",
            encoding="utf-8",
        )
        hits, _ = _grep_search(store, "Ranking", "staging", 10, False, "2.0")
        paths = [h.get("path") for h in hits]
        self.assertTrue(any("ok.md" in (p or "") for p in paths), paths)
        self.assertFalse(any("bad.md" in (p or "") for p in paths), paths)


if __name__ == "__main__":
    unittest.main()
