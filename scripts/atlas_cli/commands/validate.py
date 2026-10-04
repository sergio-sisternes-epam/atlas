from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.frontmatter import FrontmatterError, is_just_links, parse_page, read_page
from ..core.paths import RESERVED, iter_concept_md, rel, staging_files, store_root
from ..core.mesh import consolidate as mesh_consolidate
from ..core.identity import IdentityError, parse_pointer
from ..core.meshfile import MeshFileError, find_project_root, known_ids
from ..core.overlay import merge_overlays, receipt_issues
from ..core.recall_config import recall_enabled, schema_version, validate_store_v2
from ..core.recall_index import IndexError_, publish_generation
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
NON_BLOCKING_WARNING_IDS = {"atlas_uri_unmounted"}

# Memory layers (page / gist / frame) are pinned here, not read from the store.
GIST_PARENT_TYPES = frozenset(
    {"experience", "decision", "lesson", "recipe", "document", "page", "protostar"}
)
MISSING_GIST_TYPES = GIST_PARENT_TYPES - {"protostar"}


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
        path_part = target
        for sep in ("#", "?"):
            idx = path_part.find(sep)
            if idx != -1:
                path_part = path_part[:idx]
        if not path_part:
            continue
        cand = (parent / path_part).resolve()
        if not cand.exists():
            # try as root-relative
            cand2 = (root / path_part.lstrip("/")).resolve()
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



def _bad_relation_ref(value: object) -> str | None:
    """Relation ref is a per-edge git rev, not mount ref. Compile does not resolve it."""
    if not isinstance(value, str):
        return "ref must be a git rev string"
    if not value or value.strip() != value or any(ch.isspace() for ch in value) or value.startswith("-"):
        return "ref must be a non-empty git rev without whitespace"
    return None


def _relation_path_escapes(root: Path, target: str) -> bool:
    text = target.replace("\\", "/").strip()
    if not text or text.startswith(("/", "-")):
        return True
    cand = (root / text).resolve(strict=False)
    try:
        rel_path = cand.relative_to(root.resolve())
    except ValueError:
        return True
    return not rel_path.parts or any(part == ".." for part in rel_path.parts)


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
        if "ref" in item:
            ref_problem = _bad_relation_ref(item.get("ref"))
            if ref_problem:
                issues.append(
                    {
                        "id": "relates_to",
                        "path": rel(root, path),
                        "msg": f"relates_to[{i}] {ref_problem}",
                    }
                )
            if target.startswith(("http://", "https://", "atlas://")):
                issues.append(
                    {
                        "id": "relates_to",
                        "path": rel(root, path),
                        "msg": f"relates_to[{i}] ref path must be store-relative: {target}",
                    }
                )
            elif _relation_path_escapes(root, target):
                issues.append(
                    {
                        "id": "relates_to",
                        "path": rel(root, path),
                        "msg": f"relates_to[{i}] path escapes store root: {target}",
                    }
                )
            # History edge. Containment is checked. Do not resolve the blob or require HEAD.
            continue
        if target.startswith(("http://", "https://", "atlas://")):
            continue
        if _relation_path_escapes(root, target):
            issues.append(
                {
                    "id": "relates_to",
                    "path": rel(root, path),
                    "msg": f"relates_to[{i}] path escapes store root: {target}",
                }
            )
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
        if str(item.get("ref") or "").strip():
            continue
        if k == want and str(item.get("path") or "").strip():
            return True
    return False


def schema_compile_issues(root: Path) -> tuple[dict | None, list[dict], list[dict]]:
    """Schema-level compile issues. Schema is None when page checks must not use it."""
    critical: list[dict] = []
    warnings: list[dict] = []
    schema, schema_err = load_schema(root)
    if schema_err:
        critical.append({"id": "schema_present", "path": "SCHEMA.json", "msg": schema_err})
        return None, critical, warnings
    tmpl = schema.get("templates")
    if tmpl is not None and not isinstance(tmpl, dict):
        critical.append(
            {
                "id": "schema_shape",
                "path": "SCHEMA.json",
                "msg": "SCHEMA.templates must be an object",
            }
        )
    elif isinstance(tmpl, dict):
        by = tmpl.get("by_type")
        if by is not None and not isinstance(by, dict):
            critical.append(
                {
                    "id": "schema_shape",
                    "path": "SCHEMA.json",
                    "msg": "SCHEMA.templates.by_type must be an object",
                }
            )
    merged, overlay_critical, overlay_warnings = merge_overlays(schema, root)
    critical.extend(overlay_critical)
    warnings.extend(overlay_warnings)
    critical.extend(receipt_issues(root))
    shape_msgs = validate_schema_shape(merged)
    for msg in shape_msgs:
        critical.append({"id": "schema_shape", "path": "SCHEMA.json", "msg": msg})
    if shape_msgs:
        return None, critical, warnings
    for msg in validate_against_contract(merged, load_contract()):
        critical.append({"id": "schema_contract", "path": "SCHEMA.json", "msg": msg})
    if schema_version(merged) == "2.0":
        for msg in validate_store_v2(merged):
            critical.append({"id": "schema_v2", "path": "SCHEMA.json", "msg": msg})
    return merged, critical, warnings


def concept_page_errors(root: Path, path: Path, text: str | None = None) -> list[str]:
    """Compile-blocking messages for one concept page. Empty means this page would not fail compile."""
    schema, schema_issues, _schema_warnings = schema_compile_issues(root)
    msgs = [issue["msg"] for issue in schema_issues if issue.get("msg")]
    if text is None:
        text = path.read_text(encoding="utf-8", errors="replace")
    ignores = _ignores_in(text)
    try:
        meta, body = parse_page(text, schema_version(schema) if schema else "1.0")
    except FrontmatterError as e:
        return msgs + [str(e)]
    if not meta:
        if "frontmatter" not in ignores:
            msgs.append("missing frontmatter")
        return msgs
    if not str(meta.get("type") or "").strip() and "frontmatter" not in ignores and "okf_compliance" not in ignores:
        msgs.append("missing type")
    if is_just_links(body, min_body_chars(schema)) and "not_just_links" not in ignores:
        msgs.append(f"body has < {min_body_chars(schema)} non-link prose chars (thin / link-list page)")
    if "internal_links" not in ignores:
        msgs.extend(issue["msg"] for issue in _check_internal_links(root, path, body))
    if "relates_to" not in ignores:
        msgs.extend(issue["msg"] for issue in _check_relates_to(root, path, meta))
    if schema and "page_contract" not in ignores:
        msgs.extend(issue["msg"] for issue in _page_contract_issues(root, path, meta, schema))
    return msgs


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


def _memory_rung(schema: dict | None) -> tuple[str, list[dict]]:
    """Resolve the memory rung (info|warn|error) plus any shape-critical issues.

    No memory key, a memory object with no/empty rung, or any shape problem
    all resolve to info (and a malformed memory block also raises a critical
    memory_rung issue while still treating the ladder as info).

    Distinguish absent/blank string from a non-string rung value: falsey
    non-strings (0, false, [], {}) must not collapse via ``or ""`` into an
    absent rung on SCHEMA 1.0 stores that skip the v2 JSON Schema check.
    """
    if not schema:
        return "info", []
    memory = schema.get("memory")
    if memory is None:
        return "info", []
    if not isinstance(memory, dict):
        return "info", [
            {
                "id": "memory_rung",
                "path": "SCHEMA.json",
                "msg": "SCHEMA.memory must be an object; treating memory rung as info",
            }
        ]
    if "rung" not in memory or memory.get("rung") is None:
        return "info", []
    raw = memory["rung"]
    if not isinstance(raw, str):
        return "info", [
            {
                "id": "memory_rung",
                "path": "SCHEMA.json",
                "msg": (
                    "SCHEMA.memory.rung must be a string (info, warn, or error); "
                    f"got {type(raw).__name__} {raw!r}; treating memory rung as info"
                ),
            }
        ]
    rung = raw.strip().lower()
    if not rung:
        return "info", []
    if rung not in ("info", "warn", "error"):
        return "info", [
            {
                "id": "memory_rung",
                "path": "SCHEMA.json",
                "msg": (
                    f"SCHEMA.memory.rung must be info, warn, or error (got {rung!r}); "
                    "treating memory rung as info"
                ),
            }
        ]
    return rung, []


_MEMORY_ALLOWED_KEYS = frozenset({"rung", "layers", "legacy_types"})
_MEMORY_LAYERS_FIXED = ["frame", "gist", "page"]
_MEMORY_LEGACY_TYPES_FIXED = ["document"]


def _memory_contract(schema: dict | None) -> list[dict]:
    """Enforce the fixed memory.layers / memory.legacy_types contract on SCHEMA 1.0.

    SCHEMA 2.0 stores already enforce this (and more) via validate_store_v2
    against the store-v2 JSON Schema, so this check only runs for stores that
    are not 2.0 (the default 1.0 contract, or any other non-2.0 value).
    """
    if not schema:
        return []
    memory = schema.get("memory")
    if not isinstance(memory, dict):
        return []
    findings: list[dict] = []
    extra_keys = sorted(set(memory.keys()) - _MEMORY_ALLOWED_KEYS)
    for key in extra_keys:
        findings.append(
            {
                "id": "memory_contract",
                "path": "SCHEMA.json",
                "msg": f"SCHEMA.memory has an unexpected key: {key!r}",
            }
        )
    if "layers" in memory:
        layers = memory["layers"]
        if layers != _MEMORY_LAYERS_FIXED:
            findings.append(
                {
                    "id": "memory_contract",
                    "path": "SCHEMA.json",
                    "msg": (
                        "SCHEMA.memory.layers must be exactly "
                        f"{_MEMORY_LAYERS_FIXED!r} (got {layers!r})"
                    ),
                }
            )
    if "legacy_types" in memory:
        legacy_types = memory["legacy_types"]
        if legacy_types != _MEMORY_LEGACY_TYPES_FIXED:
            findings.append(
                {
                    "id": "memory_contract",
                    "path": "SCHEMA.json",
                    "msg": (
                        "SCHEMA.memory.legacy_types must be exactly "
                        f"{_MEMORY_LEGACY_TYPES_FIXED!r} (got {legacy_types!r})"
                    ),
                }
            )
    return findings


def _memory_findings(root: Path, schema: dict | None, staging_name: str) -> list[dict]:
    """Legacy-document and memory-layer (gist/frame) findings.

    Pages are read once here, independent of the main compile loop, so these
    findings do not depend on iteration order or on other checks succeeding.
    """
    pages: list[tuple[Path, dict]] = []
    for path in iter_concept_md(root, staging_name):
        if path.name in RESERVED:
            continue
        try:
            meta, _ = read_page(path, schema_version(schema) if schema else "1.0")
        except FrontmatterError:
            continue
        if not meta:
            continue
        pages.append((path, meta))

    by_rel_path = {rel(root, p): (p, m) for p, m in pages}

    def _related(meta: dict, kind: str) -> list[dict]:
        out: list[dict] = []
        rels = meta.get("relates_to")
        if not isinstance(rels, list):
            return out
        for item in rels:
            if not isinstance(item, dict):
                continue
            if str(item.get("kind") or item.get("role") or "").strip().lower() == kind:
                out.append(item)
        return out

    def _canonical_local_target(target: str) -> str | None:
        """Resolve a relates_to target to the canonical store-relative key.

        Mirrors the resolution ``_check_relates_to`` uses: remote references
        (http(s):// or atlas://) are left alone (handled elsewhere), and any
        local target is resolved against the store root so it matches the
        page index built from ``rel()``. Targets that resolve outside the
        store root are not treated as local page keys.
        """
        if not target or target.startswith(("http://", "https://", "atlas://")):
            return None
        resolved_root = root.resolve()
        cand = (root / target).resolve()
        try:
            cand.relative_to(resolved_root)
        except ValueError:
            return None
        return str(cand.relative_to(resolved_root)).replace("\\", "/")

    def _valid_gist_parent(m: dict) -> str | None:
        """Return the canonical parent path for a well-formed gist, else None.

        A gist only counts toward ``gist_parent`` coverage when it has
        exactly one ``derived_from`` parent, that parent resolves to a page
        inside the store, and the parent's type is a valid gist-parent type
        (not itself a gist). This mirrors the ``gist_parent`` ok check below
        so a malformed gist (zero/two+ parents, gist-of-gist, outside the
        store, wrong type) never suppresses ``missing_gist`` for its target.
        """
        parents = _related(m, "derived_from")
        if len(parents) != 1:
            return None
        target = str(parents[0].get("path") or "").strip()
        if not target:
            return None
        canon = _canonical_local_target(target)
        found = by_rel_path.get(canon if canon is not None else target)
        if found is None:
            return None
        _, tmeta = found
        ttype = str(tmeta.get("type") or "").strip()
        if ttype not in GIST_PARENT_TYPES:
            return None
        return canon if canon is not None else target

    # Index gists by the path of the parent they are derived_from — only for
    # valid single-parent gists; a malformed gist must not suppress the
    # target's missing_gist finding.
    gists_by_parent: dict[str, list[str]] = {}
    for p, m in pages:
        if str(m.get("type") or "").strip() != "gist":
            continue
        gp = rel(root, p)
        canon = _valid_gist_parent(m)
        if canon is not None:
            gists_by_parent.setdefault(canon, []).append(gp)

    findings: list[dict] = []
    for p, m in pages:
        ptype = str(m.get("type") or "").strip()
        rp = rel(root, p)

        if ptype == "document":
            findings.append(
                {
                    "id": "legacy_document",
                    "path": rp,
                    "msg": (
                        "type document is a legacy durable object; consider migrating "
                        "toward page/gist via path memory-migrate. The page is not "
                        "rewritten automatically."
                    ),
                }
            )

        if ptype in MISSING_GIST_TYPES and not gists_by_parent.get(rp):
            findings.append(
                {
                    "id": "missing_gist",
                    "path": rp,
                    "msg": "no gist is derived_from this page.",
                }
            )

        if ptype == "gist":
            if _valid_gist_parent(m) is None:
                findings.append(
                    {
                        "id": "gist_parent",
                        "path": rp,
                        "msg": (
                            "a gist has exactly one parent, and that parent is not "
                            "a gist (parent must be experience, decision, lesson, "
                            "recipe, document, page, or protostar)."
                        ),
                    }
                )

        if ptype == "frame":
            gist_paths: set[str] = set()
            invalid = False
            for item in _related(m, "related"):
                target = str(item.get("path") or "").strip()
                if not target:
                    invalid = True
                    continue
                canon = _canonical_local_target(target)
                lookup_key = canon if canon is not None else target
                found = by_rel_path.get(lookup_key)
                if found is None:
                    invalid = True
                    continue
                if str(found[1].get("type") or "").strip() != "gist":
                    invalid = True
                    continue
                gist_paths.add(lookup_key)
            if invalid or len(gist_paths) < 2:
                findings.append(
                    {
                        "id": "frame_members",
                        "path": rp,
                        "msg": "a frame lists at least two gists, not pages.",
                    }
                )

    return findings


def run(
    root: str | None,
    as_json: bool = False,
    type_name: str | None = None,
    path_prefix: str | None = None,
    dry_run: bool = False,
) -> int:
    r = store_root(root)
    critical: list[dict] = []
    warnings: list[dict] = []
    info: list[dict] = []
    focused_pages: list[dict] = []
    want_type = type_name.strip() if type_name else None
    want_path = path_prefix.strip() if path_prefix else None
    focused = bool(want_type or want_path)
    focus_path: Path | None = None

    schema, schema_critical, schema_warnings = schema_compile_issues(r)
    critical.extend(schema_critical)
    warnings.extend(schema_warnings)

    staging_name = staging_dir_name(schema)
    min_body = min_body_chars(schema)

    # Resolve --type/--path focus before emitting page-scoped findings so
    # memory findings honour the same intersection as the main page loop.
    skip_pages = False
    if want_path:
        focus_path, path_err = _resolve_focus_path(r, want_path)
        if path_err:
            critical.append({"id": "focus_path", "path": want_path, "msg": path_err})
            focus_path = None
            skip_pages = True

    # Memory rung (page / gist / frame): absent means info; malformed shapes
    # raise a critical memory_rung issue but still treat the ladder as info.
    memory_rung, memory_shape_issues = _memory_rung(schema)
    critical.extend(memory_shape_issues)
    if schema is not None and schema_version(schema) != "2.0":
        critical.extend(_memory_contract(schema))
    allow_inline_ignores = True
    if isinstance(schema, dict):
        compile_cfg = schema.get("compile")
        if isinstance(compile_cfg, dict) and "allow_inline_ignores" in compile_cfg:
            allow_inline_ignores = bool(compile_cfg["allow_inline_ignores"])
    if not skip_pages:
        sv = schema_version(schema) if schema else "1.0"
        for finding in _memory_findings(r, schema, staging_name):
            if allow_inline_ignores:
                fpath_ign = (r / finding["path"]).resolve()
                try:
                    ign_text = fpath_ign.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    ign_text = ""
                if finding["id"] in _ignores_in(ign_text):
                    continue
            if focused:
                fpath = (r / finding["path"]).resolve()
                try:
                    meta, _ = read_page(fpath, sv)
                except FrontmatterError:
                    meta = None
                if meta:
                    if not _in_focus(fpath, meta, want_type, focus_path):
                        continue
                else:
                    if want_type:
                        continue
                    if focus_path is not None:
                        try:
                            fpath.relative_to(focus_path)
                        except ValueError:
                            continue
            if memory_rung == "error":
                finding["severity"] = "critical"
                critical.append(finding)
            elif memory_rung == "warn":
                finding["severity"] = "warning"
                warnings.append(finding)
            else:
                finding["severity"] = "info"
                info.append(finding)

    # mesh consolidate (when fragments present)
    mesh_result = mesh_consolidate(r, write=not dry_run)
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

    # concept pages
    for path in iter_concept_md(r, staging_name):
        if skip_pages:
            break
        text = path.read_text(encoding="utf-8", errors="replace")
        ignores = _ignores_in(text)
        try:
            meta, body = read_page(path, schema_version(schema) if schema else "1.0")
        except FrontmatterError as e:
            critical.append(
                {"id": "frontmatter", "path": rel(r, path), "msg": str(e)}
            )
            continue

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

    index_info = None
    if not focused and not critical and recall_enabled(schema):
        if dry_run:
            index_info = {"published": False, "reason": "dry_run"}
        else:
            try:
                index_info = publish_generation(r, schema, focused=False)
            except (IndexError_, Exception) as e:
                critical.append(
                    {
                        "id": "recall_index",
                        "path": ".atlas-index/recall",
                        "msg": f"failed to publish recall generation: {e}",
                    }
                )

    result = {
        "root": str(r),
        "ok": len(critical) == 0,
        "critical": critical,
        "warnings": warnings,
        "info": info,
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
        "recall_index": index_info,
        "dry_run": dry_run,
        "memory_rung": memory_rung,
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
        if info:
            print(f"INFO ({len(info)}):")
            for i in info:
                print(f"  [{i['id']}] {i['path']}: {i['msg']}")
        mesh_note = mesh_result.get("written") or mesh_result.get("note")
        if mesh_note:
            print(f"mesh: {mesh_note}")
        blocking_warnings = [
            issue
            for issue in warnings
            if issue.get("id") not in NON_BLOCKING_WARNING_IDS
        ]
        if not critical and not warnings and not info:
            print("ok — no issues")
        elif not critical and not warnings:
            print("ok — informational findings only")
        elif not critical and not blocking_warnings:
            print("ok — non-blocking external dependency warnings only")
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
    if any(
        issue.get("id") not in NON_BLOCKING_WARNING_IDS
        for issue in warnings
    ):
        return 1
    return 0
