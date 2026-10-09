"""Allow-listed environment for every external driver subprocess.

External drivers (nanograph today) never inherit Atlas's environment. They get
only the variables in :data:`ALLOWED_ENV` that are already set, and a deny pass
then removes anything that looks like a credential, even when it is also on
the allow-list. See references/drivers.md.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, Mapping

from ..auth import TOKEN_ENV_KEYS

ALLOWED_ENV = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "USER",
        "LOGNAME",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "RUST_BACKTRACE",
        "RUST_LOG",
        "NO_COLOR",
    }
)

# Case-insensitive. ``PAT`` only matches as a whole ``_``-separated word so PATH survives.
_DENY = re.compile(
    r"TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY"
    r"|(?:^|_)PAT(?:_|$)"
    r"|^GH_|^GITHUB_|^GITHUB_APM_PAT|^COPILOT_|^ATLAS_PAT|^NANOGRAPH_EMBED"
    r"|^OPENAI_|^GEMINI_|^ANTHROPIC_|^AZURE_OPENAI_|^AWS_",
    re.IGNORECASE,
)
_DENY_EXACT = frozenset(k.upper() for k in TOKEN_ENV_KEYS)

# Test-only: name prefixes the test harness lets through (for a fake driver's
# own controls). Empty in production; nothing here reads the environment.
_test_passthrough: tuple[str, ...] = ()


def set_test_passthrough_prefixes(prefixes: Iterable[str]) -> None:
    """Test-only: also pass variables starting with these prefixes (the deny pass still wins)."""
    global _test_passthrough
    _test_passthrough = tuple(p.upper() for p in prefixes)


def reset_test_passthrough() -> None:
    global _test_passthrough
    _test_passthrough = ()


def denied(name: str) -> bool:
    """True when ``name`` must never reach an external driver."""
    return name.upper() in _DENY_EXACT or bool(_DENY.search(name))


def external_driver_env(
    extra_allowed: Iterable[str] = (), source: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The environment for an external driver: allow-list first, then the deny pass."""
    env = os.environ if source is None else source
    allowed = ALLOWED_ENV | {k.upper() for k in extra_allowed}
    return {
        k: v
        for k, v in env.items()
        if (k.upper() in allowed or (_test_passthrough and k.upper().startswith(_test_passthrough)))
        and not denied(k)
    }
