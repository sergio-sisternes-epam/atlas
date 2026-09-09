#!/usr/bin/env python3
"""SMR scan/FTS5/graph and legacy isolation tests."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ATLAS), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-recall-"))
    store = tmp / "store"
    run(["init", "--root", str(store), "--schema-version", "2.0", "--json"])
    write(
        store / "decisions" / "alpha.md",
        "---\ntype: decision\ntitle: Ranking contract\ncreated: 2026-09-09\n"
        "relates_to:\n  - path: work/hub.md\n    kind: implements\n---\n\n"
        "## Claim\n\nFTS5 ranking must stay deterministic for recall tests.\n",
    )
    write(
        store / "work" / "hub.md",
        "---\ntype: work\ntitle: Recall hub\ncreated: 2026-09-09\nwork_id: recall-hub\n---\n\n"
        "## Scope\n\nWork hub for configurable semantic memory recall.\n",
    )
    write(store / "decisions" / "index.md", "# Decisions\n\n- alpha\n")
    write(store / "work" / "index.md", "# Work\n\n- hub\n")
    write(store / "staging" / "secret.md", "staging must not be recalled\n")
    write(store / ".hidden" / "note.md", "---\ntype: document\ntitle: Hidden page\ncreated: 2026-09-09\n---\n\n## Claim\n\nHidden current-tree pages remain eligible for recall.\n")

    conflict = run(
        ["search", "ranking", "--root", str(store), "--engine", "grep", "--profile", "atlas:scan", "--json"]
    )
    check("engine-profile-conflict", conflict.returncode == 2)

    scoped = run(
        ["search", "ranking", "--root", str(store), "--profile", "atlas:scan", "--json"]
    )
    payload = json.loads(scoped.stdout) if scoped.stdout.strip().startswith("{") else {}
    paths = [h.get("path") for h in payload.get("hits") or []]
    check(
        "scan-profile",
        scoped.returncode == 0 and payload.get("ok") and any("alpha.md" in p for p in paths),
        scoped.stderr[:200] or str(paths),
    )
    check("staging-excluded", not any("staging" in p for p in paths))

    graph = run(
        ["search", "ranking", "--root", str(store), "--profile", "atlas:ranked-graph", "--json"]
    )
    gp = json.loads(graph.stdout) if graph.stdout.strip().startswith("{") else {}
    if graph.returncode == 2 and "sqlite_fts5" in str(gp.get("error")):
        check("fts5-unavailable-honest", True)
    else:
        nodes = [n.get("path") for n in (gp.get("neighbourhood") or {}).get("nodes") or []]
        check(
            "ranked-graph-neighbourhood",
            graph.returncode == 0 and any("hub.md" in (p or "") for p in nodes),
            graph.stderr[:200] or str(gp.get("error") or nodes),
        )

    act_default = run(["recall", "activate", "--root", str(store), "--json"])
    adp = json.loads(act_default.stdout) if act_default.stdout.strip().startswith("{") else {}
    check(
        "activate-defaults-ranked",
        act_default.returncode == 0 and adp.get("preset") == "atlas:ranked",
        act_default.stderr[:200] or str(adp),
    )
    act = run(["recall", "activate", "--profile", "atlas:scan", "--root", str(store), "--json"])
    check("activate", act.returncode == 0, act.stderr[:200])
    (store / "staging" / "secret.md").unlink()
    compiled = run(["compile", "--root", str(store), "--json"])
    cp = json.loads(compiled.stdout) if compiled.stdout.strip().startswith("{") else {}
    check(
        "compile-publishes-index",
        compiled.returncode in (0, 1) and bool((cp.get("recall_index") or {}).get("published")),
        compiled.stderr[:200] or str(cp.get("critical") or compiled.stdout[:300]),
    )
    ranked_act = run(["recall", "activate", "--profile", "atlas:ranked", "--root", str(store), "--json"])
    check("activate-ranked", ranked_act.returncode == 0, ranked_act.stderr[:200])
    compiled2 = run(["compile", "--root", str(store), "--json"])
    cp2 = json.loads(compiled2.stdout) if compiled2.stdout.strip().startswith("{") else {}
    check(
        "compile-publishes-ranked",
        compiled2.returncode in (0, 1) and bool((cp2.get("recall_index") or {}).get("published")),
        str(cp2.get("recall_index") or compiled2.stdout[:200]),
    )
    warm = run(["search", "ranking", "--root", str(store), "--json"])
    wp = json.loads(warm.stdout) if warm.stdout.strip().startswith("{") else {}
    rec = wp.get("recall") or {}
    check(
        "fast-path-after-publish",
        warm.returncode == 0 and rec.get("fast_path") is True and rec.get("ephemeral") is False,
        str(rec)[:300] or warm.stderr[:200],
    )
    alpha = store / "decisions" / "alpha.md"
    alpha.write_text(alpha.read_text(encoding="utf-8") + "\nChanged body for fingerprint miss.\n", encoding="utf-8")
    cold = run(["search", "ranking", "--root", str(store), "--json"])
    clp = json.loads(cold.stdout) if cold.stdout.strip().startswith("{") else {}
    crec = clp.get("recall") or {}
    check(
        "mismatch-rebuilds-not-stale",
        cold.returncode == 0
        and crec.get("fast_path") is False
        and any("alpha.md" in (h.get("path") or "") for h in clp.get("hits") or []),
        str(crec)[:300] or cold.stderr[:200],
    )
    focused = run(["compile", "--root", str(store), "--type", "decision", "--json"])
    fp = json.loads(focused.stdout) if focused.stdout.strip().startswith("{") else {}
    check("focused-does-not-publish", not (fp.get("recall_index") or {}).get("published"))
    hidden = run(["search", "Hidden", "--root", str(store), "--profile", "atlas:scan", "--json"])
    hp = json.loads(hidden.stdout) if hidden.stdout.strip().startswith("{") else {}
    hpaths = [h.get("path") for h in hp.get("hits") or []]
    check("hidden-current-tree", any("note.md" in (p or "") for p in hpaths), str(hpaths))

    tgrep_probe = run(
        ["search", "ranking", "--root", str(store), "--profile", "atlas:tgrep", "--json"]
    )
    tp = json.loads(tgrep_probe.stdout) if tgrep_probe.stdout.strip().startswith("{") else {}
    if shutil.which("tgrep"):
        check(
            "tgrep-profile-runs-or-honest",
            tgrep_probe.returncode in (0, 1, 2)
            and "serve" not in str(tp.get("error") or "").lower(),
            str(tp.get("error") or tp.get("engine_used")),
        )
    else:
        check(
            "tgrep-missing-binary",
            tgrep_probe.returncode == 2
            and "tgrep_binary_missing" in str(tp.get("error") or tgrep_probe.stderr),
            str(tp.get("error") or tgrep_probe.stderr[:200]),
        )

    write(store / "schema.d" / "broken.json", "{not json")
    overlay_fail = run(["search", "ranking", "--root", str(store), "--json"])
    ofp = json.loads(overlay_fail.stdout) if overlay_fail.stdout.strip().startswith("{") else {}
    check(
        "search-overlay-fail-closed",
        overlay_fail.returncode == 2 and ofp.get("ok") is False,
        overlay_fail.stdout[:300] or overlay_fail.stderr[:200],
    )
    (store / "schema.d" / "broken.json").unlink(missing_ok=True)

    contrib = tmp / "contrib" / "SCHEMA.overlay.json"
    write(
        contrib,
        json.dumps(
            {
                "contribution_id": "demo-skill",
                "claimed_folders": [],
                "presets": {
                    "explore": {
                        "description": "demo",
                        "coarse": {"driver": "scan"},
                        "rank": {"driver": "scan"},
                        "retrieve": {"driver": "pages-graph"},
                    }
                },
            }
        ),
    )
    inst = run(["schema", "install", str(contrib.parent), "--root", str(store), "--json"])
    check("install-preset", inst.returncode == 0, inst.stderr[:200] or inst.stdout[:200])
    schema = json.loads((store / "SCHEMA.json").read_text())
    check("install-not-activate", schema.get("recall", {}).get("preset") != "demo-skill:explore")
    act2 = run(["recall", "activate", "--profile", "demo-skill:explore", "--root", str(store), "--json"])
    check("activate-contrib-preset", act2.returncode == 0, act2.stderr[:200] or act2.stdout[:200])
    blocked = run(["schema", "uninstall", "demo-skill", "--root", str(store), "--json"])
    check(
        "uninstall-dangling-preset",
        blocked.returncode == 2,
        blocked.stdout[:300] or blocked.stderr[:200],
    )

    print("Failed:" if failed else "ok", ", ".join(failed))
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
