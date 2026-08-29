from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..core.schema import SCHEMA_NAME, skill_root
from ..core.paths import store_root


DEFAULT_SCHEMA = {
    "schema_version": "1.0",
    "atlas_id": "new-atlas",
    "title": "New Atlas",
    "structure": {
        "free_layout": True,
        "staging_dir": "staging",
        "require_index_in_folders": True,
        "reserved_names": ["index.md", "log.md", "staging"],
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
            "document",
            "protostar",
        ],
        "unconstrained": [],
    },
    "query": {"default_mode": "local", "search_engine": "grep", "fallback": "rg", "staging_visible": False},
}


FM_ONLY = {
    "experience": ["type", "title", "created", "work_id"],
    "decision": ["type", "title", "created"],
    "work": ["type", "title", "created", "work_id"],
    "document": ["type", "title", "created"],
    "protostar": ["type", "title", "created"],
    "lesson": ["type", "title", "created"],
    "recipe": ["type", "title", "created"],
}


def _by_type_block(tname: str) -> dict:
    return {
        "file": f"templates/{tname}.md",
        "frontmatter": {
            "required": FM_ONLY.get(tname, ["type", "title", "created"]),
            "recommended": [],
        },
        "sections": {"required": [], "recommended": []},
    }


def run(root: str | None, force: bool = False, as_json: bool = False) -> int:
    r = store_root(root)
    r.mkdir(parents=True, exist_ok=True)
    schema_path = r / SCHEMA_NAME
    if schema_path.is_file() and not force:
        msg = f"{SCHEMA_NAME} already exists; pass --force to overwrite"
        if as_json:
            print(json.dumps({"ok": False, "error": msg, "root": str(r)}))
        else:
            print(f"atlas init — {msg}")
        return 2

    schema = json.loads(json.dumps(DEFAULT_SCHEMA))
    schema["atlas_id"] = r.name or "new-atlas"
    schema["templates"]["by_type"] = {name: _by_type_block(name) for name in FM_ONLY}
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    tmpl_src = skill_root() / "references" / "templates"
    tmpl_dst = r / "templates"
    tmpl_dst.mkdir(exist_ok=True)
    copied: list[str] = []
    if tmpl_src.is_dir():
        for src in sorted(tmpl_src.glob("*.md")):
            shutil.copy2(src, tmpl_dst / src.name)
            copied.append(src.name)

    index = r / "index.md"
    if not index.is_file() or force:
        index.write_text(
            f"# {schema['atlas_id']}\n\nInitialised by atlas init.\n",
            encoding="utf-8",
        )
    log = r / "log.md"
    if not log.is_file() or force:
        log.write_text("# Log\n\n- init\n", encoding="utf-8")

    payload = {"ok": True, "root": str(r), "schema": SCHEMA_NAME, "templates": copied}
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"atlas init — root={r}")
        print(f"wrote {SCHEMA_NAME} and {len(copied)} templates")
    return 0
