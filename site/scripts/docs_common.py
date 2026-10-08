"""Shared helpers for the Python docs checks (check-version, check-drift, check-registry)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate  # noqa: E402

SITE_DIR = generate.SITE_DIR
DOCS_DIR = SITE_DIR / generate.DOCS_REL
BUILD_JSON = SITE_DIR / generate.BUILD_JSON_REL
TAG_RE = generate.TAG_RE
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


class CheckError(Exception):
    pass


def parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument(
        "--atlas-src",
        default=os.environ.get("ATLAS_SRC", str(SITE_DIR.parent / "atlas-src")),
        help="Atlas checkout at the release tag (default: $ATLAS_SRC or ../atlas-src)",
    )
    p.add_argument("--tag", default=os.environ.get("ATLAS_TAG", ""), help="resolved Atlas tag (default: $ATLAS_TAG or the tag at atlas-src HEAD)")
    return p


def atlas_src_path(raw: str) -> Path:
    path = Path(raw).resolve()
    if not (path / "SKILL.md").is_file():
        raise CheckError(f"{raw} does not look like an Atlas checkout (no SKILL.md)")
    return path


def resolve_tag(atlas_src: Path, given: str) -> str:
    tag = given.strip()
    if tag:
        if not TAG_RE.match(tag):
            raise CheckError(f"tag {tag!r} does not match {TAG_RE.pattern}")
        return tag
    try:
        return generate.resolve_tag(atlas_src)
    except generate.GenerateError as exc:
        raise CheckError(str(exc)) from exc


def blob_sha(atlas_src: Path, rel: str) -> str | None:
    try:
        return generate.blob_sha(atlas_src, rel)
    except generate.GenerateError:
        return None


def read_build_json() -> dict:
    return json.loads(BUILD_JSON.read_text(encoding="utf-8"))


def iter_pages():
    """Yield (relative path, frontmatter dict) for every content page."""
    for path in sorted(DOCS_DIR.rglob("*")):
        if path.suffix not in {".md", ".mdx"} or not path.is_file():
            continue
        rel = path.relative_to(SITE_DIR).as_posix()
        match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
        data = yaml.safe_load(match.group(1)) if match else None
        yield rel, data if isinstance(data, dict) else {}


def run(main) -> None:
    try:
        sys.exit(main())
    except (CheckError, generate.GenerateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
