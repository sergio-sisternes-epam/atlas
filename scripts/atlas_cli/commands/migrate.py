from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..core.schema import load_schema, staging_dir_name
from ..core.paths import rel, store_root


def run(
    root: str | None,
    source: str,
    into: str | None = None,
    as_json: bool = False,
) -> int:
    """Copy external/old content into staging only. Never compiles."""
    r = store_root(root)
    schema, schema_err = load_schema(r)
    if schema_err:
        print(f"CRITICAL: {schema_err} — refuse migrate without SCHEMA.json")
        return 2

    staging_name = into or staging_dir_name(schema)
    staging = r / staging_name
    staging.mkdir(parents=True, exist_ok=True)

    src = Path(source).expanduser().resolve()
    if not src.exists():
        print(f"CRITICAL: source not found: {src}")
        return 2

    copied: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _copy_file(f: Path, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f.name
        # avoid clobber: add suffix if exists
        if dest.exists():
            stem, suf = dest.stem, dest.suffix
            n = 1
            while dest.exists():
                dest = dest_dir / f"{stem}-{n}{suf}"
                n += 1
        shutil.copy2(f, dest)
        # lightweight provenance sidecar for non-md or always for md as comment? 
        # For md, prepend is invasive; write a small .provenance.json next to it
        prov = dest.with_suffix(dest.suffix + ".provenance.json")
        prov.write_text(
            json.dumps(
                {
                    "migrated_at": now,
                    "source": str(src if src.is_file() else f),
                    "original_name": f.name,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return dest

    if src.is_file():
        dest = _copy_file(src, staging)
        copied.append(rel(r, dest))
    else:
        for f in sorted(src.rglob("*")):
            if not f.is_file():
                continue
            # keep relative structure under staging
            try:
                rel_part = f.relative_to(src)
            except ValueError:
                rel_part = Path(f.name)
            dest = _copy_file(f, staging / rel_part.parent)
            copied.append(rel(r, dest))

    result = {
        "root": str(r),
        "source": str(src),
        "staging_dir": staging_name,
        "copied": copied,
        "count": len(copied),
        "note": "Content is in staging only. Agent must compile into concept pages; atlas compile fails until staging is empty.",
    }

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"atlas migrate — root={r}")
        print(f"source: {src}")
        print(f"staging: {staging_name}/ ({len(copied)} file(s))")
        for c in copied:
            print(f"  + {c}")
        print()
        print("Next: agent turns staging items into claim-bearing OKF pages,")
        print("      then `atlas compile` must go green (staging empty).")

    return 0
