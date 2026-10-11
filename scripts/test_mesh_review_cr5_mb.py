#!/usr/bin/env python3
"""Copilot review CR5 for packet MB.

index status in mesh mode must classify rows before any per-store probe, and
mesh writes must refuse a non-regular destination instead of following it.
In-process. Linux-safe: no network.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.commands.graph import run_export  # noqa: E402
from atlas_cli.commands.index import run_status  # noqa: E402
from atlas_cli.core import (  # noqa: E402
    driver_overlay,
    graph,
    index_location,
    index_publish,
    mesh_graph,
    mesh_scope,
    meshfile,
    paths,
)
from atlas_cli.core.drivers.nanograph import DB_NAME, QUERIES_NAME, READY_NAME, NanographDriver  # noqa: E402
from atlas_cli.core.ignore_guard import ensure_indexes_ignored, ensure_mesh_lock_ignored  # noqa: E402
from atlas_cli.core.owned_lock import OwnedLock  # noqa: E402
from atlas_cli.core.recall_index import _write_sqlite  # noqa: E402
from test_mesh_graph import ALPHA, contract, write  # noqa: E402

FAILURES: list[str] = []
OK = ALPHA
SECRET = "github.com/acme/secret"
EXT = "github.com/acme/ext"
ABS = "github.com/acme/abs"
CANARY = "CR5MB-PAGE-CANARY\n"


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if not ok and detail != "" else ""))
    if not ok:
        FAILURES.append(name)


def _forms(path: Path) -> frozenset[str]:
    text = os.path.normpath(os.path.abspath(path))
    forms = {text}
    try:
        forms.add(os.path.realpath(text))
    except OSError:
        pass
    return frozenset(forms)


class StatusGuard:
    """Refuse stat/open under forbidden roots and outside the project.

    Ancestors of the project and runtime prefixes (git, the interpreter) are
    allowed. Forbidden roots are refused even when they sit inside the project.
    """

    def __init__(self, project: Path, forbidden: list[Path]) -> None:
        self.project = _forms(project)
        self.forbidden = [_forms(path) for path in forbidden]
        self.hits: list[str] = []
        self.saved: list[tuple[object, str, object]] = []
        prefixes = ["/usr", "/bin", "/lib", "/lib64", "/proc", "/dev", "/etc", "/sys", "/run", "/var"]
        prefixes += [sys.prefix, getattr(sys, "base_prefix", sys.prefix), os.path.dirname(sys.executable)]
        prefixes += os.environ.get("PATH", "").split(os.pathsep)
        self.allow = [os.path.normpath(p) for p in prefixes if p]

    def _text(self, path: object) -> str | None:
        if isinstance(path, int):
            return None
        try:
            return os.path.normpath(os.path.abspath(os.fsdecode(os.fspath(path))))
        except (TypeError, ValueError):
            return None

    def _forbidden(self, text: str) -> bool:
        return any(text == root or text.startswith(root + os.sep) for forms in self.forbidden for root in forms)

    def _inside_project(self, text: str) -> bool:
        return any(text == root or text.startswith(root + os.sep) for root in self.project)

    def _ancestor(self, text: str) -> bool:
        if text == os.sep:
            return True
        return any(root == text or root.startswith(text + os.sep) for root in self.project)

    def _locate_walk(self, text: str) -> bool:
        """``locate`` / ``mesh_match`` stat ``atlas-mesh.json`` and ``.git`` on ancestors only."""
        parent, sep, name = text.rpartition(os.sep)
        if not sep or name not in {"atlas-mesh.json", ".git"}:
            return False
        return self._ancestor(parent or os.sep)

    def _allowed_outside(self, text: str) -> bool:
        if self._ancestor(text) or self._locate_walk(text):
            return True
        return any(text == prefix or text.startswith(prefix + os.sep) for prefix in self.allow)

    def _wrap(self, owner: object, name: str) -> None:
        original = getattr(owner, name)
        guard = self

        def wrapped(*args: object, **kwargs: object) -> object:
            target = args[0] if args else kwargs.get("path", kwargs.get("file"))
            text = guard._text(target)
            # Classification lstats an in-project non-ok root and does not follow it.
            if (
                name == "lstat"
                and text is not None
                and guard._inside_project(text)
                and any(text == root for forms in guard.forbidden for root in forms)
            ):
                return original(*args, **kwargs)
            if text is not None and (
                guard._forbidden(text) or (not guard._inside_project(text) and not guard._allowed_outside(text))
            ):
                guard.hits.append(f"{name}({text})")
                raise PermissionError(f"status probed {name} {text}")
            return original(*args, **kwargs)

        self.saved.append((owner, name, original))
        setattr(owner, name, wrapped)

    def __enter__(self) -> "StatusGuard":
        for name in ("stat", "lstat", "open", "listdir", "scandir", "readlink", "access"):
            self._wrap(os, name)
        self._wrap(builtins, "open")
        return self

    def __exit__(self, *exc: object) -> None:
        for owner, name, original in reversed(self.saved):
            setattr(owner, name, original)


def _mesh(project: Path, stores: list[dict]) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "atlas-mesh.json").write_text(
        json.dumps({"version": 1, "stores": stores}, indent=2) + "\n", encoding="utf-8"
    )


def _capture_status(project: Path, as_json: bool) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = run_status(str(project), as_json)
    return code, buf.getvalue()


def test_status_does_not_probe(tmp: Path) -> None:
    project = tmp / "proj"
    ok = project / "atlas" / "ok"
    contract(ok, OK, "Ok")
    write(ok / "notes" / "page.md", "ok member\n")
    excluded = project / "atlas" / "secret"
    contract(excluded, SECRET, "Secret")
    write(excluded / "notes" / "s.md", "EXCLUDED-" + CANARY)
    outside = tmp / "outside"
    outside.mkdir()
    write(outside / "notes" / "x.md", "OUTSIDE-" + CANARY)
    absolute = tmp / "absolute"
    absolute.mkdir()
    write(absolute / "notes" / "a.md", "ABSOLUTE-" + CANARY)
    before = {
        excluded / "notes" / "s.md": (excluded / "notes" / "s.md").read_bytes(),
        outside / "notes" / "x.md": (outside / "notes" / "x.md").read_bytes(),
        absolute / "notes" / "a.md": (absolute / "notes" / "a.md").read_bytes(),
    }
    _mesh(
        project,
        [
            {"id": OK, "path": "atlas/ok"},
            {"id": SECRET, "path": "atlas/secret", "mesh_member": False},
            {"id": EXT, "path": "../outside"},
            {"id": ABS, "path": str(absolute)},
        ],
    )
    index_location.clear_cache()
    with StatusGuard(project, [excluded, outside, absolute]) as guard:
        try:
            code, out = _capture_status(project, True)
            error = ""
        except Exception as exc:  # noqa: BLE001 - the guard must surface as a failed check
            code, out, error = 99, "", repr(exc)
    payload: dict = {}
    if out:
        try:
            payload = json.loads(out)
        except json.JSONDecodeError as exc:
            error = error or repr(exc)
    rows = {r.get("store_id"): r for r in payload.get("stores") or []}
    ok_row = rows.get(OK) or {}
    check(
        "status-no-probe",
        not guard.hits and not error and code == 0,
        (guard.hits[:4], error, code),
    )
    check(
        "status-ok-described",
        ok_row.get("mounted") is True and ok_row.get("engine_effective") == "grep" and "status" not in ok_row,
        ok_row,
    )
    check(
        "status-non-ok-listed",
        rows.get(SECRET, {}).get("status") == "excluded"
        and rows.get(SECRET, {}).get("mounted") is False
        and rows.get(SECRET, {}).get("path") == "atlas/secret"
        and rows.get(EXT, {}).get("status") == "invalid"
        and rows.get(EXT, {}).get("reason") == "outside_project"
        and rows.get(EXT, {}).get("path") == "../outside"
        and rows.get(ABS, {}).get("status") == "invalid"
        and rows.get(ABS, {}).get("reason") == "outside_project"
        and rows.get(ABS, {}).get("path") == str(absolute)
        and all(before[path] == path.read_bytes() for path in before),
        {k: {f: rows.get(k, {}).get(f) for f in ("status", "reason", "path", "mounted")} for k in (SECRET, EXT, ABS)},
    )
    with StatusGuard(project, [excluded, outside, absolute]) as guard:
        try:
            code, text = _capture_status(project, False)
            error = ""
        except Exception as exc:  # noqa: BLE001
            code, text, error = 99, "", repr(exc)
    check(
        "status-text-lists-non-ok",
        not guard.hits and not error and code == 0 and "excluded" in text and "outside_project" in text and SECRET in text,
        (guard.hits[:3], error, text[-400:]),
    )


def _page(tmp: Path, name: str = "page.md") -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    page = tmp / name
    page.write_text(CANARY, encoding="utf-8")
    return page


def _is_link(path: Path) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


def _refusal(exc: BaseException) -> str:
    """Refusal text when ``exc`` is the destination error, else empty.

    The class is absent on the commit these tests must fail against, so the
    lookup must not itself abort the file.
    """
    if type(exc).__name__ == "UnsafeDestination":
        return str(exc)
    return ""


def test_export_refuses_symlinks(tmp: Path) -> None:
    project = tmp / "proj"
    alpha = project / "atlas" / "alpha"
    contract(alpha, OK, "Alpha")
    page = alpha / "notes" / "page.md"
    write(page, CANARY)
    other = alpha / "notes" / "other.md"
    write(other, "OTHER-" + CANARY)
    _mesh(project, [{"id": OK, "path": "atlas/alpha"}])
    before = page.read_bytes()
    other_before = other.read_bytes()
    out = tmp / "out"
    out.mkdir()
    (out / "graph.json").symlink_to(page)
    (out / "export-receipt.json").symlink_to(other)
    index_location.clear_cache()
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = run_export(str(project), "json", str(out), False, True, "mesh")
    try:
        payload = json.loads(buf.getvalue())
    except json.JSONDecodeError:
        payload = {}
    error = str(payload.get("error") or "")
    check(
        "export-symlink-refused",
        code != 0 and "symlink" in error.lower() and "refus" in error.lower()
        and page.read_bytes() == before and other.read_bytes() == other_before
        and _is_link(out / "graph.json") and _is_link(out / "export-receipt.json"),
        (code, error, page.read_bytes()[:40]),
    )

    mixed = tmp / "mixed"
    mixed.mkdir()
    (mixed / "graph.json").write_text("OLD-GRAPH\n", encoding="utf-8")
    (mixed / "export-receipt.json").symlink_to(page)
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = run_export(str(project), "json", str(mixed), False, True, "mesh")
    check(
        "export-receipt-symlink-leaves-graph",
        code != 0 and (mixed / "graph.json").read_text(encoding="utf-8") == "OLD-GRAPH\n"
        and page.read_bytes() == before and _is_link(mixed / "export-receipt.json"),
        (code, (mixed / "graph.json").read_text(encoding="utf-8")),
    )

    atomic = tmp / "atomic"
    atomic.mkdir()
    graph_path = atomic / "graph.json"
    graph_path.write_text("OLD-GRAPH\n", encoding="utf-8")
    opened: list[tuple[object, object]] = []
    replaced: list[bytes] = []
    real_open = builtins.open
    real_replace = os.replace

    def spy_open(file: object, mode: str = "r", *args: object, **kwargs: object) -> object:
        try:
            if Path(os.fspath(file)) == graph_path and any(flag in str(mode) for flag in ("w", "a", "+")):
                opened.append((file, mode))
        except (TypeError, ValueError):
            pass
        return real_open(file, mode, *args, **kwargs)

    def spy_replace(src: object, dst: object) -> None:
        if Path(os.fspath(dst)) == graph_path:
            replaced.append(graph_path.read_bytes())
        real_replace(src, dst)

    builtins.open = spy_open  # type: ignore[assignment]
    os.replace = spy_replace  # type: ignore[assignment]
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = run_export(str(project), "json", str(atomic), False, True, "mesh")
        text = graph_path.read_text(encoding="utf-8")
        parsed = json.loads(text)
    finally:
        builtins.open = real_open
        os.replace = real_replace
    leftovers = [p.name for p in atomic.iterdir() if p.name.startswith(".graph.json.")]
    check(
        "export-regular-replaced-atomically",
        code == 0 and not opened and replaced == [b"OLD-GRAPH\n"] and parsed.get("nodes") is not None
        and text.endswith("\n") and not leftovers and page.read_bytes() == before,
        (code, opened, replaced, leftovers, text[:80]),
    )


def test_symlinked_out_dir(tmp: Path) -> None:
    project = tmp / "proj"
    alpha = project / "atlas" / "alpha"
    contract(alpha, OK, "Alpha")
    write(alpha / "notes" / "page.md", CANARY)
    _mesh(project, [{"id": OK, "path": "atlas/alpha"}])
    index_location.clear_cache()
    mg = mesh_graph.ensure(mesh_scope.discover(project))
    target = tmp / "target"
    target.mkdir()
    link = tmp / "out-link"
    link.symlink_to(target, target_is_directory=True)
    try:
        mesh_graph.export_json(mg, link)
        error = ""
    except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
        error = str(exc) if type(exc).__name__ in {"MeshGraphError", "UnsafeDestination"} else ""
    check(
        "export-symlinked-out-dir",
        bool(error) and "symlink" in error.lower() and not (target / "graph.json").exists(),
        error,
    )


def test_snapshot_symlink(tmp: Path) -> None:
    project = tmp / "proj"
    alpha = project / "atlas" / "alpha"
    contract(alpha, OK, "Alpha")
    page = alpha / "notes" / "page.md"
    write(page, CANARY)
    _mesh(project, [{"id": OK, "path": "atlas/alpha"}])
    before = page.read_bytes()
    real_mkdir = Path.mkdir

    def hooked(self: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        real_mkdir(self, mode, parents=parents, exist_ok=exist_ok)
        link = self / "mesh-graph.json"
        if self.name.startswith(".tmp-") and not link.exists() and not link.is_symlink():
            link.symlink_to(page)

    Path.mkdir = hooked  # type: ignore[method-assign]
    index_location.clear_cache()
    try:
        try:
            mesh_graph.ensure(mesh_scope.discover(project))
            error = ""
        except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
            error = _refusal(exc)
    finally:
        Path.mkdir = real_mkdir  # type: ignore[method-assign]
    check(
        "snapshot-symlink-not-followed",
        bool(error) and "symlink" in error.lower() and page.read_bytes() == before,
        (error, page.read_bytes()[:40]),
    )


def test_pointer_symlink(tmp: Path) -> None:
    project = tmp / "proj"
    alpha = project / "atlas" / "alpha"
    contract(alpha, OK, "Alpha")
    page = alpha / "notes" / "page.md"
    write(page, CANARY)
    _mesh(project, [{"id": OK, "path": "atlas/alpha"}])
    before = page.read_bytes()
    root = project / ".atlas" / "indexes" / "graph" / "_mesh"
    root.mkdir(parents=True)
    pointer = root / "current.json"
    pointer.symlink_to(page)
    index_location.clear_cache()
    try:
        mesh_graph.ensure(mesh_scope.discover(project))
        error = ""
    except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
        error = _refusal(exc)
    check(
        "current-pointer-symlink-remains",
        bool(error) and "symlink" in error.lower() and _is_link(pointer) and page.read_bytes() == before,
        (error, _is_link(pointer), page.read_bytes()[:40]),
    )


def test_publish_dir_symlink(tmp: Path) -> None:
    page = _page(tmp)
    before = page.read_bytes()
    src = tmp / "generation"
    src.mkdir()
    (src / "marker").write_text("gen\n", encoding="utf-8")
    dest = tmp / "dest"
    dest.symlink_to(page)
    try:
        index_publish.publish_dir(src, dest)
        error = ""
    except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
        error = _refusal(exc)
    check(
        "publish-dir-symlink-remains",
        bool(error) and "symlink" in error.lower() and _is_link(dest) and page.read_bytes() == before,
        error,
    )


def test_lock_symlink(tmp: Path) -> None:
    page = _page(tmp)
    before = page.read_bytes()
    os.utime(page, (0, 0))
    parent = tmp / "locks"
    parent.mkdir()
    lock = parent / ".lock"
    lock.symlink_to(page)
    held = OwnedLock(parent, ".lock", stale_seconds=1)
    try:
        held.try_acquire()
        error = ""
    except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
        error = _refusal(exc)
    check(
        "lock-symlink-not-taken-over",
        bool(error) and "symlink" in error.lower() and _is_link(lock) and page.read_bytes() == before,
        (error, _is_link(lock)),
    )
    real = tmp / "real-parent"
    real.mkdir()
    link_parent = tmp / "link-parent"
    link_parent.symlink_to(real, target_is_directory=True)
    try:
        OwnedLock(link_parent, ".lock", stale_seconds=1).try_acquire()
        parent_error = ""
    except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
        parent_error = _refusal(exc)
    check(
        "lock-parent-symlink-refused",
        bool(parent_error) and "symlink" in parent_error.lower() and not (real / ".lock").exists(),
        parent_error,
    )


def test_sqlite_symlink(tmp: Path) -> None:
    page = _page(tmp)
    before = page.read_bytes()
    link = tmp / "projection.sqlite"
    link.symlink_to(page)
    try:
        _write_sqlite(link, [], "digest")
        error = ""
    except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
        error = _refusal(exc)
    check(
        "sqlite-symlink-not-followed",
        bool(error) and "symlink" in error.lower() and page.read_bytes() == before and _is_link(link),
        (error, page.read_bytes()[:20]),
    )


def _fake_nanograph(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo 1.3.0; exit 0; fi\n'
        "prev=\n"
        "for arg in \"$@\"; do\n"
        '  if [ "$prev" = "--db" ]; then printf "corrupted\\n" > "$arg"; fi\n'
        "  prev=$arg\n"
        "done\n"
        "exit 0\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _nano_export(path: Path) -> None:
    path.mkdir()
    (path / "export-receipt.json").write_text('{"corpus_digest": "abc"}\n', encoding="utf-8")
    (path / "schema.pg").write_text("node Page {\n  slug: String @key\n}\n", encoding="utf-8")
    (path / "seed.jsonl").write_text("", encoding="utf-8")


def test_nanograph_symlinks(tmp: Path) -> None:
    fake = tmp / "nanograph"
    _fake_nanograph(fake)
    export = tmp / "export"
    _nano_export(export)
    saved = os.environ.get("ATLAS_NANOGRAPH_BIN")
    os.environ["ATLAS_NANOGRAPH_BIN"] = str(fake)
    driver_overlay.set_platform_provider_for_tests(lambda: ("darwin", "arm64"))
    try:
        page = _page(tmp, "queries-page.md")
        before = page.read_bytes()
        index = tmp / "queries-index"
        index.mkdir()
        (index / QUERIES_NAME).symlink_to(page)
        try:
            NanographDriver().build(export, index)
            error = ""
        except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
            error = str(exc) if type(exc).__name__ == "DriverError" else ""
        check(
            "nanograph-queries-symlink",
            bool(error) and "symlink" in error.lower() and page.read_bytes() == before and _is_link(index / QUERIES_NAME),
            (error, page.read_bytes()[:30]),
        )

        page = _page(tmp, "ready-page.md")
        before = page.read_bytes()
        index = tmp / "ready-index"
        index.mkdir()
        (index / READY_NAME).symlink_to(page)
        try:
            NanographDriver().build(export, index)
            error = ""
        except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
            error = str(exc) if type(exc).__name__ == "DriverError" else ""
        check(
            "nanograph-ready-symlink",
            bool(error) and "symlink" in error.lower() and page.read_bytes() == before and _is_link(index / READY_NAME),
            (error, _is_link(index / READY_NAME)),
        )

        page = _page(tmp, "db-page.md")
        before = page.read_bytes()
        index = tmp / "db-index"
        index.mkdir()
        (index / DB_NAME).symlink_to(page)
        try:
            NanographDriver().build(export, index)
            error = ""
        except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
            error = str(exc) if type(exc).__name__ == "DriverError" else ""
        check(
            "nanograph-db-symlink",
            bool(error) and "symlink" in error.lower() and page.read_bytes() == before and _is_link(index / DB_NAME),
            (error, page.read_bytes()[:30]),
        )
    finally:
        driver_overlay.reset_platform_provider()
        if saved is None:
            os.environ.pop("ATLAS_NANOGRAPH_BIN", None)
        else:
            os.environ["ATLAS_NANOGRAPH_BIN"] = saved


def _git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, capture_output=True)


def test_exclude_symlink(tmp: Path) -> None:
    project = tmp / "repo"
    _git_repo(project)
    contract(project, OK, "Alpha")
    page = project / "notes" / "page.md"
    write(page, CANARY)
    before = page.read_bytes()
    exclude = project / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    if exclude.exists() or exclude.is_symlink():
        exclude.unlink()
    exclude.symlink_to(page)
    item = ensure_indexes_ignored(project)
    check(
        "ignore-exclude-symlink",
        page.read_bytes() == before and _is_link(exclude)
        and isinstance(item, dict) and item.get("level") == "warning" and "symlink" in str(item).lower(),
        item,
    )
    page.write_text(CANARY, encoding="utf-8")
    before = page.read_bytes()
    exclude.unlink()
    exclude.symlink_to(page)
    result = ensure_mesh_lock_ignored(project)
    check(
        "mesh-lock-exclude-symlink",
        page.read_bytes() == before and _is_link(exclude) and result.status == "failed" and "symlink" in str(result.reason).lower(),
        (result.status, result.reason),
    )


def test_store_export_and_meshfile(tmp: Path) -> None:
    store = tmp / "store"
    contract(store, OK, "Alpha")
    write(store / "notes" / "page.md", CANARY)
    source = graph.load_source(store)
    page = _page(tmp, "store-page.md")
    before = page.read_bytes()
    out = tmp / "store-out"
    out.mkdir()
    (out / "graph.json").symlink_to(page)
    try:
        graph.export_json(source, out)
        error = ""
    except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
        error = str(exc) if type(exc).__name__ == "GraphError" else ""
    check(
        "store-export-json-symlink",
        bool(error) and "symlink" in error.lower() and page.read_bytes() == before and _is_link(out / "graph.json"),
        error,
    )
    nano = tmp / "nano-out"
    nano.mkdir()
    (nano / "schema.pg").symlink_to(page)
    try:
        graph.export_nanograph(source, nano)
        error = ""
    except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
        error = str(exc) if type(exc).__name__ == "GraphError" else ""
    check(
        "store-export-nanograph-symlink",
        bool(error) and "symlink" in error.lower() and page.read_bytes() == before and _is_link(nano / "schema.pg"),
        error,
    )
    link = tmp / "atlas-mesh.json"
    link.symlink_to(page)
    try:
        meshfile.write_json_atomic(link, {"version": 1, "stores": []})
        error = ""
    except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
        error = _refusal(exc)
    check(
        "meshfile-symlink-remains",
        bool(error) and "symlink" in error.lower() and _is_link(link) and page.read_bytes() == before,
        error,
    )
    target = tmp / "followed"
    target.mkdir()
    out_link = tmp / "store-out-link"
    out_link.symlink_to(target, target_is_directory=True)
    try:
        graph.export_json(source, out_link)
        error = ""
    except Exception as exc:  # noqa: BLE001 - old code must fail the check, not abort
        error = str(exc) if type(exc).__name__ == "GraphError" else ""
    check(
        "store-export-symlinked-out-dir",
        bool(error) and "symlink" in error.lower() and not (target / "graph.json").exists(),
        error,
    )


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-cr5-"))
    try:
        test_status_does_not_probe(tmp / "status")
        test_export_refuses_symlinks(tmp / "export")
        test_symlinked_out_dir(tmp / "outdir")
        test_snapshot_symlink(tmp / "snapshot")
        test_pointer_symlink(tmp / "pointer")
        test_publish_dir_symlink(tmp / "publish")
        test_lock_symlink(tmp / "lock")
        test_sqlite_symlink(tmp / "sqlite")
        test_nanograph_symlinks(tmp / "nano")
        test_exclude_symlink(tmp / "exclude")
        test_store_export_and_meshfile(tmp / "store")
    finally:
        index_location.clear_cache()
        driver_overlay.reset_platform_provider()
        shutil_rmtree(tmp)
    if FAILURES:
        print(f"\n{len(FAILURES)} mesh review CR5 check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("\nAll mesh review CR5 checks passed")
    return 0


def shutil_rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
