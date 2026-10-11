#!/usr/bin/env python3
"""Copilot review CR4: mesh scope never follows symlinks.

(a) ripgrep is not handed a top-level directory symlink and is not passed
    ``--follow`` / ``-L``.
(b) the same layout, through bm25 and ``build_view``, does not read the
    excluded store.
(c) a symlinked file inside an included store, pointing into an excluded
    store, is not read.
(d) a member whose root is a symlink, and one whose root has a symlinked
    parent component inside the project, are ``invalid`` / ``symlinked_root``
    and are never read.

Store scope is not changed: ``walk_tops`` still lists a directory symlink and
the grep walk still follows a file symlink.

Linux-safe: no network, no git.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.commands import search as search_cmd  # noqa: E402
from atlas_cli.core import index_location, mesh_scope, paths  # noqa: E402
from test_mesh_members import Guard  # noqa: E402
from test_mesh_recall import page, schema, write  # noqa: E402

INC = "github.com/acme/included"
EXC = "github.com/acme/excluded"
SIDE = "github.com/acme/side"
ROOTLINK = "github.com/acme/rootlink"
PARENTLINK = "github.com/acme/parentlink"
WORD = "wombatqx"
CANARY = "EXCLUDEDWOMBATQX"
ROOT_CANARY = "ROOTLINKCANARY"
PARENT_CANARY = "PARENTLINKCANARY"


class FollowGuard(Guard):
    """Fail a following call whose real path is strictly inside ``root``.

    ``lstat`` is not wrapped: classifying a symlink must not count as a read
    of its target. A call whose path argument is already inside ``root`` fails
    too.
    """

    busy = False

    def __enter__(self) -> FollowGuard:
        for name in ("stat", "open", "listdir", "scandir", "readlink", "access", "walk"):
            self._wrap_follow(os, name)
        self._wrap_follow(builtins, "open")
        self._wrap_follow(io, "open")
        return self

    def _wrap_follow(self, owner: object, name: str) -> None:
        original = getattr(owner, name)
        guard = self

        def wrapped(*args, **kwargs):
            # Path.is_symlink() is os.stat(..., follow_symlinks=False): an lstat,
            # not a read of the target. A path already inside the excluded root
            # is still a hit.
            if args and super(FollowGuard, guard)._inside(args[0]):
                guard.hits.append(f"{name}({args[0]})")
                raise PermissionError(f"excluded member touched: {name} {args[0]}")
            if kwargs.get("follow_symlinks") is False:
                return original(*args, **kwargs)
            if args and guard._followed(args[0]):
                guard.hits.append(f"{name}({args[0]})")
                raise PermissionError(f"excluded member touched: {name} {args[0]}")
            return original(*args, **kwargs)

        self.saved.append((owner, name, original))
        setattr(owner, name, wrapped)

    def _followed(self, path: object) -> bool:
        if FollowGuard.busy or isinstance(path, int):
            return False
        FollowGuard.busy = True
        try:
            real = os.path.realpath(os.fsdecode(os.fspath(path)))
        except (TypeError, OSError, ValueError):
            return False
        finally:
            FollowGuard.busy = False
        return real.startswith(self.root + os.sep)


def mesh_doc(stores: list[dict]) -> str:
    return json.dumps({"version": 1, "recall": {"scope": "mesh"}, "stores": stores}, indent=2) + "\n"


def run_scoped(root: Path, engine: str, guard: Guard | None, query: str) -> tuple[int, dict, list[str], str]:
    index_location.clear_cache()
    buf, ebuf = io.StringIO(), io.StringIO()
    active = guard if guard is not None else contextlib.nullcontext()
    code = 99
    try:
        with active, contextlib.redirect_stdout(buf), contextlib.redirect_stderr(ebuf):
            code = search_cmd.run_scoped(str(root), query, 10, True, engine, False, None, False, "mesh", None)
    except Exception as e:  # noqa: BLE001 - old code follows and the guard raises
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


def install_rg(bin_dir: Path, log: Path) -> None:
    script = bin_dir / "rg"
    script.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" >> "$RG_ARGV_LOG"\n'
        'printf "\\n" >> "$RG_ARGV_LOG"\n'
        "exit 1\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def build_dir_alias(tmp: Path) -> tuple[Path, Path, Path]:
    """Included store with a top-level ``alias -> <excluded member>`` directory symlink."""
    project = tmp / "proj"
    inc = project / "included"
    exc = project / "excluded"
    schema(inc)
    write(inc / "notes" / "keep.md", page("Graph export keep", "keep", f"{WORD} in included."))
    schema(exc)
    write(
        exc / "notes" / "hidden.md",
        page(f"Graph export {CANARY}", f"{CANARY} title", f"{CANARY} {WORD} body."),
    )
    (inc / "alias").symlink_to(Path("..") / "excluded", target_is_directory=True)
    write(
        project / "atlas-mesh.json",
        mesh_doc(
            [
                {"id": INC, "path": "included"},
                {"id": EXC, "path": "excluded", "mesh_member": False},
            ]
        ),
    )
    return project, inc, exc


def build_file_leak(tmp: Path) -> tuple[Path, Path, Path]:
    """Included store with ``notes/leak.md`` pointing at the excluded store."""
    project = tmp / "proj"
    inc = project / "included"
    exc = project / "excluded"
    schema(inc)
    write(inc / "notes" / "keep.md", page("Graph export keep", "keep", f"{WORD} in included."))
    schema(exc)
    write(
        exc / "notes" / "hidden.md",
        page(f"Graph export {CANARY}", f"{CANARY} title", f"{CANARY} {WORD} body."),
    )
    (inc / "notes" / "leak.md").symlink_to(Path("..") / ".." / "excluded" / "notes" / "hidden.md")
    write(
        project / "atlas-mesh.json",
        mesh_doc(
            [
                {"id": INC, "path": "included"},
                {"id": EXC, "path": "excluded", "mesh_member": False},
            ]
        ),
    )
    return project, inc, exc


def build_symlinked_roots(tmp: Path) -> tuple[Path, Path, Path]:
    """An included symlink root, and an included root under a symlinked parent."""
    project = tmp / "proj"
    real = project / "realstore"
    schema(real)
    write(real / "notes" / "hidden.md", page(f"Graph export {ROOT_CANARY}", f"{ROOT_CANARY} title", f"{ROOT_CANARY} body."))
    (project / "alias").symlink_to(Path("realstore"), target_is_directory=True)
    child = project / "nests" / "child"
    schema(child)
    write(child / "notes" / "hidden.md", page(f"Graph export {PARENT_CANARY}", f"{PARENT_CANARY} title", f"{PARENT_CANARY} body."))
    (project / "hop").symlink_to(Path("nests"), target_is_directory=True)
    side = project / "side"
    schema(side)
    write(side / "notes" / "side.md", page("Graph export side", "side title", "Graph export side body."))
    write(
        project / "atlas-mesh.json",
        mesh_doc(
            [
                {"id": ROOTLINK, "path": "alias"},
                {"id": PARENTLINK, "path": "hop/child"},
                {"id": SIDE, "path": "side"},
            ]
        ),
    )
    return project, real, child


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr4-"))
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    rg_log = tmp / "rg-argv"
    install_rg(bin_dir, rg_log)
    old_path = os.environ.get("PATH", "")
    old_log = os.environ.get("RG_ARGV_LOG")
    os.environ["PATH"] = str(bin_dir) + os.pathsep + old_path
    os.environ["RG_ARGV_LOG"] = str(rg_log)
    try:
        # (a) ripgrep must not be handed the alias and must not be told to follow.
        project, inc, exc = build_dir_alias(tmp / "dir-alias")
        which = shutil.which("rg")
        check("a-rg-wrapper-first", which == str(bin_dir / "rg"), str(which))
        code, payload, _, err = run_scoped(project, "grep", Guard(exc), WORD)
        text = json.dumps(payload)
        args = rg_log.read_text(encoding="utf-8").splitlines() if rg_log.exists() else []
        alias = str(inc / "alias")
        members = {m["atlas_id"]: m for m in payload.get("members") or []}
        uris = [h.get("uri", "") for h in payload.get("hits") or []]
        titles = [h.get("title", "") for h in payload.get("hits") or []]
        check("a-rg-invoked", WORD in args, str(args[:12]))
        check("a-rg-argv-omits-alias", alias not in args and not any(a.endswith("/alias") for a in args), str(args))
        check("a-rg-no-follow-flag", "--follow" not in args and "-L" not in args, str(args))
        check("a-rg-exit-0", code == 0, f"{code} {err[:200]} {text[:300]}")
        check("a-rg-no-excluded-hit", CANARY not in text and CANARY not in err and not any(CANARY in t for t in titles), text[:400])
        check("a-rg-no-excluded-uri", not any("hidden.md" in u or EXC in u for u in uris), str(uris))
        check(
            "a-rg-excluded-unsearched",
            members.get(EXC, {}).get("status") == "excluded" and members.get(EXC, {}).get("hits") == 0,
            str(members.get(EXC)),
        )

        # Store scope still lists the directory symlink. Mesh scope drops it.
        check("store-scope-walk-tops-keeps-dir-symlink", any(p.name == "alias" for p in paths.walk_tops(inc)))
        if hasattr(paths, "mesh_walks"):
            with paths.mesh_walks():
                mesh_tops = [p.name for p in paths.walk_tops(inc)]
            check("a-mesh-walk-tops-omits-alias", "alias" not in mesh_tops, str(mesh_tops))

        # (b) bm25 and build_view: no access under the excluded root.
        for engine in ("bm25",):
            held = Guard(exc)
            code_b, payload_b, touched, err_b = run_scoped(project, engine, held, WORD)
            text_b = json.dumps(payload_b)
            check(f"b-{engine}-exit-0", code_b == 0, f"{code_b} {err_b[:200]} {text_b[:300]}")
            check(f"b-{engine}-unread", touched == [], str(touched[:5]))
            check(f"b-{engine}-no-canary", CANARY not in text_b and CANARY not in err_b, text_b[:400])
        index_location.clear_cache()
        with Guard(exc) as view_guard:
            try:
                view = mesh_scope.build_view(mesh_scope.discover(project))
                view_error = ""
            except Exception as e:  # noqa: BLE001
                view, view_error = {}, repr(e)
        index_location.clear_cache()
        view_text = json.dumps(view)
        check("b-build-view-unread", view_guard.hits == [] and not view_error, f"{view_guard.hits[:3]} {view_error}")
        check("b-build-view-no-canary", CANARY not in view_text, view_text[:300])

        # (c) a file symlink into the excluded store is not read.
        project_c, inc_c, exc_c = build_file_leak(tmp / "file-leak")
        # Store scope still follows a file symlink (is_file stats the target)
        # even when the target is then dropped as outside the store.
        followed: list[str] = []
        original_stat = os.stat

        def recording_stat(path, *args, **kwargs):
            if kwargs.get("follow_symlinks") is not False:
                try:
                    text = os.fsdecode(os.fspath(path))
                except TypeError:
                    text = ""
                if text.endswith(f"{os.sep}leak.md") or text.endswith("/leak.md"):
                    followed.append(text)
            return original_stat(path, *args, **kwargs)

        os.stat = recording_stat
        try:
            list(paths.iter_concept_md(inc_c))
        finally:
            os.stat = original_stat
        check("store-scope-still-follows-file-symlink", bool(followed), str(followed))
        for engine in ("grep", "bm25", "nanograph"):
            held = FollowGuard(exc_c)
            code_c, payload_c, touched, err_c = run_scoped(project_c, engine, held, WORD)
            text_c = json.dumps(payload_c)
            check(f"c-{engine}-unread", touched == [] and not payload_c.get("_error"), f"{touched[:3]} {payload_c.get('_error')} {err_c[:200]}")
            check(f"c-{engine}-no-canary", CANARY not in text_c and CANARY not in err_c, text_c[:400])
            check(f"c-{engine}-exit-0", code_c == 0, f"{code_c} {err_c[:200]} {text_c[:300]}")
        index_location.clear_cache()
        with FollowGuard(exc_c) as file_guard:
            try:
                view_c = mesh_scope.build_view(mesh_scope.discover(project_c))
                file_error = ""
            except Exception as e:  # noqa: BLE001
                view_c, file_error = {}, repr(e)
        index_location.clear_cache()
        check("c-build-view-unread", file_guard.hits == [] and not file_error, f"{file_guard.hits[:3]} {file_error}")
        check("c-build-view-no-canary", CANARY not in json.dumps(view_c), json.dumps(view_c)[:300])

        # (d) symlinked member roots are invalid and never read.
        project_d, real, child = build_symlinked_roots(tmp / "roots")
        with FollowGuard(real) as g_real, FollowGuard(child) as g_child:
            try:
                statuses = [(m.atlas_id, m.status, m.reason) for m in mesh_scope.members(mesh_scope.discover(project_d))]
                class_error = ""
            except Exception as e:  # noqa: BLE001
                statuses, class_error = [], repr(e)
        check("d-symlinked-roots-unread", g_real.hits == [] and g_child.hits == [] and not class_error, f"{g_real.hits[:3]} {g_child.hits[:3]} {class_error}")
        check(
            "d-root-symlink-invalid",
            (ROOTLINK, "invalid", "symlinked_root") in statuses,
            str(statuses),
        )
        check(
            "d-parent-symlink-invalid",
            (PARENTLINK, "invalid", "symlinked_root") in statuses,
            str(statuses),
        )
        held_real, held_child = FollowGuard(real), FollowGuard(child)
        # One guard at a time: FollowGuard.busy is shared, and nested guards
        # would hide each other's realpath check. Search under each in turn.
        code_d, payload_d, touched_d, err_d = run_scoped(project_d, "grep", held_real, "graph")
        code_d2, payload_d2, touched_d2, err_d2 = run_scoped(project_d, "bm25", held_child, "graph")
        text_d = json.dumps(payload_d) + json.dumps(payload_d2)
        members_d = {m["atlas_id"]: m for m in payload_d.get("members") or []}
        check("d-search-unread", touched_d == [] and touched_d2 == [], f"{touched_d[:3]} {touched_d2[:3]} {err_d[:120]}")
        check("d-search-exit-0", code_d == 0 and code_d2 == 0, f"{code_d} {code_d2} {err_d[:160]} {err_d2[:160]}")
        check("d-search-no-canary", ROOT_CANARY not in text_d and PARENT_CANARY not in text_d, text_d[:400])
        check(
            "d-search-statuses",
            members_d.get(ROOTLINK, {}).get("reason") == "symlinked_root"
            and members_d.get(PARENTLINK, {}).get("reason") == "symlinked_root"
            and members_d.get(ROOTLINK, {}).get("hits") == 0
            and members_d.get(PARENTLINK, {}).get("hits") == 0,
            str(members_d),
        )
        index_location.clear_cache()
        with FollowGuard(real) as vg_real:
            try:
                view_d = mesh_scope.build_view(mesh_scope.discover(project_d))
                view_d_error = ""
            except Exception as e:  # noqa: BLE001
                view_d, view_d_error = {}, repr(e)
        index_location.clear_cache()
        with FollowGuard(child) as vg_child:
            try:
                mesh_scope.build_view(mesh_scope.discover(project_d))
                view_d_error2 = ""
            except Exception as e:  # noqa: BLE001
                view_d_error2 = repr(e)
        index_location.clear_cache()
        view_members = {m["atlas_id"]: m for m in view_d.get("members", [])}
        check("d-view-unread", vg_real.hits == [] and vg_child.hits == [] and not view_d_error and not view_d_error2, f"{vg_real.hits[:2]} {vg_child.hits[:2]} {view_d_error} {view_d_error2}")
        check(
            "d-view-statuses",
            view_members.get(ROOTLINK, {}).get("reason") == "symlinked_root"
            and view_members.get(PARENTLINK, {}).get("reason") == "symlinked_root",
            str(view_members),
        )
        check("d-view-no-canary", ROOT_CANARY not in json.dumps(view_d) and PARENT_CANARY not in json.dumps(view_d))
    finally:
        os.environ["PATH"] = old_path
        if old_log is None:
            os.environ.pop("RG_ARGV_LOG", None)
        else:
            os.environ["RG_ARGV_LOG"] = old_log
        index_location.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"FAILED: {len(failed)} check(s): {', '.join(failed)}")
        return 1
    print("OK: mesh review MC CR4 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
