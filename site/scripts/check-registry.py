#!/usr/bin/env python3
"""V4: module ids and CLI commands on the site match the Atlas sources at the tag.

Fails when the SKILL.md Path registry and the modules/*.md pages differ, or when
the Click command tree and the generated reference/cli pages differ. A different
set of ids in references/help/index.md is reported as a warning only.
"""

from __future__ import annotations

import re

import docs_common as dc

HELP_ROW = re.compile(r"^\|\s*\*\*([a-z0-9-]+)\*\*\s*\|")


def diff(label_a: str, a: set[str], label_b: str, b: set[str]) -> list[str]:
    out = []
    if a - b:
        out.append(f"in {label_a} but not {label_b}: {', '.join(sorted(a - b))}")
    if b - a:
        out.append(f"in {label_b} but not {label_a}: {', '.join(sorted(b - a))}")
    return out


def main() -> int:
    args = dc.parser(__doc__).parse_args()
    atlas_src = dc.atlas_src_path(args.atlas_src)

    registry = {row[0] for row in dc.generate.parse_path_registry((atlas_src / "SKILL.md").read_text(encoding="utf-8"))}
    help_ids = {
        m.group(1)
        for line in (atlas_src / "references/help/index.md").read_text(encoding="utf-8").splitlines()
        if (m := HELP_ROW.match(line))
    }
    modules_dir = dc.DOCS_DIR / "modules"
    module_pages = {p.stem for p in modules_dir.glob("*.md*") if p.stem != "index"}

    _, nodes = dc.generate.load_click_tree(atlas_src)
    commands = {dc.generate.cli_slug(path) for path, _ in nodes} | {dc.generate.OPTIMISE_SLUG}
    cli_dir = dc.DOCS_DIR / "reference" / "cli"
    cli_pages = {p.stem for p in cli_dir.glob("*.md") if dc.generate.is_generated_page(p)}

    failures = diff("SKILL.md Path registry", registry, "site modules/", module_pages)
    failures += diff("Click command tree", commands, "generated reference/cli pages", cli_pages)
    warnings = diff("SKILL.md Path registry", registry, "references/help/index.md", help_ids)

    for warning in warnings:
        print(f"::warning::V4 help/index.md differs: {warning}")
    if failures:
        for failure in failures:
            print(f"V4 FAIL: {failure}")
        return 1
    print(
        f"V4 check-registry: OK ({len(registry)} modules, {len(commands)} CLI pages"
        f"{', with warnings' if warnings else ''})"
    )
    return 0


if __name__ == "__main__":
    dc.run(main)
