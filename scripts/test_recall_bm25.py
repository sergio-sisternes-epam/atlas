#!/usr/bin/env python3
"""--engine bm25 on SQLite FTS5, labelled any-word retry, index ignore guards."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.commands import search as search_cmd  # noqa: E402
from atlas_cli.core import ignore_guard, index_location  # noqa: E402
from atlas_cli.core.recall_config import fts5_available  # noqa: E402

PAGES = {
    "decisions/alpha.md": (
        "---\ntype: decision\ntitle: Ranking contract\ncreated: 2026-09-09\n"
        "description: Recall ranking stays deterministic\n"
        "relates_to:\n  - path: work/hub.md\n    kind: implements\n---\n\n"
        "## Claim\n\nRecall ranking must stay deterministic for recall tests.\n"
    ),
    "decisions/beta.md": (
        "---\ntype: decision\ntitle: Snippet policy\ncreated: 2026-09-09\n---\n\n"
        "## Claim\n\nSnippets mention ranking once and recall once.\n"
    ),
    "decisions/gamma.md": (
        "---\ntype: decision\ntitle: Ranking weights\ncreated: 2026-09-09\n---\n\n"
        "## Claim\n\nTitle weight beats body weight when ranking pages.\n"
    ),
    "decisions/old.md": (
        "---\ntype: decision\ntitle: Old ranking recall rule\ncreated: 2026-09-09\n"
        "status: superseded\n---\n\n## Claim\n\nSuperseded ranking recall guidance kept for history only.\n"
    ),
    "work/hub.md": (
        "---\ntype: work\ntitle: Recall hub\ncreated: 2026-09-09\nwork_id: recall-hub\n---\n\n"
        "## Scope\n\nWork hub for configurable recall across every store we look after.\n"
    ),
    "decisions/index.md": "# Decisions\n\n- alpha\n- beta\n- gamma\n- old\n",
    "work/index.md": "# Work\n\n- hub\n",
}


def run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
    )


def as_json(proc: subprocess.CompletedProcess[str]) -> dict:
    text = proc.stdout.strip()
    return json.loads(text) if text.startswith("{") else {}


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_store(path: Path, version: str) -> Path:
    run(["init", "--root", str(path), "--schema-version", version, "--json"])
    for name, text in PAGES.items():
        write(path / name, text)
    return path


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)


def in_process_run(**kwargs) -> dict:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        search_cmd.run(as_json=True, **kwargs)
    return json.loads(buf.getvalue())


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-bm25-"))
    try:
        if not fts5_available():
            print("  [SKIP] sqlite3 lacks FTS5; only the grep fallback is checked")
        v1 = make_store(tmp / "v1", "1.0")
        v2 = make_store(tmp / "v2", "2.0")

        # 1. bm25 on SCHEMA 1.0 matches SMR atlas:ranked on a 2.0 copy.
        bm = run(["recall", "run", "ranking recall", "--root", str(v1), "--engine", "bm25", "--json"])
        bp = as_json(bm)
        smr = run(["recall", "run", "ranking recall", "--root", str(v2), "--profile", "atlas:ranked", "--json"])
        sp = as_json(smr)
        bpaths = [h.get("path") for h in bp.get("hits") or []]
        spaths = [h.get("path") for h in sp.get("hits") or []]
        if fts5_available():
            check(
                "bm25-v1-engine-used",
                bm.returncode == 0
                and bp.get("engine_configured") == "bm25"
                and bp.get("engine_used") == "sqlite-fts5"
                and bp.get("engine_source") == "cli"
                # An explicit --engine bm25 persists its index (0.14.0) instead of a temporary one.
                and bp.get("ephemeral") is False
                and bp.get("fast_path") is True
                and bp.get("index_rebuilt") is True
                and bp.get("match") == "all",
                bm.stderr[:200] or str({k: bp.get(k) for k in ("engine_used", "warning", "match")}),
            )
            check("bm25-matches-smr-ranked", bool(bpaths) and bpaths == spaths, f"{bpaths} vs {spaths}")
            check("smr-match-all", sp.get("match") == "all", str(sp.get("match")))
            hit = (bp.get("hits") or [{}])[0]
            check(
                "bm25-hit-shape",
                all(k in hit for k in ("path", "score", "title", "type", "snippet", "relates_to"))
                and hit.get("score_orientation") == "lower_better"
                and bp.get("score_orientation") == "lower_better"
                and "match" not in hit,
                str(hit)[:300],
            )
            alpha = next((h for h in bp.get("hits") or [] if h.get("path") == "decisions/alpha.md"), {})
            check(
                "bm25-relates-preview",
                alpha.get("relates_to") == [{"path": "work/hub.md", "kind": "implements"}],
                str(alpha.get("relates_to")),
            )
            check("no-stub-warning", not bp.get("warnings"), str(bp.get("warnings")))
            check(
                "bm25-index-persisted-not-legacy",
                not (v1 / ".atlas-index").exists()
                and (v1 / ".atlas" / "indexes" / "fts5").is_dir()
                and str(bp.get("index_dir") or "").startswith(".atlas/indexes/fts5/local/v1-"),
                str(bp.get("index_dir")),
            )

            # Exit-state exclusion.
            check("bm25-hides-superseded", bool(bpaths) and "decisions/old.md" not in bpaths, str(bpaths))
            inc = as_json(
                run(["recall", "run", "ranking recall", "--root", str(v1), "--engine", "bm25", "--include-exits", "--json"])
            )
            check(
                "bm25-include-exits",
                "decisions/old.md" in [h.get("path") for h in inc.get("hits") or []],
                str([h.get("path") for h in inc.get("hits") or []]),
            )
            asked = as_json(
                run(["recall", "run", "ranking status:superseded", "--root", str(v1), "--engine", "bm25", "--json"])
            )
            check(
                "bm25-explicit-exit-filter",
                asked.get("engine_used") == "sqlite-fts5"
                and [h.get("path") for h in asked.get("hits") or []] == ["decisions/old.md"],
                str(asked.get("hits"))[:300],
            )
            typed = as_json(
                run(["recall", "run", "recall type:work", "--root", str(v1), "--engine", "bm25", "--json"])
            )
            check(
                "bm25-type-filter",
                [h.get("path") for h in typed.get("hits") or []] == ["work/hub.md"],
                str(typed.get("hits"))[:300],
            )
            pathed = as_json(
                run(["recall", "run", "ranking path:work", "--root", str(v1), "--engine", "bm25", "--json"])
            )
            check("bm25-path-filter", pathed.get("count") == 0, str(pathed.get("hits"))[:300])

            # Filter-only queries keep grep behaviour.
            fo = as_json(run(["recall", "run", "type:work", "--root", str(v1), "--engine", "bm25", "--json"]))
            check(
                "bm25-filter-only-grep",
                fo.get("engine_used") == "grep"
                and not fo.get("warnings")
                and [h.get("path") for h in fo.get("hits") or []] == ["work/hub.md"],
                str(fo)[:300],
            )

            # 2. Any-word retry, labelled, in both paths.
            q = "ranking zebra unicorn"
            anyb = as_json(run(["recall", "run", q, "--root", str(v1), "--engine", "bm25", "--json"]))
            anys = as_json(run(["recall", "run", q, "--root", str(v2), "--profile", "atlas:ranked", "--json"]))
            for label, p in (("bm25", anyb), ("smr", anys)):
                hits = p.get("hits") or []
                check(
                    f"{label}-any-word-retry",
                    p.get("match") == "any" and bool(hits) and all(h.get("match") == "any" for h in hits),
                    str({"match": p.get("match"), "hits": [h.get("path") for h in hits]}),
                )
            check(
                "any-word-retry-respects-exits",
                "decisions/old.md" not in [h.get("path") for h in anyb.get("hits") or []],
            )
            single = as_json(run(["recall", "run", "zebra", "--root", str(v1), "--engine", "bm25", "--json"]))
            check(
                "single-token-no-retry",
                single.get("match") == "all" and single.get("count") == 0,
                str({k: single.get(k) for k in ("match", "count")}),
            )

            # 2b. The any-word retry is decided over eligible pages only: the one
            # eligible all-word match ranks below 4 * --limit excluded matches.
            buried_v1 = tmp / "buried-v1"
            buried_v2 = tmp / "buried-v2"
            for store, version in ((buried_v1, "1.0"), (buried_v2, "2.0")):
                run(["init", "--root", str(store), "--schema-version", version, "--json"])
                for i in range(12):
                    write(
                        store / "lessons" / f"loud-{i:02d}.md",
                        f"---\ntype: lesson\ntitle: Ranking buried {i}\ncreated: 2026-09-09\n---\n\n"
                        "## Claim\n\nRanking buried ranking buried ranking buried.\n",
                    )
                write(
                    store / "decisions" / "quiet.md",
                    "---\ntype: decision\ntitle: Quiet decision\ncreated: 2026-09-09\n---\n\n"
                    "## Claim\n\n" + "Filler prose about unrelated matters. " * 40
                    + "Ranking appears once and buried appears once.\n",
                )
                write(
                    store / "decisions" / "other.md",
                    "---\ntype: decision\ntitle: Other decision\ncreated: 2026-09-09\n---\n\n"
                    "## Claim\n\nOnly ranking here.\n",
                )
            for label, args in (
                ("bm25", ["--root", str(buried_v1), "--engine", "bm25"]),
                ("smr", ["--root", str(buried_v2), "--profile", "atlas:ranked"]),
            ):
                p = as_json(run(["recall", "run", "ranking buried type:decision", *args, "--limit", "2", "--json"]))
                hits = p.get("hits") or []
                check(
                    f"{label}-buried-eligible-all-word",
                    p.get("match") == "all"
                    and [h.get("path") for h in hits] == ["decisions/quiet.md"]
                    and not any(h.get("match") for h in hits),
                    str({"match": p.get("match"), "hits": [h.get("path") for h in hits]}),
                )
                p = as_json(run(["recall", "run", "ranking zebra type:decision", *args, "--limit", "2", "--json"]))
                hits = p.get("hits") or []
                check(
                    f"{label}-buried-any-word-retry",
                    p.get("match") == "any"
                    and sorted(h.get("path") for h in hits) == ["decisions/other.md", "decisions/quiet.md"]
                    and all(h.get("match") == "any" for h in hits),
                    str({"match": p.get("match"), "hits": [h.get("path") for h in hits]}),
                )
                p = as_json(run(["recall", "run", "buried zebra type:decision", *args, "--limit", "2", "--json"]))
                hits = p.get("hits") or []
                check(
                    f"{label}-buried-any-word-eligible",
                    p.get("match") == "any" and [h.get("path") for h in hits] == ["decisions/quiet.md"],
                    str({"match": p.get("match"), "hits": [h.get("path") for h in hits]}),
                )

            # bm25 on 2.0 with recall disabled reuses a published generation.
            act = run(["recall", "activate", "--profile", "atlas:ranked", "--root", str(v2), "--json"])
            comp = run(["compile", "--root", str(v2), "--json"])
            dis = run(["recall", "disable", "--root", str(v2), "--json"])
            fast = as_json(run(["recall", "run", "ranking recall", "--root", str(v2), "--engine", "bm25", "--json"]))
            check(
                "bm25-fast-path-v2-disabled",
                act.returncode == 0
                and comp.returncode in (0, 1)
                and dis.returncode == 0
                and fast.get("engine_used") == "sqlite-fts5"
                and fast.get("fast_path") is True
                and fast.get("ephemeral") is False
                and [h.get("path") for h in fast.get("hits") or []] == bpaths,
                str({k: fast.get(k) for k in ("engine_used", "fast_path", "ephemeral", "warning")}),
            )
            check(
                "bm25-fast-path-reports-index",
                str(fast.get("index_dir") or "").startswith(".atlas/indexes/fts5/local/v2-")
                and fast.get("index_location", {}).get("id_source") == "local"
                and not fast.get("warnings"),
                str({k: fast.get(k) for k in ("index_dir", "index_location", "warnings")}),
            )
            run(["recall", "activate", "--profile", "atlas:ranked", "--root", str(v2), "--json"])
            conflict = run(["recall", "run", "ranking", "--root", str(v2), "--engine", "bm25", "--json"])
            check("engine-conflicts-with-enabled-recall", conflict.returncode == 2)

        # FTS5 unavailable -> grep with warning (in process, monkeypatched).
        original = search_cmd.fts5_available
        search_cmd.fts5_available = lambda: False
        try:
            fb = in_process_run(root=str(v1), query="ranking recall", engine_override="bm25")
        finally:
            search_cmd.fts5_available = original
        check(
            "fts5-missing-falls-back-to-grep",
            fb.get("engine_configured") == "bm25"
            and fb.get("engine_used") == "grep"
            and "FTS5" in str(fb.get("warning"))
            and "falling back to grep" in str(fb.get("warning"))
            and bool(fb.get("hits")),
            str({k: fb.get(k) for k in ("engine_used", "warning")}),
        )

        # Projection failure -> grep with warning.
        broken = make_store(tmp / "broken", "2.0")
        write(
            broken / "decisions" / "bad.md",
            "---\ntype: decision\ntitle: A\ntitle: B\ncreated: 2026-09-09\n---\n\nranking\n",
        )
        bp2 = as_json(run(["recall", "run", "ranking", "--root", str(broken), "--engine", "bm25", "--json"]))
        check(
            "projection-failure-falls-back",
            bp2.get("engine_used") == "grep" and "projection failed" in str(bp2.get("warning")),
            str({k: bp2.get(k) for k in ("engine_used", "warning")}),
        )

        # Default (no flag) stays grep.
        dflt = as_json(run(["recall", "run", "ranking", "--root", str(v1), "--json"]))
        check("default-engine-grep", dflt.get("engine_used") == "grep", str(dflt.get("engine_used")))

        # 3. Ignore guard.
        if shutil.which("git"):
            for label, rel_store in (("top", ""), ("subdir", "kb/atlas")):
                repo = tmp / f"repo-{label}"
                repo.mkdir()
                git(repo, "init", "-q")
                store = repo / rel_store if rel_store else repo
                make_store(store, "2.0")
                run(["recall", "activate", "--profile", "atlas:ranked", "--root", str(store), "--json"])
                first = as_json(run(["compile", "--root", str(store), "--json"]))
                second_proc = run(["compile", "--root", str(store), "--json"])
                second = as_json(second_proc)
                exclude = repo / ".git" / "info" / "exclude"
                want = f"/{rel_store}/.atlas-index/" if rel_store else "/.atlas-index/"
                lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.is_file() else []
                status = git(repo, "status", "--porcelain", "--untracked-files=all").stdout
                built_dir = repo / ".atlas" / "indexes" / "fts5" / "local"
                check(
                    f"guard-{label}-index-built",
                    any(built_dir.glob("*/current.json")) and not (store / ".atlas-index").exists(),
                    str(sorted(p.name for p in built_dir.glob("*"))) if built_dir.is_dir() else "missing",
                )
                check(f"guard-{label}-line-once", lines.count(want) == 1, str(lines[-3:]))
                check(f"guard-{label}-indexes-line-once", lines.count("/.atlas/indexes/") == 1, str(lines[-3:]))
                status_ok = bool(status.strip()) and ".atlas-index" not in status and ".atlas/" not in status
                check(f"guard-{label}-status-clean", status_ok, "" if status_ok else status[:300])
                first_ids = [i.get("id") for i in first.get("info") or []]
                second_ids = [i.get("id") for i in second.get("info") or []]
                check(
                    f"guard-{label}-info-only-when-added",
                    "atlas_index_ignored" in first_ids
                    and "atlas_indexes_ignored" in first_ids
                    and "atlas_index_ignored" not in second_ids
                    and "atlas_indexes_ignored" not in second_ids,
                    f"{first_ids} / {second_ids}",
                )
                check(f"guard-{label}-no-gitignore", not (repo / ".gitignore").exists())

            repo = tmp / "repo-build"
            repo.mkdir()
            git(repo, "init", "-q")
            make_store(repo, "2.0")
            run(["recall", "activate", "--profile", "atlas:ranked", "--root", str(repo), "--json"])
            build = as_json(run(["recall", "index", "build", "--root", str(repo), "--json"]))
            exclude = repo / ".git" / "info" / "exclude"
            check(
                "guard-index-build",
                build.get("ok") is True
                and exclude.read_text(encoding="utf-8").splitlines().count("/.atlas-index/") == 1
                and exclude.read_text(encoding="utf-8").splitlines().count("/.atlas/indexes/") == 1,
                str(build)[:300],
            )

            covered = tmp / "repo-covered"
            covered.mkdir()
            git(covered, "init", "-q")
            make_store(covered, "2.0")
            ex = covered / ".git" / "info" / "exclude"
            ex.parent.mkdir(parents=True, exist_ok=True)
            ex.write_text("# local\n.atlas-index\n", encoding="utf-8")
            res = ignore_guard.ensure_index_ignored(covered)
            check(
                "guard-respects-existing-line",
                res is None and ex.read_text(encoding="utf-8") == "# local\n.atlas-index\n",
            )
        else:
            print("  [SKIP] git missing; ignore guard checks skipped")

        plain = tmp / "plain"
        make_store(plain, "2.0")
        in_repo = git(plain, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"
        if not in_repo:
            run(["recall", "activate", "--profile", "atlas:ranked", "--root", str(plain), "--json"])
            pc = run(["compile", "--root", str(plain), "--json"])
            pp = as_json(pc)
            check(
                "guard-non-git-silent",
                pc.returncode in (0, 1)
                and not {"atlas_index_ignored", "atlas_indexes_ignored"} & {i.get("id") for i in pp.get("info") or []}
                and ignore_guard.ensure_index_ignored(plain) is None
                and ignore_guard.ensure_indexes_ignored(plain) is None,
                pc.stderr[:200],
            )
        check(
        "guard-missing-dir-silent",
        ignore_guard.ensure_index_ignored(tmp / "nope") is None
        and ignore_guard.ensure_indexes_ignored(tmp / "nope") is None,
    )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("Failed:" if failed else "ok", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
