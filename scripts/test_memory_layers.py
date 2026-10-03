#!/usr/bin/env python3
"""Memory layers (page/gist/frame) regressions. Run: python3 scripts/test_memory_layers.py"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"


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


PROSE = (
    "This page carries enough non-link prose content to pass the "
    "not_just_links body length check used across the test fixtures."
)


def write_page(path: Path, type_name: str, title: str, created: str, relates_to=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rel_lines = ""
    if relates_to:
        rel_lines = "relates_to:\n" + "".join(
            f"  - path: {item['path']}\n    kind: {item['kind']}\n" for item in relates_to
        )
    else:
        rel_lines = "relates_to: []\n"
    path.write_text(
        "---\n"
        f"type: {type_name}\n"
        f"title: {title}\n"
        f"created: {created}\n"
        f"{rel_lines}"
        "---\n\n"
        "## Content\n\n"
        f"{PROSE}\n",
        encoding="utf-8",
    )


def write_index(folder: Path, label: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.md").write_text(f"# {label}\n\n- items\n", encoding="utf-8")


def findings_by_id(payload: dict, bucket: str) -> list[str]:
    return [i.get("id") for i in payload.get(bucket, [])]


def main() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        status = "PASS" if condition else "FAIL"
        print(f"[{status}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    tmp = Path(tempfile.mkdtemp(prefix="atlas-memory-layers-"))
    try:
        # --- Fixture 1: default rung, a legacy document with no gist ---
        store1 = tmp / "store1"
        init = run(["init", "--root", str(store1), "--json"])
        check("init store1", init.returncode == 0, init.stderr)

        write_page(
            store1 / "notes" / "legacy.md",
            "document",
            "Legacy note",
            "2026-10-01",
        )
        write_index(store1 / "notes", "Notes")

        code, payload = run_json(["compile", "--root", str(store1), "--json"])
        check("default rung exit 0", code == 0, f"exit={code} critical={payload.get('critical')}")
        info_ids = findings_by_id(payload, "info")
        check(
            "legacy_document and missing_gist are info by default",
            "legacy_document" in info_ids and "missing_gist" in info_ids,
            f"info={info_ids}",
        )
        check(
            "legacy_document/missing_gist not in warnings",
            "legacy_document" not in findings_by_id(payload, "warnings")
            and "missing_gist" not in findings_by_id(payload, "warnings"),
        )
        check(
            "legacy_document/missing_gist not in critical",
            "legacy_document" not in findings_by_id(payload, "critical")
            and "missing_gist" not in findings_by_id(payload, "critical"),
        )
        for item in payload.get("info", []):
            if item.get("id") in ("legacy_document", "missing_gist"):
                check(
                    f"{item['id']} severity is info",
                    item.get("severity") == "info",
                    str(item),
                )

        # --- schema memory-rung --set warn ---
        rung_code, rung_payload = run_json(
            ["schema", "memory-rung", "--set", "warn", "--root", str(store1), "--json"]
        )
        check("schema memory-rung --set warn ok", rung_code == 0 and rung_payload.get("ok"))
        schema_doc = json.loads((store1 / "SCHEMA.json").read_text(encoding="utf-8"))
        check(
            "SCHEMA.memory.rung == warn after --set warn",
            schema_doc.get("memory", {}).get("rung") == "warn",
            str(schema_doc.get("memory")),
        )
        legacy_meta_before = (store1 / "notes" / "legacy.md").read_text(encoding="utf-8")
        check(
            "schema memory-rung does not retype pages",
            "type: document" in legacy_meta_before,
        )

        code, payload = run_json(["compile", "--root", str(store1), "--json"])
        check("warn rung exits 1", code == 1, f"exit={code}")
        warn_ids = findings_by_id(payload, "warnings")
        check(
            "legacy_document/missing_gist in warnings at warn rung",
            "legacy_document" in warn_ids and "missing_gist" in warn_ids,
            f"warnings={warn_ids}",
        )
        for item in payload.get("warnings", []):
            if item.get("id") in ("legacy_document", "missing_gist"):
                check(f"{item['id']} severity is warning", item.get("severity") == "warning")
        check(
            "info empty of legacy_document/missing_gist at warn rung",
            "legacy_document" not in findings_by_id(payload, "info")
            and "missing_gist" not in findings_by_id(payload, "info"),
        )

        # --- schema memory-rung --set error ---
        code, _ = run_json(
            ["schema", "memory-rung", "--set", "error", "--root", str(store1), "--json"]
        )
        check("schema memory-rung --set error ok", code == 0)
        code, payload = run_json(["compile", "--root", str(store1), "--json"])
        check("error rung exits 2", code == 2, f"exit={code}")
        crit_ids = findings_by_id(payload, "critical")
        check(
            "legacy_document/missing_gist in critical at error rung",
            "legacy_document" in crit_ids and "missing_gist" in crit_ids,
            f"critical={crit_ids}",
        )
        for item in payload.get("critical", []):
            if item.get("id") in ("legacy_document", "missing_gist"):
                check(f"{item['id']} severity is critical", item.get("severity") == "critical")

        # --- Fixture 2: fresh init confirms absent rung behaves as info ---
        store2 = tmp / "store2"
        init2 = run(["init", "--root", str(store2), "--json"])
        check("init store2", init2.returncode == 0, init2.stderr)
        write_page(store2 / "legacy2.md", "document", "Legacy 2", "2026-10-01")
        code, payload = run_json(["compile", "--root", str(store2), "--json"])
        check("fresh store absent memory key exits 0", code == 0, f"exit={code}")
        check(
            "fresh store info has legacy findings",
            "legacy_document" in findings_by_id(payload, "info"),
        )
        schema2 = json.loads((store2 / "SCHEMA.json").read_text(encoding="utf-8"))
        check("fresh store has no memory key", "memory" not in schema2)
        check(
            "fresh store types.recommended excludes document",
            "document" not in schema2.get("types", {}).get("recommended", []),
            str(schema2.get("types", {}).get("recommended")),
        )
        check(
            "fresh store templates.by_type still has document",
            "document" in schema2.get("templates", {}).get("by_type", {}),
        )
        check(
            "fresh store copied templates/document.md",
            (store2 / "templates" / "document.md").is_file(),
        )

        # --- Fixture 3: gist parent cardinality ---
        store3 = tmp / "store3"
        run(["init", "--root", str(store3), "--json"])
        write_index(store3 / "concepts", "Concepts")
        write_page(
            store3 / "concepts" / "parent.md",
            "decision",
            "Parent experience",
            "2026-10-01",
        )
        write_page(
            store3 / "concepts" / "parent2.md",
            "decision",
            "Second parent",
            "2026-10-01",
        )
        write_page(
            store3 / "concepts" / "good_gist.md",
            "gist",
            "Good gist",
            "2026-10-01",
            relates_to=[{"path": "concepts/parent.md", "kind": "derived_from"}],
        )
        write_page(
            store3 / "concepts" / "zero_parent_gist.md",
            "gist",
            "Zero parent gist",
            "2026-10-01",
        )
        write_page(
            store3 / "concepts" / "two_parent_gist.md",
            "gist",
            "Two parent gist",
            "2026-10-01",
            relates_to=[
                {"path": "concepts/parent.md", "kind": "derived_from"},
                {"path": "concepts/parent2.md", "kind": "derived_from"},
            ],
        )
        write_page(
            store3 / "concepts" / "gist_of_gist.md",
            "gist",
            "Gist of gist",
            "2026-10-01",
            relates_to=[{"path": "concepts/good_gist.md", "kind": "derived_from"}],
        )
        code, payload = run_json(["compile", "--root", str(store3), "--json"])
        check("gist fixture exits 0 at default info rung", code == 0, f"exit={code}")
        info_paths = {
            (i.get("id"), i.get("path")) for i in payload.get("info", [])
        }
        check(
            "zero-parent gist flagged gist_parent (info)",
            ("gist_parent", "concepts/zero_parent_gist.md") in info_paths,
            str(info_paths),
        )
        check(
            "two-parent gist flagged gist_parent (info)",
            ("gist_parent", "concepts/two_parent_gist.md") in info_paths,
        )
        check(
            "gist-of-gist flagged gist_parent (info)",
            ("gist_parent", "concepts/gist_of_gist.md") in info_paths,
        )
        check(
            "good gist not flagged gist_parent",
            ("gist_parent", "concepts/good_gist.md") not in info_paths,
        )

        # --- Fixture 4: frame members ---
        store4 = tmp / "store4"
        run(["init", "--root", str(store4), "--json"])
        write_index(store4 / "concepts", "Concepts")
        write_page(
            store4 / "concepts" / "parent.md",
            "decision",
            "Frame parent",
            "2026-10-01",
        )
        write_page(
            store4 / "concepts" / "g1.md",
            "gist",
            "Gist one",
            "2026-10-01",
            relates_to=[{"path": "concepts/parent.md", "kind": "derived_from"}],
        )
        write_page(
            store4 / "concepts" / "g2.md",
            "gist",
            "Gist two",
            "2026-10-01",
            relates_to=[{"path": "concepts/parent.md", "kind": "derived_from"}],
        )
        write_page(
            store4 / "concepts" / "thin_frame.md",
            "frame",
            "Thin frame",
            "2026-10-01",
            relates_to=[{"path": "concepts/g1.md", "kind": "related"}],
        )
        write_page(
            store4 / "concepts" / "good_frame.md",
            "frame",
            "Good frame",
            "2026-10-01",
            relates_to=[
                {"path": "concepts/g1.md", "kind": "related"},
                {"path": "concepts/g2.md", "kind": "related"},
            ],
        )
        write_page(
            store4 / "concepts" / "duplicate_frame.md",
            "frame",
            "Duplicate gist frame",
            "2026-10-01",
            relates_to=[
                {"path": "concepts/g1.md", "kind": "related"},
                {"path": "concepts/g1.md", "kind": "related"},
            ],
        )
        write_page(
            store4 / "concepts" / "page_member.md",
            "page",
            "A plain page",
            "2026-10-01",
        )
        write_page(
            store4 / "concepts" / "mixed_frame.md",
            "frame",
            "Mixed gist+page frame",
            "2026-10-01",
            relates_to=[
                {"path": "concepts/g1.md", "kind": "related"},
                {"path": "concepts/g2.md", "kind": "related"},
                {"path": "concepts/page_member.md", "kind": "related"},
            ],
        )
        code, payload = run_json(["compile", "--root", str(store4), "--json"])
        check("frame fixture exits 0 at default info rung", code == 0, f"exit={code}")
        info_paths4 = {(i.get("id"), i.get("path")) for i in payload.get("info", [])}
        check(
            "thin frame (one gist) flagged frame_members (info, not a failure)",
            ("frame_members", "concepts/thin_frame.md") in info_paths4,
            str(info_paths4),
        )
        check(
            "good frame (two gists) not flagged frame_members",
            ("frame_members", "concepts/good_frame.md") not in info_paths4,
        )
        check(
            "duplicate-gist frame (same gist twice) flagged frame_members",
            ("frame_members", "concepts/duplicate_frame.md") in info_paths4,
            str(info_paths4),
        )
        check(
            "mixed gist+page frame flagged frame_members",
            ("frame_members", "concepts/mixed_frame.md") in info_paths4,
            str(info_paths4),
        )
        check(
            "parent page with a gist is not flagged missing_gist",
            ("missing_gist", "concepts/parent.md") not in info_paths4,
        )
        check(
            "no gists/ directory required",
            not (store4 / "gists").exists(),
        )
        check(
            "no frames/ directory required",
            not (store4 / "frames").exists(),
        )

        # --- Fixture 5: protostar with no gist produces no missing_gist ---
        store5 = tmp / "store5"
        run(["init", "--root", str(store5), "--json"])
        write_page(
            store5 / "origin.md",
            "decision",
            "Origin decision",
            "2026-10-01",
        )
        write_page(
            store5 / "proto.md",
            "protostar",
            "Forming idea",
            "2026-10-01",
            relates_to=[{"path": "origin.md", "kind": "derived_from"}],
        )
        code, payload = run_json(["compile", "--root", str(store5), "--json"])
        check("protostar fixture exits 0", code == 0, f"exit={code}")
        all_ids_paths = {
            (i.get("id"), i.get("path"))
            for bucket in ("info", "warnings", "critical")
            for i in payload.get(bucket, [])
        }
        check(
            "protostar without a gist has no missing_gist finding",
            ("missing_gist", "proto.md") not in all_ids_paths,
            str(all_ids_paths),
        )

        # --- Fixture 6: relates_to targets normalized to canonical page keys ---
        store6 = tmp / "store6"
        run(["init", "--root", str(store6), "--json"])
        write_index(store6 / "concepts", "Concepts")
        write_page(
            store6 / "concepts" / "parent.md",
            "decision",
            "Dotted parent",
            "2026-10-01",
        )
        write_page(
            store6 / "concepts" / "g1.md",
            "gist",
            "Gist one (dotted parent)",
            "2026-10-01",
            relates_to=[{"path": "./concepts/parent.md", "kind": "derived_from"}],
        )
        write_page(
            store6 / "concepts" / "g2.md",
            "gist",
            "Gist two (dotted parent)",
            "2026-10-01",
            relates_to=[{"path": "./concepts/parent.md", "kind": "derived_from"}],
        )
        write_page(
            store6 / "concepts" / "dotted_frame.md",
            "frame",
            "Dotted frame",
            "2026-10-01",
            relates_to=[
                {"path": "./concepts/g1.md", "kind": "related"},
                {"path": "./concepts/g2.md", "kind": "related"},
            ],
        )
        write_page(
            store6 / "concepts" / "outside_gist.md",
            "gist",
            "Gist with unresolved parent",
            "2026-10-01",
            relates_to=[{"path": "../outside/nope.md", "kind": "derived_from"}],
        )
        code, payload = run_json(["compile", "--root", str(store6), "--json"])
        info_paths6 = {(i.get("id"), i.get("path")) for i in payload.get("info", [])}
        check(
            "dotted-path parent with a gist is not flagged missing_gist",
            ("missing_gist", "concepts/parent.md") not in info_paths6,
            str(info_paths6),
        )
        check(
            "gist with dotted-path parent is not flagged gist_parent",
            ("gist_parent", "concepts/g1.md") not in info_paths6
            and ("gist_parent", "concepts/g2.md") not in info_paths6,
            str(info_paths6),
        )
        check(
            "frame listing two dotted-path gists is not flagged frame_members",
            ("frame_members", "concepts/dotted_frame.md") not in info_paths6,
            str(info_paths6),
        )
        check(
            "gist whose parent target resolves outside the store still flagged gist_parent",
            ("gist_parent", "concepts/outside_gist.md") in info_paths6,
            str(info_paths6),
        )

        # --- Fixture 7: schema memory-rung then schema upgrade must not block on memory ---
        store7 = tmp / "store7"
        init7 = run(["init", "--root", str(store7), "--json"])
        check("init store7", init7.returncode == 0, init7.stderr)
        schema7_before = json.loads((store7 / "SCHEMA.json").read_text(encoding="utf-8"))
        check(
            "store7 starts at SCHEMA 1.0",
            schema7_before.get("schema_version") == "1.0",
            str(schema7_before.get("schema_version")),
        )
        rung7_code, rung7_payload = run_json(
            ["schema", "memory-rung", "--set", "info", "--root", str(store7), "--json"]
        )
        check(
            "schema memory-rung --set info ok (store7)",
            rung7_code == 0 and rung7_payload.get("ok"),
        )
        preview7_code, preview7_payload = run_json(
            ["schema", "upgrade", "--root", str(store7), "--json"]
        )
        check(
            "schema upgrade preview ok after memory-rung (store7)",
            preview7_code == 0 and preview7_payload.get("ok"),
            str(preview7_payload),
        )
        check(
            "schema upgrade preview does not mention unknown root key memory",
            not any("memory" in k for k in preview7_payload.get("unknown_keys") or [])
            and not any(
                "unknown root key" in (note or "") and "memory" in (note or "")
                for note in preview7_payload.get("notes") or []
            ),
            str(preview7_payload),
        )
        apply7_code, apply7_payload = run_json(
            ["schema", "upgrade", "--apply", "--root", str(store7), "--json"]
        )
        check(
            "schema upgrade --apply ok (store7)",
            apply7_code == 0 and apply7_payload.get("ok"),
            str(apply7_payload),
        )
        schema7_after = json.loads((store7 / "SCHEMA.json").read_text(encoding="utf-8"))
        check(
            "store7 schema_version is 2.0 after upgrade",
            schema7_after.get("schema_version") == "2.0",
            str(schema7_after.get("schema_version")),
        )
        check(
            "store7 memory.rung preserved through upgrade",
            schema7_after.get("memory", {}).get("rung") == "info",
            str(schema7_after.get("memory")),
        )

        # --- Fixture 8: focused compile must not emit out-of-scope memory findings ---
        store8 = tmp / "store8"
        init8 = run(["init", "--root", str(store8), "--json"])
        check("init store8", init8.returncode == 0, init8.stderr)
        write_page(
            store8 / "out_of_scope" / "legacy.md",
            "document",
            "Out of scope legacy",
            "2026-10-03",
        )
        write_index(store8 / "out_of_scope", "Out of scope")
        write_page(
            store8 / "in_scope" / "note.md",
            "page",
            "In scope page",
            "2026-10-03",
        )
        write_page(
            store8 / "in_scope" / "note-gist.md",
            "gist",
            "In scope gist",
            "2026-10-03",
            relates_to=[{"path": "in_scope/note.md", "kind": "derived_from"}],
        )
        write_index(store8 / "in_scope", "In scope")
        rung8_code, _ = run_json(
            ["schema", "memory-rung", "--set", "warn", "--root", str(store8), "--json"]
        )
        check("store8 memory-rung warn ok", rung8_code == 0)

        code, payload = run_json(["compile", "--root", str(store8), "--json"])
        check(
            "unfocused compile still surfaces out-of-scope memory findings",
            code == 1
            and "legacy_document" in findings_by_id(payload, "warnings")
            and any(
                i.get("id") == "legacy_document" and "out_of_scope" in (i.get("path") or "")
                for i in payload.get("warnings", [])
            ),
            f"exit={code} warnings={payload.get('warnings')}",
        )

        code, payload = run_json(
            ["compile", "--root", str(store8), "--path", "in_scope", "--json"]
        )
        all_findings = (
            list(payload.get("warnings") or [])
            + list(payload.get("info") or [])
            + list(payload.get("critical") or [])
        )
        check(
            "focused --path compile exits 0 with in-scope gist present",
            code == 0,
            f"exit={code} critical={payload.get('critical')} warnings={payload.get('warnings')}",
        )
        check(
            "focused --path compile omits out-of-scope legacy_document findings",
            not any(
                i.get("id") == "legacy_document" and "out_of_scope" in (i.get("path") or "")
                for i in all_findings
            ),
            f"findings={all_findings}",
        )
        check(
            "focused --path compile omits out-of-scope missing_gist findings",
            not any(
                i.get("id") == "missing_gist" and "out_of_scope" in (i.get("path") or "")
                for i in all_findings
            ),
            f"findings={all_findings}",
        )

        code, payload = run_json(
            ["compile", "--root", str(store8), "--type", "page", "--json"]
        )
        all_findings = (
            list(payload.get("warnings") or [])
            + list(payload.get("info") or [])
            + list(payload.get("critical") or [])
        )
        check(
            "focused --type page compile exits 0 and omits document memory findings",
            code == 0
            and not any(i.get("id") == "legacy_document" for i in all_findings),
            f"exit={code} findings={all_findings}",
        )

        # --- Fixture 9: malformed relates_to (scalar) must not crash compile ---
        store9 = tmp / "store9"
        init9 = run(["init", "--root", str(store9), "--schema-version", "2.0", "--json"])
        check("init store9", init9.returncode == 0, init9.stderr)
        (store9 / "notes").mkdir(parents=True, exist_ok=True)
        (store9 / "notes" / "bad-gist.md").write_text(
            "---\n"
            "type: gist\n"
            "title: Bad gist\n"
            "created: 2026-10-03\n"
            "relates_to: 42\n"
            "---\n\n"
            "## Content\n\n"
            f"{PROSE}\n",
            encoding="utf-8",
        )
        write_index(store9 / "notes", "Notes")

        code9, payload9 = run_json(["compile", "--root", str(store9), "--json"])
        check(
            "malformed relates_to compile does not crash (valid JSON)",
            isinstance(payload9, dict),
            f"stdout parse failed: {payload9!r}",
        )
        crit9_ids = findings_by_id(payload9, "critical")
        check(
            "malformed relates_to produces relates_to critical finding",
            "relates_to" in crit9_ids,
            f"critical={payload9.get('critical')}",
        )
        check(
            "malformed relates_to critical message says must be a list",
            any(
                i.get("id") == "relates_to"
                and "must be a list" in (i.get("msg") or "")
                for i in payload9.get("critical", [])
            ),
            f"critical={payload9.get('critical')}",
        )

        # --- File-content assertions ---
        skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        check(
            "SKILL.md registry mentions memory-migrate module file",
            "memory-migrate" in skill_text
            and "references/paths/memory-migrate.md" in skill_text,
        )
        memory_migrate_path = ROOT / "references/paths/memory-migrate.md"
        check("memory-migrate.md exists", memory_migrate_path.is_file())
        migrate_text = (ROOT / "references/paths/migrate.md").read_text(encoding="utf-8")
        check(
            "migrate.md does not reuse legacy_document/missing_gist phrasing",
            "legacy type document" not in migrate_text
            and "missing gist" not in migrate_text,
        )
        mm_text = memory_migrate_path.read_text(encoding="utf-8")
        check(
            "memory-migrate.md says assess and inventory do not write",
            "assess" in mm_text.lower() and "write nothing" in mm_text.lower(),
        )
        query_text = (ROOT / "references/paths/query.md").read_text(encoding="utf-8")
        check(
            "query.md mentions index.md, frame, gist, page, and atlas search",
            all(
                term in query_text
                for term in ("index.md", "frame", "gist", "page", "atlas search")
            ),
        )
        check(
            "query.md still requires search_cmd on exit",
            "search_cmd" in query_text
            and "without `search_cmd`" in query_text
            and "incomplete Exit" in query_text,
        )
        check(
            "query.md still tells the reader to stop when the gist answers",
            "Stop there when the gist answers the ask" in query_text,
        )
        check(
            "SKILL.md has no checkpoint/constellation path row",
            "| **checkpoint**" not in skill_text
            and "| **constellation**" not in skill_text,
        )
        check(
            "no checkpoint.md / constellation.md path modules",
            not (ROOT / "references/paths/checkpoint.md").exists()
            and not (ROOT / "references/paths/constellation.md").exists(),
        )

        if failures:
            print("\n" + "\n".join(failures))
            return 1
        print("\nAll memory-layer regressions passed")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
