#!/usr/bin/env python3
"""Storage strategy regressions. Run: python3 scripts/test_store_strategy.py"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_cli.commands.mount import _persistable_ref, _relative_origin
from atlas_cli.core.gitops import (
    create_orphan_empty_branch,
    ensure_shared_branch,
    origin_url,
    push_history,
    redact_remote_userinfo,
    remove_submodule,
    run_git,
    tree_has_schema,
)
from atlas_cli.core.github_driver import (
    protect_atlas_branch,
    ruleset_payload,
    ruleset_targets_branch,
)
from atlas_cli.core.meshfile import (
    MeshFileError,
    effective_strategy,
    upsert,
    validate_doc,
)

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"


def run(
    args: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        env={**os.environ, **(env or {})},
    )


def git(
    args: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={**os.environ, **(env or {})} if env else None,
    )


def git_output(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def init_parent(path: Path, origin: str | None = None) -> None:
    path.mkdir()
    git(["init", "-q", "--initial-branch=main"], path)
    git(["config", "user.name", "Atlas Test"], path)
    git(["config", "user.email", "atlas@example.invalid"], path)
    (path / ".keep").write_text("consumer-main\n", encoding="utf-8")
    git(["add", ".keep"], path)
    git(["commit", "-q", "-m", "Parent"], path)
    if origin:
        git(["remote", "add", "origin", origin], path)


def local_remote_env(remote: Path, public_url: str) -> dict[str, str]:
    return {
        "GIT_ALLOW_PROTOCOL": "file",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.file://{remote}.insteadOf",
        "GIT_CONFIG_VALUE_0": public_url,
    }


def json_payload(result: subprocess.CompletedProcess[str]) -> tuple[dict, str]:
    try:
        return json.loads(result.stdout), ""
    except json.JSONDecodeError as error:
        detail = (
            f"invalid JSON ({error}); stdout={result.stdout!r}; "
            f"stderr={result.stderr!r}"
        )
        return {}, detail


def init_store_repo(path: Path, message: str = "store-root") -> None:
    path.mkdir()
    git(["init", "-q", "--initial-branch=main"], path)
    git(["config", "user.name", "Atlas Test"], path)
    git(["config", "user.email", "atlas@example.invalid"], path)
    (path / "SCHEMA.json").write_text("{}\n", encoding="utf-8")
    (path / "index.md").write_text("# store\n\nHello from dedicated store.\n", encoding="utf-8")
    git(["add", "SCHEMA.json", "index.md"], path)
    git(["commit", "-q", "-m", message], path)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-store-strategy-"))
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str) -> None:
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    try:
        missing = {"version": 1, "stores": [{"id": "github.com/example/store"}]}
        check(
            "missing-strategy-is-dedicated",
            not validate_doc(missing) and effective_strategy(missing["stores"][0]) == "dedicated",
            f"errs={validate_doc(missing)}",
        )

        bad = {
            "version": 1,
            "stores": [
                {
                    "id": "github.com/example/store",
                    "ref": "main",
                    "strategy": "shared",
                }
            ],
        }
        errs = validate_doc(bad)
        check(
            "no-infer-when-field-contradicts",
            any("strategy shared requires ref atlas" in e for e in errs),
            f"errs={errs}",
        )
        missing_ref = {
            "version": 1,
            "stores": [
                {
                    "id": "github.com/example/store",
                    "strategy": "shared",
                }
            ],
        }
        missing_ref_errs = validate_doc(missing_ref)
        check(
            "shared-requires-ref-atlas",
            any("strategy shared requires ref atlas" in e for e in missing_ref_errs),
            f"errs={missing_ref_errs}",
        )

        mesh_parent = tmp / "mesh-parent"
        init_parent(mesh_parent)
        raised = False
        try:
            upsert(
                mesh_parent,
                {
                    "id": "github.com/example/store",
                    "ref": "main",
                    "strategy": "shared",
                },
            )
        except MeshFileError:
            raised = True
        check("upsert-contradiction-fails-closed", raised, "expected MeshFileError")

        orphan = tmp / "orphan"
        init_parent(orphan)
        code, err = create_orphan_empty_branch(orphan, "atlas")
        tree = git_output(["ls-tree", "--name-only", "atlas"], orphan)
        main_tree = git_output(["ls-tree", "--name-only", "main"], orphan)
        check(
            "orphan-not-default-tree",
            code == 0
            and err == ""
            and tree == ""
            and ".keep" in main_tree,
            f"code={code} err={err!r} atlas={tree!r} main={main_tree!r}",
        )

        overlay = tmp / "overlay"
        init_parent(overlay)
        git(["branch", "atlas"], overlay)
        (overlay / "product.txt").write_text("nope\n", encoding="utf-8")
        git(["add", "product.txt"], overlay)
        git(["commit", "-q", "-m", "product on main"], overlay)
        git(["branch", "-f", "atlas"], overlay)
        code, status, err = ensure_shared_branch(overlay, "atlas")
        check(
            "no-overlay-product-branch",
            code == 2
            and status == ""
            and "not an Atlas root" in err
            and not tree_has_schema(overlay, "atlas"),
            f"code={code} status={status} err={err!r}",
        )

        payload = ruleset_payload()
        check(
            "bootstrap-before-ruleset-payload-targets-atlas",
            payload["conditions"]["ref_name"]["include"] == ["refs/heads/atlas"],
            f"payload={payload}",
        )
        check(
            "ruleset-targets-requested-branch-only",
            ruleset_targets_branch(payload, "atlas")
            and not ruleset_targets_branch(payload, "knowledge"),
            f"payload={payload}",
        )
        code, warn = protect_atlas_branch("git.example.com/org/repo")
        check(
            "self-hosted-warn-and-continue",
            code == 0 and "self-hosted" in warn,
            f"code={code} warn={warn!r}",
        )
        code, warn = protect_atlas_branch("git.example.com/org/repo", branch="knowledge")
        check(
            "protect-warning-uses-branch-arg",
            code == 0 and "knowledge" in warn,
            f"code={code} warn={warn!r}",
        )
        check(
            "relative-origin-bare-dotdot",
            _relative_origin("..") and _relative_origin("../") and not _relative_origin("atlas"),
            "expected '..' to count as a relative origin",
        )
        check(
            "mesh-ref-does-not-persist-head",
            _persistable_ref("HEAD", "atlas") == "atlas"
            and _persistable_ref("HEAD", "HEAD") == ""
            and _persistable_ref("main") == "main",
            "detached HEAD must not be written as a mesh ref",
        )
        leaked = "https://secret-token@github.com/example/consumer.git"
        check(
            "origin-url-strips-userinfo",
            redact_remote_userinfo(leaked) == "https://github.com/example/consumer.git",
            redact_remote_userinfo(leaked),
        )
        cred_parent = tmp / "cred-parent"
        init_parent(cred_parent, leaked)
        got_origin = origin_url(cred_parent)
        check(
            "origin-url-hides-embedded-token",
            "secret-token" not in got_origin and "github.com/example/consumer.git" in got_origin,
            got_origin,
        )
        fetch_src = tmp / "atlas-src"
        init_store_repo(fetch_src, "atlas-on-remote")
        git(["branch", "atlas"], fetch_src)
        fetch_bare = tmp / "atlas-src.git"
        git(["init", "-q", "--bare", "--initial-branch=main", str(fetch_bare)], tmp)
        git(["remote", "add", "origin", f"file://{fetch_bare}"], fetch_src)
        previous_allow = os.environ.get("GIT_ALLOW_PROTOCOL")
        os.environ["GIT_ALLOW_PROTOCOL"] = "file"
        try:
            git(["push", "-q", "origin", "main", "atlas"], fetch_src)
            no_origin = tmp / "no-origin-parent"
            init_parent(no_origin)
            code, status, err = ensure_shared_branch(
                no_origin,
                "atlas",
                f"file://{fetch_bare}",
            )
        finally:
            if previous_allow is None:
                os.environ.pop("GIT_ALLOW_PROTOCOL", None)
            else:
                os.environ["GIT_ALLOW_PROTOCOL"] = previous_allow
        check(
            "ensure-shared-branch-fetches-remote-url",
            code == 0 and status == "reused",
            f"code={code} status={status} err={err!r}",
        )

        consumer_url = "https://github.com/example/consumer.git"
        consumer_bare = tmp / "consumer.git"
        git(["init", "-q", "--bare", "--initial-branch=main", str(consumer_bare)], tmp)
        shared_parent = tmp / "shared-parent"
        init_parent(shared_parent, consumer_url)
        env = local_remote_env(consumer_bare, consumer_url)
        git(["push", "-q", "origin", "main"], shared_parent, env)
        result = run(
            ["store", "init", "--strategy", "shared", "--json", "--cwd", str(shared_parent)],
            shared_parent,
            env,
        )
        payload, parse_error = json_payload(result)
        dest = shared_parent / ".atlas/github.com/example/consumer"
        mesh = {}
        mesh_path = shared_parent / "atlas-mesh.json"
        if mesh_path.is_file():
            mesh = json.loads(mesh_path.read_text(encoding="utf-8"))
        row = (mesh.get("stores") or [{}])[0]
        atlas_files = ""
        if (dest / "SCHEMA.json").is_file():
            atlas_files = git_output(["ls-tree", "--name-only", "atlas"], dest)
        check(
            "shared-init-default-writes-strategy",
            result.returncode == 0
            and payload.get("strategy") == "shared"
            and row.get("strategy") == "shared"
            and row.get("ref") == "atlas"
            and (dest / "SCHEMA.json").is_file()
            and "SCHEMA.json" in atlas_files
            and ".keep" not in atlas_files,
            parse_error
            or f"exit={result.returncode} payload={payload} stderr={result.stderr!r} mesh={mesh}",
        )

        origin_first = tmp / "origin-first"
        init_parent(origin_first, consumer_url)
        result = run(
            [
                "store",
                "init",
                "--remote",
                "https://github.com/example/wrong.git",
                "--json",
                "--cwd",
                str(origin_first),
            ],
            origin_first,
            env,
        )
        payload, parse_error = json_payload(result)
        check(
            "shared-init-origin-before-remote",
            result.returncode == 0
            and payload.get("id") == "github.com/example/consumer"
            and payload.get("id") != "github.com/example/wrong",
            parse_error or f"exit={result.returncode} payload={payload} stderr={result.stderr!r}",
        )

        result = run(
            ["store", "init", "--strategy", "dedicated", "--json", "--cwd", str(shared_parent)],
            shared_parent,
        )
        payload, parse_error = json_payload(result)
        check(
            "no-create-host-repo",
            result.returncode == 2
            and "never creates" in payload.get("error", "")
            and "gh repo create" not in (result.stderr or "")
            and "gh repo create" not in (result.stdout or ""),
            parse_error or f"exit={result.returncode} payload={payload}",
        )

        store_url = "https://github.com/example/store.git"
        store_bare = tmp / "store.git"
        git(["init", "-q", "--bare", "--initial-branch=main", str(store_bare)], tmp)
        store_src = tmp / "store-src"
        init_store_repo(store_src, "store-root")
        git(["remote", "add", "origin", store_url], store_src)
        store_env = local_remote_env(store_bare, store_url)
        git(["push", "-q", "origin", "main"], store_src, store_env)

        rehost_parent = tmp / "rehost-parent"
        consumer2 = "https://github.com/example/rehost.git"
        consumer2_bare = tmp / "rehost.git"
        git(["init", "-q", "--bare", "--initial-branch=main", str(consumer2_bare)], tmp)
        init_parent(rehost_parent, consumer2)
        git(
            ["push", "-q", "origin", "main"],
            rehost_parent,
            local_remote_env(consumer2_bare, consumer2),
        )
        both_env = {
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": f"url.file://{store_bare}.insteadOf",
            "GIT_CONFIG_VALUE_0": store_url,
            "GIT_CONFIG_KEY_1": f"url.file://{consumer2_bare}.insteadOf",
            "GIT_CONFIG_VALUE_1": consumer2,
        }
        result = run(
            [
                "store",
                "init",
                "--strategy",
                "dedicated",
                "--remote",
                store_url,
                "--json",
                "--cwd",
                str(rehost_parent),
            ],
            rehost_parent,
            both_env,
        )
        payload, parse_error = json_payload(result)
        check(
            "dedicated-init-mounts-existing",
            result.returncode == 0 and payload.get("strategy") == "dedicated",
            parse_error or f"exit={result.returncode} payload={payload} stderr={result.stderr!r}",
        )

        old_root = rehost_parent / ".atlas/github.com/example/store"
        old_schema = (old_root / "SCHEMA.json").read_text(encoding="utf-8") if (old_root / "SCHEMA.json").is_file() else ""
        result = run(
            [
                "store",
                "rehost",
                "--destination-strategy",
                "shared",
                "--json",
                "--cwd",
                str(rehost_parent),
            ],
            rehost_parent,
            both_env,
        )
        payload, parse_error = json_payload(result)
        new_root = rehost_parent / ".atlas/github.com/example/rehost"
        mesh = {}
        if (rehost_parent / "atlas-mesh.json").is_file():
            mesh = json.loads((rehost_parent / "atlas-mesh.json").read_text(encoding="utf-8"))
        ids = [s.get("id") for s in mesh.get("stores") or []]
        log = ""
        if (new_root / ".git").exists() or (new_root / "SCHEMA.json").is_file():
            code, log, _ = run_git(["log", "--oneline"], cwd=new_root)
            log = log or ""
        dual = old_root.exists() and (old_root / "SCHEMA.json").is_file()
        check(
            "rehost-shared-preserves-history",
            result.returncode == 0
            and payload.get("strategy") == "shared"
            and "github.com/example/rehost" in ids
            and "store-root" in log,
            parse_error
            or f"exit={result.returncode} payload={payload} stderr={result.stderr!r} mesh={mesh} log={log!r}",
        )
        check(
            "no-dual-write",
            result.returncode == 0 and not dual,
            f"old root still present: {old_root} exists={old_root.exists()} schema={old_schema!r}",
        )

        result = run(
            [
                "store",
                "rehost",
                "--destination-strategy",
                "shared",
                "--json",
                "--cwd",
                str(rehost_parent),
            ],
            rehost_parent,
            both_env,
        )
        payload, parse_error = json_payload(result)
        check(
            "same-strategy-fails-closed",
            result.returncode == 2 and "both shared" in payload.get("error", ""),
            parse_error or f"exit={result.returncode} payload={payload}",
        )

        dest_url = "https://github.com/example/dedicated-dest.git"
        dest_bare = tmp / "dedicated-dest.git"
        git(["init", "-q", "--bare", "--initial-branch=main", str(dest_bare)], tmp)
        reverse_env = {
            **both_env,
            "GIT_CONFIG_COUNT": "3",
            "GIT_CONFIG_KEY_2": f"url.file://{dest_bare}.insteadOf",
            "GIT_CONFIG_VALUE_2": dest_url,
        }
        result = run(
            [
                "store",
                "rehost",
                "--destination-strategy",
                "dedicated",
                "--remote",
                dest_url,
                "--json",
                "--cwd",
                str(rehost_parent),
            ],
            rehost_parent,
            reverse_env,
        )
        payload, parse_error = json_payload(result)
        check(
            "rehost-dedicated-requires-existing-remote",
            result.returncode == 0 and payload.get("strategy") == "dedicated",
            parse_error or f"exit={result.returncode} payload={payload} stderr={result.stderr!r}",
        )

        json_parent = tmp / "json-parent"
        init_parent(json_parent)
        missing_url = "https://github.com/example/does-not-exist.git"
        result = run(
            [
                "store",
                "init",
                "--strategy",
                "dedicated",
                "--remote",
                missing_url,
                "--json",
                "--cwd",
                str(json_parent),
            ],
            json_parent,
            local_remote_env(tmp / "missing.git", missing_url),
        )
        payload, parse_error = json_payload(result)
        check(
            "store-json-keeps-json-on-mount-fail",
            result.returncode != 0
            and not parse_error
            and payload.get("ok") is False
            and "atlas mount:" not in (result.stdout or ""),
            parse_error or f"exit={result.returncode} payload={payload} stdout={result.stdout!r}",
        )

        code, err = remove_submodule(json_parent, json_parent / "no-such-submodule")
        check(
            "remove-missing-submodule-is-ok",
            code == 0,
            f"code={code} err={err!r}",
        )
        outside_rm = tmp / "outside-rm"
        outside_rm.mkdir()
        keep = outside_rm / "keep.txt"
        keep.write_text("keep\n", encoding="utf-8")
        code, err = remove_submodule(json_parent, outside_rm)
        check(
            "remove-submodule-rejects-escaped-path",
            code != 0 and keep.is_file() and "escapes" in (err or ""),
            f"code={code} err={err!r} exists={keep.is_file()}",
        )

        previous_allow = os.environ.get("GIT_ALLOW_PROTOCOL")
        os.environ["GIT_ALLOW_PROTOCOL"] = "file"
        try:
            code, err = push_history(
                shared_parent,
                f"file://{consumer_bare}",
                "atlas",
                source_ref="refs/heads/does-not-exist",
            )
        finally:
            if previous_allow is None:
                os.environ.pop("GIT_ALLOW_PROTOCOL", None)
            else:
                os.environ["GIT_ALLOW_PROTOCOL"] = previous_allow
        check(
            "push-history-bad-rev-is-not-unrelated",
            code != 0 and "unrelated" not in (err or "").lower(),
            f"code={code} err={err!r}",
        )

        escape_parent = tmp / "escape-parent"
        init_parent(escape_parent, consumer_url)
        outside = tmp / "outside-store"
        outside.mkdir()
        (outside / "SCHEMA.json").write_text("{}\n", encoding="utf-8")
        (escape_parent / "atlas-mesh.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "stores": [
                        {
                            "id": "github.com/example/store",
                            "path": "../outside-store",
                            "ref": "main",
                            "strategy": "dedicated",
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        result = run(
            [
                "store",
                "rehost",
                "--destination-strategy",
                "shared",
                "--json",
                "--cwd",
                str(escape_parent),
            ],
            escape_parent,
        )
        payload, parse_error = json_payload(result)
        check(
            "rehost-rejects-escaped-mesh-path",
            result.returncode != 0
            and "escapes" in payload.get("error", "")
            and outside.is_dir(),
            parse_error or f"exit={result.returncode} payload={payload}",
        )

        bad_ver = tmp / "bad-schema-version"
        bad_url = "https://github.com/example/bad-schema.git"
        bad_bare = tmp / "bad-schema.git"
        git(["init", "-q", "--bare", "--initial-branch=main", str(bad_bare)], tmp)
        init_parent(bad_ver, bad_url)
        bad_env = local_remote_env(bad_bare, bad_url)
        git(["push", "-q", "origin", "main"], bad_ver, bad_env)
        result = run(
            [
                "store",
                "init",
                "--schema-version",
                "9.9",
                "--json",
                "--cwd",
                str(bad_ver),
            ],
            bad_ver,
            bad_env,
        )
        payload, parse_error = json_payload(result)
        check(
            "store-init-json-on-silent-init-fail",
            result.returncode != 0
            and not parse_error
            and "unsupported" in payload.get("error", "").lower(),
            parse_error or f"exit={result.returncode} payload={payload} stderr={result.stderr!r}",
        )

        help_out = run(["migrate", "--help"], ROOT)
        check(
            "cli-migrate-stays-staging-import",
            help_out.returncode == 0
            and "staging" in (help_out.stdout or "").lower()
            and "destination-strategy" not in (help_out.stdout or ""),
            f"stdout={help_out.stdout!r}",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("FAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
