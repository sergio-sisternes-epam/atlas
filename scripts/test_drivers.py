#!/usr/bin/env python3
"""Driver overlay registry, platform gating and the nanograph driver (fake binary).

Runs on any platform: the platform provider is swapped in-process with
driver_overlay.set_platform_provider_for_tests, and CLI subprocesses that need
a fake platform run the test-only entry scripts/testing/atlas_test_cli.py with
ATLAS_TEST_PLATFORM. No real nanograph is needed.
"""

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
TEST_CLI = ROOT / "scripts" / "testing" / "atlas_test_cli.py"
SECRET_ENV = {
    "ATLAS_PAT": "atlas-pat-not-real",
    "GH_TOKEN": "gh-token-not-real",
    "GITHUB_TOKEN": "github-token-not-real",
    "GH_ENTERPRISE_TOKEN": "ghe-token-not-real",
    "GITHUB_APM_PAT": "apm-pat-not-real",
    "GITHUB_APM_PAT_ORG": "apm-pat-org-not-real",
    "COPILOT_GITHUB_TOKEN": "copilot-token-not-real",
    "OPENAI_API_KEY": "sk-test-not-real",
    "GEMINI_API_KEY": "gm-test-not-real",
    "NANOGRAPH_EMBED_MODEL": "should-not-leak",
    "FOO_BAR": "unrelated",
}
sys.path.insert(0, str(ROOT / "scripts"))

from atlas_cli.core import driver_overlay, index_location  # noqa: E402
from atlas_cli.core.drivers import nanograph as nano_mod  # noqa: E402
from test_graph import PAGES, SCHEMA_V1  # noqa: E402

FAKE = r'''#!__PYTHON__
import json, os, re, sys

LOG = os.environ.get("FAKE_NANOGRAPH_LOG")
VERSION = os.environ.get("FAKE_NANOGRAPH_VERSION", "1.3.0")
FAIL = os.environ.get("FAKE_NANOGRAPH_FAIL", "")


def opt(args, name):
    return args[args.index(name) + 1] if name in args else None


args = sys.argv[1:]
with open(os.path.realpath(__file__) + ".calls", "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\n")
if LOG:
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "argv": args,
            "cwd": os.getcwd(),
            "openai": "OPENAI_API_KEY" in os.environ,
            "gemini": "GEMINI_API_KEY" in os.environ,
            "embed": any(k.startswith("NANOGRAPH_EMBED") for k in os.environ),
            "env_keys": sorted(os.environ),
        }) + "\n")
if args == ["--version"]:
    print("nanograph " + VERSION if VERSION != "garbage" else "nanograph dev build")
    sys.exit(0)
cmd = args[0] if args else ""
if cmd == FAIL:
    print("boom", file=sys.stderr)
    sys.exit(3)
db = opt(args, "--db")
if cmd == "init":
    os.makedirs(db, exist_ok=True)
    with open(os.path.join(db, "schema-path"), "w") as fh:
        fh.write(os.path.abspath(opt(args, "--schema")))
    sys.exit(0)
if cmd == "load":
    assert opt(args, "--mode") == "overwrite"
    with open(opt(args, "--data"), encoding="utf-8") as src, open(os.path.join(db, "seed.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(src.read())
    sys.exit(0)
if cmd == "run":
    if FAIL == "garble":
        print("not json")
        sys.exit(0)
    name = opt(args, "--name")
    queries = open(opt(args, "--query"), encoding="utf-8").read()
    if not re.search(r"^query " + re.escape(name) + r"\(", queries, re.M):
        print("unknown query " + name, file=sys.stderr)
        sys.exit(4)
    params = dict(a.split("=", 1) for i, a in enumerate(args) if i and args[i - 1] == "--param")
    seed_path = os.path.join(db, "seed.jsonl")
    nodes, edges = {}, []
    for line in open(seed_path, encoding="utf-8"):
        rec = json.loads(line)
        if rec.get("type") == "Page":
            nodes[rec["data"]["slug"]] = rec["data"]
        elif "edge" in rec:
            edges.append(rec)
    rows = []
    if name == "bm25_text":
        terms = params["q"].lower().split()
        for slug, data in nodes.items():
            text = data["text"].lower()
            rows.append({"slug": slug, "score": float(sum(text.count(t) for t in terms))})
        rows.sort(key=lambda r: (-r["score"], r["slug"]))
    else:
        m = re.fullmatch(r"neighbours_(out|in)_(\w+)", name)
        edge = m.group(2)[0].upper() + m.group(2)[1:]
        seed = params["seed"]
        for e in edges:
            if e["edge"] != edge:
                continue
            if m.group(1) == "out" and e["from"] == seed and e["to"] in nodes:
                rows.append({"slug": e["to"]})
            if m.group(1) == "in" and e["to"] == seed and e["from"] in nodes:
                rows.append({"slug": e["from"]})
        rows.sort(key=lambda r: r["slug"])
    print(json.dumps({"query": name, "rows": rows}))
    sys.exit(0)
sys.exit(2)
'''


def write_fake(path: Path) -> Path:
    path.write_text(FAKE.replace("__PYTHON__", sys.executable), encoding="utf-8")
    path.chmod(0o755)
    return path


def make_store(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "SCHEMA.json").write_text(json.dumps(SCHEMA_V1, indent=2) + "\n", encoding="utf-8")
    for rel, text in PAGES.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return path


def snapshot(store: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(store)): p.read_bytes()
        for p in sorted(store.rglob("*"))
        if p.is_file() and not ({".atlas-index", ".atlas"} & set(p.relative_to(store).parts))
    }


def read_log(log: Path) -> list[dict]:
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-drivers-"))
    saved_env = dict(os.environ)
    try:
        fake = write_fake(tmp / "nanograph")
        empty_path = tmp / "empty-bin"
        empty_path.mkdir()

        # --- registry and matrix ---------------------------------------------
        reg = driver_overlay.registry()
        check("registry-ids", sorted(reg) == ["nanograph", "native-graph", "sqlite-fts5"], str(sorted(reg)))
        check(
            "registry-capabilities",
            reg["sqlite-fts5"].capabilities == {"bm25_search"}
            and reg["native-graph"].capabilities == {"graph_traversal"}
            and reg["nanograph"].capabilities == {"bm25_search", "graph_traversal"},
        )
        check(
            "registry-external",
            reg["nanograph"].external and not reg["sqlite-fts5"].external and not reg["native-graph"].external,
        )
        check("registry-builtins-all-platforms", reg["sqlite-fts5"].platforms == () and reg["native-graph"].platforms == ())
        check("defaults-builtin", driver_overlay.DEFAULT_DRIVER == {"bm25_search": "sqlite-fts5", "graph_traversal": "native-graph"})
        rows = {(r["platform"], r["machine"]): r for r in driver_overlay.PLATFORM_MATRIX}
        check(
            "matrix-rows",
            set(rows) == {("darwin", "arm64"), ("darwin", "x86_64"), ("linux", "x86_64"), ("linux", "aarch64"), ("win32", "AMD64")},
            str(sorted(rows)),
        )
        check("matrix-darwin-arm64", rows[("darwin", "arm64")]["external"] == {"nanograph": "supported"})
        check(
            "matrix-planned-none",
            all(r["planned"] == "none" and not r["external"] for k, r in rows.items() if k != ("darwin", "arm64")),
        )
        check("normalise-aarch64", driver_overlay.normalise_machine("aarch64") == "arm64")
        try:
            reg["native-graph"].bm25_search(tmp, "x", 1)
            check("not-supported", False)
        except driver_overlay.NotSupported as e:
            check("not-supported", "native-graph" in str(e))

        # --- detection with the platform probe monkeypatched ------------------
        from atlas_cli.core.drivers import subprocess_env

        subprocess_env.set_test_passthrough_prefixes(("FAKE_NANOGRAPH_",))

        def set_platform(p: str, m: str) -> None:
            driver_overlay.set_platform_provider_for_tests(lambda: (p, m))

        driver_overlay.reset_platform_provider()
        os.environ["ATLAS_NANOGRAPH_BIN"] = str(fake)
        os.environ["PATH"] = f"{tmp}{os.pathsep}{saved_env.get('PATH', '')}"
        set_platform("linux", "x86_64")
        det = nano_mod.NanographDriver().detect()
        check("linux-unavailable", det.reason == "unavailable on linux-x86_64" and not det.available, det.reason)
        check("linux-binary-not-probed", det.binary is None and det.version is None)
        set_platform("win32", "AMD64")
        check("win-unavailable", nano_mod.NanographDriver().detect().reason == "unavailable on win32-AMD64")
        set_platform("darwin", "x86_64")
        check("darwin-intel-unavailable", nano_mod.NanographDriver().detect().reason == "unavailable on darwin-x86_64")

        set_platform("darwin", "arm64")
        os.environ.pop("ATLAS_NANOGRAPH_BIN")
        os.environ["PATH"] = str(empty_path)
        det = nano_mod.NanographDriver().detect()
        check("darwin-no-binary", det.reason == "nanograph binary not found", det.reason)
        os.environ["ATLAS_NANOGRAPH_BIN"] = str(tmp / "missing-nanograph")
        check("darwin-bad-env-path", nano_mod.NanographDriver().detect().reason == "nanograph binary not found")
        os.environ["ATLAS_NANOGRAPH_BIN"] = str(fake)
        os.environ["FAKE_NANOGRAPH_VERSION"] = "1.2.0"
        det = nano_mod.NanographDriver().detect()
        check("darwin-old-version", det.reason == "nanograph version 1.2.0 below minimum 1.3.0" and not det.available, det.reason)
        os.environ["FAKE_NANOGRAPH_VERSION"] = "garbage"
        check("darwin-unreadable", nano_mod.NanographDriver().detect().reason == "nanograph version unreadable")
        os.environ["FAKE_NANOGRAPH_VERSION"] = "1.3.0"
        det = nano_mod.NanographDriver().detect()
        check("darwin-ok", det.available and det.reason == "ok" and det.version == "1.3.0" and det.binary == str(fake.resolve()), str(det))
        os.environ.pop("ATLAS_NANOGRAPH_BIN")
        os.environ["PATH"] = f"{tmp}{os.pathsep}{saved_env.get('PATH', '')}"
        check("darwin-path-lookup", nano_mod.NanographDriver().detect().binary == str(fake.resolve()))
        # T4: a relative PATH entry or ATLAS_NANOGRAPH_BIN is made absolute at detection time.
        saved_cwd = os.getcwd()
        os.chdir(tmp)
        try:
            os.environ["PATH"] = f".{os.pathsep}{saved_env.get('PATH', '')}"
            det = nano_mod.NanographDriver().detect()
            check("darwin-relative-path-entry-absolute", det.available and det.binary == str(fake.resolve()), str(det))
            os.environ["ATLAS_NANOGRAPH_BIN"] = "nanograph"
            det = nano_mod.NanographDriver().detect()
            check("darwin-relative-bin-absolute", det.available and Path(det.binary or "").is_absolute() and det.binary == str(fake.resolve()), str(det))
        finally:
            os.chdir(saved_cwd)
        os.environ.clear()
        os.environ.update(saved_env)
        set_platform("darwin", "aarch64")
        check("provider-normalised", driver_overlay.current_platform() == ("darwin", "arm64"))
        driver_overlay.reset_platform_provider()
        check("provider-reset-real", driver_overlay.platform_provider_is_real())

        # T0: the allow-listed external driver environment.
        from atlas_cli.core.drivers.subprocess_env import external_driver_env

        child = external_driver_env(source={**SECRET_ENV, "PATH": "/bin", "HOME": "/h", "RUST_LOG": "info", "LANG": "C"})
        check(
            "driver-env-allow-list",
            set(child) == {"PATH", "HOME", "RUST_LOG", "LANG"},
            str(sorted(child)),
        )
        child = external_driver_env(extra_allowed=("GH_TOKEN", "OPENAI_API_KEY", "MY_SETTING"), source={**SECRET_ENV, "MY_SETTING": "1"})
        check("driver-env-deny-wins", set(child) == {"MY_SETTING"}, str(sorted(child)))

        # T3: no production module reads a platform override from the environment.
        offenders = [
            str(f.relative_to(ROOT))
            for f in sorted((ROOT / "scripts" / "atlas_cli").rglob("*.py"))
            if "ATLAS_PLATFORM_OVERRIDE" in f.read_text(encoding="utf-8")
            or "ATLAS_TEST_PLATFORM" in f.read_text(encoding="utf-8")
        ]
        check("no-platform-env-in-production", not offenders, str(offenders))
        check("production-entry-no-harness", "testing" not in (ROOT / "scripts" / "atlas.py").read_text(encoding="utf-8"))

        gq = nano_mod.generate_queries(["DerivedFrom"])
        check(
            "queries-generated",
            "query bm25_text($q: String)" in gq
            and "query neighbours_out_derivedFrom($seed: String)" in gq
            and "$s derivedFrom $n" in gq
            and "$n derivedFrom $s" in gq,
            gq,
        )

        # --- CLI against the fake binary --------------------------------------
        store = make_store(tmp / "store")
        log = tmp / "nanograph.log"
        env = {
            **saved_env,
            **SECRET_ENV,
            "ATLAS_TEST_PLATFORM": "darwin-arm64",
            "ATLAS_NANOGRAPH_BIN": str(fake),
            "FAKE_NANOGRAPH_LOG": str(log),
        }

        def cli(*args: str, **extra: str) -> tuple[int, dict, str]:
            proc = subprocess.run(
                [sys.executable, str(TEST_CLI), *args, "--root", str(store), "--json"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env={**env, **extra},
            )
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                data = {}
            return proc.returncode, data, proc.stdout + proc.stderr

        before = snapshot(store)
        code, p, out = cli("recall", "run", "hub", "--engine", "nanograph")
        check("recall-nanograph-exit", code == 0, out)
        check(
            "recall-nanograph-used",
            p.get("engine_configured") == "nanograph"
            and p.get("engine_used") == "nanograph"
            and p.get("driver_used") == "nanograph"
            and "driver_note" not in p
            and p.get("score_orientation") == "higher_better",
            out,
        )
        hits = p.get("hits") or []
        paths = [h["path"] for h in hits]
        _, bm25, _ = cli("recall", "run", "hub", "--engine", "bm25")
        bm25_paths = {h["path"] for h in bm25.get("hits", [])}
        check(
            "recall-nanograph-hits",
            {"work/hub.md", "notes/child-a.md", "notes/child-b.md"} <= set(paths) and set(paths) == bm25_paths,
            f"{paths} vs {sorted(bm25_paths)}",
        )
        check("recall-nanograph-positive", all(h["score"] > 0 for h in hits))
        check("recall-nanograph-shape", all(h.get("driver") == "nanograph" and "title" in h and "type" in h for h in hits))
        check("recall-nanograph-order", [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True))

        base = index_location.index_dir(store, "nanograph")
        check("index-under-project", base == store / ".atlas" / "indexes" / "nanograph" / "local" / base.name, str(base))
        check("no-legacy-index-written", not (store / ".atlas-index").exists())
        gens = sorted(d.name for d in base.iterdir() if d.is_dir()) if base.is_dir() else []
        gen = gens[0] if gens else ""
        ready = {}
        if gen:
            ready = json.loads((base / gen / "ready.json").read_text(encoding="utf-8"))
        check("index-generation", len(gens) == 1 and len(gen) == 16 and ready.get("corpus_digest", "").startswith(gen), str(gens))
        check("index-ready", ready.get("version") == "1.3.0" and bool(ready.get("built_at")), str(ready))
        pointer = json.loads((base / "current.json").read_text(encoding="utf-8")) if (base / "current.json").is_file() else {}
        check("index-pointer", pointer.get("generation") == gen and pointer.get("version") == "1.3.0", str(pointer))
        check("index-no-temp-or-lock", not [d.name for d in base.iterdir() if d.name.startswith(".")])
        check(
            "index-files",
            all((base / gen / f).exists() for f in ("atlas.gq", "atlas.nano", "export/schema.pg", "export/seed.jsonl")),
        )
        reported = p.get("nanograph_index") or {}
        check(
            "recall-index-reported",
            reported.get("generation") == gen
            and reported.get("path") == f".atlas/indexes/nanograph/local/{base.name}/{gen}"
            and reported.get("index_dir") == f".atlas/indexes/nanograph/local/{base.name}"
            and (reported.get("index_location") or {}).get("id_source") == "local",
            str(reported),
        )

        code, p, out = cli("recall", "run", "frame", "--engine", "nanograph")
        check("recall-nanograph-exits-hidden", code == 0 and p.get("engine_used") == "nanograph" and p.get("count") == 0, out)
        code, p, out = cli("recall", "run", "frame", "--engine", "nanograph", "--include-exits")
        check("recall-nanograph-exits-shown", [h["path"] for h in p.get("hits", [])] == ["old/dead.md"], out)
        code, p, out = cli("recall", "run", "hub type:decision", "--engine", "nanograph")
        check("recall-nanograph-field-filter", [h["path"] for h in p.get("hits", [])] == ["notes/child-a.md"], out)
        code, p, out = cli("recall", "run", "hub", "--engine", "nanograph", "--limit", "1")
        check("recall-nanograph-limit", p.get("count") == 1, out)

        entries = read_log(log)
        inits = [e for e in entries if e["argv"][:1] == ["init"]]
        loads = [e for e in entries if e["argv"][:1] == ["load"]]
        check("index-reused", len(inits) == 1 and len(loads) == 1, f"inits={len(inits)} loads={len(loads)}")
        # Builds run in a temporary sibling (.tmp-<generation>) published by one atomic rename.
        building = base / f".tmp-{gen}"
        check(
            "init-argv",
            bool(inits)
            and inits[0]["argv"] == ["init", "--db", str(building / "atlas.nano"), "--schema", str(building / "export" / "schema.pg")],
            str(inits[:1]),
        )
        check(
            "load-argv",
            bool(loads)
            and loads[0]["argv"] == ["load", "--db", str(building / "atlas.nano"), "--data", str(building / "export" / "seed.jsonl"), "--mode", "overwrite"],
            str(loads[:1]),
        )
        check("env-stripped", entries and not any(e["openai"] or e["gemini"] or e["embed"] for e in entries))
        probes = [e for e in entries if e["argv"] == ["--version"]]
        runs = [e for e in entries if e["argv"][:1] == ["run"]]
        leaked = sorted({k for e in entries for k in e["env_keys"] if k in SECRET_ENV})
        check("env-probe-and-run-logged", bool(probes) and bool(runs), f"probes={len(probes)} runs={len(runs)}")
        check("env-no-secrets-or-unrelated", not leaked, str(leaked))
        check(
            "env-path-home-kept",
            all({"PATH", "HOME"} <= set(e["env_keys"]) for e in probes + runs),
            str([e["env_keys"] for e in probes[:1]]),
        )
        check(
            "cwd-index",
            all(
                e["cwd"] == str(building if e["argv"][:1] in (["init"], ["load"]) else base / gen)
                for e in entries
                if e["argv"] != ["--version"]
            ),
        )
        check("no-env-nano", not list(store.rglob(".env.nano")))
        check("store-untouched", snapshot(store) == before)

        # --- neighbours parity with native-graph -------------------------------
        queries = [
            ("work/hub.md", "--direction", "in", "--kind", "implements"),
            ("work/hub.md", "--hops", "3", "--include-exits"),
            ("cycle/c2.md", "--hops", "2"),
            ("stars/p1.md", "--direction", "out", "--hops", "2", "--where", "type=work"),
            ("notes/child-a.md", "--direction", "in"),
            ("work/hub.md", "--direction", "in", "--max-nodes", "1"),
            ("notes/child-b.md",),
        ]
        for q in queries:
            code_n, native, out_n = cli("graph", "neighbours", *q)
            code_g, nano, out_g = cli("graph", "neighbours", *q, "--driver", "nanograph")
            label = " ".join(q)
            check(f"neighbours-driver-{label}", code_g == 0 and nano.get("driver_used") == "nanograph" and "driver_note" not in nano, out_g)
            check(f"neighbours-native-{label}", native.get("driver_used") == "native-graph")
            strip = lambda d: {k: v for k, v in d.items() if k not in ("driver_used",)}  # noqa: E731
            check(f"neighbours-parity-{label}", code_n == code_g and strip(native) == strip(nano), f"{native} != {nano}")
        code, p, out = cli("graph", "neighbours", "nope.md", "--driver", "nanograph")
        check("neighbours-unknown-still-exit-2", code == 2, out)
        code, p, out = cli("graph", "neighbours", "cycle/c1.md", "--driver", "nanograph")
        code2, p2, _ = cli("graph", "neighbours", "cycle/c1.md", "--driver", "nanograph")
        check("neighbours-deterministic", code == 0 and p == p2, out)
        check("index-still-reused", len([e for e in read_log(log) if e["argv"][:1] == ["init"]]) == 1)

        # --- fallback ---------------------------------------------------------
        code, p, out = cli("recall", "run", "hub", "--engine", "nanograph", FAKE_NANOGRAPH_FAIL="run")
        check(
            "fallback-run-failure",
            code == 0
            and p.get("engine_configured") == "nanograph"
            and p.get("engine_used") == "sqlite-fts5"
            and p.get("driver_used") == "sqlite-fts5"
            and p.get("driver_note") == "preferred engine nanograph failed: run failed (exit 3); used bm25"
            and p.get("count", 0) > 0
            and not p.get("warnings"),
            out,
        )
        code, p, out = cli("recall", "run", "hub", "--engine", "nanograph", FAKE_NANOGRAPH_FAIL="garble")
        check("fallback-non-json", code == 0 and p.get("driver_note") == "preferred engine nanograph failed: run bm25_text returned non-JSON output; used bm25", out)
        code, p, out = cli("graph", "neighbours", "work/hub.md", "--driver", "nanograph", FAKE_NANOGRAPH_FAIL="run")
        check(
            "fallback-neighbours",
            code == 0 and p.get("driver_used") == "native-graph" and p.get("driver_note") == "nanograph run failed (exit 3)" and p.get("count", 0) > 0,
            out,
        )
        code, p, out = cli("recall", "run", "hub", "--engine", "nanograph", ATLAS_TEST_PLATFORM="linux-x86_64")
        check(
            "fallback-platform",
            code == 0
            and p.get("engine_used") == "sqlite-fts5"
            and p.get("driver_note") == "preferred engine nanograph unavailable: unavailable on linux-x86_64; used bm25",
            out,
        )
        code, p, out = cli("graph", "neighbours", "work/hub.md", "--driver", "nanograph", ATLAS_TEST_PLATFORM="linux-x86_64")
        check("fallback-platform-neighbours", code == 0 and p.get("driver_note") == "nanograph unavailable on linux-x86_64", out)
        code, p, out = cli("recall", "run", "hub", "--engine", "nanograph", FAKE_NANOGRAPH_VERSION="1.2.0")
        check("fallback-old-version", code == 0 and p.get("driver_note") == "preferred engine nanograph unavailable: nanograph version 1.2.0 below minimum 1.3.0; used bm25", out)
        code, p, out = cli("recall", "run", "hub", "--engine", "bm25")
        check("bm25-unchanged", p.get("engine_used") == "sqlite-fts5" and "driver_note" not in p, out)
        code, p, out = cli("graph", "neighbours", "work/hub.md")
        check("native-default", p.get("driver_used") == "native-graph" and "driver_note" not in p, out)

        # --- generations: rebuild on change, keep two newest -------------------
        for i in range(3):
            (store / "notes" / f"extra-{i}.md").write_text(
                f"---\ntype: lesson\ntitle: Extra {i}\ncreated: 2026-09-09\n---\n\nExtra hub note {i}.\n",
                encoding="utf-8",
            )
            code, p, out = cli("recall", "run", "hub", "--engine", "nanograph")
            check(f"rebuild-{i}", code == 0 and p.get("engine_used") == "nanograph" and (p.get("nanograph_index") or {}).get("reused") is False, out)
        gens_after = sorted(d.name for d in base.iterdir() if d.is_dir())
        current = (p.get("nanograph_index") or {}).get("generation")
        check("generations-pruned", len(gens_after) == 2 and current in gens_after and gen not in gens_after, str(gens_after))

        # --- symlink escape ----------------------------------------------------
        outside = tmp / "outside"
        outside.mkdir()
        shutil.rmtree(base)
        base.symlink_to(outside, target_is_directory=True)
        code, p, out = cli("recall", "run", "hub", "--engine", "nanograph")
        check(
            "symlink-rejected",
            code == 0 and p.get("engine_used") == "sqlite-fts5" and "index path rejected" in str(p.get("driver_note")),
            out,
        )
        check("symlink-outside-untouched", not any(outside.iterdir()))
        base.unlink()

        # --- drivers command ----------------------------------------------------
        code, p, out = cli("graph", "drivers")
        ids = [d["id"] for d in p.get("drivers", [])]
        nano = next((d for d in p.get("drivers", []) if d["id"] == "nanograph"), {})
        check("drivers-cmd", code == 0 and ids == ["sqlite-fts5", "native-graph", "nanograph"], out)
        check("drivers-cmd-detect", nano.get("detect", {}).get("available") is True and p.get("platform", {}).get("label") == "darwin-arm64", out)
        check("drivers-cmd-matrix", len(p.get("matrix", [])) == 5)
        check(
            "drivers-cmd-index-dir",
            str(nano.get("index_dir") or "").startswith(".atlas/indexes/nanograph/local/")
            and (nano.get("index_location") or {}).get("mode") == "standalone",
            str(nano),
        )
        code, p, out = cli("graph", "drivers", ATLAS_TEST_PLATFORM="linux-x86_64")
        nano = next((d for d in p.get("drivers", []) if d["id"] == "nanograph"), {})
        check("drivers-cmd-linux", nano.get("detect", {}).get("reason") == "unavailable on linux-x86_64", out)
        human = subprocess.run(
            [sys.executable, str(TEST_CLI), "graph", "drivers", "--root", str(store)],
            cwd=ROOT, text=True, capture_output=True, env={**env, "ATLAS_TEST_PLATFORM": "linux-x86_64"},
        )
        check("drivers-human", human.returncode == 0 and "unavailable on linux-x86_64" in human.stdout, human.stdout)

        # --- T3: the production entry ignores every platform env var ------------
        import platform as _platform

        prod_log = tmp / "prod-nanograph.log"
        (tmp / "prodbin").mkdir()
        prod_fake = write_fake(tmp / "prodbin" / "nanograph")
        real_label = driver_overlay.platform_label(
            (sys.platform, driver_overlay.normalise_machine(_platform.machine()))
        )
        if real_label != "darwin-arm64":
            prod = subprocess.run(
                [sys.executable, str(ATLAS), "graph", "drivers", "--root", str(store), "--json"],
                cwd=ROOT, text=True, capture_output=True,
                env={
                    **env,
                    "ATLAS_PLATFORM_OVERRIDE": "darwin-arm64",
                    "ATLAS_TEST_PLATFORM": "darwin-arm64",
                    "FAKE_NANOGRAPH_LOG": str(prod_log),
                    "ATLAS_NANOGRAPH_BIN": str(prod_fake),
                },
            )
            try:
                pdata = json.loads(prod.stdout)
            except json.JSONDecodeError:
                pdata = {}
            pnano = next((d for d in pdata.get("drivers", []) if d["id"] == "nanograph"), {})
            check(
                "production-ignores-platform-env",
                prod.returncode == 0
                and pnano.get("detect", {}).get("reason") == f"unavailable on {real_label}"
                and (pdata.get("platform") or {}).get("label") == real_label,
                prod.stdout + prod.stderr,
            )
            check("production-fake-not-executed", not prod_log.exists() and not Path(str(prod_fake.resolve()) + ".calls").exists())

        # --- T4: relative ATLAS_NANOGRAPH_BIN keeps working for build + query -----
        rel_cwd = tmp / "relcwd"
        (rel_cwd / "bin").mkdir(parents=True)
        write_fake(rel_cwd / "bin" / "nanograph")
        rel_store = make_store(tmp / "relstore")
        rel_log = tmp / "rel-nanograph.log"
        rel_env = {**env, "ATLAS_NANOGRAPH_BIN": "bin/nanograph", "FAKE_NANOGRAPH_LOG": str(rel_log)}
        rel = subprocess.run(
            [sys.executable, str(TEST_CLI), "index", "build", "--root", str(rel_store), "--json"],
            cwd=rel_cwd, text=True, capture_output=True, env={**rel_env, "ATLAS_RECALL_ENGINE": "nanograph"},
        )
        try:
            rdata = json.loads(rel.stdout)
        except json.JSONDecodeError:
            rdata = {}
        check(
            "relative-bin-build",
            rel.returncode == 0 and rdata.get("status") == "built" and rdata.get("engine_effective") == "nanograph",
            rel.stdout + rel.stderr,
        )
        relq = subprocess.run(
            [sys.executable, str(TEST_CLI), "recall", "run", "hub", "--engine", "nanograph", "--root", str(rel_store), "--json"],
            cwd=rel_cwd, text=True, capture_output=True, env=rel_env,
        )
        try:
            qdata = json.loads(relq.stdout)
        except json.JSONDecodeError:
            qdata = {}
        check(
            "relative-bin-query",
            relq.returncode == 0 and qdata.get("engine_used") == "nanograph" and "driver_note" not in qdata,
            relq.stdout + relq.stderr,
        )
        saved_cwd = os.getcwd()
        os.chdir(rel_cwd)
        try:
            os.environ["ATLAS_NANOGRAPH_BIN"] = "bin/nanograph"
            set_platform("darwin", "arm64")
            det = nano_mod.NanographDriver().detect()
            check("relative-bin-detect-absolute", Path(det.binary or "").is_absolute() and det.available, str(det))
        finally:
            os.chdir(saved_cwd)
            driver_overlay.reset_platform_provider()
    finally:
        driver_overlay.reset_platform_provider()
        subprocess_env.reset_test_passthrough()
        os.environ.clear()
        os.environ.update(saved_env)
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} driver check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll driver checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
