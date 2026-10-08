#!/usr/bin/env python3
"""V3: every page's source paths exist at the tag and their blob hashes equal source_sha."""

from __future__ import annotations

import docs_common as dc


def main() -> int:
    args = dc.parser(__doc__).parse_args()
    atlas_src = dc.atlas_src_path(args.atlas_src)
    tag = dc.resolve_tag(atlas_src, args.tag)

    pages = 0
    stale: list[tuple[str, str]] = []
    for rel, data in dc.iter_pages():
        pages += 1
        sources = data.get("source")
        shas = data.get("source_sha")
        if not isinstance(sources, list) or not sources or not isinstance(shas, dict):
            stale.append((rel, "missing source / source_sha frontmatter"))
            continue
        if data.get("source_tag") != tag:
            stale.append((rel, f"source_tag {data.get('source_tag')!r} != {tag}"))
        if set(sources) != set(shas):
            stale.append((rel, "source and source_sha list different paths"))
        for src in sources:
            actual = dc.blob_sha(atlas_src, str(src))
            if actual is None:
                stale.append((rel, f"{src}: path does not exist at {tag}"))
            elif shas.get(src) != actual:
                stale.append((rel, f"{src}: source_sha {shas.get(src)} != {actual} (source changed)"))

    if stale:
        print(f"V3 FAIL: {len(stale)} problem(s) in {len({p for p, _ in stale})} stale page(s):")
        for rel, why in stale:
            print(f"  {rel}: {why}")
        print("Fix: re-check each page against its sources, then update source_sha (generated pages: re-run generate.py).")
        return 1
    print(f"V3 check-drift: OK ({pages} pages match {tag})")
    return 0


if __name__ == "__main__":
    dc.run(main)
