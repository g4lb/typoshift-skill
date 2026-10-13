"""Unicode script identification helpers."""

from __future__ import annotations

import unicodedata
from functools import lru_cache

LATIN = "Latin"
HEBREW = "Hebrew"
CYRILLIC = "Cyrillic"
ARABIC = "Arabic"
GREEK = "Greek"
COMMON = "Common"
OTHER = "Other"

_PREFIXES = (
    ("LATIN", LATIN),
    ("HEBREW", HEBREW),
    ("CYRILLIC", CYRILLIC),
    ("ARABIC", ARABIC),
    ("GREEK", GREEK),
)

# Hebrew punctuation (geresh, gershayim, maqaf) is part of words.
_WORD_PUNCT = {"'", "’", "-", "׳", "״", "־"}


@lru_cache(maxsize=4096)
def char_script(ch: str) -> str:
    """Return the script of a single character (letters and combining marks only)."""
    cat = unicodedata.category(ch)
    if cat[0] not in ("L", "M"):
        return COMMON
    name = unicodedata.name(ch, "")
    for prefix, script in _PREFIXES:
        if name.startswith(prefix):
            return script
    return OTHER


def is_letter(ch: str) -> bool:
    return unicodedata.category(ch)[0] in ("L", "M")


def letter_scripts(text: str) -> dict[str, int]:
    """Count letters per script in ``text``."""
    counts: dict[str, int] = {}
    for ch in text:
        if is_letter(ch):
            s = char_script(ch)
            counts[s] = counts.get(s, 0) + 1
    return counts


def dominant_script(text: str) -> str | None:
    counts = letter_scripts(text)
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def word_chars_ok(word: str, script: str) -> bool:
    """True if ``word`` consists of letters of ``script`` (plus inner apostrophes/hyphens)."""
    if not word or not is_letter(word[0]) or not is_letter(word[-1]):
        return False
    for ch in word:
        if ch in _WORD_PUNCT:
            continue
        if not is_letter(ch) or char_script(ch) != script:
            return False
    return True


def split_letter_runs(text: str) -> list[str]:
    """Split ``text`` into runs of letters (allowing inner word punctuation)."""
    runs: list[str] = []
    cur: list[str] = []
    for i, ch in enumerate(text):
        if is_letter(ch):
            cur.append(ch)
        elif ch in _WORD_PUNCT and cur and i + 1 < len(text) and is_letter(text[i + 1]):
            cur.append(ch)
        else:
            if cur:
                runs.append("".join(cur))
                cur = []
    if cur:
        runs.append("".join(cur))
    return runs
