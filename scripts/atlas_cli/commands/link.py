"""Pinned Atlas link inspection and pin creation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import click

from ..core.gitops import git_root
from ..core.identity import IdentityError, MalformedPinError, parse_pointer
from ..core.meshfile import MeshFileError, find_project_root, find_store, load
from ..core.paths import has_contract_file, join_under

TEXT_LIMIT = 256 * 1024
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")


def _git(repo: Path, *args: str, binary: bool = False) -> tuple[int, str | bytes, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1"},
            capture_output=True,
            text=not binary,
            check=False,
        )
    except OSError as exc:
        return 127, b"" if binary else "", str(exc)
    stdout = result.stdout if binary else (result.stdout or "").strip()
    stderr = result.stderr.decode(errors="replace") if binary else result.stderr
    return result.returncode, stdout, (stderr or "").strip()


def _git_capped(repo: Path, *args: str) -> tuple[int, bytes, bool]:
    try:
        process = subprocess.Popen(
            ["git", "-C", str(repo), *args],
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return 127, b"", False
    assert process.stdout is not None
    data = process.stdout.read(TEXT_LIMIT + 1)
    truncated = len(data) > TEXT_LIMIT
    if truncated:
        process.terminate()
        process.stdout.close()
        process.wait()
        return 0, data[:TEXT_LIMIT], True
    return process.wait(), data, False


def _store(project: Path, atlas_id: str) -> tuple[dict[str, Any] | None, Path | None, Path | None]:
    row = find_store(project, atlas_id)
    if not row:
        return None, None, None
    mount = Path(str(row.get("path") or (project / ".atlas" / Path(*atlas_id.split("/")))))
    if not mount.is_absolute():
        mount = project / mount
    mount = mount.resolve()
    subpath = str(row.get("subpath") or "")
    store = join_under(mount, subpath)
    if store is None:
        return row, mount, None
    return row, mount, store.resolve()


def _repo_and_store_path(store: Path) -> tuple[Path, str] | None:
    repo = git_root(store)
    if repo is None:
        return None
    try:
        relative = store.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None
    return repo.resolve(), "" if relative == "." else relative + "/"


def _tip(repo: Path, row: dict[str, Any]) -> tuple[str | None, str]:
    ref = str(row.get("ref") or "").strip()
    if not ref:
        code, branch, _ = _git(repo, "symbolic-ref", "--short", "-q", "HEAD")
        ref = str(branch) if code == 0 else "HEAD"
    code, out, _ = _git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    if code != 0 or not SHA_RE.fullmatch(str(out)):
        return None, ref
    return str(out), ref


def _commit_exists(repo: Path, sha: str) -> bool:
    code, kind, _ = _git(repo, "cat-file", "-t", f"{sha}^{{commit}}")
    return code == 0 and kind == "commit"


def _blob_info(repo: Path, commit: str, path: str) -> tuple[str | None, bool, str | None]:
    code, out, _ = _git(repo, "rev-parse", "--verify", "--end-of-options", f"{commit}:{path}")
    if code != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", str(out)):
        return None, False, None
    code, kind, _ = _git(repo, "cat-file", "-t", str(out))
    if code != 0:
        return None, True, None
    if kind != "blob":
        return None, True, kind
    return str(out), True, kind


def _blob(repo: Path, commit: str, path: str) -> str | None:
    return _blob_info(repo, commit, path)[0]


def _shallow(repo: Path) -> bool:
    code, out, _ = _git(repo, "rev-parse", "--is-shallow-repository")
    return code == 0 and out == "true"


def _repo_path(prefix: str, path: str) -> str:
    return f"{prefix}{path}"


def _rename_to(repo: Path, cited: str, tip: str, path: str) -> str | None:
    code, output, _ = _git(repo, "diff", "--name-status", "-z", "--find-renames", cited, tip)
    if code != 0:
        return None
    fields = str(output).split("\0")
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        index += 1
        if status.startswith(("R", "C")):
            if index + 1 >= len(fields):
                break
            old, new = fields[index], fields[index + 1]
            index += 2
            if old == path and status.startswith("R"):
                return new
        else:
            index += 1
    return None


def _diff_stats(repo: Path, cited: str, tip: str, cited_path: str, tip_path: str) -> dict[str, int]:
    code, output, _ = _git(
        repo,
        "diff",
        "--numstat",
        "--no-ext-diff",
        f"{cited}:{cited_path}",
        f"{tip}:{tip_path}",
    )
    if code != 0 or not output:
        return {"insertions": 0, "deletions": 0}
    fields = str(output).split("\t", 2)
    if len(fields) != 3:
        return {"insertions": 0, "deletions": 0}
    try:
        return {"insertions": int(fields[0]), "deletions": int(fields[1])}
    except ValueError:
        return {"insertions": 0, "deletions": 0}


def _failure(reason: str, cited_sha: str | None, uri: str) -> dict[str, Any]:
    return {
        "ok": False,
        "pinned": True,
        "uri": uri,
        "status": "cited_unavailable",
        "reason": reason,
        "cited_sha": cited_sha,
        "tip_sha": None,
        "changed": None,
    }


def _emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json or not payload.get("ok"):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        if payload["pinned"]:
            print(f"{payload['status']}: {payload['uri']}")
            print(f"cited {payload.get('cited_sha')} ({payload.get('cited_blob')})")
            print(f"tip {payload.get('tip_sha') or 'unavailable'} ({payload.get('tip_blob')})")
        else:
            print(f"floating: {payload['uri']}")
            print(f"tip {payload.get('tip_sha') or 'unavailable'} ({payload.get('tip_blob')})")
        if payload.get("text") is not None:
            print(payload["text"], end="" if payload["text"].endswith("\n") else "\n")
        if payload.get("diff"):
            print(payload["diff"], end="" if payload["diff"].endswith("\n") else "\n")
        for key in ("text_error", "diff_error"):
            if payload.get(key):
                print(payload[key], file=sys.stderr)
    return 0 if payload.get("ok") else 2


def show(uri: str, start: str | None, as_json: bool, include_text: bool, include_diff: bool) -> int:
    try:
        pointer = parse_pointer(uri)
    except MalformedPinError:
        return _emit(_failure("malformed_pin", None, uri), as_json)
    except IdentityError:
        return _emit(_failure("malformed_pin", None, uri), as_json)
    if not pointer.commit:
        return _show_floating(uri, pointer, start, as_json, include_text)

    project = find_project_root(Path(start).resolve() if start else Path.cwd())
    try:
        row, mount, store = _store(project, pointer.atlas_id)
    except MeshFileError:
        row, mount, store = None, None, None
    if not row or store is None or not store.is_dir():
        return _emit(_failure("store_not_mounted", pointer.commit, uri), as_json)
    location = _repo_and_store_path(store)
    if location is None:
        return _emit(_failure("store_not_mounted", pointer.commit, uri), as_json)
    repo, prefix = location
    safe_path = join_under(store, pointer.in_store)
    if safe_path is None:
        return _emit(_failure("path_not_in_commit", pointer.commit, uri), as_json)
    cited_path = _repo_path(prefix, pointer.in_store)
    cited_sha = pointer.commit
    if not _commit_exists(repo, cited_sha):
        reason = "shallow_clone" if _shallow(repo) else "commit_missing"
        return _emit(_failure(reason, cited_sha, uri), as_json)
    cited_blob, cited_path_exists, cited_kind = _blob_info(repo, cited_sha, cited_path)
    if cited_blob is None:
        reason = (
            "shallow_clone"
            if _shallow(repo)
            else "purged"
            if cited_path_exists and cited_kind is None
            else "path_not_in_commit"
        )
        return _emit(_failure(reason, cited_sha, uri), as_json)

    tip_sha, tip_ref = _tip(repo, row)
    tip_path = cited_path
    renamed_to = None
    tip_blob: str | None = None
    tip_path_exists = False
    tip_kind: str | None = None
    if tip_sha:
        tip_blob, tip_path_exists, tip_kind = _blob_info(repo, tip_sha, tip_path)
    if tip_sha and not tip_path_exists:
        renamed_repo_path = _rename_to(repo, cited_sha, tip_sha, cited_path)
        if renamed_repo_path and (not prefix or renamed_repo_path.startswith(prefix)):
            renamed_to = renamed_repo_path[len(prefix):] if prefix else renamed_repo_path
            tip_path = renamed_repo_path
            tip_blob, tip_path_exists, tip_kind = _blob_info(repo, tip_sha, tip_path)
    deleted = bool(tip_sha and (not tip_path_exists or (tip_path_exists and tip_kind not in (None, "blob"))))
    changed = (
        (cited_blob != tip_blob) if tip_blob or deleted else None
    ) if tip_sha else None
    reachable: bool | None = None
    commits_since: int | None = None
    diff_stat = {"insertions": 0, "deletions": 0}
    status = "tip_unavailable"
    if tip_sha:
        status = (
            "tip_unavailable"
            if tip_path_exists and tip_kind is None
            else "deleted"
            if deleted
            else "renamed"
            if renamed_to
            else "changed"
            if changed
            else "unchanged"
        )
        code, _, _ = _git(repo, "merge-base", "--is-ancestor", cited_sha, tip_sha)
        reachable = code == 0 if code in (0, 1) else None
        code, count, _ = _git(repo, "rev-list", "--count", f"{cited_sha}..{tip_sha}")
        if code == 0:
            try:
                commits_since = int(count)
            except ValueError:
                commits_since = None
        if tip_blob or deleted:
            diff_stat = _diff_stats(repo, cited_sha, tip_sha, cited_path, tip_path)

    payload: dict[str, Any] = {
        "ok": True,
        "pinned": True,
        "uri": uri,
        "atlas_id": pointer.atlas_id,
        "path": pointer.in_store,
        "fragment": pointer.fragment,
        "cited_sha": cited_sha,
        "cited_blob": cited_blob,
        "tip_ref": tip_ref,
        "tip_sha": tip_sha,
        "tip_path": (
            tip_path[len(prefix):] if prefix else tip_path
        ) if tip_sha and tip_blob else None,
        "tip_blob": tip_blob,
        "status": status,
        "changed": changed,
        "renamed_to": renamed_to,
        "deleted": deleted,
        "diff_stat": diff_stat,
        "commits_since": commits_since,
        "cited_reachable_from_tip": reachable,
    }
    if include_text:
        code, content, truncated = _git_capped(repo, "cat-file", "blob", cited_blob)
        if code == 0:
            payload["text"] = _limited(content, truncated)
        else:
            payload["text_error"] = "unable to read cited blob from the local Git object database"
    if include_diff and tip_sha:
        code, output, truncated = _git_capped(
            repo,
            "diff",
            "--no-ext-diff",
            "--no-color",
            "--no-renames",
            "--unified=3",
            f"{cited_sha}:{cited_path}",
            f"{tip_sha}:{tip_path}",
        )
        if code == 0:
            payload["diff"] = _limited(output, truncated)
        else:
            payload["diff_error"] = "unable to produce the path-scoped diff from local Git objects"
    return _emit(payload, as_json)


def _limited(content: bytes | str, truncated: bool = False) -> str:
    data = content.encode("utf-8") if isinstance(content, str) else content
    truncated = truncated or len(data) > TEXT_LIMIT
    if truncated:
        marker = "\n[truncated at 262144 bytes]\n"
        limit = TEXT_LIMIT - len(marker.encode("ascii"))
        return data[:limit].decode("utf-8", errors="replace") + marker
    return data.decode("utf-8", errors="replace")


def _show_floating(
    uri: str, pointer: Any, start: str | None, as_json: bool, include_text: bool
) -> int:
    project = find_project_root(Path(start).resolve() if start else Path.cwd())
    try:
        row, _mount, store = _store(project, pointer.atlas_id)
    except MeshFileError:
        row, store = None, None
    if not row or store is None or not store.is_dir():
        return _emit({
            "ok": False, "pinned": False, "uri": uri, "atlas_id": pointer.atlas_id,
            "path": pointer.in_store, "fragment": pointer.fragment, "status": "floating",
            "reason": "store_not_mounted", "changed": None,
        }, as_json)
    location = _repo_and_store_path(store)
    if location is None:
        return _emit({
            "ok": False, "pinned": False, "uri": uri, "atlas_id": pointer.atlas_id,
            "path": pointer.in_store, "fragment": pointer.fragment, "status": "floating",
            "reason": "store_not_mounted", "changed": None,
        }, as_json)
    repo, prefix = location
    tip_sha, tip_ref = _tip(repo, row)
    tip_path = _repo_path(prefix, pointer.in_store)
    tip_blob = (
        _blob(repo, tip_sha, tip_path)
        if tip_sha and join_under(store, pointer.in_store) is not None
        else None
    )
    payload: dict[str, Any] = {
        "ok": True, "pinned": False, "uri": uri, "atlas_id": pointer.atlas_id,
        "path": pointer.in_store, "fragment": pointer.fragment, "cited_sha": None,
        "cited_blob": None, "tip_ref": tip_ref, "tip_sha": tip_sha,
        "tip_path": pointer.in_store if tip_blob else None, "tip_blob": tip_blob,
        "status": "floating", "changed": None, "renamed_to": None, "deleted": False,
        "diff_stat": None, "commits_since": None, "cited_reachable_from_tip": None,
    }
    if include_text and tip_blob:
        code, content, truncated = _git_capped(repo, "cat-file", "blob", tip_blob)
        if code == 0:
            payload["text"] = _limited(content, truncated)
        else:
            payload["text_error"] = "unable to read floating target blob from local Git objects"
    return _emit(payload, as_json)


def pin(pointer_or_path: str, start: str | None, as_json: bool) -> int:
    base = Path(start).resolve() if start else Path.cwd().resolve()
    project = find_project_root(base)
    if pointer_or_path.startswith("atlas://"):
        try:
            pointer = parse_pointer(pointer_or_path)
        except IdentityError as exc:
            return _pin_error(str(exc), as_json)
        if pointer.commit:
            return _pin_error("link pin requires a floating URI or a store-relative path", as_json)
        atlas_id, in_store, fragment = pointer.atlas_id, pointer.in_store, pointer.fragment
        selected_row = None
        selected_store = None
    else:
        repo = git_root(base)
        if repo is None:
            return _pin_error("no git repository", as_json)
        try:
            doc = load(project)
        except MeshFileError as exc:
            return _pin_error(str(exc), as_json)
        candidates: list[tuple[int, str, Path]] = []
        for row in doc.get("stores") or []:
            aid = str(row.get("id") or "")
            try:
                _row, _mount, store = _store(project, aid)
            except MeshFileError:
                continue
            if store is None:
                continue
            candidate = join_under(store, pointer_or_path)
            if candidate is None:
                continue
            try:
                candidate.resolve().relative_to(store.resolve())
            except (OSError, ValueError):
                continue
            if candidate.is_file():
                candidates.append((len(store.resolve().parts), aid, store))
        if not candidates:
            if not has_contract_file(repo):
                return _pin_error("path is not inside a mounted store", as_json)
            remote_code, remote, _ = _git(repo, "remote", "get-url", "origin")
            if remote_code != 0:
                return _pin_error("current store has no origin from which to derive its atlas id", as_json)
            try:
                atlas_id = parse_pointer(str(remote)).atlas_id
            except IdentityError as exc:
                return _pin_error(f"cannot derive current store atlas id: {exc}", as_json)
            selected_row = {"ref": ""}
            selected_store = repo
        else:
            _depth, atlas_id, selected_store = max(candidates, key=lambda item: item[0])
            selected_row = None
        in_store = Path(pointer_or_path).as_posix()
        fragment = ""
    if selected_row is not None:
        row, store = selected_row, selected_store
    else:
        try:
            row, _mount, store = _store(project, atlas_id)
        except MeshFileError as exc:
            return _pin_error(str(exc), as_json)
    if not row or store is None:
        return _pin_error("store_not_mounted", as_json)
    safe_path = join_under(store, in_store)
    if safe_path is None or not safe_path.is_file():
        return _pin_error("path_not_found", as_json)
    location = _repo_and_store_path(store)
    if location is None:
        return _pin_error("store_not_mounted", as_json)
    repo, prefix = location
    tip_sha, _ref = _tip(repo, row)
    if not tip_sha:
        return _pin_error("tip_unavailable", as_json)
    tip_path = _repo_path(prefix, in_store)
    if not _blob(repo, tip_sha, tip_path):
        return _pin_error("path_not_in_tip", as_json)
    uri = f"atlas://{atlas_id}/{in_store}@{tip_sha}" + (f"#{fragment}" if fragment else "")
    payload = {"ok": True, "uri": uri, "atlas_id": atlas_id, "path": in_store, "commit": tip_sha}
    print(json.dumps(payload, indent=2) if as_json else uri)
    return 0


def _pin_error(message: str, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": message}))
    else:
        print(f"atlas link pin: {message}", file=sys.stderr)
    return 2


@click.group("link")
def link_group() -> None:
    """Inspect pinned links and create new pins from mounted store tips."""


@link_group.command("show")
@click.argument("uri")
@click.option("--cwd", "start", default=None, help="project directory")
@click.option("--show", "include_text", is_flag=True, help="include cited text (capped at 256 KiB)")
@click.option("--diff", "include_diff", is_flag=True, help="include a path-scoped diff (capped at 256 KiB)")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def show_cmd(uri: str, start: str | None, include_text: bool, include_diff: bool, as_json: bool) -> None:
    """Show cited context and change impact for a pinned URI."""
    raise SystemExit(show(uri, start, as_json, include_text, include_diff))


@link_group.command("pin")
@click.argument("pointer_or_path")
@click.option("--cwd", "start", default=None, help="project directory")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def pin_cmd(pointer_or_path: str, start: str | None, as_json: bool) -> None:
    """Pin a floating URI or mounted store path to its current tip."""
    raise SystemExit(pin(pointer_or_path, start, as_json))
