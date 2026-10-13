"""Split prompts into whitespace, protected regions and candidate chunks.

Chunks are whitespace-delimited. Punctuation is *not* split off, because on a
wrong layout punctuation keys often produce letters and vice versa (on the
Hebrew layout the comma key types ``ת``; on Russian the ``[`` key types ``х``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .protection import Protector, Span

__all__ = ["Token", "tokenize"]

SPACE = "space"
CHUNK = "chunk"
PROTECTED = "protected"

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    text: str
    kind: str  # "space" | "chunk" | "protected"
    rule: str | None = None


def _split_plain(text: str, offset: int, protector: Protector) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    for m in _WS.finditer(text):
        if m.start() > pos:
            tokens.append(_chunk(text[pos : m.start()], offset + pos, protector))
        tokens.append(Token(offset + m.start(), offset + m.end(), m.group(), SPACE))
        pos = m.end()
    if pos < len(text):
        tokens.append(_chunk(text[pos:], offset + pos, protector))
    return tokens


def _chunk(text: str, start: int, protector: Protector) -> Token:
    rule = protector.check_chunk(text)
    return Token(start, start + len(text), text, PROTECTED if rule else CHUNK, rule)


def _widen(text: str, spans: list[Span]) -> list[Span]:
    """Extend spans that start or end inside a whitespace chunk to the whole chunk.

    Converting half a word ("ghbdtn$rfr" with only "$rfr" protected) would
    corrupt it; the whole chunk is left alone instead.
    """
    widened: list[Span] = []
    for span in spans:
        start, end = span.start, span.end
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        while end < len(text) and not text[end].isspace():
            end += 1
        if widened and start <= widened[-1].end:
            last = widened[-1]
            widened[-1] = Span(last.start, max(last.end, end), last.rule)
        else:
            widened.append(Span(start, end, span.rule))
    return widened


def tokenize(text: str, protector: Protector) -> list[Token]:
    """Tokenize ``text``; concatenating token texts reproduces ``text`` exactly."""
    tokens: list[Token] = []
    pos = 0
    for span in _widen(text, protector.find_spans(text)):
        if span.start > pos:
            tokens.extend(_split_plain(text[pos : span.start], pos, protector))
        tokens.append(Token(span.start, span.end, text[span.start : span.end], PROTECTED, span.rule))
        pos = span.end
    if pos < len(text):
        tokens.extend(_split_plain(text[pos:], pos, protector))
    return tokens
