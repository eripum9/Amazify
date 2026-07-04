from __future__ import annotations

import os
from pathlib import Path
import sys
import traceback

from amazify.cli import main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        if sys.stderr is not None:
            raise
        log_root = Path(os.environ.get("APPDATA", Path.home())) / "Amazify" / "logs"
        try:
            log_root.mkdir(parents=True, exist_ok=True)
            (log_root / "amazifyw-crash.log").write_text(
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                encoding="utf-8",
            )
        except OSError:
            pass
        raise SystemExit(1)
