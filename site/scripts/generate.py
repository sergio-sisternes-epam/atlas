#!/usr/bin/env python3
"""Generate the Atlas docs pages that mirror an Atlas release tag.

Usage:
    python3 site/scripts/generate.py --atlas-src <dir> [--check]

Writes (relative to the site directory):
    src/content/docs/reference/cli/<verb>.md   one page per Click command and group
    src/content/docs/reference/cli/atlas-optimise-script.md
    src/content/docs/modules/index.md          table from the SKILL.md Path registry
    src/content/docs/project/changelog.md      CHANGELOG.md body with a short lead
    src/data/atlas-build.json                  {"tag", "commit", "version"}

Only non-mutating ``--help`` invocations are run. Output is byte-deterministic.
``--check`` regenerates into a temporary directory and diffs against the
committed files (check V1).

Dependencies: Python 3.10+, the standard library and PyYAML. Walking the CLI
imports ``atlas_cli`` from ``<atlas-src>/scripts``, so the Atlas CLI
requirements (``<atlas-src>/scripts/requirements.txt``) must be installed.
"""

from __future__ import annotations

import argparse
import difflib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.dont_write_bytecode = True

SITE_DIR = Path(__file__).resolve().parent.parent
DOCS_REL = Path("src/content/docs")
CLI_REL = DOCS_REL / "reference" / "cli"
MODULES_INDEX_REL = DOCS_REL / "modules" / "index.md"
CHANGELOG_REL = DOCS_REL / "project" / "changelog.md"
BUILD_JSON_REL = Path("src/data/atlas-build.json")
OPTIMISE_SLUG = "atlas-optimise-script"
SITE_BASE = "/atlas"
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")


class GenerateError(RuntimeError):
    pass


def git(atlas_src: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(atlas_src), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GenerateError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def resolve_tag(atlas_src: Path) -> str:
    try:
        tag = git(atlas_src, "describe", "--tags", "--exact-match")
    except GenerateError:
        tag = os.environ.get("ATLAS_TAG", "").strip()
    if not tag:
        raise GenerateError("cannot determine the Atlas tag: HEAD has no exact tag and ATLAS_TAG is unset")
    if not TAG_RE.match(tag):
        raise GenerateError(f"tag {tag!r} does not match {TAG_RE.pattern}")
    return tag


def blob_sha(atlas_src: Path, rel_path: str) -> str:
    sha = git(atlas_src, "rev-parse", f"HEAD:{rel_path}")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise GenerateError(f"unexpected blob hash for {rel_path}: {sha!r}")
    return sha


def read_version(atlas_src: Path) -> str:
    data = yaml.safe_load((atlas_src / "apm.yml").read_text(encoding="utf-8"))
    version = str((data or {}).get("version", "")).strip()
    if not version:
        raise GenerateError("apm.yml has no version")
    return version


def frontmatter(
    title: str,
    description: str,
    sources: list[str],
    shas: dict[str, str],
    tag: str,
    sidebar: dict | None = None,
) -> str:
    lines = ["---", f"title: {json.dumps(title, ensure_ascii=False)}"]
    lines.append(f"description: {json.dumps(description, ensure_ascii=False)}")
    if sidebar:
        lines.append("sidebar:")
        if "label" in sidebar:
            lines.append(f"  label: {json.dumps(sidebar['label'], ensure_ascii=False)}")
        if "order" in sidebar:
            lines.append(f"  order: {int(sidebar['order'])}")
    lines.append("source:")
    lines.extend(f"  - {src}" for src in sources)
    lines.append("source_sha:")
    lines.extend(f"  {src}: {shas[src]}" for src in sources)
    lines.append(f"source_tag: {tag}")
    lines.append("generated: true")
    lines.append("---")
    return "\n".join(lines) + "\n"


class Scrubber:
    """Replace machine-specific absolute paths with stable placeholders."""

    def __init__(self, atlas_src: Path, home: Path, work: Path):
        pairs = {
            (str(atlas_src.resolve()), "<atlas-skill>"),
            (str(atlas_src), "<atlas-skill>"),
            (str(home), "/home/you"),
            (str(work), "<tmp>"),
            (tempfile.gettempdir(), "<tmp>"),
        }
        real_home = os.environ.get("HOME", "")
        if real_home and real_home != "/":
            pairs.add((real_home, "/home/you"))
        # Longest first, so nested paths collapse to the most specific placeholder.
        self.pairs = sorted((p for p in pairs if p[0]), key=lambda p: (-len(p[0]), p[0]))

    def __call__(self, text: str) -> str:
        for needle, placeholder in self.pairs:
            text = text.replace(needle, placeholder)
        return text


def help_env(home: Path) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "COLUMNS": "100",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
        "NO_COLOR": "1",
        "TERM": "dumb",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    for key in ("SYSTEMROOT", "VIRTUAL_ENV"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def run_help(script: Path, argv: list[str], env: dict[str, str], cwd: Path) -> str:
    cmd = [sys.executable, str(script), *argv, "--help"]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env, cwd=cwd)
    if result.returncode != 0:
        where = " ".join(argv) or "<root>"
        raise GenerateError(f"{script.name} {where} --help exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.rstrip() + "\n"


def load_click_tree(atlas_src: Path):
    import click  # noqa: PLC0415 - Atlas CLI requirement

    scripts = str((atlas_src / "scripts").resolve())
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from atlas_cli.cli import main  # type: ignore[import-not-found]  # noqa: PLC0415

    nodes = []

    def walk(cmd, path):
        if path:
            nodes.append((path, cmd))
        if isinstance(cmd, click.Group):
            for name in sorted(cmd.commands):
                walk(cmd.commands[name], path + [name])

    walk(main, [])
    return click, nodes


def defining_file(atlas_src: Path, callback) -> str | None:
    try:
        target = inspect.unwrap(callback)
        src_file = Path(inspect.getsourcefile(target) or "").resolve()
        return src_file.relative_to(atlas_src.resolve()).as_posix()
    except (TypeError, ValueError):
        return None


def first_paragraph(text: str | None) -> str:
    if not text:
        return ""
    para = inspect.cleandoc(text).split("\n\n", 1)[0]
    return " ".join(para.split())


def cli_slug(path: list[str]) -> str:
    return "-".join(path)


INVOCATION = "python3 <atlas-skill>/scripts/atlas.py"
BARE_CLI = re.compile(r"`atlas (?=[a-z])")


def md_inline(text: str) -> str:
    """Keep help prose literal in Markdown: escape angle brackets."""
    return text.replace("<", "&lt;").replace(">", "&gt;")


def fenced(text: str) -> list[str]:
    fence = "```"
    while fence in text:
        fence += "`"
    return [f"{fence}text", text.rstrip("\n"), fence]


def build_cli_pages(atlas_src: Path, tag: str, out: dict[str, str], work: Path) -> None:
    click, nodes = load_click_tree(atlas_src)
    home = work / "home"
    home.mkdir(parents=True, exist_ok=True)
    scrub = Scrubber(atlas_src, home, work)
    env = help_env(home)
    atlas_py = atlas_src / "scripts" / "atlas.py"
    cli_py = "scripts/atlas_cli/cli.py"

    for order, (path, cmd) in enumerate(nodes, start=1):
        joined = " ".join(path)
        sources = [cli_py]
        extra = defining_file(atlas_src, cmd.callback) if cmd.callback else None
        if extra and extra not in sources:
            sources.append(extra)
        shas = {s: blob_sha(atlas_src, s) for s in sources}
        summary = first_paragraph(cmd.help)
        is_group = isinstance(cmd, click.Group)
        kind = "command group" if is_group else "command"
        help_text = scrub(run_help(atlas_py, path, env, work))

        body = [
            frontmatter(
                f"atlas.py {joined}",
                f"Generated reference for the Atlas CLI {kind} {joined} at {tag}.",
                sources,
                shas,
                tag,
                {"label": joined, "order": order},
            ),
            f"This page is generated from the Atlas CLI at `{tag}`. Do not edit it manually.",
            "",
        ]
        if summary:
            body.append(f"Summary from the help text: {md_inline(summary)}")
        else:
            body.append("The help text has no one-line summary. Read the options below.")
        body += ["", "Run it from the installed skill directory:", ""]
        body += fenced(f"python3 <atlas-skill>/scripts/atlas.py {joined} ...")
        body.append("")
        if is_group:
            body += ["## Subcommands", ""]
            for name in sorted(cmd.commands):
                sub = path + [name]
                body.append(f"- [`{' '.join(sub)}`]({SITE_BASE}/reference/cli/{cli_slug(sub)}/)")
            body.append("")
        body += [
            "## Help output",
            "",
            f"Exact output of `python3 <atlas-skill>/scripts/atlas.py {joined} --help`:",
            "",
        ]
        body += fenced(help_text)
        body += [
            "",
            f"See the [CLI reference overview]({SITE_BASE}/reference/cli/) for the invocation form and exit codes.",
        ]
        out[(CLI_REL / f"{cli_slug(path)}.md").as_posix()] = "\n".join(body) + "\n"

    # Standalone optimise helper (argparse; not an atlas.py command).
    opt_rel = "scripts/atlas_optimise.py"
    opt_py = atlas_src / opt_rel
    shas = {opt_rel: blob_sha(atlas_src, opt_rel)}
    top = scrub(run_help(opt_py, [], env, work))
    sub_help = {}
    subs = re.search(r"\{([a-z0-9_,-]+)\}", top)
    sub_names = subs.group(1).split(",") if subs else []
    for name in sub_names:
        sub_help[name] = scrub(run_help(opt_py, [name], env, work))
    body = [
        frontmatter(
            "atlas_optimise.py",
            f"Generated reference for the standalone atlas_optimise.py helper at {tag}.",
            [opt_rel],
            shas,
            tag,
            {"label": "atlas_optimise.py", "order": len(nodes) + 1},
        ),
        f"This page is generated from the Atlas helper at `{tag}`. Do not edit it manually.",
        "",
        "`atlas_optimise.py` is a standalone helper. It is not an `atlas.py` command. "
        f"The operator runs it through the [atlas-optimise module]({SITE_BASE}/modules/atlas-optimise/). "
        "Install and compile never run it.",
        "",
    ]
    body += fenced("python3 <atlas-skill>/scripts/atlas_optimise.py ...")
    body += [
        "",
        "## Help output",
        "",
        "Exact output of `python3 <atlas-skill>/scripts/atlas_optimise.py --help`:",
        "",
    ]
    body += fenced(top)
    body.append("")
    for name in sub_names:
        text = sub_help[name]
        body += [
            f"## Subcommand {name}",
            "",
            f"Exact output of `python3 <atlas-skill>/scripts/atlas_optimise.py {name} --help`:",
            "",
        ]
        body += fenced(text)
        body.append("")
    body.append(f"See the [CLI reference overview]({SITE_BASE}/reference/cli/) for the invocation form.")
    out[(CLI_REL / f"{OPTIMISE_SLUG}.md").as_posix()] = "\n".join(body) + "\n"


def parse_path_registry(skill_md: str) -> list[tuple[str, str, str]]:
    section = re.search(r"^## Path registry[^\n]*\n(.*?)^## ", skill_md, re.S | re.M)
    if not section:
        raise GenerateError("SKILL.md has no '## Path registry' section")
    rows = []
    for line in section.group(1).splitlines():
        m = re.match(r"^\|\s*\*\*([a-z0-9-]+)\*\*\s*\|(.*)\|\s*`([^`]+)`\s*\|\s*$", line)
        if m:
            rows.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
    if not rows:
        raise GenerateError("the SKILL.md Path registry table has no rows")
    return rows


def build_modules_index(atlas_src: Path, tag: str, out: dict[str, str]) -> None:
    rel = "SKILL.md"
    rows = parse_path_registry((atlas_src / rel).read_text(encoding="utf-8"))
    shas = {rel: blob_sha(atlas_src, rel)}
    body = [
        frontmatter(
            "Modules",
            "Every Atlas module in the installed path registry, with a one-line purpose.",
            [rel],
            shas,
            tag,
            {"label": "All modules", "order": 0},
        ),
        f"This table is generated from the `SKILL.md` path registry at `{tag}`.",
        "",
        "A *module* is one procedure that the agent loads for one intent. "
        "The skill calls a module a *path*. "
        "Modules are not separate skills. "
        "CLI commands are tools that modules use.",
        "",
        "| Module | When to use it | Page |",
        "|--------|----------------|------|",
    ]
    for path_id, when, _module in rows:
        body.append(f"| `{path_id}` | {when} | [{path_id}]({SITE_BASE}/modules/{path_id}/) |")
    body += [
        "",
        "To learn about a module in a session, ask the agent, for example `/atlas help recall`. "
        "The agent explains the module from the installed skill and does not run it.",
    ]
    out[MODULES_INDEX_REL.as_posix()] = "\n".join(body) + "\n"


def build_changelog(atlas_src: Path, tag: str, out: dict[str, str]) -> None:
    rel = "CHANGELOG.md"
    lines = (atlas_src / rel).read_text(encoding="utf-8").splitlines()
    if lines and lines[0].strip().lower() == "# changelog":
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    text = "\n".join(lines).rstrip() + "\n"
    text = BARE_CLI.sub("`" + INVOCATION + " ", text)
    shas = {rel: blob_sha(atlas_src, rel)}
    head = frontmatter(
        "Changelog",
        f"Atlas release notes, mirrored from CHANGELOG.md at {tag}.",
        [rel],
        shas,
        tag,
        {"order": 1},
    )
    lead = (
        f"These are the Atlas release notes from `CHANGELOG.md` at `{tag}`. "
        "The text is verbatim, with one exception: these docs never show a bare `atlas` command, "
        "so short command names are expanded to the supported invocation form, "
        "`python3 <atlas-skill>/scripts/atlas.py <command> ...`."
    )
    out[CHANGELOG_REL.as_posix()] = head + lead + "\n\n" + text


def build_data(atlas_src: Path, tag: str, version: str, out: dict[str, str]) -> None:
    data = {"tag": tag, "commit": git(atlas_src, "rev-parse", "HEAD"), "version": version}
    out[BUILD_JSON_REL.as_posix()] = json.dumps(data, indent=2) + "\n"


def generate(atlas_src: Path) -> dict[str, str]:
    if not (atlas_src / "SKILL.md").is_file():
        raise GenerateError(f"{atlas_src} does not look like an Atlas checkout (no SKILL.md)")
    tag = resolve_tag(atlas_src)
    version = read_version(atlas_src)
    out: dict[str, str] = {}
    work = Path(tempfile.mkdtemp(prefix="atlas-docs-gen-"))
    try:
        build_cli_pages(atlas_src, tag, out, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    build_modules_index(atlas_src, tag, out)
    build_changelog(atlas_src, tag, out)
    build_data(atlas_src, tag, version, out)
    return dict(sorted(out.items()))


def is_generated_page(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return bool(m and re.search(r"^generated:\s*true\s*$", m.group(1), re.M))


def committed_generated(site: Path) -> set[str]:
    found = set()
    docs = site / DOCS_REL
    if docs.is_dir():
        for page in sorted(docs.rglob("*.md*")):
            if is_generated_page(page):
                found.add(page.relative_to(site).as_posix())
    if (site / BUILD_JSON_REL).exists():
        found.add(BUILD_JSON_REL.as_posix())
    return found


def write(site: Path, files: dict[str, str]) -> None:
    for stale in sorted(committed_generated(site) - set(files)):
        (site / stale).unlink()
        print(f"removed stale generated file {stale}")
    for rel, content in files.items():
        dest = site / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content.encode("utf-8"))
    print(f"wrote {len(files)} generated files under {site.name}/")


def check(site: Path, files: dict[str, str]) -> int:
    expected = set(files)
    committed = committed_generated(site)
    missing = sorted(r for r in expected if not (site / r).exists())
    not_marked = sorted(
        r for r in expected if (site / r).exists() and r.endswith(".md") and r not in committed
    )
    extra = sorted(committed - expected)
    changed = []
    diff_lines: list[str] = []
    with tempfile.TemporaryDirectory(prefix="atlas-docs-check-") as tmp:
        tmp_site = Path(tmp)
        for rel, content in files.items():
            dest = tmp_site / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content.encode("utf-8"))
        for rel in sorted(expected):
            current = site / rel
            if not current.exists():
                continue
            new = (tmp_site / rel).read_bytes()
            old = current.read_bytes()
            if new != old:
                changed.append(rel)
                diff = difflib.unified_diff(
                    old.decode("utf-8", "replace").splitlines(),
                    new.decode("utf-8", "replace").splitlines(),
                    f"committed/{rel}",
                    f"generated/{rel}",
                    lineterm="",
                    n=1,
                )
                diff_lines.extend(list(diff)[:30])
    if not (missing or extra or changed or not_marked):
        print(f"V1 generate --check: OK ({len(files)} generated files are up to date)")
        return 0
    print("V1 generate --check: FAILED")
    for rel in missing:
        print(f"  missing      {rel}")
    for rel in extra:
        print(f"  extra        {rel}")
    for rel in not_marked:
        print(f"  not marked   {rel} (expected generated: true)")
    for rel in changed:
        print(f"  changed      {rel}")
    if diff_lines:
        print("\nDiff (first lines per changed file):")
        print("\n".join(diff_lines))
    print("\nFix: run python3 site/scripts/generate.py --atlas-src <atlas-src> and commit the result.")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate Atlas docs pages from an Atlas release tag.")
    ap.add_argument("--atlas-src", required=True, type=Path, help="checkout of the Atlas release tag")
    ap.add_argument("--check", action="store_true", help="diff against the committed files; exit 1 on drift")
    ap.add_argument("--site", type=Path, default=SITE_DIR, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    atlas_src = args.atlas_src.resolve()
    try:
        files = generate(atlas_src)
    except GenerateError as exc:
        print(f"generate.py: error: {exc}", file=sys.stderr)
        return 2
    if args.check:
        return check(args.site.resolve(), files)
    write(args.site.resolve(), files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
