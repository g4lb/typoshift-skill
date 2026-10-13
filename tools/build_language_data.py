#!/usr/bin/env python3
"""Build TypoShift's offline language models from word-frequency lists.

Source data: FrequencyWords (Hermit Dave), 2018 OpenSubtitles lists, pinned to
a specific commit. The word lists are licensed CC-BY-SA-4.0, so the derived
files in ``src/typoshift/data/lang`` are distributed under the same license
(see ``src/typoshift/data/lang/LICENSE``).

For every language the builder writes ``<lang>.json.gz`` containing:

* ``words``: the ``LEXICON_SIZE`` most frequent words (rank order);
* ``trigrams``: frequency-weighted character trigram counts (with ``^``/``$``
  word boundary markers) trained on those words;
* ``norm``: mean and standard deviation of the per-character log-probability
  measured on *held-out* words (ranks LEXICON_SIZE+1 .. 50 000), which are never
  part of the lexicon. Normalizing by these statistics makes scores comparable
  across languages with different alphabet sizes.

The held-out words are also written to ``tools/cache/holdout/<lang>.txt`` for
use by ``tools/calibrate.py``.

Usage::

    python tools/build_language_data.py
"""

from __future__ import annotations

import gzip
import json
import math
import sys
import unicodedata
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from typoshift.langmodel import CharTrigramModel, word_chars_ok  # noqa: E402
from typoshift.layouts import builtin_registry  # noqa: E402

FREQ_COMMIT = "525f9b560de45753a5ea01069454e72e9aa541c6"
FREQ_URL = "https://raw.githubusercontent.com/hermitdave/FrequencyWords/{commit}/content/2018/{code}/{code}_50k.txt"
CACHE = ROOT / "tools" / "cache"
OUT = ROOT / "src" / "typoshift" / "data" / "lang"
EXTRA = ROOT / "tools" / "vocab"

LEXICON_SIZE = 30_000

# language -> (script, FrequencyWords list codes)
LANGUAGES: dict[str, tuple[str, tuple[str, ...]]] = {
    "en": ("Latin", ("en",)),
    "he": ("Hebrew", ("he",)),
    "ru": ("Cyrillic", ("ru",)),
    "ar": ("Arabic", ("ar",)),
    "fr": ("Latin", ("fr",)),
    "de": ("Latin", ("de",)),
    "es": ("Latin", ("es",)),
    "it": ("Latin", ("it",)),
    "pt": ("Latin", ("pt", "pt_br")),
    "uk": ("Cyrillic", ("uk",)),
    "el": ("Greek", ("el",)),
    "tr": ("Latin", ("tr",)),
    "pl": ("Latin", ("pl",)),
    "cs": ("Latin", ("cs",)),
    "sv": ("Latin", ("sv",)),
    "no": ("Latin", ("no",)),
    "da": ("Latin", ("da",)),
    "nl": ("Latin", ("nl",)),
}


def fetch(code: str) -> list[tuple[str, int]]:
    path = CACHE / "freq" / f"{code}_50k.txt"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = FREQ_URL.format(commit=FREQ_COMMIT, code=code)
        print(f"downloading {url}", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - pinned https URL
            path.write_bytes(resp.read())
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            rows.append((parts[0], int(parts[1])))
    return rows


# Native letters that the layout only offers on AltGr (level 3), which TypoShift
# does not model; they still belong to the language's alphabet.
ALTGR_LETTERS = {"pl": "ąćęłńóśźż"}


def alphabet(lang: str) -> set[str]:
    """Lowercase letters typeable on the language's native layout(s), incl. dead-key compositions.

    Filtering the word lists with it removes foreign-language contamination
    (e.g. Russian words containing ы/э/ъ in the Ukrainian subtitle list).
    """
    letters: set[str] = set()
    for layout in builtin_registry():
        if lang not in layout.languages:
            continue
        for ch in layout.characters:
            if ch.isalpha():
                letters.add(ch.lower())
        for ch in map(chr, range(0x00C0, 0x0400)):
            if ch.isalpha() and layout.produces(ch):
                letters.add(ch.lower())
    if not letters:
        raise KeyError(f"no layout declares language {lang!r}")
    return letters | set(ALTGR_LETTERS.get(lang, ""))


def load_counts(lang: str, script: str, codes: tuple[str, ...]) -> list[tuple[str, int]]:
    allowed = alphabet(lang) | {"'", "\u2019", "-", "\u05f3", "\u05f4", "\u05be"}
    counts: Counter[str] = Counter()
    for code in codes:
        for word, count in fetch(code):
            word = unicodedata.normalize("NFC", word).lower()
            if word_chars_ok(word, script) and set(word) <= allowed:
                counts[word] += count
    return counts.most_common()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (CACHE / "holdout").mkdir(parents=True, exist_ok=True)
    for lang, (script, codes) in LANGUAGES.items():
        ranked = load_counts(lang, script, codes)
        lexicon = ranked[:LEXICON_SIZE]
        holdout = ranked[LEXICON_SIZE:]
        extra_path = EXTRA / f"{lang}.txt"
        extra = []
        if extra_path.exists():
            extra = [w.strip().lower() for w in extra_path.read_text(encoding="utf-8").splitlines()
                     if w.strip() and not w.startswith("#")]
        model = CharTrigramModel.train([(w, c) for w, c in lexicon])
        scores = [model.per_char_logprob(w) for w, _ in holdout if len(w) >= 2]
        mean = sum(scores) / len(scores)
        std = math.sqrt(sum((s - mean) ** 2 for s in scores) / len(scores))
        words = [w for w, _ in lexicon]
        seen = set(words)
        words += [w for w in extra if w not in seen]
        data = {
            "lang": lang,
            "script": script,
            "source": {
                "dataset": "FrequencyWords (OpenSubtitles 2018)",
                "commit": FREQ_COMMIT,
                "lists": list(codes),
                "license": "CC-BY-SA-4.0",
                "extra_vocabulary": len(extra),
            },
            "words": words,
            "trigrams": model.to_counts(),
            "norm": {"mean": round(mean, 6), "std": round(std, 6), "holdout_words": len(scores)},
        }
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        (OUT / f"{lang}.json.gz").write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
        (CACHE / "holdout" / f"{lang}.txt").write_text(
            "\n".join(f"{w}\t{c}" for w, c in holdout) + "\n", encoding="utf-8"
        )
        print(f"{lang}: {len(words)} words, {len(data['trigrams'])} trigrams, "
              f"norm mean={mean:.3f} std={std:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
