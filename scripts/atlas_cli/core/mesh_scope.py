"""Mesh core: who is in the mesh, mesh node ids and the strict cross-store resolver.

Pure library (no CLI surface yet). Later packets persist :func:`build_view`
as the structure-only mesh graph and use :func:`members` for federated recall.

- Discovery (M2): ``--root`` is a project directory holding
  ``atlas-mesh.json`` or a store listed by one of its rows
  (:func:`index_location.mesh_match`). A standalone store raises
  :class:`MeshScopeError`.
- Members (M2): the rows in file order. A row with ``mesh_member: false`` is
  ``excluded`` and nothing inside its root is ever read (no stat, open,
  listdir or projection). A row whose root is not a directory holding a
  contract file is ``unmounted``; it is never mounted, and no git or network
  call is made for it.
- Node ids (M3): ``atlas://<atlas-id>/<store-relative path>``.
- Privacy (M7, M20): ``sensitivity: restricted`` pages are dropped from the
  view and remembered only as a set of withheld paths. Node records carry
  structure only (M6): no title, description, body, tags or other text.
- Resolver (M4, M21): every ``relates_to`` target of every included page is
  classified exactly once, in this order: local edge; canonical
  ``atlas://<atlas-id>/<path>[#fragment]``; mesh-relative path; otherwise
  unresolved with one reason. The first segment after ``atlas://`` is a
  host when it is host-shaped (a dot, a ``:port``, an IP literal or
  ``localhost``) or is the host of a mesh row id (:func:`is_canonical_host`);
  otherwise ``atlas://<name>/<path>`` is a short form, never resolved as an
  alias.

Edge records: ``from`` (node id), ``to`` (a node id when the target lands in
an included member, otherwise the authored target), ``kind``, ``cross`` (target store is
not the source store), ``resolved``, ``resolution`` (how the target was
written: ``local``, ``atlas_uri`` or ``mesh_path``), and ``reason`` /
``suggest`` when relevant.
"""

from __future__ import annotations

import os
import posixpath
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from . import graph, index_location, meshfile
from .identity import IdentityError, fold_host, parse_pointer
from .paths import has_contract_file
from .projection import ProjectedPage, normalise_target

ATLAS_SCHEME = "atlas://"
RESOLVER_VERSION = 1

STATUS_OK = "ok"
STATUS_UNMOUNTED = "unmounted"
STATUS_EXCLUDED = "excluded"

RESOLUTION_LOCAL = "local"
RESOLUTION_ATLAS_URI = "atlas_uri"
RESOLUTION_MESH_PATH = "mesh_path"

REASON_UNMOUNTED = "unmounted"
REASON_EXCLUDED = "excluded_member"
REASON_MISSING = "missing_page"
REASON_WITHHELD = "withheld"
REASON_OUTSIDE = "outside_mesh"
REASON_NONCANONICAL = "noncanonical_atlas_uri"
REASONS = (
    REASON_UNMOUNTED,
    REASON_EXCLUDED,
    REASON_MISSING,
    REASON_WITHHELD,
    REASON_OUTSIDE,
    REASON_NONCANONICAL,
)

NONCANONICAL_LINK = "noncanonical_cross_store_link"
RESTRICTED = "restricted"
NODE_SCALARS = (
    "kva",
    "status",
    "work_id",
    "sensitivity",
    "growth",
    "consolidation",
    "star_kind",
    "kva_role",
    "origin",
)
PROJECT_MOUNT_PREFIX = ".atlas/"


class MeshScopeError(ValueError):
    """No mesh, an invalid mesh file or an unreadable member; callers map it to exit 2."""


# --- node ids ----------------------------------------------------------------


def node_id(atlas_id: str, path: str) -> str:
    """``atlas://<atlas-id>/<store-relative path>``."""
    rel = normalise_target(path).lstrip("/")
    if not atlas_id or not rel:
        raise MeshScopeError(f"node id needs an atlas id and a path, got {atlas_id!r} and {path!r}")
    return f"{ATLAS_SCHEME}{atlas_id}/{rel}"


def parse_node_id(uri: str, hosts: frozenset[str] | set[str] | None = None) -> tuple[str, str]:
    """Inverse of :func:`node_id`: ``(atlas_id, path)``; any ``#fragment`` is dropped.

    The id is read with the identity grammar (:func:`identity.parse_pointer`),
    so every atlas id mesh validation accepts round-trips, whatever its host.
    Pass ``hosts`` (see :func:`mesh_hosts`) to also apply the short-form rule
    of :func:`is_canonical_host`.
    """
    text = str(uri or "").strip()
    if not text.startswith(ATLAS_SCHEME):
        raise MeshScopeError(f"{uri!r} is not a canonical atlas://<host>/<org>/<repo>/<path> node id")
    if hosts is not None and not is_canonical_host(text, hosts):
        raise MeshScopeError(f"{uri!r} is a short form, not a canonical atlas://<host>/<org>/<repo>/<path> node id")
    try:
        parsed = parse_pointer(text)
    except IdentityError as e:
        raise MeshScopeError(f"{uri!r} is not a canonical node id: {e}") from e
    path = _clean_in_store(parsed.in_store)
    if not path:
        raise MeshScopeError(f"{uri!r} has no store-relative path")
    return parsed.atlas_id, path


def is_host_shaped(segment: str) -> bool:
    """A host on its own: a dotted name, an IP literal, ``host:port`` or ``localhost``."""
    host = fold_host(segment)
    return "." in host or ":" in host or host.startswith("[") or host == "localhost"


def mesh_hosts(atlas_ids: Any) -> frozenset[str]:
    """Folded hosts (first segments) of the given atlas ids, as :func:`identity.normalise` writes them."""
    out: set[str] = set()
    for sid in atlas_ids:
        try:
            canon = parse_pointer(str(sid)).atlas_id
        except IdentityError:
            canon = str(sid)
        out.add(fold_host(_first_segment(canon)).lower())
    return frozenset(out)


def is_canonical_host(uri: str, hosts: frozenset[str] | set[str] | None = None) -> bool:
    """True when the first segment after ``atlas://`` is a host, not a short-form name.

    One rule for node ids and the resolver: the segment is host-shaped
    (:func:`is_host_shaped`) or it is the host of a mesh row id (``hosts``).
    Anything else, such as ``atlas://<repo>/<path>``, is a short form.
    """
    first = _first_segment(uri.removeprefix(ATLAS_SCHEME))
    if not first:
        return False
    return is_host_shaped(first) or fold_host(first).lower() in (hosts or ())


def _first_segment(body: str) -> str:
    return body.split("/", 1)[0].split("#", 1)[0]


def _clean_in_store(path: str) -> str:
    text = normalise_target(path).lstrip("/")
    if not text:
        return ""
    return posixpath.normpath(text)


def repo_name(atlas_id: str) -> str:
    return atlas_id.rstrip("/").rsplit("/", 1)[-1]


# --- discovery -----------------------------------------------------------------


@dataclass(frozen=True)
class Mesh:
    project: Path
    doc: dict[str, Any]

    @property
    def mesh_file(self) -> Path:
        return self.project / meshfile.MESH_NAME


def discover(root: Path | str) -> Mesh:
    """The mesh for ``root``: a project directory with atlas-mesh.json, or a store one of its rows lists."""
    start = Path(root).expanduser().resolve()
    if (start / meshfile.MESH_NAME).is_file():
        return _load_mesh(start)
    try:
        match = index_location.mesh_match(start)
    except index_location.IndexLocationError as e:
        raise MeshScopeError(str(e)) from e
    if match is not None:
        return _load_mesh(match.directory)
    project = _member_root_match(start)
    if project is not None:
        return _load_mesh(project)
    raise MeshScopeError(f"no atlas-mesh.json lists this store: {start}")


def _load_mesh(project: Path) -> Mesh:
    # Strict load: a malformed mesh_member must never include a store by accident.
    try:
        doc = meshfile.load(project)
    except (meshfile.MeshFileError, OSError) as e:
        raise MeshScopeError(f"{project / meshfile.MESH_NAME}: {e}") from e
    return Mesh(project, doc)


def _member_root_match(start: Path) -> Path | None:
    """Rows ``mesh_match`` does not cover: a ``subpath`` root or a row with no ``path``."""
    for directory in [start.parent, *start.parent.parents]:
        if not (directory / meshfile.MESH_NAME).is_file():
            continue
        try:
            doc = meshfile.load_for_location(directory)
        except (meshfile.MeshFileError, OSError, ValueError):
            continue
        for i, row in enumerate(doc.get("stores") or []):
            if not isinstance(row, dict) or not meshfile.is_mesh_member(row):
                continue
            try:
                candidate = _row_root(directory, row, i)
                if candidate.resolve() == start:
                    return directory
            except (MeshScopeError, OSError, RuntimeError):
                continue
    return None


# --- members -----------------------------------------------------------------


@dataclass(frozen=True)
class Member:
    index: int
    atlas_id: str
    mount: str
    subpath: str
    root: Path
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {"atlas_id": self.atlas_id, "path": self.mount, "subpath": self.subpath, "status": self.status}


def _row_root(project: Path, row: dict[str, Any], index: int) -> Path:
    """Lexical member root ``project / path / subpath``; never touches the filesystem."""
    from ..commands.resolve import _join_under, default_mount

    sid = str(row.get("id") or f"stores[{index}]")
    raw = row.get("path")
    mount = project / raw if isinstance(raw, str) and raw.strip() else default_mount(project, sid)
    root = _join_under(mount, str(row.get("subpath") or ""))
    if root is None:
        raise MeshScopeError(f"store {sid}: subpath {row.get('subpath')!r} must stay under its mount")
    return Path(os.path.normpath(root))


def _mount_label(project: Path, row: dict[str, Any], sid: str) -> str:
    raw = row.get("path")
    if isinstance(raw, str) and raw.strip():
        return PurePosixPath(raw.replace("\\", "/")).as_posix()
    return (PurePosixPath(".atlas") / PurePosixPath(*sid.split("/"))).as_posix()


def members(mesh: Mesh) -> list[Member]:
    """Every row in file order with its status; an excluded row's root is never touched."""
    out: list[Member] = []
    for i, row in enumerate(mesh.doc.get("stores") or []):
        sid = str(row["id"])
        root = _row_root(mesh.project, row, i)
        if not meshfile.is_mesh_member(row):
            status = STATUS_EXCLUDED
        elif root.is_dir() and has_contract_file(root):
            status = STATUS_OK
        else:
            status = STATUS_UNMOUNTED
        out.append(Member(i, sid, _mount_label(mesh.project, row, sid), str(row.get("subpath") or ""), root, status))
    return out


# --- member pages ----------------------------------------------------------------


@dataclass
class MemberPages:
    member: Member
    pages: dict[str, ProjectedPage]
    withheld: frozenset[str] = field(default_factory=frozenset)


def is_restricted(meta: dict[str, Any] | None) -> bool:
    value = (meta or {}).get("sensitivity")
    return isinstance(value, str) and value.strip().lower() == RESTRICTED


def load_member(member: Member) -> MemberPages:
    """Pages of an included member via the shared graph source, restricted pages withheld (M7, M20)."""
    if member.status != STATUS_OK:
        raise MeshScopeError(f"store {member.atlas_id} is {member.status}; its pages are not read")
    try:
        source = graph.load_source(member.root)
    except graph.GraphError as e:
        raise MeshScopeError(f"store {member.atlas_id}: {e}") from e
    pages: dict[str, ProjectedPage] = {}
    withheld: set[str] = set()
    for page in source["pages"]:
        if is_restricted(page.meta):
            withheld.add(page.path)
        else:
            pages[page.path] = page
    return MemberPages(member, pages, frozenset(withheld))


def node_record(atlas_id: str, page: ProjectedPage) -> dict[str, Any]:
    """Structure only (M6): id, atlas_id, path, type and lifecycle scalars; no text."""
    meta = page.meta if isinstance(page.meta, dict) else {}
    record: dict[str, Any] = {
        "id": node_id(atlas_id, page.path),
        "atlas_id": atlas_id,
        "path": page.path,
        "type": graph.normalise_text(meta.get("type")) or "",
    }
    for key in NODE_SCALARS:
        if key == "growth":
            flag = graph._bool_or_none(meta.get(key))
            if flag is not None:
                record[key] = flag
            continue
        text = graph.normalise_text(meta.get(key))
        if text:
            record[key] = text
    return record


# --- resolver --------------------------------------------------------------------


class Resolver:
    """Strict M4 classification of ``relates_to`` targets across the mesh."""

    def __init__(self, mesh: Mesh, all_members: list[Member], loaded: dict[int, MemberPages]) -> None:
        self.mesh = mesh
        self.members = all_members
        self.loaded = loaded
        self.by_key = {meshfile.id_key(m.atlas_id): m for m in all_members}
        self.hosts = mesh_hosts(m.atlas_id for m in all_members)
        # Longest root first, so a nested member root wins over its parent.
        self.by_root = sorted(all_members, key=lambda m: len(m.root.parts), reverse=True)

    def classify(self, source: Member, target: str) -> dict[str, Any]:
        text = normalise_target(target)
        if text.startswith(ATLAS_SCHEME):
            return self._atlas_uri(source, text)
        own = self.loaded[source.index]
        local = _clean_in_store(text)
        if local in own.pages:
            return self._edge(source, source, local, RESOLUTION_LOCAL, None)
        if local in own.withheld:
            return self._edge(source, source, local, RESOLUTION_LOCAL, REASON_WITHHELD)
        if text.startswith(PROJECT_MOUNT_PREFIX) or local == ".." or local.startswith("../"):
            return self._mesh_path(source, text)
        return self._edge(source, source, local, RESOLUTION_LOCAL, REASON_MISSING, raw=text)

    def _edge(
        self,
        source: Member,
        target: Member | None,
        path: str | None,
        resolution: str,
        reason: str | None,
        raw: str | None = None,
        suggest: str | None = None,
        cross: bool | None = None,
    ) -> dict[str, Any]:
        if target is not None and path and path != "." and not path.startswith("../"):
            to = node_id(target.atlas_id, path)
        else:
            to = raw if raw is not None else str(path or "")
        rec: dict[str, Any] = {
            "to": to,
            "cross": (target is None or target.index != source.index) if cross is None else cross,
            "resolved": reason is None,
            "resolution": resolution,
        }
        if reason is not None:
            rec["reason"] = reason
        if suggest is not None:
            rec["suggest"] = suggest
        return rec

    def _lookup(self, source: Member, target: Member, path: str, resolution: str, raw: str) -> dict[str, Any]:
        if target.status == STATUS_EXCLUDED:
            return self._edge(source, target, None, resolution, REASON_EXCLUDED, raw=raw)
        if target.status != STATUS_OK:
            return self._edge(source, target, None, resolution, REASON_UNMOUNTED, raw=raw)
        pages = self.loaded[target.index]
        if path in pages.pages:
            return self._edge(source, target, path, resolution, None)
        if path in pages.withheld:
            return self._edge(source, target, path, resolution, REASON_WITHHELD)
        return self._edge(source, target, path, resolution, REASON_MISSING, raw=raw)

    def _atlas_uri(self, source: Member, text: str) -> dict[str, Any]:
        body = text[len(ATLAS_SCHEME) :]
        first = _first_segment(body)
        if not is_canonical_host(text, self.hosts):
            return self._short_form(source, text, first, body)
        try:
            parsed = parse_pointer(text)
        except IdentityError:
            return self._edge(source, None, None, RESOLUTION_ATLAS_URI, REASON_NONCANONICAL, raw=text)
        path = _clean_in_store(parsed.in_store)
        target = self.by_key.get(meshfile.id_key(parsed.atlas_id))
        if target is None:
            return self._edge(source, None, None, RESOLUTION_ATLAS_URI, REASON_UNMOUNTED, raw=text)
        if not path:
            return self._edge(source, target, None, RESOLUTION_ATLAS_URI, REASON_MISSING, raw=text)
        if path == ".." or path.startswith("../"):
            return self._edge(source, target, None, RESOLUTION_ATLAS_URI, REASON_OUTSIDE, raw=text)
        return self._lookup(source, target, path, RESOLUTION_ATLAS_URI, text)

    def _short_form(self, source: Member, text: str, name: str, body: str) -> dict[str, Any]:
        """``atlas://<name>/<path>``: never an alias; suggest only on a unique repo-name match."""
        rest = body.split("/", 1)[1] if "/" in body else ""
        matches = [m for m in self.members if repo_name(m.atlas_id).lower() == name.lower()]
        suggest = None
        cross = True
        if len(matches) == 1 and rest.split("#", 1)[0].strip("/"):
            suggest = f"{ATLAS_SCHEME}{matches[0].atlas_id}/{rest.lstrip('/')}"
            cross = matches[0].index != source.index
        return self._edge(
            source, None, None, RESOLUTION_ATLAS_URI, REASON_NONCANONICAL, raw=text, suggest=suggest, cross=cross
        )

    def _mesh_path(self, source: Member, text: str) -> dict[str, Any]:
        if text.startswith(PROJECT_MOUNT_PREFIX):
            candidate = Path(os.path.normpath(self.mesh.project / text))
        else:
            candidate = Path(os.path.normpath(source.root / text))
        target = next((m for m in self.by_root if _lexically_under(candidate, m.root)), None)
        if target is None:
            return self._edge(source, None, None, RESOLUTION_MESH_PATH, REASON_OUTSIDE, raw=text)
        rel = candidate.relative_to(target.root)
        path = rel.as_posix()
        if target.status != STATUS_OK:
            return self._lookup(source, target, path, RESOLUTION_MESH_PATH, text)
        if path in ("", ".") or _crosses_symlink(target.root, rel):
            return self._edge(source, None, None, RESOLUTION_MESH_PATH, REASON_OUTSIDE, raw=text)
        rec = self._lookup(source, target, path, RESOLUTION_MESH_PATH, text)
        if rec["resolved"]:
            rec["suggest"] = rec["to"]
        return rec


def _lexically_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _crosses_symlink(root: Path, rel: PurePosixPath | Path) -> bool:
    acc = root
    for part in rel.parts:
        acc = acc / part
        if acc.is_symlink():
            return True
    return False


# --- view ----------------------------------------------------------------------


def build_view(mesh: Mesh) -> dict[str, Any]:
    """In-memory mesh view: ``{members, nodes, edges, warnings, unresolved_by_reason}``.

    Deterministic (sorted, no timestamps) and structure only. Writes nothing.
    """
    all_members = members(mesh)
    loaded = {m.index: load_member(m) for m in all_members if m.status == STATUS_OK}
    resolver = Resolver(mesh, all_members, loaded)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    counts = {reason: 0 for reason in REASONS}
    for member in all_members:
        member_pages = loaded.get(member.index)
        if member_pages is None:
            continue
        for path in sorted(member_pages.pages):
            page = member_pages.pages[path]
            nodes.append(node_record(member.atlas_id, page))
            from_id = node_id(member.atlas_id, page.path)
            seen: set[tuple[str, str]] = set()
            for edge in page.edges:
                target = normalise_target(edge.get("target") or "")
                if not target:
                    continue
                kind = str(edge.get("kind") or "related")
                if (target, kind) in seen:
                    continue
                seen.add((target, kind))
                rec = {"from": from_id, "kind": kind, **resolver.classify(member, target)}
                edges.append(_ordered(rec))
                if "reason" in rec:
                    counts[rec["reason"]] += 1
                if rec.get("resolution") == RESOLUTION_MESH_PATH and rec["resolved"]:
                    warnings.append(
                        {
                            "code": NONCANONICAL_LINK,
                            "level": "warning",
                            "from": from_id,
                            "target": target,
                            "suggest": rec["suggest"],
                            "message": (
                                f"{from_id} links to {target} through a mesh-relative path, which breaks "
                                f"where the stores are mounted elsewhere; write {rec['suggest']} instead"
                            ),
                        }
                    )
    nodes.sort(key=lambda n: n["id"])
    edges.sort(key=lambda e: (e["from"], e["to"], e["kind"]))
    warnings.sort(key=lambda w: (w["from"], w["target"]))
    return {
        "members": [m.as_dict() for m in all_members],
        "nodes": nodes,
        "edges": edges,
        "warnings": warnings,
        "unresolved_by_reason": counts,
    }


_EDGE_ORDER = ("from", "to", "kind", "cross", "resolved", "resolution", "reason", "suggest")


def _ordered(rec: dict[str, Any]) -> dict[str, Any]:
    return {key: rec[key] for key in _EDGE_ORDER if key in rec}
