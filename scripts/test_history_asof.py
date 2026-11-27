#!/usr/bin/env python3
"""Git history and fail-closed repository-as-of recall tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"


def git(args: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def commit(repo: Path, body: str, day: int) -> str:
    (repo / "facts.md").write_text(
        f"---\ntype: document\ntitle: Project alpha\n---\n\n{body}\n",
        encoding="utf-8",
    )
    git(["add", "facts.md"], repo)
    date = f"2020-01-{day:02d}T12:00:00+00:00"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Atlas Test",
        "GIT_AUTHOR_EMAIL": "atlas-test@example.invalid",
        "GIT_COMMITTER_NAME": "Atlas Test",
        "GIT_COMMITTER_EMAIL": "atlas-test@example.invalid",
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
    }
    git(["commit", "-m", f"version {day}"], repo, env=env)
    return git(["rev-parse", "HEAD"], repo)


def dated_commit(repo: Path, message: str, day: int) -> str:
    date = f"2020-02-{day:02d}T12:00:00+00:00"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Atlas Test",
        "GIT_AUTHOR_EMAIL": "atlas-test@example.invalid",
        "GIT_COMMITTER_NAME": "Atlas Test",
        "GIT_COMMITTER_EMAIL": "atlas-test@example.invalid",
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
    }
    git(["add", "-A"], repo)
    git(["commit", "-m", message], repo, env=env)
    return git(["rev-parse", "HEAD"], repo)


def main() -> int:
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}".rstrip())
        if not ok:
            failures.append(name)

    with tempfile.TemporaryDirectory(prefix="atlas-history-asof-") as raw_temp:
        temp = Path(raw_temp)
        repo = temp / "repo"
        repo.mkdir()
        git(["init", "-q"], repo)
        git(["config", "user.name", "Atlas Test"], repo)
        git(["config", "user.email", "atlas-test@example.invalid"], repo)
        first = commit(repo, "Project alpha was blue.", 1)
        commit(repo, "Project alpha became green.", 3)
        tip = commit(repo, "Project alpha is red.", 5)

        history_result = cli("history", "facts.md", "--root", str(repo), "--json")
        history_payload = json.loads(history_result.stdout)
        versions = history_payload.get("versions") or []
        check(
            "history-three-newest-first",
            history_result.returncode == 0
            and len(versions) == 3
            and versions[0]["commit"] == tip
            and versions[-1]["commit"] == first
            and all(version["availability"] == "available" for version in versions),
            str([version.get("commit") for version in versions]),
        )
        check(
            "history-has-recorded-time-and-blob",
            all(version.get("recorded_time") and version.get("blob") for version in versions),
        )

        default_before = cli(
            "recall", "run", "Project alpha", "--root", str(repo), "--engine", "grep", "--json"
        )
        asof = cli(
            "recall", "run", "Project alpha", "--root", str(repo), "--engine", "grep",
            "--as-of", "2020-01-02", "--json",
        )
        asof_payload = json.loads(asof.stdout)
        historical_hits = asof_payload.get("hits") or []
        check(
            "as-of-returns-older-text-and-provenance",
            asof.returncode == 0
            and len(historical_hits) == 1
            and "blue" in historical_hits[0].get("snippet", "").lower()
            and historical_hits[0].get("provenance", {}).get("commit") == first
            and historical_hits[0].get("provenance", {}).get("label")
            == "repository version at that date",
            asof.stdout[:300],
        )

        before = cli(
            "recall", "run", "Project alpha", "--root", str(repo), "--engine", "grep",
            "--as-of", "2019-12-31", "--json",
        )
        before_payload = json.loads(before.stdout)
        unavailable = before_payload.get("unavailable") or []
        check(
            "date-before-first-version-unavailable",
            before.returncode == 2
            and before_payload.get("ok") is False
            and len(unavailable) == 1
            and unavailable[0].get("reason_code") == "no_commit_at_date"
            and "red" not in before.stdout.lower(),
            before.stdout[:300],
        )

        default_after = cli(
            "recall", "run", "Project alpha", "--root", str(repo), "--engine", "grep", "--json"
        )
        check(
            "default-recall-output-unchanged",
            default_before.returncode == default_after.returncode == 0
            and default_before.stdout == default_after.stdout
            and "provenance" not in default_after.stdout,
        )

        rename_repo = temp / "rename"
        rename_repo.mkdir()
        git(["init", "-q"], rename_repo)
        git(["config", "user.name", "Atlas Test"], rename_repo)
        git(["config", "user.email", "atlas-test@example.invalid"], rename_repo)
        (rename_repo / "old.md").write_text("Renamed page contents.\n", encoding="utf-8")
        dated_commit(rename_repo, "add page", 1)
        git(["mv", "old.md", "new.md"], rename_repo)
        dated_commit(rename_repo, "rename page", 2)
        renamed_history = cli(
            "history", "new.md", "--root", str(rename_repo), "--json"
        )
        renamed_versions = (json.loads(renamed_history.stdout).get("versions") or [])
        check(
            "history-follows-simple-rename",
            renamed_history.returncode == 0
            and len(renamed_versions) == 2
            and len({version.get("blob") for version in renamed_versions}) == 1,
            str(renamed_versions),
        )

        absent_repo = temp / "path-absent"
        absent_repo.mkdir()
        git(["init", "-q"], absent_repo)
        git(["config", "user.name", "Atlas Test"], absent_repo)
        git(["config", "user.email", "atlas-test@example.invalid"], absent_repo)
        (absent_repo / "other.md").write_text("Unrelated page.\n", encoding="utf-8")
        dated_commit(absent_repo, "first repository commit", 1)
        (absent_repo / "facts.md").write_text(
            "Project alpha is a current-only tip.\n", encoding="utf-8"
        )
        dated_commit(absent_repo, "add matching page", 3)
        path_absent = cli(
            "recall", "run", "Project alpha", "--root", str(absent_repo), "--engine", "grep",
            "--as-of", "2020-02-02", "--json",
        )
        absent_payload = json.loads(path_absent.stdout)
        absent_items = absent_payload.get("unavailable") or []
        check(
            "path-absent-at-date-does-not-fall-forward",
            path_absent.returncode == 2
            and absent_payload.get("ok") is False
            and len(absent_items) == 1
            and absent_items[0].get("reason_code") == "path_absent"
            and not absent_payload.get("hits")
            and "current-only" not in path_absent.stdout,
            path_absent.stdout[:300],
        )

        partial_repo = temp / "partial"
        partial_repo.mkdir()
        git(["init", "-q"], partial_repo)
        git(["config", "user.name", "Atlas Test"], partial_repo)
        git(["config", "user.email", "atlas-test@example.invalid"], partial_repo)
        (partial_repo / "other.md").write_text("Project alpha existed before.\n", encoding="utf-8")
        dated_commit(partial_repo, "historical match", 1)
        (partial_repo / "facts.md").write_text("Project alpha is a current-only tip.\n", encoding="utf-8")
        dated_commit(partial_repo, "current match", 3)
        partial = cli(
            "recall", "run", "Project alpha", "--root", str(partial_repo), "--engine", "grep",
            "--as-of", "2020-02-02", "--json",
        )
        partial_payload = json.loads(partial.stdout)
        check(
            "partial-unavailability-remains-successful",
            partial.returncode == 0
            and partial_payload.get("ok") is True
            and len(partial_payload.get("hits") or []) == 1
            and len(partial_payload.get("unavailable") or []) == 1
            and "current-only" not in partial.stdout,
            partial.stdout[:300],
        )

        shallow = temp / "shallow"
        env = os.environ.copy()
        env.pop("GH_TOKEN", None)
        env.pop("GITHUB_TOKEN", None)
        cloned = subprocess.run(
            ["git", "clone", "--quiet", "--depth=1", f"file://{repo}", str(shallow)],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        shallow_result = cli(
            "recall", "run", "Project alpha", "--root", str(shallow), "--engine", "grep",
            "--as-of", "2020-01-02", "--json",
        )
        shallow_payload = json.loads(shallow_result.stdout)
        shallow_unavailable = shallow_payload.get("unavailable") or []
        check(
            "shallow-history-unavailable-without-tip-text",
            cloned.returncode == 0
            and shallow_result.returncode == 2
            and shallow_payload.get("ok") is False
            and len(shallow_unavailable) == 1
            and shallow_unavailable[0].get("reason_code") == "shallow_history"
            and not shallow_payload.get("hits")
            and "red" not in shallow_result.stdout.lower(),
            shallow_result.stdout[:300] or cloned.stderr[:200],
        )

    if failures:
        print(f"\nFailed history/as-of tests: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("\nAll history/as-of checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
