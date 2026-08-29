from __future__ import annotations

import re
from pathlib import Path

LINK_MD = re.compile(r"\[([^\]]*)\]\([^)]+\)")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
HTML_LINK = re.compile(r"<a\s[^>]*href=", re.I)


def _strip_q(v: str) -> str:
    v = v.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    return v


def split_fm(text: str) -> tuple[dict, str]:
    """
    Minimal YAML-ish frontmatter parser.
    Supports:
      key: value
      key:              # list of scalars or list of maps
        - item
        - path: foo
          role: bar
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip("\n")
    body = text[end + 4 :]
    meta: dict = {}
    current: str | None = None
    current_obj: dict | None = None

    for raw in block.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue

        # nested key under list object: "    role: records"
        if current is not None and current_obj is not None and re.match(r"^\s{2,}\w", raw):
            if ":" in raw:
                k, v = raw.split(":", 1)
                current_obj[k.strip()] = _strip_q(v)
            continue

        # list item
        m = re.match(r"^(\s*)-\s+(.*)$", raw)
        if m and current is not None:
            rest = m.group(2).strip()
            if ":" in rest and not rest.startswith("["):
                # start of map item: - path: foo
                k, v = rest.split(":", 1)
                current_obj = {k.strip(): _strip_q(v)}
                meta.setdefault(current, [])
                if not isinstance(meta[current], list):
                    meta[current] = []
                meta[current].append(current_obj)
            else:
                current_obj = None
                meta.setdefault(current, [])
                if not isinstance(meta[current], list):
                    meta[current] = []
                meta[current].append(_strip_q(rest))
            continue

        if ":" not in raw:
            continue

        # top-level key (no leading list indent treated as new key)
        if raw.startswith(" ") or raw.startswith("\t"):
            # orphan indented line — skip
            continue

        k, v = raw.split(":", 1)
        k, v = k.strip(), v.strip()
        current_obj = None
        if v in ("", "[]"):
            meta[k] = []
            current = k
        else:
            current = None
            meta[k] = _strip_q(v)

    return meta, body


def read_page(path: Path) -> tuple[dict, str]:
    return split_fm(path.read_text(encoding="utf-8", errors="replace"))


def leftover_prose(body: str) -> str:
    text = WIKILINK.sub("", body)
    text = LINK_MD.sub(r"\1", text)
    text = HTML_LINK.sub("", text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"^#+\s+.*$", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def is_just_links(body: str, min_prose: int = 40) -> bool:
    """True when body is effectively only links / headings (thin page)."""
    return len(leftover_prose(body)) < min_prose
