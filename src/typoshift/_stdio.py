"""Standard-stream helpers."""

from __future__ import annotations

import contextlib
import sys


def utf8_streams() -> None:
    """Use UTF-8 for stdio (Windows consoles default to a legacy code page)."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8", errors="replace")
