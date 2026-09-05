#!/usr/bin/env python3
"""Focused Git authentication regressions. Run: python3 scripts/test_gitops_auth.py"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_cli.commands.mount import _explicit_git_token
from atlas_cli.core.auth import AuthResult
from atlas_cli.core import gitops


TOKEN = "atlas-test-token"
HOST = "github.example"
TOKEN_CONFIG = (
    f"url.https://x-access-token:{TOKEN}@{HOST}/.insteadOf=https://{HOST}/"
)


class GitAuthArgumentTests(unittest.TestCase):
    def test_explicit_token_precedes_gh(self) -> None:
        with patch.object(gitops.shutil, "which", return_value="/fake/gh"):
            args, drop = gitops._auth_args(TOKEN, host=HOST)

        self.assertEqual(
            ["-c", "credential.helper=", "-c", TOKEN_CONFIG],
            args,
        )
        self.assertEqual(("GH_TOKEN", "GITHUB_TOKEN"), drop)
        self.assertNotIn("credential.helper=!gh auth git-credential", args)

    def test_no_token_uses_gh_helper_and_preserves_environment(self) -> None:
        with patch.object(gitops.shutil, "which", return_value="/fake/gh"):
            args, drop = gitops._auth_args(None, host=HOST)

        self.assertEqual(
            [
                "-c",
                "credential.helper=",
                "-c",
                "credential.helper=!gh auth git-credential",
            ],
            args,
        )
        self.assertEqual((), drop)

    def test_gh_backend_token_uses_helper_instead_of_token_rewrite(self) -> None:
        auth = AuthResult(
            backend="gh",
            host=HOST,
            token="gh-cli-token",
            ssh=False,
        )

        with patch.object(gitops.shutil, "which", return_value="/fake/gh"):
            args, drop = gitops._auth_args(
                _explicit_git_token(auth),
                host=HOST,
            )

        self.assertEqual(
            [
                "-c",
                "credential.helper=",
                "-c",
                "credential.helper=!gh auth git-credential",
            ],
            args,
        )
        self.assertEqual((), drop)

    def test_env_token_backend_passes_explicit_token_to_git(self) -> None:
        auth = AuthResult(
            backend="token",
            host=HOST,
            token=TOKEN,
            ssh=False,
        )

        self.assertEqual(TOKEN, _explicit_git_token(auth))

    def test_no_token_or_gh_adds_no_auth_configuration(self) -> None:
        with patch.object(gitops.shutil, "which", return_value=None):
            self.assertEqual(([], ()), gitops._auth_args(None, host=HOST))

    def test_shared_operations_use_token_configuration_and_redact_errors(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas-gitops-auth-") as raw_tmp:
            tmp = Path(raw_tmp)
            parent = tmp / "parent"
            parent.mkdir()
            calls = (
                (
                    "clone",
                    lambda: gitops.clone(
                        f"https://{HOST}/example/store.git",
                        tmp / "clone",
                        "main",
                        token=TOKEN,
                    ),
                ),
                (
                    "submodule add",
                    lambda: gitops.submodule_add(
                        parent,
                        f"https://{HOST}/example/store.git",
                        parent / "store",
                        "main",
                        token=TOKEN,
                    ),
                ),
                (
                    "submodule update",
                    lambda: gitops.submodule_init(
                        parent,
                        parent / "store",
                        token=TOKEN,
                        host=HOST,
                    ),
                ),
            )

            for operation, invoke in calls:
                with self.subTest(operation=operation):
                    with (
                        patch.object(
                            gitops.shutil, "which", return_value="/fake/gh"
                        ),
                        patch.object(
                            gitops,
                            "run_git",
                            return_value=(128, "", f"fatal: rejected {TOKEN}"),
                        ) as run_git,
                    ):
                        code, error = invoke()

                    command = run_git.call_args.args[0]
                    self.assertEqual(128, code)
                    self.assertEqual("fatal: rejected ***", error)
                    self.assertIn(TOKEN_CONFIG, command)
                    self.assertNotIn(
                        "credential.helper=!gh auth git-credential", command
                    )
                    self.assertEqual(
                        ("GH_TOKEN", "GITHUB_TOKEN"),
                        run_git.call_args.kwargs["drop_keys"],
                    )


class GitAuthProcessBoundaryTests(unittest.TestCase):
    def test_token_auth_is_process_local_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas-gitops-process-") as raw_tmp:
            tmp = Path(raw_tmp)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            capture = tmp / "capture.json"
            fake_git = bin_dir / "git"
            fake_gh = bin_dir / "gh"
            fake_git.write_text(
                f"""#!{sys.executable}
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
Path(os.environ["ATLAS_TEST_CAPTURE"]).write_text(
    json.dumps(
        {{
            "token_config": {TOKEN_CONFIG!r} in args,
            "gh_helper": "credential.helper=!gh auth git-credential" in args,
            "gh_token_present": "GH_TOKEN" in os.environ,
            "github_token_present": "GITHUB_TOKEN" in os.environ,
        }}
    ),
    encoding="utf-8",
)
print("fatal: rejected {TOKEN}", file=sys.stderr)
raise SystemExit(128)
""",
                encoding="utf-8",
            )
            fake_gh.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            executable = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
            fake_git.chmod(executable)
            fake_gh.chmod(executable)

            env = {
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "ATLAS_TEST_CAPTURE": str(capture),
                "GH_TOKEN": "stale-gh-token",
                "GITHUB_TOKEN": "stale-github-token",
            }
            destination = tmp / "checkout"
            with patch.dict(os.environ, env):
                code, error = gitops.clone(
                    f"https://{HOST}/example/private-store.git",
                    destination,
                    "main",
                    token=TOKEN,
                )

            observed = json.loads(capture.read_text(encoding="utf-8"))
            self.assertEqual(128, code)
            self.assertEqual("fatal: rejected ***", error)
            self.assertTrue(observed["token_config"])
            self.assertFalse(observed["gh_helper"])
            self.assertFalse(observed["gh_token_present"])
            self.assertFalse(observed["github_token_present"])
            self.assertFalse((destination / ".git").exists())
            self.assertFalse((tmp / ".gitconfig").exists())


if __name__ == "__main__":
    unittest.main()
