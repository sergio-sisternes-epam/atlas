#!/usr/bin/env python3
"""Review R4: invalid ids are invalid members; members load through their mesh location.

1. Every id form ``atlas-mesh.json`` validation accepts is checked against
   mesh scope. A row id that ``index_location.safe_id_path`` rejects is an
   ``invalid`` member with reason ``invalid_atlas_id``: an empty host
   (``/acme/repo``, ``:8080/acme/repo``), a host with a port
   (``git.example.com:8443/acme/repo``) or an IPv6 literal
   (``[::1]/acme/repo``, ``[fe80::1]:8080/acme/repo``). Decided before any
   filesystem access of its root, never read or projected, and a link into
   it is unresolved (``outside_mesh``). Invariant: every ``ok`` member's id
   round-trips through ``node_id`` / ``parse_node_id`` and a link to its
   page resolves as ``atlas_uri``. Global validation is unchanged.
2. A ``subpath`` row and a pathless row (which ``index_location.mesh_match``
   cannot match) load through their mesh location: their own
   ``.atlas/indexes/fts5/<row id>/`` index is used, no ``local/...`` id is
   consulted and no ``git`` subprocess runs.

Linux-safe: no network; git is banned in part 2.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import graph, index_location, mesh_scope, meshfile, recall_index  # noqa: E402
from atlas_cli.core.overlay import merge_overlays  # noqa: E402
from atlas_cli.core.schema import load_schema  # noqa: E402
from test_mesh_members import Guard  # noqa: E402

SRC = "github.com/acme/src"
# (label, id, expected to be a valid member)
ID_FORMS: list[tuple[str, str, bool]] = [
    ("dotted-host", "github.com/acme/repo", True),
    ("localhost", "localhost/acme/repo", True),
    ("host-port", "git.example.com:8443/acme/repo", False),
    ("ipv4", "10.0.0.5/acme/repo", True),
    ("ipv6", "[::1]/acme/repo", False),
    ("ipv6-port", "[fe80::1]:8080/acme/repo", False),
    ("intranet-host", "intranet/acme/repo", True),
    ("empty-host", "/acme/repo", False),
    ("empty-host-port", ":8080/acme/repo", False),
]
# Forms validation rejects; mesh scope never sees them.
REJECTED = ["//acme/repo", "/github.com/acme/repo", "github.com/acme/repo/", "GitHub.com/acme/repo", "github.com//acme/repo"]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def store(root: Path, links: list[str] | None = None) -> None:
    write(root / "CONTRACT.json", json.dumps({"schema_version": "1.0", "atlas_id": "fixture", "title": "t"}) + "\n")
    lines = ["---", "type: lesson", "title: t", "status: active"]
    if links:
        lines.append("relates_to:")
        lines += [f"  - path: {json.dumps(r)}\n    kind: related" for r in links]
    lines += ["---", "", "body.", ""]
    write(root / "x.md", "\n".join(lines))


def use_mesh(project: Path, rows: list[dict[str, Any]]) -> mesh_scope.Mesh:
    write(project / "atlas-mesh.json", json.dumps({"version": 1, "stores": rows}) + "\n")
    index_location.clear_cache()
    return mesh_scope.discover(project)


def accepted(sid: str) -> bool:
    return not meshfile.validate_doc({"version": 1, "stores": [{"id": sid, "path": "atlas/s"}]})


def guarded(root: Path, fn: Callable[[], Any]) -> tuple[Any, list[str], str]:
    with Guard(root) as guard:
        try:
            return fn(), guard.hits, ""
        except Exception as e:  # noqa: BLE001
            return None, guard.hits, repr(e)


class GitBan:
    """Fail (and record) any ``git`` subprocess; record every resolved index location."""

    NAMES = ("run", "Popen", "check_output", "check_call", "call")

    def __init__(self) -> None:
        self.git: list[str] = []
        self.ids: list[str] = []
        self.standalone: list[str] = []
        self.sources: list[dict[str, Any]] = []
        self.saved: list[tuple[object, str, object]] = []

    def _patch(self, owner: object, name: str, make: Callable[[Any], Any]) -> None:
        original = getattr(owner, name)
        self.saved.append((owner, name, original))
        setattr(owner, name, make(original))

    def __enter__(self) -> GitBan:
        ban = self

        def subproc(original: Any) -> Any:
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                cmd = args[0] if args else kwargs.get("args")
                first = cmd if isinstance(cmd, (str, bytes)) else (list(cmd)[0] if cmd else "")
                text = os.fsdecode(first) if isinstance(first, (str, bytes)) else str(first)
                if os.path.basename(text.split()[0] if text.split() else text) == "git":
                    ban.git.append(str(cmd))
                    raise RuntimeError(f"git subprocess in mesh scope: {cmd}")
                return original(*args, **kwargs)

            return wrapped

        for name in self.NAMES:
            self._patch(subprocess, name, subproc)

        def resolve(original: Any) -> Any:
            def wrapped(store: Path) -> Any:
                loc = original(store)
                ban.ids.append(loc.atlas_id)
                return loc

            return wrapped

        def standalone(original: Any) -> Any:
            def wrapped(store: Path) -> Any:
                ban.standalone.append(str(store))
                return original(store)

            return wrapped

        def load_source(original: Any) -> Any:
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                source = original(*args, **kwargs)
                ban.sources.append(source)
                return source

            return wrapped

        self._patch(index_location, "resolve", resolve)
        self._patch(index_location, "_standalone", standalone)
        self._patch(graph, "load_source", load_source)
        return self

    def __exit__(self, *exc: object) -> None:
        for owner, name, original in reversed(self.saved):
            setattr(owner, name, original)


def publish(project: Path, root: Path, sid: str) -> Path:
    """Publish an fts5 index for ``root`` under ``.atlas/indexes/fts5/<sid>/`` (the row's mesh location)."""
    index_location.clear_cache()
    loc = index_location.IndexLocation(root.resolve(), project.resolve(), sid, "mesh", "mesh")
    index_location._cache[(str(root.resolve()), "")] = loc
    try:
        schema, err = load_schema(root)
        assert schema is not None, err
        merged, _, _ = merge_overlays(schema, root)
        recall_index.publish_fts5(root, merged)
    finally:
        index_location.clear_cache()
    return project / ".atlas" / "indexes" / "fts5" / Path(*sid.split("/"))


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    # 1. Validation is unchanged: every listed form is accepted or rejected as before.
    for label, sid, _ in ID_FORMS:
        check(f"validation-accepts {label}", accepted(sid), sid)
    for sid in REJECTED:
        check(f"validation-rejects {sid}", not accepted(sid))

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-r4-"))
    try:
        project = tmp / "proj"
        for label, sid, valid in ID_FORMS:
            shutil.rmtree(project, ignore_errors=True)
            store(project / "atlas" / "src", [f"atlas://{sid}/x.md", "../t/x.md"])
            store(project / "atlas" / "t")
            mesh = use_mesh(project, [{"id": SRC, "path": "atlas/src"}, {"id": sid, "path": "atlas/t"}])
            target_root = project / "atlas" / "t"
            if valid:
                got, hits, error = mesh_scope.members(mesh), [], ""
            else:
                got, hits, error = guarded(target_root, lambda: mesh_scope.members(mesh))
            status = {m.atlas_id: (m.status, m.reason) for m in got or []}
            want = ("ok", None) if valid else ("invalid", "invalid_atlas_id")
            check(f"member-status {label}", status.get(sid) == want and not error, f"{status.get(sid)} {error}")
            if not valid:
                check(f"invalid-untouched {label}", not hits, str(hits[:3]))
                view, hits, error = guarded(target_root, lambda: mesh_scope.build_view(mesh))
                check(f"invalid-view-untouched {label}", not hits and not error, f"{hits[:3]} {error}")
                view = view or {}
                check(f"invalid-no-nodes {label}", all(n["atlas_id"] != sid for n in view.get("nodes", [])))
                into = [e for e in view.get("edges", []) if e["from"] == f"atlas://{SRC}/x.md"]
                check(f"invalid-links-unresolved {label}", into and not any(e["resolved"] for e in into), str(into))
                rel = next((e for e in into if e["to"] == "../t/x.md"), {})
                check(f"invalid-mesh-path-outside-mesh {label}", rel.get("reason") == "outside_mesh", str(rel))
            # The invariant, for every ok member of the view.
            view = mesh_scope.build_view(mesh)
            ok_ids = [m["atlas_id"] for m in view["members"] if m["status"] == "ok"]
            hosts = mesh_scope.mesh_hosts(ok_ids)
            src_edges = {
                e["to"]: e for e in view["edges"] if e["from"] == f"atlas://{SRC}/x.md" and e["resolution"] == "atlas_uri"
            }
            for aid in ok_ids:
                nid = mesh_scope.node_id(aid, "x.md")
                try:
                    back = mesh_scope.parse_node_id(nid, hosts)
                except mesh_scope.MeshScopeError as e:
                    back = (repr(e), "")
                check(f"invariant-round-trip {label} {aid}", back == (aid, "x.md"), str(back))
                check(f"invariant-node {label} {aid}", any(n["id"] == nid for n in view["nodes"]))
                if aid == sid:
                    rec = src_edges.get(nid) or {}
                    check(
                        f"invariant-resolves {label}",
                        rec.get("resolved") is True and rec.get("resolution") == "atlas_uri",
                        str(rec),
                    )
        # Pathless and excluded rows with an empty host are invalid too, and never touched.
        shutil.rmtree(project, ignore_errors=True)
        store(project / "atlas" / "src", ["../../.atlas/acme/repo/x.md"])
        store(project / ".atlas" / "acme" / "repo")
        mesh = use_mesh(
            project,
            [{"id": SRC, "path": "atlas/src"}, {"id": "/acme/repo"}, {"id": ":1/a/b", "mesh_member": False}],
        )
        view, hits, error = guarded(project / ".atlas" / "acme", lambda: mesh_scope.build_view(mesh))
        check("pathless-invalid-untouched", not hits and not error, f"{hits[:3]} {error}")
        status = [(m["atlas_id"], m["status"], m.get("reason")) for m in (view or {}).get("members", [])]
        check(
            "pathless-and-excluded-invalid",
            status[1:] == [("/acme/repo", "invalid", "invalid_atlas_id"), (":1/a/b", "invalid", "invalid_atlas_id")],
            str(status),
        )
        rel = next((e for e in (view or {}).get("edges", []) if e["to"] == "../../.atlas/acme/repo/x.md"), {})
        check("pathless-link-outside-mesh", rel.get("reason") == "outside_mesh", str(rel))

        # 2. subpath and pathless rows load through their own mesh location.
        shutil.rmtree(project, ignore_errors=True)
        sub_id, bare_id = "github.com/acme/subp", "github.com/acme/bare"
        sub_root = project / "repos" / "sub" / "atlas"
        bare_root = project / ".atlas" / "github.com" / "acme" / "bare"
        store(sub_root, [f"atlas://{bare_id}/x.md"])
        store(bare_root, [f"atlas://{sub_id}/x.md"])
        rows = [{"id": sub_id, "path": "repos/sub", "subpath": "atlas"}, {"id": bare_id}]
        write(project / "atlas-mesh.json", json.dumps({"version": 1, "stores": rows}) + "\n")
        for root, sid in ((sub_root, sub_id), (bare_root, bare_id)):
            where = publish(project, root, sid)
            check(f"index-published {sid}", (where / recall_index.CURRENT_NAME).is_file(), str(where))
        for label, start in (("project", project), ("subpath-root", sub_root), ("pathless-root", bare_root)):
            index_location.clear_cache()
            with GitBan() as ban:
                try:
                    mesh = mesh_scope.discover(start)
                    view = mesh_scope.build_view(mesh)
                    loaded = [mesh_scope.load_member(m) for m in mesh_scope.members(mesh) if m.status == "ok"]
                    error = ""
                except Exception as e:  # noqa: BLE001
                    view, loaded, error = {}, [], repr(e)
            check(f"no-git {label}", not ban.git and not error, f"{ban.git[:2]} {error}")
            check(f"no-standalone {label}", not ban.standalone, str(ban.standalone[:2]))
            check(
                f"row-id-locations {label}",
                bool(ban.ids) and set(ban.ids) <= {sub_id, bare_id} and not any(i.startswith("local/") for i in ban.ids),
                str(sorted(set(ban.ids))),
            )
            used = sorted(
                (s.get("index_location") or {}).get("atlas_id", "") for s in ban.sources if s.get("fast_path")
            )
            check(f"own-index-used {label}", len(ban.sources) == 4 and used == sorted([sub_id, bare_id] * 2), str(used))
            locs = [(s.get("index_location") or {}).get("mode") for s in ban.sources]
            check(f"mesh-mode {label}", locs and all(m == "mesh" for m in locs), str(locs))
            check(f"members-loaded {label}", sorted(p.member.atlas_id for p in loaded) == sorted([sub_id, bare_id]))
            edges = (view or {}).get("edges", [])
            check(f"cross-links-resolve {label}", len(edges) == 2 and all(e["resolved"] for e in edges), str(edges))
    finally:
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} mesh review R4 check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll mesh review R4 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
