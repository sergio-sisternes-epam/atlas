#!/usr/bin/env python3
"""Copilot review CR3 for federated recall (MC).

Recommended: a listed excluded ``subpath`` or pathless root is still a mesh.
Discovery resolves that row root and does not read the store, so a project
``recall.scope: mesh`` federates and reports the member excluded. It must not
fall back to store recall. Explicit ``--scope store`` still searches that
store alone: exclusion is a mesh-scope rule, and the flag overrides the
project setting.

A member root that is a symlink is ``invalid`` / ``symlinked_root``, decided
with ``lstat`` and not resolved for overlap. Lexical overlap and the
walk-skip exemption remain. Classification does not follow the link.

Linux-safe: no network, no git.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.commands import search as search_cmd  # noqa: E402
from atlas_cli.core import index_location, mesh_scope  # noqa: E402
from test_mesh_members import Guard  # noqa: E402
from test_mesh_recall import page, schema, write  # noqa: E402


class ContentGuard(Guard):
    """Guard member contents, but not the discovery probe ``<root>/atlas-mesh.json``.

    :func:`mesh_scope.discover` always stats that path to see whether ``--root``
    is itself a project. That is not a read of the store's pages.
    """

    def _inside(self, path: object) -> bool:
        if isinstance(path, int):
            return False
        try:
            text = os.fsdecode(os.fspath(path))
        except TypeError:
            return False
        absolute = os.path.normpath(os.path.join(os.getcwd(), text))
        if absolute == os.path.join(self.root, "atlas-mesh.json"):
            return False
        return absolute.startswith(self.root + os.sep)


class NoFollow(Guard):
    """Fail ``stat``/``open`` of exactly ``link``. ``lstat`` of the symlink is allowed."""

    def __init__(self, link: Path) -> None:
        super().__init__(link.parent)
        self.link = os.path.normpath(str(link))

    def __enter__(self) -> NoFollow:
        for name in ("stat", "open", "listdir", "scandir", "readlink", "access", "walk"):
            self._wrap_follow(os, name)
        self._wrap_follow(builtins, "open")
        self._wrap_follow(io, "open")
        return self

    def _wrap_follow(self, owner: object, name: str) -> None:
        original = getattr(owner, name)
        guard = self

        def wrapped(*args, **kwargs):
            # lstat (follow_symlinks=False) of the symlink itself is allowed.
            if kwargs.get("follow_symlinks") is False:
                return original(*args, **kwargs)
            if args and guard._inside(args[0]):
                guard.hits.append(f"{name}({args[0]})")
                raise PermissionError(f"symlink followed: {name} {args[0]}")
            return original(*args, **kwargs)

        self.saved.append((owner, name, original))
        setattr(owner, name, wrapped)

    def _inside(self, path: object) -> bool:
        if isinstance(path, int):
            return False
        try:
            text = os.fsdecode(os.fspath(path))
        except TypeError:
            return False
        return os.path.normpath(os.path.join(os.getcwd(), text)) == self.link

SUB = "github.com/acme/sub"
BARE = "github.com/acme/bare"
SIDE = "github.com/acme/side"
TOP = "github.com/acme/top"
NESTED = "github.com/acme/nested"
LEFT = "github.com/acme/left"
RIGHT = "github.com/acme/right"
HOP = "github.com/acme/hop"
QUERY = "graph export"
SUB_CANARY = "subpathwombatqx"
BARE_CANARY = "pathlesswombatqx"
ALIAS_CANARY = "aliaswombatqx"


def mesh_doc(stores: list[dict], *, scope: str | None) -> str:
    doc: dict = {"version": 1, "stores": stores}
    if scope is not None:
        doc["recall"] = {"scope": scope}
    return json.dumps(doc, indent=2) + "\n"


def statuses_of(project: Path) -> list[tuple[str, str, str | None]]:
    return [(m.atlas_id, m.status, m.reason) for m in mesh_scope.members(mesh_scope.discover(project))]


def run_scoped(
    root: Path,
    scope: str | None,
    guard_root: Path | None,
    *,
    engine: str = "grep",
    guard_cls: type[Guard] = Guard,
    guard: Guard | None = None,
) -> tuple[int, dict, list[str], str]:
    index_location.clear_cache()
    buf, ebuf = io.StringIO(), io.StringIO()
    if guard is None:
        guard = guard_cls(guard_root) if guard_root is not None else contextlib.nullcontext()
    code = 99
    try:
        with guard, contextlib.redirect_stdout(buf), contextlib.redirect_stderr(ebuf):
            code = search_cmd.run_scoped(str(root), QUERY, 10, True, engine, False, None, False, scope, None)
    except Exception as e:  # noqa: BLE001 - old code leaks and the guard raises
        index_location.clear_cache()
        hits = guard.hits if isinstance(guard, Guard) else []
        return 99, {"_error": repr(e)}, hits, ebuf.getvalue()
    index_location.clear_cache()
    hits = guard.hits if isinstance(guard, Guard) else []
    try:
        payload = json.loads(buf.getvalue())
    except ValueError:
        payload = {"_raw": buf.getvalue()}
    return code, payload, hits, ebuf.getvalue()


def build_listed_excluded(tmp: Path, *, scope: str | None) -> tuple[Path, Path, Path]:
    """Excluded subpath at ``mono/kb``, excluded pathless mount, included ``side/``."""
    project = tmp / "proj"
    sub = project / "mono" / "kb"
    bare = project / ".atlas" / "github.com" / "acme" / "bare"
    side = project / "side"
    schema(sub)
    write(sub / "notes" / "hidden.md", page(f"Graph export {SUB_CANARY}", f"Graph export {SUB_CANARY}", f"{SUB_CANARY} body."))
    schema(bare)
    write(bare / "notes" / "hidden.md", page(f"Graph export {BARE_CANARY}", f"Graph export {BARE_CANARY}", f"{BARE_CANARY} body."))
    schema(side)
    write(side / "notes" / "side.md", page("Graph export side", "Graph export in side", "Graph export side body."))
    stores = [
        {"id": SUB, "path": "mono", "subpath": "kb", "mesh_member": False},
        {"id": BARE, "mesh_member": False},
        {"id": SIDE, "path": "side"},
    ]
    write(project / "atlas-mesh.json", mesh_doc(stores, scope=scope))
    return project, sub, bare


def build_alias_into_included(tmp: Path) -> tuple[Path, Path]:
    """Included ``atlas/``; excluded ``alias -> atlas/secret``."""
    project = tmp / "proj"
    top = project / "atlas"
    secret = top / "secret"
    schema(top)
    write(top / "notes" / "top.md", page("Graph export top", "Graph export in top", "Graph export top body."))
    schema(secret)
    write(secret / "notes" / "hidden.md", page(f"Graph export {ALIAS_CANARY}", f"Graph export {ALIAS_CANARY}", f"{ALIAS_CANARY} body."))
    (project / "alias").symlink_to(Path("atlas") / "secret", target_is_directory=True)
    side = project / "side"
    schema(side)
    write(
        side / "notes" / "side.md",
        page(
            "Graph export side",
            "Graph export in side",
            "Graph export side body.",
            extra=(
                "relates_to:\n"
                f"  - path: atlas://{TOP}/notes/top.md\n    kind: related\n"
                f"  - path: atlas://{NESTED}/notes/hidden.md\n    kind: related\n"
            ),
        ),
    )
    stores = [
        {"id": TOP, "path": "atlas"},
        {"id": NESTED, "path": "alias", "mesh_member": False},
        {"id": SIDE, "path": "side"},
    ]
    write(project / "atlas-mesh.json", mesh_doc(stores, scope="mesh"))
    return project, secret


def build_included_alias_ancestor(tmp: Path) -> tuple[Path, Path]:
    """Included ``alias -> atlas``; excluded real store at ``atlas/secret``."""
    project = tmp / "proj"
    top = project / "atlas"
    secret = top / "secret"
    schema(top)
    write(top / "notes" / "top.md", page("Graph export top", "Graph export in top", "Graph export top body."))
    schema(secret)
    write(secret / "notes" / "hidden.md", page(f"Graph export {ALIAS_CANARY}", f"Graph export {ALIAS_CANARY}", f"{ALIAS_CANARY} body."))
    (project / "alias").symlink_to(Path("atlas"), target_is_directory=True)
    side = project / "side"
    schema(side)
    write(side / "notes" / "side.md", page("Graph export side", "Graph export in side", "Graph export side body."))
    stores = [
        {"id": TOP, "path": "alias"},
        {"id": NESTED, "path": "atlas/secret", "mesh_member": False},
        {"id": SIDE, "path": "side"},
    ]
    write(project / "atlas-mesh.json", mesh_doc(stores, scope="mesh"))
    return project, secret


def build_same_directory_aliases(tmp: Path) -> tuple[Path, Path]:
    """``left`` and ``right`` are aliases of one directory; ``side/`` is disjoint."""
    project = tmp / "proj"
    store = project / "store"
    schema(store)
    write(store / "notes" / "shared.md", page(f"Graph export {ALIAS_CANARY}", f"Graph export {ALIAS_CANARY}", f"{ALIAS_CANARY} body."))
    (project / "left").symlink_to(Path("store"), target_is_directory=True)
    (project / "right").symlink_to(Path("store"), target_is_directory=True)
    side = project / "side"
    schema(side)
    write(side / "notes" / "side.md", page("Graph export side", "Graph export in side", "Graph export side body."))
    stores = [
        {"id": LEFT, "path": "left"},
        {"id": RIGHT, "path": "right"},
        {"id": SIDE, "path": "side"},
    ]
    write(project / "atlas-mesh.json", mesh_doc(stores, scope="mesh"))
    return project, store


def build_skipped_real_alias(tmp: Path) -> tuple[Path, Path]:
    """Excluded ``alias -> atlas/templates/x``; the real relative path is walk-skipped."""
    project = tmp / "proj"
    top = project / "atlas"
    hidden = top / "templates" / "x"
    schema(top)
    write(top / "notes" / "top.md", page("Graph export top", "Graph export in top", "Graph export top body."))
    schema(hidden)
    write(hidden / "notes" / "hidden.md", page(f"Graph export {ALIAS_CANARY}", f"Graph export {ALIAS_CANARY}", f"{ALIAS_CANARY} body."))
    (project / "alias").symlink_to(Path("atlas") / "templates" / "x", target_is_directory=True)
    stores = [
        {"id": TOP, "path": "atlas"},
        {"id": NESTED, "path": "alias", "mesh_member": False},
    ]
    write(project / "atlas-mesh.json", mesh_doc(stores, scope="mesh"))
    return project, hidden


def build_lexical_skip_real_reached(tmp: Path) -> tuple[Path, Path]:
    """Lexical path starts in ``templates/``; the symlink target ``atlas/secret`` does not."""
    project = tmp / "proj"
    top = project / "atlas"
    secret = top / "secret"
    schema(top)
    write(top / "notes" / "top.md", page("Graph export top", "Graph export in top", "Graph export top body."))
    schema(secret)
    write(secret / "notes" / "hidden.md", page(f"Graph export {ALIAS_CANARY}", f"Graph export {ALIAS_CANARY}", f"{ALIAS_CANARY} body."))
    hop = top / "templates" / "hop"
    hop.parent.mkdir(parents=True, exist_ok=True)
    hop.symlink_to(Path("..") / "secret", target_is_directory=True)
    side = project / "side"
    schema(side)
    write(side / "notes" / "side.md", page("Graph export side", "Graph export in side", "Graph export side body."))
    stores = [
        {"id": TOP, "path": "atlas"},
        {"id": HOP, "path": "atlas/templates/hop", "mesh_member": False},
        {"id": SIDE, "path": "side"},
    ]
    write(project / "atlas-mesh.json", mesh_doc(stores, scope="mesh"))
    return project, secret


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr3-"))
    try:
        # --- Recommended: listed excluded subpath and pathless roots -----------------
        project, sub, bare = build_listed_excluded(tmp / "listed", scope="mesh")
        for label, root, canary, other in (
            ("subpath", sub, SUB_CANARY, BARE_CANARY),
            ("pathless", bare, BARE_CANARY, SUB_CANARY),
        ):
            index_location.clear_cache()
            discovered = ""
            with ContentGuard(root) as guard:
                try:
                    discovered = str(mesh_scope.discover(root).project)
                except (mesh_scope.MeshScopeError, PermissionError) as e:
                    discovered = f"error: {e}"
            check(f"{label}-discover-listed", discovered == str(project.resolve()), discovered)
            check(f"{label}-discover-unread", guard.hits == [], str(guard.hits[:5]))

            code, payload, touched, err = run_scoped(root, None, root, guard_cls=ContentGuard)
            text = json.dumps(payload)
            members = {m["atlas_id"]: m for m in payload.get("members") or []}
            uris = [h.get("uri", "") for h in payload.get("hits") or []]
            check(f"{label}-no-flag-exit-0", code == 0, f"{code} {err[:200]} {text[:300]}")
            check(
                f"{label}-no-flag-mesh-from-project",
                payload.get("scope") == "mesh" and payload.get("scope_source") == "project",
                str({k: payload.get(k) for k in ("scope", "scope_source", "error")}),
            )
            check(f"{label}-no-flag-unread", touched == [], str(touched[:5]))
            check(f"{label}-no-flag-excluded", members.get({"subpath": SUB, "pathless": BARE}[label], {}).get("status") == "excluded", str(members))
            check(f"{label}-no-flag-side-hit", uris == [f"atlas://{SIDE}/notes/side.md"], str(uris))
            check(f"{label}-no-flag-no-canary", canary not in text and other not in text and canary not in err, text[:400])

            code, payload, touched, err = run_scoped(root, "mesh", root, guard_cls=ContentGuard)
            text = json.dumps(payload)
            check(
                f"{label}-explicit-mesh",
                code == 0 and payload.get("scope") == "mesh" and payload.get("scope_source") == "cli" and touched == [],
                f"{code} {err[:200]} {text[:300]} {touched[:3]}",
            )
            check(f"{label}-explicit-mesh-no-canary", canary not in text and other not in text, text[:300])

            # Flag wins: store scope still reads the named store. Mesh exclusion does not apply.
            code, payload, _, err = run_scoped(root, "store", None)
            text = json.dumps(payload)
            check(
                f"{label}-store-scope-reads-named-store",
                code == 0 and payload.get("scope") != "mesh" and canary in text and other not in text and "members" not in payload,
                f"{code} {err[:200]} {text[:300]}",
            )

        # Default scope, no project key: still store recall of the named excluded root.
        project_default, sub_default, _bare_default = build_listed_excluded(tmp / "default-scope", scope=None)
        code, payload, _, err = run_scoped(sub_default, None, None)
        text = json.dumps(payload)
        check(
            "subpath-default-scope-is-store",
            code == 0 and payload.get("scope") != "mesh" and SUB_CANARY in text and "members" not in payload,
            f"{code} {err[:200]} {text[:300]}",
        )
        try:
            listed = mesh_scope.discover(sub_default).project == project_default.resolve()
            detail = ""
        except mesh_scope.MeshScopeError as e:
            listed, detail = False, str(e)
        check("subpath-default-still-listed", listed, detail)

        # --- Symlinked roots (alias is not resolved for overlap) ----------------
        # ``atlas/secret`` is a real directory of the included store, so a walk
        # of ``atlas/`` reads it. The forbidden access is following ``alias``.
        project, secret = build_alias_into_included(tmp / "alias-into")
        alias = project / "alias"
        with NoFollow(alias) as classify:
            statuses = statuses_of(project)
        check("alias-into-classify-nofollow", classify.hits == [], str(classify.hits[:3]))
        check(
            "alias-into-members",
            statuses == [(TOP, "ok", None), (NESTED, "invalid", "symlinked_root"), (SIDE, "ok", None)],
            str(statuses),
        )
        for engine in ("grep", "bm25"):
            held = NoFollow(alias)
            code, payload, touched, err = run_scoped(project, "mesh", None, engine=engine, guard=held)
            text = json.dumps(payload)
            members = {m["atlas_id"]: m for m in payload.get("members") or []}
            uris = [h.get("uri", "") for h in payload.get("hits") or []]
            check(f"alias-into-{engine}-exit-0", code == 0, f"{code} {err[:200]} {text[:300]}")
            check(f"alias-into-{engine}-nofollow", touched == [], str(touched[:5]))
            nested = members.get(NESTED, {})
            check(
                f"alias-into-{engine}-symlinked-root",
                nested.get("status") == "invalid" and nested.get("reason") == "symlinked_root" and nested.get("hits") == 0,
                str(nested),
            )
            check(f"alias-into-{engine}-top-ok", members.get(TOP, {}).get("status") == "ok", str(members.get(TOP)))
            check(f"alias-into-{engine}-no-nested-uri", not any(NESTED in u for u in uris), str(uris))
            check(f"alias-into-{engine}-side-hit", any(u.startswith(f"atlas://{SIDE}/") for u in uris), str(uris))
        index_location.clear_cache()
        with NoFollow(alias) as guard:
            try:
                view = mesh_scope.build_view(mesh_scope.discover(project))
                error = ""
            except Exception as e:  # noqa: BLE001
                view, error = {}, repr(e)
        index_location.clear_cache()
        node_ids = [n["id"] for n in view.get("nodes", [])]
        edges = [e for e in view.get("edges", []) if e.get("from") == f"atlas://{SIDE}/notes/side.md"]
        check("alias-into-view-nofollow", guard.hits == [] and not error, f"{guard.hits[:3]} {error}")
        check("alias-into-view-no-nested-node", not any(i.startswith(f"atlas://{NESTED}/") for i in node_ids), str(node_ids))
        into_top = next((e for e in edges if TOP in e.get("to", "")), {})
        into_nested = next((e for e in edges if NESTED in e.get("to", "")), {})
        check("alias-into-link-top-resolves", into_top.get("resolved") is True, str(into_top))
        check("alias-into-link-symlinked-outside-mesh", into_nested.get("reason") == "outside_mesh" and not into_nested.get("resolved"), str(into_nested))

        project, secret = build_included_alias_ancestor(tmp / "alias-ancestor")
        statuses = statuses_of(project)
        check(
            "alias-ancestor-members",
            statuses == [(TOP, "invalid", "symlinked_root"), (NESTED, "excluded", None), (SIDE, "ok", None)],
            str(statuses),
        )
        code, payload, touched, err = run_scoped(project, "mesh", secret)
        text = json.dumps(payload)
        uris = [h.get("uri", "") for h in payload.get("hits") or []]
        check("alias-ancestor-exit-0", code == 0, f"{code} {err[:200]} {text[:300]}")
        check("alias-ancestor-unread", touched == [], str(touched[:5]))
        check("alias-ancestor-side-only", uris == [f"atlas://{SIDE}/notes/side.md"], str(uris))
        check("alias-ancestor-no-canary", ALIAS_CANARY not in text and ALIAS_CANARY not in err, text[:400])
        check("alias-ancestor-no-top-page", not any(TOP in u for u in uris), str(uris))

        project, store = build_same_directory_aliases(tmp / "same-dir")
        statuses = statuses_of(project)
        check(
            "same-dir-members",
            statuses == [(LEFT, "invalid", "symlinked_root"), (RIGHT, "invalid", "symlinked_root"), (SIDE, "ok", None)],
            str(statuses),
        )
        code, payload, touched, err = run_scoped(project, "mesh", store)
        text = json.dumps(payload)
        uris = [h.get("uri", "") for h in payload.get("hits") or []]
        check("same-dir-exit-0", code == 0, f"{code} {err[:200]} {text[:300]}")
        check("same-dir-unread", touched == [], str(touched[:5]))
        check("same-dir-side-only", uris == [f"atlas://{SIDE}/notes/side.md"], str(uris))
        check("same-dir-no-canary", ALIAS_CANARY not in text and ALIAS_CANARY not in err, text[:400])

        project, hidden = build_skipped_real_alias(tmp / "skipped-real")
        statuses = statuses_of(project)
        check(
            "skipped-real-members",
            statuses == [(TOP, "ok", None), (NESTED, "invalid", "symlinked_root")],
            str(statuses),
        )
        code, payload, touched, err = run_scoped(project, "mesh", hidden)
        text = json.dumps(payload)
        uris = [h.get("uri", "") for h in payload.get("hits") or []]
        check("skipped-real-exit-0", code == 0, f"{code} {err[:200]} {text[:300]}")
        check("skipped-real-unread", touched == [], str(touched[:5]))
        check("skipped-real-top-only", uris == [f"atlas://{TOP}/notes/top.md"], str(uris))
        check("skipped-real-no-canary", ALIAS_CANARY not in text and ALIAS_CANARY not in err, text[:400])

        # Classification must not follow ``hop`` into ``secret``. Search of the
        # included store reads ``atlas/secret`` because it is a real directory
        # of that store, not because the symlink is followed.
        project, secret = build_lexical_skip_real_reached(tmp / "lexical-skip")
        with Guard(secret) as classify:
            statuses = statuses_of(project)
        check("lexical-skip-classify-unread", classify.hits == [], str(classify.hits[:3]))
        check(
            "lexical-skip-real-reached-members",
            statuses == [(TOP, "ok", None), (HOP, "invalid", "symlinked_root"), (SIDE, "ok", None)],
            str(statuses),
        )
        held = NoFollow(project / "atlas" / "templates" / "hop")
        code, payload, touched, err = run_scoped(project, "mesh", None, guard=held)
        text = json.dumps(payload)
        members = {m["atlas_id"]: m for m in payload.get("members") or []}
        uris = [h.get("uri", "") for h in payload.get("hits") or []]
        hop = members.get(HOP, {})
        check("lexical-skip-real-reached-exit-0", code == 0, f"{code} {err[:200]} {text[:300]}")
        check("lexical-skip-real-reached-nofollow", touched == [], str(touched[:5]))
        check(
            "lexical-skip-real-reached-symlinked",
            hop.get("status") == "invalid" and hop.get("reason") == "symlinked_root" and hop.get("hits") == 0,
            str(hop),
        )
        check("lexical-skip-real-reached-no-hop-uri", not any(HOP in u for u in uris), str(uris))
        check("lexical-skip-real-reached-side-hit", any(u.startswith(f"atlas://{SIDE}/") for u in uris), str(uris))
    finally:
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"FAILED: {len(failed)} check(s): {', '.join(failed)}")
        return 1
    print("OK: mesh review MC CR3 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
