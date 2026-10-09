#!/usr/bin/env python3
"""FTS5 query tokenisation matches unicode61: Unicode terms, diacritics, CJK, underscores."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core.drivers import fts5  # noqa: E402
from atlas_cli.core.recall_config import fts5_available  # noqa: E402


def page(title: str, body: str) -> str:
    return f"---\ntype: decision\ntitle: {title}\ncreated: 2026-10-09\n---\n\n## Claim\n\n{body}\n"


PAGES = {
    "decisions/cafe-accent.md": page("Accented venue", "We met at the café near the station."),
    "decisions/cafe-plain.md": page("Plain venue", "The cafe opens early on weekdays."),
    "decisions/resume.md": page("Hiring note", "Every résumé is read twice before interview."),
    "decisions/both.md": page("Mixed note", "A résumé was left at the café counter."),
    "decisions/naive.md": page("Model note", "A naïve baseline is kept for comparison."),
    "decisions/tokyo.md": page("Travel note", "The office in 東京 opens next spring."),
    "decisions/tokyo-run.md": page("Prefecture note", "Registered under 東京都 rules."),
    "decisions/gruesse.md": page("Greeting note", "Viele Grüße from the platform team."),
    "decisions/underscore.md": page("Identifier note", "Set quux_flag before running the job."),
    "decisions/index.md": "# Decisions\n",
}


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ATLAS), *args], cwd=ROOT, text=True, capture_output=True)


def as_json(proc: subprocess.CompletedProcess[str]) -> dict:
    text = proc.stdout.strip()
    return json.loads(text) if text.startswith("{") else {}


def make_store(path: Path, version: str) -> Path:
    run(["init", "--root", str(path), "--schema-version", version, "--json"])
    for name, text in PAGES.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return path


def sqlite_matches(content: str, query: str) -> bool:
    """Ground truth: does real unicode61 FTS5 match ``query`` (as a phrase) against ``content``?"""
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='unicode61')")
        conn.execute("INSERT INTO t(x) VALUES (?)", (content,))
        phrase = '"' + query.replace('"', '""') + '"'
        return conn.execute("SELECT count(*) FROM t WHERE t MATCH ?", (phrase,)).fetchone()[0] > 0
    finally:
        conn.close()


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}".rstrip())
        if not ok:
            failed.append(name)

    # 1. escape_query / query_tokens unit checks.
    check("escape-cafe", fts5.escape_query("café") == '"café"', fts5.escape_query("café"))
    check("escape-resume-whole", fts5.escape_query("résumé") == '"résumé"', fts5.escape_query("résumé"))
    check("escape-no-ascii-split", "sum" not in fts5.escape_query("résumé").replace("résumé", ""))
    check("escape-cjk", fts5.escape_query("東京") == '"東京"', fts5.escape_query("東京"))
    check("escape-grusse", fts5.escape_query("grüße") == '"grüße"', fts5.escape_query("grüße"))
    check(
        "escape-mixed-and",
        fts5.escape_query("résumé café") == '"résumé" AND "café"',
        fts5.escape_query("résumé café"),
    )
    check(
        "escape-mixed-or",
        fts5.escape_query("résumé café", "OR") == '"résumé" OR "café"',
        fts5.escape_query("résumé café", "OR"),
    )
    check("tokens-count-unicode", len(fts5.query_tokens("résumé café 東京")) == 3, str(fts5.query_tokens("résumé café 東京")))
    check("tokens-underscore-separates", fts5.query_tokens("foo_bar") == ["foo", "bar"], str(fts5.query_tokens("foo_bar")))
    # A decomposed accent (Mn) stays inside the token, as in unicode61.
    check("tokens-combining-mark", fts5.query_tokens("cafe\u0301 x") == ["cafe\u0301", "x"], str(fts5.query_tokens("cafe\u0301 x")))
    check("tokens-punctuation-separates", fts5.query_tokens("a-b's") == ["a", "b", "s"], str(fts5.query_tokens("a-b's")))
    for punct in ("", "   ", "?!", "—…", "_", "\"'", "😀 ✓"):
        check(f"escape-empty-{punct!r}", fts5.escape_query(punct) == '""', fts5.escape_query(punct))
    check("escape-not-empty-digits", fts5.escape_query("²") == '"²"', fts5.escape_query("²"))

    if not fts5_available():
        print("  [SKIP] sqlite3 lacks FTS5; only query tokenisation is checked")
        print("Failed:" if failed else "ok", ", ".join(failed))
        return 1 if failed else 0

    # 2. Query tokens agree with real unicode61: the query side splits where SQLite splits.
    for content in ("foo_bar", "café", "résumé", "東京", "Grüße", "a-b", "e\u0301te", "x\ue000y", "a²b"):
        joined = " ".join(fts5.query_tokens(content))
        check(f"agrees-with-sqlite-{content!r}", sqlite_matches(content, joined), joined)
    # unicode61 splits ``foo_bar``: both ``foo bar`` and ``foo_bar`` match it.
    check("sqlite-underscore-is-separator", sqlite_matches("foo_bar", "foo") and sqlite_matches("foo_bar", "bar"))

    tmp = Path(tempfile.mkdtemp(prefix="atlas-fts5-unicode-"))
    try:
        v1 = make_store(tmp / "v1", "1.0")
        v2 = make_store(tmp / "v2", "2.0")
        modes = (
            ("bm25", ["--root", str(v1), "--engine", "bm25"]),
            ("smr", ["--root", str(v2), "--profile", "atlas:ranked"]),
        )

        def query(args: list[str], q: str) -> tuple[dict, set[str]]:
            proc = run(["recall", "run", q, *args, "--limit", "20", "--json"])
            payload = as_json(proc)
            return payload, {h.get("path") for h in payload.get("hits") or []}

        expected = {
            "café": {"decisions/cafe-accent.md", "decisions/cafe-plain.md", "decisions/both.md"},
            "cafe": {"decisions/cafe-accent.md", "decisions/cafe-plain.md", "decisions/both.md"},
            "résumé": {"decisions/resume.md", "decisions/both.md"},
            "naïve": {"decisions/naive.md"},
            "東京": {"decisions/tokyo.md"},
            "grüße": {"decisions/gruesse.md"},
            "quux flag": {"decisions/underscore.md"},
            "quux_flag": {"decisions/underscore.md"},
        }
        for label, args in modes:
            for q, want in expected.items():
                payload, got = query(args, q)
                check(
                    f"{label}-query-{q}",
                    payload.get("engine_used") == "sqlite-fts5" and payload.get("match") == "all" and got == want,
                    str({"engine": payload.get("engine_used"), "match": payload.get("match"), "hits": sorted(got)}),
                )
            # CJK caveat: a contiguous run is one unicode61 token, so 東京 is not found inside 東京都.
            _, got = query(args, "東京")
            check(f"{label}-cjk-run-not-partial", "decisions/tokyo-run.md" not in got, str(sorted(got)))

            payload, got = query(args, "résumé café")
            check(
                f"{label}-mixed-all-words",
                payload.get("match") == "all" and got == {"decisions/both.md"},
                str({"match": payload.get("match"), "hits": sorted(got)}),
            )
            payload, got = query(args, "résumé zebra")
            hits = payload.get("hits") or []
            check(
                f"{label}-unicode-any-word-retry",
                payload.get("match") == "any"
                and got == {"decisions/resume.md", "decisions/both.md"}
                and all(h.get("match") == "any" for h in hits),
                str({"match": payload.get("match"), "hits": sorted(got)}),
            )
            payload, got = query(args, "東京")
            check(f"{label}-single-unicode-token-no-retry", payload.get("match") == "all", str(payload.get("match")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("Failed:" if failed else "ok", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
