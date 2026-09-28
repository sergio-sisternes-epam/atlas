#!/usr/bin/env python3
"""Relation ref compile fence, show, and prune. Run: python3 scripts/test_ref_time_travel.py"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.commands.refcmd import (  # noqa: E402
    RefError,
    _rewrite_regular,
    _rewrite_store,
    _unlink_store,
    _empty_relates,
    _write_all,
    append_ref_edges,
)
from atlas_cli.commands.search import _relates_preview  # noqa: E402
from atlas_cli.commands.validate import _bad_relation_ref  # noqa: E402
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
            page(
                "Terminate summary",
                "relates_to: []\n",
                "Why the trial ended. The frame closed after the claim failed.",
            ),
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

        escaped = store / "escaped.md"
        escaped.write_text(
            page(
                "Escaped history",
                "relates_to:\n  - path: ../../outside.md\n    kind: related\n    ref: abcdef\n",
                "History path must stay inside the store.",
            ),
            encoding="utf-8",
        )
        escape_run = run(["compile", "--root", str(store), "--json"])
        escape_payload = json.loads(escape_run.stdout) if escape_run.stdout else {}
        if not any("escapes store root" in item.get("msg", "") for item in escape_payload.get("critical", [])):
            failures.append(f"history path should not escape the store: {escape_payload.get('critical')}")
        else:
            print("[PASS] history path must stay inside the store")
        escaped.unlink()

        if _bad_relation_ref(123) is None or _bad_relation_ref(None) is None:
            failures.append("non-string ref should be rejected before stringification")
        else:
            print("[PASS] non-string ref is rejected")

        preview = _relates_preview(
            {
                "relates_to": [
                    {"path": "tip.md", "kind": "related"},
                    {"path": "old.md", "kind": "related", "ref": "abc"},
                ]
            }
        )
        if preview != [{"path": "tip.md", "kind": "related"}]:
            failures.append(f"search preview should omit history edges: {preview}")
        else:
            print("[PASS] search preview omits history edges")

        outside = tmp / "outside.md"
        outside.write_text("path: victim.md\n", encoding="utf-8")
        (store / "linked.md").symlink_to(outside)
        (store / "victim.md").write_text(
            page("Victim", "relates_to: []\n", "Named drop."),
            encoding="utf-8",
        )
        (store / "summary-link.md").write_text(
            page(
                "Link summary",
                "relates_to: []\n",
                "Summary for symlink case. This page is a real concept.",
            ),
            encoding="utf-8",
        )
        git(store, ["add", "victim.md", "summary-link.md"])
        git(store, ["commit", "-m", "victim"])
        linked = run(
            [
                "ref",
                "prune",
                "--summary",
                "summary-link.md",
                "--drop",
                "victim.md",
                "--ref",
                "HEAD",
                "--kind",
                "derived_from",
                "--root",
                str(store),
                "--json",
            ]
        )
        if linked.returncode != 0 or "path: victim.md" not in outside.read_text(encoding="utf-8"):
            failures.append(f"prune followed a symlink: {linked.stdout} {outside.read_text(encoding='utf-8')}")
        else:
            print("[PASS] prune does not rewrite symlink pages")

        (store / "dir-drop.md").write_text(
            page("Dir drop", "relates_to: []\n", "Will become a directory."),
            encoding="utf-8",
        )
        git(store, ["add", "dir-drop.md"])
        git(store, ["commit", "-m", "dir drop blob"])
        (store / "dir-drop.md").unlink()
        (store / "dir-drop.md").mkdir()
        before_summary = (store / "summary-link.md").read_text(encoding="utf-8")
        refused_dir = run(
            [
                "ref",
                "prune",
                "--summary",
                "summary-link.md",
                "--drop",
                "dir-drop.md",
                "--ref",
                "HEAD",
                "--kind",
                "derived_from",
                "--root",
                str(store),
                "--json",
            ]
        )
        after_summary = (store / "summary-link.md").read_text(encoding="utf-8")
        if refused_dir.returncode == 0 or after_summary != before_summary or not (store / "dir-drop.md").is_dir():
            failures.append(f"directory drop should refuse before rewrite: {refused_dir.stdout}")
        else:
            print("[PASS] prune refuses a directory drop before writing")

        (store / "again.md").write_text(
            page("Again", "relates_to: []\n", "First wording."),
            encoding="utf-8",
        )
        git(store, ["add", "again.md"])
        git(store, ["commit", "-m", "again first"])
        old_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=store,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        (store / "summary-again.md").write_text(
            page(
                "Again summary",
                f"relates_to:\n  - path: again.md\n    kind: derived_from\n    ref: {old_sha}\n",
                "Already has an older history edge. The summary stays a concept page.",
            ),
            encoding="utf-8",
        )
        (store / "again.md").write_text(
            page("Again", "relates_to: []\n", "Second wording."),
            encoding="utf-8",
        )
        git(store, ["add", "again.md", "summary-again.md"])
        git(store, ["commit", "-m", "again second"])
        new_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=store,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        second = run(
            [
                "ref",
                "prune",
                "--summary",
                "summary-again.md",
                "--drop",
                "again.md",
                "--ref",
                "HEAD",
                "--kind",
                "derived_from",
                "--root",
                str(store),
                "--json",
            ]
        )
        again_summary = (store / "summary-again.md").read_text(encoding="utf-8")
        if second.returncode != 0 or again_summary.count("path: again.md") < 2 or new_sha not in again_summary or old_sha not in again_summary:
            failures.append(f"distinct history revs should both remain: {second.stdout}\n{again_summary}")
        else:
            print("[PASS] prune keeps a distinct older history rev")

        typed = tmp / "typed"
        typed_init = run(["init", "--root", str(typed), "--schema-version", "2.0", "--json"])
        if typed_init.returncode != 0:
            failures.append(f"schema 2.0 init failed: {typed_init.stdout} {typed_init.stderr}")
        else:
            (typed / "numeric-ref.md").write_text(
                page(
                    "Numeric ref",
                    "relates_to:\n  - path: gone.md\n    kind: related\n    ref: 123\n",
                    "YAML integer is not a rev string.",
                ),
                encoding="utf-8",
            )
            numeric = run(["compile", "--root", str(typed), "--json"])
            numeric_payload = json.loads(numeric.stdout) if numeric.stdout else {}
            if not any("git rev string" in item.get("msg", "") for item in numeric_payload.get("critical", [])):
                failures.append(f"numeric ref should fail schema 2.0 compile: {numeric_payload.get('critical')}")
            else:
                print("[PASS] schema 2.0 rejects a numeric ref")

        inline = tmp / "inline"
        inline_init = run(["init", "--root", str(inline), "--schema-version", "2.0", "--json"])
        if inline_init.returncode != 0:
            failures.append(f"inline store init failed: {inline_init.stdout} {inline_init.stderr}")
        else:
            git(inline, ["init", "-b", "main"])
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            (inline / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (inline / "other.md").write_text(page("Other", "relates_to: []\n", prose), encoding="utf-8")
            (inline / "living.md").write_text(
                page(
                    "Living",
                    "relates_to: [{path: dead.md, kind: related}]\n",
                    f"See [dead](dead.md). {prose}",
                ),
                encoding="utf-8",
            )
            (inline / "summary.md").write_text(
                page(
                    "Summary",
                    "relates_to: [{path: other.md, kind: related}]\n",
                    f"Why this frame failed. {prose}",
                ),
                encoding="utf-8",
            )
            git(inline, ["add", "dead.md", "other.md", "living.md", "summary.md"])
            git(inline, ["commit", "-m", "inline relations"])
            inline_prune = run(
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
                    str(inline),
                    "--json",
                ]
            )
            living = (inline / "living.md").read_text(encoding="utf-8")
            summary = (inline / "summary.md").read_text(encoding="utf-8")
            compiled = run(["compile", "--root", str(inline), "--json"])
            compiled_ok = compiled.returncode == 0 and '"ok": true' in compiled.stdout
            if (
                inline_prune.returncode != 0
                or "path: dead.md" in living
                or "path: summary.md" not in living
                or summary.count("relates_to:") != 1
                or "path: dead.md" not in summary
                or "path: other.md" not in summary
                or not compiled_ok
            ):
                failures.append(
                    f"inline relates_to was not rewritten as one list: {inline_prune.stdout}\n{living}\n{summary}\n{compiled.stdout}"
                )
            else:
                print("[PASS] prune rewrites an inline relates_to list")

            (inline / "victim.md").write_text(page("Victim", "relates_to: []\n", "Must survive."), encoding="utf-8")
            git(inline, ["add", "victim.md"])
            git(inline, ["commit", "-m", "victim blob"])
            (inline / "alias.md").symlink_to("victim.md")
            before_victim = (inline / "victim.md").read_text(encoding="utf-8")
            alias_drop = run(
                [
                    "ref",
                    "prune",
                    "--summary",
                    "summary.md",
                    "--drop",
                    "alias.md",
                    "--ref",
                    "HEAD",
                    "--kind",
                    "derived_from",
                    "--root",
                    str(inline),
                    "--json",
                ]
            )
            if (
                alias_drop.returncode == 0
                or not (inline / "victim.md").is_file()
                or (inline / "victim.md").read_text(encoding="utf-8") != before_victim
                or "symlink" not in alias_drop.stdout
            ):
                failures.append(f"in-store symlink drop should be refused: {alias_drop.stdout}")
            else:
                print("[PASS] prune refuses an in-store symlink drop")

        guarded = tmp / "guarded"
        guarded_init = run(["init", "--root", str(guarded), "--json"])
        if guarded_init.returncode != 0:
            failures.append(f"guarded store init failed: {guarded_init.stdout} {guarded_init.stderr}")
        else:
            git(guarded, ["init", "-b", "main"])
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            (guarded / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (guarded / "living.md").write_text(
                page("Living", "relates_to:\n  - path: dead.md\n    kind: related\n", f"See [dead](dead.md). {prose}"),
                encoding="utf-8",
            )
            summary_name = "sum:mary.md"
            (guarded / summary_name).write_text(page("Summary", "relates_to: []\n", prose), encoding="utf-8")
            (guarded / "notes.txt").write_text("not a page\n", encoding="utf-8")
            (guarded / "templates" / "foo.md").write_text(page("Template", "relates_to: []\n", prose), encoding="utf-8")
            (guarded / "staging").mkdir(exist_ok=True)
            (guarded / "staging" / "foo.md").write_text(page("Staged", "relates_to: []\n", prose), encoding="utf-8")
            git(guarded, ["add", "."])
            git(guarded, ["commit", "-m", "guarded fixtures"])

            quoted = run(
                [
                    "ref",
                    "prune",
                    "--summary",
                    summary_name,
                    "--drop",
                    "dead.md",
                    "--ref",
                    "HEAD",
                    "--kind",
                    "derived_from",
                    "--root",
                    str(guarded),
                    "--json",
                ]
            )
            living = (guarded / "living.md").read_text(encoding="utf-8")
            summary = (guarded / summary_name).read_text(encoding="utf-8")
            if quoted.returncode != 0 or 'path: "sum:mary.md"' not in living or "path: dead.md" not in summary:
                failures.append(f"YAML-special summary path was not quoted: {quoted.stdout}\n{living}\n{summary}")
            else:
                print("[PASS] prune quotes a YAML-special summary path")

            (guarded / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            not_md = run(
                [
                    "ref",
                    "prune",
                    "--summary",
                    "notes.txt",
                    "--drop",
                    "dead.md",
                    "--ref",
                    "HEAD",
                    "--kind",
                    "derived_from",
                    "--root",
                    str(guarded),
                    "--json",
                ]
            )
            if not_md.returncode == 0 or not (guarded / "dead.md").is_file() or "eligible" not in not_md.stdout:
                failures.append(f"non-markdown summary should be refused: {not_md.stdout}")
            else:
                print("[PASS] prune refuses a non-markdown summary")

            managed_summary = run(
                [
                    "ref",
                    "prune",
                    "--summary",
                    "templates/foo.md",
                    "--drop",
                    "dead.md",
                    "--ref",
                    "HEAD",
                    "--kind",
                    "derived_from",
                    "--root",
                    str(guarded),
                    "--json",
                ]
            )
            managed_drop = run(
                [
                    "ref",
                    "prune",
                    "--summary",
                    summary_name,
                    "--drop",
                    "staging/foo.md",
                    "--ref",
                    "HEAD",
                    "--kind",
                    "derived_from",
                    "--root",
                    str(guarded),
                    "--json",
                ]
            )
            if (
                managed_summary.returncode == 0
                or managed_drop.returncode == 0
                or not (guarded / "dead.md").is_file()
                or not (guarded / "staging" / "foo.md").is_file()
                or "Atlas-managed" not in managed_summary.stdout
                or "Atlas-managed" not in managed_drop.stdout
            ):
                failures.append(
                    f"managed paths should be refused: {managed_summary.stdout} {managed_drop.stdout}"
                )
            else:
                print("[PASS] prune refuses Atlas-managed summary and drop paths")

            dirty_text = (guarded / "dead.md").read_text(encoding="utf-8") + "uncommitted edit\n"
            (guarded / "dead.md").write_text(dirty_text, encoding="utf-8")
            dirty = run(
                [
                    "ref",
                    "prune",
                    "--summary",
                    summary_name,
                    "--drop",
                    "dead.md",
                    "--ref",
                    "HEAD",
                    "--kind",
                    "derived_from",
                    "--root",
                    str(guarded),
                    "--json",
                ]
            )
            if dirty.returncode == 0 or (guarded / "dead.md").read_text(encoding="utf-8") != dirty_text or "dirty" not in dirty.stdout:
                failures.append(f"dirty drop should be refused: {dirty.stdout}")
            else:
                print("[PASS] prune refuses a dirty drop target")

        linked = tmp / "linked"
        linked_init = run(["init", "--root", str(linked), "--json"])
        if linked_init.returncode != 0:
            failures.append(f"linked store init failed: {linked_init.stdout} {linked_init.stderr}")
        else:
            git(linked, ["init", "-b", "main"])
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            (linked / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (linked / "summary.md").write_text(page("Summary", "relates_to: []\n", prose), encoding="utf-8")
            (linked / "living.md").write_text(
                page("Living", "relates_to:\n  - path: dead.md\n    kind: related\n", f"See [dead](dead.md). {prose}"),
                encoding="utf-8",
            )
            git(linked, ["add", "."])
            git(linked, ["commit", "-m", "linked fixtures"])
            outside = tmp / "outside-hard.md"
            outside.write_text((linked / "living.md").read_text(encoding="utf-8"), encoding="utf-8")
            (linked / "living.md").unlink()
            os.link(outside, linked / "living.md")
            hard = run(
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
                    str(linked),
                    "--json",
                ]
            )
            if (
                hard.returncode == 0
                or "hard-linked" not in hard.stdout
                or outside.read_text(encoding="utf-8") != (linked / "living.md").read_text(encoding="utf-8")
                or "path: dead.md" not in outside.read_text(encoding="utf-8")
                or not (linked / "dead.md").is_file()
            ):
                failures.append(f"hard-linked page should not be rewritten: {hard.stdout}")
            else:
                print("[PASS] prune refuses to rewrite a hard-linked page")

            (linked / "living.md").unlink()
            (linked / "living.md").write_text(outside.read_text(encoding="utf-8"), encoding="utf-8")
            not_page = run(
                [
                    "ref",
                    "prune",
                    "--summary",
                    "summary.md",
                    "--drop",
                    "SCHEMA.json",
                    "--ref",
                    "HEAD",
                    "--kind",
                    "derived_from",
                    "--root",
                    str(linked),
                    "--json",
                ]
            )
            if not_page.returncode == 0 or not (linked / "SCHEMA.json").is_file() or "eligible" not in not_page.stdout:
                failures.append(f"non-page drop should be refused: {not_page.stdout}")
            else:
                print("[PASS] prune refuses a non-page drop")

        reserved = tmp / "reserved"
        reserved_init = run(["init", "--root", str(reserved), "--json"])
        if reserved_init.returncode != 0:
            failures.append(f"reserved store init failed: {reserved_init.stdout} {reserved_init.stderr}")
        else:
            git(reserved, ["init", "-b", "main"])
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            (reserved / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (reserved / "summary.md").write_text(page("Summary", "relates_to: []\n", prose), encoding="utf-8")
            (reserved / "living.md").write_text(
                page(
                    "Living",
                    "relates_to:\n  - path: dead.md\n    kind: related\n",
                    f"See [trial](dead.md#why). {prose}",
                ),
                encoding="utf-8",
            )
            tree = reserved / "thing.md"
            tree.mkdir()
            (tree / "child.md").write_text(page("Child", "relates_to: []\n", prose), encoding="utf-8")
            git(reserved, ["add", "."])
            git(reserved, ["commit", "-m", "reserved fixtures"])
            shutil.rmtree(tree)
            drop_index = run(
                [
                    "ref",
                    "prune",
                    "--summary",
                    "summary.md",
                    "--drop",
                    "index.md",
                    "--ref",
                    "HEAD",
                    "--kind",
                    "derived_from",
                    "--root",
                    str(reserved),
                    "--json",
                ]
            )
            if drop_index.returncode == 0 or not (reserved / "index.md").is_file() or "eligible" not in drop_index.stdout:
                failures.append(f"reserved index.md should not be dropped: {drop_index.stdout}")
            else:
                print("[PASS] prune refuses to drop index.md")

            drop_tree = run(
                [
                    "ref",
                    "prune",
                    "--summary",
                    "summary.md",
                    "--drop",
                    "thing.md",
                    "--ref",
                    "HEAD",
                    "--kind",
                    "derived_from",
                    "--root",
                    str(reserved),
                    "--json",
                ]
            )
            show_tree = run(["ref", "show", "thing.md", "--ref", "HEAD", "--root", str(reserved), "--json"])
            summary_text = (reserved / "summary.md").read_text(encoding="utf-8")
            if (
                drop_tree.returncode == 0
                or show_tree.returncode == 0
                or "thing.md" in summary_text
                or "child.md" in show_tree.stdout
            ):
                failures.append(f"historical directory should not be a page blob: {drop_tree.stdout} {show_tree.stdout}")
            else:
                print("[PASS] prune and show require a page blob")

            fragment = run(
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
                    str(reserved),
                    "--json",
                ]
            )
            living = (reserved / "living.md").read_text(encoding="utf-8")
            fragment_compile = run(["compile", "--root", str(reserved), "--json"])
            if (
                fragment.returncode != 0
                or "[trial](summary.md#why)" not in living
                or (reserved / "dead.md").exists()
                or fragment_compile.returncode != 0
                or '"ok": true' not in fragment_compile.stdout
            ):
                failures.append(
                    f"fragment link was not retargeted: {fragment.stdout}\n{living}\n{fragment_compile.stdout}"
                )
            else:
                print("[PASS] prune keeps a fragment when retargeting a markdown link")

        flow_map = tmp / "flow-map"
        flow_init = run(["init", "--root", str(flow_map), "--schema-version", "2.0", "--json"])
        if flow_init.returncode != 0:
            failures.append(f"flow-map store init failed: {flow_init.stdout} {flow_init.stderr}")
        else:
            git(flow_map, ["init", "-b", "main"])
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            (flow_map / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (flow_map / "summary.md").write_text(page("Summary", "relates_to: []\n", prose), encoding="utf-8")
            (flow_map / "living.md").write_text(
                page(
                    "Living",
                    "relates_to:\n  - {path: dead.md, kind: related}\n",
                    f"See [dead](dead.md). {prose}",
                ),
                encoding="utf-8",
            )
            git(flow_map, ["add", "."])
            git(flow_map, ["commit", "-m", "flow map item"])
            mapped = run(
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
                    str(flow_map),
                    "--json",
                ]
            )
            living = (flow_map / "living.md").read_text(encoding="utf-8")
            if mapped.returncode != 0 or "path: dead.md" in living or "path: summary.md" not in living:
                failures.append(f"flow-map relation was not rewritten: {mapped.stdout}\n{living}")
            else:
                print("[PASS] prune rewrites a flow-map relates_to item")

            summary_index = run(
                [
                    "ref",
                    "prune",
                    "--summary",
                    "index.md",
                    "--drop",
                    "dead.md",
                    "--ref",
                    "HEAD",
                    "--kind",
                    "derived_from",
                    "--root",
                    str(flow_map),
                    "--json",
                ]
            )
            if summary_index.returncode == 0 or "eligible" not in summary_index.stdout:
                failures.append(f"reserved summary should be refused: {summary_index.stdout}")
            else:
                print("[PASS] prune refuses a reserved summary page")

        bare = tmp / "bare-summary"
        bare_init = run(["init", "--root", str(bare), "--json"])
        if bare_init.returncode != 0:
            failures.append(f"bare summary store init failed: {bare_init.stdout} {bare_init.stderr}")
        else:
            git(bare, ["init", "-b", "main"])
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            (bare / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (bare / "summary.md").write_text(
                "---\ntitle: Summary\n---\n\n" + prose + "\n",
                encoding="utf-8",
            )
            git(bare, ["add", "."])
            git(bare, ["commit", "-m", "bare summary"])
            refused_summary = run(
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
                    str(bare),
                    "--json",
                ]
            )
            if (
                refused_summary.returncode == 0
                or not (bare / "dead.md").is_file()
                or "compile" not in refused_summary.stdout
            ):
                failures.append(f"invalid summary should be refused before delete: {refused_summary.stdout}")
            else:
                print("[PASS] prune refuses a summary compile would reject")

            (bare / "summary.md").write_text(
                "---\ntype: document\ntitle: Summary\nrelates_to: []\n---\n\n" + prose + "\n",
                encoding="utf-8",
            )
            missing_created = run(
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
                    str(bare),
                    "--json",
                ]
            )
            if (
                missing_created.returncode == 0
                or not (bare / "dead.md").is_file()
                or "required frontmatter" not in missing_created.stdout
            ):
                failures.append(f"summary missing created should be refused: {missing_created.stdout}")
            else:
                print("[PASS] prune refuses a summary that fails the page contract")

            git(bare, ["rm", "dead.md"])
            git(bare, ["commit", "-m", "remove dead from tip"])
            old = subprocess.run(
                ["git", "rev-parse", "HEAD~1"],
                cwd=bare,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            (bare / "summary.md").write_text(page("Summary", "relates_to: []\n", prose), encoding="utf-8")
            (bare / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            untracked = run(
                [
                    "ref",
                    "prune",
                    "--summary",
                    "summary.md",
                    "--drop",
                    "dead.md",
                    "--ref",
                    old,
                    "--kind",
                    "derived_from",
                    "--root",
                    str(bare),
                    "--json",
                ]
            )
            if untracked.returncode == 0 or not (bare / "dead.md").is_file() or "untracked" not in untracked.stdout:
                failures.append(f"untracked drop should be refused: {untracked.stdout}")
            else:
                print("[PASS] prune refuses an untracked drop")

        external = store / "external-ref.md"
        external.write_text(
            page(
                "External ref",
                "relates_to:\n  - path: https://example.invalid/old.md\n    kind: related\n    ref: abcdef\n",
                "History edge must stay inside the store.",
            ),
            encoding="utf-8",
        )
        external_run = run(["compile", "--root", str(store), "--json"])
        external_payload = json.loads(external_run.stdout) if external_run.stdout else {}
        if not any("store-relative" in item.get("msg", "") for item in external_payload.get("critical", [])):
            failures.append(f"external ref path should fail compile: {external_payload.get('critical')}")
        else:
            print("[PASS] history ref rejects an external path")
        external.unlink()

        commented = tmp / "commented"
        commented_init = run(["init", "--root", str(commented), "--schema-version", "2.0", "--json"])
        if commented_init.returncode != 0:
            failures.append(f"commented store init failed: {commented_init.stdout}")
        else:
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            git(commented, ["init", "-b", "main"])
            (commented / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (commented / "summary.md").write_text(page("Summary", "relates_to: []\n", prose), encoding="utf-8")
            (commented / "living.md").write_text(
                page("Living", "relates_to:\n  - path: dead.md # gone\n    kind: related\n", prose),
                encoding="utf-8",
            )
            git(commented, ["add", "."])
            git(commented, ["commit", "-m", "commented edge"])
            commented_prune = run(
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
                    str(commented),
                    "--json",
                ]
            )
            living = (commented / "living.md").read_text(encoding="utf-8")
            if commented_prune.returncode != 0 or "path: dead.md" in living or not (commented / "summary.md").is_file():
                failures.append(f"commented relation was not rewritten: {commented_prune.stdout}\n{living}")
            else:
                print("[PASS] prune rewrites a commented schema 2.0 path")

        shown = tmp / "shown"
        shown_init = run(["init", "--root", str(shown), "--json"])
        if shown_init.returncode != 0:
            failures.append(f"show store init failed: {shown_init.stdout}")
        else:
            git(shown, ["init", "-b", "main"])
            staged = shown / "staging" / "secret.md"
            staged.parent.mkdir(exist_ok=True)
            staged.write_text(page("Secret", "relates_to: []\n", "Staging must not answer."), encoding="utf-8")
            git(shown, ["add", "staging/secret.md"])
            git(shown, ["commit", "-m", "stage"])
            shown_run = run(["ref", "show", "staging/secret.md", "--ref", "HEAD", "--root", str(shown), "--json"])
            if shown_run.returncode == 0 or "managed" not in shown_run.stdout:
                failures.append(f"show should refuse staging: {shown_run.stdout}")
            else:
                print("[PASS] show refuses an Atlas-managed path")

        hub = store / "hub-only-history.md"
        hub.write_text(
            page(
                "Hub",
                "work_id: trial\nrelates_to:\n  - path: missing.md\n    kind: implements\n    ref: abcdef\n",
                "A history edge is not a live work hub.",
            ),
            encoding="utf-8",
        )
        hub_run = run(["compile", "--root", str(store), "--json"])
        hub_payload = json.loads(hub_run.stdout) if hub_run.stdout else {}
        if not any("work_id" in item.get("msg", "") for item in hub_payload.get("warnings", [])):
            failures.append(f"history implements edge should not satisfy work_id: {hub_payload.get('warnings')}")
        else:
            print("[PASS] history ref does not satisfy a live kind contract")
        hub.unlink()

        nested = tmp / "nested-link"
        nested.mkdir()
        outside_dir = tmp / "outside-dir"
        outside_dir.mkdir()
        outside_page = outside_dir / "page.md"
        outside_page.write_text("outside\n", encoding="utf-8")
        (nested / "linked").symlink_to(outside_dir, target_is_directory=True)
        try:
            _rewrite_store(nested, "linked/page.md", b"pwned\n")
        except RefError:
            refused_parent = True
        else:
            refused_parent = False
        if not refused_parent or outside_page.read_text(encoding="utf-8") != "outside\n":
            failures.append("store rewrite followed an intermediate symlink")
        else:
            print("[PASS] store rewrite refuses an intermediate symlink")

        indexed = tmp / "indexed"
        indexed_init = run(["init", "--root", str(indexed), "--json"])
        if indexed_init.returncode != 0:
            failures.append(f"index store init failed: {indexed_init.stdout}")
        else:
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            git(indexed, ["init", "-b", "main"])
            (indexed / "notes").mkdir()
            (indexed / "notes" / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (indexed / "notes" / "summary.md").write_text(page("Summary", "relates_to: []\n", prose), encoding="utf-8")
            git(indexed, ["add", "."])
            git(indexed, ["commit", "-m", "no folder index"])
            missing_index = run(
                [
                    "ref",
                    "prune",
                    "--summary",
                    "notes/summary.md",
                    "--drop",
                    "notes/dead.md",
                    "--ref",
                    "HEAD",
                    "--kind",
                    "derived_from",
                    "--root",
                    str(indexed),
                    "--json",
                ]
            )
            if missing_index.returncode == 0 or not (indexed / "notes" / "dead.md").is_file() or "index.md" not in missing_index.stdout:
                failures.append(f"summary folder without index should be refused: {missing_index.stdout}")
            else:
                print("[PASS] prune refuses a summary folder without index.md")

        overlaid = tmp / "overlaid"
        overlaid_init = run(["init", "--root", str(overlaid), "--json"])
        if overlaid_init.returncode != 0:
            failures.append(f"overlay store init failed: {overlaid_init.stdout}")
        else:
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            git(overlaid, ["init", "-b", "main"])
            (overlaid / "schema.d").mkdir()
            (overlaid / "schema.d" / "trial.json").write_text(
                json.dumps(
                    {
                        "contribution_id": "trial",
                        "claimed_folders": [],
                        "templates": {
                            "by_type": {
                                "trial-note": {
                                    "frontmatter": {"required": ["type", "title", "created", "owner"]}
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (overlaid / "schema.d" / "trial.receipt.json").write_text(
                json.dumps({"written": ["schema.d/trial.json"]}),
                encoding="utf-8",
            )
            (overlaid / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (overlaid / "summary.md").write_text(
                "---\ntype: trial-note\ntitle: Summary\ncreated: 2026-09-27\nrelates_to: []\n---\n\n"
                + prose
                + "\n",
                encoding="utf-8",
            )
            git(overlaid, ["add", "."])
            git(overlaid, ["commit", "-m", "overlay"])
            overlay_prune = run(
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
                    str(overlaid),
                    "--json",
                ]
            )
            if overlay_prune.returncode == 0 or not (overlaid / "dead.md").is_file() or "owner" not in overlay_prune.stdout:
                failures.append(f"overlay-required summary field should be refused: {overlay_prune.stdout}")
            else:
                print("[PASS] prune uses overlay-required frontmatter")

        fifo_store = tmp / "fifo"
        fifo_init = run(["init", "--root", str(fifo_store), "--json"])
        if fifo_init.returncode != 0:
            failures.append(f"fifo store init failed: {fifo_init.stdout}")
        else:
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            git(fifo_store, ["init", "-b", "main"])
            (fifo_store / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (fifo_store / "summary.md").write_text(page("Summary", "relates_to: []\n", prose), encoding="utf-8")
            os.mkfifo(fifo_store / "noise.md")
            git(fifo_store, ["add", "dead.md", "summary.md"])
            git(fifo_store, ["commit", "-m", "fifo neighbor"])
            fifo_run = subprocess.run(
                [
                    sys.executable,
                    str(ATLAS),
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
                    str(fifo_store),
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=5,
            )
            if fifo_run.returncode != 0 or (fifo_store / "dead.md").exists():
                failures.append(f"fifo neighbor blocked prune: {fifo_run.stdout} {fifo_run.stderr}")
            else:
                print("[PASS] prune ignores a non-regular markdown name")

        absent = tmp / "absent-drop"
        absent_init = run(["init", "--root", str(absent), "--json"])
        if absent_init.returncode != 0:
            failures.append(f"absent store init failed: {absent_init.stdout}")
        else:
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            git(absent, ["init", "-b", "main"])
            (absent / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (absent / "summary.md").write_text(page("Summary", "relates_to: []\n", prose), encoding="utf-8")
            git(absent, ["add", "."])
            git(absent, ["commit", "-m", "present"])
            old = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=absent,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            (absent / "dead.md").unlink()
            git(absent, ["add", "dead.md"])
            git(absent, ["commit", "-m", "remove dead"])
            absent_run = run(
                [
                    "ref",
                    "prune",
                    "--summary",
                    "summary.md",
                    "--drop",
                    "dead.md",
                    "--ref",
                    old,
                    "--kind",
                    "derived_from",
                    "--root",
                    str(absent),
                    "--json",
                ]
            )
            summary_text = (absent / "summary.md").read_text(encoding="utf-8")
            if absent_run.returncode == 0 or "absent" not in absent_run.stdout or "ref:" in summary_text:
                failures.append(f"absent drop should be refused before rewrite: {absent_run.stdout}\n{summary_text}")
            else:
                print("[PASS] prune refuses an absent tip drop")

        modes = tmp / "modes"
        modes_init = run(["init", "--root", str(modes), "--json"])
        if modes_init.returncode != 0:
            failures.append(f"mode store init failed: {modes_init.stdout}")
        else:
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            git(modes, ["init", "-b", "main"])
            (modes / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (modes / "summary.md").write_text(page("Summary", "relates_to: []\n", prose), encoding="utf-8")
            (modes / "living.md").write_text(
                page("Living", "relates_to:\n  - path: dead.md\n    kind: related\n", prose),
                encoding="utf-8",
            )
            os.chmod(modes / "living.md", 0o640)
            git(modes, ["add", "."])
            git(modes, ["commit", "-m", "modes"])
            mode_run = run(
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
                    str(modes),
                    "--json",
                ]
            )
            kept = stat.S_IMODE((modes / "living.md").stat().st_mode)
            if mode_run.returncode != 0 or kept != 0o640:
                failures.append(f"rewrite changed page mode {oct(kept)}: {mode_run.stdout}")
            else:
                print("[PASS] prune keeps rewritten page mode")

        mismatch = tmp / "mismatch"
        mismatch.mkdir()
        git(mismatch, ["init", "-b", "main"])
        (mismatch / "dead.md").write_text("same\n", encoding="utf-8")
        git(mismatch, ["add", "dead.md"])
        git(mismatch, ["commit", "-m", "blob"])
        try:
            _unlink_store(mismatch, "dead.md", mismatch, "0" * 40)
        except RefError:
            refused_hash = True
        else:
            refused_hash = False
        if not refused_hash or not (mismatch / "dead.md").is_file():
            failures.append("unlink should recheck the blob before delete")
        else:
            print("[PASS] unlink refuses bytes that no longer match the blob")

        null_body = "This page keeps enough prose that compile does not treat it as a link list."
        for label, scalar in (("null", "null"), ("tilde", "~")):
            empty_store = tmp / f"empty-{label}"
            empty_init = run(["init", "--root", str(empty_store), "--schema-version", "2.0", "--json"])
            if empty_init.returncode != 0:
                failures.append(f"{label} store init failed: {empty_init.stdout}")
                continue
            git(empty_store, ["init", "-b", "main"])
            (empty_store / "dead.md").write_text(page("Dead", "relates_to: []\n", null_body), encoding="utf-8")
            (empty_store / "summary.md").write_text(
                page("Summary", f"relates_to: {scalar}\n", null_body),
                encoding="utf-8",
            )
            git(empty_store, ["add", "."])
            git(empty_store, ["commit", "-m", f"empty {label}"])
            empty_run = run(
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
                    str(empty_store),
                    "--json",
                ]
            )
            summary_text = (empty_store / "summary.md").read_text(encoding="utf-8")
            compile_run = run(["compile", "--root", str(empty_store), "--json"])
            relates_keys = [
                line for line in summary_text.splitlines() if line.startswith("relates_to:")
            ]
            if (
                empty_run.returncode != 0
                or relates_keys != ["relates_to:"]
                or "ref:" not in summary_text
                or compile_run.returncode != 0
            ):
                failures.append(
                    f"{label} relates_to should become one edge list: {empty_run.stdout}\n{summary_text}\n{compile_run.stdout}"
                )
            else:
                print(f"[PASS] prune folds relates_to {scalar} into one key")

        kind_store = tmp / "kind-summary"
        kind_init = run(["init", "--root", str(kind_store), "--json"])
        if kind_init.returncode != 0:
            failures.append(f"kind store init failed: {kind_init.stdout}")
        else:
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            git(kind_store, ["init", "-b", "main"])
            (kind_store / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (kind_store / "summary.md").write_text(
                page(
                    "Summary",
                    "type: protostar\nrelates_to:\n  - path: dead.md\n    kind: derived_from\n",
                    prose,
                ).replace("type: document\n", "", 1),
                encoding="utf-8",
            )
            before = (kind_store / "summary.md").read_text(encoding="utf-8")
            git(kind_store, ["add", "."])
            git(kind_store, ["commit", "-m", "required kind"])
            kind_run = run(
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
                    str(kind_store),
                    "--json",
                ]
            )
            after = (kind_store / "summary.md").read_text(encoding="utf-8")
            if kind_run.returncode == 0 or "derived_from" not in kind_run.stdout or after != before or not (kind_store / "dead.md").is_file():
                failures.append(f"required live kind should block prune: {kind_run.stdout}\n{after}")
            else:
                print("[PASS] prune refuses a summary that loses its live kind")

        fd, name = tempfile.mkstemp(prefix="atlas-write-")
        try:
            real_write = os.write

            def short_write(target: int, data: bytes | memoryview) -> int:
                chunk = bytes(memoryview(data)[:1])
                return real_write(target, chunk)

            os.write = short_write  # type: ignore[assignment]
            try:
                _write_all(fd, b"abcd")
            finally:
                os.write = real_write
            os.lseek(fd, 0, os.SEEK_SET)
            if os.read(fd, 8) != b"abcd":
                failures.append("short writes were not retried")
            else:
                print("[PASS] replacement writes retry a short write")
            os.write = lambda target, data: 0  # type: ignore[assignment]
            try:
                try:
                    _write_all(fd, b"more")
                except RefError:
                    print("[PASS] replacement write refuses zero progress")
                else:
                    failures.append("zero-progress write should fail")
            finally:
                os.write = real_write
        finally:
            os.close(fd)
            Path(name).unlink(missing_ok=True)

        folded = append_ref_edges(
            "---\nrelates_to: null\n---\n\nbody\n",
            [("dead.md", "derived_from", "abc")],
        )
        if folded.count("relates_to:") != 1:
            failures.append(f"null relates_to gained a second key:\n{folded}")
        else:
            print("[PASS] append treats null relates_to as empty")

        commented_empty = "---\ntype: document\ntitle: Summary\nrelates_to: # none\n---\n\nbody\n"
        folded_comment = append_ref_edges(commented_empty, [("dead.md", "derived_from", "abc")])
        if not _empty_relates("relates_to: # none") or folded_comment.count("relates_to:") != 1:
            failures.append(f"commented empty relates_to gained a second key:\n{folded_comment}")
        else:
            print("[PASS] append treats a commented empty relates_to as empty")

        broken = tmp / "broken-schema"
        broken_init = run(["init", "--root", str(broken), "--json"])
        if broken_init.returncode != 0:
            failures.append(f"broken schema init failed: {broken_init.stdout}")
        else:
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            git(broken, ["init", "-b", "main"])
            (broken / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (broken / "summary.md").write_text(page("Summary", "relates_to: []\n", prose), encoding="utf-8")
            git(broken, ["add", "."])
            git(broken, ["commit", "-m", "pages"])
            schema_path = broken / "SCHEMA.json"
            schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
            schema_doc.pop("atlas_id", None)
            schema_path.write_text(json.dumps(schema_doc), encoding="utf-8")
            broken_run = run(
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
                    str(broken),
                    "--json",
                ]
            )
            if broken_run.returncode == 0 or "SCHEMA" not in broken_run.stdout or not (broken / "dead.md").is_file():
                failures.append(f"invalid schema should block prune: {broken_run.stdout}")
            else:
                print("[PASS] prune refuses a schema compile would reject")

        extra = tmp / "extra-schema"
        extra_init = run(["init", "--root", str(extra), "--schema-version", "2.0", "--json"])
        if extra_init.returncode != 0:
            failures.append(f"extra schema init failed: {extra_init.stdout}")
        else:
            prose = "This page keeps enough prose that compile does not treat it as a link list."
            git(extra, ["init", "-b", "main"])
            (extra / "dead.md").write_text(page("Dead", "relates_to: []\n", prose), encoding="utf-8")
            (extra / "summary.md").write_text(page("Summary", "relates_to: []\n", prose), encoding="utf-8")
            git(extra, ["add", "."])
            git(extra, ["commit", "-m", "pages"])
            extra_path = extra / "SCHEMA.json"
            extra_doc = json.loads(extra_path.read_text(encoding="utf-8"))
            extra_doc["not_a_field"] = True
            extra_path.write_text(json.dumps(extra_doc), encoding="utf-8")
            extra_run = run(
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
                    str(extra),
                    "--json",
                ]
            )
            if extra_run.returncode == 0 or not (extra / "dead.md").is_file():
                failures.append(f"schema 2.0 shape should block prune: {extra_run.stdout}")
            else:
                print("[PASS] prune refuses a schema 2.0 document compile would reject")

        outside = tmp / "outside-target.md"
        outside.write_text("outside\n", encoding="utf-8")
        linked = tmp / "linked-page.md"
        linked.symlink_to(outside)
        try:
            _rewrite_regular(linked, b"rewritten\n", "linked-page.md")
        except RefError:
            refused_link = True
        else:
            refused_link = False
        if not refused_link or outside.read_text(encoding="utf-8") != "outside\n":
            failures.append("rewrite followed or accepted a symlink")
        else:
            print("[PASS] page rewrite refuses a symlink")
        regular = tmp / "regular-page.md"
        regular.write_text("old\n", encoding="utf-8")
        _rewrite_regular(regular, b"new\n", "regular-page.md")
        if regular.read_text(encoding="utf-8") != "new\n" or regular.is_symlink():
            failures.append("atomic rewrite did not replace a regular page")
        else:
            print("[PASS] page rewrite replaces a regular file")

        if failures:
            print("\n" + "\n".join(failures))
            return 1
        print("\nAll ref time-travel checks passed")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
