#!/usr/bin/env python3
"""Mesh members (M2, M6, M7, M20): statuses, excluded rows unread, restricted
pages withheld, structure-only records, deterministic in-memory view.

Linux-safe: no network, no git.
"""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, mesh_scope  # noqa: E402

CANARY = "QUOKKAMARMALADE"
ALPHA = "github.com/acme/alpha"
BETA = "github.com/acme/beta"
SECRET = "github.com/acme/secret"
GONE = "github.com/acme/gone"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def contract(root: Path, title: str = "Fixture") -> None:
    write(root / "CONTRACT.json", json.dumps({"schema_version": "1.0", "atlas_id": "fixture", "title": title}) + "\n")


def public_page(name: str, rels: list[str] | None = None) -> str:
    lines = [
        "---",
        "type: lesson",
        f"title: {name} {CANARY} title",
        f"description: {CANARY} description",
        f"tags: [{CANARY.lower()}, {CANARY}]",
        "status: active",
        "kva: K",
        "growth: true",
        "origin: authored",
        f"summary: {CANARY} summary",
        "created: 2026-10-10",
    ]
    if rels:
        lines.append("relates_to:")
        lines += [f"  - path: {json.dumps(r)}\n    kind: related\n    note: {CANARY} note" for r in rels]
    lines += ["---", "", f"# {name} {CANARY} heading", "", f"Body {CANARY} text.", ""]
    return "\n".join(lines)


def restricted_page() -> str:
    # The canary sits in every field, including the path-free ones a leak would expose.
    return "\n".join(
        [
            "---",
            "type: lesson",
            f"title: {CANARY} restricted title",
            f"description: {CANARY} restricted description",
            f"tags: [{CANARY}]",
            f"status: {CANARY}",
            f"origin: {CANARY}",
            f"work_id: {CANARY}",
            "sensitivity: Restricted",
            "relates_to:",
            f"  - path: notes/{CANARY}.md",
            "    kind: related",
            "---",
            "",
            f"{CANARY} restricted body.",
            "",
        ]
    )


def build_fixture(tmp: Path) -> tuple[Path, Path]:
    project = tmp / "proj"
    alpha = project / "atlas" / "alpha"
    contract(alpha, f"{CANARY} alpha")
    write(alpha / "notes" / "a.md", public_page("Alpha", [f"atlas://{BETA}/notes/b.md", "notes/hidden.md"]))
    write(alpha / "notes" / "hidden.md", restricted_page())
    beta = project / "atlas" / "beta"
    write(beta / "SCHEMA.json", json.dumps({"schema_version": "1.0", "title": f"{CANARY} beta"}) + "\n")
    write(beta / "notes" / "b.md", public_page("Beta", [f"atlas://{SECRET}/notes/s.md"]))
    secret = project / "atlas" / "secret"
    contract(secret, CANARY)
    write(secret / "notes" / f"{CANARY}.md", restricted_page().replace("sensitivity: Restricted", "sensitivity: public"))
    write(project / "atlas" / "empty" / "README.md", "not a store\n")
    doc = {
        "version": 1,
        "stores": [
            {"id": ALPHA, "path": "atlas/alpha", "mesh_member": True},
            {"id": BETA, "path": "atlas/beta"},
            {"id": SECRET, "path": "atlas/secret", "mesh_member": False},
            {"id": GONE, "path": "atlas/gone"},
            {"id": "github.com/acme/empty", "path": "atlas/empty"},
        ],
    }
    write(project / "atlas-mesh.json", json.dumps(doc, indent=2) + "\n")
    return project, secret


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        h.update(str(path.relative_to(root)).encode())
        if path.is_file() and not path.is_symlink():
            h.update(path.read_bytes())
    return h.hexdigest()


class Guard:
    """Fail any filesystem call strictly inside ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = os.path.realpath(root)
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
        return absolute.startswith(self.root + os.sep)

    def _wrap(self, owner: object, name: str) -> None:
        original = getattr(owner, name)
        guard = self

        def wrapped(*args, **kwargs):
            if args and guard._inside(args[0]):
                guard.hits.append(f"{name}({args[0]})")
                raise PermissionError(f"excluded member touched: {name} {args[0]}")
            return original(*args, **kwargs)

        self.saved.append((owner, name, original))
        setattr(owner, name, wrapped)

    def __enter__(self) -> Guard:
        for name in ("stat", "lstat", "open", "listdir", "scandir", "readlink", "access", "walk"):
            self._wrap(os, name)
        self._wrap(builtins, "open")
        self._wrap(io, "open")
        return self

    def __exit__(self, *exc: object) -> None:
        for owner, name, original in reversed(self.saved):
            setattr(owner, name, original)


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-members-"))
    try:
        index_location.clear_cache()
        project, secret = build_fixture(tmp)
        mesh = mesh_scope.discover(project)
        check("discover-project", mesh.project == project.resolve())
        check("discover-from-store", mesh_scope.discover(project / "atlas" / "beta").project == project.resolve())

        statuses = [(m.atlas_id, m.status) for m in mesh_scope.members(mesh)]
        check(
            "member-statuses-in-file-order",
            statuses
            == [
                (ALPHA, "ok"),
                (BETA, "ok"),
                (SECRET, "excluded"),
                (GONE, "unmounted"),
                ("github.com/acme/empty", "unmounted"),
            ],
            str(statuses),
        )

        # Excluded member: nothing inside its root is stat'ed, opened or listed.
        before = tree_digest(tmp)
        index_location.clear_cache()
        with Guard(secret) as guard:
            try:
                view = mesh_scope.build_view(mesh_scope.discover(project))
                error = ""
            except Exception as e:  # noqa: BLE001
                view, error = {}, repr(e)
        check("excluded-member-unread", not guard.hits and not error, f"{guard.hits} {error}")

        # The guard really bites: reading the excluded store under it must fail.
        with Guard(secret) as probe:
            try:
                (secret / "CONTRACT.json").read_text()
            except PermissionError:
                pass
        check("guard-is-effective", bool(probe.hits))

        check("no-writes", tree_digest(tmp) == before)
        check("no-mesh-index-written", not (project / ".atlas").exists())

        node_ids = [n["id"] for n in view.get("nodes", [])]
        check(
            "restricted-pages-absent",
            node_ids == [f"atlas://{ALPHA}/notes/a.md", f"atlas://{BETA}/notes/b.md"],
            str(node_ids),
        )
        node = view["nodes"][0] if view.get("nodes") else {}
        check(
            "structure-only-node",
            set(node) == {"id", "atlas_id", "path", "type", "status", "kva", "growth", "origin"}
            and node.get("growth") is True
            and node.get("kva") == "K",
            json.dumps(node),
        )
        edges = {(e["from"], e["to"]): e for e in view.get("edges", [])}
        hidden = edges.get((f"atlas://{ALPHA}/notes/a.md", f"atlas://{ALPHA}/notes/hidden.md"))
        check("restricted-target-withheld", bool(hidden) and hidden.get("reason") == "withheld", str(hidden))
        excluded = [e for e in view.get("edges", []) if e.get("reason") == "excluded_member"]
        check("excluded-target-reason", len(excluded) == 1, str(excluded))
        check("edge-count", len(view.get("edges", [])) == 3, str(len(view.get("edges", []))))

        dumped = json.dumps(view, sort_keys=True)
        check("canary-absent", CANARY.lower() not in dumped.lower(), dumped[:300])
        leaks = [k for k in ("title", "description", "body", "tags", "summary", "note") if f'"{k}"' in dumped]
        check("no-text-fields", not leaks, str(leaks))

        index_location.clear_cache()
        again = json.dumps(mesh_scope.build_view(mesh_scope.discover(project)), sort_keys=False)
        check("deterministic", again == json.dumps(view, sort_keys=False))

        # Discovery failures.
        lone = tmp / "lone"
        contract(lone)
        try:
            mesh_scope.discover(lone)
            message = ""
        except mesh_scope.MeshScopeError as e:
            message = str(e)
        check("standalone-store-rejected", "no atlas-mesh.json lists this store" in message, message)
        try:
            mesh_scope.load_member(mesh_scope.members(mesh)[2])
            refused = False
        except mesh_scope.MeshScopeError:
            refused = True
        check("load-excluded-refused", refused)

        # Restricted detection: case-insensitive and trimmed only.
        cases = {"restricted": True, " Restricted ": True, "RESTRICTED": True, "internal": False, None: False, "": False}
        check(
            "is-restricted",
            all(mesh_scope.is_restricted({"sensitivity": k}) is v for k, v in cases.items()),
        )

        # node ids
        uri = mesh_scope.node_id(ALPHA, "notes/a.md")
        check("node-id-round-trip", mesh_scope.parse_node_id(uri) == (ALPHA, "notes/a.md"))
        check("repo-name", mesh_scope.repo_name(ALPHA) == "alpha")

        # Malformed mesh_member must not be read as a member.
        bad = tmp / "bad"
        contract(bad / "s")
        write(bad / "atlas-mesh.json", json.dumps({"version": 1, "stores": [{"id": ALPHA, "path": "s", "mesh_member": "no"}]}) + "\n")
        try:
            mesh_scope.discover(bad)
            message = ""
        except mesh_scope.MeshScopeError as e:
            message = str(e)
        check("malformed-mesh-member-rejected", "mesh_member" in message, message)
    finally:
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} mesh member check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll mesh member checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
