from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

from ..core.frontmatter import read_page, split_fm
from ..core.paths import rel, store_root
from ..core.schema import load_schema, staging_dir_name

CHECKLIST = """
Agent checklist (promote only scaffolds — you must finish compilation):
  [ ] Complete required frontmatter (type, title, … per template / SCHEMA)
  [ ] Write claim-bearing body (not just links)
  [ ] Write relates_to frontmatter (authoritative) with kinds: follows, records, supersedes, implements, derived_from, related
  [ ] Optionally mirror in ## Related for human body reading; agents use frontmatter
  [ ] Update targets' relates_to (backlinks) when the relationship is important
  [ ] Update folder index.md if the stub is insufficient
  [ ] Remove any leftover staging material
  [ ] Run: atlas compile --root <atlas>  → must be green
""".strip()


def _templates_dir(root: Path, schema: dict | None) -> Path:
    # Prefer Atlas skill bundled templates, then store-local templates/
    skill_tpl = Path(__file__).resolve().parents[3] / "references" / "templates"
    if schema:
        t = (schema.get("templates") or {}).get("directory") or "templates/"
        local = root / t
        if local.is_dir():
            return local
    if skill_tpl.is_dir():
        return skill_tpl
    return root / "templates"


def _pick_template(templates: Path, type_hint: str | None, target: Path) -> Path | None:
    # by type name, then by target folder name
    candidates = []
    if type_hint:
        candidates.append(templates / f"{type_hint}.md")
    folder = target.parent.name
    # map common folders
    folder_map = {
        "experiences": "experience",
        "experience": "experience",
        "decisions": "decision",
        "decision": "decision",
        "recipes": "recipe",
        "work": "work",
    }
    mapped = folder_map.get(folder)
    if mapped:
        candidates.append(templates / f"{mapped}.md")
    candidates.append(templates / f"{target.stem}.md")
    for c in candidates:
        if c.is_file():
            return c
    # any single default
    for c in sorted(templates.glob("*.md")):
        return c
    return None


def _fill_skeleton(skel: str, title: str, source_name: str) -> str:
    meta, body = split_fm(skel)
    today = date.today().isoformat()
    # pre-fill empty common keys
    if "title" in meta and not str(meta.get("title") or "").strip():
        meta["title"] = title
    if "created" in meta and not str(meta.get("created") or "").strip():
        meta["created"] = today
    if "status" in meta and not str(meta.get("status") or "").strip():
        meta["status"] = "raw"
    # rebuild frontmatter simply
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            if not v:
                lines.append("  []")
            else:
                for item in v:
                    lines.append(f"  - {item}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    note = f"\n<!-- promoted from staging:{source_name} on {today} — complete claims and links -->\n"
    return "\n".join(lines) + note + body


def _ensure_index_stub(root: Path, target: Path, title: str) -> str | None:
    index = target.parent / "index.md"
    link = target.name
    entry = f"- [{title}]({link}) — promoted (complete me)\n"
    if not index.exists():
        index.write_text(
            f"# {target.parent.name}\n\n{entry}",
            encoding="utf-8",
        )
        return rel(root, index)
    text = index.read_text(encoding="utf-8", errors="replace")
    if link in text or target.stem in text:
        return None
    with index.open("a", encoding="utf-8") as f:
        if not text.endswith("\n"):
            f.write("\n")
        f.write(entry)
    return rel(root, index)


def run(
    root: str | None,
    staging_file: str,
    to: str,
    type_hint: str | None = None,
    as_json: bool = False,
) -> int:
    """Scaffold durable page from template; agent must finish claims/links."""
    r = store_root(root)
    schema, schema_err = load_schema(r)
    if schema_err:
        print(f"CRITICAL: {schema_err}")
        return 2

    staging_name = staging_dir_name(schema)
    src = Path(staging_file)
    if not src.is_absolute():
        # try relative to root, then to staging/
        cand = (r / src).resolve()
        if not cand.exists():
            cand = (r / staging_name / src).resolve()
        src = cand
    else:
        src = src.resolve()

    if not src.is_file():
        print(f"CRITICAL: staging file not found: {src}")
        return 2

    # must be under staging
    staging_root = (r / staging_name).resolve()
    try:
        src.relative_to(staging_root)
    except ValueError:
        print(f"CRITICAL: source is not under {staging_name}/: {src}")
        return 2

    target = (r / to).resolve() if not Path(to).is_absolute() else Path(to).resolve()
    try:
        target.relative_to(r.resolve())
    except ValueError:
        print(f"CRITICAL: target outside atlas root: {target}")
        return 2

    if target.exists():
        print(f"CRITICAL: target already exists: {rel(r, target)}")
        return 2

    templates = _templates_dir(r, schema)
    tpl = _pick_template(templates, type_hint, target)
    title_guess = target.stem.replace("-", " ").replace("_", " ").strip() or src.stem

    if tpl:
        skel = tpl.read_text(encoding="utf-8", errors="replace")
        content = _fill_skeleton(skel, title_guess, src.name)
        template_used = str(tpl)
    else:
        # minimal OKF page
        content = (
            f"---\ntype: note\ntitle: {title_guess}\ncreated: {date.today().isoformat()}\n---\n\n"
            f"<!-- promoted from staging:{src.name} — complete claims and links -->\n\n"
            f"## Summary\n\n"
        )
        template_used = None

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    index_touched = _ensure_index_stub(r, target, title_guess)

    # remove staging file + provenance sidecar if present
    removed = [rel(r, src)]
    src.unlink(missing_ok=True)
    prov = Path(str(src) + ".provenance.json")
    if not prov.exists():
        prov = src.with_suffix(src.suffix + ".provenance.json")
    if prov.exists():
        removed.append(rel(r, prov))
        prov.unlink()

    result = {
        "root": str(r),
        "from": removed[0],
        "to": rel(r, target),
        "template": template_used,
        "index_updated": index_touched,
        "removed_staging": removed,
        "checklist": CHECKLIST,
        "note": "Scaffold only. atlas compile will still fail until body/links satisfy schema.",
    }

    if as_json:
        import json

        print(json.dumps(result, indent=2))
    else:
        print(f"atlas promote — root={r}")
        print(f"from: {removed[0]}")
        print(f"to:   {rel(r, target)}")
        if template_used:
            print(f"template: {template_used}")
        if index_touched:
            print(f"index: {index_touched} (stub entry added)")
        print()
        print(CHECKLIST)

    return 0
