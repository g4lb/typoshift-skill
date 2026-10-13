"""TypoShift: type in the wrong language, get the right words.

Keyboard-layout mistake detection and reconstruction. TypoShift maps text back
through physical key positions; it never translates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__version__ = "0.1.0"

__all__ = ["Correction", "Engine", "FixResult", "Mode", "__version__", "convert", "detect", "fix"]

if TYPE_CHECKING:  # pragma: no cover
    from .engine import Correction, Engine, FixResult, Mode, convert, detect, fix


def __getattr__(name: str) -> Any:
    # Lazy import keeps `import typoshift` cheap for the Claude Code hook.
    if name in __all__ and name != "__version__":
        from . import engine

        return getattr(engine, name)
    raise AttributeError(f"module 'typoshift' has no attribute {name!r}")
