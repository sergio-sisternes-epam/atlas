#!/usr/bin/env python3
"""`atlas index show|status|build` at a project root (mesh mode, no --store).

Regression for B1: from a consuming project's root (an `atlas-mesh.json`, not
a store) `atlas index show` invented a store such as `local/project-<hash>`
and reported `ok: true` next to a missing-schema error. No `atlas index` verb
may synthesise an id for a directory that is not a store, and `ok` is never
true alongside an error.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.commands import index as index_cmd  # noqa: E402
from atlas_cli.core import index_location  # noqa: E402

A = "github.com/acme/alpha"
B = "github.com/acme/beta"
GONE = "github.com/acme/gone"
CLEAN_ENV = ("ATLAS_RECALL_ENGINE", "ATLAS_INDEX_ROOT", "ATLAS_TEST_PLATFORM")


def atlas(*args: str) -> tuple[int, str, str]:
    env = {k: v for k, v in os.environ.items() if k not in CLEAN_ENV}
    proc = subprocess.run([sys.executable, str(ATLAS), *args], cwd=ROOT, text=True, capture_output=True, env=env)
    return proc.returncode, proc.stdout, proc.stderr


def as_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def init_store(path: Path) -> Path:
    code, out, err = atlas("init", "--root", str(path), "--schema-version", "1.0", "--json")
    if code != 0:
        raise SystemExit(f"atlas init failed for {path}: {out}{err}")
    return path


def write_mesh(project: Path, rows: list[dict], default: str | None = "bm25") -> None:
    doc: dict = {"version": 1, "stores": rows}
    if default:
        doc["recall"] = {"engine": default}
    project.mkdir(parents=True, exist_ok=True)
    (project / "atlas-mesh.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def errors_in(payload: object) -> list[object]:
    """Every ``error`` / ``schema_error`` value anywhere in a payload."""
    found: list[object] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in ("error", "schema_error") and value:
                found.append(value)
            found.extend(errors_in(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(errors_in(item))
    return found


def main() -> int:
    failed: list[str] = []
    invariant: list[tuple[str, dict]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    def run_json(label: str, *args: str) -> tuple[int, dict, str]:
        code, out, err = atlas(*args, "--json")
        payload = as_json(out)
        invariant.append((label, payload))
        return code, payload, out + err

    tmp = Path(tempfile.mkdtemp(prefix="atlas-index-mesh-root-"))
    try:
        project = tmp / "project"
        sa = init_store(project / "atlas" / "alpha")
        init_store(project / "atlas" / "beta")
        write_mesh(
            project,
            [
                {"id": A, "path": "atlas/alpha"},
                {"id": B, "path": "atlas/beta"},
                {"id": GONE, "path": "atlas/gone"},
            ],
        )
        subdir = project / "src" / "deep"
        subdir.mkdir(parents=True)
        mesh_ids = [A, B, GONE]

        # --- show at the project root -------------------------------------------------
        code, p, out = run_json("show-root", "index", "show", "--root", str(project))
        check(
            "show-root-store-required",
            code == 2 and p.get("ok") is False and p.get("code") == "store_required" and p.get("known_ids") == mesh_ids,
            out[:600],
        )
        check("show-root-no-local-id", "local/" not in out, out[:600])
        check("show-root-message", "is a project root, not a store" in str(p.get("error")) and "--store" in str(p.get("error")), out[:400])

        code, out, err = atlas("index", "show", "--root", str(project))
        err_lines = [line for line in err.splitlines() if line.strip()]
        check(
            "show-root-text",
            code == 2
            and not out.strip()
            and len(err_lines) == 2
            and "error:" in err_lines[0]
            and "project root, not a store" in err_lines[0]
            and err_lines[1].startswith("hint:")
            and "local/" not in out + err,
            out + err,
        )

        code, p, out = run_json("show-subdir", "index", "show", "--root", str(subdir))
        check("show-subdir-store-required", code == 2 and p.get("code") == "store_required" and "local/" not in out, out[:600])

        # --- status at the project root and from a subdirectory ------------------------
        for label, where in (("root", project), ("subdir", subdir)):
            code, p, out = run_json(f"status-{label}", "index", "status", "--root", str(where))
            ids = [r.get("store_id") for r in p.get("stores") or []]
            check(
                f"status-{label}-mesh-rows",
                code == 0 and p.get("mode") == "mesh" and ids == mesh_ids and p.get("default") == "bm25"
                and p.get("project") == str(project.resolve()) and p.get("current_store") is None,
                out[:600],
            )
            check(f"status-{label}-no-local-id", "local/" not in out, out[:600])
            check(f"status-{label}-ok-consistent", p.get("ok") is (not errors_in(p.get("stores"))), out[:600])
            code, out, err = atlas("index", "status", "--root", str(where))
            check(f"status-{label}-text", code == 0 and all(i in out for i in mesh_ids) and "local/" not in out + err, out + err)

        # --root inside a mounted store: the whole project, with the current row marked.
        inner = sa / "notes"
        inner.mkdir(exist_ok=True)
        code, p, out = run_json("status-in-store", "index", "status", "--root", str(inner))
        rows = p.get("stores") or []
        check(
            "status-in-store-current",
            code == 0
            and [r.get("store_id") for r in rows] == mesh_ids
            and p.get("current_store") == A
            and [r.get("current") for r in rows] == [True, False, False],
            out[:600],
        )

        # --- show with --store, and with --root inside a mounted store -------------------
        code, p, out = run_json("show-store", "index", "show", "--root", str(project), "--store", B)
        check("show-store-flag", code == 0 and p.get("ok") is True and p.get("store_id") == B and "local/" not in out, out[:500])
        code, p, out = run_json("show-in-store", "index", "show", "--root", str(sa))
        check("show-root-is-store", code == 0 and p.get("store_id") == A and p.get("mesh_file") == "atlas-mesh.json", out[:500])
        code, p, out = run_json("show-in-store-subdir", "index", "show", "--root", str(inner))
        check("show-inside-store", code == 0 and p.get("store_id") == A and "local/" not in out, out[:500])
        # --- a missing --root never walks up to a mounted store ---------------------------
        missing = sa / "missing"
        mesh_original = (project / "atlas-mesh.json").read_bytes()
        code, p, out = run_json("set-in-store-subdir", "index", "set", "grep", "--root", str(inner))
        check("set-existing-subdir-selects-store", code == 0 and p.get("target") == A, out[:500])
        mesh_before = (project / "atlas-mesh.json").read_bytes()
        for verb, extra in (("set", ("bm25",)), ("unset", ())):
            code, p, out = run_json(f"{verb}-missing-root", "index", verb, *extra, "--root", str(missing))
            check(
                f"{verb}-missing-root-not-found",
                code == 2 and p.get("ok") is False and p.get("code") == "root_not_found"
                and str(missing) in str(p.get("error")) and p.get("root") == str(missing),
                out[:500],
            )
            check(f"{verb}-missing-root-mesh-unchanged", (project / "atlas-mesh.json").read_bytes() == mesh_before)
            (project / "atlas-mesh.json").write_bytes(mesh_before)
        for verb in ("show", "status", "build"):
            code, p, out = run_json(f"{verb}-missing-root", "index", verb, "--root", str(missing))
            check(f"{verb}-missing-root-not-found", code == 2 and p.get("code") == "root_not_found", out[:500])
        code, out, err = atlas("index", "set", "bm25", "--root", str(missing))
        err_lines = [line for line in err.splitlines() if line.strip()]
        check(
            "set-missing-root-text",
            code == 2 and not out.strip() and len(err_lines) == 1 and "error:" in err_lines[0] and str(missing) in err_lines[0],
            out + err,
        )
        as_file = sa / "page.md"
        as_file.write_text("x\n", encoding="utf-8")
        code, p, out = run_json("show-file-root", "index", "show", "--root", str(as_file))
        check("show-file-root-not-found", code == 2 and p.get("code") == "root_not_found", out[:500])
        check("missing-root-mesh-unchanged", (project / "atlas-mesh.json").read_bytes() == mesh_before)
        as_file.unlink()
        (project / "atlas-mesh.json").write_bytes(mesh_original)

        # --- set/unset from a store subdirectory (no --store) write only that store's row ----
        mesh_path = project / "atlas-mesh.json"
        original_doc = json.loads(mesh_original)

        def mesh_doc() -> dict:
            return json.loads(mesh_path.read_text(encoding="utf-8"))

        def only_row_changed(doc: dict, sid: str, engine: str) -> bool:
            """``sid``'s row carries ``engine``; every other row and the top level equal the original."""
            rows_now = {r.get("id"): r for r in doc.get("stores") or []}
            rows_was = {r.get("id"): r for r in original_doc["stores"]}
            if list(rows_now) != list(rows_was):
                return False
            row = rows_now[sid]
            expected_row = {**rows_was[sid], "recall": {"engine": engine}}
            others_same = all(rows_now[i] == rows_was[i] for i in rows_was if i != sid)
            top_same = {k: v for k, v in doc.items() if k != "stores"} == {
                k: v for k, v in original_doc.items() if k != "stores"
            }
            return row == expected_row and others_same and top_same

        nano_warn = (index_cmd.unavailable_warning("nanograph") or {}).get("code")

        # JSON mode, from alpha's subdirectory (alpha is the first row).
        code, p, out = run_json("set-subdir", "index", "set", "bm25", "--root", str(inner))
        check(
            "set-subdir-updates-row",
            code == 0 and p.get("ok") is True and p.get("changed") is True and p.get("target") == A
            and p.get("previous") is None and p.get("value") == "bm25" and only_row_changed(mesh_doc(), A, "bm25"),
            out[:600],
        )
        code, p, out = run_json("set-subdir-second", "index", "set", "nanograph", "--root", str(inner))
        warn_codes = [w.get("code") for w in p.get("warnings") or []]
        check(
            "set-subdir-second-engine-overwrites-row",
            code == 0 and p.get("ok") is True and p.get("target") == A and p.get("previous") == "bm25"
            and p.get("value") == "nanograph" and only_row_changed(mesh_doc(), A, "nanograph")
            and warn_codes == ([nano_warn] if nano_warn else []),
            out[:600],
        )
        code, p, out = run_json("unset-subdir", "index", "unset", "--root", str(inner))
        doc = mesh_doc()
        check(
            "unset-subdir-restores-row",
            code == 0 and p.get("ok") is True and p.get("changed") is True and p.get("target") == A
            and p.get("previous") == "nanograph" and p.get("value") is None
            and "recall" not in doc["stores"][0] and doc == original_doc,
            out[:600],
        )
        # The writer keeps the detected indent and trailing newline, so the file round-trips byte for byte.
        check("unset-subdir-restores-bytes", mesh_path.read_bytes() == mesh_original)

        # Text mode, from beta's subdirectory (not the first row, so a first-row default would fail).
        beta_inner = project / "atlas" / "beta" / "notes"
        beta_inner.mkdir(exist_ok=True)
        code, out, err = atlas("index", "set", "bm25", "--root", str(beta_inner))
        check(
            "set-subdir-text",
            code == 0 and f"store {B} recall.engine (unset) -> bm25" in out and "error" not in err
            and only_row_changed(mesh_doc(), B, "bm25"),
            out + err,
        )
        code, out, err = atlas("index", "set", "nanograph", "--root", str(beta_inner))
        check(
            "set-subdir-text-second-engine",
            code == 0 and f"store {B} recall.engine bm25 -> nanograph" in out
            and (("warning:" in err and "nanograph" in err) if nano_warn else "warning:" not in err)
            and only_row_changed(mesh_doc(), B, "nanograph"),
            out + err,
        )
        code, out, err = atlas("index", "unset", "--root", str(beta_inner))
        check(
            "unset-subdir-text",
            code == 0 and f"store {B} recall.engine nanograph -> (unset)" in out
            and mesh_doc() == original_doc and mesh_path.read_bytes() == mesh_original,
            out + err,
        )
        mesh_path.write_bytes(mesh_original)

        code, p, out = run_json("show-unknown", "index", "show", "--root", str(project), "--store", "github.com/acme/nope")
        check("show-unknown-store", code == 2 and p.get("known_ids") == mesh_ids, out[:400])

        # A mesh row whose directory exists but holds no contract: show still
        # reads it and reports the error. status classifies it as unmounted
        # and does not probe, so it is not a schema error (exit 0).
        broken = tmp / "broken"
        init_store(broken / "atlas" / "alpha")
        (broken / "atlas" / "empty").mkdir(parents=True)
        write_mesh(broken, [{"id": A, "path": "atlas/alpha"}, {"id": "github.com/acme/empty", "path": "atlas/empty"}])
        code, p, out = run_json("show-broken", "index", "show", "--root", str(broken), "--store", "github.com/acme/empty")
        check("show-schema-error-not-ok", code == 1 and p.get("ok") is False and bool(p.get("error")), out[:500])
        code, p, out = run_json("status-broken", "index", "status", "--root", str(broken))
        empty = next((r for r in p.get("stores") or [] if r.get("store_id") == "github.com/acme/empty"), {})
        check(
            "status-schema-error-not-ok",
            code == 0 and p.get("ok") is True and empty.get("status") == "unmounted"
            and empty.get("mounted") is False and "error" not in empty,
            out[:500],
        )

        # --- a plain directory with no mesh ----------------------------------------------
        plain = tmp / "plain"
        plain.mkdir()
        for verb in ("show", "status", "build"):
            code, p, out = run_json(f"{verb}-plain", "index", verb, "--root", str(plain))
            check(
                f"{verb}-plain-mount-hint",
                code == 2 and p.get("ok") is False and p.get("code") == "not_a_store"
                and "atlas mount" in str(p.get("error")) and "local/" not in out,
                out[:500],
            )

        # A standalone store (no mesh) still gets exactly one row.
        lone = init_store(tmp / "lone")
        code, p, out = run_json("status-lone", "index", "status", "--root", str(lone))
        check("status-standalone-one-row", code == 0 and p.get("mode") == "standalone" and len(p.get("stores") or []) == 1, out[:400])

        # --- build at the project root ------------------------------------------------------
        code, out, err = atlas("index", "build", "--root", str(project), "--json")
        p = as_json(out)
        check(
            "build-root-store-required",
            code == 2 and p.get("code") == "store_required" and "--all" in str(p.get("hint")) and "--store" in str(p.get("hint"))
            and "local/" not in out and not (project / ".atlas").exists(),
            out[:500],
        )
        code, out, err = atlas("index", "build", "--root", str(project))
        check("build-root-text-hint", code == 2 and "hint:" in err and "--all" in err, out + err)

        # --- single-row mesh: the only row is selected ------------------------------------
        single = tmp / "single"
        init_store(single / "atlas" / "alpha")
        write_mesh(single, [{"id": A, "path": "atlas/alpha"}], default=None)
        code, p, out = run_json("show-single", "index", "show", "--root", str(single))
        check(
            "show-single-row-selected",
            code == 0 and p.get("ok") is True and p.get("store_id") == A and p.get("selected") == "only_mesh_row" and "local/" not in out,
            out[:500],
        )
        code, out, err = atlas("index", "show", "--root", str(single))
        check("show-single-row-text-note", code == 0 and out.startswith("note:") and A in out, out + err)

        # --- core: no id is ever derived for a non-store directory --------------------------
        index_location.clear_cache()
        for label, where in (("project", project), ("subdir", subdir), ("plain", plain)):
            try:
                loc = index_location.resolve(where)
            except index_location.NotAStoreError:
                check(f"resolve-{label}-refused", True)
            else:
                check(f"resolve-{label}-refused", False, loc.atlas_id)
        check("resolve-mesh-row", index_location.resolve(sa).atlas_id == A)
        check("resolve-standalone-local", index_location.resolve(lone).id_source in ("local", "origin"))

        # `atlas recall status` on a non-store reports its error without an index id.
        code, out, err = atlas("recall", "status", "--root", str(project), "--json")
        check("recall-status-root-no-local-id", as_json(out).get("ok") is False and "local/" not in out, out[:400])

        # --- invariant: ok: true never coexists with an error ---------------------------------
        bad = [label for label, payload in invariant if payload.get("ok") is True and errors_in(payload)]
        check("ok-never-true-with-error", not bad and len(invariant) > 10, str(bad))
        check("all-json-parsed", all(payload for _, payload in invariant), str([lbl for lbl, pl in invariant if not pl]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} check(s) failed: {', '.join(failed)}")
        return 1
    print("\nall index show/status mesh-root checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
