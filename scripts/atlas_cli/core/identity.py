"""Deterministic atlas-id normaliser and URI peel. Pure: no git, no network."""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit


class IdentityError(ValueError):
    """Pointer cannot be normalised to host/org/repo."""


class MalformedPinError(IdentityError):
    """A pin-like suffix is not a full lowercase commit or has no path."""


@dataclass(frozen=True)
class ParsedPointer:
    atlas_id: str
    in_store: str
    fragment: str
    commit: str = ""


def normalise(pointer: str) -> str:
    return parse_pointer(pointer).atlas_id


def parse_pointer(pointer: str) -> ParsedPointer:
    if pointer is None:
        raise IdentityError("empty pointer")
    s = pointer.strip(" \t\r\n")
    if not s:
        raise IdentityError("empty pointer")

    s, _, fragment = s.partition("#")
    if s.startswith("atlas://"):
        s = s[len("atlas://") :]

    if "://" not in s and s.startswith("git@") and ":" in s[4:]:
        rest = s[4:]
        host, path = rest.split(":", 1)
        port = re.match(r"^([0-9]+):(.*)$", path)
        if port:
            host = f"{host}:{port.group(1)}"
            path = port.group(2)
    elif "://" in s:
        parts = urlsplit(s)
        if not parts.hostname:
            raise IdentityError("URI missing host")
        host = parts.hostname
        if parts.port not in (None, 80, 443, 22):
            host = f"{host}:{parts.port}"
        path = parts.path or ""
    elif "/" in s:
        first, _, rem = s.partition("/")
        host, path = first, rem
    else:
        raise IdentityError("unparseable pointer")

    host = _fold_host(host)
    org, repo, extra = _org_repo_rest(path)
    commit = ""
    if extra:
        match = re.search(r"@([A-Za-z0-9]{7,64})$", extra[-1])
        if match:
            candidate = match.group(1)
            if not re.fullmatch(r"[0-9a-f]{40}", candidate):
                raise MalformedPinError("malformed pin: expected 40 lowercase hex characters")
            extra[-1] = extra[-1][: match.start()]
            if not extra[-1] and len(extra) == 1:
                raise MalformedPinError("malformed pin: empty in-store path")
            if not extra[-1]:
                raise MalformedPinError("malformed pin: empty final path segment")
            commit = candidate
    return ParsedPointer(
        atlas_id=f"{host}/{org}/{repo}",
        in_store="/".join(extra),
        fragment=fragment,
        commit=commit,
    )


def fold_host(host: str) -> str:
    """The host as :func:`normalise` writes it (``www.`` dropped, ASCII lower-cased)."""
    return _fold_host(host)


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
