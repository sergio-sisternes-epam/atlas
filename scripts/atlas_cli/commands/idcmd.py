from __future__ import annotations

import json
import sys

from ..core.identity import IdentityError, parse_pointer


def run(pointer: str, as_json: bool) -> int:
    try:
        parsed = parse_pointer(pointer)
    except IdentityError as e:
        if as_json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"atlas id: {e}", file=sys.stderr)
        return 2
    if as_json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "id": parsed.atlas_id,
                    "path": parsed.in_store,
                    "fragment": parsed.fragment,
                }
            )
        )
    else:
        print(parsed.atlas_id)
        if parsed.in_store:
            print(parsed.in_store)
    return 0
