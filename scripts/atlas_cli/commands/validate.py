from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.frontmatter import FrontmatterError, is_just_links, read_page
from ..core.paths import RESERVED, iter_concept_md, rel, staging_files, store_root
from ..core.mesh import consolidate as mesh_consolidate
from ..core.identity import IdentityError, parse_pointer
from ..core.meshfile import MeshFileError, find_project_root, known_ids
from ..core.overlay import merge_overlays, receipt_issues
from ..core.recall_config import recall_enabled, schema_version, validate_store_v2
from ..core import index_location
from ..core.ignore_guard import ensure_index_ignored, ensure_indexes_ignored
from ..core.recall_index import IndexError_, publish_generation
from ..core.engine_preference import refresh_preferred
from ..core.schema import (
    by_type_map,
    compute_stamp_shape,
    contract_filename,
    load_contract,
    load_schema,
    min_body_chars,
    page_contract,
    recommended_without_contract,
    staging_dir_name,
    validate_against_contract,
    validate_schema_shape,
    BETA3_LAYERS,
    IN_BETA_LAYERS,
    SHIPPED_BETA_LAYERS,
)

# Inline ignore: <!-- atlas-ignore: rule_id -->
IGNORE_RE = re.compile(r"<!--\s*atlas-ignore:\s*([a-z0-9_\-]+)\s*-->", re.I)
MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
NON_BLOCKING_WARNING_IDS = {
    "atlas_uri_unmounted",
    # Preferred recall engine index work never changes compile exit codes.
    "preferred_engine_invalid",
    "preferred_index_failed",
    # A failed ignore guard is reported, never fatal: the index is still built.
    "atlas_indexes_ignore_failed",
    "atlas_index_ignore_failed",
}

# Memory layers (frame / gist / page, original shipped 0.13.0-beta;
# frame / gist / memory, 0.13.0-beta.2; schema / gist / memory, beta.3) are
# pinned here, not read from the store. "page" is the original shipped-beta
# episode type and must count as a valid gist parent alongside "memory".
GIST_PARENT_TYPES = frozenset(
    {"experience", "decision", "lesson", "recipe", "document", "memory", "page", "protostar"}
)
MISSING_GIST_TYPES = GIST_PARENT_TYPES - {"protostar"}


def _canonical_local_target(root: Path, target: str) -> str | None:
    """Resolve a relates_to target to the canonical store-relative key.

    Mirrors the resolution ``_check_relates_to`` uses: remote references
    (http(s):// or atlas://) are left alone (handled elsewhere), and any
    local target is resolved against the store root so it matches a page
    index built from ``rel()``. Targets that resolve outside the store root
    are not treated as local page keys.
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


def _resolve_related_gist(
    item: dict, root: Path, by_rel_path: dict, kind: str = "related"
) -> str | None:
    """Resolve one relates_to entry to a local gist page's canonical key, or None.

    Shared by frame-folder validation (shipped-beta SCHEMA.json shapes) and
    schema-folder validation (the beta.3 CONTRACT.json shape): an entry only
    resolves when it has ``kind`` (default ``related``), a non-empty path,
    and that path resolves to a local page whose type is ``gist``.
    """
    if not isinstance(item, dict):
        return None
    if str(item.get("kind") or item.get("role") or "").strip().lower() != kind:
        return None
    target = str(item.get("path") or "").strip()
    if not target:
        return None
    canon = _canonical_local_target(root, target)
    lookup_key = canon if canon is not None else target
    found = by_rel_path.get(lookup_key)
    if found is None or str(found[1].get("type") or "").strip() != "gist":
        return None
    return lookup_key


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
    skip_top = {staging_dir, "templates", "mesh", ".atlas-index", ".atlas", "schema.d"}
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


def _folder_in_scope(folder: Path, focus_path: Path) -> bool:
    """True when ``folder`` is the schema_folder scope for ``focus_path``.

    Two independent ways a folder stays in scope:
    - ``folder`` is ``focus_path`` itself or lies under it (``folder.relative_to
      (focus_path)`` succeeds): ``--path notes`` keeps folder ``notes`` and
      folders under ``notes`` in scope, and does not include an unrelated
      sibling folder; or
    - ``focus_path``'s parent is ``folder`` (``focus_path.parent == folder``):
      ``--path notes/g1.md`` keeps folder ``notes`` in scope because the
      file's parent is ``notes``. This is a direct-membership check only, so
      ``--path notes/sub/g1.md`` does NOT keep ancestor folder ``notes`` in
      scope (its parent is ``notes/sub``, not ``notes``).
    """
    try:
        folder.relative_to(focus_path)
        return True
    except ValueError:
        pass
    return focus_path.parent == folder


def _finding_in_focus(
    root: Path,
    finding: dict,
    focused: bool,
    want_type: str | None,
    focus_path: Path | None,
    sv: str,
    staging_name: str,
) -> bool:
    """True when a folder/page-scoped finding is within --type/--path focus.

    Shared by the main page loop's handling of ``_memory_findings`` and by
    ``_schema_folder_findings``, so a focused compile never fails because of
    an out-of-focus folder.
    """
    if not focused:
        return True
    fpath = (root / finding["path"]).resolve()
    directory_scoped = fpath.is_dir()
    if finding.get("id") == "schema_folder":
        # An uncovered-gist finding is reported on the gist itself. Treat the
        # folder invariant as in scope for either schema or gist type focus.
        folder = fpath if directory_scoped else fpath.parent
        if focus_path is not None and not _folder_in_scope(folder, focus_path):
            return False
        if want_type:
            relevant_types = {want_type}
            if want_type in {"schema", "gist"}:
                relevant_types = {"schema", "gist"}
            for page in iter_concept_md(folder, staging_name):
                if page.parent.resolve() != folder or page.name in RESERVED:
                    continue
                try:
                    meta, _ = read_page(page, sv)
                except FrontmatterError:
                    continue
                if str(meta.get("type") or "").strip() in relevant_types:
                    return True
            return False
        return True
    if directory_scoped:
        if not _in_focus(fpath, {}, None, focus_path):
            return False
        if want_type:
            # Folder findings apply to types present in their direct concept pages.
            for page in iter_concept_md(fpath, staging_name):
                if page.parent.resolve() != fpath or page.name in RESERVED:
                    continue
                try:
                    meta, _ = read_page(page, sv)
                except FrontmatterError:
                    continue
                if _in_focus(page, meta, want_type, None):
                    return True
            return False
        return True
    try:
        meta, _ = read_page(fpath, sv)
    except FrontmatterError:
        meta = None
    if meta:
        return _in_focus(fpath, meta, want_type, focus_path)
    if want_type:
        return False
    if focus_path is not None:
        try:
            fpath.relative_to(focus_path)
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


def _memory_rung(schema: dict | None, contract_name: str = "SCHEMA.json") -> tuple[str, list[dict]]:
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
                "path": contract_name,
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
                "path": contract_name,
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
                "path": contract_name,
                "msg": (
                    f"SCHEMA.memory.rung must be info, warn, or error (got {rung!r}); "
                    "treating memory rung as info"
                ),
            }
        ]
    return rung, []


_MEMORY_ALLOWED_KEYS = frozenset({"rung", "layers", "legacy_types"})
_MEMORY_LAYERS_FIXED = IN_BETA_LAYERS
_MEMORY_LEGACY_TYPES_FIXED = ["document"]


def _memory_contract(schema: dict | None, contract_name: str = "SCHEMA.json", shape: str | None = None) -> list[dict]:
    """Enforce the memory.layers / memory.legacy_types contract for a given shape.

    SCHEMA 2.0 stores already enforce this (and more) via validate_store_v2
    against the store-v2 JSON Schema, so this check only runs for stores that
    are not 2.0 (the default 1.0 contract, or any other non-2.0 value).

    in_beta stores may have differing types/layers by design (pin 3), so
    layers enforcement is skipped there. Every other shape (shipped_beta,
    current, and a stamp_shape mismatch that still carries a memory.layers
    key) keeps the pre-existing strict layers check for its contract
    filename, so a malformed SCHEMA.json/CONTRACT.json still raises
    memory_contract in addition to (not instead of) the separate
    stamp_shape finding.
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
                "path": contract_name,
                "msg": f"SCHEMA.memory has an unexpected key: {key!r}",
            }
        )
    expected_layers = None if shape == "in_beta" else (
        BETA3_LAYERS if contract_name == "CONTRACT.json" else SHIPPED_BETA_LAYERS
    )
    if expected_layers is not None and "layers" in memory:
        layers = memory["layers"]
        if layers != expected_layers:
            findings.append(
                {
                    "id": "memory_contract",
                    "path": contract_name,
                    "msg": (
                        "SCHEMA.memory.layers must be exactly "
                        f"{expected_layers!r} (got {layers!r})"
                    ),
                }
            )
    if "legacy_types" in memory:
        legacy_types = memory["legacy_types"]
        if legacy_types != _MEMORY_LEGACY_TYPES_FIXED:
            findings.append(
                {
                    "id": "memory_contract",
                    "path": contract_name,
                    "msg": (
                        "SCHEMA.memory.legacy_types must be exactly "
                        f"{_MEMORY_LEGACY_TYPES_FIXED!r} (got {legacy_types!r})"
                    ),
                }
            )
    return findings


def _memory_findings(
    root: Path, schema: dict | None, staging_name: str, run_frame_rules: bool = True
) -> list[dict]:
    """Legacy-document and memory-layer (memory/gist/frame) findings.

    Markdown files are read once here, independent of the main compile loop, so these
    findings do not depend on iteration order or on other checks succeeding.

    ``run_frame_rules`` gates the frame-folder model (frame_members): it must
    only run for shipped SCHEMA.json shapes. The beta.3 CONTRACT.json shape
    uses the schema-folder model instead (``_schema_folder_findings``); the
    two models must never both run on the same store.
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

    def _page_folder(path: Path) -> str:
        folder = rel(root, path.parent)
        return "." if folder in ("", ".") else folder

    def _valid_gist_parents(m: dict) -> list[str] | None:
        """Return canonical parent paths for a well-formed gist, else None.

        A gist counts toward coverage when it has N>=1 ``derived_from``
        parents, every parent resolves inside the store to a gist-parent
        type (not itself a gist), and every parent lives in the same folder
        (Cut 2). A shared cluster gist lists all of those parents. Zero
        parents, a duplicate parent, a gist-of-gist, an unresolved target,
        or parents in different folders never suppress ``missing_gist``.
        Index membership itself does not require a gist or a schema.
        """
        parents = _related(m, "derived_from")
        if not parents:
            return None
        canons: list[str] = []
        folders: list[str] = []
        for item in parents:
            target = str(item.get("path") or "").strip()
            if not target:
                return None
            canon = _canonical_local_target(root, target)
            key = canon if canon is not None else target
            found = by_rel_path.get(key)
            if found is None:
                return None
            tpath, tmeta = found
            ttype = str(tmeta.get("type") or "").strip()
            if ttype not in GIST_PARENT_TYPES:
                return None
            if key in canons:
                return None
            canons.append(key)
            folders.append(_page_folder(tpath))
        if len(set(folders)) != 1:
            return None
        return canons

    # Index gists by each same-folder parent they derive from. A malformed
    # gist must not suppress missing_gist for any of its targets.
    gists_by_parent: dict[str, list[str]] = {}
    for p, m in pages:
        if str(m.get("type") or "").strip() != "gist":
            continue
        gp = rel(root, p)
        canons = _valid_gist_parents(m)
        if canons:
            for canon in canons:
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
                        "toward memory/gist via path memory-migrate. The file is not "
                        "rewritten automatically."
                    ),
                }
            )

        if ptype in MISSING_GIST_TYPES and not gists_by_parent.get(rp):
            findings.append(
                {
                    "id": "missing_gist",
                    "path": rp,
                    "msg": "no gist is derived_from this memory page.",
                }
            )

        if ptype == "gist":
            if _valid_gist_parents(m) is None:
                findings.append(
                    {
                        "id": "gist_parent",
                        "path": rp,
                        "msg": (
                            "a gist has one or more same-folder parents, and no "
                            "parent is a gist (each parent must be experience, "
                            "decision, lesson, recipe, document, memory, page, "
                            "or protostar)."
                        ),
                    }
                )

    gists_by_folder: dict[str, set[str]] = {}
    frames_by_folder: dict[str, list[tuple[str, dict]]] = {}
    if run_frame_rules:
        for p, m in pages:
            folder = rel(root, p.parent)
            page_path = rel(root, p)
            if str(m.get("type") or "").strip() == "gist":
                gists_by_folder.setdefault(folder, set()).add(page_path)
            elif str(m.get("type") or "").strip() == "frame":
                frames_by_folder.setdefault(folder, []).append((page_path, m))

    for folder in sorted(set(gists_by_folder) | set(frames_by_folder)):
        expected_gists = gists_by_folder.get(folder, set())
        frames = frames_by_folder.get(folder, [])
        if expected_gists and len(frames) != 1:
            findings.append(
                {
                    "id": "frame_members",
                    "path": folder or ".",
                    "msg": (
                        "a folder with gists must have exactly one frame grouping "
                        "exactly those gists."
                    ),
                }
            )

        for frame_path, frame_meta in frames:
            related = frame_meta.get("relates_to")
            listed_paths: list[str] = []
            invalid = not isinstance(related, list)
            if invalid:
                related = []
            for item in related:
                resolved = _resolve_related_gist(item, root, by_rel_path)
                if resolved is None:
                    invalid = True
                    continue
                listed_paths.append(resolved)
            if (
                not expected_gists
                or invalid
                or len(listed_paths) != len(set(listed_paths))
                or set(listed_paths) != expected_gists
                or len(listed_paths) != len(expected_gists)
            ):
                findings.append(
                    {
                        "id": "frame_members",
                        "path": frame_path,
                        "msg": (
                            "a frame must list each gist in its folder exactly once "
                            "and no other targets."
                        ),
                    }
                )

    return findings


def _schema_folder_findings(root: Path, schema: dict | None, staging_name: str) -> list[dict]:
    """Validate schema coverage, index cues, and gist-to-memory freshness."""
    pages: list[tuple[Path, dict, str]] = []
    for path in iter_concept_md(root, staging_name):
        if path.name in RESERVED:
            continue
        try:
            meta, body = read_page(path, schema_version(schema) if schema else "1.0")
        except FrontmatterError:
            continue
        if not meta:
            continue
        pages.append((path, meta, body))

    by_rel_path = {rel(root, p): (p, m, body) for p, m, body in pages}

    gists_by_folder: dict[str, set[str]] = {}
    for p, m, _ in pages:
        folder = str(p.parent.resolve().relative_to(root.resolve())).replace("\\", "/")
        ptype = str(m.get("type") or "").strip()
        if ptype == "gist":
            gists_by_folder.setdefault(folder, set()).add(rel(root, p))

    findings: list[dict] = []
    covered_gists: set[str] = set()
    for schema_path, (schema_file, schema_meta, _) in by_rel_path.items():
        if str(schema_meta.get("type") or "").strip() != "schema":
            continue
        schema_folder = schema_file.parent.resolve()
        related = schema_meta.get("relates_to")
        if isinstance(related, list):
            for item in related:
                resolved = _resolve_related_gist(item, root, by_rel_path)
                if resolved is None:
                    continue
                gist_file = by_rel_path[resolved][0]
                if gist_file.parent.resolve() == schema_folder:
                    covered_gists.add(resolved)

        index_path = schema_folder / "index.md"
        cues_schema = False
        try:
            index_body = index_path.read_text(encoding="utf-8")
        except OSError:
            index_body = ""
        index_targets = [
            match.group(2).strip().split()[0].strip("\"'")
            for match in MD_LINK.finditer(index_body)
        ]
        index_targets.extend(match.group(1).strip() for match in WIKILINK.finditer(index_body))
        for target in index_targets:
            if target.startswith(("http://", "https://", "atlas://", "#")):
                continue
            local_target = target.split("#", 1)[0].split("?", 1)[0]
            if not local_target:
                continue
            candidate = (index_path.parent / local_target).resolve()
            if candidate == schema_file.resolve():
                cues_schema = True
                break
        if not cues_schema:
            findings.append(
                {
                    "id": "schema_missing_from_index",
                    "path": schema_path,
                    "msg": f"type=schema page {schema_path} is not cued by {rel(root, index_path)}",
                }
            )

    for _, gist_paths in sorted(gists_by_folder.items()):
        for gist_path in sorted(gist_paths - covered_gists):
            findings.append(
                {
                    "id": "schema_folder",
                    "path": gist_path,
                    "msg": (
                        f"gist {gist_path} is not listed by any same-folder "
                        "type=schema page via relates_to kind=related"
                    ),
                }
            )

    for gist_path, (_, gist_meta, _) in by_rel_path.items():
        if str(gist_meta.get("type") or "").strip() != "gist":
            continue
        description = gist_meta.get("description")
        if not isinstance(description, str) or not description:
            continue
        relates = gist_meta.get("relates_to")
        if not isinstance(relates, list):
            continue
        memory_parents: list[tuple] = []
        for item in relates:
            if not isinstance(item, dict):
                continue
            if str(item.get("kind") or item.get("role") or "").strip().lower() != "derived_from":
                continue
            target = str(item.get("path") or "").strip()
            canonical = _canonical_local_target(root, target)
            found = by_rel_path.get(canonical if canonical is not None else target)
            if found is None or str(found[1].get("type") or "").strip() != "memory":
                continue
            memory_parents.append(found)
        if not memory_parents:
            continue
        # N=1: the description must be a substring of that parent.
        # N>1: union pack — a substring of at least one derived_from parent.
        def _holds(found: tuple) -> bool:
            memory_meta, memory_body = found[1], found[2]
            memory_description = memory_meta.get("description")
            return description in memory_body or (
                isinstance(memory_description, str) and description in memory_description
            )

        if any(_holds(found) for found in memory_parents):
            continue
        if len(memory_parents) == 1:
            msg = (
                "gist description is not present in its memory parent "
                f"{rel(root, memory_parents[0][0])}"
            )
        else:
            msg = "gist description is not present in any derived_from memory parent"
        findings.append(
            {
                "id": "stale_upper_page",
                "path": gist_path,
                "msg": msg,
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

    schema, schema_err = load_schema(r)
    contract_name = contract_filename(r) or "SCHEMA.json"
    stamp_shape: str | None = None
    if schema_err:
        critical.append({"id": "schema_present", "path": contract_name, "msg": schema_err})
        schema = None
    else:
        assert schema is not None
        stamp_shape, stamp_err = compute_stamp_shape(contract_name, schema)
        if stamp_err:
            critical.append({"id": "stamp_shape", "path": contract_name, "msg": stamp_err})
        tmpl = schema.get("templates")
        if tmpl is not None and not isinstance(tmpl, dict):
            critical.append(
                {
                    "id": "schema_shape",
                    "path": contract_name,
                    "msg": "SCHEMA.templates must be an object",
                }
            )
        elif isinstance(tmpl, dict):
            by = tmpl.get("by_type")
            if by is not None and not isinstance(by, dict):
                critical.append(
                    {
                        "id": "schema_shape",
                        "path": contract_name,
                        "msg": "SCHEMA.templates.by_type must be an object",
                    }
                )
        merged, ov_crit, ov_warn = merge_overlays(schema, r)
        critical.extend(ov_crit)
        warnings.extend(ov_warn)
        critical.extend(receipt_issues(r))
        schema = merged
        shape_msgs = validate_schema_shape(schema)
        for msg in shape_msgs:
            critical.append({"id": "schema_shape", "path": contract_name, "msg": msg})
        if shape_msgs:
            schema = None
        else:
            for msg in validate_against_contract(schema, load_contract()):
                critical.append({"id": "schema_contract", "path": contract_name, "msg": msg})
            if schema is not None and schema_version(schema) == "2.0":
                for msg in validate_store_v2(schema):
                    critical.append({"id": "schema_v2", "path": contract_name, "msg": msg})

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

    # Memory rung (memory / gist / frame): absent means info; malformed shapes
    # raise a critical memory_rung issue but still treat the ladder as info.
    memory_rung, memory_shape_issues = _memory_rung(schema, contract_name)
    critical.extend(memory_shape_issues)
    if schema is not None and schema_version(schema) != "2.0":
        critical.extend(_memory_contract(schema, contract_name, stamp_shape))
    if not skip_pages and stamp_shape == "current":
        sv = schema_version(schema) if schema else "1.0"
        for finding in _schema_folder_findings(r, schema, staging_name):
            if _finding_in_focus(r, finding, focused, want_type, focus_path, sv, staging_name):
                critical.append(finding)
    allow_inline_ignores = True
    if isinstance(schema, dict):
        compile_cfg = schema.get("compile")
        if isinstance(compile_cfg, dict) and "allow_inline_ignores" in compile_cfg:
            allow_inline_ignores = bool(compile_cfg["allow_inline_ignores"])
    if not skip_pages:
        sv = schema_version(schema) if schema else "1.0"
        for finding in _memory_findings(
            r, schema, staging_name, run_frame_rules=(stamp_shape != "current")
        ):
            fpath = (r / finding["path"]).resolve()
            directory_scoped = fpath.is_dir()
            if allow_inline_ignores and not directory_scoped:
                try:
                    ign_text = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    ign_text = ""
                if finding["id"] in _ignores_in(ign_text):
                    continue
            if not _finding_in_focus(r, finding, focused, want_type, focus_path, sv, staging_name):
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
                    "path": contract_name,
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
                try:
                    index_path = index_location.describe(r, "fts5")["index_dir"]
                except Exception:
                    index_path = None
                critical.append(
                    {
                        "id": "recall_index",
                        "path": index_path or ".atlas/indexes/fts5",
                        "msg": f"failed to publish recall generation: {e}",
                    }
                )

    if not dry_run and not focused and not critical:
        for item in refresh_preferred(r, schema):
            (warnings if item.get("level") == "warning" else info).append(item)

    if not dry_run:
        for ignored in (ensure_indexes_ignored(r), ensure_index_ignored(r)):
            if ignored:
                (warnings if ignored.get("level") == "warning" else info).append(ignored)

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
