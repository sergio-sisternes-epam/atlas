#!/usr/bin/env python3
"""Copilot review CR8: a symlinked path: filter fails closed.

A member with ``notes/alias -> notes/real`` and unrelated pages elsewhere must
not be searched without that constraint. Mesh recall of ``path:notes/alias``
under grep, bm25 and nanograph (or its fallback) returns no hits from that
member, emits the existing warning, and does not read through the link.
Another member with a real ``notes/alias`` still contributes its hit.

These checks fail on 1a4efb4, which dropped the constraint and searched the
whole member. Linux-safe: no network, no git.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.commands import search as search_cmd  # noqa: E402
from atlas_cli.core import index_location  # noqa: E402
from test_mesh_review_mc_cr4 import mesh_doc  # noqa: E402
from test_mesh_recall import page, schema, write  # noqa: E402

LINKED = "github.com/acme/linked"
PEER = "github.com/acme/peer"
WORD = "wombatqx"
UNRELATED = "UNRELATEDWOMBATQX"
CANARY = "LINKREALCANARY"
PEER_MARK = "PEERKEPTWOMBATQX"
WARN = "warning: mesh scope skipped symlink"
ENGINES = ("grep", "bm25", "nanograph")


class LinkGuard:
    """Fail a following read of ``link`` or anything lexically under it.

    ``lstat`` (``follow_symlinks=False``) is allowed: classifying the link is
    not a read of its target. A direct read of the target's real path is not
    a read through the link.
    """

    def __init__(self, link: Path) -> None:
        self.link = os.path.normpath(os.path.abspath(os.fspath(link)))
        self.hits: list[str] = []
        self.saved: list[tuple[object, str, object]] = []

    def _through(self, path: object) -> bool:
        if isinstance(path, int):
            return False
        try:
            text = os.fsdecode(os.fspath(path))
        except (TypeError, ValueError):
            return False
        absolute = os.path.normpath(os.path.join(os.getcwd(), text))
        return absolute == self.link or absolute.startswith(self.link + os.sep)

    def _note(self, name: str, path: object) -> None:
        self.hits.append(f"{name}({path})")
        raise PermissionError(f"read through symlink: {name} {path}")

    def _wrap(self, owner: object, name: str) -> None:
        original = getattr(owner, name)
        guard = self

        def wrapped(*args, **kwargs):
            if kwargs.get("follow_symlinks") is False:
                return original(*args, **kwargs)
            if args and guard._through(args[0]):
                guard._note(name, args[0])
            return original(*args, **kwargs)

        self.saved.append((owner, name, original))
        setattr(owner, name, wrapped)

    def _wrap_run(self) -> None:
        original = subprocess.run
        guard = self

        def wrapped(*args, **kwargs):
            argv = args[0] if args else kwargs.get("args")
            if isinstance(argv, (list, tuple)) and argv and Path(str(argv[0])).name == "rg":
                if "--follow" in argv or "-L" in argv:
                    guard._note("rg", "--follow")
                for arg in argv:
                    if guard._through(arg):
                        guard._note("rg", arg)
            return original(*args, **kwargs)

        self.saved.append((subprocess, "run", original))
        subprocess.run = wrapped  # type: ignore[assignment]

    def __enter__(self) -> LinkGuard:
        for name in ("stat", "open", "listdir", "scandir", "access", "walk"):
            self._wrap(os, name)
        self._wrap(os.path, "realpath")
        self._wrap_run()
        return self

    def __exit__(self, *exc: object) -> None:
        for owner, name, original in reversed(self.saved):
            setattr(owner, name, original)
        self.saved.clear()


def build(tmp: Path) -> tuple[Path, Path]:
    project = tmp / "proj"
    linked = project / "linked"
    peer = project / "peer"
    schema(linked)
    schema(peer)
    write(
        linked / "notes" / "elsewhere.md",
        page("Unrelated page", "stray", f"{WORD} {UNRELATED} outside the alias."),
    )
    write(
        linked / "other.md",
        page("Other page", "other", f"{WORD} {UNRELATED} outside notes."),
    )
    write(
        linked / "notes" / "real" / "hidden.md",
        page(f"Hidden {CANARY}", CANARY, f"{WORD} {CANARY} behind the link."),
    )
    (linked / "notes" / "alias").symlink_to(Path("real"), target_is_directory=True)
    write(
        peer / "notes" / "alias" / "kept.md",
        page(f"Peer kept {PEER_MARK}", "kept", f"{WORD} {PEER_MARK} in the real alias."),
    )
    write(
        peer / "notes" / "stray.md",
        page("Peer stray", "stray", f"{WORD} outside the peer alias."),
    )
    write(
        project / "atlas-mesh.json",
        mesh_doc(
            [
                {"id": LINKED, "path": "linked"},
                {"id": PEER, "path": "peer"},
            ]
        ),
    )
    return project, linked / "notes" / "alias"


def run_mesh(root: Path, engine: str, guard: LinkGuard, query: str) -> tuple[int, dict, list[str], str]:
    index_location.clear_cache()
    buf, ebuf = io.StringIO(), io.StringIO()
    code = 99
    try:
        with guard, contextlib.redirect_stdout(buf), contextlib.redirect_stderr(ebuf):
            code = search_cmd.run_scoped(str(root), query, 10, True, engine, False, None, False, "mesh", None)
    except Exception as e:  # noqa: BLE001 - a followed link raises from the guard
        index_location.clear_cache()
        return 99, {"_error": repr(e)}, list(guard.hits), ebuf.getvalue()
    index_location.clear_cache()
    try:
        payload = json.loads(buf.getvalue())
    except ValueError:
        payload = {"_raw": buf.getvalue()}
    return code, payload, list(guard.hits), ebuf.getvalue()


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr8-"))
    project, link = build(tmp)
    query = f"{WORD} path:notes/alias"
    try:
        for engine in ENGINES:
            code, payload, touched, err = run_mesh(project, engine, LinkGuard(link), query)
            blob = json.dumps(payload)
            hits = payload.get("hits") or []
            members = {m.get("atlas_id"): m for m in payload.get("members") or []}
            linked_hits = [h for h in hits if h.get("atlas_id") == LINKED]
            peer_hits = [h for h in hits if h.get("atlas_id") == PEER]
            linked = members.get(LINKED) or {}
            peer = members.get(PEER) or {}
            check(
                f"{engine}-unread",
                touched == [] and not payload.get("_error"),
                f"{touched[:3]} {payload.get('_error')} {err[:240]}",
            )
            check(
                f"{engine}-no-linked-hits",
                linked_hits == [] and linked.get("status") == "ok" and linked.get("hits") == 0,
                f"{linked_hits[:3]} {linked}",
            )
            check(
                f"{engine}-no-unrelated",
                UNRELATED not in blob and CANARY not in blob and "elsewhere.md" not in blob and "hidden.md" not in blob,
                blob[:400],
            )
            check(
                f"{engine}-peer-hit",
                peer.get("status") == "ok"
                and peer.get("hits", 0) >= 1
                and any(h.get("path") == "notes/alias/kept.md" for h in peer_hits)
                and PEER_MARK in blob,
                f"{peer} paths={[h.get('path') for h in peer_hits]}",
            )
            check(
                f"{engine}-peer-constrained",
                all(h.get("path") != "notes/stray.md" for h in hits),
                str([h.get("path") for h in hits]),
            )
            check(
                f"{engine}-warning",
                WARN in err and "path filter" in err and "alias" in err,
                err[:400],
            )
            check(
                f"{engine}-exit",
                code == 0 and payload.get("complete") is True and not payload.get("_error"),
                f"{code} complete={payload.get('complete')} {blob[:240]}",
            )
    finally:
        index_location.clear_cache()

    if failed:
        print(f"FAILED: {len(failed)} check(s): {', '.join(failed)}")
        return 1
    print("OK: mesh review MC CR8 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
