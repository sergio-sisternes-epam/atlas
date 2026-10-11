#!/usr/bin/env python3
"""M15 acceptance: with no ``--scope`` flag and no mesh config key, single-store
output is byte-identical to the main-branch goldens.

The goldens under ``fixtures/mesh-default/`` were captured from the unmodified
tree at 7e84953 (the PR #62 squash merge) by running this file with
``ATLAS_UPDATE_GOLDEN=1`` before any mesh product code changed. Only the
temporary directory path (and the ``local/<name>-<hash>`` id derived from it)
and timing values are normalised.

The same command sequence runs twice: once with the plain mesh document, once
with the new mesh keys (``recall.scope``, ``recall.rrf_k``, ``graph``,
``mesh_member: true``) set to their defaults where the running tree accepts
them. Both runs must match the goldens: the new keys are inert in packet MA.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "scripts" / "atlas.py"
GOLDEN = ROOT / "fixtures" / "mesh-default"
GOLDEN_FILE = GOLDEN / "goldens.json"
CLEAN_ENV = ("ATLAS_INDEX_ROOT", "ATLAS_UPDATE_GOLDEN", "ATLAS_TEST_PLATFORM", "ATLAS_NANOGRAPH_BIN")

ALPHA = "github.com/acme/alpha"
BETA = "github.com/acme/beta"

ALPHA_PAGES: dict[str, str] = {
    "index.md": "# Alpha\n\n- work\n- notes\n",
    "work/index.md": "# Work\n\n- hub\n",
    "notes/index.md": "# Notes\n\n- child\n- other\n",
    "work/hub.md": (
        "---\ntype: work\ntitle: Ranking hub\ndescription: Hub for recall ranking\ncreated: 2026-10-10\n"
        "work_id: hub\nkva: forming\ngrowth: true\ntags:\n  - ranking\n  - recall\n---\n\n"
        "## Scope\n\nRanking recall across the alpha store, with enough prose to pass the thin page gate.\n"
    ),
    "notes/child.md": (
        "---\ntype: decision\ntitle: Ranking child\ncreated: 2026-10-10\nwork_id: hub\n"
        "relates_to:\n  - path: work/hub.md\n    kind: implements\n"
        "  - path: notes/missing.md\n    kind: related\n"
        f"  - path: atlas://{BETA}/notes/peer.md\n    kind: derived_from\n"
        "  - path: atlas://beta/notes/peer.md\n    kind: related\n"
        "---\n\n## Claim\n\nThe child implements ranking recall and cites beta.\n"
    ),
    "notes/other.md": (
        "---\ntype: lesson\ntitle: Graph lesson\ndescription: Traversal note\ncreated: 2026-10-10\n"
        "relates_to:\n  - path: notes/child.md\n    kind: derived_from\n---\n\n"
        "## Claim\n\nGraph traversal follows relates_to edges.\n"
    ),
}

BETA_PAGES: dict[str, str] = {
    "index.md": "# Beta\n\n- notes\n",
    "notes/index.md": "# Notes\n\n- peer\n",
    "notes/peer.md": (
        "---\ntype: lesson\ntitle: Peer ranking note\ncreated: 2026-10-10\n"
        "relates_to:\n  - path: notes/second.md\n    kind: related\n---\n\n"
        "## Claim\n\nBeta also ranks recall results, and this sentence keeps the page above the thin gate.\n"
    ),
    "notes/second.md": (
        "---\ntype: document\ntitle: Second beta page\ncreated: 2026-10-10\nsensitivity: restricted\n---\n\n"
        "Second page body about ranking, long enough to count as real prose for compile.\n"
    ),
}

LONE_PAGES: dict[str, str] = {
    "index.md": "# Lone\n\n- notes\n",
    "notes/index.md": "# Notes\n\n- solo\n",
    "notes/solo.md": (
        "---\ntype: lesson\ntitle: Solo ranking\ncreated: 2026-10-10\n---\n\n## Claim\n\nA standalone ranking page.\n"
    ),
}

TIMING_KEYS = re.compile(r'("(?:[a-z_]*_ms|elapsed[a-z_]*|duration[a-z_]*|took[a-z_]*|seconds)"\s*:\s*)-?[0-9.]+(?:e-?[0-9]+)?')
GENERATION = re.compile(r"\b[0-9]{8}T[0-9]{6}-[0-9a-f]{8}\b")
TIMING_TEXT = re.compile(r"\b[0-9]+(?:\.[0-9]+)?\s?(?:ms|s)\b(?=[)\]., ]|$)", re.M)


def base_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in CLEAN_ENV}
    env["DBUS_SESSION_BUS_ADDRESS"] = "disabled:"
    return env


def run(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(ATLAS), *args], cwd=ROOT, text=True, capture_output=True, env=base_env()
    )
    return proc.returncode, proc.stdout, proc.stderr


def write_pages(store: Path, pages: dict[str, str]) -> None:
    for rel, text in pages.items():
        path = store / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def local_hash(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:8]


class Normaliser:
    def __init__(self, tmp: Path, standalone: list[Path]) -> None:
        self.paths = sorted({str(tmp), str(tmp.resolve())}, key=len, reverse=True)
        self.hashes = sorted({local_hash(p) for p in standalone} | {local_hash(p.resolve()) for p in standalone})

    def __call__(self, text: str) -> str:
        for p in self.paths:
            text = text.replace(p, "<TMP>")
            text = text.replace(json.dumps(p)[1:-1], "<TMP>")
        for h in self.hashes:
            text = text.replace(h, "<TMPHASH>")
        text = GENERATION.sub("<GENERATION>", text)
        text = TIMING_KEYS.sub(r"\1<TIME>", text)
        return TIMING_TEXT.sub("<TIME>", text)


def mesh_doc(with_new_keys: bool) -> dict:
    alpha: dict = {"id": ALPHA, "path": "atlas/alpha"}
    beta: dict = {"id": BETA, "path": "atlas/beta"}
    doc: dict = {"version": 1, "stores": [alpha, beta]}
    if with_new_keys:
        alpha["mesh_member"] = True
        beta["mesh_member"] = True
        doc["recall"] = {"scope": "store", "rrf_k": 60}
        doc["graph"] = {"scope": "store", "driver": "native"}
    return doc


def scenario(tmp: Path, with_new_keys: bool) -> list[dict]:
    """Build the fixtures under ``tmp`` and run the fixed command sequence."""
    project = tmp / "proj"
    alpha = project / "atlas" / "alpha"
    beta = project / "atlas" / "beta"
    lone = tmp / "lone"
    project.mkdir(parents=True)
    (project / "atlas-mesh.json").write_text(json.dumps(mesh_doc(with_new_keys), indent=2) + "\n", encoding="utf-8")
    norm = Normaliser(tmp, [lone, project, alpha, beta])
    results: list[dict] = []

    def step(name: str, *args: str) -> None:
        code, out, err = run(*args)
        results.append({"name": name, "exit": code, "stdout": norm(out), "stderr": norm(err)})

    def files(name: str, base: Path) -> None:
        listing = {}
        for p in sorted(base.rglob("*")):
            if p.is_file():
                listing[p.relative_to(base).as_posix()] = norm(p.read_text(encoding="utf-8"))
        results.append({"name": name, "files": listing})

    for label, store, pages, version in (
        ("alpha", alpha, ALPHA_PAGES, "1.0"),
        ("beta", beta, BETA_PAGES, "1.0"),
        ("lone", lone, LONE_PAGES, "1.0"),
    ):
        step(f"init-{label}", "init", "--root", str(store), "--schema-version", version, "--json")
        write_pages(store, pages)

    a, b, s, p = str(alpha), str(beta), str(lone), str(project)
    step("validate-alpha-dry-json", "validate", "--root", a, "--dry-run", "--json")
    step("validate-beta-dry-text", "validate", "--root", b, "--dry-run")
    step("compile-lone-dry-json", "compile", "--root", s, "--dry-run", "--json")
    step("graph-drivers-json", "graph", "drivers", "--root", a, "--json")
    step("graph-drivers-text", "graph", "drivers", "--root", a)
    step("index-show-alpha-json", "index", "show", "--root", a, "--json")
    step("index-show-project-json", "index", "show", "--root", p, "--json")
    step("index-show-lone-json", "index", "show", "--root", s, "--json")
    step("index-status-project-json-before", "index", "status", "--root", p, "--json")
    step("index-status-lone-json-before", "index", "status", "--root", s, "--json")
    for label, root in (("alpha", a), ("beta", b), ("lone", s)):
        step(f"recall-grep-{label}-json", "recall", "run", "ranking recall", "--root", root, "--engine", "grep", "--json")
        step(f"recall-grep-{label}-text", "recall", "run", "ranking recall", "--root", root, "--engine", "grep")
    step("recall-default-alpha-json", "recall", "run", "ranking", "--root", a, "--json")
    for label, root in (("alpha", a), ("beta", b), ("lone", s)):
        step(f"recall-bm25-{label}-json", "recall", "run", "ranking recall", "--root", root, "--engine", "bm25", "--json")
        step(f"recall-bm25-{label}-text", "recall", "run", "ranking recall", "--root", root, "--engine", "bm25")
    step("graph-nodes-alpha-json", "graph", "nodes", "--root", a, "--json")
    step("graph-nodes-alpha-text", "graph", "nodes", "--root", a)
    step("graph-nodes-beta-json", "graph", "nodes", "--root", b, "--json")
    step("graph-edges-alpha-json", "graph", "edges", "--root", a, "--all", "--json")
    step("graph-edges-alpha-text", "graph", "edges", "--root", a, "--all")
    step("graph-edges-beta-json", "graph", "edges", "--root", b, "--all", "--json")
    step("graph-neighbours-alpha-json", "graph", "neighbours", "notes/child.md", "--root", a, "--hops", "2", "--json")
    step("graph-neighbours-alpha-text", "graph", "neighbours", "work/hub.md", "--root", a, "--direction", "in")
    step("graph-export-alpha-json", "graph", "export", "--root", a, "--format", "json", "--out", str(tmp / "export-alpha"), "--json")
    files("graph-export-alpha-files", tmp / "export-alpha")
    step("compile-alpha-json", "compile", "--root", a, "--json")
    step("compile-beta-text", "compile", "--root", b)
    step("validate-lone-json", "validate", "--root", s, "--json")
    step("index-status-project-json-after", "index", "status", "--root", p, "--json")
    step("index-status-alpha-text", "index", "status", "--root", a)
    step("index-status-lone-json-after", "index", "status", "--root", s, "--json")
    step("index-show-alpha-text", "index", "show", "--root", a)
    step("recall-bm25-alpha-json-after-compile", "recall", "run", "ranking", "--root", a, "--engine", "bm25", "--json")
    step("graph-nodes-alpha-json-after-compile", "graph", "nodes", "--root", a, "--json")
    return results


def run_scenario(with_new_keys: bool) -> list[dict]:
    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-default-"))
    try:
        return scenario(tmp, with_new_keys)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def new_keys_supported() -> bool:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from atlas_cli.core import meshfile
    except ImportError:
        return False
    return not meshfile.validate_doc(mesh_doc(True))


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    if os.environ.get("ATLAS_UPDATE_GOLDEN") == "1":
        results = run_scenario(False)
        GOLDEN.mkdir(parents=True, exist_ok=True)
        GOLDEN_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {GOLDEN_FILE.relative_to(ROOT)} ({len(results)} steps)")
        return 0

    golden = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
    golden_by = {g["name"]: g for g in golden}
    runs = [("default", False)]
    if new_keys_supported():
        runs.append(("new-keys", True))
    else:
        print("  [SKIP] new mesh keys not accepted by this tree; only the default run is checked")
    for label, flag in runs:
        results = run_scenario(flag)
        check(f"{label}-step-names", [r["name"] for r in results] == [g["name"] for g in golden])
        for r in results:
            want = golden_by.get(r["name"])
            same = want is not None and json.dumps(r, sort_keys=True) == json.dumps(want, sort_keys=True)
            detail = ""
            if not same and want is not None:
                for key in ("exit", "stdout", "stderr", "files"):
                    if r.get(key) != want.get(key):
                        detail = f"{key}: got {str(r.get(key))[:300]!r} want {str(want.get(key))[:300]!r}"
                        break
            check(f"{label}-{r['name']}", same, detail)

    if failed:
        print(f"\n{len(failed)} mesh default check(s) failed: {', '.join(failed[:10])}")
        return 1
    print("\nAll mesh default (byte-identical) checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
