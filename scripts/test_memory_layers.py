#!/usr/bin/env python3
"""Memory layers (memory/gist/frame) regressions. Run: python3 scripts/test_memory_layers.py"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"

sys.path.insert(0, str(ROOT / "scripts"))
from atlas_cli.core.recall_config import default_recall_block  # noqa: E402


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


# --- SCHEMA.json (0.13.0-beta.2) fixture writer -----------------------------
#
# `atlas init` always writes CONTRACT.json (0.13.0-beta.3) now, so the
# SCHEMA.json (memory.layers frame/gist/memory) fixtures this suite exercises
# are written directly, mirroring the actual `atlas init` default shape
# byte-for-byte (no atlas_release stamp, no memory key) so the
# frame/gist/memory and frame_members checks below keep exercising real
# shipped 0.13.0-beta.2 behaviour rather than the new beta.3 contract shape.
_LEGACY_FM_ONLY = {
    "experience": ["type", "title", "created", "work_id"],
    "decision": ["type", "title", "created"],
    "work": ["type", "title", "created", "work_id"],
    "document": ["type", "title", "created"],
    "protostar": ["type", "title", "created"],
    "lesson": ["type", "title", "created"],
    "recipe": ["type", "title", "created"],
    "memory": ["type", "title", "created"],
    "gist": ["type", "title", "created"],
    "frame": ["type", "title", "created"],
}


def _legacy_by_type_block(tname: str) -> dict:
    return {
        "file": f"templates/{tname}.md",
        "frontmatter": {
            "required": _LEGACY_FM_ONLY.get(tname, ["type", "title", "created"]),
            "recommended": [],
        },
        "sections": {"required": [], "recommended": []},
    }


def _legacy_default_schema() -> dict:
    return {
        "schema_version": "1.0",
        "atlas_id": "new-atlas",
        "title": "New Atlas",
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
        "query": {
            "default_mode": "local",
            "search_engine": "grep",
            "fallback": "rg",
            "staging_visible": False,
        },
    }


def _default_recall_block() -> dict:
    return default_recall_block()


def init_legacy(root: Path, schema_version: str = "1.0") -> subprocess.CompletedProcess[str]:
    """Write a shipped-beta SCHEMA.json store directly (no CLI `init` call).

    Returns a CompletedProcess-shaped result (returncode/stderr) so existing
    `check("init storeN", initN.returncode == 0, initN.stderr)` call sites do
    not need to change shape, only the call itself.
    """
    root.mkdir(parents=True, exist_ok=True)
    schema = _legacy_default_schema()
    version = (schema_version or "1.0").strip() or "1.0"
    schema["schema_version"] = version
    schema["atlas_id"] = root.name or "new-atlas"
    schema["templates"]["by_type"] = {
        name: _legacy_by_type_block(name) for name in _LEGACY_FM_ONLY
    }
    if version == "2.0":
        schema["recall"] = _default_recall_block()
    (root / "SCHEMA.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    tmpl_src = ROOT / "references" / "templates"
    tmpl_dst = root / "templates"
    tmpl_dst.mkdir(exist_ok=True)
    if tmpl_src.is_dir():
        for src in sorted(tmpl_src.glob("*.md")):
            shutil.copy2(src, tmpl_dst / src.name)

    index = root / "index.md"
    if not index.is_file():
        index.write_text(
            f"# {schema['atlas_id']}\n\nInitialised by atlas init.\n", encoding="utf-8"
        )
    log = root / "log.md"
    if not log.is_file():
        log.write_text("# Log\n\n- init\n", encoding="utf-8")

    return subprocess.CompletedProcess(args=["init-legacy"], returncode=0, stdout="", stderr="")


PROSE = (
    "This page carries enough non-link prose content to pass the "
    "not_just_links body length check used across the test fixtures."
)


def write_page(
    path: Path,
    type_name: str,
    title: str,
    created: str,
    relates_to=None,
    body_suffix: str = "",
) -> None:
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
        f"{PROSE}\n"
        f"{body_suffix}",
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
        init = init_legacy(store1)
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
        init2 = init_legacy(store2)
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
            "fresh store recommends memory and not page",
            "memory" in schema2.get("types", {}).get("recommended", [])
            and "page" not in schema2.get("types", {}).get("recommended", []),
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
        check(
            "fresh store copies memory.md without a page.md type template",
            (store2 / "templates" / "memory.md").is_file()
            and not (store2 / "templates" / "page.md").exists(),
        )
        check(
            "fresh store templates.by_type has memory and not page",
            "memory" in schema2.get("templates", {}).get("by_type", {})
            and "page" not in schema2.get("templates", {}).get("by_type", {}),
        )

        # --- Fixture 3: gist parent cardinality ---
        store3 = tmp / "store3"
        init_legacy(store3)
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
        check(
            "parent.md covered by good_gist is not missing_gist",
            ("missing_gist", "concepts/parent.md") not in info_paths,
            str(info_paths),
        )
        check(
            "parent2.md is only 'covered' by the malformed two-parent gist, "
            "so it still reports missing_gist",
            ("missing_gist", "concepts/parent2.md") in info_paths,
            str(info_paths),
        )

        # --- Fixture 4: frame members ---
        store4 = tmp / "store4"
        init_legacy(store4)
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
            "memory",
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
            "frame that omits a folder gist is flagged frame_members",
            ("frame_members", "concepts/thin_frame.md") in info_paths4,
            str(info_paths4),
        )
        check(
            "the frame listing both folder gists has no member finding",
            ("frame_members", "concepts/good_frame.md") not in info_paths4,
        )
        check(
            "duplicate-gist frame (same gist twice) flagged frame_members",
            ("frame_members", "concepts/duplicate_frame.md") in info_paths4,
            str(info_paths4),
        )
        check(
            "frame listing a memory episode as a member is flagged frame_members",
            ("frame_members", "concepts/mixed_frame.md") in info_paths4,
            str(info_paths4),
        )
        check(
            "folder with multiple frames has a folder-level frame_members finding",
            ("frame_members", "concepts") in info_paths4,
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

        # --- Fixture 4a: one gist still requires one matching frame ---
        store4a = tmp / "store4a"
        init_legacy(store4a)
        write_index(store4a / "concepts", "Concepts")
        write_page(
            store4a / "concepts" / "parent.md",
            "memory",
            "Single gist parent",
            "2026-10-01",
        )
        write_page(
            store4a / "concepts" / "only-gist.md",
            "gist",
            "Only gist",
            "2026-10-01",
            relates_to=[{"path": "concepts/parent.md", "kind": "derived_from"}],
        )
        write_page(
            store4a / "concepts" / "frame.md",
            "frame",
            "Single gist frame",
            "2026-10-01",
            relates_to=[{"path": "concepts/only-gist.md", "kind": "related"}],
        )
        code, payload = run_json(["compile", "--root", str(store4a), "--json"])
        check("single-gist frame fixture exits 0 at info rung", code == 0)
        check(
            "one gist grouped by its only frame is valid",
            not any(
                i.get("id") == "frame_members"
                for i in payload.get("info", [])
                + payload.get("warnings", [])
                + payload.get("critical", [])
            ),
            str(payload),
        )

        frame_path = store4a / "concepts" / "frame.md"
        valid_frame = frame_path.read_text(encoding="utf-8")
        valid_relations = (
            "relates_to:\n"
            "  - path: concepts/only-gist.md\n"
            "    kind: related\n"
        )
        invalid_relations = (
            (
                "extra non-related target",
                valid_relations
                + "  - path: concepts/parent.md\n    kind: derived_from\n",
            ),
            ("non-dict entry", valid_relations + "  - invalid\n"),
            ("empty path", valid_relations + "  - path: ''\n    kind: related\n"),
            (
                "duplicate gist",
                valid_relations + "  - path: concepts/only-gist.md\n    kind: related\n",
            ),
            ("missing relates_to", ""),
            ("non-list relates_to", "relates_to: invalid\n"),
        )
        for case, relations in invalid_relations:
            frame_path.write_text(
                valid_frame.replace(valid_relations, relations), encoding="utf-8"
            )
            _, payload = run_json(["compile", "--root", str(store4a), "--json"])
            check(
                f"frame with {case} is flagged frame_members",
                any(
                    i.get("id") == "frame_members"
                    and i.get("path") == "concepts/frame.md"
                    for i in payload.get("info", [])
                    + payload.get("warnings", [])
                    + payload.get("critical", [])
                ),
                str(payload),
            )
        frame_path.write_text(valid_frame, encoding="utf-8")
        _, payload = run_json(["compile", "--root", str(store4a), "--json"])
        check(
            "same frame without extra entries has no member finding",
            not any(
                i.get("id") == "frame_members"
                and i.get("path") == "concepts/frame.md"
                for i in payload.get("info", [])
                + payload.get("warnings", [])
                + payload.get("critical", [])
            ),
            str(payload),
        )

        # --- Fixture 4b: gists without a frame are a memory-rung finding ---
        store4b = tmp / "store4b"
        init_legacy(store4b)
        write_index(store4b / "concepts", "Concepts")
        write_page(
            store4b / "concepts" / "parent.md",
            "memory",
            "Parent without a frame",
            "2026-10-01",
        )
        write_page(
            store4b / "concepts" / "only-gist.md",
            "gist",
            "Unframed gist",
            "2026-10-01",
            relates_to=[{"path": "concepts/parent.md", "kind": "derived_from"}],
        )
        code, payload = run_json(["compile", "--root", str(store4b), "--json"])
        check("unframed gist fixture exits 0 at info rung", code == 0)
        check(
            "folder containing a gist with no frame has frame_members info",
            any(
                i.get("id") == "frame_members"
                and i.get("path") == "concepts"
                and i.get("severity") == "info"
                for i in payload.get("info", [])
            ),
            str(payload.get("info")),
        )
        for store, case, gist_file, has_frame in (
            (store4b, "missing frame", "only-gist.md", False),
            (store4, "multiple frames", "g1.md", True),
        ):
            write_index(store / "other", "Other")
            for focus_args, expected in (
                (["--path", "concepts"], True),
                (["--path", "."], True),
                (["--type", "gist"], True),
                (["--type", "frame"], has_frame),
                (["--path", "concepts", "--type", "gist"], True),
                (["--path", "concepts", "--type", "frame"], has_frame),
                (["--path", "other"], False),
                (["--path", "other", "--type", "gist"], False),
                (["--path", "other", "--type", "frame"], False),
                (["--path", f"concepts/{gist_file}"], False),
            ):
                code, payload = run_json(
                    ["compile", "--root", str(store), *focus_args, "--json"]
                )
                label = f"{case}, focus {' '.join(focus_args)}"
                check(
                    f"{label}: valid JSON and exit 0 at default info rung",
                    code == 0 and payload.get("memory_rung") == "info",
                    str(payload),
                )
                folder_findings = [
                    finding
                    for bucket in ("info", "warnings", "critical")
                    for finding in payload.get(bucket, [])
                    if finding.get("id") == "frame_members"
                    and finding.get("path") == "concepts"
                ]
                check(
                    f"{label}: folder finding follows path/type focus",
                    len(folder_findings) == int(expected)
                    and all(
                        finding.get("severity") == "info"
                        and finding in payload.get("info", [])
                        for finding in folder_findings
                    ),
                    str(payload),
                )
        rung4b_code, _ = run_json(
            ["schema", "memory-rung", "--set", "warn", "--root", str(store4b), "--json"]
        )
        check("store4b memory-rung warn ok", rung4b_code == 0)
        code, payload = run_json(["compile", "--root", str(store4b), "--json"])
        check(
            "missing-frame finding is a warning with exit 1 at warn rung",
            code == 1
            and any(i.get("id") == "frame_members" for i in payload.get("warnings", [])),
            str(payload),
        )
        rung4b_code, _ = run_json(
            ["schema", "memory-rung", "--set", "error", "--root", str(store4b), "--json"]
        )
        check("store4b memory-rung error ok", rung4b_code == 0)
        code, payload = run_json(["compile", "--root", str(store4b), "--json"])
        check(
            "missing-frame finding is critical with exit 2 at error rung",
            code == 2
            and any(i.get("id") == "frame_members" for i in payload.get("critical", [])),
            str(payload),
        )

        # --- Fixture 4c: exactly one frame groups both folder gists ---
        store4c = tmp / "store4c"
        init_legacy(store4c)
        write_index(store4c / "concepts", "Concepts")
        write_page(
            store4c / "concepts" / "parent.md",
            "memory",
            "Two gist parent",
            "2026-10-01",
        )
        for gist_name in ("g1.md", "g2.md"):
            write_page(
                store4c / "concepts" / gist_name,
                "gist",
                gist_name,
                "2026-10-01",
                relates_to=[{"path": "concepts/parent.md", "kind": "derived_from"}],
            )
        write_page(
            store4c / "concepts" / "frame.md",
            "frame",
            "Both gists",
            "2026-10-01",
            relates_to=[
                {"path": "concepts/g1.md", "kind": "related"},
                {"path": "concepts/g2.md", "kind": "related"},
            ],
        )
        code, payload = run_json(["compile", "--root", str(store4c), "--json"])
        check("two-gist single-frame fixture exits 0", code == 0)
        check(
            "one frame listing both folder gists has no frame finding",
            not any(
                i.get("id") == "frame_members"
                for i in payload.get("info", [])
                + payload.get("warnings", [])
                + payload.get("critical", [])
            ),
            str(payload),
        )

        # --- Fixture 4d: a frame in a folder with zero gists is invalid ---
        store4d = tmp / "store4d"
        init_legacy(store4d)
        write_index(store4d / "empty", "Empty")
        write_page(
            store4d / "empty" / "frame.md",
            "frame",
            "Orphan frame",
            "2026-10-01",
        )
        code, payload = run_json(["compile", "--root", str(store4d), "--json"])
        check("zero-gist folder with frame exits 0 at info rung", code == 0)
        check(
            "frame in a folder with no gists is a frame_members finding",
            any(
                i.get("id") == "frame_members"
                and i.get("path") == "empty/frame.md"
                for i in payload.get("info", [])
            ),
            str(payload.get("info")),
        )

        # --- Fixture 5: protostar with no gist produces no missing_gist ---
        store5 = tmp / "store5"
        init_legacy(store5)
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
        check(
            "folder with no gist and no frame has no frame_members finding",
            "frame_members" not in {finding_id for finding_id, _ in all_ids_paths},
            str(all_ids_paths),
        )

        # --- Fixture 6: relates_to targets normalized to canonical page keys ---
        store6 = tmp / "store6"
        init_legacy(store6)
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
            store6 / "concepts" / "unresolved" / "outside_gist.md",
            "gist",
            "Gist with unresolved parent",
            "2026-10-01",
            relates_to=[{"path": "../../outside/nope.md", "kind": "derived_from"}],
        )
        write_index(store6 / "concepts" / "unresolved", "Unresolved")
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
            ("gist_parent", "concepts/unresolved/outside_gist.md") in info_paths6,
            str(info_paths6),
        )

        # --- Fixture 7: schema memory-rung then schema upgrade must not block on memory ---
        store7 = tmp / "store7"
        init7 = init_legacy(store7)
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
        init8 = init_legacy(store8)
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
            "memory",
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
        write_page(
            store8 / "in_scope" / "note-frame.md",
            "frame",
            "In scope frame",
            "2026-10-03",
            relates_to=[{"path": "in_scope/note-gist.md", "kind": "related"}],
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
            ["compile", "--root", str(store8), "--type", "memory", "--json"]
        )
        all_findings = (
            list(payload.get("warnings") or [])
            + list(payload.get("info") or [])
            + list(payload.get("critical") or [])
        )
        check(
            "focused --type memory compile exits 0 and omits document memory findings",
            code == 0
            and not any(i.get("id") == "legacy_document" for i in all_findings),
            f"exit={code} findings={all_findings}",
        )

        # --- Fixture 9: malformed relates_to (scalar) must not crash compile ---
        store9 = tmp / "store9"
        init9 = init_legacy(store9, schema_version="2.0")
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

        # --- Fixture 10: --dry-run compile writes nothing (mesh.json, recall) ---
        store10 = tmp / "store10"
        init10 = init_legacy(store10, schema_version="2.0")
        check("init store10", init10.returncode == 0, init10.stderr)

        (store10 / "mesh.fragment.json").write_text(
            json.dumps(
                {
                    "atlases": [
                        {"id": "demo", "root": "github.com/demo/demo", "access": "read"}
                    ]
                }
            ),
            encoding="utf-8",
        )

        activate10 = run(
            ["recall", "activate", "--profile", "atlas:scan", "--root", str(store10), "--json"]
        )
        check("recall activate atlas:scan on store10", activate10.returncode == 0, activate10.stderr)

        mesh_path10 = store10 / "mesh.json"
        recall_pointer10 = store10 / ".atlas-index" / "recall" / "current.json"

        code10, payload10 = run_json(["compile", "--root", str(store10), "--json", "--dry-run"])
        check("dry-run compile exits 0", code10 == 0, f"exit={code10} payload={payload10}")
        check("dry-run compile does not write mesh.json", not mesh_path10.exists())
        check(
            "dry-run compile reports mesh.written as None",
            payload10.get("mesh", {}).get("written") is None,
            str(payload10.get("mesh")),
        )
        check(
            "dry-run compile still reports mesh atlas_count",
            payload10.get("mesh", {}).get("atlas_count") == 1,
            str(payload10.get("mesh")),
        )
        check(
            "dry-run compile does not publish recall index",
            not recall_pointer10.exists(),
        )
        check(
            "dry-run compile reports recall_index reason dry_run",
            (payload10.get("recall_index") or {}).get("reason") == "dry_run",
            str(payload10.get("recall_index")),
        )
        check("dry-run compile marks dry_run true", payload10.get("dry_run") is True)
        check(
            "dry-run compile reports memory_rung info (absent SCHEMA memory/rung)",
            payload10.get("memory_rung") == "info",
            str(payload10.get("memory_rung")),
        )

        code10b, payload10b = run_json(["compile", "--root", str(store10), "--json"])
        check(
            "non-dry-run compile exits 0 after dry-run (unchanged behaviour)",
            code10b == 0,
            f"exit={code10b} payload={payload10b}",
        )
        check("non-dry-run compile writes mesh.json", mesh_path10.exists())
        check(
            "non-dry-run compile reports mesh.written as mesh.json",
            payload10b.get("mesh", {}).get("written") == "mesh.json",
        )
        check("non-dry-run compile publishes recall index", recall_pointer10.exists())
        check(
            "non-dry-run compile reports recall_index published",
            (payload10b.get("recall_index") or {}).get("published") is True,
            str(payload10b.get("recall_index")),
        )
        check(
            "non-dry-run compile reports memory_rung info (absent SCHEMA memory/rung)",
            payload10b.get("memory_rung") == "info",
            str(payload10b.get("memory_rung")),
        )

        rung10 = run(
            ["schema", "memory-rung", "--set", "warn", "--root", str(store10), "--json"]
        )
        check("schema memory-rung --set warn ok (store10)", rung10.returncode == 0, rung10.stderr)
        code10c, payload10c = run_json(["compile", "--root", str(store10), "--json"])
        check(
            "compile after schema memory-rung --set warn: memory_rung warn",
            payload10c.get("memory_rung") == "warn",
            str(payload10c.get("memory_rung")),
        )
        check(
            "compile after schema memory-rung --set warn: exit policy unchanged",
            code10c == 0,
            f"exit={code10c} payload={payload10c}",
        )

        # --- Fixture 11: inline atlas-ignore comments suppress memory findings ---
        store11 = tmp / "store11"
        init11 = init_legacy(store11)
        check("init store11", init11.returncode == 0, init11.stderr)
        write_page(
            store11 / "notes" / "ignored_doc.md",
            "document",
            "Ignored legacy doc",
            "2026-10-03",
            body_suffix=(
                "<!-- atlas-ignore: legacy_document -->\n"
                "<!-- atlas-ignore: missing_gist -->\n"
            ),
        )
        write_index(store11 / "notes", "Notes")
        write_page(
            store11 / "notes" / "ignored_gist.md",
            "gist",
            "Ignored gist with bad parent",
            "2026-10-03",
            body_suffix="<!-- atlas-ignore: gist_parent -->\n",
        )
        write_page(
            store11 / "notes" / "ignored_frame.md",
            "frame",
            "Ignored frame with too few members",
            "2026-10-03",
            body_suffix="<!-- atlas-ignore: frame_members -->\n",
        )
        rung11_code, _ = run_json(
            ["schema", "memory-rung", "--set", "warn", "--root", str(store11), "--json"]
        )
        check("store11 memory-rung warn ok", rung11_code == 0)

        code, payload = run_json(["compile", "--root", str(store11), "--json"])
        four_ids = {"missing_gist", "legacy_document", "gist_parent", "frame_members"}
        all_found_ids = (
            set(findings_by_id(payload, "info"))
            | set(findings_by_id(payload, "warnings"))
            | set(findings_by_id(payload, "critical"))
        )
        check(
            "inline-ignored memory findings: exit 0 with allow_inline_ignores true",
            code == 0,
            f"exit={code} payload={payload}",
        )
        check(
            "inline-ignored memory findings: none of the four ids appear",
            not (four_ids & all_found_ids),
            f"found={all_found_ids}",
        )

        schema11_path = store11 / "SCHEMA.json"
        schema11 = json.loads(schema11_path.read_text(encoding="utf-8"))
        schema11["compile"]["allow_inline_ignores"] = False
        schema11_path.write_text(json.dumps(schema11, indent=2) + "\n", encoding="utf-8")

        code, payload = run_json(["compile", "--root", str(store11), "--json"])
        all_found_ids = (
            set(findings_by_id(payload, "info"))
            | set(findings_by_id(payload, "warnings"))
            | set(findings_by_id(payload, "critical"))
        )
        check(
            "allow_inline_ignores false: exit 1 (warn rung)",
            code == 1,
            f"exit={code} payload={payload}",
        )
        check(
            "allow_inline_ignores false: all four ids reported as warnings",
            four_ids <= set(findings_by_id(payload, "warnings")),
            f"warnings={findings_by_id(payload, 'warnings')}",
        )

        # --- Fixture 12: inline ignores are page-scoped, not global ---
        store12 = tmp / "store12"
        init12 = init_legacy(store12)
        check("init store12", init12.returncode == 0, init12.stderr)
        write_page(
            store12 / "notes" / "doc_commented.md",
            "document",
            "Commented legacy doc",
            "2026-10-03",
            body_suffix=(
                "<!-- atlas-ignore: legacy_document -->\n"
                "<!-- atlas-ignore: missing_gist -->\n"
            ),
        )
        write_page(
            store12 / "notes" / "doc_plain.md",
            "document",
            "Plain legacy doc",
            "2026-10-03",
        )
        write_index(store12 / "notes", "Notes")
        rung12_code, _ = run_json(
            ["schema", "memory-rung", "--set", "warn", "--root", str(store12), "--json"]
        )
        check("store12 memory-rung warn ok", rung12_code == 0)

        code, payload = run_json(["compile", "--root", str(store12), "--json"])
        warn_items = payload.get("warnings") or []
        check(
            "page-scoped ignore: doc_plain still reports legacy_document/missing_gist",
            any(
                i.get("id") == "legacy_document" and "doc_plain" in (i.get("path") or "")
                for i in warn_items
            )
            and any(
                i.get("id") == "missing_gist" and "doc_plain" in (i.get("path") or "")
                for i in warn_items
            ),
            f"warnings={warn_items}",
        )
        check(
            "page-scoped ignore: doc_commented omits legacy_document/missing_gist",
            not any(
                i.get("id") in ("legacy_document", "missing_gist")
                and "doc_commented" in (i.get("path") or "")
                for i in warn_items
            ),
            f"warnings={warn_items}",
        )

        # --- Fixture 13: info-only terminal summary line ---
        store13 = tmp / "store13"
        init13 = init_legacy(store13)
        check("init store13", init13.returncode == 0, init13.stderr)
        write_page(
            store13 / "notes" / "legacy.md",
            "document",
            "Legacy note",
            "2026-10-03",
        )
        write_index(store13 / "notes", "Notes")
        text_result = run(["compile", "--root", str(store13)])
        check(
            "info-only compile exits 0",
            text_result.returncode == 0,
            f"exit={text_result.returncode} stderr={text_result.stderr}",
        )
        check(
            "info-only compile prints INFO section",
            "INFO (" in text_result.stdout,
            text_result.stdout,
        )
        check(
            "info-only compile prints the informational-only summary",
            "ok — informational findings only" in text_result.stdout,
            text_result.stdout,
        )
        check(
            "info-only compile does not print the no-issues summary",
            "ok — no issues" not in text_result.stdout,
            text_result.stdout,
        )

        store14 = tmp / "store14"
        init14 = init_legacy(store14)
        check("init store14", init14.returncode == 0, init14.stderr)
        write_page(
            store14 / "notes" / "page.md",
            "memory",
            "Clean page",
            "2026-10-03",
        )
        write_page(
            store14 / "notes" / "page-gist.md",
            "gist",
            "Clean page gist",
            "2026-10-03",
            relates_to=[{"path": "notes/page.md", "kind": "derived_from"}],
        )
        write_page(
            store14 / "notes" / "frame.md",
            "frame",
            "Clean frame",
            "2026-10-03",
            relates_to=[{"path": "notes/page-gist.md", "kind": "related"}],
        )
        write_index(store14 / "notes", "Notes")
        text_result14 = run(["compile", "--root", str(store14)])
        check(
            "no-issues compile exits 0",
            text_result14.returncode == 0,
            f"exit={text_result14.returncode} stderr={text_result14.stderr}",
        )
        check(
            "no-issues compile prints the no-issues summary",
            "ok — no issues" in text_result14.stdout,
            text_result14.stdout,
        )
        check(
            "no-issues compile does not print the informational-only summary",
            "ok — informational findings only" not in text_result14.stdout,
            text_result14.stdout,
        )

        # --- Fixture 15: v2 memory.layers / memory.legacy_types are constrained ---
        schema_doc_path = ROOT / "scripts/atlas_cli/schemas/store-v2.schema.json"
        schema_doc = json.loads(schema_doc_path.read_text(encoding="utf-8"))
        memory_props = schema_doc["properties"]["memory"]["properties"]
        layers_const_options = [
            o.get("const")
            for o in (memory_props["layers"].get("oneOf") or [memory_props["layers"]])
        ]
        check(
            "store-v2 schema: memory.layers is exact-array const frame/gist/memory",
            memory_props["layers"].get("const") == ["frame", "gist", "memory"],
            str(memory_props["layers"]),
        )
        check(
            "store-v2 schema: memory.legacy_types is exact-array const [document]",
            memory_props["legacy_types"].get("const") == ["document"],
            str(memory_props["legacy_types"]),
        )

        store15 = tmp / "store15"
        init15 = init_legacy(store15)
        check("init store15", init15.returncode == 0, init15.stderr)
        rung15_code, _ = run_json(
            ["schema", "memory-rung", "--set", "info", "--root", str(store15), "--json"]
        )
        check("store15 memory-rung info ok", rung15_code == 0)
        apply15_code, apply15_payload = run_json(
            ["schema", "upgrade", "--apply", "--root", str(store15), "--json"]
        )
        check(
            "store15 schema upgrade --apply ok",
            apply15_code == 0 and apply15_payload.get("ok"),
            str(apply15_payload),
        )
        schema15_path = store15 / "SCHEMA.json"
        schema15 = json.loads(schema15_path.read_text(encoding="utf-8"))
        check(
            "store15 upgraded to 2.0",
            schema15.get("schema_version") == "2.0",
            str(schema15.get("schema_version")),
        )
        check(
            "store15 legacy_types includes document after upgrade",
            "document" in (schema15.get("memory", {}).get("legacy_types") or []),
            str(schema15.get("memory")),
        )

        code, payload = run_json(["compile", "--root", str(store15), "--json"])
        check(
            "store15 default memory.layers/legacy_types: no schema_v2 critical",
            not any(
                i.get("id") == "schema_v2"
                and ("layers" in (i.get("msg") or "") or "legacy_types" in (i.get("msg") or ""))
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        schema15["memory"]["layers"] = ["other"]
        schema15_path.write_text(json.dumps(schema15, indent=2) + "\n", encoding="utf-8")
        code, payload = run_json(["compile", "--root", str(store15), "--json"])
        check("store15 invalid layers: exit 2", code == 2, f"exit={code}")
        check(
            "store15 invalid layers: schema_v2 critical mentions layers",
            any(
                i.get("id") == "schema_v2" and "layers" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        schema15["memory"]["layers"] = ["frame", "gist", "memory"]
        schema15["memory"]["legacy_types"] = ["not-a-type"]
        schema15_path.write_text(json.dumps(schema15, indent=2) + "\n", encoding="utf-8")
        code, payload = run_json(["compile", "--root", str(store15), "--json"])
        check("store15 invalid legacy_types: exit 2", code == 2, f"exit={code}")
        check(
            "store15 invalid legacy_types: schema_v2 critical present",
            any(i.get("id") == "schema_v2" for i in payload.get("critical", [])),
            f"critical={payload.get('critical')}",
        )

        schema15["memory"]["layers"] = []
        schema15["memory"]["legacy_types"] = ["document"]
        schema15_path.write_text(json.dumps(schema15, indent=2) + "\n", encoding="utf-8")
        code, payload = run_json(["compile", "--root", str(store15), "--json"])
        check("store15 empty layers: exit 2", code == 2, f"exit={code}")
        check(
            "store15 empty layers: schema_v2 critical mentions layers",
            any(
                i.get("id") == "schema_v2" and "layers" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        schema15["memory"]["layers"] = ["memory"]
        schema15_path.write_text(json.dumps(schema15, indent=2) + "\n", encoding="utf-8")
        code, payload = run_json(["compile", "--root", str(store15), "--json"])
        check("store15 partial layers: exit 2", code == 2, f"exit={code}")
        check(
            "store15 partial layers: schema_v2 critical mentions layers",
            any(
                i.get("id") == "schema_v2" and "layers" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        schema15["memory"]["layers"] = ["frame", "gist", "memory", "frame"]
        schema15_path.write_text(json.dumps(schema15, indent=2) + "\n", encoding="utf-8")
        code, payload = run_json(["compile", "--root", str(store15), "--json"])
        check("store15 duplicate layers: exit 2", code == 2, f"exit={code}")
        check(
            "store15 duplicate layers: schema_v2 critical mentions layers",
            any(
                i.get("id") == "schema_v2" and "layers" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        schema15["memory"]["layers"] = ["frame", "gist", "memory"]
        schema15["memory"]["legacy_types"] = []
        schema15_path.write_text(json.dumps(schema15, indent=2) + "\n", encoding="utf-8")
        code, payload = run_json(["compile", "--root", str(store15), "--json"])
        check("store15 empty legacy_types: exit 2", code == 2, f"exit={code}")
        check(
            "store15 empty legacy_types: schema_v2 critical mentions legacy_types",
            any(
                i.get("id") == "schema_v2" and "legacy_types" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        schema15["memory"]["layers"] = ["frame", "gist", "memory"]
        schema15["memory"]["legacy_types"] = ["document", "document"]
        schema15_path.write_text(json.dumps(schema15, indent=2) + "\n", encoding="utf-8")
        code, payload = run_json(["compile", "--root", str(store15), "--json"])
        check("store15 duplicate legacy_types: exit 2", code == 2, f"exit={code}")
        check(
            "store15 duplicate legacy_types: schema_v2 critical mentions legacy_types",
            any(
                i.get("id") == "schema_v2" and "legacy_types" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        schema15["memory"]["layers"] = ["frame", "gist", "memory"]
        schema15["memory"]["legacy_types"] = ["document"]
        schema15_path.write_text(json.dumps(schema15, indent=2) + "\n", encoding="utf-8")
        code, payload = run_json(["compile", "--root", str(store15), "--json"])
        check(
            "store15 restored legacy_types: no schema_v2 critical",
            not any(i.get("id") == "schema_v2" for i in payload.get("critical", [])),
            f"critical={payload.get('critical')}",
        )

        # --- Fixture 16: falsey non-string memory.rung is critical (SCHEMA 1.0) ---
        # SCHEMA 1.0 stores skip the v2 JSON Schema check, so 0/false/[]/{} must
        # not collapse via `or ""` into an absent rung that lets compile exit 0.
        store16 = tmp / "store16"
        init16 = init_legacy(store16)
        check("init store16", init16.returncode == 0, init16.stderr)
        schema16_path = store16 / "SCHEMA.json"
        schema16 = json.loads(schema16_path.read_text(encoding="utf-8"))
        write_page(
            store16 / "notes" / "alone.md",
            "memory",
            "Alone",
            "2026-10-03",
        )
        write_index(store16 / "notes", "Notes")

        for falsey in (0, False, [], {}):
            schema16["memory"] = {"rung": falsey}
            schema16_path.write_text(json.dumps(schema16, indent=2) + "\n", encoding="utf-8")
            code, payload = run_json(["compile", "--root", str(store16), "--json"])
            label = type(falsey).__name__
            crit_ids = findings_by_id(payload, "critical")
            check(
                f"falsey non-string rung ({label}={falsey!r}): exit != 0",
                code != 0,
                f"exit={code} critical={payload.get('critical')}",
            )
            check(
                f"falsey non-string rung ({label}={falsey!r}): memory_rung critical",
                "memory_rung" in crit_ids,
                f"critical={payload.get('critical')}",
            )
            check(
                f"falsey non-string rung ({label}={falsey!r}): message names type",
                any(
                    i.get("id") == "memory_rung"
                    and "must be a string" in (i.get("msg") or "")
                    for i in payload.get("critical", [])
                ),
                f"critical={payload.get('critical')}",
            )

        # Absent / blank string remain info (no memory_rung critical)
        for case_name, memory_block in (
            ("missing memory key", None),
            ("memory without rung", {}),
            ("rung null", {"rung": None}),
            ("rung blank", {"rung": "   "}),
        ):
            if memory_block is None:
                schema16.pop("memory", None)
            else:
                schema16["memory"] = memory_block
            schema16_path.write_text(json.dumps(schema16, indent=2) + "\n", encoding="utf-8")
            code, payload = run_json(["compile", "--root", str(store16), "--json"])
            crit_ids = findings_by_id(payload, "critical")
            check(
                f"absent/blank rung ({case_name}): no memory_rung critical",
                "memory_rung" not in crit_ids,
                f"exit={code} critical={payload.get('critical')}",
            )
            check(
                f"absent/blank rung ({case_name}): compile exit 0",
                code == 0,
                f"exit={code} critical={payload.get('critical')}",
            )
            check(
                f"absent/blank rung ({case_name}): memory_rung effective ladder is info",
                payload.get("memory_rung") == "info",
                f"memory_rung={payload.get('memory_rung')}",
            )

        # Malformed rung also reports effective ladder info in memory_rung,
        # even though it raises the memory_rung critical finding above.
        schema16["memory"] = {"rung": 0}
        schema16_path.write_text(json.dumps(schema16, indent=2) + "\n", encoding="utf-8")
        code, payload = run_json(["compile", "--root", str(store16), "--json"])
        check(
            "malformed rung (0): memory_rung field still reports info",
            payload.get("memory_rung") == "info",
            f"memory_rung={payload.get('memory_rung')}",
        )

        # --- Fixture 17: SCHEMA 1.0 memory.layers/legacy_types contract ---
        # SCHEMA 1.0 stores are not upgraded to v2 so they skip validate_store_v2,
        # but the fixed memory.layers/legacy_types contract must still hold.
        store17 = tmp / "store17"
        init17 = init_legacy(store17)
        check("init store17", init17.returncode == 0, init17.stderr)
        schema17_path = store17 / "SCHEMA.json"
        schema17 = json.loads(schema17_path.read_text(encoding="utf-8"))
        check(
            "store17 stays on SCHEMA 1.0 (no schema upgrade applied)",
            schema17.get("schema_version") != "2.0",
            str(schema17.get("schema_version")),
        )
        write_page(
            store17 / "notes" / "alone.md",
            "memory",
            "Alone",
            "2026-10-03",
        )
        write_index(store17 / "notes", "Notes")

        def write_schema17(memory_block):
            if memory_block is None:
                schema17.pop("memory", None)
            else:
                schema17["memory"] = memory_block
            schema17_path.write_text(json.dumps(schema17, indent=2) + "\n", encoding="utf-8")

        # No memory key at all: valid, no memory_contract critical.
        write_schema17(None)
        code, payload = run_json(["compile", "--root", str(store17), "--json"])
        check(
            "store17 no memory key: no memory_contract critical",
            "memory_contract" not in findings_by_id(payload, "critical"),
            f"critical={payload.get('critical')}",
        )

        # memory.rung only: valid, no memory_contract critical.
        write_schema17({"rung": "info"})
        code, payload = run_json(["compile", "--root", str(store17), "--json"])
        check(
            "store17 rung-only memory block: no memory_contract critical",
            "memory_contract" not in findings_by_id(payload, "critical"),
            f"critical={payload.get('critical')}",
        )

        # Exact layers + legacy_types: valid, no memory_contract critical.
        write_schema17({"layers": ["frame", "gist", "memory"], "legacy_types": ["document"]})
        code, payload = run_json(["compile", "--root", str(store17), "--json"])
        check(
            "store17 exact layers/legacy_types: no memory_contract critical",
            "memory_contract" not in findings_by_id(payload, "critical"),
            f"critical={payload.get('critical')}",
        )

        # Wrong layers.
        write_schema17({"layers": ["other"], "legacy_types": ["document"]})
        code, payload = run_json(["compile", "--root", str(store17), "--json"])
        check("store17 wrong layers: exit 2", code == 2, f"exit={code}")
        check(
            "store17 wrong layers: memory_contract critical mentions layers",
            any(
                i.get("id") == "memory_contract" and "layers" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        # Wrong legacy_types.
        write_schema17({"layers": ["frame", "gist", "memory"], "legacy_types": ["not-a-type"]})
        code, payload = run_json(["compile", "--root", str(store17), "--json"])
        check("store17 wrong legacy_types: exit 2", code == 2, f"exit={code}")
        check(
            "store17 wrong legacy_types: memory_contract critical mentions legacy_types",
            any(
                i.get("id") == "memory_contract" and "legacy_types" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        # Empty layers.
        write_schema17({"layers": [], "legacy_types": ["document"]})
        code, payload = run_json(["compile", "--root", str(store17), "--json"])
        check("store17 empty layers: exit 2", code == 2, f"exit={code}")
        check(
            "store17 empty layers: memory_contract critical mentions layers",
            any(
                i.get("id") == "memory_contract" and "layers" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        # Partial layers.
        write_schema17({"layers": ["memory"], "legacy_types": ["document"]})
        code, payload = run_json(["compile", "--root", str(store17), "--json"])
        check("store17 partial layers: exit 2", code == 2, f"exit={code}")
        check(
            "store17 partial layers: memory_contract critical mentions layers",
            any(
                i.get("id") == "memory_contract" and "layers" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        # Duplicate layers.
        write_schema17(
            {"layers": ["frame", "gist", "memory", "frame"], "legacy_types": ["document"]}
        )
        code, payload = run_json(["compile", "--root", str(store17), "--json"])
        check("store17 duplicate layers: exit 2", code == 2, f"exit={code}")
        check(
            "store17 duplicate layers: memory_contract critical mentions layers",
            any(
                i.get("id") == "memory_contract" and "layers" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        # Empty legacy_types.
        write_schema17({"layers": ["frame", "gist", "memory"], "legacy_types": []})
        code, payload = run_json(["compile", "--root", str(store17), "--json"])
        check("store17 empty legacy_types: exit 2", code == 2, f"exit={code}")
        check(
            "store17 empty legacy_types: memory_contract critical mentions legacy_types",
            any(
                i.get("id") == "memory_contract" and "legacy_types" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        # Duplicate legacy_types.
        write_schema17(
            {"layers": ["frame", "gist", "memory"], "legacy_types": ["document", "document"]}
        )
        code, payload = run_json(["compile", "--root", str(store17), "--json"])
        check("store17 duplicate legacy_types: exit 2", code == 2, f"exit={code}")
        check(
            "store17 duplicate legacy_types: memory_contract critical mentions legacy_types",
            any(
                i.get("id") == "memory_contract" and "legacy_types" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        # Extra key while layers/legacy_types are the exact legal lists.
        write_schema17(
            {
                "layers": ["frame", "gist", "memory"],
                "legacy_types": ["document"],
                "note": "unexpected",
            }
        )
        code, payload = run_json(["compile", "--root", str(store17), "--json"])
        check("store17 extra key: exit 2", code == 2, f"exit={code}")
        check(
            "store17 extra key: memory_contract critical mentions the key",
            any(
                i.get("id") == "memory_contract" and "note" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        # Extra key while layers/legacy_types are absent.
        write_schema17({"foo": "bar"})
        code, payload = run_json(["compile", "--root", str(store17), "--json"])
        check("store17 extra key (absent layers/legacy_types): exit 2", code == 2, f"exit={code}")
        check(
            "store17 extra key (absent layers/legacy_types): memory_contract critical mentions the key",
            any(
                i.get("id") == "memory_contract" and "foo" in (i.get("msg") or "")
                for i in payload.get("critical", [])
            ),
            f"critical={payload.get('critical')}",
        )

        # Restore exact layers/legacy_types: no memory_contract critical.
        write_schema17({"layers": ["frame", "gist", "memory"], "legacy_types": ["document"]})
        code, payload = run_json(["compile", "--root", str(store17), "--json"])
        check(
            "store17 restored exact layers/legacy_types: no memory_contract critical",
            "memory_contract" not in findings_by_id(payload, "critical"),
            f"critical={payload.get('critical')}",
        )

        # Sanity: memory_contract never uses the schema_v2 id on SCHEMA 1.0.
        check(
            "store17 never emits schema_v2 critical (SCHEMA 1.0)",
            "schema_v2" not in findings_by_id(payload, "critical"),
            f"critical={payload.get('critical')}",
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
        recall_text = (ROOT / "references/paths/recall.md").read_text(encoding="utf-8")
        check(
            "recall.md mentions index.md, frame, gist, memory, and atlas recall run",
            all(
                term in recall_text
                for term in ("index.md", "frame", "gist", "memory", "atlas recall run")
            ),
        )
        check(
            "recall.md still requires recall_cmd on exit",
            "recall_cmd" in recall_text
            and "without `recall_cmd`" in recall_text
            and "incomplete Exit" in recall_text,
        )
        check(
            "recall.md still tells the reader to stop when the gist answers",
            "Stop at the gist when it answers the ask" in recall_text,
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
