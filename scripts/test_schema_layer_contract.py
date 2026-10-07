#!/usr/bin/env python3
"""Current-shape schema layer contract regressions.

Run: python3 scripts/test_schema_layer_contract.py
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))
from atlas_cli.core.frontmatter import read_page
from atlas_cli.core.schema import classify_lineage, compute_stamp_shape

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


def write_page(
    path: Path,
    type_name: str,
    relates_to=None,
    description: str | None = None,
    body: str = PROSE,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rel_lines = ""
    if relates_to:
        rel_lines = "relates_to:\n" + "".join(
            f"  - path: {item['path']}\n    kind: {item['kind']}\n" for item in relates_to
        )
    desc_line = f"description: {json.dumps(description)}\n" if description is not None else ""
    path.write_text(
        "---\n"
        f"type: {type_name}\n"
        "title: t\n"
        "created: 2026-10-04\n"
        f"{desc_line}"
        f"{rel_lines}"
        "---\n\n"
        "## Content\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    if type_name == "schema" and (path.parent / "index.md").is_file():
        index_path = path.parent / "index.md"
        with index_path.open("a", encoding="utf-8") as index_file:
            index_file.write(f"\n- [{path.stem}]({path.name})\n")


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
        check(
            "one-contract-file: init writes package-aligned beta.7 stamp",
            json.loads((one / "CONTRACT.json").read_text(encoding="utf-8")).get("atlas_release")
            == "0.13.0-beta.7",
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
            code == 2
            and "batch_required" in findings_by_id(payload, "findings")
            and {path.name for path in pre_beta.iterdir()} == {"SCHEMA.json"}
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
            code == 2
            and "batch_required" in findings_by_id(payload, "findings")
            and {path.name for path in pre_beta.iterdir()} == {"SCHEMA.json"}
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
            "pre-beta-eligible: migrated store stamps atlas_release/memory.layers beta.7",
            migrated.get("atlas_release") == "0.13.0-beta.7"
            and migrated.get("memory", {}).get("layers") == ["schema", "gist", "memory"],
            str(migrated),
        )

        # === unstamped-page-shaped-store =========================================
        page_shaped = tmp / "unstamped-page-shaped-store"
        preexisting_pages = write_page_shaped_store(page_shaped)
        original_page_hashes = {
            path.relative_to(page_shaped): sha(path)
            for path in preexisting_pages
            if path.name not in ("index.md", "log.md")
        }
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
            and not list(page_shaped.rglob("*.schema.md")),
        )
        code, payload = run_json(["compile", "--root", str(page_shaped), "--json"])
        check(
            "SCHEMA.json store does not require current-shape schema pages",
            "schema_folder" not in findings_by_id(payload, "critical")
            and "schema_missing_from_index" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )
        code, payload = run_json(
            ["memory-migrate", "--root", str(page_shaped), "--operation", "apply", "--json"]
        )
        check(
            "page-shaped-store: apply without batch refuses without writing",
            code != 0
            and sha(page_shaped_contract) == original_contract_hash
            and not (page_shaped / "CONTRACT.json").exists()
            and not list(page_shaped.rglob("*.schema.md")),
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
            "page-shaped-store: migration writes beta.7 contract stamp and layers",
            migrated.get("atlas_release") == "0.13.0-beta.7"
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
            "page-shaped-store: migration adds a schema page for each gist folder",
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
        check(
            "page-shaped-store: every new schema is cued from its folder index",
            all(
                created_schema_pages[folder][0].name in
                (page_shaped / folder / "index.md").read_text(encoding="utf-8")
                for folder in ("one", "two")
            ),
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
            and not list(stamped_page_shaped.rglob("*.schema.md")),
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
            schema_target = store / "one" / "schema.schema.md"
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

        replaced_frame_store = tmp / "replaced-unsuffixed-frame"
        replaced_frame_store.mkdir()
        (replaced_frame_store / "SCHEMA.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "atlas_id": "replaced-frame",
                "structure": {},
                "compile": {},
            }),
            encoding="utf-8",
        )
        write_index(replaced_frame_store / "notes")
        write_page(replaced_frame_store / "notes" / "g1.md", "gist")
        write_page(replaced_frame_store / "notes" / "frame.md", "frame")
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(replaced_frame_store),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        check(
            "memory-migrate: generated schema replaces leftover unsuffixed frame page",
            code == 0
            and not (replaced_frame_store / "notes" / "frame.md").exists()
            and (replaced_frame_store / "notes" / "schema.schema.md").is_file(),
            f"exit={code} payload={payload}",
        )
        replaced_meta, replaced_body = read_page(
            replaced_frame_store / "notes" / "schema.schema.md"
        )
        check(
            "memory-migrate: replacement schema keeps authored frame content",
            replaced_meta.get("type") == "schema"
            and "## Content" in replaced_body
            and PROSE in replaced_body,
            f"meta={replaced_meta} body={replaced_body!r}",
        )

        existing_schema_store = tmp / "existing-schema-cues"
        existing_schema_store.mkdir()
        (existing_schema_store / "SCHEMA.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "existing-schema-cues",
                    "structure": {},
                    "compile": {},
                }
            ),
            encoding="utf-8",
        )
        existing_schema_paths = [
            existing_schema_store / "notes" / "subject.schema.md",
            existing_schema_store / "notes" / "second.schema.md",
            existing_schema_store / "schema-only" / "subject.schema.md",
        ]
        for schema_path in existing_schema_paths:
            write_index(schema_path.parent)
            if schema_path.parent.name == "notes":
                write_page(
                    schema_path.parent / "g1.gist.md",
                    "gist",
                    [{"path": "notes/index.md", "kind": "derived_from"}],
                )
                relates = [{"path": "notes/g1.gist.md", "kind": "related"}]
            else:
                relates = []
            write_page(schema_path, "schema", relates)
            (schema_path.parent / "index.md").write_text(
                "# Existing index\n\nNo schema links here.\n", encoding="utf-8"
            )
        existing_schema_hashes = {
            path: sha(path) for path in existing_schema_paths
        }
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(existing_schema_store),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        check(
            "memory-migrate: existing schemas and schema-only folder receive cues",
            code == 0
            and all(sha(path) == existing_schema_hashes[path] for path in existing_schema_paths)
            and all(
                re.search(r"\[[^\]]+\]\(\./[^)]+\)", (path.parent / "index.md").read_text(encoding="utf-8"))
                and any(
                    (path.parent / target).resolve() == path.resolve()
                    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", (path.parent / "index.md").read_text(encoding="utf-8"))
                )
                for path in existing_schema_paths
            ),
            f"exit={code} payload={payload}",
        )
        code, payload = run_json(
            ["compile", "--root", str(existing_schema_store), "--json"]
        )
        check(
            "memory-migrate: existing schema cue repair compiles without missing-index critical",
            "schema_missing_from_index" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        existing_schema_symlink_store = tmp / "existing-schema-index-symlink"
        existing_schema_symlink_store.mkdir()
        (existing_schema_symlink_store / "SCHEMA.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "existing-schema-index-symlink",
                    "structure": {},
                    "compile": {},
                }
            ),
            encoding="utf-8",
        )
        symlink_schema_folder = existing_schema_symlink_store / "notes"
        symlink_schema_folder.mkdir()
        symlink_schema = symlink_schema_folder / "subject.schema.md"
        write_page(symlink_schema, "schema")
        symlink_target = tmp / "existing-schema-index-target.md"
        symlink_target.write_text("# Outside index\n", encoding="utf-8")
        (symlink_schema_folder / "index.md").symlink_to(symlink_target)
        symlink_schema_contract = existing_schema_symlink_store / "SCHEMA.json"
        symlink_schema_contract_hash = sha(symlink_schema_contract)
        symlink_target_hash = sha(symlink_target)
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(existing_schema_symlink_store),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        check(
            "memory-migrate: existing schema index symlink refuses before writes",
            code != 0
            and any(
                finding.get("id") == "schema_symlink"
                for finding in payload.get("findings", [])
            )
            and sha(symlink_schema_contract) == symlink_schema_contract_hash
            and not (existing_schema_symlink_store / "CONTRACT.json").exists()
            and (symlink_schema_folder / "index.md").is_symlink()
            and sha(symlink_target) == symlink_target_hash,
            f"exit={code} payload={payload}",
        )

        substring_schema_store = tmp / "schema-cue-substring"
        substring_schema_store.mkdir()
        (substring_schema_store / "SCHEMA.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "schema-cue-substring",
                    "structure": {},
                    "compile": {},
                }
            ),
            encoding="utf-8",
        )
        substring_folder = substring_schema_store / "notes"
        write_index(substring_folder)
        write_page(
            substring_folder / "g1.gist.md",
            "gist",
            [{"path": "notes/index.md", "kind": "derived_from"}],
        )
        substring_index = substring_folder / "index.md"
        substring_index.write_text(
            "# Notes\n\nThe filename schema.schema.md is mentioned here.\n"
            "See https://example.invalid/schema.schema.md for details.\n",
            encoding="utf-8",
        )
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(substring_schema_store),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        generated_schema = substring_folder / "schema.schema.md"
        index_after_migrate = substring_index.read_text(encoding="utf-8")
        link_targets = re.findall(r"\[[^\]]+\]\(([^)]+)\)", index_after_migrate)
        check(
            "memory-migrate: filename prose and URL do not suppress a real schema cue",
            code == 0
            and any((substring_index.parent / target).resolve() == generated_schema.resolve() for target in link_targets),
            f"exit={code} payload={payload} index={index_after_migrate!r}",
        )
        code, payload = run_json(
            ["compile", "--root", str(substring_schema_store), "--json"]
        )
        check(
            "memory-migrate: repaired substring-only cue passes compile",
            "schema_missing_from_index" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        authored_frame_store = tmp / "authored-frame-conversion"
        authored_frame_store.mkdir()
        (authored_frame_store / "SCHEMA.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "authored-frame-conversion",
                    "structure": {},
                    "compile": {},
                }
            ),
            encoding="utf-8",
        )
        authored_folder = authored_frame_store / "notes"
        write_index(authored_folder)
        write_page(
            authored_folder / "g1.gist.md",
            "gist",
            [{"path": "notes/index.md", "kind": "derived_from"}],
        )
        frame_path = authored_folder / "frame.md"
        frame_body = (
            "\n\n## Authored frame\n\n"
            "The body has original framing and an authored Provenance sentence.\n"
        )
        frame_path.write_text(
            "---\n"
            "type: frame\n"
            'title: "Distinct authored frame"\n'
            'description: "A preserved description."\n'
            "created: 2025-02-03\n"
            "origin: third-party\n"
            "sensitivity: restricted\n"
            'custom_field: "preserve this field"\n'
            "relates_to:\n"
            "  - path: notes/prior.schema.md\n"
            "    kind: follows\n"
            "---"
            f"{frame_body}",
            encoding="utf-8",
        )
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(authored_frame_store),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        converted_path = authored_folder / "schema.schema.md"
        converted_meta, converted_body = read_page(converted_path)
        check(
            "memory-migrate: frame conversion retains metadata, body, and schema coverage",
            code == 0
            and not frame_path.exists()
            and converted_meta.get("type") == "schema"
            and converted_meta.get("title") == "Distinct authored frame"
            and converted_meta.get("description") == "A preserved description."
            and converted_meta.get("created") == "2025-02-03"
            and converted_meta.get("origin") == "third-party"
            and converted_meta.get("sensitivity") == "restricted"
            and converted_meta.get("custom_field") == "preserve this field"
            and converted_body == frame_body
            and {"path": "notes/prior.schema.md", "kind": "follows"} in converted_meta.get("relates_to", [])
            and {"path": "notes/g1.gist.md", "kind": "related"} in converted_meta.get("relates_to", []),
            f"exit={code} payload={payload} meta={converted_meta} body={converted_body!r}",
        )

        long_description = (
            "This long plain description records the original framing without "
            "losing any words when the schema page is created. "
        ) * 5 + "It also preserves Unicode such as café."
        check(
            "description fixture: default YAML width would wrap",
            len(yaml.safe_dump({"description": long_description}, allow_unicode=True).splitlines()) > 1,
        )
        for version in ("1.0", "2.0"):
            store = tmp / f"long-frame-description-{version}"
            store.mkdir()
            (store / "SCHEMA.json").write_text(
                json.dumps({
                    "schema_version": version,
                    "atlas_id": "long-frame-description",
                    "structure": {},
                    "compile": {},
                }),
                encoding="utf-8",
            )
            write_index(store / "notes")
            write_page(store / "notes" / "g1.gist.md", "gist")
            frame = store / "notes" / "frame.md"
            frame.write_text(
                "---\ntype: frame\ntitle: Original frame\n"
                f"description: {long_description}\n---\n\n{PROSE}\n",
                encoding="utf-8",
            )
            original_meta, original_body = read_page(frame, version)
            code, payload = run_json([
                "memory-migrate", "--root", str(store), "--operation", "apply",
                "--batch", "contract-file", "--json",
            ])
            target = store / "notes" / "schema.schema.md"
            meta, body = read_page(target, version) if target.is_file() else ({}, "")
            expected_meta = dict(original_meta)
            expected_meta["type"] = "schema"
            expected_meta["relates_to"] = [{"path": "notes/g1.gist.md", "kind": "related"}]
            check(
                f"memory-migrate: long plain description survives exactly on SCHEMA {version}",
                code == 0
                and original_meta.get("description") == long_description
                and meta == expected_meta
                and body == original_body
                and not frame.exists()
                and not (store / "SCHEMA.json").exists()
                and json.loads((store / "CONTRACT.json").read_text(encoding="utf-8"))["atlas_release"]
                == "0.13.0-beta.7",
                f"exit={code} payload={payload} meta={meta}",
            )

        failing_store = tmp / "unroundtrippable-frame-description"
        failing_store.mkdir()
        failing_contract = failing_store / "SCHEMA.json"
        failing_contract.write_text(
            json.dumps({
                "schema_version": "1.0",
                "atlas_id": "unroundtrippable-frame-description",
                "structure": {},
                "compile": {},
            }),
            encoding="utf-8",
        )
        # An earlier folder must not be written if a later conversion fails.
        write_index(failing_store / "a-first")
        write_page(failing_store / "a-first" / "g1.gist.md", "gist")
        write_index(failing_store / "notes")
        write_page(failing_store / "notes" / "g1.gist.md", "gist")
        failing_frame = failing_store / "notes" / "frame.md"
        failing_description = "Operator's description: retain this exact claim."
        failing_frame.write_text(
            "---\ntype: frame\ntitle: Original frame\n"
            f"description: {failing_description}\n---\n\n{PROSE}\n",
            encoding="utf-8",
        )
        original_hashes = {
            path: sha(path) for path in failing_store.rglob("*") if path.is_file()
        }
        check(
            "description fixture: original reader retains the unroundtrippable description",
            read_page(failing_frame)[0].get("description") == failing_description,
        )
        code, payload = run_json([
            "memory-migrate", "--root", str(failing_store), "--operation", "apply",
            "--batch", "contract-file", "--json",
        ])
        steps = failing_store / "staging" / "memory-migrate-operator-steps.md"
        steps_text = steps.read_text(encoding="utf-8") if steps.is_file() else ""
        check(
            "memory-migrate: unroundtrippable description exits 2 with required finding",
            code == 2
            and payload.get("ok") is False
            and "frame_description_not_round_trippable" in findings_by_id(payload, "findings"),
            f"exit={code} payload={payload}",
        )
        check(
            "memory-migrate: description failure stages verbatim description and next step",
            failing_description in steps_text
            and "make the description a plain scalar the reader round-trips, then re-run "
            "`atlas memory-migrate --operation apply --batch contract-file`" in steps_text,
            steps_text,
        )
        check(
            "memory-migrate: description failure preserves every original byte and path",
            all(path.is_file() and sha(path) == digest for path, digest in original_hashes.items())
            and {path for path in failing_store.rglob("*") if path.is_file()}
            == set(original_hashes) | {steps}
            and not (failing_store / "CONTRACT.json").exists()
            and not list(failing_store.rglob("*.schema.md")),
        )

        unreadable_frame_store = tmp / "unreadable-frame-conversion"
        unreadable_frame_store.mkdir()
        unreadable_contract = unreadable_frame_store / "SCHEMA.json"
        unreadable_contract.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "atlas_id": "unreadable-frame-conversion",
                    "structure": {},
                    "compile": {},
                }
            ),
            encoding="utf-8",
        )
        unreadable_folder = unreadable_frame_store / "notes"
        write_index(unreadable_folder)
        write_page(
            unreadable_folder / "g1.gist.md",
            "gist",
            [{"path": "notes/index.md", "kind": "derived_from"}],
        )
        unreadable_frame = unreadable_folder / "frame.md"
        unreadable_frame.write_text("---\ntype: frame\n", encoding="utf-8")
        unreadable_contract_hash = sha(unreadable_contract)
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(unreadable_frame_store),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        check(
            "memory-migrate: unreadable replacement frame requires manual migration before writes",
            code != 0
            and payload.get("ok") is False
            and any(
                finding.get("id") == "schema_manual_migration"
                and "manual migration is required" in finding.get("msg", "")
                for finding in payload.get("findings", [])
            )
            and sha(unreadable_contract) == unreadable_contract_hash
            and not (unreadable_frame_store / "CONTRACT.json").exists()
            and unreadable_frame.is_file(),
            f"exit={code} payload={payload}",
        )

        remember_text = (ROOT / "references" / "paths" / "remember.md").read_text(
            encoding="utf-8"
        ).lower()
        check(
            "remember: schema cue critical is an index-only exit-2 first-pass exception",
            "schema_missing_from_index" in remember_text
            and "index-only" in remember_text
            and "including exit 2" in remember_text
            and "waiting for exit 0 first deadlocks the required schema cue" in remember_text
            and "if any critical finding id is not `schema_missing_from_index`" in remember_text
            and "do **not** edit `index.md` yet" in remember_text,
            "step 9 does not describe the exit-2 schema-cue exception and non-index critical refusal",
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
        # Full beta.2 init (templates plus types.recommended including frame, no
        # atlas_release, no memory key) that already has a beta.2 content page.
        # An empty store of this contract shape is eligible; content keeps the
        # in_beta_not_legacy refusal.
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
        write_page(unstamped / "episode.md", "page")
        unstamped_before = sha(unstamped_schema_path)
        unstamped_page_before = sha(unstamped / "episode.md")
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
            and sha(unstamped / "episode.md") == unstamped_page_before
            and not (unstamped / "CONTRACT.json").exists(),
        )

        # === empty-beta2-init-eligible ===========================================
        # Unstamped full beta.2 init shaped like a real SCHEMA.json: templates
        # for frame/gist/page, types.recommended containing frame and page, no
        # atlas_release, no memory key, and no frame/gist/page/memory content.
        def beta2_type_block(type_name: str, required: list[str] | None = None) -> dict:
            return {
                "file": f"templates/{type_name}.md",
                "frontmatter": {
                    "required": required or ["type", "title", "created"],
                    "recommended": [],
                },
                "sections": {"required": [], "recommended": []},
            }

        empty_beta2 = tmp / "empty-beta2-init"
        empty_beta2.mkdir(parents=True)
        vendor_block = {
            "file": "templates/vendor.md",
            "frontmatter": {
                "required": ["type", "title", "created", "vendor_id"],
                "recommended": ["region"],
            },
            "sections": {"required": ["Terms"], "recommended": []},
        }
        experience_block = beta2_type_block(
            "experience", ["type", "title", "created", "work_id"]
        )
        empty_contract = {
            "schema_version": "1.0",
            "atlas_id": "atlas.example/master/atlas",
            "title": "Master Atlas",
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
                "simplicity_budget": {
                    "max_required_frontmatter_keys_per_type": 8,
                    "max_required_sections_per_type": 6,
                },
                "page_contract": {
                    "when_work_id": {"require_kind": "implements"},
                    "when_type": {"protostar": {"require_kind": "derived_from"}},
                    "forming_requires_type": "protostar",
                },
            },
            "templates": {
                "directory": "templates/",
                "by_type": {
                    "experience": experience_block,
                    "decision": beta2_type_block("decision"),
                    "work": beta2_type_block("work", ["type", "title", "created", "work_id"]),
                    "document": beta2_type_block("document"),
                    "protostar": beta2_type_block("protostar"),
                    "lesson": beta2_type_block("lesson"),
                    "recipe": beta2_type_block("recipe"),
                    "page": beta2_type_block("page"),
                    "gist": beta2_type_block("gist"),
                    "frame": beta2_type_block("frame"),
                    "vendor": vendor_block,
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
                    "vendor",
                ],
                "unconstrained": ["scratch", "frame"],
            },
            "query": {
                "default_mode": "local",
                "search_engine": "grep",
                "fallback": "rg",
                "staging_visible": False,
            },
        }
        empty_schema_path = empty_beta2 / "SCHEMA.json"
        empty_schema_path.write_text(json.dumps(empty_contract, indent=2) + "\n", encoding="utf-8")
        tmpl = empty_beta2 / "templates"
        tmpl.mkdir()
        (tmpl / "frame.md").write_text("beta2 frame template\n", encoding="utf-8")
        (tmpl / "page.md").write_text("beta2 page template\n", encoding="utf-8")
        (tmpl / "gist.md").write_text("kept gist template\n", encoding="utf-8")
        (tmpl / "experience.md").write_text("custom experience template\n", encoding="utf-8")
        (tmpl / "vendor.md").write_text("custom vendor template\n", encoding="utf-8")
        (empty_beta2 / "index.md").write_text("# Master Atlas\n\n- items\n", encoding="utf-8")
        (empty_beta2 / "log.md").write_text("# Log\n\n- init\n", encoding="utf-8")
        write_page(empty_beta2 / "choice.md", "decision")
        preserved_paths = [
            empty_beta2 / "choice.md",
            empty_beta2 / "index.md",
            empty_beta2 / "log.md",
            tmpl / "gist.md",
            tmpl / "experience.md",
            tmpl / "vendor.md",
        ]
        preserved_hashes = {path: sha(path) for path in preserved_paths}
        schema_before = sha(empty_schema_path)
        code, payload = run_json(
            ["memory-migrate", "--root", str(empty_beta2), "--operation", "assess", "--json"]
        )
        check(
            "empty-beta2-init: assess reports lineage empty-beta2-init and eligible",
            code == 0
            and payload.get("ok") is True
            and payload.get("lineage") == "empty-beta2-init"
            and payload.get("contract_file_eligible") is True
            and payload.get("beta_content_pages") == []
            and not (empty_beta2 / "CONTRACT.json").exists(),
            f"exit={code} payload={payload}",
        )
        check(
            "empty-beta2-init: assess writes nothing",
            sha(empty_schema_path) == schema_before
            and all(sha(path) == digest for path, digest in preserved_hashes.items())
            and (tmpl / "frame.md").is_file()
            and (tmpl / "page.md").is_file(),
        )
        code, payload = run_json(
            ["memory-migrate", "--root", str(empty_beta2), "--operation", "inventory", "--json"]
        )
        check(
            "empty-beta2-init: inventory reports the same eligibility and writes nothing",
            code == 0
            and payload.get("lineage") == "empty-beta2-init"
            and payload.get("contract_file_eligible") is True
            and sha(empty_schema_path) == schema_before
            and not (empty_beta2 / "CONTRACT.json").exists(),
            f"exit={code} payload={payload}",
        )
        code, payload = run_json(
            ["memory-migrate", "--root", str(empty_beta2), "--operation", "apply", "--json"]
        )
        check(
            "empty-beta2-init: apply without batch refuses and writes nothing",
            code == 2
            and "batch_required" in findings_by_id(payload, "findings")
            and sha(empty_schema_path) == schema_before
            and not (empty_beta2 / "CONTRACT.json").exists()
            and (tmpl / "frame.md").is_file(),
            f"exit={code} payload={payload}",
        )
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(empty_beta2),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        check(
            "empty-beta2-init: apply renames SCHEMA.json to CONTRACT.json",
            code == 0
            and payload.get("ok") is True
            and payload.get("lineage") == "current"
            and payload.get("contract_file") == "CONTRACT.json"
            and (empty_beta2 / "CONTRACT.json").is_file()
            and not empty_schema_path.exists(),
            f"exit={code} payload={payload}",
        )
        migrated = json.loads((empty_beta2 / "CONTRACT.json").read_text(encoding="utf-8"))
        check(
            "empty-beta2-init: migrated store stamps beta.7 layers schema/gist/memory",
            migrated.get("atlas_release") == "0.13.0-beta.7"
            and migrated.get("memory", {}).get("layers") == ["schema", "gist", "memory"],
            str(migrated.get("atlas_release")),
        )
        check(
            "empty-beta2-init: store-specific settings are preserved",
            migrated.get("atlas_id") == empty_contract["atlas_id"]
            and migrated.get("title") == empty_contract["title"]
            and migrated.get("structure") == empty_contract["structure"]
            and migrated.get("compile") == empty_contract["compile"]
            and migrated.get("query") == empty_contract["query"],
            str({k: migrated.get(k) for k in ("atlas_id", "title", "structure", "compile", "query")}),
        )
        check(
            "empty-beta2-init: recommended types drop frame/page and gain schema/memory",
            migrated.get("types", {}).get("recommended") == [
                "experience",
                "decision",
                "lesson",
                "recipe",
                "work",
                "protostar",
                "gist",
                "schema",
                "memory",
                "vendor",
            ]
            and migrated.get("types", {}).get("unconstrained") == ["scratch"],
            str(migrated.get("types")),
        )
        by_type = migrated.get("templates", {}).get("by_type", {})
        check(
            "empty-beta2-init: by_type drops frame/page, keeps custom blocks, adds init schema/memory",
            "frame" not in by_type
            and "page" not in by_type
            and by_type.get("experience") == experience_block
            and by_type.get("vendor") == vendor_block
            and by_type.get("document") == beta2_type_block("document")
            and by_type.get("schema", {}).get("frontmatter", {}).get("required") == [
                "type",
                "title",
                "created",
            ]
            and by_type.get("memory", {}).get("file") == "templates/memory.md"
            and by_type.get("gist", {}).get("file") == "templates/gist.md",
            str(sorted(by_type)),
        )
        package_templates = ROOT / "references" / "templates"
        check(
            "empty-beta2-init: frame/page template files are removed and schema/memory match init",
            not (tmpl / "frame.md").exists()
            and not (tmpl / "page.md").exists()
            and (tmpl / "schema.md").read_bytes() == (package_templates / "schema.md").read_bytes()
            and (tmpl / "memory.md").read_bytes() == (package_templates / "memory.md").read_bytes(),
        )
        check(
            "empty-beta2-init: content pages and custom templates are byte-identical",
            all(sha(path) == digest for path, digest in preserved_hashes.items()),
        )
        code, payload = run_json(["compile", "--root", str(empty_beta2), "--json"])
        check(
            "empty-beta2-init: compile is green after apply",
            code == 0 and payload.get("ok") is True and not payload.get("critical"),
            f"exit={code} critical={payload.get('critical')} warnings={payload.get('warnings')}",
        )

        for content_type in ("frame", "gist", "page", "memory"):
            bearing = tmp / f"beta2-content-{content_type}"
            bearing.mkdir()
            (bearing / "SCHEMA.json").write_text(
                json.dumps(empty_contract, indent=2) + "\n", encoding="utf-8"
            )
            write_page(bearing / "episode.md", content_type)
            before = {
                path.relative_to(bearing): sha(path)
                for path in bearing.rglob("*")
                if path.is_file()
            }
            code, payload = run_json(
                [
                    "memory-migrate",
                    "--root",
                    str(bearing),
                    "--operation",
                    "assess",
                    "--json",
                ]
            )
            check(
                f"beta2-content-{content_type}: assess stays in-beta and ineligible",
                code == 0
                and payload.get("lineage") == "in-beta"
                and payload.get("contract_file_eligible") is False
                and payload.get("beta_content_pages") == ["episode.md"],
                f"exit={code} payload={payload}",
            )
            code, payload = run_json(
                [
                    "memory-migrate",
                    "--root",
                    str(bearing),
                    "--operation",
                    "apply",
                    "--batch",
                    "contract-file",
                    "--json",
                ]
            )
            after = {
                path.relative_to(bearing): sha(path)
                for path in bearing.rglob("*")
                if path.is_file()
            }
            check(
                f"beta2-content-{content_type}: apply refuses with in_beta_not_legacy and no writes",
                code != 0
                and "in_beta_not_legacy" in [f.get("id") for f in payload.get("findings", [])]
                and after == before
                and not (bearing / "CONTRACT.json").exists(),
                f"exit={code} payload={payload}",
            )

        for label, extra in (
            ("stamped-beta", {"atlas_release": "0.13.0-beta"}),
            ("stamped-beta2", {"atlas_release": "0.13.0-beta.2"}),
            ("layers-page", {"memory": {"layers": ["frame", "gist", "page"]}}),
            ("layers-memory", {"memory": {"layers": ["frame", "gist", "memory"]}}),
        ):
            refused = tmp / f"beta2-still-refused-{label}"
            refused.mkdir()
            stamped_contract = dict(empty_contract)
            stamped_contract.update(extra)
            (refused / "SCHEMA.json").write_text(
                json.dumps(stamped_contract, indent=2) + "\n", encoding="utf-8"
            )
            before_hash = sha(refused / "SCHEMA.json")
            code, payload = run_json(
                [
                    "memory-migrate",
                    "--root",
                    str(refused),
                    "--operation",
                    "apply",
                    "--batch",
                    "contract-file",
                    "--json",
                ]
            )
            check(
                f"beta2-still-refused-{label}: in_beta_not_legacy and bytes unchanged",
                code != 0
                and payload.get("lineage") == "in-beta"
                and "in_beta_not_legacy" in [f.get("id") for f in payload.get("findings", [])]
                and sha(refused / "SCHEMA.json") == before_hash
                and not (refused / "CONTRACT.json").exists(),
                f"exit={code} payload={payload}",
            )

        ambiguous = tmp / "beta2-non-string-type"
        ambiguous.mkdir()
        ambiguous_contract = dict(empty_contract)
        ambiguous_contract["schema_version"] = "2.0"
        (ambiguous / "SCHEMA.json").write_text(
            json.dumps(ambiguous_contract, indent=2) + "\n", encoding="utf-8"
        )
        (ambiguous / "odd.md").write_text(
            "---\ntype:\n  - frame\ntitle: t\ncreated: 2026-10-04\n---\n\n" + PROSE + "\n",
            encoding="utf-8",
        )
        ambiguous_before = sha(ambiguous / "SCHEMA.json")
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(ambiguous),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        check(
            "beta2-ambiguous-type: non-string type fails closed with no writes",
            code != 0
            and "beta2_content_ambiguous" in [f.get("id") for f in payload.get("findings", [])]
            and sha(ambiguous / "SCHEMA.json") == ambiguous_before
            and not (ambiguous / "CONTRACT.json").exists(),
            f"exit={code} payload={payload}",
        )

        linked = tmp / "beta2-template-symlink"
        linked.mkdir()
        (linked / "SCHEMA.json").write_text(
            json.dumps(empty_contract, indent=2) + "\n", encoding="utf-8"
        )
        link_tmpl = linked / "templates"
        link_tmpl.mkdir()
        outside_template = tmp / "outside-frame-template.md"
        outside_template.write_text("do not follow\n", encoding="utf-8")
        (link_tmpl / "frame.md").symlink_to(outside_template)
        linked_before = sha(linked / "SCHEMA.json")
        code, payload = run_json(
            [
                "memory-migrate",
                "--root",
                str(linked),
                "--operation",
                "apply",
                "--batch",
                "contract-file",
                "--json",
            ]
        )
        check(
            "beta2-template-symlink: frame.md symlink fails closed and the target is untouched",
            code != 0
            and "beta2_contract_ambiguous" in [f.get("id") for f in payload.get("findings", [])]
            and sha(linked / "SCHEMA.json") == linked_before
            and not (linked / "CONTRACT.json").exists()
            and (link_tmpl / "frame.md").is_symlink()
            and outside_template.read_text(encoding="utf-8") == "do not follow\n",
            f"exit={code} payload={payload}",
        )

        # === current-shape schema coverage ======================================
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
            "schema coverage: one gist + one schema accepted",
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
            "schema coverage: two gists + one schema accepted",
            code == 0 and "schema_folder" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # A schema-only folder is allowed by compile.
        d = beta3_store("folder-zero-gist-schema")
        write_index(d / "notes")
        write_page(d / "notes" / "s1.md", "schema")
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "schema-folder: zero gists + a schema accepted",
            code == 0 and "schema_folder" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # Multiple schemas in a folder are allowed when the gist is covered.
        d = beta3_store("folder-two-schema")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(d / "notes" / "s1.md", "schema", [{"path": "notes/g1.md", "kind": "related"}])
        write_page(d / "notes" / "s2.md", "schema", [{"path": "notes/g1.md", "kind": "related"}])
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "schema-folder: two schemas in a gist-bearing folder accepted",
            code == 0 and "schema_folder" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # one gist, no schema -> rejected
        d = beta3_store("folder-one-gist-no-schema")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "schema coverage: one gist, no schema rejected",
            code != 0 and "schema_folder" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # Duplicate listing is harmless as long as every gist is covered.
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
            "schema-folder: uncovered gist still fails despite duplicate listing",
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
            "schema coverage: schema omitting a folder gist rejected",
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
            "schema coverage: cross-folder links do not cover local gists",
            code != 0
            and "alpha/g1.md" in schema_folder_paths
            and "beta/g2.md" in schema_folder_paths,
            f"exit={code} critical={payload.get('critical')}",
        )

        # Every schema needs a local index cue; text elsewhere is not a cue.
        d = beta3_store("schema-missing-index-cue")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.gist.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(d / "notes" / "subject.schema.md", "schema", [{"path": "notes/g1.gist.md", "kind": "related"}])
        (d / "notes" / "index.md").write_text("# Notes\n\n- items\n", encoding="utf-8")
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "schema_missing_from_index: uncued schema fails",
            code != 0 and "schema_missing_from_index" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # A schema-only folder is allowed, but distinct schemas can own separate
        # gists in one folder and both must be cued from its index.
        d = beta3_store("folder-two-schemas-two-gists")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.gist.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(d / "notes" / "g2.gist.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(d / "notes" / "s1.schema.md", "schema", [{"path": "notes/g1.gist.md", "kind": "related"}])
        write_page(d / "notes" / "s2.schema.md", "schema", [{"path": "notes/g2.gist.md", "kind": "related"}])
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "schema-folder: two schemas each cover their own gist and are indexed",
            code == 0
            and "schema_folder" not in findings_by_id(payload, "critical")
            and "schema_missing_from_index" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # A non-empty gist description must be an exact substring of its memory
        # parent. N>1 shared gists pass when at least one derived_from parent
        # still contains that substring.
        d = beta3_store("stale-upper-page")
        write_index(d / "notes")
        write_page(d / "notes" / "memory.memory.md", "memory", body="The underlying claim was changed.")
        write_page(
            d / "notes" / "g1.gist.md",
            "gist",
            [{"path": "notes/memory.memory.md", "kind": "derived_from"}],
            description="The old exact claim",
        )
        write_page(d / "notes" / "s.schema.md", "schema", [{"path": "notes/g1.gist.md", "kind": "related"}])
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "stale_upper_page: changed memory claim fails exact description check",
            code != 0 and "stale_upper_page" in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )
        (d / "notes" / "memory.memory.md").write_text(
            "---\ntype: memory\ntitle: t\ncreated: 2026-10-04\n---\n\n"
            "The old exact claim remains present in this memory body.\n",
            encoding="utf-8",
        )
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "stale_upper_page: exact claim in memory body passes",
            code == 0 and "stale_upper_page" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )

        # Shared gist: union membership. The description may live in only one parent.
        d = beta3_store("stale-upper-page-shared")
        write_index(d / "notes")
        claim = "The shared exact claim lives in one parent only."
        write_page(
            d / "notes" / "left.memory.md",
            "memory",
            body="Left parent has other wording entirely. " + PROSE,
        )
        write_page(d / "notes" / "right.memory.md", "memory", body=claim + " " + PROSE)
        write_page(
            d / "notes" / "shared.gist.md",
            "gist",
            [
                {"path": "notes/left.memory.md", "kind": "derived_from"},
                {"path": "notes/right.memory.md", "kind": "derived_from"},
            ],
            description=claim,
        )
        write_page(d / "notes" / "s.schema.md", "schema", [{"path": "notes/shared.gist.md", "kind": "related"}])
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "stale_upper_page: N>1 passes when one parent still holds the description",
            code == 0 and "stale_upper_page" not in findings_by_id(payload, "critical"),
            f"exit={code} critical={payload.get('critical')}",
        )
        (d / "notes" / "right.memory.md").write_text(
            "---\ntype: memory\ntitle: t\ncreated: 2026-10-04\n---\n\n"
            "Neither parent keeps the old shared wording.\n" + PROSE + "\n",
            encoding="utf-8",
        )
        code, payload = run_json(["compile", "--root", str(d), "--json"])
        check(
            "stale_upper_page: N>1 fails when no derived_from parent holds the description",
            code != 0 and "stale_upper_page" in findings_by_id(payload, "critical"),
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

        # === focused-compile-keeps-own-folder-gist-coverage-in-scope ============
        # A --path focus on a gist that IS a member of a gist-bearing folder
        # must keep that folder's schema_folder invariant in scope. An
        # unrelated folder must still stay out of scope.

        # Missing-schema finding is reported on the uncovered gist.
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
            ["compile", "--root", str(d), "--type", "schema", "--json"]
        )
        check(
            "focused-compile --type schema: includes uncovered-gist schema requirement",
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

        # An uncovered gist in notes/ stays in scope; the separate folder is excluded.
        d = beta3_store("folder-focus-own-folder-membership-error")
        write_index(d / "notes")
        write_page(d / "notes" / "g1.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        write_page(d / "notes" / "g2.md", "gist", [{"path": "notes/index.md", "kind": "derived_from"}])
        # schema omits g2 -> finding reported on notes/g2.md.
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
        # "0.13.0-beta.3" stamp (not the "0.13.0-beta.7" stamp init/apply now
        # write) with layers schema/gist/memory must still read as "current":
        # compile succeeds, memory-migrate assess reports lineage current, and
        # apply is a no-op that never rewrites the stamp to beta.7.
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
            "beta3-contract-still-current: apply does not rewrite the stamp to beta.7",
            sha(beta3_reader / "CONTRACT.json") == before_beta3_hash,
        )
        for stamp in ("0.13.0-beta.3", "0.13.0-beta.4", "0.13.0-beta.7"):
            contract = json.loads((beta3_reader / "CONTRACT.json").read_text(encoding="utf-8"))
            contract["atlas_release"] = stamp
            (beta3_reader / "CONTRACT.json").write_text(json.dumps(contract), encoding="utf-8")
            current_hashes = {
                path: sha(path) for path in beta3_reader.rglob("*") if path.is_file()
            }
            shape, error = compute_stamp_shape("CONTRACT.json", contract)
            check(
                f"current reader: {stamp} stamp and lineage agree",
                shape == "current" and error is None
                and classify_lineage("CONTRACT.json", contract) == "current",
                f"shape={shape} error={error}",
            )
            code, payload = run_json(["compile", "--root", str(beta3_reader), "--json", "--dry-run"])
            check(f"current reader: {stamp} compiles", code == 0, str(payload))
            code, payload = run_json([
                "memory-migrate", "--root", str(beta3_reader), "--operation", "apply",
                "--batch", "contract-file", "--json",
            ])
            check(
                f"current reader: apply on {stamp} is a zero-write no-op",
                code == 0 and payload.get("lineage") == "current"
                and {path for path in beta3_reader.rglob("*") if path.is_file()} == set(current_hashes)
                and all(sha(path) == digest for path, digest in current_hashes.items()),
                str(payload),
            )
            shape, error = compute_stamp_shape("SCHEMA.json", contract)
            check(
                f"current reader: SCHEMA.json refuses {stamp}",
                shape is None and error is not None,
                f"shape={shape} error={error}",
            )
        for stamp in ("0.13.0-beta.6", "0.13.0-beta.999"):
            contract["atlas_release"] = stamp
            for filename in ("SCHEMA.json", "CONTRACT.json"):
                shape, error = compute_stamp_shape(filename, contract)
                check(
                    f"unknown reader: {filename} refuses {stamp}",
                    shape is None and error is not None
                    and classify_lineage(filename, contract) != "current",
                    f"shape={shape} error={error}",
                )
            (beta3_reader / "CONTRACT.json").write_text(json.dumps(contract), encoding="utf-8")
            before_hash = sha(beta3_reader / "CONTRACT.json")
            code, payload = run_json(["compile", "--root", str(beta3_reader), "--json", "--dry-run"])
            check(
                f"unknown reader: {stamp} compile fails closed",
                code == 2 and "stamp_shape" in findings_by_id(payload, "critical"),
                str(payload),
            )
            code, payload = run_json([
                "memory-migrate", "--root", str(beta3_reader), "--operation", "apply",
                "--batch", "contract-file", "--json",
            ])
            check(
                f"unknown reader: apply refuses {stamp} without restamping",
                code == 2 and sha(beta3_reader / "CONTRACT.json") == before_hash,
                str(payload),
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
