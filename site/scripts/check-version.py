#!/usr/bin/env python3
"""V2: apm.yml version == tag without "v" == atlas-build.json version (and tag/commit agree)."""

from __future__ import annotations

import docs_common as dc


def main() -> int:
    args = dc.parser(__doc__).parse_args()
    atlas_src = dc.atlas_src_path(args.atlas_src)
    tag = dc.resolve_tag(atlas_src, args.tag)
    apm_version = dc.generate.read_version(atlas_src)
    build = dc.read_build_json()
    commit = dc.generate.git(atlas_src, "rev-parse", "HEAD")

    rows = [
        ("tag without v", tag[1:]),
        ("apm.yml version", apm_version),
        ("atlas-build.json version", str(build.get("version", ""))),
    ]
    problems = []
    if len({value for _, value in rows}) != 1:
        problems.append("versions differ")
    if build.get("tag") != tag:
        problems.append(f"atlas-build.json tag {build.get('tag')!r} != {tag!r}")
    if build.get("commit") != commit:
        problems.append(f"atlas-build.json commit {build.get('commit')!r} != atlas-src HEAD {commit!r}")

    for label, value in rows:
        print(f"  {label:<26} {value}")
    if problems:
        for problem in problems:
            print(f"V2 FAIL: {problem}")
        print("Fix: re-run generate.py against the matching Atlas tag.")
        return 1
    print(f"V2 check-version: OK ({tag})")
    return 0


if __name__ == "__main__":
    dc.run(main)
