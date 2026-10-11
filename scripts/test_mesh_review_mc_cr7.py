#!/usr/bin/env python3
"""Copilot review CR7: mesh scope never follows symlinked schema, overlay or member inputs.

(a) an included member whose ``schema.d`` is a symlink to an excluded member
    is not read (grep, bm25, build_view).
(b) a symlinked ``*.json`` overlay inside a real ``schema.d``, pointing at an
    excluded member, is not read (grep, bm25, build_view).
(c) other member inputs: symlinked ``SCHEMA.json`` is ``invalid`` /
    ``symlinked_root``; a symlinked ``CONTRACT.json``, index pointer,
    nanograph pointer, tgrep digest, ``log.md`` page, ``path:`` filter and
    project ``atlas-mesh.json`` are not followed.

Store scope still follows a symlinked overlay. Linux-safe: no network, no git.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

import jsonschema  # noqa: F401 - import before FollowGuard wraps open

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import index_location, mesh_scope, paths  # noqa: E402
from atlas_cli.core.drivers.nanograph import NanographDriver  # noqa: E402
from atlas_cli.core.drivers.tgrep import _load_digest  # noqa: E402
from atlas_cli.core.frontmatter import read_page  # noqa: E402
from atlas_cli.core.overlay import overlay_files  # noqa: E402
from test_mesh_recall import page, schema, write  # noqa: E402
from test_mesh_review_mc_cr4 import FollowGuard, mesh_doc, run_scoped  # noqa: E402

INC = "github.com/acme/included"
EXC = "github.com/acme/excluded"
WORD = "wombatqx"
CANARY = "EXCLUDEDWOMBATQX"
WARN = "warning: mesh scope skipped symlink"


def mesh_listing(stores: list[dict]) -> str:
    return mesh_doc(stores)


def project_with(inc: Path, exc: Path) -> None:
    write(
        inc.parent / "atlas-mesh.json",
        mesh_listing(
            [
                {"id": INC, "path": "included"},
                {"id": EXC, "path": "excluded", "mesh_member": False},
            ]
        ),
    )


def seed(tmp: Path) -> tuple[Path, Path, Path]:
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
    write(exc / "secret.json", json.dumps({"canary": CANARY, "secret": True}) + "\n")
    return project, inc, exc


def overlay_payload() -> str:
    return json.dumps({"contribution_id": "ext-notes", "canary": CANARY, "types": {}}) + "\n"


def build_dir_overlay(tmp: Path) -> tuple[Path, Path, Path]:
    project, inc, exc = seed(tmp)
    write(exc / "schema.d" / "ext-notes.json", overlay_payload())
    (inc / "schema.d").symlink_to(Path("..") / "excluded" / "schema.d", target_is_directory=True)
    project_with(inc, exc)
    return project, inc, exc


def build_file_overlay(tmp: Path) -> tuple[Path, Path, Path]:
    project, inc, exc = seed(tmp)
    write(exc / "schema.d" / "x.json", overlay_payload().replace("ext-notes", "x"))
    (inc / "schema.d").mkdir(parents=True)
    (inc / "schema.d" / "x.json").symlink_to(Path("..") / ".." / "excluded" / "schema.d" / "x.json")
    project_with(inc, exc)
    return project, inc, exc


def run_view(project: Path, guard: FollowGuard) -> tuple[dict, list[str], str]:
    index_location.clear_cache()
    ebuf = io.StringIO()
    try:
        with guard, contextlib.redirect_stderr(ebuf):
            view = mesh_scope.build_view(mesh_scope.discover(project))
            error = ""
    except Exception as e:  # noqa: BLE001 - old code follows and the guard raises
        view, error = {"_error": repr(e)}, repr(e)
    index_location.clear_cache()
    return view, list(guard.hits), ebuf.getvalue() + error


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr7-"))
    try:
        # (a) symlinked schema.d directory.
        project_a, inc_a, exc_a = build_dir_overlay(tmp / "dir")
        for engine in ("grep", "bm25"):
            held = FollowGuard(exc_a)
            code, payload, touched, err = run_scoped(project_a, engine, held, WORD)
            text = json.dumps(payload)
            check(f"a-{engine}-unread", touched == [] and not payload.get("_error"), f"{touched[:3]} {payload.get('_error')} {err[:240]}")
            check(f"a-{engine}-no-canary", CANARY not in text and CANARY not in err, text[:300])
            check(f"a-{engine}-warning", WARN in err and "schema.d" in err, err[:300])
            check(f"a-{engine}-exit-0", code == 0, f"{code} {text[:240]}")
        view_a, hits_a, err_a = run_view(project_a, FollowGuard(exc_a))
        check("a-build-view-unread", hits_a == [] and "_error" not in view_a, f"{hits_a[:3]} {err_a[:240]}")
        check("a-build-view-no-canary", CANARY not in json.dumps(view_a) and CANARY not in err_a, err_a[:240])
        check("a-build-view-warning", WARN in err_a and "schema.d" in err_a, err_a[:300])

        # (b) symlinked overlay file.
        project_b, inc_b, exc_b = build_file_overlay(tmp / "file")
        # Store scope still lists the symlinked overlay (follows). Mesh scope must not.
        store_listed = [p.name for p in overlay_files(inc_b)]
        check("b-store-scope-lists-symlink", "x.json" in store_listed, str(store_listed))
        with paths.mesh_walks(), contextlib.redirect_stderr(io.StringIO()):
            mesh_listed = [p.name for p in overlay_files(inc_b)]
        check("b-mesh-omits-symlink", "x.json" not in mesh_listed, str(mesh_listed))
        for engine in ("grep", "bm25"):
            held = FollowGuard(exc_b)
            code, payload, touched, err = run_scoped(project_b, engine, held, WORD)
            text = json.dumps(payload)
            check(f"b-{engine}-unread", touched == [] and not payload.get("_error"), f"{touched[:3]} {payload.get('_error')} {err[:240]}")
            check(f"b-{engine}-no-canary", CANARY not in text and CANARY not in err, text[:300])
            check(f"b-{engine}-warning", WARN in err and "overlay" in err, err[:300])
            check(f"b-{engine}-exit-0", code == 0, f"{code} {text[:240]}")
        view_b, hits_b, err_b = run_view(project_b, FollowGuard(exc_b))
        check("b-build-view-unread", hits_b == [] and "_error" not in view_b, f"{hits_b[:3]} {err_b[:240]}")
        check("b-build-view-no-canary", CANARY not in json.dumps(view_b) and CANARY not in err_b, err_b[:240])
        check("b-build-view-warning", WARN in err_b, err_b[:300])

        # (c) symlinked SCHEMA.json -> invalid / symlinked_root, never read.
        project_s, inc_s, exc_s = seed(tmp / "schema")
        (inc_s / "SCHEMA.json").unlink()
        (inc_s / "SCHEMA.json").symlink_to(Path("..") / "excluded" / "SCHEMA.json")
        project_with(inc_s, exc_s)
        held = FollowGuard(exc_s)
        code, payload, touched, err = run_scoped(project_s, "grep", held, WORD)
        members = {m["atlas_id"]: m for m in payload.get("members") or []}
        text = json.dumps(payload)
        check("c-schema-unread", touched == [] and not payload.get("_error"), f"{touched[:3]} {payload.get('_error')} {err[:240]}")
        check("c-schema-no-canary", CANARY not in text and CANARY not in err, text[:300])
        check(
            "c-schema-invalid",
            members.get(INC, {}).get("status") == "invalid" and members.get(INC, {}).get("reason") == "symlinked_root",
            str(members.get(INC)),
        )
        check("c-schema-exit-0", code == 0, f"{code} {text[:240]}")

        # (c) symlinked CONTRACT.json beside a real SCHEMA.json is skipped.
        project_c, inc_c, exc_c = seed(tmp / "contract")
        write(exc_c / "CONTRACT.json", json.dumps({"canary": CANARY, "schema_version": "2.0"}) + "\n")
        (inc_c / "CONTRACT.json").symlink_to(Path("..") / "excluded" / "CONTRACT.json")
        project_with(inc_c, exc_c)
        held = FollowGuard(exc_c)
        code, payload, touched, err = run_scoped(project_c, "grep", held, WORD)
        members = {m["atlas_id"]: m for m in payload.get("members") or []}
        text = json.dumps(payload)
        check("c-contract-unread", touched == [] and not payload.get("_error"), f"{touched[:3]} {payload.get('_error')} {err[:240]}")
        check("c-contract-no-canary", CANARY not in text and CANARY not in err, text[:300])
        check("c-contract-warning", WARN in err and "CONTRACT.json" in err, err[:300])
        check("c-contract-ok", members.get(INC, {}).get("status") == "ok" and code == 0, str(members.get(INC)))

        # (c) symlinked fts5 current.json is not opened.
        project_i, inc_i, exc_i = seed(tmp / "index")
        project_with(inc_i, exc_i)
        pointer = project_i / ".atlas" / "indexes" / "fts5" / "github.com" / "acme" / "included" / "current.json"
        pointer.parent.mkdir(parents=True)
        pointer.symlink_to(exc_i / "secret.json")
        held = FollowGuard(exc_i)
        code, payload, touched, err = run_scoped(project_i, "bm25", held, WORD)
        text = json.dumps(payload)
        check("c-index-unread", touched == [] and not payload.get("_error"), f"{touched[:3]} {payload.get('_error')} {err[:240]}")
        check("c-index-no-canary", CANARY not in text and CANARY not in err, text[:300])
        check("c-index-warning", WARN in err and "index pointer" in err, err[:300])
        check("c-index-exit-0", code == 0, f"{code} {text[:240]}")

        # (c) nanograph current.json.
        project_n, _inc_n, exc_n = seed(tmp / "nanograph")
        base = project_n / "ng-index"
        base.mkdir()
        (base / "current.json").symlink_to(exc_n / "secret.json")
        ebuf = io.StringIO()
        ng_error = ""
        with FollowGuard(exc_n) as ng_guard, paths.mesh_walks(), contextlib.redirect_stderr(ebuf):
            try:
                NanographDriver.has_new_index(base)
                NanographDriver()._current(base, "abc", "1")
            except Exception as e:  # noqa: BLE001
                ng_error = repr(e)
        ng_err = ebuf.getvalue()
        check("c-nanograph-unread", ng_guard.hits == [] and not ng_error, f"{ng_guard.hits[:3]} {ng_error}")
        check("c-nanograph-warning", WARN in ng_err and "nanograph index pointer" in ng_err, ng_err[:300])
        check("c-nanograph-no-canary", CANARY not in ng_err, ng_err[:200])

        # (c) tgrep digest.
        project_t, _inc_t, exc_t = seed(tmp / "tgrep")
        dest = project_t / "tg-index"
        dest.mkdir()
        (dest / "generation.json").symlink_to(exc_t / "secret.json")
        ebuf = io.StringIO()
        tg_error = ""
        with FollowGuard(exc_t) as tg_guard, paths.mesh_walks(), contextlib.redirect_stderr(ebuf):
            try:
                _load_digest(dest)
            except Exception as e:  # noqa: BLE001
                tg_error = repr(e)
        tg_err = ebuf.getvalue()
        check("c-tgrep-unread", tg_guard.hits == [] and not tg_error, f"{tg_guard.hits[:3]} {tg_error}")
        check("c-tgrep-warning", WARN in tg_err and "tgrep digest" in tg_err, tg_err[:300])
        check("c-tgrep-no-canary", CANARY not in tg_err, tg_err[:200])

        # (c) symlinked log.md refused by read_page.
        project_p, inc_p, exc_p = seed(tmp / "page")
        (inc_p / "log.md").symlink_to(Path("..") / "excluded" / "notes" / "hidden.md")
        ebuf = io.StringIO()
        page_error = ""
        with FollowGuard(exc_p) as page_guard, paths.mesh_walks(), contextlib.redirect_stderr(ebuf):
            try:
                read_page(inc_p / "log.md")
            except OSError as e:
                page_error = str(e)
        page_err = ebuf.getvalue()
        check("c-page-unread", page_guard.hits == [] and "skipped symlink" in page_error, f"{page_guard.hits[:3]} {page_error}")
        check("c-page-warning", WARN in page_err and "page" in page_err, page_err[:300])
        check("c-page-no-canary", CANARY not in page_err and CANARY not in page_error, page_err[:200])

        # (c) path: filter does not follow a directory symlink.
        project_f, inc_f, exc_f = seed(tmp / "filter")
        (inc_f / "notes" / "alias").symlink_to(Path("..") / ".." / "excluded" / "notes", target_is_directory=True)
        project_with(inc_f, exc_f)
        held = FollowGuard(exc_f)
        code, payload, touched, err = run_scoped(project_f, "grep", held, f"{WORD} path:notes/alias")
        text = json.dumps(payload)
        check("c-path-unread", touched == [] and not payload.get("_error"), f"{touched[:3]} {payload.get('_error')} {err[:240]}")
        check("c-path-no-canary", CANARY not in text and CANARY not in err, text[:300])
        check("c-path-warning", WARN in err and "path filter" in err, err[:300])
        check("c-path-exit-0", code == 0, f"{code} {text[:240]}")

        # (c) project atlas-mesh.json symlink is not followed.
        project_m, _inc_m, exc_m = seed(tmp / "meshfile")
        secret = {
            "version": 1,
            "recall": {"scope": "mesh"},
            "canary": CANARY,
            "stores": [{"id": EXC, "path": "excluded"}],
        }
        write(exc_m / "hidden-mesh.json", json.dumps(secret, indent=2) + "\n")
        listing = project_m / "atlas-mesh.json"
        if listing.exists() or listing.is_symlink():
            listing.unlink()
        listing.symlink_to(Path("excluded") / "hidden-mesh.json")
        held = FollowGuard(exc_m)
        code, payload, touched, err = run_scoped(project_m, "grep", held, WORD)
        text = json.dumps(payload) + err
        check("c-meshfile-unread", touched == [] and not payload.get("_error"), f"{touched[:3]} {payload.get('_error')} {err[:240]}")
        check("c-meshfile-no-canary", CANARY not in text, text[:300])
        check("c-meshfile-refused", code == 2 and "symlink" in text, f"{code} {text[:300]}")
    finally:
        index_location.clear_cache()

    if failed:
        print(f"FAILED: {len(failed)} check(s): {', '.join(failed)}")
        return 1
    print("OK: mesh review MC CR7 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
