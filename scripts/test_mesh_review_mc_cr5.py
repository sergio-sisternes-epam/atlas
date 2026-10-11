#!/usr/bin/env python3
"""Review CR5: mesh member ids must be index-path safe.

Host-with-port and IPv6 ids pass ``atlas-mesh.json`` validation, but
``index_location.safe_id_path`` rejects ``:`` and ``[``. Those rows are
``invalid`` with reason ``invalid_atlas_id`` under ``members()``, federated
recall (grep and bm25) and ``build_view``, and are never read. A normal host
member still uses its configured bm25 engine and its own per-store index
directory, not an ephemeral index.

Linux-safe: no network, no git.
"""

from __future__ import annotations

import builtins
import io
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

from atlas_cli.core import engine_preference, index_location, mesh_recall, mesh_scope, meshfile, recall_index  # noqa: E402
from test_mesh_recall import page, schema, write  # noqa: E402

HOST = "github.com/acme/host"
PORT = "git.example.com:8443/acme/repo"
IPV6 = "[::1]/acme/repo"
IPV6_PORT = "[fe80::1]:8080/acme/repo"
UNSAFE = (
    ("host-port", PORT, "PORTMEMBERWOMBAT"),
    ("ipv6", IPV6, "IPV6MEMBERWOMBAT"),
    ("ipv6-port", IPV6_PORT, "IPV6PORTMEMBERWOMBAT"),
)
QUERY = "quollmesh"
INVALID = ("invalid", "invalid_atlas_id")


def path_safe(atlas_id: str) -> bool:
    try:
        index_location.safe_id_path(atlas_id)
    except index_location.IndexLocationError:
        return False
    return True


def validation_accepts(atlas_id: str) -> bool:
    return not meshfile.validate_doc({"version": 1, "stores": [{"id": atlas_id, "path": "atlas/s"}]})


class RootsGuard:
    """Fail any filesystem call inside the given roots (the same probes as ``Guard``)."""

    NAMES = ("stat", "lstat", "open", "listdir", "scandir", "readlink", "access", "walk")
    SUBPROC = ("run", "Popen", "check_output", "check_call", "call")

    def __init__(self, roots: list[Path]) -> None:
        self.roots = [os.path.realpath(root) for root in roots]
        self.hits: list[str] = []
        self.saved: list[tuple[object, str, object]] = []

    def _inside(self, path: object) -> bool:
        if isinstance(path, int):
            return False
        try:
            text = os.fsdecode(os.fspath(path))
        except TypeError:
            return False
        absolute = os.path.normpath(os.path.join(os.getcwd(), text))
        return any(absolute == root or absolute.startswith(root + os.sep) for root in self.roots)

    def _touch(self, args: tuple, kwargs: dict) -> str | None:
        parts: list[object] = []
        if args:
            cmd = args[0]
            parts.extend(cmd if isinstance(cmd, (list, tuple)) else [cmd])
        if kwargs.get("cwd") is not None:
            parts.append(kwargs["cwd"])
        for part in parts:
            if self._inside(part):
                return os.fsdecode(os.fspath(part))
        return None

    def _wrap(self, owner: object, name: str, make: Callable[[Any], Any]) -> None:
        original = getattr(owner, name)
        self.saved.append((owner, name, original))
        setattr(owner, name, make(original))

    def __enter__(self) -> RootsGuard:
        guard = self

        def fs(original: Any) -> Any:
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                if args and guard._inside(args[0]):
                    guard.hits.append(f"{original.__name__}({args[0]})")
                    raise PermissionError(f"invalid member touched: {original.__name__} {args[0]}")
                return original(*args, **kwargs)

            return wrapped

        def subproc(original: Any) -> Any:
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                touched = guard._touch(args, kwargs)
                if touched is not None:
                    guard.hits.append(f"subprocess({touched})")
                    raise PermissionError(f"invalid member touched: subprocess {touched}")
                return original(*args, **kwargs)

            return wrapped

        for name in self.NAMES:
            self._wrap(os, name, fs)
        self._wrap(builtins, "open", fs)
        self._wrap(io, "open", fs)
        for name in self.SUBPROC:
            self._wrap(subprocess, name, subproc)
        return self

    def __exit__(self, *exc: object) -> None:
        for owner, name, original in reversed(self.saved):
            setattr(owner, name, original)


def build(tmp: Path) -> tuple[Path, dict[str, Path]]:
    project = tmp / "proj"
    roots = {
        HOST: project / "atlas" / "host",
        PORT: project / "atlas" / "port",
        IPV6: project / "atlas" / "ipv6",
        IPV6_PORT: project / "atlas" / "ipv6port",
    }
    schema(roots[HOST])
    write(roots[HOST] / "notes" / "n.md", page("Quollmesh export", "Quollmesh note", "The quollmesh token lives here."))
    for _label, sid, canary in UNSAFE:
        schema(roots[sid])
        write(
            roots[sid] / "notes" / "bait.md",
            page(f"Quollmesh {canary}", f"{canary} quollmesh", f"quollmesh {canary} body"),
        )
    stores = [{"id": sid, "path": f"atlas/{roots[sid].name}", "recall": {"engine": "bm25"}} for sid in roots]
    write(project / "atlas-mesh.json", json.dumps({"version": 1, "stores": stores}, indent=2) + "\n")
    return project, roots


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    for _label, sid, _canary in UNSAFE:
        check(f"validation-still-accepts {_label}", validation_accepts(sid), sid)
        check(
            f"predicate-rejects {_label}",
            path_safe(sid) is False and mesh_scope.is_member_id(sid) is False,
            f"safe={path_safe(sid)} member={mesh_scope.is_member_id(sid)}",
        )
    check("predicate-accepts-host", path_safe(HOST) and mesh_scope.is_member_id(HOST))

    saved_env = {key: os.environ.pop(key, None) for key in ("ATLAS_INDEX_ROOT", "ATLAS_RECALL_ENGINE")}
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr5-"))
    try:
        project, roots = build(tmp)
        unsafe_roots = [roots[sid] for _label, sid, _canary in UNSAFE]
        index_location.clear_cache()
        mesh = mesh_scope.discover(project)

        def under(fn: Callable[[], Any]) -> tuple[Any, list[str], str]:
            with RootsGuard(unsafe_roots) as guard:
                try:
                    return fn(), guard.hits, ""
                except Exception as e:  # noqa: BLE001
                    return None, guard.hits, repr(e)

        got, hits, error = under(lambda: mesh_scope.members(mesh))
        status = {m.atlas_id: (m.status, m.reason) for m in got or []}
        check("members-host-ok", status.get(HOST) == ("ok", None) and not error, f"{status.get(HOST)} {error}")
        for label, sid, _canary in UNSAFE:
            check(f"members-invalid {label}", status.get(sid) == INVALID and not hits and not error, f"{status.get(sid)} {hits[:2]} {error}")

        view, hits, error = under(lambda: mesh_scope.build_view(mesh))
        view_status = {m["atlas_id"]: (m["status"], m.get("reason")) for m in (view or {}).get("members", [])}
        check("view-host-ok", view_status.get(HOST) == ("ok", None) and not hits and not error, f"{view_status.get(HOST)} {error}")
        for label, sid, canary in UNSAFE:
            check(f"view-invalid {label}", view_status.get(sid) == INVALID and not hits and not error, f"{view_status.get(sid)} {hits[:2]} {error}")
            check(f"view-no-nodes {label}", all(n.get("atlas_id") != sid for n in (view or {}).get("nodes", [])))
            check(f"view-no-canary {label}", canary not in json.dumps(view or {}))

        settings = mesh_recall.resolve_settings(project, "mesh")
        ephemeral: list[str] = []
        original_ephemeral = recall_index.build_ephemeral

        def spy_ephemeral(projection: dict[str, Any]) -> Path:
            ephemeral.append("build_ephemeral")
            return original_ephemeral(projection)

        def federated(engine: str | None) -> tuple[dict[str, Any] | None, list[str], str]:
            def run() -> tuple[dict[str, Any], int]:
                return mesh_recall.federate(settings, QUERY, engine_override=engine)

            payload, guard_hits, err = under(run)
            if err or not isinstance(payload, tuple):
                return None, guard_hits, err or repr(payload)
            body, code = payload
            if code != 0:
                return body, guard_hits, f"exit {code}"
            return body, guard_hits, ""

        for engine in ("grep", "bm25"):
            payload, guard_hits, err = federated(engine)
            members = {m["atlas_id"]: m for m in (payload or {}).get("members", [])}
            text = json.dumps(payload or {})
            for label, sid, canary in UNSAFE:
                row = members.get(sid, {})
                check(
                    f"recall-{engine}-invalid {label}",
                    (row.get("status"), row.get("reason")) == INVALID and row.get("hits") == 0 and not guard_hits and not err,
                    f"{row} {guard_hits[:2]} {err}",
                )
                check(f"recall-{engine}-no-canary {label}", canary not in text and sid not in [h.get("atlas_id") for h in (payload or {}).get("hits", [])])

        recall_index.build_ephemeral = spy_ephemeral
        try:
            payload, guard_hits, err = federated(None)
        finally:
            recall_index.build_ephemeral = original_ephemeral
        members = {m["atlas_id"]: m for m in (payload or {}).get("members", [])}
        host = members.get(HOST, {})
        check(
            "configured-bm25-engine",
            host.get("status") == "ok"
            and host.get("engine_requested") == "bm25"
            and host.get("engine_used") == "sqlite-fts5"
            and host.get("hits", 0) >= 1
            and not guard_hits
            and not err,
            f"{host} {guard_hits[:2]} {err}",
        )
        for label, sid, _canary in UNSAFE:
            row = members.get(sid, {})
            check(
                "recall-configured-invalid " + label,
                (row.get("status"), row.get("reason")) == INVALID and row.get("hits") == 0,
                str(row),
            )
        index_location.clear_cache()
        host_root = roots[HOST]
        try:
            where = index_location.index_dir(host_root, "fts5")
            rel = index_location.project_relative(host_root, where)
            loc = index_location.resolve(host_root)
            detail = f"{rel} {loc}"
        except index_location.IndexLocationError as e:
            where, rel, loc, detail = None, "", None, repr(e)
        own = project.resolve() / ".atlas" / "indexes" / "fts5" / "github.com" / "acme" / "host"
        check(
            "host-own-index-dir",
            where == own and rel == ".atlas/indexes/fts5/github.com/acme/host" and loc is not None and loc.atlas_id == HOST and loc.mode == "mesh",
            detail,
        )
        check(
            "host-index-not-ephemeral",
            where is not None
            and where.is_relative_to(project.resolve() / ".atlas" / "indexes")
            and (where / recall_index.CURRENT_NAME).is_file()
            and ephemeral == []
            and "atlas-recall-eph" not in str(where),
            f"{where} ephemeral={ephemeral}",
        )
        with mesh_recall._pinned(next(m for m in mesh_scope.members(mesh) if m.atlas_id == HOST), mesh):
            pref = engine_preference.resolve_engine(host_root)
        check("configured-bm25-source", (pref.requested, pref.source, pref.store_id) == ("bm25", "store", HOST), str(pref))
    finally:
        index_location.clear_cache()
        for key, value in saved_env.items():
            if value is not None:
                os.environ[key] = value
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} mesh CR5 check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll mesh CR5 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
