#!/usr/bin/env python3
"""Duplicate store ids in atlas-mesh.json are a validation error naming both
rows; index resolution, `atlas index` and recall refuse such a mesh instead of
sharing one index directory between two stores.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, meshfile  # noqa: E402
from test_recall_bm25 import make_store  # noqa: E402

CLEAN_ENV = ("ATLAS_RECALL_ENGINE", "ATLAS_INDEX_ROOT", "ATLAS_TEST_PLATFORM", "ATLAS_NANOGRAPH_BIN")


def cli(*args: str) -> tuple[int, dict, str]:
    env = {k: v for k, v in os.environ.items() if k not in CLEAN_ENV}
    proc = subprocess.run([sys.executable, str(ATLAS), *args], cwd=ROOT, text=True, capture_output=True, env=env)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {}
    return proc.returncode, data, proc.stdout + proc.stderr


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-dup-"))
    try:
        # --- validate_doc ---------------------------------------------------------
        doc = {
            "version": 1,
            "stores": [
                {"id": "github.com/o/r", "path": "stores/a"},
                {"id": "github.com/x/y", "path": "stores/c"},
                {"id": "github.com/O/R", "path": "stores/b"},
            ],
        }
        errs = meshfile.validate_doc(doc)
        dup = [e for e in errs if e.startswith("duplicate store id")]
        check(
            "validate-case-duplicate",
            dup == ["duplicate store id github.com/O/R: stores[0] (path stores/a) and stores[2] (path stores/b)"],
            str(errs),
        )
        url_doc = {
            "version": 1,
            "stores": [{"id": "github.com/o/r", "path": "stores/a"}, {"id": "https://github.com/o/r.git", "path": "stores/b"}],
        }
        errs = meshfile.validate_doc(url_doc)
        check(
            "validate-url-duplicate",
            any("duplicate store id github.com/o/r: stores[0] (path stores/a) and stores[1] (path stores/b)" == e for e in errs),
            str(errs),
        )
        unique = {"version": 1, "stores": [{"id": "github.com/o/r", "path": "stores/a"}, {"id": "github.com/o/s", "path": "stores/b"}]}
        check("validate-unique-ok", meshfile.validate_doc(unique) == [], str(meshfile.validate_doc(unique)))

        # --- a project whose mesh has two rows with one canonical id --------------
        project = tmp / "project"
        project.mkdir()
        store_a = make_store(project / "stores" / "a", "1.0")
        store_b = make_store(project / "stores" / "b", "1.0")
        mesh = project / meshfile.MESH_NAME
        mesh.write_text(
            json.dumps(
                {
                    "version": 1,
                    "stores": [{"id": "github.com/o/r", "path": "stores/a"}, {"id": "github.com/O/R", "path": "stores/b"}],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        try:
            meshfile.load(project)
            check("load-refuses", False)
        except meshfile.MeshFileError as e:
            check("load-refuses", "duplicate store id" in str(e) and "stores[0]" in str(e) and "stores[1]" in str(e), str(e))

        # upsert replaces by id and cannot add a case-variant duplicate.
        good = tmp / "good"
        good.mkdir()
        (good / meshfile.MESH_NAME).write_text(json.dumps(unique) + "\n", encoding="utf-8")
        meshfile.upsert(good, {"id": "github.com/o/r", "path": "stores/z"})
        rows = meshfile.load(good)["stores"]
        check("upsert-replaces", [r["id"] for r in rows].count("github.com/o/r") == 1 and len(rows) == 2, str(rows))
        try:
            meshfile.upsert(good, {"id": "github.com/O/R", "path": "stores/y"})
            check("upsert-no-duplicate", False, json.dumps(meshfile.load(good)))
        except meshfile.MeshFileError as e:
            check("upsert-no-duplicate", "duplicate store id" in str(e), str(e))

        for name, store in (("a", store_a), ("b", store_b)):
            index_location.clear_cache()
            try:
                loc = index_location.resolve(store)
                check(f"resolve-refuses-{name}", False, str(loc))
            except index_location.IndexLocationError as e:
                check(f"resolve-refuses-{name}", "duplicate store id" in str(e), str(e))

        indexes = project / ".atlas" / "indexes"
        for args, label in (
            (("index", "status", "--root", str(project), "--json"), "project"),
            (("index", "status", "--root", str(store_a), "--json"), "store-a"),
            (("index", "status", "--root", str(store_b)), "store-b-human"),
            (("index", "build", "--root", str(store_a), "--json"), "build-a"),
        ):
            code, p, out = cli(*args)
            check(f"index-{label}-exit-2", code == 2 and "duplicate store id github.com/O/R" in out, out[:400])
        for name, store in (("a", store_a), ("b", store_b)):
            code, p, out = cli("recall", "run", "ranking", "--root", str(store), "--engine", "bm25", "--json")
            check(f"recall-{name}-refuses", code == 2 and "duplicate store id" in out, out[:400])
        check("no-shared-index-dir", not indexes.exists(), str(list(indexes.rglob("*"))[:5]) if indexes.exists() else "")
    finally:
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} mesh unique id check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll mesh unique id checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
