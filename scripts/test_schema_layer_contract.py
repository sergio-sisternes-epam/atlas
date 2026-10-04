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
            "pre-beta-eligible: migrated store stamps atlas_release/memory.layers beta.3",
            migrated.get("atlas_release") == "0.13.0-beta.3"
            and migrated.get("memory", {}).get("layers") == ["schema", "gist", "memory"],
            str(migrated),
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
