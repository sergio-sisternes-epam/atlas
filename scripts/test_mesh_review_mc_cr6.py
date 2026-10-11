#!/usr/bin/env python3
"""Copilot review CR6: invalid-id rows cannot bypass mesh scope.

A direct ``--root`` at an invalid-id (host-port or IPv6) subpath or pathless
row must find the mesh. With ``recall.scope: mesh`` and no flag, recall stays
mesh scope, reports the row ``invalid`` / ``invalid_atlas_id``, returns only
other members' hits, and never reads under that root. Explicit ``--scope
mesh`` finds the same mesh. A path-based invalid-id row is covered for
completeness.

These checks fail on 185f35d, which filtered non-member ids out of fallback
discovery. Linux-safe: no network, no git.
"""

from __future__ import annotations

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


SIDE = "github.com/acme/side"
PORT_SUB = "git.example.com:8443/acme/subport"
IPV6_SUB = "[::1]/acme/subv6"
PORT_BARE = "git.example.com:8443/acme/bareport"
IPV6_BARE = "[::1]/acme/barev6"
PORT_PATH = "git.example.com:8443/acme/pathport"
QUERY = "graph export"
INVALID = ("invalid", "invalid_atlas_id")
CASES = (
    ("subpath-host-port", PORT_SUB, "PORTSUBWOMBATQX"),
    ("subpath-ipv6", IPV6_SUB, "IPV6SUBWOMBATQX"),
    ("pathless-host-port", PORT_BARE, "PORTBAREWOMBATQX"),
    ("pathless-ipv6", IPV6_BARE, "IPV6BAREWOMBATQX"),
    ("path-host-port", PORT_PATH, "PORTPATHWOMBATQX"),
)


def mesh_doc(stores: list[dict]) -> str:
    doc = {"version": 1, "recall": {"scope": "mesh"}, "stores": stores}
    return json.dumps(doc, indent=2) + "\n"


def pathless_root(project: Path, atlas_id: str) -> Path:
    """Same mount a pathless row gets: ``.atlas/<id>``."""
    return project.joinpath(".atlas", *atlas_id.split("/"))


def run_scoped(root: Path, scope: str | None) -> tuple[int, dict, list[str], str]:
    index_location.clear_cache()
    buf, ebuf = io.StringIO(), io.StringIO()
    guard = ContentGuard(root)
    code = 99
    try:
        with guard, contextlib.redirect_stdout(buf), contextlib.redirect_stderr(ebuf):
            code = search_cmd.run_scoped(str(root), QUERY, 10, True, "grep", False, None, False, scope, None)
    except Exception as e:  # noqa: BLE001 - old code leaks and the guard raises
        index_location.clear_cache()
        return 99, {"_error": repr(e)}, guard.hits, ebuf.getvalue()
    index_location.clear_cache()
    try:
        payload = json.loads(buf.getvalue())
    except ValueError:
        payload = {"_raw": buf.getvalue()}
    return code, payload, guard.hits, ebuf.getvalue()


def build(tmp: Path) -> tuple[Path, dict[str, Path]]:
    project = tmp / "proj"
    roots = {
        PORT_SUB: project / "mono" / "portsub",
        IPV6_SUB: project / "mono" / "ipv6sub",
        PORT_BARE: pathless_root(project, PORT_BARE),
        IPV6_BARE: pathless_root(project, IPV6_BARE),
        PORT_PATH: project / "atlas" / "port",
        SIDE: project / "side",
    }
    for _label, sid, canary in CASES:
        schema(roots[sid])
        write(
            roots[sid] / "notes" / "bait.md",
            page(f"Graph export {canary}", f"Graph export {canary}", f"{canary} graph export body."),
        )
    schema(roots[SIDE])
    write(roots[SIDE] / "notes" / "side.md", page("Graph export side", "Graph export in side", "Graph export side body."))
    stores = [
        {"id": PORT_SUB, "path": "mono", "subpath": "portsub"},
        {"id": IPV6_SUB, "path": "mono", "subpath": "ipv6sub"},
        {"id": PORT_BARE},
        {"id": IPV6_BARE},
        {"id": PORT_PATH, "path": "atlas/port"},
        {"id": SIDE, "path": "side"},
    ]
    write(project / "atlas-mesh.json", mesh_doc(stores))
    return project, roots


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    saved_env = {key: os.environ.pop(key, None) for key in ("ATLAS_INDEX_ROOT", "ATLAS_RECALL_ENGINE")}
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr6-"))
    try:
        project, roots = build(tmp)
        side_uri = f"atlas://{SIDE}/notes/side.md"
        for label, sid, canary in CASES:
            root = roots[sid]
            index_location.clear_cache()
            discovered = ""
            with ContentGuard(root) as guard:
                try:
                    discovered = str(mesh_scope.discover(root).project)
                except (mesh_scope.MeshScopeError, PermissionError) as e:
                    discovered = f"error: {e}"
            check(f"{label}-discover-listed", discovered == str(project.resolve()), discovered)
            check(f"{label}-discover-unread", guard.hits == [], str(guard.hits[:5]))

            code, payload, touched, err = run_scoped(root, None)
            text = json.dumps(payload)
            members = {m.get("atlas_id"): m for m in payload.get("members") or []}
            uris = [h.get("uri", "") for h in payload.get("hits") or []]
            row = members.get(sid, {})
            check(f"{label}-no-flag-exit-0", code == 0, f"{code} {err[:200]} {text[:300]}")
            check(
                f"{label}-no-flag-mesh-from-project",
                payload.get("scope") == "mesh" and payload.get("scope_source") == "project",
                str({k: payload.get(k) for k in ("scope", "scope_source", "error", "_error")}),
            )
            check(
                f"{label}-no-flag-invalid",
                (row.get("status"), row.get("reason")) == INVALID and row.get("hits") == 0,
                str(row),
            )
            check(f"{label}-no-flag-other-hits-only", uris == [side_uri], str(uris))
            check(f"{label}-no-flag-unread", touched == [], str(touched[:5]))
            check(f"{label}-no-flag-no-canary", canary not in text and canary not in err, text[:400])

            code, payload, touched, err = run_scoped(root, "mesh")
            text = json.dumps(payload)
            members = {m.get("atlas_id"): m for m in payload.get("members") or []}
            uris = [h.get("uri", "") for h in payload.get("hits") or []]
            row = members.get(sid, {})
            check(
                f"{label}-explicit-mesh",
                code == 0
                and payload.get("scope") == "mesh"
                and payload.get("scope_source") == "cli"
                and (row.get("status"), row.get("reason")) == INVALID
                and uris == [side_uri]
                and touched == [],
                f"{code} {err[:200]} {text[:300]} {touched[:3]}",
            )
            check(f"{label}-explicit-mesh-no-canary", canary not in text and canary not in err, text[:300])
    finally:
        index_location.clear_cache()
        for key, value in saved_env.items():
            if value is not None:
                os.environ[key] = value
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"FAILED: {len(failed)} check(s): {', '.join(failed)}")
        return 1
    print("OK: mesh review MC CR6 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
