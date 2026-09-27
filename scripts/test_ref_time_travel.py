#!/usr/bin/env python3
"""Relation ref compile fence, show, and prune. Run: python3 scripts/test_ref_time_travel.py"""

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

from atlas_cli.core.projection import _edges_from_meta  # noqa: E402


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "Atlas Test")
    env.setdefault("GIT_AUTHOR_EMAIL", "atlas@example.invalid")
    env.setdefault("GIT_COMMITTER_NAME", "Atlas Test")
    env.setdefault("GIT_COMMITTER_EMAIL", "atlas@example.invalid")
    return subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=cwd or ROOT,
        text=True,
        capture_output=True,
        env=env,
    )


def git(repo: Path, args: list[str]) -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Atlas Test"
    env["GIT_AUTHOR_EMAIL"] = "atlas@example.invalid"
    env["GIT_COMMITTER_NAME"] = "Atlas Test"
    env["GIT_COMMITTER_EMAIL"] = "atlas@example.invalid"
    proc = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"git {args}: {proc.stderr}")


def page(title: str, relates: str, body: str) -> str:
    return (
        "---\n"
        "type: document\n"
        f"title: {title}\n"
        "created: 2026-09-27\n"
        f"{relates}"
        "---\n\n"
        "## Content\n\n"
        f"{body}\n"
    )


def main() -> int:
    failures: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="atlas-ref-"))
    try:
        store = tmp / "store"
        init = run(["init", "--root", str(store), "--json"])
        if init.returncode != 0:
            print(f"[FAIL] init: {init.stderr}")
            return 1

        missing = store / "missing-target.md"
        missing.write_text(
            page(
                "Missing target",
                "relates_to:\n  - path: gone.md\n    kind: related\n",
                "Tip edge to a page that is not on HEAD.",
            ),
            encoding="utf-8",
        )
        broken = run(["compile", "--root", str(store), "--json"])
        try:
            broken_payload = json.loads(broken.stdout)
        except json.JSONDecodeError:
            broken_payload = {}
        broken_msgs = [item.get("msg", "") for item in broken_payload.get("critical", [])]
        if broken.returncode == 0 or not any("gone.md" in msg for msg in broken_msgs):
            failures.append(f"missing tip target should fail compile: {broken.stdout} {broken.stderr}")
        else:
            print("[PASS] missing tip target without ref fails compile")

        missing.write_text(
            page(
                "Missing target",
                "relates_to:\n  - path: gone.md\n    kind: related\n    ref: not-a-rev\n",
                "History edge. Compile must not call git.",
            ),
            encoding="utf-8",
        )
        fenced = run(["compile", "--root", str(store), "--json"])
        try:
            fenced_payload = json.loads(fenced.stdout)
        except json.JSONDecodeError:
            fenced_payload = {}
        fenced_critical = fenced_payload.get("critical") or []
        link_critical = [
            item for item in fenced_critical if item.get("id") in {"relates_to", "internal_links"}
        ]
        if link_critical:
            failures.append(f"ref edge should not require HEAD or git: {link_critical}")
        else:
            print("[PASS] ref edge skips HEAD existence and does not resolve git")

        edges = _edges_from_meta(
            {
                "relates_to": [
                    {"path": "keep.md", "kind": "related"},
                    {"path": "gone.md", "kind": "related", "ref": "not-a-rev"},
                ]
            }
        )
        if edges != [{"target": "keep.md", "kind": "related", "direction": "outgoing"}]:
            failures.append(f"projection should omit ref edges: {edges}")
        else:
            print("[PASS] projection omits ref edges")

        blank = store / "blank-ref.md"
        blank.write_text(
            page(
                "Blank ref",
                "relates_to:\n  - path: gone.md\n    kind: related\n    ref: 'has space'\n",
                "Malformed relation ref.",
            ),
            encoding="utf-8",
        )
        bad_ref = run(["compile", "--root", str(store), "--json"])
        bad_payload = json.loads(bad_ref.stdout)
        if not any("ref must be" in item.get("msg", "") for item in bad_payload.get("critical", [])):
            failures.append(f"whitespace ref should fail compile: {bad_payload.get('critical')}")
        else:
            print("[PASS] whitespace ref fails compile")
        blank.unlink()
        missing.unlink()

        git(store, ["init", "-b", "main"])
        git(store, ["add", "."])
        git(store, ["commit", "-m", "init without trial"])
        empty = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=store,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

        (store / "dead.md").write_text(
            page("Dead trial", "relates_to: []\n", "Trial body that must leave tip."),
            encoding="utf-8",
        )
        (store / "summary.md").write_text(
            page("Terminate summary", "relates_to: []\n", "Why the trial ended."),
            encoding="utf-8",
        )
        (store / "living.md").write_text(
            page(
                "Living",
                "relates_to:\n  - path: dead.md\n    kind: implements\n",
                "See [the trial](dead.md).",
            ),
            encoding="utf-8",
        )
        notes = store / "notes"
        notes.mkdir()
        (notes / "index.md").write_text("# Notes\n\n- [trial](../dead.md)\n", encoding="utf-8")
        (notes / "other.md").write_text(
            page(
                "Other",
                "relates_to:\n  - path: dead.md\n    kind: related\n    ref: already-history\n",
                "Keep [history edge](../dead.md) body link, but frontmatter ref stays.",
            ),
            encoding="utf-8",
        )
        git(store, ["add", "."])
        git(store, ["commit", "-m", "trial"])

        escaped = run(["ref", "show", "../secret.md", "--ref", "HEAD", "--root", str(store), "--json"])
        if escaped.returncode == 0:
            failures.append(f"show should refuse path escape: {escaped.stdout}")
        else:
            print("[PASS] show refuses path escape")

        shown = run(["ref", "show", "dead.md", "--ref", "HEAD", "--root", str(store), "--json"])
        shown_payload = json.loads(shown.stdout)
        if shown.returncode != 0 or "Trial body" not in shown_payload.get("content", ""):
            failures.append(f"show should print the historical page: {shown.stdout} {shown.stderr}")
        else:
            print("[PASS] show prints path at rev")

        refuse_summary = run(
            [
                "ref",
                "prune",
                "--summary",
                "summary.md",
                "--drop",
                "summary.md",
                "--ref",
                "HEAD",
                "--kind",
                "derived_from",
                "--root",
                str(store),
                "--json",
            ]
        )
        if refuse_summary.returncode == 0 or not (store / "summary.md").is_file():
            failures.append(f"prune should refuse dropping the summary: {refuse_summary.stdout}")
        else:
            print("[PASS] prune refuses dropping the summary")

        refuse_rev = run(
            [
                "ref",
                "prune",
                "--summary",
                "summary.md",
                "--drop",
                "dead.md",
                "--ref",
                empty,
                "--kind",
                "derived_from",
                "--root",
                str(store),
                "--json",
            ]
        )
        if refuse_rev.returncode == 0 or not (store / "dead.md").is_file():
            failures.append(f"prune should refuse a rev that lacks the blob: {refuse_rev.stdout}")
        else:
            print("[PASS] prune refuses a rev that lacks the blob")

        pruned = run(
            [
                "ref",
                "prune",
                "--summary",
                "summary.md",
                "--drop",
                "dead.md",
                "--ref",
                "HEAD",
                "--kind",
                "derived_from",
                "--root",
                str(store),
                "--json",
            ]
        )
        if pruned.returncode != 0:
            failures.append(f"prune failed: {pruned.stdout} {pruned.stderr}")
        else:
            living = (store / "living.md").read_text(encoding="utf-8")
            summary = (store / "summary.md").read_text(encoding="utf-8")
            other = (store / "notes" / "other.md").read_text(encoding="utf-8")
            notes_index = (store / "notes" / "index.md").read_text(encoding="utf-8")
            ok = (
                not (store / "dead.md").exists()
                and "path: summary.md" in living
                and "kind: implements" in living
                and "ref:" not in living
                and "[the trial](summary.md)" in living
                and "path: dead.md" in summary
                and "kind: derived_from" in summary
                and "ref:" in summary
                and "ref: already-history" in other
                and "path: dead.md" in other
                and "summary.md" in notes_index
                and "dead.md" not in notes_index
                and "../summary.md" in other
                and "../dead.md" not in other
            )
            compiled = run(["compile", "--root", str(store), "--json"])
            compiled_payload = json.loads(compiled.stdout) if compiled.stdout else {}
            link_critical = [
                item
                for item in compiled_payload.get("critical", [])
                if item.get("id") in {"relates_to", "internal_links"}
            ]
            if link_critical:
                failures.append(f"prune left broken tip links: {link_critical}")
            if not ok:
                failures.append(
                    "prune rewrite mismatch\n"
                    f"living:\n{living}\nsummary:\n{summary}\nother:\n{other}\nindex:\n{notes_index}"
                )
            else:
                print("[PASS] prune retargets tip links and writes summary ref edges")
                print("[PASS] compile has no broken tip links after prune")

        if failures:
            print("\n" + "\n".join(failures))
            return 1
        print("\nAll ref time-travel checks passed")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
