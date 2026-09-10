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

from atlas_cli.core.gitops import (
    create_orphan_empty_branch,
    ensure_shared_branch,
    run_git,
    tree_has_schema,
)
from atlas_cli.core.github_driver import protect_atlas_branch, ruleset_payload
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
        code, warn = protect_atlas_branch("git.example.com/org/repo")
        check(
            "self-hosted-warn-and-continue",
            code == 0 and "self-hosted" in warn,
            f"code={code} warn={warn!r}",
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
