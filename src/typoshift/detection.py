"""Candidate generation and span selection.

Pipeline for one prompt (see ``docs/ARCHITECTURE.md`` for the full picture):

1. The tokenizer splits the prompt into whitespace, protected regions and
   chunks.
2. For every enabled *source* layout, chunks the layout could have produced
   form *runs* (protected regions and unproducible chunks break runs).
3. Runs without a single suspicious chunk (unknown word or implausible
   character sequence in every enabled language of its script) are skipped;
   this keeps correctly typed prompts cheap.
4. For every *target* layout, each chunk in a remaining run is converted by
   physical key and scored against the target layout's languages. The gain of
   a chunk is how much more plausible the conversion is than the original.
5. Contiguous chunks with positive gain become a *proposal* (a span), with a
   feature vector that :mod:`typoshift.confidence` turns into a calibrated
   probability.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from .conversion import convert_variants, producible
from .langmodel import LanguageModel, load_language
from .layouts.registry import Layout, LayoutRegistry
from .scripts import dominant_script, is_letter, letter_scripts
from .tokenizer import CHUNK, PROTECTED, SPACE, Token

__all__ = ["Proposal", "Detector", "FEATURES"]

FEATURES = (
    "delta_z",
    "delta_known",
    "target_known",
    "source_known",
    "delta_noise",
    "purity",
    "log_letters",
    "context_support",
    "has_context",
    "short",
    "competitor_gap",
    "contested",
    "context_conflict",
    "short_conflict",
    "unexplained",
)

KNOWN_WEIGHT = 3.0
# A letter, punctuation other than apostrophes/hyphens, then another letter.
_INNER_PUNCT = re.compile(r"[^\W\d_][^\w\s'\u2019-]+[^\W\d_]")


@dataclass
class Score:
    z: float
    known: float
    letters: int
    lang: str | None


@dataclass
class ChunkEval:
    token_index: int
    original: str
    candidate: str
    source: Score
    target: Score
    purity: float
    neutral: bool

    @property
    def gain(self) -> float:
        if self.neutral:
            return 0.0
        return (
            (self.target.z - self.source.z)
            + KNOWN_WEIGHT * (self.target.known - self.source.known)
            - KNOWN_WEIGHT * (1.0 - self.purity)
        )


@dataclass
class Proposal:
    start: int
    end: int
    original: str
    replacement: str
    source_layout: str
    target_layout: str
    language: str | None
    features: dict[str, float]
    confidence: float = 0.0
    equivalent_layouts: list[str] = field(default_factory=list)
    score: float = 0.0  # span-level target plausibility (z + weighted known fraction)

    def key(self) -> tuple[int, int, str]:
        return (self.start, self.end, self.replacement)


def _noise(text: str) -> float:
    """Fraction of characters that are neither letters nor whitespace, ignoring chunk edges."""
    inner = 0
    total = 0
    for chunk in text.split():
        core = chunk.strip("\"'()[]{}<>.,;:!?«»“”")
        total += len(core)
        inner += sum(1 for ch in core if not is_letter(ch) and not ch.isdigit())
    return inner / total if total else 0.0


def consistent(p: Proposal, c: Proposal) -> bool:
    """True if ``p`` covers ``c`` and rewrites ``c``'s span word for word identically."""
    if not (p.start <= c.start and c.end <= p.end):
        return False
    head = p.original[: c.start - p.start].split()
    inner = c.replacement.split()
    return p.replacement.split()[len(head) : len(head) + len(inner)] == inner


def _letters(text: str) -> str:
    return "".join(ch for ch in text.lower() if is_letter(ch))


def _purity(text: str, script: str) -> float:
    counts = letter_scripts(text)
    total = sum(counts.values())
    return counts.get(script, 0) / total if total else 1.0


class Detector:
    def __init__(
        self,
        registry: LayoutRegistry,
        layouts: Sequence[str],
        layout_languages: dict[str, list[str]] | None = None,
        min_letters: int = 2,
    ):
        self.layouts: list[Layout] = [registry.get(lid) for lid in layouts]
        self.layout_languages = {
            lay.id: list((layout_languages or {}).get(lay.id) or lay.languages) for lay in self.layouts
        }
        self.min_letters = min_letters
        langs: dict[str, None] = {}
        for lay in self.layouts:
            for lang in self.layout_languages[lay.id]:
                langs[lang] = None
        self.languages = list(langs)
        self._script_langs: dict[str, list[str]] | None = None

    # -- language helpers --------------------------------------------------------
    def _model(self, lang: str) -> LanguageModel | None:
        try:
            return load_language(lang)
        except KeyError:
            return None

    def languages_for_script(self, script: str) -> list[str]:
        if self._script_langs is None:
            mapping: dict[str, list[str]] = {}
            for lay in self.layouts:
                for lang in self.layout_languages[lay.id]:
                    if lang not in mapping.setdefault(lay.script, []):
                        mapping[lay.script].append(lang)
            self._script_langs = mapping
        return self._script_langs.get(script, [])

    def best_score(self, text: str, langs: Sequence[str]) -> Score:
        best: Score | None = None
        for lang in langs:
            model = self._model(lang)
            if model is None:
                continue
            z, known, letters = model.score_text(text)
            if not letters:
                return Score(0.0, 0.0, 0, None)
            score = Score(max(-15.0, min(15.0, z)), known, letters, lang)
            if best is None or score.z + KNOWN_WEIGHT * score.known > best.z + KNOWN_WEIGHT * best.known:
                best = score
        if best is None:
            letters = sum(1 for ch in text if is_letter(ch))
            return Score(-15.0 if letters else 0.0, 0.0, letters, None)
        return best

    def native_score(self, text: str) -> Score:
        script = dominant_script(text)
        if script is None:
            return Score(0.0, 0.0, 0, None)
        score = self.best_score(text, self.languages_for_script(script))
        if _INNER_PUNCT.search(text):
            # "pr;ta" splits into the known fragments "pr" and "ta", but letters
            # glued by punctuation are not words as typed.
            score.known = 0.0
        return score

    # -- proposals -----------------------------------------------------------------
    def propose(self, text: str, tokens: Sequence[Token]) -> list[Proposal]:
        chunk_idx = [i for i, t in enumerate(tokens) if t.kind == CHUNK]
        if not chunk_idx:
            return []
        native: dict[int, Score] = {}

        def native_of(i: int) -> Score:
            if i not in native:
                native[i] = self.native_score(tokens[i].text)
            return native[i]

        proposals: dict[tuple[int, int, str], Proposal] = {}
        for source in self.layouts:
            for run in self._runs(tokens, source):
                if not any(self._suspicious(native_of(i), tokens[i].text) for i in run):
                    continue
                for target in self.layouts:
                    if target.id == source.id:
                        continue
                    for prop in self._evaluate_run(text, tokens, run, source, target, native_of):
                        existing = proposals.get(prop.key())
                        if existing is None:
                            proposals[prop.key()] = prop
                        elif target.id not in existing.equivalent_layouts and target.id != existing.target_layout:
                            existing.equivalent_layouts.append(target.id)
        result = list(proposals.values())
        self._add_competition(result)
        return result

    def _add_competition(self, proposals: list[Proposal]) -> None:
        """Compare each proposal with overlapping proposals that rewrite the text differently.

        For rivals over the same span only the words that differ are compared,
        each under its own language; shared words carry no evidence (this is
        what separates, e.g., Russian from Ukrainian candidates).
        """
        for p in proposals:
            gaps = []
            for q in proposals:
                if q is p or not (q.start < p.end and p.start < q.end) or q.replacement == p.replacement:
                    continue
                if consistent(p, q) or consistent(q, p):
                    continue  # one is a word-for-word extension of the other
                if (q.start, q.end) == (p.start, p.end):
                    gaps.append(self._differential(p, q))
                else:
                    gaps.append(p.score - q.score)
            p.features["contested"] = 1.0 if gaps else 0.0
            p.features["competitor_gap"] = max(-5.0, min(5.0, min(gaps))) if gaps else 0.0

    def _differential(self, p: Proposal, q: Proposal) -> float:
        pw, qw = p.replacement.split(), q.replacement.split()
        if len(pw) != len(qw):
            return p.score - q.score
        diff = [(a, b) for a, b in zip(pw, qw) if a != b]
        if not diff:
            return 0.0

        def side(words: list[str], lang: str | None) -> float:
            model = self._model(lang) if lang else None
            if model is None:
                return -15.0
            z, known, letters = model.score_text(" ".join(words))
            return z + KNOWN_WEIGHT * known if letters else 0.0

        return side([a for a, _ in diff], p.language) - side([b for _, b in diff], q.language)

    @staticmethod
    def _suspicious(score: Score, text: str = "") -> bool:
        """Mostly unknown words, or letters glued together by punctuation ("pr;ta").

        Known words with unusual spelling ("lgtm") are not suspicious on their
        own; they can still join a span next to real garble.
        """
        return score.letters >= 1 and (score.known < 0.5 or bool(_INNER_PUNCT.search(text)))

    @staticmethod
    def _runs(tokens: Sequence[Token], source: Layout) -> list[list[int]]:
        runs: list[list[int]] = []
        current: list[int] = []
        for i, tok in enumerate(tokens):
            if tok.kind == SPACE:
                continue
            if tok.kind == PROTECTED or not producible(tok.text, source):
                if current:
                    runs.append(current)
                current = []
                continue
            current.append(i)
        if current:
            runs.append(current)
        return runs

    def _evaluate_run(self, text, tokens, run, source, target, native_of) -> list[Proposal]:
        langs = self.layout_languages[target.id]
        evals: list[ChunkEval] = []
        for i in run:
            original = tokens[i].text
            variants = convert_variants(original, source, target)
            if len(variants) == 1:
                candidate = variants[0].text
                tscore = self.best_score(candidate, langs)
            else:
                scored = [(self.best_score(v.text, langs), v.text) for v in variants]
                tscore, candidate = max(scored, key=lambda sv: sv[0].z + KNOWN_WEIGHT * sv[0].known)
            src = native_of(i)
            # Only rewrites that change letters count; punctuation-only changes
            # (e.g. "cook-off" -> "cook/off" between two Latin layouts) are neutral.
            neutral = _letters(candidate) == _letters(original)
            evals.append(ChunkEval(i, original, candidate, src, tscore, _purity(candidate, target.script), neutral))

        spans = self._select_spans(evals)
        # Suspicious letters in this run that the pair's spans leave unexplained:
        # real wrong-layout typing converts consistently, while foreign or noisy
        # text only occasionally turns into a word of the target language.
        covered = {k for lo, hi in spans for k in range(lo, hi + 1)}
        suspicious = [(k, e.source.letters) for k, e in enumerate(evals) if self._suspicious(e.source, e.original)]
        total_susp = sum(n for _, n in suspicious)
        unexplained = sum(n for k, n in suspicious if k not in covered) / total_susp if total_susp else 0.0
        proposals = []
        for lo, hi in spans:
            chosen = evals[lo : hi + 1]
            letters = sum(e.target.letters for e in chosen if not e.neutral)
            if letters < self.min_letters:
                continue
            start, end = tokens[chosen[0].token_index].start, tokens[chosen[-1].token_index].end
            original = text[start:end]
            # Rebuild the replacement keeping the original whitespace between chunks.
            parts: list[str] = []
            pos = start
            for e in chosen:
                tok = tokens[e.token_index]
                parts.append(text[pos : tok.start])
                parts.append(e.candidate)
                pos = tok.end
            replacement = "".join(parts)
            prop = self._proposal(text, tokens, start, end, original, replacement, source, target, langs)
            prop.features["unexplained"] = unexplained
            proposals.append(prop)
        return proposals

    @classmethod
    def _select_spans(cls, evals: list[ChunkEval]) -> list[tuple[int, int]]:
        flips = [not e.neutral and e.gain > 0 for e in evals]
        n = len(evals)
        spans: list[tuple[int, int]] = []
        i = 0
        while i < n:
            if not flips[i]:
                i += 1
                continue
            lo = hi = i
            j = i + 1
            while j < n:
                if flips[j]:
                    hi = j
                    j += 1
                    continue
                if cls._bridgeable(evals[j]) and any(flips[j + 1 :]):
                    j += 1
                    continue
                break
            # Extend over adjacent chunks that are no better as typed (e.g. a short
            # word that happens to exist in both languages at the edge of a span).
            if hi > lo or evals[lo].target.letters > 3:
                strong = sum(flips[lo : hi + 1]) >= 2
                while lo > 0 and (not spans or lo - 1 > spans[-1][1]) and cls._edge_ok(evals[lo - 1], strong):
                    lo -= 1
                while hi + 1 < n and not flips[hi + 1] and cls._edge_ok(evals[hi + 1], strong):
                    hi += 1
            spans.append((lo, hi))
            i = hi + 1
        return spans

    @staticmethod
    def _bridgeable(e: ChunkEval) -> bool:
        """A non-flipping chunk between two flipping chunks joins the span."""
        if e.neutral:
            return True
        if Detector._suspicious(e.source, e.original) and e.gain > -4.0:
            return True
        return e.target.letters <= 3 and e.gain > -3.0

    @staticmethod
    def _edge_ok(e: ChunkEval, strong: bool) -> bool:
        if e.neutral:
            return False
        # Next to a span of several corrected words, a word that is valid in both
        # languages ("כשר" / "far") most likely belongs to the same mistake.
        if strong and e.target.known >= 1.0 and e.gain > -2.5:
            return True
        if Detector._suspicious(e.source, e.original) and e.gain > -2.0:
            return True
        return e.target.letters <= 2 and e.gain > -1.0

    def _proposal(self, text, tokens, start, end, original, replacement, source, target, langs) -> Proposal:
        tgt = self.best_score(replacement, langs)
        src = self.native_score(original)
        context_text = " ".join(
            t.text for t in tokens if t.kind == CHUNK and (t.end <= start or t.start >= end)
        )
        ctx_support = 0.0
        has_context = 0.0
        if tgt.lang:
            model = self._model(tgt.lang)
            if model is not None:
                _, ctx_known, ctx_letters = model.score_text(context_text)
                if ctx_letters >= 3:
                    has_context = 1.0
                    ctx_support = ctx_known
        context_conflict = has_context * (1.0 - ctx_support)
        letters = max(tgt.letters, 1)
        features = {
            "delta_z": max(-15.0, min(15.0, tgt.z - src.z)),
            "delta_known": tgt.known - src.known,
            "target_known": tgt.known,
            "source_known": src.known,
            "delta_noise": _noise(original) - _noise(replacement),
            "purity": _purity(replacement, target.script),
            "log_letters": math.log1p(letters),
            "context_support": ctx_support,
            "has_context": has_context,
            "short": 1.0 if letters <= 3 else 0.0,
            "context_conflict": context_conflict,
            # Short fragments inside text of another language are rarely mistakes.
            "short_conflict": context_conflict * (1.0 if letters <= 4 else 0.0),
        }
        return Proposal(start, end, original, replacement, source.id, target.id, tgt.lang, features,
                        score=tgt.z + KNOWN_WEIGHT * tgt.known)
