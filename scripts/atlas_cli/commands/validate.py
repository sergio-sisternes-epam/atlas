from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.frontmatter import is_just_links, read_page
from ..core.paths import RESERVED, iter_concept_md, rel, staging_files, store_root
from ..core.mesh import consolidate as mesh_consolidate
from ..core.identity import IdentityError, parse_pointer
from ..core.meshfile import MeshFileError, find_project_root, known_ids
from ..core.overlay import merge_overlays, receipt_issues
from ..core.schema import (
    by_type_map,
    load_contract,
    load_schema,
    min_body_chars,
    page_contract,
    recommended_without_contract,
    staging_dir_name,
    validate_against_contract,
    validate_schema_shape,
)

# Inline ignore: <!-- atlas-ignore: rule_id -->
IGNORE_RE = re.compile(r"<!--\s*atlas-ignore:\s*([a-z0-9_\-]+)\s*-->", re.I)
MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")


def _ignores_in(text: str) -> set[str]:
    return {m.group(1).lower() for m in IGNORE_RE.finditer(text)}


def _check_internal_links(root: Path, path: Path, body: str) -> list[dict]:
    issues: list[dict] = []
    parent = path.parent
    for m in MD_LINK.finditer(body):
        target = m.group(2).strip()
        if target.startswith(("http://", "https://", "mailto:", "atlas://", "#")):
            continue
        # strip optional title
        target = target.split()[0].strip("\"'")
        cand = (parent / target).resolve()
        if not cand.exists():
            # try as root-relative
            cand2 = (root / target.lstrip("/")).resolve()
            if not cand2.exists():
                issues.append(
                    {
                        "id": "internal_links",
                        "path": rel(root, path),
                        "msg": f"broken link: {target}",
                    }
                )
    return issues


def _folders_needing_index(root: Path, staging_dir: str) -> list[Path]:
    """Dirs that contain concept .md files (not only index/log) should have index.md."""
    need: list[Path] = []
    skip_top = {staging_dir, "templates", "mesh", ".atlas-index", "schema.d"}
    for d in sorted(root.rglob("*")):
        if not d.is_dir():
            continue
        try:
            parts = d.resolve().relative_to(root.resolve()).parts
        except ValueError:
            continue
        if parts and parts[0] in skip_top:
            continue
        if d == root:
            continue
        leaves = [
            f
            for f in d.iterdir()
            if f.is_file() and f.suffix == ".md" and f.name not in RESERVED
        ]
        if leaves and not (d / "index.md").is_file():
            need.append(d)
    return need



def _check_relates_to(root: Path, path: Path, meta: dict) -> list[dict]:
    issues: list[dict] = []
    rels = meta.get("relates_to")
    if not rels:
        return issues
    if not isinstance(rels, list):
        issues.append(
            {
                "id": "relates_to",
                "path": rel(root, path),
                "msg": "relates_to must be a list of {path, role} objects",
            }
        )
        return issues
    for i, item in enumerate(rels):
        if not isinstance(item, dict):
            # frontmatter parser may give strings; tolerate "path" only forms later
            continue
        target = str(item.get("path") or "").strip()
        if not target:
            issues.append(
                {
                    "id": "relates_to",
                    "path": rel(root, path),
                    "msg": f"relates_to[{i}] missing path",
                }
            )
            continue
        if target.startswith(("http://", "https://", "atlas://")):
            continue
        cand = (root / target).resolve()
        if not cand.exists():
            issues.append(
                {
                    "id": "relates_to",
                    "path": rel(root, path),
                    "msg": f"relates_to broken path: {target}",
                }
            )
    return issues


def _has_kind(meta: dict, kind: str) -> bool:
    rels = meta.get("relates_to")
    if not isinstance(rels, list):
        return False
    want = kind.strip().lower()
    for item in rels:
        if not isinstance(item, dict):
            continue
        k = str(item.get("kind") or item.get("role") or "").strip().lower()
        if k == want and str(item.get("path") or "").strip():
            return True
    return False


def _page_contract_issues(root: Path, path: Path, meta: dict, schema: dict) -> list[dict]:
    issues: list[dict] = []
    rp = rel(root, path)
    ptype = str(meta.get("type") or "").strip()
    by_type = by_type_map(schema)
    block = by_type.get(ptype) if ptype else None
    if isinstance(block, dict):
        required = ((block.get("frontmatter") or {}).get("required")) or []
        for key in required:
            if not str(meta.get(key) or "").strip():
                issues.append(
                    {
                        "id": "page_contract",
                        "path": rp,
                        "msg": f"type {ptype} missing required frontmatter '{key}'",
                    }
                )

    pc = page_contract(schema)
    work_id = str(meta.get("work_id") or "").strip()
    when_work = pc.get("when_work_id") or {}
    if work_id and isinstance(when_work, dict) and ptype != "work":
        need = str(when_work.get("require_kind") or "implements").strip()
        if need and not _has_kind(meta, need):
            issues.append(
                {
                    "id": "page_contract",
                    "path": rp,
                    "msg": f"work_id set but no relates_to kind={need}",
                }
            )

    when_type = pc.get("when_type") or {}
    if ptype and isinstance(when_type, dict):
        rule = when_type.get(ptype) or {}
        if isinstance(rule, dict):
            need = str(rule.get("require_kind") or "").strip()
            if need and not _has_kind(meta, need):
                issues.append(
                    {
                        "id": "page_contract",
                        "path": rp,
                        "msg": f"type {ptype} missing relates_to kind={need}",
                    }
                )

    forming_type = str(pc.get("forming_requires_type") or "").strip()
    kva = str(meta.get("kva") or "").strip()
    from_types = pc.get("forming_from_types")
    if from_types is None:
        from_types = ["document"]
    if (
        forming_type
        and kva == "forming"
        and ptype
        and ptype != forming_type
        and (not from_types or ptype in from_types)
    ):
        issues.append(
            {
                "id": "page_contract",
                "path": rp,
                "msg": f"kva=forming requires type={forming_type} (got {ptype})",
            }
        )
    return issues


def _resolve_focus_path(root: Path, path_prefix: str) -> tuple[Path | None, str | None]:
    raw = path_prefix.strip()
    if not raw:
        return None, "--path is empty"
    p = Path(raw)
    cand = p.resolve() if p.is_absolute() else (root / raw).resolve()
    try:
        cand.relative_to(root.resolve())
    except ValueError:
        return None, f"--path escapes atlas root: {path_prefix}"
    if not cand.exists():
        return None, f"--path not found: {path_prefix}"
    return cand, None


def _in_focus(
    path: Path,
    meta: dict,
    type_name: str | None,
    focus_path: Path | None,
) -> bool:
    if type_name and str(meta.get("type") or "").strip() != type_name.strip():
        return False
    if focus_path is not None:
        try:
            path.resolve().relative_to(focus_path)
        except ValueError:
            return False
    return True


def _unknown_atlas_uri_warnings(root: Path) -> list[dict]:
    issues: list[dict] = []
    try:
        ids = known_ids(find_project_root(root))
    except MeshFileError:
        ids = set()
    seen: set[str] = set()
    for path in root.rglob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in re.finditer(r"atlas://[^\s)\]\"']+", text):
            raw = m.group(0).rstrip(".,;`'\"")
            try:
                aid = parse_pointer(raw).atlas_id
            except IdentityError:
                continue
            if aid in ids or aid in seen:
                continue
            seen.add(aid)
            issues.append(
                {
                    "id": "atlas_uri_unmounted",
                    "path": rel(root, path),
                    "msg": f"atlas:// id not in atlas-mesh.json: {aid}",
                    "severity": "warning",
                }
            )
    return issues


def run(
    root: str | None,
    as_json: bool = False,
    type_name: str | None = None,
    path_prefix: str | None = None,
) -> int:
    r = store_root(root)
    critical: list[dict] = []
    warnings: list[dict] = []
    focused_pages: list[dict] = []
    want_type = type_name.strip() if type_name else None
    want_path = path_prefix.strip() if path_prefix else None
    focused = bool(want_type or want_path)
    focus_path: Path | None = None

    schema, schema_err = load_schema(r)
    if schema_err:
        critical.append({"id": "schema_present", "path": "SCHEMA.json", "msg": schema_err})
        schema = None
    else:
        assert schema is not None
        for msg in validate_schema_shape(schema):
            critical.append({"id": "schema_shape", "path": "SCHEMA.json", "msg": msg})
        merged, ov_crit, ov_warn = merge_overlays(schema, r)
        critical.extend(ov_crit)
        warnings.extend(ov_warn)
        critical.extend(receipt_issues(r))
        schema = merged
        for msg in validate_schema_shape(schema):
            critical.append({"id": "schema_shape", "path": "SCHEMA.json", "msg": msg})
        for msg in validate_against_contract(schema, load_contract()):
            critical.append({"id": "schema_contract", "path": "SCHEMA.json", "msg": msg})

    staging_name = staging_dir_name(schema)
    min_body = min_body_chars(schema)

    # mesh consolidate (when fragments present)
    mesh_result = mesh_consolidate(r)
    critical.extend(mesh_result.get("critical") or [])
    warnings.extend(mesh_result.get("warnings") or [])
    warnings.extend(_unknown_atlas_uri_warnings(r))

    # staging must be empty
    staged = staging_files(r, staging_name)
    if staged:
        for p in staged:
            critical.append(
                {
                    "id": "no_answerable_in_staging",
                    "path": rel(r, p),
                    "msg": "staging is not empty — compile-in-place required before green",
                }
            )

    skip_pages = False
    if want_path:
        focus_path, path_err = _resolve_focus_path(r, want_path)
        if path_err:
            critical.append({"id": "focus_path", "path": want_path, "msg": path_err})
            focus_path = None
            skip_pages = True

    # concept pages
    for path in iter_concept_md(r, staging_name):
        if skip_pages:
            break
        text = path.read_text(encoding="utf-8", errors="replace")
        ignores = _ignores_in(text)
        meta, body = read_page(path)

        if path.name in RESERVED:
            # index.md / log.md are allowed; they should not be ordinary concepts
            continue

        if focused:
            if meta:
                if not _in_focus(path, meta, want_type, focus_path):
                    continue
            else:
                if want_type:
                    continue
                if focus_path is not None:
                    try:
                        path.resolve().relative_to(focus_path)
                    except ValueError:
                        continue
            focused_pages.append(
                {
                    "path": rel(r, path),
                    "title": str((meta or {}).get("title") or ""),
                    "type": str((meta or {}).get("type") or ""),
                }
            )

        if not meta:
            if "frontmatter" not in ignores:
                critical.append(
                    {"id": "frontmatter", "path": rel(r, path), "msg": "missing frontmatter"}
                )
            continue

        if not str(meta.get("type") or "").strip():
            if "frontmatter" not in ignores and "okf_compliance" not in ignores:
                critical.append(
                    {"id": "okf_compliance", "path": rel(r, path), "msg": "missing type"}
                )

        if is_just_links(body, min_body):
            if "not_just_links" not in ignores:
                critical.append(
                    {
                        "id": "not_just_links",
                        "path": rel(r, path),
                        "msg": f"body has < {min_body} non-link prose chars (thin / link-list page)",
                    }
                )

        for issue in _check_internal_links(r, path, body):
            if "internal_links" not in ignores:
                critical.append(issue)

        if "relates_to" not in ignores:
            for issue in _check_relates_to(r, path, meta):
                critical.append(issue)

        if schema:
            for issue in _page_contract_issues(r, path, meta, schema):
                rid = issue.get("id") or ""
                if rid not in ignores:
                    warnings.append(issue)

    if schema:
        for tname in recommended_without_contract(schema):
            warnings.append(
                {
                    "id": "schema_type_contract",
                    "path": "SCHEMA.json",
                    "msg": f"recommended type '{tname}' has no templates.by_type frontmatter.required and is not types.unconstrained",
                }
            )

    # progressive disclosure
    require_index = True
    if schema:
        structure = schema.get("structure") or {}
        require_index = bool(structure.get("require_index_in_folders", True))
    if require_index:
        for d in _folders_needing_index(r, staging_name):
            warnings.append(
                {
                    "id": "index_md_present",
                    "path": rel(r, d),
                    "msg": "folder has concept pages but no index.md",
                }
            )

    # root index recommended
    if not (r / "index.md").is_file():
        warnings.append(
            {"id": "index_md_present", "path": "index.md", "msg": "root index.md missing"}
        )

    result = {
        "root": str(r),
        "ok": len(critical) == 0,
        "critical": critical,
        "warnings": warnings,
        "staging_dir": staging_name,
        "staging_count": len(staged),
        "type": want_type,
        "path": want_path,
        "page_count": len(focused_pages) if focused else None,
        "pages": focused_pages if focused else None,
        "mesh": {
            "fragment_count": mesh_result.get("fragment_count", 0),
            "written": mesh_result.get("written"),
            "atlas_count": mesh_result.get("atlas_count"),
            "note": mesh_result.get("note"),
        },
    }

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"atlas validate — root={r}")
        if critical:
            print(f"CRITICAL ({len(critical)}):")
            for i in critical:
                print(f"  [{i['id']}] {i['path']}: {i['msg']}")
        if warnings:
            print(f"WARNINGS ({len(warnings)}):")
            for i in warnings:
                print(f"  [{i['id']}] {i['path']}: {i['msg']}")
        mesh_note = mesh_result.get("written") or mesh_result.get("note")
        if mesh_note:
            print(f"mesh: {mesh_note}")
        if not critical and not warnings:
            print("ok — no issues")
        elif not critical:
            print("ok — warnings only")
        else:
            print("FAIL — critical issues present")
        if focused:
            bits = []
            if want_type:
                bits.append(f"type={want_type}")
            if want_path:
                bits.append(f"path={want_path}")
            bits.append(f"pages={len(focused_pages)}")
            print("scope: " + " ".join(bits))
            for h in focused_pages:
                title = f"  {h['title']}" if h.get("title") else ""
                print(f"  {h['path']}{title}")

    if critical:
        return 2
    if warnings:
        return 1
    return 0
