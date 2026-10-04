#!/usr/bin/env python3
"""0.13.0-beta.3 schema layer contract regressions. Run: python3 scripts/test_schema_layer_contract.py

Covers: one-contract-file, pre-beta-eligible, in-beta-refused,
one-schema-per-gist-folder, read-shipped-beta, stamp-shape-disagree.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))
from atlas_cli.core.frontmatter import read_page

PROSE = (
    "This page carries enough non-link prose content to pass the "
    "not_just_links body length check used across the test fixtures."
)


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def run_json(args: list[str]) -> tuple[int, dict]:
    result = run(args)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"invalid JSON for {args}: {error}; stdout={result.stdout!r} stderr={result.stderr!r}"
        ) from error
    return result.returncode, payload


def findings_by_id(payload: dict, bucket: str) -> list[str]:
    return [i.get("id") for i in payload.get(bucket, [])]


def write_page(path: Path, type_name: str, relates_to=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rel_lines = ""
    if relates_to:
        rel_lines = "relates_to:\n" + "".join(
            f"  - path: {item['path']}\n    kind: {item['kind']}\n" for item in relates_to
        )
    path.write_text(
        "---\n"
        f"type: {type_name}\n"
        "title: t\n"
        "created: 2026-10-04\n"
        f"{rel_lines}"
        "---\n\n"
        "## Content\n\n"
        f"{PROSE}\n",
        encoding="utf-8",
    )


def write_index(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.md").write_text("# Notes\n\n- items\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_page_shaped_store(store: Path, stamp: str | None = None) -> list[Path]:
    store.mkdir(parents=True, exist_ok=True)
    schema = {
        "schema_version": "1.0",
        "atlas_id": "page-shaped",
        "structure": {},
        "compile": {},
    }
    if stamp is not None:
        schema["atlas_release"] = stamp
    (store / "SCHEMA.json").write_text(json.dumps(schema), encoding="utf-8")

    write_index(store)
    write_page(store / "memory.md", "memory")
    write_page(store / "frame.md", "frame")
    for folder, gist_names in (("one", ("g1.md",)), ("two", ("g1.md", "g2.md"))):
        write_index(store / folder)
        for name in gist_names:
            write_page(
                store / folder / name,
                "gist",
                [{"path": f"{folder}/index.md", "kind": "derived_from"}],
            )
    write_index(store / "none")
    write_page(store / "none" / "decision.md", "decision")
    return sorted(path for path in store.rglob("*.md") if path.is_file())


def main() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        status = "PASS" if condition else "FAIL"
        print(f"[{status}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    tmp = Path(tempfile.mkdtemp(prefix="atlas-schema-layer-contract-"))
    try:
        # === one-contract-file ===================================================
        both = tmp / "one-contract-file-both"
        both.mkdir(parents=True)
        (both / "SCHEMA.json").write_text("{}\n", encoding="utf-8")
        (both / "CONTRACT.json").write_text("{}\n", encoding="utf-8")
        code, payload = run_json(["compile", "--root", str(both), "--json"])
        check(
            "one-contract-file: both SCHEMA.json and CONTRACT.json present fails",
            code != 0 and "schema_present" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        neither = tmp / "one-contract-file-neither"
        neither.mkdir(parents=True)
        code, payload = run_json(["compile", "--root", str(neither), "--json"])
        check(
            "one-contract-file: neither SCHEMA.json nor CONTRACT.json present fails",
            code != 0 and "schema_present" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        one = tmp / "one-contract-file-single"
        init_r = run(["init", "--root", str(one), "--json"])
        check("one-contract-file: single CONTRACT.json beta.3 store init ok", init_r.returncode == 0, init_r.stderr)
        check(
            "one-contract-file: init writes CONTRACT.json not SCHEMA.json",
            (one / "CONTRACT.json").is_file() and not (one / "SCHEMA.json").is_file(),
        )
        code, payload = run_json(["compile", "--root", str(one), "--json"])
        check(
            "one-contract-file: a single CONTRACT.json beta.3 store compiles",
            code == 0,
            f"exit={code} critical={payload.get('critical')}",
        )

        # === pre-beta-eligible ====================================================
        pre_beta = tmp / "pre-beta-eligible"
        pre_beta.mkdir(parents=True)
        (pre_beta / "SCHEMA.json").write_text(
            json.dumps({"schema_version": "1.0", "atlas_id": "pb", "structure": {}, "compile": {}}),
            encoding="utf-8",
        )
        before_hash = sha(pre_beta / "SCHEMA.json")
        code, payload = run_json(
            ["memory-migrate", "--root", str(pre_beta), "--operation", "assess", "--json"]
        )
        check(
            "pre-beta-eligible: assess reports lineage pre-beta",
            code == 0 and payload.get("lineage") == "pre-beta",
            f"exit={code} payload={payload}",
        )
        check(
            "pre-beta-eligible: assess writes nothing (SCHEMA.json unchanged, no CONTRACT.json)",
            sha(pre_beta / "SCHEMA.json") == before_hash and not (pre_beta / "CONTRACT.json").exists(),
        )
        code, payload = run_json(
            ["memory-migrate", "--root", str(pre_beta), "--operation", "inventory", "--json"]
        )
        check(
            "pre-beta-eligible: inventory reports lineage pre-beta and writes nothing",
            code == 0
            and payload.get("lineage") == "pre-beta"
            and sha(pre_beta / "SCHEMA.json") == before_hash
            and not (pre_beta / "CONTRACT.json").exists(),
            f"exit={code} payload={payload}",
        )
        code, payload = run_json(
            ["memory-migrate", "--root", str(pre_beta), "--operation", "apply", "--json"]
        )
        check(
            "pre-beta-eligible: apply with no --batch refuses and writes nothing",
            code != 0
            and sha(pre_beta / "SCHEMA.json") == before_hash
            and not (pre_beta / "CONTRACT.json").exists(),
            f"exit={code} payload={payload}",
        )
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(pre_beta),
                "--operation",
                "apply",
                "--batch",
                "migrate everything",
                "--json",
            ]
        )
        check(
            "pre-beta-eligible: apply with 'migrate everything' refuses and writes nothing",
            code != 0
            and sha(pre_beta / "SCHEMA.json") == before_hash
            and not (pre_beta / "CONTRACT.json").exists(),
            f"exit={code} payload={payload}",
        )
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(pre_beta),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        check(
            "pre-beta-eligible: apply --batch contract-file renames to CONTRACT.json",
            code == 0 and (pre_beta / "CONTRACT.json").is_file() and not (pre_beta / "SCHEMA.json").exists(),
            f"exit={code} payload={payload}",
        )
        migrated = json.loads((pre_beta / "CONTRACT.json").read_text(encoding="utf-8"))
        check(
            "pre-beta-eligible: migrated store stamps atlas_release/memory.layers beta.4",
            migrated.get("atlas_release") == "0.13.0-beta.4"
            and migrated.get("memory", {}).get("layers") == ["schema", "gist", "memory"],
            str(migrated),
        )

        # === unstamped-page-shaped-store =========================================
        page_shaped = tmp / "unstamped-page-shaped-store"
        preexisting_pages = write_page_shaped_store(page_shaped)
        original_page_hashes = {path.relative_to(page_shaped): sha(path) for path in preexisting_pages}
        page_shaped_contract = page_shaped / "SCHEMA.json"
        original_contract_hash = sha(page_shaped_contract)
        code, payload = run_json(
            ["memory-migrate", "--root", str(page_shaped), "--operation", "assess", "--json"]
        )
        check(
            "page-shaped-store: assess reports in-beta lineage",
            code == 0 and payload.get("lineage") == "in-beta",
            f"exit={code} payload={payload}",
        )
        check(
            "page-shaped-store: assess writes nothing",
            sha(page_shaped_contract) == original_contract_hash
            and not (page_shaped / "CONTRACT.json").exists()
            and not list(page_shaped.rglob("schema.md")),
        )
        code, payload = run_json(
            ["memory-migrate", "--root", str(page_shaped), "--operation", "apply", "--json"]
        )
        check(
            "page-shaped-store: apply without batch refuses without writing",
            code != 0
            and sha(page_shaped_contract) == original_contract_hash
            and not (page_shaped / "CONTRACT.json").exists()
            and not list(page_shaped.rglob("schema.md")),
            f"exit={code} payload={payload}",
        )
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(page_shaped),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        check(
            "page-shaped-store: contract-file apply succeeds and renames contract",
            code == 0
            and payload.get("ok") is True
            and payload.get("contract_file") == "CONTRACT.json"
            and (page_shaped / "CONTRACT.json").is_file()
            and not (page_shaped / "SCHEMA.json").exists(),
            f"exit={code} payload={payload}",
        )
        migrated = json.loads((page_shaped / "CONTRACT.json").read_text(encoding="utf-8"))
        check(
            "page-shaped-store: migration writes beta.4 contract stamp and layers",
            migrated.get("atlas_release") == "0.13.0-beta.4"
            and migrated.get("memory", {}).get("layers") == ["schema", "gist", "memory"],
            str(migrated),
        )
        check(
            "page-shaped-store: all pre-existing page bytes are unchanged",
            all(sha(page_shaped / relative) == digest for relative, digest in original_page_hashes.items()),
            str(original_page_hashes),
        )
        created_schema_pages: dict[str, list[Path]] = {}
        for folder in ("one", "two", "none"):
            found: list[Path] = []
            for path in sorted((page_shaped / folder).glob("*.md")):
                if path.name in ("index.md", "log.md"):
                    continue
                meta, _ = read_page(path)
                if meta.get("type") == "schema":
                    found.append(path)
            created_schema_pages[folder] = found
        check(
            "page-shaped-store: schema page count is one per gist folder and zero otherwise",
            len(created_schema_pages["one"]) == 1
            and len(created_schema_pages["two"]) == 1
            and len(created_schema_pages["none"]) == 0,
            str({folder: [str(p) for p in paths] for folder, paths in created_schema_pages.items()}),
        )
        relationships_match = True
        for folder, gist_names in (("one", ("g1.md",)), ("two", ("g1.md", "g2.md"))):
            schema_meta, _ = read_page(created_schema_pages[folder][0])
            expected = [
                {"path": f"{folder}/{name}", "kind": "related"}
                for name in sorted(gist_names)
            ]
            relationships_match = relationships_match and schema_meta.get("relates_to") == expected
        check(
            "page-shaped-store: new schema pages list exactly their own gists once",
            relationships_match,
        )
        code, payload = run_json(["compile", "--root", str(page_shaped), "--json"])
        check(
            "page-shaped-store: migrated beta.3 store has no schema_folder critical",
            "schema_folder" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # The released beta stamp takes precedence over otherwise memory-like
        # pages; apply must refuse it without touching any store file.
        stamped_page_shaped = tmp / "stamped-page-shaped-store"
        stamped_pages = write_page_shaped_store(stamped_page_shaped, "0.13.0-beta")
        stamped_hashes = {
            path.relative_to(stamped_page_shaped): sha(path)
            for path in [stamped_page_shaped / "SCHEMA.json", *stamped_pages]
        }
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(stamped_page_shaped),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        check(
            "page-shaped-store: beta stamp still refuses with in_beta_not_legacy",
            code != 0
            and "in_beta_not_legacy" in [f.get("id") for f in payload.get("findings", [])],
            f"exit={code} payload={payload}",
        )
        check(
            "page-shaped-store: beta stamp refusal leaves all bytes and paths unchanged",
            all(
                (stamped_page_shaped / relative).is_file()
                and sha(stamped_page_shaped / relative) == digest
                for relative, digest in stamped_hashes.items()
            )
            and not (stamped_page_shaped / "CONTRACT.json").exists()
            and not list(stamped_page_shaped.rglob("schema.md")),
        )

        for path_case in ("broken-symlink", "existing-file"):
            store = tmp / f"schema-page-target-{path_case}"
            store.mkdir()
            contract_path = store / "SCHEMA.json"
            contract_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "atlas_id": path_case,
                        "structure": {},
                        "compile": {},
                    }
                ),
                encoding="utf-8",
            )
            write_index(store / "one")
            write_page(store / "one" / "g1.md", "gist")
            schema_target = store / "one" / "schema.md"
            if path_case == "broken-symlink":
                schema_target.symlink_to(store / "missing-schema-target.md")
            else:
                schema_target.write_text("existing file must be preserved\n", encoding="utf-8")
            target_hash = None if path_case == "broken-symlink" else sha(schema_target)
            contract_hash = sha(contract_path)
            code, payload = run_json(
                [
                    "memory-migrate",
                    "--root",
                    str(store),
                    "--operation",
                    "apply",
                    "--batch",
                    "contract-file",
                    "--json",
                ]
            )
            check(
                f"schema-page-target-{path_case}: migration refuses before writing",
                code != 0
                and sha(contract_path) == contract_hash
                and not (store / "CONTRACT.json").exists()
                and (
                    schema_target.is_symlink()
                    if path_case == "broken-symlink"
                    else schema_target.is_file()
                )
                and (
                    target_hash is None
                    or sha(schema_target) == target_hash
                ),
                f"exit={code} payload={payload}",
            )

        # === in-beta-refused ======================================================
        for stamp in ("0.13.0-beta", "0.13.0-beta.2"):
            store = tmp / f"in-beta-refused-{stamp.replace('.', '_')}"
            store.mkdir(parents=True)
            schema_path = store / "SCHEMA.json"
            schema_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "atlas_id": "ib",
                        "atlas_release": stamp,
                        "structure": {},
                        "compile": {},
                    }
                ),
                encoding="utf-8",
            )
            before = sha(schema_path)
            code, payload = run_json(
                [
                    "memory-migrate",
                    "--root",
                    str(store),
                    "--operation",
                    "apply",
                    "--batch",
                    "contract-file",
                    "--json",
                ]
            )
            findings = [f.get("id") for f in payload.get("findings", [])]
            check(
                f"in-beta-refused: apply on {stamp} exits non-zero",
                code != 0,
                f"exit={code} payload={payload}",
            )
            check(
                f"in-beta-refused: apply on {stamp} finding id in_beta_not_legacy",
                "in_beta_not_legacy" in findings,
                f"findings={findings}",
            )
            check(
                f"in-beta-refused: apply on {stamp} leaves SCHEMA.json bytes unchanged",
                sha(schema_path) == before and not (store / "CONTRACT.json").exists(),
            )

        # === in-beta-refused-unstamped-shipped-beta2 ==============================
        # The actual shipped 0.13.0-beta.2 init shape: no atlas_release stamp and
        # no memory key, but the full init document (templates plus
        # types.recommended including frame) — the same discriminator pin 5 uses
        # to tell it apart from the minimal pre-beta-eligible fixture above.
        unstamped = tmp / "in-beta-refused-unstamped-shipped-beta2"
        unstamped.mkdir(parents=True)
        unstamped_schema_path = unstamped / "SCHEMA.json"
        unstamped_schema_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "ib2",
                    "structure": {},
                    "compile": {},
                    "templates": {"directory": "templates/", "by_type": {}},
                    "types": {
                        "recommended": [
                            "experience",
                            "decision",
                            "lesson",
                            "recipe",
                            "work",
                            "protostar",
                            "gist",
                            "frame",
                            "memory",
                        ],
                        "unconstrained": [],
                    },
                }
            ),
            encoding="utf-8",
        )
        unstamped_before = sha(unstamped_schema_path)
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(unstamped),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        findings = [f.get("id") for f in payload.get("findings", [])]
        check(
            "in-beta-refused-unstamped-shipped-beta2: apply exits non-zero",
            code != 0,
            f"exit={code} payload={payload}",
        )
        check(
            "in-beta-refused-unstamped-shipped-beta2: finding id in_beta_not_legacy",
            "in_beta_not_legacy" in findings,
            f"findings={findings}",
        )
        check(
            "in-beta-refused-unstamped-shipped-beta2: leaves SCHEMA.json bytes unchanged",
            sha(unstamped_schema_path) == unstamped_before
            and not (unstamped / "CONTRACT.json").exists(),
        )

        # === one-schema-per-gist-folder (beta.3 / current shape only) ============
        def beta3_store(name: str) -> Path:
            d = tmp / name
            r = run(["init", "--root", str(d), "--json"])
            if r.returncode != 0:
                raise AssertionError(f"init failed for {name}: {r.stderr}")
            return d

        # one gist, one schema -> accepted
        d = beta3_store("folder-one-gist-one-schema")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(d / "notes" / "s1.md", "schema", [{"path": "notes/g1.md", "kind": "related"}])
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "one-schema-per-gist-folder: one gist + one schema accepted",
            code == 0 and "schema_folder" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # two gists, one schema -> accepted
        d = beta3_store("folder-two-gist-one-schema")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(d / "notes" / "g2.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(
            d / "notes" / "s1.md",
            "schema",
            [{"path": "notes/g1.md", "kind": "related"}, {"path": "notes/g2.md", "kind": "related"}],
        )
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "one-schema-per-gist-folder: two gists + one schema accepted",
            code == 0 and "schema_folder" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # zero gists, one schema -> rejected
        d = beta3_store("folder-zero-gist-schema")
        write_index(d / "notes")
        write_page(d / "notes" / "s1.md", "schema")
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "one-schema-per-gist-folder: zero gists + a schema rejected",
            code != 0 and "schema_folder" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # two schemas, one gist -> rejected
        d = beta3_store("folder-two-schema")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(d / "notes" / "s1.md", "schema", [{"path": "notes/g1.md", "kind": "related"}])
        write_page(d / "notes" / "s2.md", "schema", [{"path": "notes/g1.md", "kind": "related"}])
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "one-schema-per-gist-folder: two schemas in a gist-bearing folder rejected",
            code != 0 and "schema_folder" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # one gist, no schema -> rejected
        d = beta3_store("folder-one-gist-no-schema")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "one-schema-per-gist-folder: one gist, no schema rejected",
            code != 0 and "schema_folder" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # two gists, schema lists one gist twice (duplicate) -> rejected
        d = beta3_store("folder-schema-duplicate-gist")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(d / "notes" / "g2.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(
            d / "notes" / "s1.md",
            "schema",
            [{"path": "notes/g1.md", "kind": "related"}, {"path": "notes/g1.md", "kind": "related"}],
        )
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "one-schema-per-gist-folder: schema listing one gist twice (duplicate) rejected",
            code != 0 and "schema_folder" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # two gists, schema lists only one (omission) -> rejected
        d = beta3_store("folder-schema-omits-gist")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(d / "notes" / "g2.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(d / "notes" / "s1.md", "schema", [{"path": "notes/g1.md", "kind": "related"}])
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "one-schema-per-gist-folder: schema omitting a folder gist rejected",
            code != 0 and "schema_folder" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # one gist per folder, each folder's schema lists the other folder's gist
        # (cross-folder reference) -> rejected in both folders
        d = beta3_store("folder-schema-other-folder-gist")
        write_index(d / "alpha")
        write_index(d / "beta")
        write_page(d / "alpha" / "g1.md", "gist", [{"path": "alpha/index.md", "kind": "derived_from"}])
        write_page(d / "beta" / "g2.md", "gist", [{"path": "beta/index.md", "kind": "derived_from"}])
        write_page(d / "alpha" / "s1.md", "schema", [{"path": "beta/g2.md", "kind": "related"}])
        write_page(d / "beta" / "s2.md", "schema", [{"path": "alpha/g1.md", "kind": "related"}])
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        schema_folder_paths = [
            i.get("path") for i in payload.get("critical", []) if i.get("id") == "schema_folder"
        ]
        check(
            "one-schema-per-gist-folder: schema listing another folder's gist rejected in both folders",
            code != 0
            and "alpha/s1.md" in schema_folder_paths
            and "beta/s2.md" in schema_folder_paths,
            f"exit={code} critical={payload.get('critical')}",
        )

        # === focused-compile-ignores-out-of-focus-schema-folder ==================
        # A --path/--type focused compile must not fail because of an
        # unrelated out-of-focus folder's schema_folder finding.
        d = beta3_store("folder-focus-ignores-other-folder")
        write_index(d / "good")
        write_page(d / "good" / "g1.md", "gist", [{"path": "good/index.md", "kind": "derived_from"}])
        write_page(d / "good" / "s1.md", "schema", [{"path": "good/g1.md", "kind": "related"}])
        write_index(d / "bad")
        write_page(d / "bad" / "g1.md", "gist", [{"path": "bad/index.md", "kind": "derived_from"}])
        # "bad" folder has a gist but no schema page -> schema_folder finding.
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "focused-compile: unfocused compile sees the other folder's schema_folder finding",
            code != 0 and "schema_folder" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )
        code, payload = run_json(
            ["compile", "--root", str(d), "--path", "good", "--json"]
        )
        check(
            "focused-compile --path good: ignores the unrelated bad/ schema_folder finding",
            code == 0 and "schema_folder" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # === focused-compile-keeps-own-folder-schema-folder-in-scope =============
        # A --path focus on a gist that IS a member of a gist-bearing folder
        # must keep that folder's schema_folder invariant in scope, whether
        # the finding is reported on the folder itself (missing schema) or on
        # a sibling schema page in the same folder (membership errors). An
        # unrelated folder must still stay out of scope.

        # missing-schema finding reported on the folder path itself.
        d = beta3_store("folder-focus-own-folder-missing-schema")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_index(d / "other")
        write_page(d / "other" / "g1.md", "gist", [{"path": "other/index.md", "kind": "derived_from"}])
        write_page(d / "other" / "s1.md", "schema", [{"path": "other/g1.md", "kind": "related"}])
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "focused-compile own-folder: unfocused compile sees notes/ missing-schema finding",
            code != 0 and "schema_folder" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )
        code, payload = run_json(
            ["compile", "--root", str(d), "--path", "notes/g1.md", "--json"]
        )
        check(
            "focused-compile --path notes/g1.md: keeps notes/ missing-schema finding in scope",
            code != 0 and "schema_folder" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )
        code, payload = run_json(
            ["compile", "--root", str(d), "--path", "other/g1.md", "--json"]
        )
        check(
            "focused-compile --path other/g1.md: unrelated notes/ finding stays out of scope",
            code == 0 and "schema_folder" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # membership error reported on a sibling schema page in the same folder.
        d = beta3_store("folder-focus-own-folder-membership-error")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(d / "notes" / "g2.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        # schema omits g2 (membership error) -> finding reported on notes/s1.md.
        write_page(d / "notes" / "s1.md", "schema", [{"path": "notes/g1.md", "kind": "related"}])
        write_index(d / "other")
        write_page(d / "other" / "g1.md", "gist", [{"path": "other/index.md", "kind": "derived_from"}])
        write_page(d / "other" / "s1.md", "schema", [{"path": "other/g1.md", "kind": "related"}])
        code, payload = run_json(
            ["compile", "--root", str(d), "--path", "notes/g2.md", "--json"]
        )
        check(
            "focused-compile --path notes/g2.md: sibling schema's membership error stays in scope",
            code != 0 and "schema_folder" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )
        code, payload = run_json(
            ["compile", "--root", str(d), "--path", "other/g1.md", "--json"]
        )
        check(
            "focused-compile --path other/g1.md: unrelated notes/ membership error stays out of scope",
            code == 0 and "schema_folder" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # one gist listed once by its schema still compiles clean under file focus.
        d = beta3_store("folder-focus-one-gist-one-schema-clean")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(d / "notes" / "s1.md", "schema", [{"path": "notes/g1.md", "kind": "related"}])
        code, payload = run_json(
            ["compile", "--root", str(d), "--path", "notes/g1.md", "--json"]
        )
        check(
            "focused-compile --path notes/g1.md: one gist listed once by its schema compiles clean",
            code == 0 and "schema_folder" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # a focused descendant page is a member of its own folder only, not of
        # any ancestor folder: notes/ has a gist and no schema (schema_folder
        # on notes), but notes/sub/g1.md's own folder (notes/sub) has a valid
        # schema. Focusing notes/sub/g1.md must not pull in the ancestor
        # notes/ finding.
        d = beta3_store("folder-focus-ancestor-not-member")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        # "notes" folder has a gist but no schema page -> schema_folder finding on "notes".
        write_index(d / "notes" / "sub")
        write_page(
            d / "notes" / "sub" / "g1.md", "gist", [{"path": "notes/sub/index.md", "kind": "derived_from"}]
        )
        write_page(
            d / "notes" / "sub" / "s1.md", "schema", [{"path": "notes/sub/g1.md", "kind": "related"}]
        )
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "focused-compile ancestor-not-member: unfocused compile sees notes/ missing-schema finding",
            code != 0 and "schema_folder" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )
        code, payload = run_json(
            ["compile", "--root", str(d), "--path", "notes/sub/g1.md", "--json"]
        )
        check(
            "focused-compile --path notes/sub/g1.md: ancestor notes/ finding stays out of scope",
            code == 0 and "schema_folder" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )
        code, payload = run_json(
            ["compile", "--root", str(d), "--path", "notes", "--json"]
        )
        check(
            "focused-compile --path notes: still includes the notes/ missing-schema finding itself",
            code != 0 and "schema_folder" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # === read-shipped-beta ====================================================
        shipped = tmp / "read-shipped-beta"
        shipped.mkdir(parents=True)
        (shipped / "SCHEMA.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "shipped",
                    "structure": {
                        "free_layout": True,
                        "staging_dir": "staging",
                        "require_index_in_folders": True,
                        "reserved_names": ["index.md", "log.md", "staging", "schema.d"],
                    },
                    "compile": {
                        "hard_fail": True,
                        "allow_inline_ignores": True,
                        "min_body_chars": 40,
                        "core_checks": [
                            "okf_compliance",
                            "frontmatter",
                            "internal_links",
                            "not_just_links",
                            "schema_present",
                            "no_answerable_in_staging",
                            "index_md_present",
                            "index_md_listing",
                        ],
                    },
                    "templates": {
                        "directory": "templates/",
                        "by_type": {
                            name: {
                                "file": f"templates/{name}.md",
                                "frontmatter": {
                                    "required": ["type", "title", "created"],
                                    "recommended": [],
                                },
                                "sections": {"required": [], "recommended": []},
                            }
                            for name in (
                                "experience",
                                "decision",
                                "lesson",
                                "recipe",
                                "work",
                                "protostar",
                                "gist",
                                "frame",
                                "page",
                            )
                        },
                    },
                    "types": {
                        "recommended": [
                            "experience",
                            "decision",
                            "lesson",
                            "recipe",
                            "work",
                            "protostar",
                            "gist",
                            "frame",
                            "page",
                        ],
                        "unconstrained": [],
                    },
                    "memory": {"layers": ["frame", "gist", "page"]},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (shipped / "index.md").write_text("# shipped\n\n- items\n", encoding="utf-8")
        (shipped / "log.md").write_text("# Log\n\n- init\n", encoding="utf-8")
        tmpl_dst = shipped / "templates"
        tmpl_dst.mkdir()
        for name in ("experience.md", "gist.md", "frame.md", "page.md"):
            src = ROOT / "references" / "templates" / name
            if src.is_file():
                shutil.copy2(src, tmpl_dst / name)
        before_hash = sha(shipped / "SCHEMA.json")
        code, payload = run_json(["compile", "--root", str(shipped), "--json"])
        check(
            "read-shipped-beta: SCHEMA.json frame/gist/page store with no stamp compiles",
            code == 0,
            f"exit={code} critical={payload.get('critical')}",
        )
        check(
            "read-shipped-beta: SCHEMA.json is not renamed by compile",
            (shipped / "SCHEMA.json").is_file()
            and not (shipped / "CONTRACT.json").exists()
            and sha(shipped / "SCHEMA.json") == before_hash,
        )

        # === stamp-shape-disagree =================================================
        disagree = tmp / "stamp-shape-disagree"
        disagree.mkdir(parents=True)
        (disagree / "SCHEMA.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "disagree",
                    "atlas_release": "0.13.0-beta.3",
                    "structure": {},
                    "compile": {},
                    "memory": {"layers": ["frame", "gist", "page"]},
                }
            ),
            encoding="utf-8",
        )
        code, payload = run_json(["compile", "--root", str(disagree), "--json"])
        check(
            "stamp-shape-disagree: atlas_release 0.13.0-beta.3 on SCHEMA.json with frame/gist/page fails",
            code != 0 and "stamp_shape" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # === beta3-contract-still-current ========================================
        # A hand-stamped CONTRACT.json still carrying the original
        # "0.13.0-beta.3" stamp (not the "0.13.0-beta.4" stamp init/apply now
        # write) with layers schema/gist/memory must still read as "current":
        # compile succeeds, memory-migrate assess reports lineage current, and
        # apply is a no-op that never rewrites the stamp to beta.4.
        beta3_reader = tmp / "beta3-contract-still-current"
        beta3_reader.mkdir(parents=True)
        (beta3_reader / "index.md").write_text("# Store\n\n- notes\n", encoding="utf-8")
        write_index(beta3_reader / "notes")
        write_page(
            beta3_reader / "notes" / "g1.md",
            "gist",
            [{"path": "notes/index.md", "kind": "derived_from"}],
        )
        write_page(
            beta3_reader / "notes" / "s1.md",
            "schema",
            [{"path": "notes/g1.md", "kind": "related"}],
        )
        (beta3_reader / "CONTRACT.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "beta3-reader",
                    "atlas_release": "0.13.0-beta.3",
                    "structure": {},
                    "compile": {},
                    "memory": {"layers": ["schema", "gist", "memory"]},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        before_beta3_hash = sha(beta3_reader / "CONTRACT.json")
        code, payload = run_json(["compile", "--root", str(beta3_reader), "--json"])
        check(
            "beta3-contract-still-current: a hand-stamped 0.13.0-beta.3 CONTRACT.json compiles",
            code == 0,
            f"exit={code} critical={payload.get('critical')}",
        )
        code, payload = run_json(
            ["memory-migrate", "--root", str(beta3_reader), "--operation", "assess", "--json"]
        )
        check(
            "beta3-contract-still-current: memory-migrate assess reports lineage current",
            code == 0 and payload.get("lineage") == "current",
            f"exit={code} payload={payload}",
        )
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(beta3_reader),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        check(
            "beta3-contract-still-current: apply on an already-current beta.3 store is a no-op",
            code == 0 and (beta3_reader / "CONTRACT.json").is_file(),
            f"exit={code} payload={payload}",
        )
        check(
            "beta3-contract-still-current: apply does not rewrite the stamp to beta.4",
            sha(beta3_reader / "CONTRACT.json") == before_beta3_hash,
        )

        # === memory-rung-preserves-lineage =======================================
        # A shipped 0.13.0-beta SCHEMA.json with no memory block must keep
        # frame/gist/page after `schema memory-rung --set` — merely setting the
        # rung must not promote it to the beta.2 frame/gist/memory layers.
        rung_beta = tmp / "memory-rung-preserves-shipped-beta"
        rung_beta.mkdir(parents=True)
        (rung_beta / "SCHEMA.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "rung-beta",
                    "atlas_release": "0.13.0-beta",
                    "structure": {},
                    "compile": {},
                }
            ),
            encoding="utf-8",
        )
        code, payload = run_json(
            ["schema", "memory-rung", "--set", "warn", "--root", str(rung_beta), "--json"]
        )
        after = json.loads((rung_beta / "SCHEMA.json").read_text(encoding="utf-8"))
        check(
            "memory-rung-preserves-lineage: memory-less SCHEMA.json stamped 0.13.0-beta "
            "gets frame/gist/page after memory-rung, not frame/gist/memory",
            code == 0 and after.get("memory", {}).get("layers") == ["frame", "gist", "page"],
            f"exit={code} payload={payload} after={after}",
        )

        # An unstamped (no atlas_release) SCHEMA.json with no memory block and no
        # full beta.2 init shape also resolves to shipped_beta via
        # compute_stamp_shape, so it must also keep frame/gist/page.
        rung_unstamped = tmp / "memory-rung-preserves-shipped-beta-unstamped"
        rung_unstamped.mkdir(parents=True)
        (rung_unstamped / "SCHEMA.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "rung-unstamped",
                    "structure": {},
                    "compile": {},
                }
            ),
            encoding="utf-8",
        )
        code, payload = run_json(
            ["schema", "memory-rung", "--set", "warn", "--root", str(rung_unstamped), "--json"]
        )
        after = json.loads((rung_unstamped / "SCHEMA.json").read_text(encoding="utf-8"))
        check(
            "memory-rung-preserves-lineage: unstamped memory-less SCHEMA.json also "
            "gets frame/gist/page, not frame/gist/memory",
            code == 0 and after.get("memory", {}).get("layers") == ["frame", "gist", "page"],
            f"exit={code} payload={payload} after={after}",
        )

        # A SCHEMA.json that already carries frame/gist/memory (0.13.0-beta.2
        # shape) must keep that shape after memory-rung.
        rung_beta2 = tmp / "memory-rung-preserves-in-beta"
        rung_beta2.mkdir(parents=True)
        (rung_beta2 / "SCHEMA.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "rung-beta2",
                    "structure": {},
                    "compile": {},
                    "memory": {"layers": ["frame", "gist", "memory"]},
                }
            ),
            encoding="utf-8",
        )
        code, payload = run_json(
            ["schema", "memory-rung", "--set", "warn", "--root", str(rung_beta2), "--json"]
        )
        after = json.loads((rung_beta2 / "SCHEMA.json").read_text(encoding="utf-8"))
        check(
            "memory-rung-preserves-lineage: SCHEMA.json already frame/gist/memory stays that way",
            code == 0 and after.get("memory", {}).get("layers") == ["frame", "gist", "memory"],
            f"exit={code} payload={payload} after={after}",
        )

        # A CONTRACT.json beta.3 store keeps schema/gist/memory after memory-rung.
        rung_beta3 = beta3_store("memory-rung-preserves-current")
        code, payload = run_json(
            ["schema", "memory-rung", "--set", "warn", "--root", str(rung_beta3), "--json"]
        )
        after = json.loads((rung_beta3 / "CONTRACT.json").read_text(encoding="utf-8"))
        check(
            "memory-rung-preserves-lineage: CONTRACT.json beta.3 store stays schema/gist/memory",
            code == 0 and after.get("memory", {}).get("layers") == ["schema", "gist", "memory"],
            f"exit={code} payload={payload} after={after}",
        )

        # A stamp_shape mismatch must fail closed: memory-rung must not write.
        rung_mismatch = tmp / "memory-rung-fails-closed-on-stamp-mismatch"
        rung_mismatch.mkdir(parents=True)
        (rung_mismatch / "SCHEMA.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "rung-mismatch",
                    "atlas_release": "0.13.0-beta.999",
                    "structure": {},
                    "compile": {},
                }
            ),
            encoding="utf-8",
        )
        before_mismatch = sha(rung_mismatch / "SCHEMA.json")
        code, payload = run_json(
            ["schema", "memory-rung", "--set", "warn", "--root", str(rung_mismatch), "--json"]
        )
        check(
            "memory-rung-preserves-lineage: unknown stamp fails closed, nothing written",
            code != 0 and sha(rung_mismatch / "SCHEMA.json") == before_mismatch,
            f"exit={code} payload={payload}",
        )

        # === gist-parent-accepts-page (original shipped-beta page type) =========
        page_store = tmp / "gist-parent-accepts-page"
        page_store.mkdir(parents=True)
        write_index(page_store / "notes")
        write_page(page_store / "notes" / "p1.md", "page")
        write_page(
            page_store / "notes" / "g1.md",
            "gist",
            [{"path": "notes/p1.md", "kind": "derived_from"}],
        )
        write_page(
            page_store / "notes" / "f1.md",
            "frame",
            [{"path": "notes/g1.md", "kind": "groups"}],
        )
        (page_store / "SCHEMA.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "page-gist-frame",
                    "atlas_release": "0.13.0-beta",
                    "structure": {
                        "free_layout": True,
                        "staging_dir": "staging",
                        "require_index_in_folders": True,
                        "reserved_names": ["index.md", "log.md", "staging", "schema.d"],
                    },
                    "compile": {
                        "hard_fail": True,
                        "allow_inline_ignores": True,
                        "min_body_chars": 40,
                        "core_checks": [
                            "okf_compliance",
                            "frontmatter",
                            "internal_links",
                            "not_just_links",
                            "schema_present",
                            "no_answerable_in_staging",
                            "index_md_present",
                            "index_md_listing",
                        ],
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        code, payload = run_json(["compile", "--root", str(page_store), "--json"])
        all_findings = (
            payload.get("critical", []) + payload.get("warnings", []) + payload.get("info", [])
        )
        all_ids_paths = {(i.get("id"), i.get("path")) for i in all_findings}
        check(
            "gist-parent-accepts-page: page -> gist -> frame store does not report "
            "gist_parent for the gist derived from the page",
            ("gist_parent", "notes/g1.md") not in all_ids_paths,
            f"findings={all_findings}",
        )
        check(
            "gist-parent-accepts-page: the page is credited by its gist (no missing_gist)",
            ("missing_gist", "notes/p1.md") not in all_ids_paths,
            f"findings={all_findings}",
        )

        # === contract-symlink-rejected (central find_contract_path helper) =======
        outside = tmp / "contract-symlink-outside-target.json"
        outside.write_text(
            json.dumps({"schema_version": "1.0", "atlas_id": "outside", "structure": {}, "compile": {}}),
            encoding="utf-8",
        )
        outside_before = sha(outside)
        symlink_store = tmp / "contract-symlink-store"
        symlink_store.mkdir(parents=True)
        (symlink_store / "CONTRACT.json").symlink_to(outside)
        code, payload = run_json(
            [
                "schema",
                "memory-rung",
                "--set",
                "warn",
                "--root",
                str(symlink_store),
                "--json",
            ]
        )
        check(
            "contract-symlink-rejected: a mutating command refuses a CONTRACT.json symlink",
            code != 0,
            f"exit={code} payload={payload}",
        )
        check(
            "contract-symlink-rejected: the outside symlink target is unchanged",
            sha(outside) == outside_before,
        )
        check(
            "contract-symlink-rejected: the symlink itself is left in place",
            (symlink_store / "CONTRACT.json").is_symlink(),
        )

        # A broken symlink (target does not exist) must also be rejected, not
        # just a symlink pointing at a real file.
        broken_store = tmp / "contract-symlink-store-broken"
        broken_store.mkdir(parents=True)
        (broken_store / "CONTRACT.json").symlink_to(tmp / "does-not-exist.json")
        code, payload = run_json(
            [
                "schema",
                "memory-rung",
                "--set",
                "warn",
                "--root",
                str(broken_store),
                "--json",
            ]
        )
        check(
            "contract-symlink-rejected: a broken CONTRACT.json symlink is also refused",
            code != 0,
            f"exit={code} payload={payload}",
        )

        # A real (non-symlink) contract file must still load/write normally.
        real_store = beta3_store("contract-symlink-real-file-still-works")
        code, payload = run_json(
            ["schema", "memory-rung", "--set", "warn", "--root", str(real_store), "--json"]
        )
        check(
            "contract-symlink-rejected: a real non-symlink CONTRACT.json still loads/writes",
            code == 0 and payload.get("ok") is True,
            f"exit={code} payload={payload}",
        )

        # === init-schema-symlink-rejected (broken SCHEMA.json symlink) ===========
        # A broken SCHEMA.json symlink must be caught by init too, not just
        # find_contract_path's readers — has_contract_file() uses is_file(),
        # which is False for a broken link, so without an explicit is_symlink()
        # check init would silently write CONTRACT.json alongside the dangling
        # SCHEMA.json symlink.
        init_symlink_store = tmp / "init-schema-symlink-store"
        init_symlink_store.mkdir(parents=True)
        (init_symlink_store / "SCHEMA.json").symlink_to(tmp / "init-schema-symlink-does-not-exist.json")
        code, payload = run_json(["init", "--root", str(init_symlink_store), "--json"])
        check(
            "init-schema-symlink-rejected: init refuses a broken SCHEMA.json symlink",
            code != 0,
            f"exit={code} payload={payload}",
        )
        check(
            "init-schema-symlink-rejected: init does not create CONTRACT.json",
            not (init_symlink_store / "CONTRACT.json").exists(),
        )
        check(
            "init-schema-symlink-rejected: the SCHEMA.json symlink is left in place",
            (init_symlink_store / "SCHEMA.json").is_symlink(),
        )

        code, payload = run_json(["init", "--root", str(init_symlink_store), "--force", "--json"])
        check(
            "init-schema-symlink-rejected: --force also refuses a broken SCHEMA.json symlink",
            code != 0,
            f"exit={code} payload={payload}",
        )
        check(
            "init-schema-symlink-rejected: --force does not create CONTRACT.json",
            not (init_symlink_store / "CONTRACT.json").exists(),
        )
        check(
            "init-schema-symlink-rejected: --force leaves the SCHEMA.json symlink in place",
            (init_symlink_store / "SCHEMA.json").is_symlink(),
        )

        # A SCHEMA.json symlink to a real outside file must not have that file
        # modified either.
        init_symlink_outside = tmp / "init-schema-symlink-outside-target.json"
        init_symlink_outside.write_text(
            json.dumps({"schema_version": "1.0", "atlas_id": "outside", "structure": {}, "compile": {}}),
            encoding="utf-8",
        )
        init_symlink_outside_before = sha(init_symlink_outside)
        init_symlink_store_live = tmp / "init-schema-symlink-store-live"
        init_symlink_store_live.mkdir(parents=True)
        (init_symlink_store_live / "SCHEMA.json").symlink_to(init_symlink_outside)
        code, payload = run_json(["init", "--root", str(init_symlink_store_live), "--force", "--json"])
        check(
            "init-schema-symlink-rejected: init refuses a SCHEMA.json symlink to a real file",
            code != 0,
            f"exit={code} payload={payload}",
        )
        check(
            "init-schema-symlink-rejected: the outside symlink target is unchanged",
            sha(init_symlink_outside) == init_symlink_outside_before,
        )

        # A normal (non-symlink) init with no pre-existing SCHEMA.json/CONTRACT.json
        # still writes only CONTRACT.json.
        init_plain_store = tmp / "init-schema-symlink-plain-store"
        code, payload = run_json(["init", "--root", str(init_plain_store), "--json"])
        check(
            "init-schema-symlink-rejected: a plain init (no symlink) still succeeds",
            code == 0,
            f"exit={code} payload={payload}",
        )
        check(
            "init-schema-symlink-rejected: a plain init writes only CONTRACT.json",
            (init_plain_store / "CONTRACT.json").is_file() and not (init_plain_store / "SCHEMA.json").exists(),
        )

        # === malformed-stamp-fails-closed (stamp compare) ========================
        malformed = tmp / "malformed-stamp-fails-closed"
        malformed.mkdir(parents=True)
        (malformed / "SCHEMA.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "malformed",
                    "atlas_release": "0.12.0oops",
                    "structure": {},
                    "compile": {},
                }
            ),
            encoding="utf-8",
        )
        malformed_before = sha(malformed / "SCHEMA.json")
        code, payload = run_json(
            ["memory-migrate", "--root", str(malformed), "--operation", "assess", "--json"]
        )
        check(
            "malformed-stamp-fails-closed: 0.12.0oops is not classified pre-beta",
            code == 0 and payload.get("lineage") != "pre-beta",
            f"exit={code} payload={payload}",
        )
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(malformed),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        check(
            "malformed-stamp-fails-closed: apply on 0.12.0oops exits non-zero and writes nothing",
            code != 0
            and sha(malformed / "SCHEMA.json") == malformed_before
            and not (malformed / "CONTRACT.json").exists(),
            f"exit={code} payload={payload}",
        )

        # A genuine older X.Y.Z stamp (not malformed) still classifies pre-beta
        # and still migrates only with an attested named batch.
        genuine_old = tmp / "malformed-stamp-fails-closed-genuine-old"
        genuine_old.mkdir(parents=True)
        (genuine_old / "SCHEMA.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "genuine-old",
                    "atlas_release": "0.12.0",
                    "structure": {},
                    "compile": {},
                }
            ),
            encoding="utf-8",
        )
        code, payload = run_json(
            ["memory-migrate", "--root", str(genuine_old), "--operation", "assess", "--json"]
        )
        check(
            "malformed-stamp-fails-closed: a genuine 0.12.0 stamp still classifies pre-beta",
            code == 0 and payload.get("lineage") == "pre-beta",
            f"exit={code} payload={payload}",
        )

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("\nFailed checks:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("\nAll schema-layer-contract regressions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
