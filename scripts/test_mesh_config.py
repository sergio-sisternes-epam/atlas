#!/usr/bin/env python3
"""Mesh config keys (M14): top-level ``recall.scope``/``recall.rrf_k``, a
top-level ``graph`` block and row-level ``mesh_member`` are accepted and
validated; existing writers keep them. Also the ``_mesh`` index location (M5).

Linux-safe: no network.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, meshfile  # noqa: E402
from test_engine_preference import cli  # noqa: E402
from test_recall_bm25 import make_store  # noqa: E402

A = "github.com/acme/alpha"
B = "github.com/acme/beta"


def base_doc() -> dict:
    return {
        "version": 1,
        "recall": {"engine": "grep", "scope": "mesh", "rrf_k": 60},
        "graph": {"scope": "mesh", "driver": "nanograph"},
        "stores": [
            {"id": A, "path": "atlas/alpha", "mesh_member": True},
            {"id": B, "path": "atlas/beta", "mesh_member": False},
        ],
    }


def errors(doc: dict) -> list[str]:
    return meshfile.validate_doc(doc)


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    # --- validation ------------------------------------------------------------------
    check("new-keys-accepted", errors(base_doc()) == [], str(errors(base_doc())))
    for scope in ("store", "mesh"):
        doc = base_doc()
        doc["recall"] = {"scope": scope}
        doc["graph"] = {"scope": scope, "driver": "native"}
        check(f"scope-{scope}-accepted", errors(doc) == [], str(errors(doc)))
    for k in (1, 1000):
        doc = base_doc()
        doc["recall"]["rrf_k"] = k
        check(f"rrf_k-{k}-accepted", errors(doc) == [], str(errors(doc)))
    for bad in (0, 1001, True, False, 1.5, 60.0, "60", None, -1):
        doc = base_doc()
        doc["recall"]["rrf_k"] = bad
        errs = errors(doc)
        check(f"rrf_k-{bad!r}-rejected", any("rrf_k" in e for e in errs), str(errs))
    for key, bad in (("scope", "global"), ("scope", 1), ("driver", "fts5"), ("driver", "graph"), ("colour", "red")):
        doc = base_doc()
        doc["graph"][key] = bad
        errs = errors(doc)
        check(f"graph-{key}-{bad!r}-rejected", any("graph" in e for e in errs), str(errs))
    doc = base_doc()
    doc["graph"] = "mesh"
    check("graph-non-object-rejected", any("graph" in e for e in errors(doc)), str(errors(doc)))
    doc = base_doc()
    doc["recall"]["scope"] = "everything"
    check("recall-scope-invalid-rejected", any("recall.scope" in e for e in errors(doc)), str(errors(doc)))
    for bad in ("false", 0, None):
        doc = base_doc()
        doc["stores"][1]["mesh_member"] = bad
        errs = errors(doc)
        check(f"mesh_member-{bad!r}-rejected", any("mesh_member" in e and B in e for e in errs), str(errs))
    for key, value in (("scope", "mesh"), ("rrf_k", 60)):
        doc = base_doc()
        doc["stores"][0]["recall"] = {"engine": "bm25", key: value}
        errs = errors(doc)
        check(
            f"row-recall-{key}-rejected-naming-row",
            len(errs) >= 1 and any(A in e and f"recall.{key}" in e for e in errs),
            str(errs),
        )
    check("mesh-member-default", meshfile.is_mesh_member({"id": A}) is True)
    check("mesh-member-false", meshfile.is_mesh_member({"id": A, "mesh_member": False}) is False)

    schema = json.loads((ROOT / "scripts" / "atlas_cli" / "schemas" / "atlas-mesh.schema.json").read_text())
    row_props = schema["$defs"]["store"]["properties"] if "$defs" in schema and "store" in schema["$defs"] else {}
    check("schema-has-graph", "graph" in schema.get("properties", {}))
    check("schema-row-mesh-member", row_props.get("mesh_member", {}).get("type") == "boolean", str(row_props.get("mesh_member")))

    # --- writers keep the keys ---------------------------------------------------------
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-config-"))
    try:
        project = tmp / "proj"
        make_store(project / "atlas" / "alpha", "1.0")
        make_store(project / "atlas" / "beta", "1.0")
        for indent, label in ((4, "indent4"), ("\t", "tab"), (2, "indent2")):
            doc = base_doc()
            mesh = project / "atlas-mesh.json"
            mesh.write_text(json.dumps(doc, indent=indent) + "\n", encoding="utf-8")
            code, p, out = cli("index", "set", "bm25", "--store", A, "--root", str(project), "--json")
            text = mesh.read_text(encoding="utf-8")
            expected = base_doc()
            expected["stores"][0] = {"id": A, "path": "atlas/alpha", "mesh_member": True, "recall": {"engine": "bm25"}}
            check(
                f"index-set-row-keeps-keys-{label}",
                code == 0 and text == json.dumps(expected, indent=indent) + "\n",
                out[:300] + "\n" + text,
            )
            code, p, out = cli("index", "set", "bm25", "--default", "--root", str(project), "--json")
            text = mesh.read_text(encoding="utf-8")
            expected["recall"]["engine"] = "bm25"
            check(
                f"index-set-default-keeps-keys-{label}",
                code == 0 and text == json.dumps(expected, indent=indent) + "\n",
                out[:300] + "\n" + text,
            )
            code, p, out = cli("index", "unset", "--store", A, "--root", str(project), "--json")
            text = mesh.read_text(encoding="utf-8")
            del expected["stores"][0]["recall"]
            check(
                f"index-unset-keeps-keys-{label}",
                code == 0 and text == json.dumps(expected, indent=indent) + "\n",
                out[:300] + "\n" + text,
            )
            code, p, out = cli("index", "unset", "--default", "--root", str(project), "--json")
            text = mesh.read_text(encoding="utf-8")
            expected["recall"] = {"scope": "mesh", "rrf_k": 60}
            check(
                f"index-unset-default-keeps-scope-{label}",
                code == 0 and text == json.dumps(expected, indent=indent) + "\n",
                out[:300] + "\n" + text,
            )

        mesh = project / "atlas-mesh.json"
        mesh.write_text(json.dumps(base_doc(), indent=2) + "\n", encoding="utf-8")
        meshfile.upsert(project, {"id": B, "path": "atlas/beta", "url": "", "ref": ""})
        rows = {r["id"]: r for r in json.loads(mesh.read_text())["stores"]}
        check("upsert-keeps-mesh-member", rows[B].get("mesh_member") is False, str(rows[B]))
        after = json.loads(mesh.read_text())
        check("upsert-keeps-top-level", after["recall"] == base_doc()["recall"] and after["graph"] == base_doc()["graph"])

        # The keys are inert: index show still works and reports the per-store engine.
        code, p, out = cli("index", "show", "--root", str(project / "atlas" / "alpha"), "--json")
        check("index-show-with-new-keys", code == 0, out[:300])

        bad = base_doc()
        bad["stores"][0]["recall"] = {"scope": "mesh"}
        mesh.write_text(json.dumps(bad, indent=2) + "\n", encoding="utf-8")
        code, _p, out = cli("index", "set", "bm25", "--store", A, "--root", str(project), "--json")
        check("index-set-refuses-row-scope", code != 0 and A in out and "recall.scope" in out, out[:300])

        # --- _mesh index location ------------------------------------------------------
        for kind in ("graph", "nanograph"):
            got = index_location.mesh_index_dir(project, kind)
            want = project.resolve() / ".atlas" / "indexes" / kind / "_mesh"
            check(f"mesh-index-dir-{kind}", got == want, str(got))
        for kind in ("bm25", "fts5", "native", "../x", "_mesh"):
            try:
                index_location.mesh_index_dir(project, kind)
                raised = False
            except ValueError:
                raised = True
            check(f"mesh-index-dir-rejects-{kind}", raised)
        check("graph-not-per-store-driver-type", "graph" not in index_location.DRIVER_TYPES)
        check("mesh-driver-types", index_location.MESH_DRIVER_TYPES == {"graph", "nanograph"})

        linked = tmp / "linked"
        (linked / ".atlas").mkdir(parents=True)
        (linked / "elsewhere").mkdir()
        (linked / ".atlas" / "indexes").symlink_to(linked / "elsewhere", target_is_directory=True)
        try:
            index_location.mesh_index_dir(linked, "graph")
            raised = False
        except index_location.IndexLocationError:
            raised = True
        check("mesh-index-dir-rejects-symlinked-base", raised)

        escape = tmp / "escape"
        (escape / ".atlas" / "indexes" / "graph").mkdir(parents=True)
        (escape / "out").mkdir()
        os.symlink(escape / "out", escape / ".atlas" / "indexes" / "graph" / "_mesh", target_is_directory=True)
        try:
            index_location.mesh_index_dir(escape, "graph")
            raised = False
        except index_location.IndexLocationError:
            raised = True
        check("mesh-index-dir-rejects-symlinked-mesh", raised)

        # --- id collision: no valid atlas id maps to _mesh ---------------------------
        for sid in ("_mesh", "github.com/_mesh", "_mesh/x/y", "github.com/acme/_mesh"):
            try:
                index_location.safe_id_path(sid)
                raised = False
            except (ValueError, index_location.IndexLocationError):
                raised = True
            check(f"id-collision-rejects-{sid}", raised)
        mesh.write_text(json.dumps(base_doc(), indent=2) + "\n", encoding="utf-8")
        index_location.clear_cache()
        for kind in sorted(index_location.DRIVER_TYPES):
            path = index_location.index_dir(project / "atlas" / "alpha", kind)
            check(f"id-collision-store-dir-{kind}", "_mesh" not in path.parts, str(path))
        check(
            "id-collision-segment-rule",
            all(not index_location._SEGMENT.match(s) for s in ("_mesh", "_", "_x")),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} mesh config check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll mesh config checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
