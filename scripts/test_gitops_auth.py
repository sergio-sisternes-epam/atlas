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

from atlas_cli.commands import mount
from atlas_cli.commands.mount import _explicit_git_token
from atlas_cli.core.auth import AuthResult
from atlas_cli.core import auth, gitops


TOKEN = "atlas-test-token"
HOST = "github.example"
TOKEN_CONFIG = (
    f"url.https://x-access-token:{TOKEN}@{HOST}/.insteadOf=https://{HOST}/"
)


class AuthHostScopeTests(unittest.TestCase):
    def test_github_com_accepts_generic_environment_tokens(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ATLAS_PAT": TOKEN,
                "GH_HOST": "enterprise.example",
                "GH_ENTERPRISE_TOKEN": "enterprise-token",
            },
            clear=True,
        ):
            result = auth.resolve_auth("github.com")

        self.assertEqual("token", result.backend)
        self.assertEqual(TOKEN, result.token)

    def test_github_enterprise_cloud_accepts_github_token(self) -> None:
        with patch.dict(
            os.environ,
            {"GITHUB_TOKEN": TOKEN},
            clear=True,
        ):
            result = auth.resolve_auth("tenant.ghe.com")

        self.assertEqual("token", result.backend)
        self.assertEqual(TOKEN, result.token)

    def test_ghes_accepts_enterprise_token_only_for_matching_gh_host(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GH_HOST": HOST.upper(),
                "GH_ENTERPRISE_TOKEN": TOKEN,
                "GH_TOKEN": "public-token",
            },
            clear=True,
        ):
            result = auth.resolve_auth(HOST)

        self.assertEqual("token", result.backend)
        self.assertEqual(TOKEN, result.token)

    def test_arbitrary_host_rejects_all_unmatched_environment_tokens(self) -> None:
        attacker = "attacker.example"
        with (
            patch.dict(
                os.environ,
                {
                    "ATLAS_PAT": "atlas-pat",
                    "GH_TOKEN": "gh-token",
                    "GITHUB_TOKEN": "github-token",
                    "GITHUB_APM_PAT": "apm-token",
                    "GH_ENTERPRISE_TOKEN": "enterprise-token",
                    "GITHUB_ENTERPRISE_TOKEN": "github-enterprise-token",
                    "GH_HOST": HOST,
                },
                clear=True,
            ),
            patch.object(auth, "gh_token", return_value=None),
            patch.object(auth, "interactive_login", return_value=None),
        ):
            result = auth.resolve_auth(attacker)

        self.assertEqual("none", result.backend)
        self.assertIsNone(result.token)
        self.assertEqual(attacker, result.host)
        self.assertIn(f"no credentials for {attacker}", result.error or "")

    def test_github_lookups_scrub_environment_tokens(self) -> None:
        with (
            patch.object(auth.shutil, "which", return_value="/fake/gh"),
            patch.object(auth, "_run", return_value=(0, TOKEN)) as run,
        ):
            self.assertEqual(TOKEN, auth.gh_token(HOST))

        self.assertEqual(
            (["gh", "auth", "token", "--hostname", HOST],),
            run.call_args.args,
        )
        self.assertEqual(auth.TOKEN_ENV_KEYS, run.call_args.kwargs["drop_keys"])


class GitAuthArgumentTests(unittest.TestCase):
    def test_explicit_token_precedes_gh(self) -> None:
        with patch.object(gitops.shutil, "which", return_value="/fake/gh"):
            args, drop = gitops._auth_args(TOKEN, host=HOST)

        self.assertEqual(
            ["-c", "credential.helper=", "-c", TOKEN_CONFIG],
            args,
        )
        self.assertEqual(auth.TOKEN_ENV_KEYS, drop)
        self.assertNotIn("credential.helper=!gh auth git-credential", args)

    def test_gh_backend_uses_helper_with_scrubbed_environment(self) -> None:
        args, drop = gitops._auth_args(None, host=HOST, backend="gh")

        self.assertEqual(
            [
                "-c",
                "credential.helper=",
                "-c",
                "credential.helper=!gh auth git-credential",
            ],
            args,
        )
        self.assertEqual(auth.TOKEN_ENV_KEYS, drop)

    def test_gh_backend_token_uses_helper_instead_of_token_rewrite(self) -> None:
        auth_result = AuthResult(
            backend="gh",
            host=HOST,
            token="gh-cli-token",
            ssh=False,
        )

        args, drop = gitops._auth_args(
            _explicit_git_token(auth_result),
            host=HOST,
            backend=auth_result.backend,
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
        self.assertEqual(auth.TOKEN_ENV_KEYS, drop)

    def test_env_token_backend_passes_explicit_token_to_git(self) -> None:
        auth_result = AuthResult(
            backend="token",
            host=HOST,
            token=TOKEN,
            ssh=False,
        )

        self.assertEqual(TOKEN, _explicit_git_token(auth_result))

    def test_anonymous_https_disables_credentials(self) -> None:
        self.assertEqual(
            (
                ["-c", "credential.helper="],
                auth.TOKEN_ENV_KEYS,
            ),
            gitops._auth_args(None, host=HOST),
        )

    def test_ssh_does_not_change_git_authentication(self) -> None:
        self.assertEqual(
            ([], ()),
            gitops._auth_args(None, host=HOST, backend="ssh"),
        )

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
                    with patch.object(
                        gitops,
                        "run_git",
                        return_value=(128, "", f"fatal: rejected {TOKEN}"),
                    ) as run_git:
                        code, error = invoke()

                    command = run_git.call_args.args[0]
                    self.assertEqual(128, code)
                    self.assertEqual("fatal: rejected ***", error)
                    self.assertIn(TOKEN_CONFIG, command)
                    self.assertNotIn(
                        "credential.helper=!gh auth git-credential", command
                    )
                    self.assertEqual(
                        auth.TOKEN_ENV_KEYS,
                        run_git.call_args.kwargs["drop_keys"],
                    )

    def test_shared_anonymous_operations_never_forward_credentials(self) -> None:
        attacker = "attacker.example"
        with tempfile.TemporaryDirectory(prefix="atlas-gitops-anon-") as raw_tmp:
            tmp = Path(raw_tmp)
            parent = tmp / "parent"
            parent.mkdir()
            calls = (
                lambda: gitops.clone(
                    f"https://{attacker}/example/store.git",
                    tmp / "clone",
                    "main",
                ),
                lambda: gitops.submodule_add(
                    parent,
                    f"https://{attacker}/example/store.git",
                    parent / "store",
                    "main",
                ),
                lambda: gitops.submodule_init(
                    parent,
                    parent / "store",
                    host=attacker,
                ),
            )

            for invoke in calls:
                with (
                    self.subTest(operation=invoke),
                    patch.object(
                        gitops,
                        "run_git",
                        return_value=(128, "", "fatal: authentication failed"),
                    ) as run_git,
                ):
                    code, _error = invoke()

                command = run_git.call_args.args[0]
                self.assertEqual(128, code)
                self.assertIn("credential.helper=", command)
                self.assertNotIn(
                    "credential.helper=!gh auth git-credential",
                    command,
                )
                self.assertFalse(any(TOKEN in arg for arg in command))
                self.assertEqual(
                    auth.TOKEN_ENV_KEYS,
                    run_git.call_args.kwargs["drop_keys"],
                )


class MountAuthDispatchTests(unittest.TestCase):
    def test_arbitrary_host_mount_dispatches_anonymous_git(self) -> None:
        attacker = "attacker.example"
        with tempfile.TemporaryDirectory(prefix="atlas-mount-auth-") as raw_tmp:
            project = Path(raw_tmp)
            no_auth = AuthResult(
                backend="none",
                host=attacker,
                token=None,
                ssh=False,
                error=f"no credentials for {attacker}",
            )
            with (
                patch.object(mount, "has_git", return_value=True),
                patch.object(mount, "git_root", return_value=project),
                patch.object(mount, "lookup", return_value=None),
                patch.object(mount, "resolve_auth", return_value=no_auth),
                patch.object(mount, "is_gitlink", return_value=False),
                patch.object(mount, "submodule_add", return_value=(128, "failed")) as add,
            ):
                code = mount.run(
                    f"{attacker}/org/repo",
                    ref="main",
                    target=None,
                    ssh=False,
                    start=str(project),
                    as_json=True,
                )

        self.assertEqual(2, code)
        self.assertIsNone(add.call_args.kwargs["token"])
        self.assertEqual("none", add.call_args.kwargs["backend"])


class GitAuthProcessBoundaryTests(unittest.TestCase):
    def test_arbitrary_host_operations_have_no_credential_material(self) -> None:
        attacker = "attacker.example"
        environment_tokens = {
            key: f"secret-{index}"
            for index, key in enumerate(auth.TOKEN_ENV_KEYS)
        }
        with tempfile.TemporaryDirectory(prefix="atlas-gitops-untrusted-") as raw_tmp:
            tmp = Path(raw_tmp)
            parent = tmp / "parent"
            bin_dir = tmp / "bin"
            parent.mkdir()
            bin_dir.mkdir()
            capture = tmp / "capture.json"
            fake_git = bin_dir / "git"
            fake_git.write_text(
                f"""#!{sys.executable}
import json
import os
import sys
from pathlib import Path

Path(os.environ["ATLAS_TEST_CAPTURE"]).write_text(
    json.dumps(
        {{
            "args": sys.argv[1:],
            "credential_keys": [
                key for key in {auth.TOKEN_ENV_KEYS!r} if key in os.environ
            ],
        }}
    ),
    encoding="utf-8",
)
print("fatal: anonymous access denied", file=sys.stderr)
raise SystemExit(128)
""",
                encoding="utf-8",
            )
            executable = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
            fake_git.chmod(executable)

            operations = (
                (
                    "clone",
                    lambda: gitops.clone(
                        f"https://{attacker}/org/repo.git",
                        tmp / "clone",
                        "main",
                    ),
                ),
                (
                    "submodule add",
                    lambda: gitops.submodule_add(
                        parent,
                        f"https://{attacker}/org/repo.git",
                        parent / "store",
                        "main",
                    ),
                ),
                (
                    "submodule update",
                    lambda: gitops.submodule_init(
                        parent,
                        parent / "store",
                        host=attacker,
                    ),
                ),
            )
            env = {
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "ATLAS_TEST_CAPTURE": str(capture),
                **environment_tokens,
            }

            for operation, invoke in operations:
                with self.subTest(operation=operation), patch.dict(os.environ, env):
                    code, error = invoke()

                observed = json.loads(capture.read_text(encoding="utf-8"))
                self.assertEqual(128, code)
                self.assertEqual("fatal: anonymous access denied", error)
                self.assertEqual([], observed["credential_keys"])
                self.assertIn("credential.helper=", observed["args"])
                self.assertNotIn(
                    "credential.helper=!gh auth git-credential",
                    observed["args"],
                )
                for value in environment_tokens.values():
                    self.assertFalse(
                        any(value in argument for argument in observed["args"])
                    )
            self.assertFalse((tmp / ".gitconfig").exists())

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
            "enterprise_token_present": "GH_ENTERPRISE_TOKEN" in os.environ,
            "atlas_token_present": "ATLAS_PAT" in os.environ,
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
                "GH_ENTERPRISE_TOKEN": "stale-enterprise-token",
                "ATLAS_PAT": "stale-atlas-token",
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
            self.assertFalse(observed["enterprise_token_present"])
            self.assertFalse(observed["atlas_token_present"])
            self.assertFalse((destination / ".git").exists())
            self.assertFalse((tmp / ".gitconfig").exists())


if __name__ == "__main__":
    unittest.main()
