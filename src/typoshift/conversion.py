"""Physical-key reconstruction between keyboard layouts.

Conversion is a two-step process:

1. **Decode** text typed under the *source* layout into keystrokes
   (physical key + shift level). Characters that the source layout cannot
   produce (spaces, newlines, emoji, digits typed on a numpad...) pass through
   unchanged. Precomposed letters produced with a dead key (e.g. Greek ``έ`` =
   dead tonos + ``ε``) decode into two keystrokes.
2. **Encode** the keystrokes under the *target* layout. A dead key in the target
   layout combines with the following character, as it would while typing.

No translation, transliteration or dictionary lookup is involved.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from itertools import islice, product

from .layouts.registry import DEAD_TO_COMBINING, Layout, Stroke

__all__ = ["ConversionResult", "decode", "encode", "convert_text", "convert_variants", "producible"]

# A decoded item is either a keystroke or a pass-through string.
Item = Stroke | str
SPACE: Stroke = ("SPCE", 0)


@dataclass(frozen=True)
class ConversionResult:
    text: str
    unmapped: int  # keystrokes the target layout has no character for (kept as typed)
    passthrough: int  # characters the source layout could not have produced


def _decode_char(ch: str, layout: Layout) -> list[Item] | None:
    strokes = layout.strokes_for(ch)
    if strokes:
        return [strokes[0]]
    decomposed = unicodedata.normalize("NFD", ch)
    if len(decomposed) == 2:
        base = layout.strokes_for(decomposed[0])
        dead = layout.dead_stroke_for(decomposed[1])
        if base and dead:
            return [dead, base[0]]
    return None


def _ambiguous_letter(ch: str, layout: Layout) -> list[list[Item]] | None:
    """Letters produced by several (non-ISO) keys, e.g. Greek Σ = Shift+σ or Shift+ς."""
    if not ch.isalpha():
        return None
    strokes = [s for s in layout.strokes_for(ch) if s[0] not in ("LSGT", "AB11")]
    if len(strokes) < 2:
        return None
    return [[s] for s in strokes]


def decode(text: str, layout: Layout) -> list[list[list[Item]]]:
    """Decode ``text`` into slots of keystroke items.

    Each slot lists one or more alternative item sequences. A slot has several
    alternatives only when the text is ambiguous, e.g. Arabic ``لا`` can come
    from the lam-alef key or from the lam and alef keys; see
    :func:`convert_variants`.
    """
    slots: list[list[list[Item]]] = []
    i = 0
    seqs = sorted(layout.sequences.items(), key=lambda kv: -len(kv[0]))
    while i < len(text):
        matched = False
        for seq, stroke in seqs:
            if text.startswith(seq, i):
                # The sequence may also have been typed key by key.
                options: list[list[Item]] = [[stroke]]
                per_char = [_decode_char(c, layout) for c in seq]
                if all(p is not None for p in per_char):
                    options.append([item for p in per_char for item in p])  # type: ignore[union-attr]
                slots.append(options)
                i += len(seq)
                matched = True
                break
        if matched:
            continue
        ch = text[i]
        items = _decode_char(ch, layout)
        alternatives = _ambiguous_letter(ch, layout)
        if alternatives:
            slots.append(alternatives)
            i += 1
            continue
        if items is None:
            slots.append([[ch]])
        elif len(items) == 1 and isinstance(items[0], tuple) and layout.is_dead(items[0]):
            # A standalone accent from a dead key was typed as dead key + Space.
            slots.append([[items[0], SPACE]])
        else:
            slots.append([items])
        i += 1
    return slots


def encode(items: list[Item], layout: Layout, fallback: Layout | None = None) -> tuple[str, int]:
    """Encode keystroke items under ``layout``. Returns (text, unmapped_count).

    Keystrokes on keys that ``layout`` lacks (e.g. the ISO ``<>`` key on a US
    layout) are counted as unmapped and emitted as ``fallback`` would type them.
    """
    out: list[str] = []
    unmapped = 0
    i = 0
    while i < len(items):
        item = items[i]
        if isinstance(item, str):
            out.append(item)
            i += 1
            continue
        if item == SPACE:
            out.append(" ")
            i += 1
            continue
        char = layout.char_at(item)
        if char is None:
            unmapped += 1
            original = fallback.char_at(item) if fallback else None
            out.append(original or "\ufffd")
            i += 1
            continue
        if layout.is_dead(item) and i + 1 < len(items):
            nxt = items[i + 1]
            if nxt == SPACE or nxt == " ":
                out.append(char)  # dead key + Space = the spacing accent alone
                i += 2
                continue
            nxt_char = nxt if isinstance(nxt, str) else layout.char_at(nxt)
            mark = DEAD_TO_COMBINING.get(char)
            if nxt_char and mark and not (isinstance(nxt, tuple) and layout.is_dead(nxt)):
                composed = unicodedata.normalize("NFC", nxt_char + mark)
                if len(composed) == 1:
                    out.append(composed)
                    i += 2
                    continue
        out.append(layout.output_at(item) or char)
        i += 1
    return "".join(out), unmapped


def _flatten(slots: list[list[list[Item]]], choice: tuple[int, ...] | None = None) -> list[Item]:
    items: list[Item] = []
    k = 0
    for options in slots:
        if len(options) > 1 and choice is not None:
            items.extend(options[choice[k]])
            k += 1
        else:
            items.extend(options[0])
    return items


def convert_text(text: str, source: Layout, target: Layout) -> ConversionResult:
    """Convert ``text`` typed under ``source`` into what ``target`` would produce."""
    slots = decode(text, source)
    items = _flatten(slots)
    passthrough = sum(1 for it in items if isinstance(it, str) and not it.isspace())
    out, unmapped = encode(items, target, source)
    return ConversionResult(out, unmapped, passthrough)


def convert_variants(text: str, source: Layout, target: Layout, limit: int = 8) -> list[ConversionResult]:
    """All conversions for ambiguous decodings (e.g. Arabic lam-alef), up to ``limit``."""
    slots = decode(text, source)
    ambiguous = [len(o) for o in slots if len(o) > 1]
    if not ambiguous:
        return [convert_text(text, source, target)]
    results: list[ConversionResult] = []
    seen: set[str] = set()
    for choice in islice(product(*(range(n) for n in ambiguous)), limit):
        items = _flatten(slots, choice)
        passthrough = sum(1 for it in items if isinstance(it, str) and not it.isspace())
        out, unmapped = encode(items, target, source)
        if out not in seen:
            seen.add(out)
            results.append(ConversionResult(out, unmapped, passthrough))
    return results


def producible(text: str, layout: Layout) -> bool:
    """True if every non-space character of ``text`` can be typed on ``layout`` (levels 1-2)."""
    i = 0
    seqs = list(layout.sequences)
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        seq = next((s for s in seqs if text.startswith(s, i)), None)
        if seq:
            i += len(seq)
            continue
        if not layout.produces(ch):
            return False
        i += 1
    return True
