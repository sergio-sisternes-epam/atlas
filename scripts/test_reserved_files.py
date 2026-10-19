#!/usr/bin/env python3
"""OKF reserved-file compile checks. Run: python3 scripts/test_reserved_files.py

index.md / log.md must not be concept pages (reserved_name_concept, warning);
other frontmatter on them is info (reserved_name_frontmatter); an oldest-first
log.md is info (log_md_order). atlas-tasks list indexes and okf_version on the
store-root index.md are exempt.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
IDS = {"reserved_name_concept", "reserved_name_frontmatter", "log_md_order"}


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args], cwd=ROOT, text=True, capture_output=True
    )


def compile_json(store: Path, *extra: str) -> tuple[int, dict]:
    result = run(["compile", "--root", str(store), "--json", *extra])
    try:
        return result.returncode, json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.returncode, {"_stdout": result.stdout, "_stderr": result.stderr}


def findings(payload: dict) -> set[tuple[str, str, str]]:
    out = set()
    for sev in ("critical", "warnings", "info"):
        for issue in payload.get(sev, []) or []:
            if issue.get("id") in IDS:
                out.add((sev, issue["id"], issue["path"]))
    return out


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def new_store(tmp: Path, name: str) -> Path:
    store = tmp / name
    init = run(["init", "--root", str(store), "--json"])
    if init.returncode != 0:
        raise SystemExit(f"[FAIL] init {name}: {init.stderr!r}")
    return store


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-reserved-files-"))
    failures: list[str] = []

    def check(label: str, cond: bool, detail: object = "") -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        if not cond:
            failures.append(f"{label}: {detail}")

    try:
        # 1. fresh init store: no reserved findings
        store = new_store(tmp, "fresh")
        code, payload = compile_json(store)
        check("fresh init has no reserved findings", findings(payload) == set() and code == 0, (code, payload))

        # 2. meeting summary filed as index.md -> warning, exit 1
        store = new_store(tmp, "concept")
        write(store / "index.md", "# Store\n\n- [Meetings](meetings/index.md)\n")
        write(store / "meetings" / "index.md", "# Meetings\n\n- [Standup](standup/index.md)\n")
        write(
            store / "meetings" / "standup" / "index.md",
            "---\ntype: meeting\ntitle: Standup\ncreated: 2026-10-19\n---\n\n"
            "# Standup\n\nThe team agreed to ship on Friday.\n",
        )
        code, payload = compile_json(store)
        got = findings(payload)
        check(
            "concept-typed index.md -> reserved_name_concept warning",
            ("warnings", "reserved_name_concept", "meetings/standup/index.md") in got,
            got,
        )
        check("reserved_name_concept is blocking (exit 1)", code == 1, code)

        # 3. inline ignore suppresses it
        write(
            store / "meetings" / "standup" / "index.md",
            "---\ntype: meeting\ntitle: Standup\ncreated: 2026-10-19\n---\n\n"
            "<!-- atlas-ignore: reserved_name_concept -->\n# Standup\n\nNotes.\n",
        )
        code, payload = compile_json(store)
        got = findings(payload)
        check("atlas-ignore suppresses reserved_name_concept", not any(i == "reserved_name_concept" for _, i, _ in got), got)

        # 4. --path focus outside the file -> not reported
        write(
            store / "meetings" / "standup" / "index.md",
            "---\ntype: meeting\ntitle: Standup\ncreated: 2026-10-19\n---\n\n# Standup\n\nNotes.\n",
        )
        write(store / "notes" / "index.md", "# Notes\n\n- [A](a.md)\n")
        write(store / "notes" / "a.md", "---\ntype: document\ntitle: A\ncreated: 2026-10-19\n---\n\n## Content\n\nThis page holds enough plain prose to pass the thin-page check in compile.\n")
        code, payload = compile_json(store, "--path", "notes")
        got = findings(payload)
        check("focused --path outside skips reserved findings", got == set(), got)

        # 5. concept-typed log.md -> warning
        store = new_store(tmp, "typedlog")
        write(store / "log.md", "---\ntype: decision\ntitle: A decision\n---\n\nWe decided X.\n")
        code, payload = compile_json(store)
        got = findings(payload)
        check("concept-typed log.md -> reserved_name_concept", ("warnings", "reserved_name_concept", "log.md") in got, got)

        # 6. type: document on a listing -> info only, exit 0
        store = new_store(tmp, "docindex")
        write(store / "area" / "index.md", "---\ntype: document\ntitle: Area\n---\n\n# Area\n\n- [P](p.md)\n")
        write(store / "area" / "p.md", "---\ntype: document\ntitle: P\ncreated: 2026-10-19\n---\n\n## Content\n\nThis page holds enough plain prose to pass the thin-page check in compile.\n")
        code, payload = compile_json(store)
        got = findings(payload)
        check(
            "type: document index -> reserved_name_frontmatter info",
            got == {("info", "reserved_name_frontmatter", "area/index.md")},
            got,
        )
        check("info-only reserved finding keeps exit 0", code == 0, (code, payload.get("warnings")))

        # 7. root index: okf_version only is clean; extra keys are info
        store = new_store(tmp, "rootindex")
        write(store / "index.md", '---\nokf_version: "0.2"\n---\n\n# Store\n')
        code, payload = compile_json(store)
        check("root index.md with only okf_version is clean", findings(payload) == set(), findings(payload))
        write(store / "sub" / "index.md", '---\nokf_version: "0.2"\n---\n\n# Sub\n')
        write(store / "sub" / "p.md", "---\ntype: document\ntitle: P\ncreated: 2026-10-19\n---\n\n## Content\n\nThis page holds enough plain prose to pass the thin-page check in compile.\n")
        code, payload = compile_json(store)
        check(
            "okf_version below the root is not exempt",
            ("info", "reserved_name_frontmatter", "sub/index.md") in findings(payload),
            findings(payload),
        )
        write(store / "index.md", '---\nokf_version: "0.2"\ntitle: Store\n---\n\n# Store\n')
        code, payload = compile_json(store)
        check(
            "root index.md with okf_version + title -> info",
            ("info", "reserved_name_frontmatter", "index.md") in findings(payload),
            findings(payload),
        )

        # 8. atlas-tasks list indexes are exempt
        store = new_store(tmp, "tasks")
        write(
            store / "tasks" / "index.md",
            "---\ntype: task-list\ntitle: Tasks index\ntask_id: atlas://x/tasks/01M43VD3PFNF8Q2NFYSMKGMEKY\ntasks: []\n---\n\n## Members\n",
        )
        write(
            store / "tasks" / "01M57SQQNGBBG6S5FRPGFV7GDN-list" / "index.md",
            "---\ntitle: 'Index: list'\ngenerated_by: atlas-tasks\n"
            "task_list_page: 01M57SQQNGBBG6S5FRPGFV7GDN-list.task-list.md\n---\n\n- list\n",
        )
        code, payload = compile_json(store)
        got = {f for f in findings(payload) if f[2].startswith("tasks/")}
        check("atlas-tasks list indexes are exempt", got == set(), got)

        # 9. log order
        store = new_store(tmp, "logorder")
        write(store / "log.md", "# Log\n\n- 2026-10-01: a\n- 2026-10-05: b\n- 2026-10-19: c\n")
        code, payload = compile_json(store)
        got = findings(payload)
        check("oldest-first log.md -> log_md_order info", got == {("info", "log_md_order", "log.md")}, got)
        check("log_md_order keeps exit 0", code == 0, code)
        write(store / "log.md", "# Log\n\n- 2026-10-19: c\n- 2026-10-05: b\n- 2026-10-01: a\n- init\n")
        code, payload = compile_json(store)
        check("newest-first log.md is clean", findings(payload) == set(), findings(payload))
        write(store / "log.md", "# Log\n\n- 2026-10-19: only one dated entry\n- init\n")
        code, payload = compile_json(store)
        check("single dated entry is not judged", findings(payload) == set(), findings(payload))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"- {f}")
        return 1
    print("\nall reserved-file checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
