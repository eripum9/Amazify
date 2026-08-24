from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: write_spotify_runtime_hook.py OUTPUT")
    client_id = os.environ.get("AMAZIFY_SPOTIFY_CLIENT_ID", "").strip()
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "import os\n"
        f"os.environ.setdefault('AMAZIFY_SPOTIFY_CLIENT_ID', {client_id!r})\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
