"""Deterministic atlas-id normaliser and URI peel. Pure: no git, no network."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


class IdentityError(ValueError):
    """Pointer cannot be normalised to host/org/repo."""


@dataclass(frozen=True)
class ParsedPointer:
    atlas_id: str
    in_store: str
    fragment: str


def normalise(pointer: str) -> str:
    return parse_pointer(pointer).atlas_id


def parse_pointer(pointer: str) -> ParsedPointer:
    if pointer is None:
        raise IdentityError("empty pointer")
    s = pointer.strip(" \t\r\n")
    if not s:
        raise IdentityError("empty pointer")

    fragment = ""
    if s.startswith("atlas://"):
        s = s[len("atlas://") :]

    if "://" not in s and s.startswith("git@") and ":" in s[4:]:
        rest = s[4:]
        host, path = rest.split(":", 1)
        if "#" in path:
            path, fragment = path.split("#", 1)
    elif "://" in s:
        parts = urlsplit(s)
        if not parts.hostname:
            raise IdentityError("URI missing host")
        host = parts.hostname
        if parts.port not in (None, 80, 443, 22):
            host = f"{host}:{parts.port}"
        path = parts.path or ""
        fragment = parts.fragment or fragment
    elif "/" in s:
        if "#" in s:
            s, fragment = s.split("#", 1)
        first, _, rem = s.partition("/")
        host, path = first, rem
    else:
        raise IdentityError("unparseable pointer")

    host = _fold_host(host)
    org, repo, extra = _org_repo_rest(path)
    return ParsedPointer(
        atlas_id=f"{host}/{org}/{repo}",
        in_store="/".join(extra),
        fragment=fragment,
    )


def _fold_host(host: str) -> str:
    h = host.strip()
    lower = h.lower()
    if lower.startswith("www."):
        h = h[4:]
    return "".join(ch.lower() if "A" <= ch <= "Z" else ch for ch in h)


def _org_repo_rest(path: str) -> tuple[str, str, list[str]]:
    p = path.strip()
    if p.startswith("/"):
        p = p[1:]
    if p.endswith("/"):
        p = p[:-1]
    segs = [seg for seg in p.split("/") if seg]
    if len(segs) < 2:
        raise IdentityError("need org and repo")
    repo = segs[1]
    if repo.lower().endswith(".git"):
        repo = repo[: -len(".git")]
        if not repo:
            raise IdentityError("need org and repo")
        segs[1] = repo
    return segs[0], segs[1], segs[2:]
