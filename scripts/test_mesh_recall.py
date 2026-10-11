#!/usr/bin/env python3
"""Federated recall (M7, M11, M12, M14, M20): ``recall run --scope mesh`` on temp meshes.

Covers atlas ids and URIs on every hit, grep and bm25 members, scope and k
precedence with their sources, store scope unchanged, exit 2 and exit 1
cases, the restricted pre-filter, an excluded member that is never touched,
``invalid`` members (outside the project, invalid atlas id) that are never
read and are reported, percent-encoded node ids for a page path with ``#``,
members searched through their pinned mesh index location, canary privacy over ``.atlas/indexes/`` and the ``rrf-interleave-noise``
probe. Linux-safe: no network, no git.
"""

from __future__ import annotations

import contextlib
import io
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

from atlas_cli.commands import search as search_cmd  # noqa: E402
from atlas_cli.core import index_location, mesh_recall, mesh_scope  # noqa: E402
from test_mesh_members import Guard  # noqa: E402

ALPHA = "github.com/acme/alpha"
BETA = "github.com/acme/beta"
GAMMA = "github.com/acme/gamma"
SECRET = "github.com/acme/secret"
GONE = "github.com/acme/gone"
CLEAN_ENV = ("ATLAS_INDEX_ROOT", "ATLAS_RECALL_ENGINE", "ATLAS_TEST_PLATFORM", "ATLAS_NANOGRAPH_BIN")
QUERY = "graph export nanograph"

# Canaries: one per text field per store, and one for restricted pages and the excluded store.
CANARY = {
    ALPHA: ("ALPHATITLEQUOLL", "ALPHADESCQUOLL", "ALPHABODYQUOLL"),
    BETA: ("BETATITLEQUOLL", "BETADESCQUOLL", "BETABODYQUOLL"),
    GAMMA: ("GAMMATITLEQUOLL", "GAMMADESCQUOLL", "GAMMABODYQUOLL"),
}
RESTRICTED = {ALPHA: "ALPHARESTRICTEDWOMBAT", BETA: "BETARESTRICTEDWOMBAT"}
EXCLUDED = "SECRETSTOREWOMBAT"
HASH = "github.com/acme/hash"
SUB = "github.com/acme/sub"
ESCAPE = "github.com/acme/escape"
NOID = "/acme/noid"
INVALID_CANARY = "INVALIDMEMBERWOMBAT"
HASH_PAGE = "notes/c#sharp graph.md"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def page(title: str, desc: str, body: str, extra: str = "") -> str:
    return f"---\ntype: lesson\ntitle: {title}\ndescription: {desc}\ncreated: 2026-10-10\n{extra}---\n\n{body}\n"


def restricted_page(canary: str, words: str) -> str:
    # Every field carries the canary, and the query words dominate so it would rank first.
    return (
        "---\n"
        f"type: lesson\ntitle: {words} {words} {canary}\ndescription: {words} {canary}\n"
        f"tags: [{canary}]\nstatus: {canary}\nwork_id: {canary}\norigin: {canary}\n"
        f"sensitivity: restricted\ncreated: 2026-10-10\n"
        f"relates_to:\n  - path: notes/{canary}.md\n    kind: related\n"
        f"---\n\n{words} {words} {words} {canary} body.\n"
    )


def schema(store: Path) -> None:
    write(store / "SCHEMA.json", json.dumps({"schema_version": "1.0", "title": "fixture"}) + "\n")


def build_mesh(tmp: Path, *, recall: dict | None = None, three: bool = True, broken_gamma: bool = False) -> Path:
    """alpha (bm25 by row preference), beta (bm25, any-word only), [gamma (grep)], secret (excluded), gone."""
    project = tmp / "proj"
    alpha = project / "atlas" / "alpha"
    schema(alpha)
    at, ad, ab = CANARY[ALPHA]
    write(alpha / "notes" / "export.md", page(f"Graph export to nanograph {at}", f"How export works {ad}", f"The graph export nanograph path {ab}."))
    write(alpha / "notes" / "export-two.md", page("Second export note", "More about graph export", "Graph export feeds nanograph in batches."))
    write(alpha / "notes" / "export-three.md", page("Third note", "Notes", "graph and export and nanograph once each."))
    write(alpha / "notes" / "secret.md", restricted_page(RESTRICTED[ALPHA], QUERY))
    write(alpha / "notes" / "unrelated.md", page("Gardening", "Plants", "Tomatoes grow in summer."))

    beta = project / "atlas" / "beta"
    schema(beta)
    bt, bd, bb = CANARY[BETA]
    write(beta / "notes" / "graph-one.md", page(f"Graph basics {bt}", f"Nodes and edges {bd}", f"A graph has nodes {bb}."))
    write(beta / "notes" / "graph-two.md", page("Graph walks", "Walking", "Walk the graph breadth first."))
    write(beta / "notes" / "graph-three.md", page("Graph sizes", "Sizes", "Counting a graph is cheap."))
    # Restricted: matches all words, so without the pre-filter beta would answer with all-words.
    write(beta / "notes" / "hidden.md", restricted_page(RESTRICTED[BETA], QUERY))

    stores = [
        {"id": ALPHA, "path": "atlas/alpha", "recall": {"engine": "bm25"}},
        {"id": SECRET, "path": "atlas/secret", "mesh_member": False},
        {"id": BETA, "path": "atlas/beta", "recall": {"engine": "bm25"}},
    ]
    if three:
        gamma = project / "atlas" / "gamma"
        if broken_gamma:
            write(gamma / "SCHEMA.json", "{ broken\n")
        else:
            schema(gamma)
        gt, gd, gb = CANARY[GAMMA]
        write(gamma / "notes" / "nano.md", page(f"Nanograph notes {gt}", f"Graph export tips {gd}", f"Export a graph to nanograph {gb}."))
        write(gamma / "notes" / "other.md", page("Other", "Other", "Nothing relevant here."))
        stores.append({"id": GAMMA, "path": "atlas/gamma"})
    secret = project / "atlas" / "secret"
    schema(secret)
    write(secret / "notes" / "s.md", page(f"{QUERY} {EXCLUDED}", f"{EXCLUDED} {QUERY}", f"{QUERY} {EXCLUDED} body"))
    stores.append({"id": GONE, "path": "atlas/gone"})
    doc: dict = {"version": 1, "stores": stores}
    if recall is not None:
        doc["recall"] = recall
    write(project / "atlas-mesh.json", json.dumps(doc, indent=2) + "\n")
    return project


def build_edge_mesh(tmp: Path) -> Path:
    """hash (a page path with ``#``), sub (a subpath row), escape (outside the project), noid (invalid id)."""
    project = tmp / "proj"
    hashed = project / "atlas" / "hash"
    schema(hashed)
    write(hashed / HASH_PAGE, page("Sharp graph export", "Graph export with a hash", "Graph export nanograph sharp."))
    sub = project / "atlas" / "mono" / "kb"
    schema(sub)
    write(sub / "notes" / "sub.md", page("Sub graph export", "Graph export in a subpath", "Graph export nanograph sub."))
    for store in (tmp / "outside", project / "atlas" / "noid"):
        schema(store)
        write(store / "notes" / "bait.md", page(f"{QUERY} {INVALID_CANARY}", f"{INVALID_CANARY} {QUERY}", f"{QUERY} {INVALID_CANARY}"))
    stores = [
        {"id": HASH, "path": "atlas/hash"},
        {"id": ESCAPE, "path": "../outside"},
        {"id": NOID, "path": "atlas/noid"},
        {"id": SUB, "path": "atlas/mono", "subpath": "kb"},
    ]
    write(project / "atlas-mesh.json", json.dumps({"version": 1, "stores": stores}, indent=2) + "\n")
    return project


def env() -> dict[str, str]:
    out = {k: v for k, v in os.environ.items() if k not in CLEAN_ENV}
    out["DBUS_SESSION_BUS_ADDRESS"] = "disabled:"
    return out


def atlas(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run([sys.executable, str(ATLAS), *args], cwd=ROOT, text=True, capture_output=True, env=env())
    return proc.returncode, proc.stdout, proc.stderr


def recall(root: Path, *extra: str, query: str = QUERY, as_json: bool = True) -> tuple[int, dict | str, str]:
    args = ["recall", "run", query, "--root", str(root), *extra]
    if as_json:
        args.append("--json")
    code, out, err = atlas(*args)
    if not as_json:
        return code, out, err
    try:
        return code, json.loads(out), err
    except ValueError:
        return code, {"_raw": out}, err


def files_under(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*") if p.is_file()) if base.exists() else []


def main() -> int:
    failed: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail if not ok else ''}".rstrip())
        if not ok:
            failed.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="atlas-mesh-recall-"))
    outputs: list[str] = []
    try:
        project = build_mesh(tmp)
        alpha = project / "atlas" / "alpha"
        beta = project / "atlas" / "beta"
        secret = project / "atlas" / "secret"

        # --- three-store mesh, mixed engines --------------------------------------
        code, p, err = recall(project, "--scope", "mesh")
        outputs.append(json.dumps(p) + err)
        check("mesh-exit-0", code == 0, f"{code} {err} {p}")
        check("mesh-payload-scope", p.get("scope") == "mesh" and p.get("scope_source") == "cli")
        check("mesh-k-default", p.get("rrf_k") == 60 and p.get("rrf_k_source") == "default")
        check("mesh-complete", p.get("complete") is True)
        hits = p.get("hits") or []
        check("mesh-has-hits", len(hits) >= 5, str(len(hits)))
        check(
            "every-hit-has-atlas-id-and-uri",
            all(h.get("atlas_id") and h.get("uri") == mesh_scope.node_id(h["atlas_id"], h["path"]) for h in hits),
        )
        check(
            "hit-keys",
            all(list(h) == ["atlas_id", "path", "uri", "title", "member_rank", "tier", "rrf_score", "engine_used"] for h in hits),
        )
        members = {m["atlas_id"]: m for m in p.get("members") or []}
        check("members-in-row-order", [m["atlas_id"] for m in p["members"]] == [ALPHA, SECRET, BETA, GAMMA, GONE])
        check(
            "member-keys",
            all({"atlas_id", "status", "engine_requested", "engine_used", "driver_note", "match", "hits"} <= set(m) for m in p["members"]),
        )
        check("member-statuses", [m["status"] for m in p["members"]] == ["ok", "excluded", "ok", "ok", "unmounted"])
        check("alpha-bm25", members[ALPHA]["engine_requested"] == "bm25" and members[ALPHA]["engine_used"] == "sqlite-fts5")
        check("beta-bm25-any", members[BETA]["engine_used"] == "sqlite-fts5" and members[BETA]["match"] == "any", str(members[BETA]))
        check("gamma-grep", members[GAMMA]["engine_requested"] == "grep" and members[GAMMA]["engine_used"] == "grep")
        check("alpha-match-all", members[ALPHA]["match"] == "all")
        check("hit-engine-matches-member", all(h["engine_used"] == members[h["atlas_id"]]["engine_used"] for h in hits))
        check("hit-counts-match-member", all(
            members[a]["hits"] == sum(1 for h in hits if h["atlas_id"] == a) for a in (ALPHA, BETA, GAMMA)
        ), str({a: members[a]["hits"] for a in members}))
        check("titles-from-member", any(h["title"].startswith("Graph export to nanograph") for h in hits))
        check("excluded-not-in-hits", all(h["atlas_id"] != SECRET for h in hits))
        check("unmounted-never-mounted", not (project / "atlas" / "gone").exists())

        # rrf-interleave-noise: alpha (all words) and beta (any-word retry only).
        tiers = [h["tier"] for h in hits]
        check("probe-every-tier-1-before-tier-2", tiers == sorted(tiers) and 2 in tiers and 1 in tiers, str(tiers))
        check("probe-beta-is-tier-2", all(h["tier"] == 2 for h in hits if h["atlas_id"] == BETA))
        check("probe-alpha-is-tier-1", all(h["tier"] == 1 for h in hits if h["atlas_id"] == ALPHA))
        beta_first = next(h for h in hits if h["atlas_id"] == BETA)
        tier1_last = [h for h in hits if h["tier"] == 1][-1]
        check(
            "probe-plain-rrf-would-interleave",
            beta_first["rrf_score"] > tier1_last["rrf_score"] and hits.index(beta_first) > hits.index(tier1_last),
        )

        # Restricted pre-filter: the restricted page ranks first in store scope, never in mesh scope.
        code_s, store_alpha, _ = recall(alpha, "--engine", "bm25")
        check("restricted-ranks-first-in-store-scope", code_s == 0 and store_alpha["hits"][0]["path"] == "notes/secret.md")
        code_b, store_beta, _ = recall(beta, "--engine", "bm25")
        check("beta-store-scope-matches-all-via-restricted", store_beta.get("match") == "all" and store_beta["count"] == 1)
        check("restricted-absent-from-hits", all(h["path"] not in ("notes/secret.md", "notes/hidden.md") for h in hits))
        check("alpha-count-excludes-restricted", members[ALPHA]["hits"] == 3, str(members[ALPHA]["hits"]))
        check("beta-count-excludes-restricted", members[BETA]["hits"] == 3, str(members[BETA]["hits"]))
        check("alpha-ranks-start-at-1", [h["member_rank"] for h in hits if h["atlas_id"] == ALPHA] == [1, 2, 3])

        # Text output: one line per hit led by its atlas id, then one member line.
        code_t, text, err_t = recall(project, "--scope", "mesh", as_json=False)
        outputs.append(text + err_t)
        lines = text.splitlines()
        check("text-exit-0", code_t == 0)
        check("text-one-line-per-hit", len(lines) == len(hits) + 1, str(lines))
        check("text-hit-lines-lead-with-atlas-id", all(line.split(" ", 1)[0] == h["atlas_id"] for line, h in zip(lines, hits)))
        check("text-member-summary", lines[-1].startswith("members (complete=true rrf_k=60): ") and f"{SECRET} excluded" in lines[-1])

        # Determinism: byte-identical JSON on a second run.
        _, out1, _ = atlas("recall", "run", QUERY, "--root", str(project), "--scope", "mesh", "--json")
        _, out2, _ = atlas("recall", "run", QUERY, "--root", str(project), "--scope", "mesh", "--json")
        check("deterministic-json", out1 == out2)

        # Mesh found from a member store root too; --limit truncates; --engine applies to every member.
        code_m, from_store, _ = recall(beta, "--scope", "mesh", "--limit", "2")
        check("mesh-from-member-root", code_m == 0 and from_store["project"] == str(project.resolve()))
        check("limit-truncates", from_store["count"] == 2 and len(from_store["hits"]) == 2)
        check("overfetch-2x-limit", from_store["members"][0]["hits"] <= 4 and from_store["members"][0]["hits"] == 3)
        code_g, all_grep, _ = recall(project, "--scope", "mesh", "--engine", "grep")
        outputs.append(json.dumps(all_grep))
        check(
            "engine-flag-applies-to-every-member",
            code_g == 0 and all(m["engine_requested"] == "grep" for m in all_grep["members"] if m["status"] == "ok"),
        )
        check("grep-lists-are-tier-1", all(h["tier"] == 1 for h in all_grep["hits"]))
        check("grep-restricted-absent", all(h["path"] not in ("notes/secret.md", "notes/hidden.md") for h in all_grep["hits"]))

        # --- precedence: scope and k ------------------------------------------------
        def store_payload_equal(root: Path, *extra: str) -> bool:
            a = atlas("recall", "run", QUERY, "--root", str(root), "--json", *extra)
            b = atlas("recall", "run", QUERY, "--root", str(root), "--json", "--scope", "store", *extra)
            return a == b and "scope" not in json.loads(a[1])

        check("store-scope-unchanged-alpha", store_payload_equal(alpha))
        check("store-scope-unchanged-gamma-text", atlas("recall", "run", QUERY, "--root", str(project / "atlas" / "gamma"))
              == atlas("recall", "run", QUERY, "--root", str(project / "atlas" / "gamma"), "--scope", "store"))
        code_d, default_scope, _ = recall(alpha)
        check("default-scope-is-store", code_d == 0 and "scope" not in default_scope and "hits" in default_scope)

        cfg = tmp / "cfg"
        cfg.mkdir()
        project_cfg = build_mesh(cfg, recall={"scope": "mesh", "rrf_k": 10})
        code_c, from_cfg, _ = recall(project_cfg / "atlas" / "alpha")
        check("config-scope-mesh", code_c == 0 and from_cfg.get("scope") == "mesh" and from_cfg["scope_source"] == "project")
        check("config-k", from_cfg.get("rrf_k") == 10 and from_cfg["rrf_k_source"] == "project")
        first = from_cfg["hits"][0]
        check("config-k-used-in-score", abs(first["rrf_score"] - 1 / (10 + first["member_rank"])) < 1e-12)
        code_k, flag_k, _ = recall(project_cfg, "--rrf-k", "5")
        check("flag-k-beats-config", code_k == 0 and flag_k["rrf_k"] == 5 and flag_k["rrf_k_source"] == "cli")
        code_f, flag_scope, _ = recall(project_cfg / "atlas" / "alpha", "--scope", "store")
        check("flag-scope-beats-config", code_f == 0 and "scope" not in flag_scope and flag_scope["root"].endswith("alpha"))
        code_fk, _, _ = recall(project_cfg / "atlas" / "alpha", "--scope", "store", "--rrf-k", "5")
        check("flag-store-with-rrf-k-exit-2", code_fk == 2)

        cfg2 = tmp / "cfg2"
        cfg2.mkdir()
        project_store_cfg = build_mesh(cfg2, recall={"scope": "store", "rrf_k": 60})
        code_sc, store_cfg, _ = recall(project_store_cfg / "atlas" / "alpha")
        check("config-scope-store-unchanged", code_sc == 0 and "scope" not in store_cfg)
        code_sm, store_cfg_mesh, _ = recall(project_store_cfg / "atlas" / "alpha", "--scope", "mesh")
        check("flag-mesh-beats-config-store", code_sm == 0 and store_cfg_mesh["scope_source"] == "cli" and store_cfg_mesh["rrf_k_source"] == "project")

        # --- exit 2 -------------------------------------------------------------------
        lone = tmp / "lone"
        schema(lone)
        write(lone / "notes" / "a.md", page("Graph", "Graph", "graph export nanograph"))
        code_l, lone_p, _ = recall(lone, "--scope", "mesh")
        check("standalone-mesh-exit-2", code_l == 2 and "no atlas-mesh.json lists this store" in str(lone_p.get("error")), str(lone_p))
        code_lt, _, _ = recall(lone, "--scope", "mesh", as_json=False)
        check("standalone-mesh-text-exit-2", code_lt == 2)
        code_lk, lone_k, _ = recall(lone, "--rrf-k", "60")
        check("standalone-rrf-k-exit-2", code_lk == 2 and "--rrf-k" in str(lone_k.get("error")))
        code_sk, _, _ = recall(alpha, "--scope", "store", "--rrf-k", "60")
        check("store-scope-rrf-k-exit-2", code_sk == 2)
        code_dk, _, _ = recall(alpha, "--rrf-k", "60")
        check("default-scope-rrf-k-exit-2", code_dk == 2)
        code_pr, prof, _ = recall(project, "--scope", "mesh", "--profile", "atlas:ranked")
        check("profile-with-mesh-exit-2", code_pr == 2 and "per store" in str(prof.get("error")))
        code_pc, _, _ = recall(project_cfg / "atlas" / "alpha", "--profile", "atlas:ranked")
        check("profile-with-config-mesh-exit-2", code_pc == 2)
        code_ap, _, _ = recall(project, "--scope", "mesh", "--allow-partial")
        check("allow-partial-with-mesh-exit-2", code_ap == 2)
        for bad in ("0", "1001", "abc", "6.5", "-1"):
            code_b2, bad_p, _ = recall(project, "--scope", "mesh", "--rrf-k", bad)
            check(f"rrf-k-{bad}-exit-2", code_b2 == 2 and "--rrf-k" in str(bad_p.get("error")), str(bad_p))
        for good in ("1", "1000"):
            code_g2, good_p, _ = recall(project, "--scope", "mesh", "--rrf-k", good)
            check(f"rrf-k-{good}-ok", code_g2 == 0 and good_p["rrf_k"] == int(good))

        # --- exit 1: one member's SCHEMA.json is broken ---------------------------------
        broken = tmp / "broken"
        broken.mkdir()
        project_broken = build_mesh(broken, broken_gamma=True)
        code_x, part, _ = recall(project_broken, "--scope", "mesh")
        bm = {m["atlas_id"]: m for m in part["members"]}
        check("broken-member-exit-1", code_x == 1, str(code_x))
        check("broken-member-complete-false", part.get("complete") is False)
        check("broken-member-status-error", bm[GAMMA]["status"] == "error" and bool(bm[GAMMA].get("error")), str(bm[GAMMA]))
        check("others-still-answer", bm[ALPHA]["status"] == "ok" and bm[BETA]["status"] == "ok" and len(part["hits"]) > 0)
        check("broken-member-no-hits", all(h["atlas_id"] != GAMMA for h in part["hits"]))
        code_xt, text_x, _ = recall(project_broken, "--scope", "mesh", as_json=False)
        check("broken-member-text-exit-1", code_xt == 1 and f"{GAMMA} error (" in text_x and "complete=false" in text_x)

        # --- two-store mesh -------------------------------------------------------------
        two = tmp / "two"
        two.mkdir()
        project_two = build_mesh(two, three=False)
        code_2, two_p, _ = recall(project_two, "--scope", "mesh", "--engine", "bm25")
        outputs.append(json.dumps(two_p))
        check("two-store-exit-0", code_2 == 0 and {h["atlas_id"] for h in two_p["hits"]} == {ALPHA, BETA})
        check("two-store-uris", all(h["uri"].startswith(f"atlas://{h['atlas_id']}/") for h in two_p["hits"]))

        # --- invalid members are never read and are reported; '#' paths are encoded ----
        edge = tmp / "edge"
        edge.mkdir()
        project_edge = build_edge_mesh(edge)
        code_e, edge_p, err_e = recall(project_edge, "--scope", "mesh")
        outputs.append(json.dumps(edge_p) + err_e)
        em = {m["atlas_id"]: m for m in edge_p.get("members") or []}
        check("edge-exit-0", code_e == 0 and edge_p.get("complete") is True, f"{code_e} {err_e} {edge_p}")
        check(
            "invalid-members-reported",
            [(m["atlas_id"], m["status"], m.get("reason")) for m in edge_p["members"]]
            == [
                (HASH, "ok", None),
                (ESCAPE, "invalid", "outside_project"),
                (NOID, "invalid", "invalid_atlas_id"),
                (SUB, "ok", None),
            ],
            str(edge_p.get("members")),
        )
        check("invalid-members-no-hits", all(h["atlas_id"] in (HASH, SUB) for h in edge_p["hits"]) and em[ESCAPE]["hits"] == 0)
        check("invalid-members-never-output", INVALID_CANARY not in json.dumps(edge_p) and "bait.md" not in json.dumps(edge_p))
        check("invalid-members-no-index", not any((project_edge / ".atlas" / "indexes" / k / ESCAPE).exists() for k in ("fts5", "nanograph")))
        code_et, text_e, _ = recall(project_edge, "--scope", "mesh", as_json=False)
        outputs.append(text_e)
        check(
            "invalid-members-text",
            code_et == 0 and f"{ESCAPE} invalid (outside_project)" in text_e and f"{NOID} invalid (invalid_atlas_id)" in text_e,
            text_e[-300:],
        )
        hash_hits = [h for h in edge_p["hits"] if h["atlas_id"] == HASH]
        check("hash-page-hit", [h["path"] for h in hash_hits] == [HASH_PAGE], str(edge_p["hits"]))
        if hash_hits:
            uri = hash_hits[0]["uri"]
            check("hash-page-uri-encoded", uri == f"atlas://{HASH}/notes/c%23sharp%20graph.md", uri)
            check("hash-page-uri-round-trips", mesh_scope.parse_node_id(uri) == (HASH, HASH_PAGE), uri)
        index_location.clear_cache()
        settings_e = mesh_recall.resolve_settings(project_edge, "mesh")
        seen: dict[str, tuple[str, str]] = {}

        def spy(root: Path, *_: object) -> mesh_recall.MemberAnswer:
            loc = index_location.resolve(root)
            seen[loc.atlas_id] = (str(loc.project_root), loc.mode)
            return mesh_recall.MemberAnswer([], "all", "grep", "grep", None)

        with Guard(edge / "outside") as g_out, Guard(project_edge / "atlas" / "noid") as g_noid:
            payload_e, code_spy = mesh_recall.federate(settings_e, QUERY, search=spy)
        check("invalid-member-roots-never-touched", g_out.hits == [] and g_noid.hits == [], str(g_out.hits[:3] + g_noid.hits[:3]))
        check("spy-only-ok-members", code_spy == 0 and sorted(seen) == sorted([HASH, SUB]), str(seen))
        check(
            "members-search-through-pinned-location",
            all(v == (str(project_edge.resolve()), "mesh") for v in seen.values()),
            str(seen),
        )
        check("pin-released", str(project_edge.resolve() / "atlas" / "mono" / "kb") not in index_location._pins.get())

        # --- excluded member never touched (in process, file access patched) -------------
        index_location.clear_cache()
        buf, ebuf = io.StringIO(), io.StringIO()
        with Guard(secret) as guard, contextlib.redirect_stdout(buf), contextlib.redirect_stderr(ebuf):
            code_in = search_cmd.run_scoped(str(project), QUERY, 10, True, None, False, None, False, "mesh", None)
        check("guard-run-exit-0", code_in == 0, ebuf.getvalue()[:300])
        check("excluded-member-root-never-touched", guard.hits == [], str(guard.hits[:5]))
        payload_in = json.loads(buf.getvalue())
        check("guard-run-same-hits", [h["uri"] for h in payload_in["hits"]] == [h["uri"] for h in hits])
        index_location.clear_cache()
        with Guard(secret) as probe:
            try:
                (secret / "SCHEMA.json").read_text(encoding="utf-8")
            except PermissionError:
                pass
        check("guard-is-effective", bool(probe.hits))

        # --- canary privacy: five federated queries, then scan .atlas/indexes ------------
        queries = [QUERY, "graph", "export nanograph", RESTRICTED[ALPHA], EXCLUDED]
        for q in queries:
            # The payload echoes the query; mask it so only leaked page content can match.
            for extra in ((), ("--engine", "bm25")):
                code_q, out_q, err_q = atlas("recall", "run", q, "--root", str(project), "--scope", "mesh", "--json", *extra)
                outputs.append((out_q + err_q).replace(q, "<QUERY>"))
                check(f"canary-query-{q[:12]}-{len(extra)}-exit-0", code_q == 0, err_q[:200])
                if q in (RESTRICTED[ALPHA], EXCLUDED):
                    check(f"canary-query-{q[:12]}-{len(extra)}-no-hits", json.loads(out_q)["count"] == 0)
            code_q, out_q, err_q = atlas("recall", "run", q, "--root", str(project), "--scope", "mesh")
            outputs.append((out_q + err_q).replace(q, "<QUERY>"))
        indexes = project / ".atlas" / "indexes"
        all_files = files_under(indexes)
        check("indexes-exist", bool(all_files))
        check("no-mesh-dir", not any(p.name == "_mesh" for p in indexes.rglob("*")) and not list(project.rglob("_mesh")))
        member_dirs = {
            sid: [indexes / kind / sid for kind in ("fts5", "nanograph", "graph", "tgrep")] for sid in (ALPHA, BETA, GAMMA)
        }

        def owner(path: Path) -> str | None:
            for sid, dirs in member_dirs.items():
                if any(path.is_relative_to(d) for d in dirs):
                    return sid
            return None

        stray = [p for p in all_files if owner(p) is None]
        check("only-per-store-index-files", stray == [], str(stray[:5]))
        leaks: list[str] = []
        for path in all_files:
            data = path.read_bytes()
            who = owner(path)
            for sid, words in CANARY.items():
                for word in words:
                    if word.encode() in data and who != sid:
                        leaks.append(f"{word} in {path.relative_to(indexes)}")
            for sid, word in RESTRICTED.items():
                if word.encode() in data and who != sid:
                    leaks.append(f"{word} in {path.relative_to(indexes)}")
            if EXCLUDED.encode() in data:
                leaks.append(f"{EXCLUDED} in {path.relative_to(indexes)}")
        check("no-canary-outside-own-index", leaks == [], str(leaks[:5]))
        check("alpha-own-index-built", any(owner(p) == ALPHA for p in all_files))
        check("no-excluded-index", not any((indexes / kind / SECRET).exists() for kind in ("fts5", "nanograph")))
        joined = "\n".join(outputs)
        forbidden = [w for w in (*RESTRICTED.values(), EXCLUDED) if w in joined]
        check("restricted-and-excluded-canaries-never-output", forbidden == [], str(forbidden))
        check("restricted-paths-never-output", "notes/secret.md" not in joined and "notes/hidden.md" not in joined)
        check("excluded-paths-never-output", "notes/s.md" not in joined)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failed:
        print(f"\n{len(failed)} mesh recall check(s) failed: {', '.join(failed[:10])}")
        return 1
    print("\nAll mesh recall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
