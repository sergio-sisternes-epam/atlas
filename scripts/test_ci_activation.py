#!/usr/bin/env python3
"""Contract tests for the Atlas CI activation path and GitHub adapters."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from release_readiness import manifest_version, read_surface, CI_SURFACES


ROOT = Path(__file__).resolve().parents[1]
COPY = ROOT / "references/ci/github-actions.compile.yml"
CALLER = ROOT / "references/ci/github-actions.caller.yml"
REUSABLE = ROOT / ".github/workflows/atlas-compile.yml"
PATH_CI = ROOT / "references/paths/ci.md"
SCENARIO = ROOT / "references/scenarios/ci-activation-adversarial-v1.yaml"
CI_REQUIREMENTS = ROOT / "scripts/requirements-ci.txt"
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"
RELEASE_WORKFLOW = ROOT / ".github/workflows/release.yml"


class CiActivationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.copy = COPY.read_text(encoding="utf-8")
        cls.caller = CALLER.read_text(encoding="utf-8")
        cls.reusable = REUSABLE.read_text(encoding="utf-8")
        cls.path_ci = PATH_CI.read_text(encoding="utf-8")
        cls.scenario = SCENARIO.read_text(encoding="utf-8")
        cls.ci_requirements = CI_REQUIREMENTS.read_text(encoding="utf-8")
        cls.ci_workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        cls.release_workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        cls.version = manifest_version()
        cls.ci_ref_version = read_surface(CI_SURFACES[0])

    def test_path_and_router_are_distinct_from_compile_path(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        registry = re.findall(r"^\| \*\*([a-z0-9-]+)\*\* \|", skill, flags=re.M)
        operational = registry[registry.index("recall"):registry.index("help")]
        insert_at = operational.index("ci") + 1
        operational = operational[:insert_at] + ["memory-migrate"] + operational[insert_at:]
        self.assertIn("ci", operational)
        for path_id in ("memory-migrate", "history", "version-hint", "prune"):
            self.assertIn(path_id, operational)
        self.assertIn("path: " + " | ".join(operational), skill)
        self.assertIn("`path: compile` is the agent-session", self.path_ci)

    def test_version_is_consistent(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        manifest = (ROOT / "apm.yml").read_text(encoding="utf-8")
        self.assertIn(f"version: {self.version}", skill)
        self.assertIn(f"version: {self.version}", manifest)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/atlas.py"), "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(f"atlas, version {self.version}", result.stdout.strip())

    def test_gate_is_unfocused(self) -> None:
        compile_gate = re.compile(
            r'atlas\.py"?\s+compile\s+(?:\\\s*)?'
            r'--root\s+"?\$ROOT"?\s+--json\b'
        )
        for workflow in (self.copy, self.reusable):
            self.assertRegex(workflow, compile_gate)
            self.assertNotIn("--path", workflow)
            self.assertNotIn("--type", workflow)

    def test_exit_one_warns_and_exit_two_fails(self) -> None:
        for workflow in (self.copy, self.reusable):
            self.assertIn('if [ "$status" -ge 2 ]', workflow)
            self.assertIn('if [ "$status" -eq 1 ]', workflow)
            self.assertNotIn("continue-on-error", workflow)
            self.assertIn("python3 -m json.tool atlas-compile.json", workflow)

    def test_missing_schema_fails_closed(self) -> None:
        for workflow in (self.copy, self.reusable):
            self.assertIn('if [ -f "$ROOT/SCHEMA.json" ]; then', workflow)
            self.assertIn('if [ -f "$ROOT/CONTRACT.json" ]; then', workflow)
            self.assertIn('if [ "$count" -ne 1 ]; then', workflow)
            self.assertIn(
                "Atlas root must contain exactly one of SCHEMA.json or CONTRACT.json",
                workflow,
            )
            self.assertIn("exit 2", workflow)

    def test_cli_is_acquired_outside_workspace(self) -> None:
        for workflow in (self.copy, self.reusable):
            self.assertIn('$RUNNER_TEMP/atlas-cli.', workflow)
            self.assertNotIn("$GITHUB_WORKSPACE", workflow)

    def test_cli_downloads_use_configured_token(self) -> None:
        token_env = (
            "ATLAS_TOKEN: ${{ secrets.ATLAS_CLI_TOKEN || github.token }}"
        )
        auth_header = '--header "Authorization: Bearer $ATLAS_TOKEN"'
        for workflow in (self.copy, self.reusable):
            self.assertIn(token_env, workflow)
            self.assertEqual(2, workflow.count(auth_header))

    def test_cli_dependencies_are_exactly_locked(self) -> None:
        requirements = self.ci_requirements.splitlines()
        self.assertTrue(requirements)
        for requirement in requirements:
            self.assertRegex(requirement, r"^[A-Za-z0-9_.-]+==[^\s]+$")
        self.assertTrue(any(line.startswith("click==") for line in requirements))
        self.assertTrue(
            any(line.startswith("jsonschema==") for line in requirements)
        )
        for workflow in (self.copy, self.reusable):
            self.assertIn("scripts/requirements-ci.txt", workflow)
            self.assertNotIn(
                'pip install -r "$ATLAS_CLI/scripts/requirements.txt"',
                workflow,
            )

    def test_cli_archive_ref_is_encoded_and_temp_file_is_unique(self) -> None:
        for workflow in (self.copy, self.reusable):
            self.assertIn(
                'urllib.parse.quote(os.environ["ATLAS_REF"], safe="")', workflow
            )
            self.assertIn(
                '"https://api.github.com/repos/$ATLAS_REPO/tarball/$archive_ref"',
                workflow,
            )
            self.assertIn(
                'archive="$(mktemp "$RUNNER_TEMP/atlas-cli.XXXXXX")"', workflow
            )
            self.assertNotIn(
                'archive="$RUNNER_TEMP/atlas-cli.tar.gz"', workflow
            )

    def test_cli_default_ref_is_not_a_floating_branch(self) -> None:
        floating_env_ref = re.compile(
            r"^\s*ATLAS_REF:\s*(?:main|master)\s*$", re.MULTILINE
        )
        floating_input_default = re.compile(
            r"^\s*default:\s*(?:main|master)\s*$", re.MULTILINE
        )
        for workflow in (self.copy, self.reusable):
            self.assertIn(
                "ATLAS_REF must be a tag or 40-character commit SHA", workflow
            )
        self.assertNotRegex(self.copy, floating_env_ref)
        self.assertNotRegex(self.reusable, floating_input_default)

    def test_cli_ref_normalizes_tags_and_rejects_other_qualified_refs(self) -> None:
        for workflow in (self.copy, self.reusable):
            self.assertIn(
                'ATLAS_REF="${ATLAS_REF#refs/tags/}"', workflow
            )
            self.assertIn("refs/*)", workflow)

    def test_third_party_actions_are_sha_pinned(self) -> None:
        external_use = re.compile(r"^\s*uses:\s+(?!\./)(\S+)", re.MULTILINE)
        sha_pinned = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
        for workflow in (self.copy, self.reusable):
            refs = external_use.findall(workflow)
            self.assertTrue(refs)
            for ref in refs:
                self.assertRegex(ref, sha_pinned)

    def test_reusable_and_caller_have_separate_triggers(self) -> None:
        self.assertIn("workflow_call:", self.reusable)
        self.assertNotIn("  pull_request:", self.reusable)
        self.assertNotIn("  push:", self.reusable)
        self.assertIn("  pull_request:", self.caller)
        self.assertIn("  push:", self.caller)
        self.assertIn(f"@v{self.ci_ref_version}", self.caller)

    def test_ci_exercises_repository_release_gates(self) -> None:
        self.assertIn("workflow_dispatch:", self.ci_workflow)
        self.assertIn("python3 scripts/run_tests.py", self.ci_workflow)
        self.assertIn("python3 scripts/release_readiness.py", self.ci_workflow)
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository",
            self.ci_workflow,
        )
        self.assertIn("name: Scan committed APM primitives", self.ci_workflow)
        self.assertIn("apm audit --no-policy --no-drift", self.ci_workflow)
        self.assertNotIn("apm install --frozen", self.ci_workflow)
        self.assertEqual(
            2,
            self.ci_workflow.count('apm-version: "0.30.0"'),
        )
        self.assertIn(
            "apm marketplace add sergio-sisternes-epam/atlas-marketplace --name atlas",
            self.ci_workflow,
        )
        self.assertEqual(
            2,
            self.ci_workflow.count(
                "apm marketplace add sergio-sisternes-epam/atlas-marketplace --name atlas"
            ),
        )
        self.assertEqual(
            2,
            self.ci_workflow.count(
                "github.event.pull_request.head.repo.full_name == github.repository"
            ),
        )
        self.assertEqual(
            2,
            self.ci_workflow.count(
                "github.event_name == 'workflow_dispatch' &&\n"
                "       github.ref == 'refs/heads/main'"
            ),
        )
        self.assertIn(
            "apm audit --ci --no-policy --no-fail-fast\n",
            self.ci_workflow,
        )
        self.assertIn("name: Release readiness decision", self.ci_workflow)
        self.assertIn('if [ "$REF_NAME" != main ]', self.ci_workflow)

    def test_ci_readiness_records_pr_validated_or_blocked(self) -> None:
        self.assertRegex(
            self.ci_workflow,
            r"name: Release readiness decision\n(?:.*\n){1,12}\s+if: always\(\)\n",
        )
        self.assertNotIn(
            "if: always() && github.event_name != 'pull_request'",
            self.ci_workflow,
        )
        self.assertIn('if [ "$EVENT_NAME" = pull_request ]; then', self.ci_workflow)
        self.assertIn(
            'echo "release_readiness_decision=pr-validated"',
            self.ci_workflow,
        )
        self.assertIn('if [ "$TEST_RESULT" != success ] ||', self.ci_workflow)
        self.assertIn('[ "$PACKAGE_RESULT" != success ] ||', self.ci_workflow)
        self.assertIn('[ "$CONSUMER_RESULT" != success ]; then', self.ci_workflow)
        self.assertIn(
            'echo "release_readiness_decision=blocked"',
            self.ci_workflow,
        )

    def test_ci_test_job_fetches_full_history_and_tags_for_pre_tag_check(self) -> None:
        self.assertIn(
            "    steps:\n"
            "      - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5\n"
            "        with:\n"
            "          fetch-depth: 0\n"
            "      - uses: actions/setup-python",
            self.ci_workflow,
        )

    def test_ci_test_job_runs_pre_tag_check_and_exports_tag_ready(self) -> None:
        self.assertIn(
            "    outputs:\n"
            "      tag_ready: ${{ steps.pre_tag.outputs.tag_ready }}\n",
            self.ci_workflow,
        )
        self.assertIn(
            "        id: pre_tag\n"
            "        run: |\n"
            "          if python3 scripts/release_readiness.py --pre-tag; then\n"
            '            echo "tag_ready=true" >> "$GITHUB_OUTPUT"\n'
            "          else\n"
            '            echo "tag_ready=false" >> "$GITHUB_OUTPUT"\n',
            self.ci_workflow,
        )
        step = workflow_step(
            CI_WORKFLOW, "test", "Check tag readiness (CI refs equal package version)"
        )
        self.assertEqual("pre_tag", step.get("id"))
        self.assertNotIn("continue-on-error", step)

    def test_ci_readiness_gates_ready_to_tag_on_tag_ready(self) -> None:
        self.assertIn(
            "TAG_READY: ${{ needs.test.outputs.tag_ready }}", self.ci_workflow
        )
        self.assertIn(
            '           if [ "$TAG_READY" != true ]; then\n'
            '             echo "pre_tag_decision=blocked: pre-tag check failed" |\n'
            '               tee -a "$GITHUB_STEP_SUMMARY"\n'
            '             if [ "$EVENT_NAME" = workflow_dispatch ]; then\n'
            "               exit 1\n"
            "             fi\n"
            "             exit 0\n"
            "           fi\n"
            '           echo "pre_tag_decision=ready to tag" | tee -a "$GITHUB_STEP_SUMMARY"\n',
            self.ci_workflow,
        )
        self.assertEqual(1, self.ci_workflow.count("pre_tag_decision=ready to tag"))

    def test_release_verifies_metadata_before_publishing(self) -> None:
        self.assertIn("python3 scripts/release_readiness.py", self.release_workflow)
        self.assertIn('--tag "$GITHUB_REF_NAME"', self.release_workflow)
        self.assertIn("release_validation_decision=ready to publish", self.release_workflow)

    def test_release_creation_is_idempotent(self) -> None:
        self.assertIn(
            'if state="$(gh release view "$TAG" --json tagName,isDraft,isPrerelease '
            "--jq '\"\\(.isDraft) \\(.isPrerelease)\"' 2>/dev/null)\"; then",
            self.release_workflow,
        )
        self.assertIn('read -r draft existing <<<"$state"', self.release_workflow)
        self.assertIn(
            '            if [ "$draft" = true ]; then\n'
            '              echo "::error title=Release is a draft::GitHub release $TAG '
            "exists but is still a draft; publish it (or delete it) and re-run this "
            'workflow."\n'
            "              exit 1\n"
            "            fi\n",
            self.release_workflow,
        )
        self.assertIn('if [ "$existing" != "$PRERELEASE" ]; then', self.release_workflow)
        self.assertIn('gh release create "$TAG" "${ARGS[@]}"', self.release_workflow)

    def test_adversarial_contract_names_all_approved_smokes(self) -> None:
        for smoke in (
            "not-path-compile",
            "focused-compile-forbidden-in-ci",
            "exit-2-fails-exit-1-does-not",
            "missing-schema-not-success",
            "floating-main-pin-forbidden",
            "dependency-closure-locked",
            "skill-pytest-not-mount-ci",
            "cli-not-in-workspace-root",
        ):
            self.assertIn(f"id: {smoke}", self.scenario)


def workflow_step(workflow: Path, job: str, name: str) -> dict:
    document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    matches = [
        step for step in document["jobs"][job]["steps"] if step.get("name") == name
    ]
    if len(matches) != 1:
        raise AssertionError(f"{workflow.name}: expected one {job} step named {name!r}")
    return matches[0]


class WorkflowStepExecutionTests(unittest.TestCase):
    """Execute workflow `run:` scripts under bash with stubbed tools on PATH."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="atlas-workflow-step-")
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.bin = self.temp / "bin"
        self.bin.mkdir()
        self.log = self.temp / "calls.log"
        self.log.touch()
        self.summary = self.temp / "summary.md"
        self.summary.touch()
        self.output = self.temp / "output.txt"
        self.output.touch()

    def _stub(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(
            "#!/usr/bin/env bash\n"
            f'{{ printf %s {name}; printf "\\t%s" "$@"; printf "\\n"; }} >> "$STUB_LOG"\n'
            + body,
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _real_python3(self) -> None:
        path = self.bin / "python3"
        path.write_text(
            f'#!/usr/bin/env bash\nexec {shlex.quote(sys.executable)} "$@"\n',
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _run(self, step: dict, env: dict[str, str]) -> subprocess.CompletedProcess:
        script = step["run"]
        self.assertNotIn("${{", script, "run script must take inputs from env only")
        script_path = self.temp / "step.sh"
        script_path.write_text(script, encoding="utf-8")
        full_env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "STUB_LOG": str(self.log),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "GITHUB_OUTPUT": str(self.output),
            **env,
        }
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-e", str(script_path)],
            cwd=ROOT,
            env=full_env,
            capture_output=True,
            text=True,
        )

    def _calls(self, tool: str) -> list[list[str]]:
        return [
            line.split("\t")[1:]
            for line in self.log.read_text(encoding="utf-8").splitlines()
            if line.split("\t", 1)[0] == tool
        ]

    # --- CI pre-tag check (test job) ---------------------------------------

    def _run_pre_tag(self, exit_code: int) -> subprocess.CompletedProcess:
        self._stub("python3", f"exit {exit_code}\n")
        step = workflow_step(CI_WORKFLOW, "test", "Check tag readiness (CI refs equal package version)")
        self.assertEqual("pre_tag", step.get("id"))
        result = self._run(step, {})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [["scripts/release_readiness.py", "--pre-tag"]], self._calls("python3")
        )
        return result

    def test_pre_tag_pass_sets_tag_ready_true(self) -> None:
        result = self._run_pre_tag(0)
        self.assertEqual("tag_ready=true\n", self.output.read_text(encoding="utf-8"))
        self.assertNotIn("::warning", result.stdout)

    def test_pre_tag_block_sets_tag_ready_false_and_warns(self) -> None:
        result = self._run_pre_tag(1)
        self.assertEqual("tag_ready=false\n", self.output.read_text(encoding="utf-8"))
        self.assertIn("::warning title=Tagging blocked::", result.stdout)
        self.assertIn("release_readiness.py --pre-tag failed", result.stdout)
        self.assertNotIn("every CI ref", result.stdout)

    # --- CI readiness decision ---------------------------------------------

    def _run_decision(
        self, event: str, tag_ready: str, ref_type: str = "branch", ref_name: str = "main"
    ) -> tuple[subprocess.CompletedProcess, str]:
        step = workflow_step(CI_WORKFLOW, "readiness", "Record candidate decision")
        self.assertEqual("${{ needs.test.outputs.tag_ready }}", step["env"]["TAG_READY"])
        result = self._run(
            step,
            {
                "TEST_RESULT": "success",
                "PACKAGE_RESULT": "success",
                "CONSUMER_RESULT": "success",
                "EVENT_NAME": event,
                "REF_TYPE": ref_type,
                "REF_NAME": ref_name,
                "TAG_READY": tag_ready,
                "CANDIDATE_REVISION": "0" * 40,
            },
        )
        return result, self.summary.read_text(encoding="utf-8")

    def test_decision_ready_to_tag_only_when_tag_ready(self) -> None:
        for event in ("push", "workflow_dispatch"):
            with self.subTest(event=event):
                self.summary.write_text("", encoding="utf-8")
                result, summary = self._run_decision(event, "true")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("pre_tag_decision=ready to tag\n", summary)
                self.assertNotIn("pre_tag_decision=blocked", summary)

    def test_decision_blocked_pre_tag_fails_only_on_manual_dispatch(self) -> None:
        for event, tag_ready, expected_exit in (
            ("push", "false", 0),
            ("push", "", 0),
            ("workflow_dispatch", "false", 1),
            ("workflow_dispatch", "", 1),
        ):
            with self.subTest(event=event, tag_ready=tag_ready):
                self.summary.write_text("", encoding="utf-8")
                result, summary = self._run_decision(event, tag_ready)
                self.assertEqual(expected_exit, result.returncode, result.stderr)
                self.assertIn(
                    "pre_tag_decision=blocked: pre-tag check failed\n",
                    summary,
                )
                self.assertNotIn("pre_tag_decision=ready to tag", summary)

    def test_decision_tag_and_pr_ignore_tag_ready(self) -> None:
        result, summary = self._run_decision("push", "false", "tag", "v9.9.9")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("release_validation_decision=ready to publish\n", summary)
        self.assertNotIn("pre_tag_decision", summary)

        self.summary.write_text("", encoding="utf-8")
        result, summary = self._run_decision("pull_request", "false", ref_name="55/merge")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("release_readiness_decision=pr-validated\n", summary)
        self.assertNotIn("pre_tag_decision", summary)

    # --- Release workflow: idempotent GitHub release creation --------------

    def _run_release(
        self,
        tag: str,
        existing: str | None,
        draft: bool | str = False,
        expected_exit: int = 0,
    ) -> subprocess.CompletedProcess:
        self._real_python3()
        self._stub(
            "gh",
            'if [ "$1 $2" = "release view" ]; then\n'
            '  if [ -n "${STUB_EXISTING_PRERELEASE:-}" ]; then\n'
            '    echo "${STUB_EXISTING_DRAFT:-false} $STUB_EXISTING_PRERELEASE"\n'
            "    exit 0\n"
            "  fi\n"
            '  echo "release not found" >&2\n'
            "  exit 1\n"
            "fi\n"
            '[ "$1 $2" = "release create" ] && exit 0\n'
            'echo "unexpected gh call: $*" >&2\n'
            "exit 64\n",
        )
        step = workflow_step(RELEASE_WORKFLOW, "release", "Create GitHub release")
        env = {"GITHUB_REF_NAME": tag, "GH_TOKEN": "stub-token"}
        if existing is not None:
            env["STUB_EXISTING_PRERELEASE"] = existing
            if isinstance(draft, str):
                env["STUB_EXISTING_DRAFT"] = draft
            else:
                env["STUB_EXISTING_DRAFT"] = "true" if draft else "false"
        result = self._run(step, env)
        self.assertEqual(expected_exit, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            [[
                "release", "view", tag,
                "--json", "tagName,isDraft,isPrerelease",
                "--jq", '"\\(.isDraft) \\(.isPrerelease)"',
            ]],
            [call for call in self._calls("gh") if call[:2] == ["release", "view"]],
        )
        return result

    def _creates(self) -> list[list[str]]:
        return [call for call in self._calls("gh") if call[:2] == ["release", "create"]]

    def test_release_absent_is_created_with_prerelease_flag(self) -> None:
        tag = "v0.13.0-beta.13"
        result = self._run_release(tag, None)
        self.assertEqual(
            [["release", "create", tag, "--verify-tag", "--generate-notes",
              "--title", tag, "--prerelease"]],
            self._creates(),
        )
        self.assertIn(f"prerelease=true (tag {tag})", result.stdout)
        self.assertNotIn("::warning", result.stdout)

    def test_release_absent_stable_tag_is_created_without_prerelease_flag(self) -> None:
        tag = "v1.0.0"
        result = self._run_release(tag, None)
        self.assertEqual(
            [["release", "create", tag, "--verify-tag", "--generate-notes", "--title", tag]],
            self._creates(),
        )
        self.assertIn(f"prerelease=false (tag {tag})", result.stdout)

    def test_existing_matching_release_is_left_unchanged(self) -> None:
        for tag, existing in (("v0.13.0-beta.13", "true"), ("v1.0.0", "false")):
            with self.subTest(tag=tag):
                self.log.write_text("", encoding="utf-8")
                result = self._run_release(tag, existing)
                self.assertEqual([], self._creates())
                self.assertIn("::notice title=Release already exists::", result.stdout)
                self.assertIn(
                    f"existing_prerelease={existing} expected_prerelease={existing}",
                    result.stdout,
                )
                self.assertNotIn("::warning", result.stdout)

    def test_existing_release_with_different_prerelease_flag_warns(self) -> None:
        for tag, existing, expected in (
            ("v0.13.0-beta.13", "false", "true"),
            ("v1.0.0", "true", "false"),
        ):
            with self.subTest(tag=tag):
                self.log.write_text("", encoding="utf-8")
                result = self._run_release(tag, existing)
                self.assertEqual([], self._creates())
                self.assertIn("::notice title=Release already exists::", result.stdout)
                self.assertIn(
                    f"::warning title=Prerelease flag mismatch::Existing release {tag} "
                    f"has prerelease={existing}; this workflow would have set "
                    f"prerelease={expected}.",
                    result.stdout,
                )

    def test_existing_draft_release_fails_closed(self) -> None:
        for tag, existing in (("v0.13.0-beta.13", "true"), ("v1.0.0", "false")):
            with self.subTest(tag=tag):
                self.log.write_text("", encoding="utf-8")
                result = self._run_release(tag, existing, draft=True, expected_exit=1)
                self.assertIn(
                    f"::error title=Release is a draft::GitHub release {tag} exists "
                    "but is still a draft; publish it (or delete it) and re-run this "
                    "workflow.",
                    result.stdout,
                )
                self.assertEqual([], self._creates())
                self.assertEqual(
                    [],
                    [call for call in self._calls("gh") if call[:2] != ["release", "view"]],
                )
                self.assertNotIn("::notice title=Release already exists::", result.stdout)

    def test_existing_release_with_unreadable_draft_state_fails_closed(self) -> None:
        for tag, existing in (("v0.13.0-beta.13", "true"), ("v1.0.0", "false")):
            with self.subTest(tag=tag):
                self.log.write_text("", encoding="utf-8")
                result = self._run_release(tag, existing, draft="null", expected_exit=1)
                self.assertIn(
                    f"::error title=Unknown release state::Could not read the draft "
                    f"state of GitHub release {tag} (got 'null {existing}').",
                    result.stdout,
                )
                self.assertEqual([], self._creates())
                self.assertEqual(
                    [],
                    [call for call in self._calls("gh") if call[:2] != ["release", "view"]],
                )
                self.assertNotIn("::notice title=Release already exists::", result.stdout)


if __name__ == "__main__":
    unittest.main()
