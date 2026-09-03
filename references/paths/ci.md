---
name: atlas/paths/ci
description: Assess, install, or repair CI for an Atlas mount. Defines the canonical platform-neutral gate and the GitHub Actions default.
path_id: ci
---

# Path: ci

## When

Use this path when a repository containing an Atlas `SCHEMA.json` needs a CI
merge gate, when an existing setup must be assessed, or when an Atlas compile
workflow is partial or incorrect.

This path targets the **Atlas mount repository**, not the Atlas skill package's
Python tests or release pipeline.

## Layers (do not merge)

| Name | Layer | Job |
|------|-------|-----|
| `path: ci` | B17 protocol | Discover, assess, install or repair, and emit a receipt |
| Platform adapter | GitHub Actions by default | Trigger, acquire the pinned CLI, invoke the gate, retain evidence |
| `atlas compile` | CLI tool | Run the unfocused store gate |

`path: compile` is the agent-session compile discipline. `path: ci` is the
institutional merge-gate setup. Do not merge them.

## Enter

```text
skill: atlas
skill_path: <atlas skill root>
mode: run
subject: <mount repository>
path: ci
path_module: references/paths/ci.md
intent: assess | install | repair
root: <SCHEMA.json parent>
```

Read this file before acting. Missing card or unloaded module means incomplete
Enter.

## Canonical model (v1.1)

Adapters on any CI platform conform to these clauses.

### MUST

| ID | Clause |
|----|--------|
| M1 | The subject is a git repository containing `SCHEMA.json`. Dedicated stores use the git root; embedded stores declare the schema parent. |
| M2 | Root discovery fails closed. Missing or ambiguous `SCHEMA.json` is not success. Tool-acquisition trees are excluded. |
| M3 | The merge gate runs unfocused `atlas compile --root <root> --json`, without `--path` or `--type`. |
| M4 | Compile exit `0` passes. Exit `1` passes with warnings retained as evidence. Exit `2` fails. Any other abnormal failure fails. |
| M5 | The Atlas CLI comes from an immutable tag or commit SHA, never `main` or `master`. |
| M6 | CLI acquisition happens before compile. Acquisition failure fails the job rather than skipping the gate. |
| M7 | The gate runs on pull requests and pushes that include the default branch. |
| M8 | The compile job has read-only mount permissions. |
| M9 | Compile JSON is printed in logs and retained as an artifact even when the gate fails. |
| M10 | One job compiles one Atlas root. Mesh consolidation remains inside compile. |

### MAY

- Run manually or on a schedule.
- Fail on warnings as an explicitly stricter local policy.
- Add formatters or linters outside the canonical Atlas gate.
- Use a reusable workflow or a local copied workflow.
- Use a read token solely to acquire a private Atlas CLI source.

### MUST NOT

| ID | Forbidden |
|----|-----------|
| X1 | Focused `--path` or `--type` compile as the merge gate. |
| X2 | Success when the intended `SCHEMA.json` is missing. |
| X3 | Substitute Atlas skill unit tests or package publishing for mount compile. |
| X4 | Swallow compile exit `2`, including `continue-on-error` on the compile step. |
| X5 | Use a floating CLI branch. |
| X6 | Require secrets unrelated to private CLI acquisition. |
| X7 | Turn this path into tag-based product release automation. |
| X8 | Acquire the CLI inside the mount tree being compiled. |

## Conformance grades

| Grade | Meaning |
|-------|---------|
| `missing` | No job invokes Atlas compile on a `SCHEMA.json` root. |
| `partial` | Compile runs, but a MUST is weak, such as missing evidence, one missing trigger, or floating third-party Action tags. |
| `incorrect` | A MUST NOT is present, the wrong repository/root is targeted, or critical exit is swallowed. |
| `correct` | Every MUST holds and no MUST NOT is present. |

## Checklist

Mark every item pass, fail, or not applicable.

### A. Identity

- [ ] A1. Repository or declared subpath contains `SCHEMA.json`.
- [ ] A2. Target is the mount store, not Atlas skill tests.
- [ ] A3. Dedicated store uses root `.`; embedded store uses the schema parent.
- [ ] A4. Activation-card or adapter root matches A3.

### B. Gate

- [ ] B1. Job runs `atlas compile` (or its `validate` alias) with `--json`.
- [ ] B2. Merge gate has no `--path` or `--type`.
- [ ] B3. Exit `2` fails.
- [ ] B4. Exit `1` succeeds and retains warning JSON.
- [ ] B5. Exit `0` succeeds.
- [ ] B6. Staging-empty is left to compile rather than reimplemented.

### C. CLI

- [ ] C1. CLI source is the Atlas skill's `scripts/atlas.py`.
- [ ] C2. CLI ref is a tag or SHA, not `main` or `master`.
- [ ] C3. CLI dependencies are installed.
- [ ] C4. Acquisition failure fails the job.
- [ ] C5. Private source has a documented read token, or source is public.
- [ ] C6. CLI acquisition directory is outside the compiled mount.

### D. Triggers and privilege

- [ ] D1. Pull requests trigger the gate.
- [ ] D2. Pushes including the default branch trigger the gate.
- [ ] D3. Compile does not request write permission.
- [ ] D4. No unrelated secret is required.

### E. Evidence and hygiene

- [ ] E1. Compile JSON is printed in the log.
- [ ] E2. Compile JSON is uploaded even on failure.
- [ ] E3. Inputs and refs are passed as environment data, not interpolated into shell.
- [ ] E4. Third-party GitHub Actions are pinned to commit SHAs; floating major tags grade partial. The Atlas reusable workflow and CLI follow M5 and may use a release tag or commit SHA.

### F. Anti-patterns

Any hit makes the setup `incorrect`.

- [ ] F1. No `continue-on-error: true` on compile.
- [ ] F2. No remap of exit `2` or abnormal failure to success.
- [ ] F3. No PR-diff path as the only compile scope.
- [ ] F4. No Atlas-skill pytest job masquerading as mount compile.
- [ ] F5. No success path when `SCHEMA.json` is missing.
- [ ] F6. CLI is not acquired inside the compiled root.

## GitHub Actions default

The skill ships two equivalent adapters:

- `references/ci/github-actions.caller.yml` is preferred when the mount can
  call the Atlas reusable workflow.
- `references/ci/github-actions.compile.yml` is the self-contained fallback.

The reusable implementation is `.github/workflows/atlas-compile.yml` in the
Atlas skill and has `workflow_call` only. It is not Atlas-skill product CI.

Both implementations:

- acquire the pinned CLI under `${RUNNER_TEMP}`, not `${GITHUB_WORKSPACE}`;
- require `<root>/SCHEMA.json`;
- run unfocused compile;
- validate and print the JSON;
- translate compile exit `1` to job success only after valid JSON exists;
- fail on exit `2` or abnormal execution;
- upload the JSON with `if: always()`;
- use SHA-pinned third-party GitHub Actions.

For a private Atlas skill repository, configure `ATLAS_CLI_TOKEN` with
read-only contents access. A public source can use `github.token`.

## Procedure

1. **Resolve mount and root.**
   - Use the supplied `root` when it contains `SCHEMA.json`.
   - Otherwise use `.` when `<git-root>/SCHEMA.json` exists.
   - Otherwise inspect the mount tree only. Exactly one `SCHEMA.json` selects
     its parent. Zero or multiple candidates fail closed.
   - Stop if the candidate is the Atlas skill package rather than a mount.
2. **Detect adapter.** A GitHub remote or `.github/` selects GitHub Actions.
   Unknown platforms are assess-only unless the user names an adapter.
3. **Assess.** Apply the checklist and report the grade plus failed IDs.
4. **For `assess`, stop** after the report and receipt.
5. **For `install` or `repair`:**
   - Prefer the thin reusable caller when cross-repository workflow access is
     configured.
   - Otherwise copy `references/ci/github-actions.compile.yml` to
     `<mount>/.github/workflows/atlas-compile.yml`.
   - Set the actual Atlas root and an immutable Atlas CLI ref.
   - Do not vendor the CLI or edit Atlas skill tests.
6. **Re-assess.** The result must be `correct`, or `partial` with every
   remaining failed ID named.
7. **Emit the receipt.**

## Exit receipt

```text
skill: atlas
skill_path: <atlas skill root>
subject: <mount repository>
path: ci
root: <SCHEMA.json parent>
intent: assess | install | repair
adapter: github-actions | github-actions-reusable | unknown | <id>
grade: missing | partial | incorrect | correct
failing_ids: <ids or none>
remember: no
compile: n/a
```

## Non-goals

- Running the mount pipeline from this path.
- Implementing `path: compile`.
- Atlas skill unit tests, publishing, or releases.
- Inventing an adapter for an unnamed platform.
- Changing Atlas compile exit semantics.
