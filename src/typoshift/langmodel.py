"""Offline language plausibility models.

Each language model combines:

* a lexicon of frequent words (membership is a strong signal), and
* a character trigram model with Witten-Bell smoothing, which scores words that
  are not in the lexicon (inflections, names, technical words).

Per-character log-probabilities are normalized into z-scores using statistics
measured on held-out words, so that scores from different languages (with
different alphabet sizes) can be compared directly.
"""

from __future__ import annotations

import gzip
import json
import math
import unicodedata
from dataclasses import dataclass
from functools import cache
from importlib import resources

from .scripts import split_letter_runs, word_chars_ok

__all__ = ["CharTrigramModel", "LanguageModel", "load_language", "available_languages", "word_chars_ok"]

BOS = "^"
EOS = "$"


class CharTrigramModel:
    """Character trigram model with interpolated Witten-Bell smoothing."""

    def __init__(self, trigrams: dict[str, int]):
        self.trigrams = trigrams
        ctx3_total: dict[str, int] = {}
        ctx3_types: dict[str, int] = {}
        bigrams: dict[str, int] = {}
        unigrams: dict[str, int] = {}
        for tri, count in trigrams.items():
            ab, bc, c = tri[:2], tri[1:], tri[2]
            ctx3_total[ab] = ctx3_total.get(ab, 0) + count
            ctx3_types[ab] = ctx3_types.get(ab, 0) + 1
            bigrams[bc] = bigrams.get(bc, 0) + count
            unigrams[c] = unigrams.get(c, 0) + count
        ctx2_total: dict[str, int] = {}
        ctx2_types: dict[str, int] = {}
        for bc, count in bigrams.items():
            ctx2_total[bc[0]] = ctx2_total.get(bc[0], 0) + count
            ctx2_types[bc[0]] = ctx2_types.get(bc[0], 0) + 1
        self._ctx3_total, self._ctx3_types = ctx3_total, ctx3_types
        self._bigrams, self._ctx2_total, self._ctx2_types = bigrams, ctx2_total, ctx2_types
        self._unigrams = unigrams
        self._n = sum(unigrams.values())
        self._v = len(unigrams) + 1  # +1 reserves mass for unseen characters

    @classmethod
    def train(cls, words: list[tuple[str, int]]) -> CharTrigramModel:
        counts: dict[str, int] = {}
        for word, freq in words:
            weight = max(1, round(math.sqrt(freq)))
            padded = BOS + BOS + word + EOS
            for i in range(len(padded) - 2):
                tri = padded[i : i + 3]
                counts[tri] = counts.get(tri, 0) + weight
        return cls(counts)

    def to_counts(self) -> dict[str, int]:
        return dict(sorted(self.trigrams.items()))

    def prob(self, a: str, b: str, c: str) -> float:
        p1 = (self._unigrams.get(c, 0) + 1) / (self._n + self._v)
        t2 = self._ctx2_types.get(b, 0)
        p2 = (self._bigrams.get(b + c, 0) + t2 * p1) / (self._ctx2_total[b] + t2) if t2 else p1
        ab = a + b
        t3 = self._ctx3_types.get(ab, 0)
        if not t3:
            return p2
        return (self.trigrams.get(ab + c, 0) + t3 * p2) / (self._ctx3_total[ab] + t3)

    def logprob(self, word: str) -> float:
        padded = BOS + BOS + word + EOS
        return sum(math.log(self.prob(padded[i], padded[i + 1], padded[i + 2])) for i in range(len(padded) - 2))

    def per_char_logprob(self, word: str) -> float:
        return self.logprob(word) / (len(word) + 1)


@dataclass
class WordScore:
    z: float  # normalized character-model score
    known: bool  # word is in the lexicon
    letters: int


class LanguageModel:
    """Lexicon + character model for one language."""

    def __init__(self, data: dict):
        self.lang: str = data["lang"]
        self.script: str = data["script"]
        self.source: dict = data.get("source", {})
        words = data["words"]
        self.lexicon: dict[str, int] = {w: i for i, w in enumerate(words)}
        self.chars = CharTrigramModel(data["trigrams"])
        self.mean: float = data["norm"]["mean"]
        self.std: float = data["norm"]["std"] or 1.0
        self._cache: dict[str, WordScore] = {}

    def is_known(self, word: str) -> bool:
        w = word.lower()
        if w in self.lexicon:
            return True
        # Hyphenated compounds ("cook-off") are known when every part is.
        if "-" in w:
            parts = [p for p in w.split("-") if p]
            return bool(parts) and all(self.is_known(p) for p in parts)
        # Contractions and elisions: "don't", "l'homme", "it's".
        for sep in ("'", "’"):
            if sep in w:
                parts = [p for p in w.split(sep) if p]
                return bool(parts) and all(p in self.lexicon or len(p) <= 2 for p in parts)
        return False

    def score_word(self, word: str) -> WordScore:
        cached = self._cache.get(word)
        if cached is not None:
            return cached
        w = unicodedata.normalize("NFC", word.lower())
        # Lexicon words carry no apostrophes (contractions are split in the source
        # lists), so score "let's" by its letters.
        bare = w.replace("'", "").replace("\u2019", "") or w
        z = (self.chars.per_char_logprob(bare) - self.mean) / self.std
        result = WordScore(z=z, known=self.is_known(w), letters=len(w))
        if len(self._cache) < 50_000:
            self._cache[word] = result
        return result

    def score_text(self, text: str) -> tuple[float, float, int]:
        """Return (mean z-score, known-letter fraction, letters), letter-weighted over words."""
        total = 0
        z_sum = 0.0
        known = 0
        for run in split_letter_runs(text):
            s = self.score_word(run)
            total += s.letters
            z_sum += s.z * s.letters
            if s.known:
                known += s.letters
        if not total:
            return 0.0, 0.0, 0
        return z_sum / total, known / total, total


@cache
def available_languages() -> tuple[str, ...]:
    root = resources.files("typoshift.data") / "lang"
    return tuple(sorted(p.name.split(".")[0] for p in root.iterdir() if p.name.endswith(".json.gz")))


@cache
def load_language(lang: str) -> LanguageModel:
    path = resources.files("typoshift.data") / "lang" / f"{lang}.json.gz"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise KeyError(f"no language model for {lang!r}") from None
    return LanguageModel(json.loads(gzip.decompress(raw)))
