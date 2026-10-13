"""Keyboard layout model and registry.

A layout maps *physical keys* (named with XKB key codes such as ``AD01`` for the
key labelled Q on a US keyboard) to the characters they produce at each shift
level. Converting text between layouts means recovering the keystrokes that
produced it under one layout and replaying them under another.

Layouts are loaded from three places, in order (later sources override earlier
ones with the same id):

1. built-in JSON files shipped in ``typoshift/layouts/data``;
2. packages exposing the ``typoshift.layouts`` entry-point group (each entry
   point resolves to a directory path or a callable returning layout dicts);
3. ``*.json`` files in the user layout directory (see ``typoshift config``).
"""

from __future__ import annotations

import json
import os
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import metadata, resources
from pathlib import Path
from typing import Any

LEVELS = 2
# Keys absent from ANSI (US) keyboards; used as a last resort when several keys
# produce the same character.
_ISO_ONLY_KEYS = {"LSGT", "AB11"}

# Spacing form of a dead key -> combining mark it applies.
DEAD_TO_COMBINING = {
    "`": "̀", "´": "́", "^": "̂", "~": "̃", "¯": "̄", "˘": "̆",
    "˙": "̇", "¨": "̈", "˚": "̊", "˝": "̋", "ˇ": "̌", "¸": "̧",
    "˛": "̨", "ͺ": "ͅ",
}


class LayoutError(ValueError):
    """Raised for invalid layout definitions."""


Stroke = tuple[str, int]  # (physical key code, shift level)


@dataclass
class Layout:
    id: str
    name: str
    languages: tuple[str, ...]
    script: str
    keys: dict[str, tuple[str | None, ...]]
    dead_keys: dict[str, frozenset[int]] = field(default_factory=dict)
    sequences: dict[str, Stroke] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    origin: str = "builtin"

    def __post_init__(self) -> None:
        reverse: dict[str, list[Stroke]] = {}
        for code, values in self.keys.items():
            for level, char in enumerate(values[:LEVELS]):
                if char is None:
                    continue
                reverse.setdefault(char, []).append((code, level))
        for char, strokes in reverse.items():
            # Prefer ANSI keys, then the key whose base level is this letter's
            # lowercase (Greek Σ is Shift+σ, not Shift+ς), then lower levels.
            strokes.sort(key=lambda s: (s[0] in _ISO_ONLY_KEYS,
                                        self.keys[s[0]][0] != char.lower() if s[1] else False, s[1]))
        self._reverse = reverse
        # Keys whose output is better written as a multi-character sequence.
        self._sequence_out = {stroke: seq for seq, stroke in self.sequences.items()}
        self._dead_chars = {
            self.keys[code][level]: (code, level)
            for code, levels in self.dead_keys.items()
            for level in levels
            if self.keys.get(code) and self.keys[code][level]
        }

    # -- forward ---------------------------------------------------------------
    def char_at(self, stroke: Stroke) -> str | None:
        values = self.keys.get(stroke[0])
        if not values or stroke[1] >= len(values):
            return None
        return values[stroke[1]]

    def output_at(self, stroke: Stroke) -> str | None:
        """Text produced by a keystroke (sequence-aware, e.g. Arabic lam-alef)."""
        return self._sequence_out.get(stroke) or self.char_at(stroke)

    def is_dead(self, stroke: Stroke) -> bool:
        return stroke[1] in self.dead_keys.get(stroke[0], ())

    # -- reverse ---------------------------------------------------------------
    def strokes_for(self, char: str) -> list[Stroke]:
        """All keystrokes that directly produce ``char``, best first."""
        return self._reverse.get(char, [])

    def dead_stroke_for(self, combining: str) -> Stroke | None:
        for spacing, mark in DEAD_TO_COMBINING.items():
            if mark == combining and spacing in self._dead_chars:
                return self._dead_chars[spacing]
        return None

    def produces(self, char: str) -> bool:
        if char in self._reverse:
            return True
        decomposed = unicodedata.normalize("NFD", char)
        if len(decomposed) == 2:
            return decomposed[0] in self._reverse and self.dead_stroke_for(decomposed[1]) is not None
        return False

    @property
    def characters(self) -> set[str]:
        return set(self._reverse)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "languages": list(self.languages),
            "script": self.script,
            "levels": ["base", "shift"],
            "keys": {k: list(v) for k, v in self.keys.items()},
        }
        if self.dead_keys:
            data["dead_keys"] = {k: [str(lv) for lv in sorted(v)] for k, v in self.dead_keys.items()}
        if self.sequences:
            data["sequences"] = {k: list(v) for k, v in self.sequences.items()}
        if self.source:
            data["source"] = self.source
        if self.notes:
            data["notes"] = self.notes
        return data


def layout_from_dict(data: dict[str, Any], origin: str = "builtin") -> Layout:
    try:
        layout_id = str(data["id"])
        keys_raw = data["keys"]
    except (KeyError, TypeError) as exc:
        raise LayoutError(f"layout definition missing required field: {exc}") from None
    if not isinstance(keys_raw, dict) or not keys_raw:
        raise LayoutError(f"layout {layout_id!r}: 'keys' must be a non-empty object")
    keys: dict[str, tuple[str | None, ...]] = {}
    for code, values in keys_raw.items():
        if not isinstance(values, list) or not 1 <= len(values) <= LEVELS:
            raise LayoutError(f"layout {layout_id!r}: key {code!r} must list 1-{LEVELS} levels")
        for v in values:
            if v is not None and (not isinstance(v, str) or len(v) != 1):
                raise LayoutError(f"layout {layout_id!r}: key {code!r} has invalid character {v!r}")
        keys[str(code)] = tuple(values) + (None,) * (LEVELS - len(values))
    dead = {code: frozenset(int(lv) for lv in levels) for code, levels in data.get("dead_keys", {}).items()}
    sequences = {seq: (str(s[0]), int(s[1])) for seq, s in data.get("sequences", {}).items()}
    for seq, stroke in sequences.items():
        if stroke[0] not in keys:
            raise LayoutError(f"layout {layout_id!r}: sequence {seq!r} references unknown key {stroke[0]!r}")
    return Layout(
        id=layout_id,
        name=str(data.get("name", layout_id)),
        languages=tuple(data.get("languages", ())),
        script=str(data.get("script", "Latin")),
        keys=keys,
        dead_keys=dead,
        sequences=sequences,
        source=dict(data.get("source", {})),
        notes=str(data.get("notes", "")),
        origin=origin,
    )


def _builtin_layout_dicts() -> Iterator[tuple[dict[str, Any], str]]:
    root = resources.files("typoshift.layouts") / "data"
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.name.endswith(".json"):
            yield json.loads(entry.read_text(encoding="utf-8")), "builtin"


def _dir_layout_dicts(directory: Path, origin: str) -> Iterator[tuple[dict[str, Any], str]]:
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.json")):
        yield json.loads(path.read_text(encoding="utf-8")), f"{origin}:{path}"


def _entry_point_layout_dicts() -> Iterator[tuple[dict[str, Any], str]]:
    try:
        eps = metadata.entry_points(group="typoshift.layouts")
    except Exception:  # noqa: BLE001  # pragma: no cover - defensive against broken metadata
        return
    for ep in eps:
        obj = ep.load()
        origin = f"entry-point:{ep.name}"
        result = obj() if callable(obj) else obj
        if isinstance(result, (str, os.PathLike)):
            yield from _dir_layout_dicts(Path(result), origin)
        elif isinstance(result, Iterable):
            for item in result:
                yield item, origin


class LayoutRegistry:
    """Collection of available layouts, keyed by id."""

    def __init__(self, layouts: Iterable[Layout] = ()):
        self._layouts: dict[str, Layout] = {}
        for layout in layouts:
            self.register(layout)

    def register(self, layout: Layout) -> None:
        self._layouts[layout.id] = layout

    def get(self, layout_id: str) -> Layout:
        try:
            return self._layouts[layout_id]
        except KeyError:
            lowered = {k.lower(): v for k, v in self._layouts.items()}
            if layout_id.lower() in lowered:
                return lowered[layout_id.lower()]
            raise KeyError(f"unknown layout {layout_id!r}; run 'typoshift layouts' to list layouts") from None

    def __contains__(self, layout_id: object) -> bool:
        return isinstance(layout_id, str) and (layout_id in self._layouts or layout_id.lower() in
                                                {k.lower() for k in self._layouts})

    def __iter__(self) -> Iterator[Layout]:
        return iter(self._layouts.values())

    def __len__(self) -> int:
        return len(self._layouts)

    def ids(self) -> list[str]:
        return list(self._layouts)

    @classmethod
    def load(cls, user_dir: Path | None = None, *, entry_points: bool = True) -> LayoutRegistry:
        registry = cls()
        sources = [_builtin_layout_dicts()]
        if entry_points:
            sources.append(_entry_point_layout_dicts())
        if user_dir is not None:
            sources.append(_dir_layout_dicts(user_dir, "user"))
        for source in sources:
            for data, origin in source:
                registry.register(layout_from_dict(data, origin))
        return registry


@lru_cache(maxsize=1)
def builtin_registry() -> LayoutRegistry:
    """Registry with only the built-in layouts (cached)."""
    registry = LayoutRegistry()
    for data, origin in _builtin_layout_dicts():
        registry.register(layout_from_dict(data, origin))
    return registry
