"""Native mesh graph (packet MB): the structure-only ``graph/_mesh`` index and its queries.

Location (M5): ``<project>/.atlas/indexes/graph/_mesh/`` with
``generations/<gen>/mesh-graph.json`` and a ``current.json`` pointer, laid out
like the fts5 index.

Contents (M6, M7, M20): the :func:`mesh_scope.build_view` structure only:
node id, ``atlas_id``, ``path``, ``type`` and the lifecycle scalars; edges with
``from``, ``to``, ``kind``, ``cross``, ``resolved``, ``resolution``,
``reason`` and ``suggest``. No title, description, body, tags or other
frontmatter text. Restricted pages, excluded stores and ``invalid`` rows
(never read, as excluded) are absent. Titles and
``--where`` on other fields are read back at query time from each member's own
source (:class:`Hydrator`), only for nodes being returned.

Digest and freshness (M8): ``mesh_digest`` is the sha256 of canonical JSON
holding the index format, the resolver and privacy policy versions, every
serialised member record (the same fields the snapshot writes, sorted,
including excluded, unmounted and invalid rows) and each included member's
corpus digest. A path, subpath, status or reason change therefore changes
the digest even when the row stays in the same status. The pointer records
each member's cheap fingerprint, but a fingerprint match
never proves freshness (a same-length edit can keep its mtime): every read
recomputes each included member's corpus digest from its bytes and accepts the
snapshot only when ``mesh_digest`` matches; otherwise the index is rebuilt
before answering. The fingerprint is only an advisory "stale" signal. A
rebuild does not hash the members and then reread them for the view: it loads
each included member once, hashes those bytes and parses those same bytes, and
publishes that view under that digest.

Locking (M9): ``index_publish.locked_build`` on the ``_mesh`` parent (an
:class:`owned_lock.OwnedLock` with a 10-minute stale timeout). The build
writes a temporary sibling, renames it into place and replaces the pointer
inside the owned critical section, keeping the pointer's generation plus one.
A reader that finds the lock held waits up to :data:`READ_WAIT_SECONDS`, then
answers from an in-memory build with ``driver_note: mesh_index_busy``.
Lock order: the mesh build reads member pages and published generations
read-only and never takes a member lock, so the mesh lock is never held while
a member lock is taken, and a member's own stale index is never rebuilt here.

No daemon and no watcher (M10): refreshes happen on a mesh-scope graph read,
``atlas index build --mesh`` and ``atlas compile`` on a member store when the
mesh graph index already exists (:func:`refresh_after_compile`).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import graph, index_location, index_publish, meshfile, mesh_scope, paths
from .ignore_guard import ensure_indexes_ignored
from .overlay import merge_overlays
from .projection import (
    ProjectionError,
    cheap_fingerprint,
    content_digest,
    eligible_paths,
    normalise_target,
    project_store,
)
from .retrieve import EXIT_FIELDS, is_exit_value
from .schema import load_schema

DRIVER_TYPE = "graph"
GRAPH_NAME = "mesh-graph.json"
CURRENT_NAME = "current.json"
INDEX_FORMAT = 1
PRIVACY_POLICY_VERSION = 1
KEEP_GENERATIONS = 2
READ_WAIT_SECONDS = index_publish.LOCK_WAIT_SECONDS
BUSY_NOTE = "mesh_index_busy"
NANOGRAPH_NOTE = "nanograph mesh graph is not built yet (packet MD); used native"
NATIVE_DRIVER = "native-graph"
INDEXED_FIELDS = frozenset({"type", *mesh_scope.NODE_SCALARS})
REFRESHED = "mesh_graph_refreshed"
FRESH = "mesh_graph_fresh"
REFRESH_FAILED = "mesh_graph_refresh_failed"


class MeshGraphError(mesh_scope.MeshScopeError):
    """Bad input or an unreadable member in mesh scope; callers map it to exit 2."""


# --- location ------------------------------------------------------------------


def index_dir(project: Path) -> Path:
    try:
        return index_location.mesh_index_dir(project, DRIVER_TYPE)
    except index_location.IndexLocationError as e:
        raise MeshGraphError(str(e)) from e


def relative_dir(project: Path, path: Path) -> str:
    try:
        return path.relative_to(Path(project).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_pointer(root: Path) -> dict[str, Any] | None:
    return _read_json(root / CURRENT_NAME)


def exists(project: Path) -> bool:
    """True when a mesh graph index (a pointer or a published generation) exists for ``project``."""
    try:
        root = index_dir(project)
    except MeshGraphError:
        return False
    pointer = root / CURRENT_NAME
    if pointer.exists() or pointer.is_symlink():
        return True
    gens = root / "generations"
    return gens.is_dir() and any(not c.name.startswith(index_publish.TMP_PREFIX) for c in gens.iterdir())


def usable_pointer(cur: dict[str, Any] | None) -> bool:
    return bool(cur and cur.get("complete") and cur.get("format") == INDEX_FORMAT and cur.get("mesh_digest"))


def _graph_file(root: Path, raw: object) -> Path | None:
    text = str(raw or "").strip()
    if not text or text.startswith("/") or "\\" in text:
        return None
    rel = Path(text)
    if rel.is_absolute() or ".." in rel.parts or rel.parts[:1] != ("generations",):
        return None
    candidate = root / rel
    try:
        index_location.reject_symlink_escape(root, candidate)
    except index_location.IndexLocationError:
        return None
    return candidate if candidate.is_file() else None


def load_snapshot(root: Path, pointer: dict[str, Any] | None) -> dict[str, Any] | None:
    if not usable_pointer(pointer):
        return None
    path = _graph_file(root, pointer.get("graph"))
    doc = _read_json(path) if path is not None else None
    if not doc or doc.get("mesh_digest") != pointer.get("mesh_digest"):
        return None
    return doc


# --- members, fingerprints and the digest --------------------------------------------


@dataclass
class MemberState:
    member: mesh_scope.Member
    schema: dict[str, Any]
    paths: list[Path]
    fingerprint: str
    digest: str | None = None


def _member_schema(member: mesh_scope.Member) -> dict[str, Any]:
    schema, err = load_schema(member.root)
    if schema is None:
        raise MeshGraphError(f"store {member.atlas_id}: {err or 'missing schema'}")
    merged, critical, _ = merge_overlays(schema, member.root)
    if critical:
        raise MeshGraphError(f"store {member.atlas_id}: " + "; ".join(i["msg"] for i in critical))
    return merged


def member_states(all_members: list[mesh_scope.Member]) -> list[MemberState]:
    """Cheap fingerprints of every included member, read-only and without any member lock."""
    out: list[MemberState] = []
    for m in all_members:
        if m.status != mesh_scope.STATUS_OK:
            continue
        schema = _member_schema(m)
        paths = eligible_paths(m.root, schema)
        out.append(MemberState(m, schema, paths, cheap_fingerprint(m.root, schema, paths)))
    return out


def _ids_with(all_members: list[mesh_scope.Member], status: str) -> list[str]:
    return sorted(m.atlas_id for m in all_members if m.status == status)


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest_member_records(all_members: list[mesh_scope.Member]) -> list[dict[str, Any]]:
    """Snapshot member records in canonical order.

    The dicts are :func:`mesh_scope.member_records` (what the snapshot writes),
    so a field added there is covered here without a second hand-written shape.
    File order is not part of the digest.
    """
    return sorted(mesh_scope.member_records(all_members), key=lambda row: (str(row.get("atlas_id") or ""), _canon(row)))


def mesh_digest(states: list[MemberState], all_members: list[mesh_scope.Member]) -> str:
    """sha256 of canonical JSON (M8).

    Covers every serialised member record (ok and not: atlas id, path, subpath,
    status, reason and any other field the snapshot writes) plus each included
    member's corpus digest. A path, subpath or reason change on an excluded,
    unmounted or invalid row therefore changes the digest even when the row
    stays in the same status. Those records come from ``atlas-mesh.json`` only;
    no excluded, unmounted or invalid store is read.
    """
    corpus = [
        {"atlas_id": state.member.atlas_id, "corpus_digest": state.digest}
        for state in states
    ]
    corpus.sort(key=lambda row: (row["atlas_id"], row["corpus_digest"] or ""))
    doc = {
        "format": INDEX_FORMAT,
        "resolver_version": mesh_scope.RESOLVER_VERSION,
        "privacy_policy_version": PRIVACY_POLICY_VERSION,
        "members": _digest_member_records(all_members),
        "corpus": corpus,
    }
    return hashlib.sha256(_canon(doc).encode("utf-8")).hexdigest()


def _pointer_members(pointer: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    rows = (pointer or {}).get("members")
    return {str(r.get("atlas_id")): r for r in rows if isinstance(r, dict)} if isinstance(rows, list) else {}


def fill_digests(states: list[MemberState]) -> None:
    """Corpus digests hashed from each member's bytes; a matching fingerprint is never trusted (R4)."""
    for s in states:
        digest = content_digest(s.member.root, s.schema, s.paths)
        if digest is None:
            raise MeshGraphError(f"store {s.member.atlas_id}: corpus is incomplete (an eligible page is unreadable)")
        s.digest = digest


# --- snapshot ------------------------------------------------------------------------


def snapshot_doc(view: dict[str, Any], digest: str) -> dict[str, Any]:
    """The structure-only document written as ``mesh-graph.json`` (no generation, no time)."""
    return {
        "format": INDEX_FORMAT,
        "resolver_version": mesh_scope.RESOLVER_VERSION,
        "privacy_policy_version": PRIVACY_POLICY_VERSION,
        "mesh_digest": digest,
        "members": view["members"],
        "nodes": view["nodes"],
        "edges": view["edges"],
        "unresolved_by_reason": view["unresolved_by_reason"],
    }


def dump_doc(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _pointer(gen_id: str, digest: str, doc: dict[str, Any], states: list[MemberState], all_members) -> dict[str, Any]:
    return {
        "format": INDEX_FORMAT,
        "generation": gen_id,
        "mesh_digest": digest,
        "graph": f"generations/{gen_id}/{GRAPH_NAME}",
        "complete": True,
        "members": [
            {
                "atlas_id": s.member.atlas_id,
                "path": s.member.mount,
                "subpath": s.member.subpath,
                "corpus_digest": s.digest,
                "cheap_fingerprint": s.fingerprint,
            }
            for s in sorted(states, key=lambda s: s.member.atlas_id)
        ],
        "excluded": _ids_with(all_members, mesh_scope.STATUS_EXCLUDED),
        "unmounted": _ids_with(all_members, mesh_scope.STATUS_UNMOUNTED),
        "invalid": _ids_with(all_members, mesh_scope.STATUS_INVALID),
        "nodes": len(doc["nodes"]),
        "edges": len(doc["edges"]),
        "unresolved_by_reason": dict(doc["unresolved_by_reason"]),
    }


def _prune(root: Path, keep: str, previous: str | None) -> list[Path]:
    """Retire all but the pointer's generation and one other (call inside the critical section)."""
    gens = root / "generations"
    if not gens.is_dir():
        return []
    others: list[tuple[int, int, str, Path]] = []
    for child in gens.iterdir():
        if child.name == keep or child.is_symlink() or not child.is_dir():
            continue
        if child.name.startswith(index_publish.TMP_PREFIX):
            continue
        try:
            others.append((1 if child.name == previous else 0, child.stat().st_mtime_ns, child.name, child))
        except OSError:
            continue
    others.sort(reverse=True)
    return index_publish.retire([old for *_, old in others[KEEP_GENERATIONS - 1 :]], root)


def _refresh_fingerprints(root: Path, pointer: dict[str, Any], states: list[MemberState]) -> dict[str, Any]:
    """Best effort: record the current fingerprints, only if the lock is free and the pointer unchanged."""
    by_id = {s.member.atlas_id: s.fingerprint for s in states}
    updated = {
        **pointer,
        "members": [{**row, "cheap_fingerprint": by_id.get(row.get("atlas_id"), row.get("cheap_fingerprint"))} for row in pointer.get("members") or []],
    }
    if updated == pointer:
        return pointer
    lock = index_publish.BuildLock(root)
    try:
        if not lock.try_acquire():
            return updated
    except OSError:
        return updated
    try:
        with index_publish.critical_section(lock):
            cur = read_pointer(root) or {}
            if cur.get("generation") == pointer.get("generation") and cur.get("mesh_digest") == pointer.get("mesh_digest"):
                index_publish.write_json_atomic(root / CURRENT_NAME, updated)
    except (OSError, index_publish.LockLost):
        pass
    finally:
        lock.release()
    return updated


# --- ensure -------------------------------------------------------------------------


@dataclass
class MeshGraph:
    mesh: mesh_scope.Mesh
    members: list[mesh_scope.Member]
    doc: dict[str, Any]
    index_dir: Path
    pointer: dict[str, Any] | None
    rebuilt: bool = False
    in_memory: bool = False
    driver_note: str | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def generation(self) -> str | None:
        return None if self.in_memory or not self.pointer else self.pointer.get("generation")

    @property
    def mesh_digest(self) -> str:
        return str(self.doc.get("mesh_digest") or "")


def _pages_from_projection(member: mesh_scope.Member, projection: dict[str, Any]) -> mesh_scope.MemberPages:
    """Pages for the view from a projection already loaded. Logs are dropped, as in ``graph.load_source``."""
    pages: dict[str, Any] = {}
    withheld: set[str] = set()
    for page in projection["pages"]:
        if page.role == "log":
            continue
        if mesh_scope.is_restricted(page.meta):
            withheld.add(page.path)
        else:
            pages[page.path] = page
    return mesh_scope.MemberPages(member, pages, frozenset(withheld))


def _load_member_once(member: mesh_scope.Member) -> tuple[MemberState, mesh_scope.MemberPages]:
    """Schema, corpus digest, fingerprint and pages from one read of this member.

    The digest is the hash of the bytes :func:`project_store` parsed, not of a
    later reread.
    """
    schema = _member_schema(member)
    try:
        projection = project_store(member.root, schema)
    except ProjectionError as e:
        text = str(e)
        if "unreadable" in text or "root_escape" in text:
            raise MeshGraphError(
                f"store {member.atlas_id}: corpus is incomplete (an eligible page is unreadable)"
            ) from e
        raise MeshGraphError(f"store {member.atlas_id}: {e}") from e
    state = MemberState(
        member,
        schema,
        eligible_paths(member.root, schema),
        str(projection["cheap_fingerprint"]),
        str(projection["corpus_digest"]),
    )
    return state, _pages_from_projection(member, projection)


def _load_consistent(
    mesh: mesh_scope.Mesh, all_members: list[mesh_scope.Member]
) -> tuple[list[MemberState], dict[str, Any]]:
    """Member states and the view from one load per included member. No second read."""
    states: list[MemberState] = []
    loaded: dict[int, mesh_scope.MemberPages] = {}
    for member in all_members:
        if member.status != mesh_scope.STATUS_OK:
            continue
        state, pages = _load_member_once(member)
        states.append(state)
        loaded[member.index] = pages
    return states, mesh_scope.assemble_view(mesh, all_members, loaded)


def ensure(
    mesh: mesh_scope.Mesh,
    *,
    force: bool = False,
    wait: float | None = None,
    fallback: bool = True,
) -> MeshGraph:
    """The current mesh graph, rebuilt under the ``_mesh`` lock when the digest changed.

    ``wait`` (default :data:`READ_WAIT_SECONDS`) bounds the wait for a busy
    lock. With ``fallback`` a busy lock (or a lock lost mid-build) yields an
    in-memory build with ``driver_note: mesh_index_busy``; without it
    :class:`index_publish.IndexBusy` propagates (``atlas index build --mesh``).
    Raises :class:`MeshGraphError` for an unreadable member or an unsafe path.

    A rebuild (and the busy fallback) loads each included member once and
    publishes that view under that load's digest. A probe used only to skip
    the lock is never paired with a later reread.
    """
    root = index_dir(mesh.project)
    all_members = mesh_scope.members(mesh)
    pointer = read_pointer(root)
    probe_states: list[MemberState] | None = None
    probe_digest: str | None = None
    if not force:
        probe_states = member_states(all_members)
        fill_digests(probe_states)
        probe_digest = mesh_digest(probe_states, all_members)
        if usable_pointer(pointer) and pointer.get("mesh_digest") == probe_digest:
            doc = load_snapshot(root, pointer)
            if doc is not None:
                return MeshGraph(mesh, all_members, doc, root, _refresh_fingerprints(root, pointer, probe_states))
    warnings: list[dict[str, Any]] = []

    def fresh() -> tuple[dict[str, Any], dict[str, Any]] | None:
        if force or probe_digest is None:
            return None
        cur = read_pointer(root)
        if not usable_pointer(cur) or cur.get("mesh_digest") != probe_digest:
            return None
        doc = load_snapshot(root, cur)
        return (doc, cur) if doc is not None else None

    def publish(
        lock: index_publish.BuildLock, states: list[MemberState], digest: str, doc: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        gen_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        base = Path(mesh.project).resolve() / index_location.INDEXES_REL
        tmp_dir = root / f"{index_publish.TMP_PREFIX}{gen_id}"
        dest = root / "generations" / gen_id
        index_location.reject_symlink_escape(base, tmp_dir)
        index_location.reject_symlink_escape(base, dest)
        tmp_dir.mkdir(parents=True)
        try:
            paths.atomic_write_text(tmp_dir / GRAPH_NAME, dump_doc(doc))
            index_publish.ensure_owned(lock)
            index_publish.publish_dir(tmp_dir, dest)
        except BaseException:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        new_pointer = _pointer(gen_id, digest, doc, states, all_members)
        try:
            with index_publish.critical_section(lock):
                before = read_pointer(root) or {}
                index_publish.write_json_atomic(root / CURRENT_NAME, new_pointer)
                retired = _prune(root, gen_id, str(before.get("generation") or "") or None)
        except index_publish.LockLost:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        index_publish.discard(retired)
        return doc, new_pointer

    def build(lock: index_publish.BuildLock) -> tuple[dict[str, Any], dict[str, Any]]:
        guard = _guard_ignore(all_members)
        if guard:
            warnings.append(guard)
        states, view = _load_consistent(mesh, all_members)
        digest = mesh_digest(states, all_members)
        if not force:
            cur = read_pointer(root)
            if usable_pointer(cur) and cur.get("mesh_digest") == digest:
                found = load_snapshot(root, cur)
                if found is not None:
                    return found, _refresh_fingerprints(root, cur, states)
        return publish(lock, states, digest, snapshot_doc(view, digest))

    try:
        (doc, cur), built = index_publish.locked_build(
            root, fresh, build, wait=READ_WAIT_SECONDS if wait is None else wait, warnings=warnings
        )
    except (index_publish.IndexBusy, index_publish.LockLost):
        # A lock lost mid-build falls back like a busy one; only ``fallback=False`` re-raises.
        if not fallback:
            raise
        _states, view = _load_consistent(mesh, all_members)
        digest = mesh_digest(_states, all_members)
        doc = snapshot_doc(view, digest)
        return MeshGraph(mesh, all_members, doc, root, None, in_memory=True, driver_note=BUSY_NOTE, warnings=warnings)
    return MeshGraph(mesh, all_members, doc, root, cur, rebuilt=built, warnings=warnings)


def _guard_ignore(all_members: list[mesh_scope.Member]) -> dict[str, Any] | None:
    """Make sure ``.atlas/indexes/`` is ignored (P22), via the first included member; advisory only."""
    for m in all_members:
        if m.status == mesh_scope.STATUS_OK:
            location = m.location()
            try:
                if location is None:
                    item = ensure_indexes_ignored(m.root)
                else:
                    with index_location.pinned(location):
                        item = ensure_indexes_ignored(m.root)
            except Exception:  # noqa: BLE001 - the guard never blocks a build
                return None
            return item if item and item.get("level") == "warning" else None
    return None


def status(mesh: mesh_scope.Mesh) -> dict[str, Any]:
    """Read-only freshness of the mesh graph index (nothing is built or written)."""
    out: dict[str, Any] = {"dir": None, "built": False, "generation": None, "fresh": None, "mesh_digest": None, "unresolved_by_reason": None}
    try:
        root = index_dir(mesh.project)
    except MeshGraphError as e:
        out["error"] = str(e)
        return out
    out["dir"] = relative_dir(mesh.project, root)
    pointer = read_pointer(root)
    if not usable_pointer(pointer) or load_snapshot(root, pointer) is None:
        return out
    out.update(
        built=True,
        generation=pointer.get("generation"),
        mesh_digest=pointer.get("mesh_digest"),
        unresolved_by_reason=pointer.get("unresolved_by_reason"),
    )
    try:
        all_members = mesh_scope.members(mesh)
        states = member_states(all_members)
        fill_digests(states)
        out["fresh"] = mesh_digest(states, all_members) == pointer.get("mesh_digest")
    except (mesh_scope.MeshScopeError, OSError) as e:
        out["fresh"] = False
        out["error"] = str(e)
    return out


def refresh_after_compile(store: Path) -> dict[str, Any] | None:
    """M10(c): after a compile of a member store, refresh the mesh graph if its index already exists.

    Returns an info item, a non-blocking warning item (``mesh_graph_refresh_failed``) or ``None``.
    """
    try:
        mesh = mesh_scope.discover(store)
    except (mesh_scope.MeshScopeError, OSError):
        return None
    if not exists(mesh.project):
        return None
    target = Path(store).resolve()
    try:
        # Only included roots are resolved: excluded and invalid roots are never touched.
        member = next(
            (m for m in mesh_scope.members(mesh) if m.status == mesh_scope.STATUS_OK and m.root.resolve() == target),
            None,
        )
    except (mesh_scope.MeshScopeError, OSError):
        member = None
    if member is None or member.status != mesh_scope.STATUS_OK:
        return None
    path = ".atlas/indexes/graph/_mesh"
    try:
        result = ensure(mesh)
        path = relative_dir(mesh.project, result.index_dir)
    except Exception as e:  # noqa: BLE001 - a failed refresh never changes compile's exit code
        return {"id": REFRESH_FAILED, "level": "warning", "path": path, "msg": f"mesh graph refresh failed: {e}"}
    if result.in_memory:
        return {
            "id": REFRESH_FAILED,
            "level": "warning",
            "path": path,
            "msg": "mesh graph refresh skipped: another build holds the lock (mesh_index_busy)",
        }
    verb = "rebuilt" if result.rebuilt else "already fresh"
    return {
        "id": REFRESHED if result.rebuilt else FRESH,
        "level": "info",
        "path": path,
        "msg": f"mesh graph {verb}: generation {result.generation}",
        "generation": result.generation,
    }


# --- scope configuration ---------------------------------------------------------------


def configured_scope(doc: dict[str, Any] | None, block: str) -> str | None:
    value = ((doc or {}).get(block) or {}).get("scope") if isinstance((doc or {}).get(block), dict) else None
    return value if value in meshfile.SCOPES else None


def configured_driver(doc: dict[str, Any] | None) -> str | None:
    block = (doc or {}).get("graph")
    value = block.get("driver") if isinstance(block, dict) else None
    return value if value in meshfile.GRAPH_DRIVERS else None


def in_use(mesh: mesh_scope.Mesh) -> bool:
    """A mesh scope is configured or the mesh graph index exists (gates the `index status` block, M15)."""
    return (
        configured_scope(mesh.doc, "graph") == "mesh"
        or configured_scope(mesh.doc, "recall") == "mesh"
        or exists(mesh.project)
    )


def describe_block(mesh: mesh_scope.Mesh) -> dict[str, Any]:
    """The `index status` / `index show --mesh` mesh block (read-only)."""
    all_members = mesh_scope.members(mesh)
    scope: dict[str, Any] = {"source": {}}
    for block in ("recall", "graph"):
        value = configured_scope(mesh.doc, block)
        scope[block] = value or "store"
        scope["source"][block] = "config" if value else "default"
    return {
        "project": str(mesh.project),
        "members": [m.as_dict() for m in all_members],
        "excluded": _ids_with(all_members, mesh_scope.STATUS_EXCLUDED),
        "invalid": [
            {"atlas_id": m.atlas_id, "reason": m.reason}
            for m in sorted(all_members, key=lambda m: m.atlas_id)
            if m.status == mesh_scope.STATUS_INVALID
        ],
        "scope": scope,
        "indexes": {
            "graph": status(mesh),
            "nanograph": {"built": False, "note": "nanograph mesh graph is not built yet (packet MD)"},
        },
    }


def block_lines(block: dict[str, Any]) -> list[str]:
    members = ", ".join(f"{m['atlas_id']} ({m['status']})" for m in block["members"]) or "(none)"
    scope = block["scope"]
    g = block["indexes"]["graph"]
    lines = [
        f"mesh members: {members}",
        f"mesh excluded: {', '.join(block['excluded']) or '-'}",
        "mesh invalid: " + (", ".join(f"{m['atlas_id']} ({m['reason']})" for m in block["invalid"]) or "-"),
        f"mesh scope: recall={scope['recall']} ({scope['source']['recall']}) graph={scope['graph']} ({scope['source']['graph']})",
    ]
    if g.get("built"):
        counts = " ".join(f"{k}={v}" for k, v in sorted((g.get("unresolved_by_reason") or {}).items()) if v) or "none"
        lines.append(
            f"mesh graph: {g['dir']} generation={g['generation']} fresh={str(g['fresh']).lower()} unresolved: {counts}"
        )
    else:
        lines.append(f"mesh graph: {g.get('dir') or '-'} not built" + (f" ({g['error']})" if g.get("error") else ""))
    lines.append("mesh nanograph: not built (packet MD)")
    return lines


# --- queries --------------------------------------------------------------------------


def _exit_state(node: dict[str, Any]) -> str | None:
    for key in EXIT_FIELDS:
        if is_exit_value(node.get(key)):
            return str(node[key]).strip().lower()
    return None


class Hydrator:
    """Reads titles and non-indexed fields back from each member's own source (M6).

    Only included members are ever loaded, each through its pinned mesh
    location (:func:`mesh_scope.load_member`); restricted pages are never returned.
    """

    def __init__(self, members: list[mesh_scope.Member]) -> None:
        self.by_id = {m.atlas_id: m for m in members if m.status == mesh_scope.STATUS_OK}
        self.cache: dict[str, dict[str, Any]] = {}

    def page(self, node: dict[str, Any]) -> Any | None:
        sid = node["atlas_id"]
        if sid not in self.cache:
            member = self.by_id.get(sid)
            if member is None:
                self.cache[sid] = {}
            else:
                self.cache[sid] = dict(mesh_scope.load_member(member).pages)
        return self.cache[sid].get(node["path"])

    def title(self, node: dict[str, Any]) -> str:
        page = self.page(node)
        return page.title if page is not None else ""

    def matches(self, node: dict[str, Any], wheres: list[tuple[str, str]]) -> bool:
        pending: list[tuple[str, str]] = []
        for key, want in wheres:
            if key in INDEXED_FIELDS and key in node:
                if graph.normalise_text(node[key]) != want:
                    return False
            elif key in ("atlas_id", "path", "id"):
                if node.get(key) != want:
                    return False
            else:
                pending.append((key, want))
        if not pending:
            return True
        page = self.page(node)
        return page is not None and graph.where_matches(page.meta, pending)


def _public_node(node: dict[str, Any], hydrator: Hydrator, hop: int | None = None) -> dict[str, Any]:
    out = {**node, "title": hydrator.title(node)}
    if hop is not None:
        out["hop"] = hop
    return out


_UNREADABLE = frozenset({mesh_scope.STATUS_EXCLUDED, mesh_scope.STATUS_INVALID})


def _unreadable_why(member: mesh_scope.Member) -> str:
    if member.status == mesh_scope.STATUS_INVALID:
        return f"is an invalid mesh row ({member.reason}); it is never read"
    return "is excluded from the mesh (mesh_member: false)"


class Query:
    """Mesh-scope verbs over a :class:`MeshGraph` snapshot."""

    def __init__(self, mg: MeshGraph, root_store: Path | None) -> None:
        self.mg = mg
        self.nodes = {n["id"]: n for n in mg.doc["nodes"]}
        self.edges = list(mg.doc["edges"])
        self.members = mg.members
        self.by_key = {meshfile.id_key(m.atlas_id): m for m in self.members}
        self.hosts = mesh_scope.mesh_hosts(m.atlas_id for m in self.members)
        self.hydrator = Hydrator(self.members)
        target = Path(root_store).resolve() if root_store is not None else None
        self.root_member = next(
            (m for m in self.members if m.status == mesh_scope.STATUS_OK and target is not None and m.root.resolve() == target),
            None,
        )

    # page arguments and --store

    def member_for(self, raw_id: str) -> mesh_scope.Member:
        text = str(raw_id or "").strip()
        if text.startswith(mesh_scope.ATLAS_SCHEME):
            text = text[len(mesh_scope.ATLAS_SCHEME) :]
        found = self.by_key.get(meshfile.id_key(text))
        if found is None:
            known = ", ".join(m.atlas_id for m in self.members) or "(none)"
            raise MeshGraphError(f"--store {raw_id!r} is not a row of {meshfile.MESH_NAME}; known ids: {known}")
        if found.status in _UNREADABLE:
            raise MeshGraphError(f"--store {found.atlas_id} {_unreadable_why(found)}")
        return found

    def store_ids(self, stores: tuple[str, ...] | list[str]) -> set[str] | None:
        if not stores:
            return None
        return {self.member_for(s).atlas_id for s in stores}

    def target_id(self, page: str) -> str:
        """A page argument as a node id: a canonical ``atlas://`` URI or a path in the ``--root`` store."""
        text = str(page or "").strip()
        if text.startswith(mesh_scope.ATLAS_SCHEME):
            atlas_id, path = mesh_scope.parse_node_id(text, self.hosts)
            member = self.by_key.get(meshfile.id_key(atlas_id))
            if member is None:
                raise MeshGraphError(f"{page!r}: store {atlas_id} is not in this mesh")
            if member.status in _UNREADABLE:
                raise MeshGraphError(f"{page!r}: store {member.atlas_id} {_unreadable_why(member)}")
            return mesh_scope.node_id(member.atlas_id, path)
        if self.root_member is None:
            raise MeshGraphError(
                f"{page!r}: --root is not a member store; pass a canonical atlas://<atlas-id>/<path> page"
            )
        path = normalise_target(text).lstrip("/")
        return mesh_scope.node_id(self.root_member.atlas_id, path)

    def node(self, page: str) -> dict[str, Any]:
        nid = self.target_id(page)
        node = self.nodes.get(nid)
        if node is None:
            raise MeshGraphError(f"unknown page {page!r} in mesh scope (expected an atlas://<atlas-id>/<path> node or a path in the --root store)")
        return node

    def check_anchor(self, node: dict[str, Any], include_exits: bool, label: str = "starting page") -> None:
        state = None if include_exits else _exit_state(node)
        if state is None:
            return
        hint = "traverse from it" if label == "starting page" else "include it"
        raise MeshGraphError(f"{label} {node['id']} is in exit state {state}; pass --include-exits to {hint}")

    # verbs

    def nodes_query(
        self,
        *,
        wheres: list[tuple[str, str]],
        stores: tuple[str, ...] = (),
        path_prefix: str | None = None,
        include_exits: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        only = self.store_ids(stores)
        reveal = include_exits or graph.asks_for_exit(wheres)
        out: list[dict[str, Any]] = []
        truncated = False
        for node in sorted(self.nodes.values(), key=lambda n: n["id"]):
            if only is not None and node["atlas_id"] not in only:
                continue
            if not reveal and _exit_state(node) is not None:
                continue
            if not graph._path_prefix_matches(node["path"], path_prefix):
                continue
            if not self.hydrator.matches(node, wheres):
                continue
            if limit is not None and len(out) >= limit:
                truncated = True
                break
            out.append(_public_node(node, self.hydrator))
        return {"nodes": out, "truncated": truncated}

    def edges_query(
        self,
        *,
        from_page: str | None = None,
        to_page: str | None = None,
        kinds: tuple[str, ...] = (),
        stores: tuple[str, ...] = (),
        include_exits: bool = False,
    ) -> dict[str, Any]:
        only = self.store_ids(stores)
        src = None
        if from_page:
            node = self.node(from_page)
            self.check_anchor(node, include_exits)
            src = node["id"]
        dst = None
        if to_page:
            dst = self.target_id(to_page)
            if dst in self.nodes:
                self.check_anchor(self.nodes[dst], include_exits, label="page")
        kind_set = set(kinds or ())
        out: list[dict[str, Any]] = []
        for edge in self.edges:
            if src is not None and edge["from"] != src:
                continue
            if dst is not None and edge["to"] != dst:
                continue
            if kind_set and edge["kind"] not in kind_set:
                continue
            if only is not None and self.nodes.get(edge["from"], {}).get("atlas_id") not in only:
                continue
            if not include_exits:
                ends = [self.nodes.get(edge["from"]), self.nodes.get(edge["to"])]
                if any(n is not None and _exit_state(n) is not None for n in ends):
                    continue
            out.append(dict(edge))
        return {"edges": out, "unresolved_by_reason": count_reasons(out)}

    def neighbours_query(
        self,
        seed: str,
        *,
        kinds: tuple[str, ...] = (),
        direction: str = "both",
        hops: int = 1,
        wheres: list[tuple[str, str]] | None = None,
        max_nodes: int | None = graph.DEFAULT_MAX_NODES,
        max_edges: int | None = graph.DEFAULT_MAX_EDGES,
        include_exits: bool = False,
    ) -> dict[str, Any]:
        """Bounded BFS across stores with the P6 caps and the exit-state rule (as ``graph.query_neighbours``)."""
        if direction not in ("in", "out", "both"):
            raise MeshGraphError("--direction must be in, out or both")
        if hops < 1 or hops > graph.MAX_HOPS:
            raise MeshGraphError(f"--hops must be between 1 and {graph.MAX_HOPS}")
        if max_nodes is not None and max_nodes < 1:
            raise MeshGraphError("--max-nodes must be at least 1")
        if max_edges is not None and max_edges < 1:
            raise MeshGraphError("--max-edges must be at least 1")
        wheres = wheres or []
        seed_node = self.node(seed)
        self.check_anchor(seed_node, include_exits)
        reveal = include_exits or graph.asks_for_exit(wheres)
        kind_set = frozenset(kinds or ())
        outgoing: dict[str, list[dict[str, Any]]] = {}
        incoming: dict[str, list[dict[str, Any]]] = {}
        for edge in self.edges:
            if edge.get("resolved") and edge["to"] in self.nodes:
                outgoing.setdefault(edge["from"], []).append(edge)
                incoming.setdefault(edge["to"], []).append(edge)

        def steps(current: str) -> list[tuple[str, str, str, dict[str, Any]]]:
            out: list[tuple[str, str, str, dict[str, Any]]] = []
            if direction in ("both", "out"):
                out += [(e["to"], e["kind"], "outgoing", e) for e in outgoing.get(current, [])]
            if direction in ("both", "in"):
                out += [(e["from"], e["kind"], "incoming", e) for e in incoming.get(current, [])]
            if kind_set:
                out = [s for s in out if s[1] in kind_set]
            return sorted(out, key=lambda s: (s[0], s[1], s[2]))

        hop_of: dict[str, int] = {seed_node["id"]: 0}
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        edge_keys: set[tuple[str, str, str]] = set()
        truncated = False
        level = [seed_node["id"]]
        hop = 0
        while level and hop < hops and not truncated:
            next_level: list[str] = []
            for current in sorted(level):
                for other, kind, step_dir, edge in steps(current):
                    other_node = self.nodes.get(other)
                    if other_node is None or (not reveal and _exit_state(other_node) is not None):
                        continue
                    key = (current, other, kind) if step_dir == "outgoing" else (other, current, kind)
                    is_new = other not in hop_of
                    wanted = is_new and self.hydrator.matches(other_node, wheres)
                    if wanted and max_nodes is not None and len(nodes) >= max_nodes:
                        truncated = True
                        break
                    if key not in edge_keys:
                        if max_edges is not None and len(edges) >= max_edges:
                            truncated = True
                            break
                        edge_keys.add(key)
                        edges.append(
                            {
                                "from": key[0],
                                "to": key[1],
                                "kind": kind,
                                "direction": "out" if step_dir == "outgoing" else "in",
                                "hop": hop + 1,
                                "cross": bool(edge.get("cross")),
                                "resolution": edge.get("resolution"),
                            }
                        )
                    if is_new:
                        hop_of[other] = hop + 1
                        next_level.append(other)
                        if wanted:
                            nodes.append(_public_node(other_node, self.hydrator, hop + 1))
                if truncated:
                    break
            level = next_level
            hop += 1
        nodes.sort(key=lambda n: (n["hop"], n["id"]))
        edges.sort(key=lambda e: (e["hop"], e["from"], e["to"], e["kind"]))
        return {
            "seed": seed_node["id"],
            "direction": direction,
            "hops": hops,
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
            "driver_used": NATIVE_DRIVER,
        }


def count_reasons(edges: list[dict[str, Any]]) -> dict[str, int]:
    counts = {reason: 0 for reason in mesh_scope.REASONS}
    for edge in edges:
        if edge.get("reason") in counts:
            counts[edge["reason"]] += 1
    return counts


# --- export ---------------------------------------------------------------------------


_MAX_SYMLINK_HOPS = 40


def _out_aliases(out: Path, inside: Any) -> Path | None:
    """Every spelling ``out`` takes while its symlinks are followed; the first one ``inside`` refuses.

    Each spelling is checked before any component under it is examined, so a
    path through an excluded or invalid member's (symlinked) root is refused
    without that root or anything beneath it being touched.
    """
    current = Path(os.path.normpath(os.path.abspath(out)))
    for _ in range(_MAX_SYMLINK_HOPS):
        if inside(current):
            return current
        parts = current.parts
        for i in range(2, len(parts) + 1):
            prefix = Path(*parts[:i])
            if not prefix.is_symlink():
                continue
            current = Path(os.path.normpath(prefix.parent.joinpath(os.readlink(prefix), *parts[i:])))
            break
        else:
            return None
    return None


def check_export_out(mesh: mesh_scope.Mesh, out: str) -> Path:
    """Refuse an ``--out`` inside any member root (every row) or under ``.atlas/indexes/`` (M7).

    Excluded and invalid roots are compared lexically (never resolved), against
    every spelling ``--out`` takes while its symlinks are followed, so writing
    through a symlinked member root (or a link into one) is refused too.
    """
    raw = Path(out).expanduser()
    forbidden: list[tuple[Path, str]] = [
        ((Path(mesh.project).resolve() / index_location.INDEXES_REL), f"under {index_location.INDEXES_REL.as_posix()}/")
    ]
    for m in mesh_scope.members(mesh):
        why = f"inside member {m.atlas_id}"
        lexical = Path(os.path.abspath(m.root))
        forbidden.append((lexical, why))
        if m.status in _UNREADABLE:
            continue
        try:
            forbidden.append((m.root.resolve(), why))
        except OSError:
            pass

    def inside(path: Path) -> tuple[Path, str] | None:
        for base, why in forbidden:
            if path == base or base in path.parents:
                return base, why
        return None

    def refuse(path: Path, why: str) -> MeshGraphError:
        return MeshGraphError(f"--out {path} is {why}; choose a directory outside every member and .atlas/indexes/")

    try:
        alias = _out_aliases(raw, lambda p: inside(p) is not None)
    except (OSError, RuntimeError, ValueError):
        alias = None
    hit = inside(alias) if alias is not None else None
    if hit is not None:
        raise refuse(Path(os.path.abspath(raw)), hit[1])
    # Resolved only once no spelling of --out is inside a member, so no member root is followed.
    out_dir = raw.resolve()
    hit = inside(out_dir)
    if hit is not None:
        raise refuse(out_dir, hit[1])
    return out_dir


def export_json(mg: MeshGraph, out_dir: Path) -> tuple[list[str], dict[str, Any]]:
    """Structure-only ``graph.json`` plus ``export-receipt.json`` listing the members combined."""
    doc = mg.doc
    included = sorted(m.atlas_id for m in mg.members if m.status == mesh_scope.STATUS_OK)
    unresolved = sum(1 for e in doc["edges"] if not e.get("resolved"))
    receipt = {
        "format": "json",
        "scope": "mesh",
        "structure_only": True,
        "mesh_digest": doc["mesh_digest"],
        "members": included,
        "excluded": _ids_with(mg.members, mesh_scope.STATUS_EXCLUDED),
        "unmounted": _ids_with(mg.members, mesh_scope.STATUS_UNMOUNTED),
        "invalid": _ids_with(mg.members, mesh_scope.STATUS_INVALID),
        "nodes": len(doc["nodes"]),
        "edges": len(doc["edges"]),
        "unresolved": unresolved,
        "unresolved_by_reason": dict(doc["unresolved_by_reason"]),
        "files": ["export-receipt.json", "graph.json"],
    }
    graph_path = out_dir / "graph.json"
    receipt_path = out_dir / "export-receipt.json"
    try:
        paths.ensure_directory(out_dir)
        # Refuse both names before either write, so a regular graph.json is
        # not replaced when export-receipt.json is a symlink.
        paths.refuse_non_regular(graph_path)
        paths.refuse_non_regular(receipt_path)
        paths.atomic_write_text(graph_path, dump_doc(doc))
        paths.atomic_write_text(receipt_path, dump_doc(receipt))
    except paths.UnsafeDestination as e:
        raise MeshGraphError(str(e)) from e
    return receipt["files"], receipt
