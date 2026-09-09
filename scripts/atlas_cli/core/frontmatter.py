from __future__ import annotations

import re
from pathlib import Path
from typing import Any

MAX_FRONTMATTER_BYTES = 1_000_000
MAX_YAML_EVENTS = 20_000
MAX_YAML_DEPTH = 32

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


class FrontmatterError(ValueError):
    pass


def _jsonish(value: Any, depth: int = 0) -> Any:
    if depth > MAX_YAML_DEPTH:
        raise FrontmatterError("frontmatter nesting exceeds limit")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise FrontmatterError("non-finite number in frontmatter")
        return value
    if isinstance(value, list):
        return [_jsonish(v, depth + 1) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise FrontmatterError("frontmatter keys must be strings")
            out[k] = _jsonish(v, depth + 1)
        return out
    raise FrontmatterError(f"unsupported frontmatter value type {type(value).__name__}")


def split_fm_v2(text: str) -> tuple[dict, str]:
    """Safe YAML frontmatter for SCHEMA 2.0 stores."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip("\n")
    body = text[end + 4 :]
    if len(block.encode("utf-8")) > MAX_FRONTMATTER_BYTES:
        raise FrontmatterError("frontmatter exceeds size limit")
    try:
        import yaml
        from yaml.nodes import MappingNode
    except ImportError as e:
        raise FrontmatterError("PyYAML is required for SCHEMA 2.0 frontmatter") from e

    class UniqueSafeLoader(yaml.SafeLoader):
        pass

    UniqueSafeLoader.yaml_implicit_resolvers = {
        ch: [
            (tag, regexp)
            for tag, regexp in resolvers
            if tag
            not in (
                "tag:yaml.org,2002:bool",
                "tag:yaml.org,2002:timestamp",
            )
        ]
        for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    def construct_mapping(loader: yaml.SafeLoader, node: MappingNode, deep: bool = False):
        if not isinstance(node, MappingNode):
            raise FrontmatterError("expected a mapping")
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                if key in seen:
                    raise FrontmatterError(f"duplicate key {key!r}")
                seen.add(key)
            except TypeError as e:
                raise FrontmatterError("mapping keys must be hashable strings") from e
            tag = getattr(key_node, "tag", "") or ""
            if tag.startswith("!") and not tag.startswith("tag:yaml.org,2002:"):
                raise FrontmatterError(f"unsafe YAML tag {tag}")
        return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)

    UniqueSafeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping
    )
    try:
        events = list(yaml.parse(block, Loader=yaml.SafeLoader))
    except yaml.YAMLError as e:
        raise FrontmatterError(f"invalid YAML frontmatter: {e}") from e
    if len(events) > MAX_YAML_EVENTS:
        raise FrontmatterError("frontmatter exceeds event limit")
    for event in events:
        if event.__class__.__name__ == "AliasEvent":
            raise FrontmatterError("YAML aliases are not supported")
        tag = getattr(event, "tag", None) or ""
        if tag in ("tag:yaml.org,2002:merge",) or tag.startswith("!"):
            raise FrontmatterError(f"unsupported YAML tag {tag}")
    try:
        data = yaml.load(block, Loader=UniqueSafeLoader)
    except yaml.YAMLError as e:
        raise FrontmatterError(f"invalid YAML frontmatter: {e}") from e
    except FrontmatterError:
        raise
    if data is None:
        return {}, body
    if not isinstance(data, dict):
        raise FrontmatterError("frontmatter must be a mapping")
    return _jsonish(data), body


def read_page(path: Path, schema_version: str = "1.0") -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if str(schema_version).strip() == "2.0":
        return split_fm_v2(text)
    return split_fm(text)


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
