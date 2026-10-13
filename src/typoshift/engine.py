"""Public engine API.

>>> from typoshift import fix
>>> fix("פךקשדק גקהקךםפ איק מקסא כקשאורק").corrected
'please develop the next feature'
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any

from . import confidence as _confidence
from .configuration import Config, load_config
from .conversion import convert_text, producible
from .detection import Detector, Proposal, consistent
from .layouts.registry import LayoutRegistry
from .protection import Protector
from .tokenizer import CHUNK, tokenize

__all__ = ["Mode", "Correction", "FixResult", "Engine", "fix", "detect", "convert"]

METHOD = "keyboard_layout_mapping"
MANUAL_METHOD = "manual_keyboard_layout_mapping"

# Reconstructed instructions matching these patterns always require explicit
# user confirmation before an agent acts on them.
_DESTRUCTIVE = re.compile(
    r"\b(?:rm\s+-[a-z]*[rf]|delete|remove|drop|truncate|destroy|wipe|erase|purge|reset\s+--hard|"
    r"force[- ]?push|push\s+(?:-f|--force)|overwrite|deploy|publish|revert|uninstall|kill|shutdown|"
    r"format|rollback)\b"
    r"|(?:מחק|תמחק|למחוק|מחיקה|הסר|תסיר|לפרוס|דרוס)"
    r"|(?:удали|удалить|удаление|сотри|очисти|откати|задеплой|сбрось)"
    r"|(?:видали|видалити|очисти)"
    r"|(?:احذف|حذف|امسح)",
    re.IGNORECASE,
)


class Mode(str, Enum):
    AUTO = "auto"
    SUGGEST = "suggest"
    MANUAL = "manual"
    DISABLED = "disabled"


@dataclass
class Correction:
    start: int
    end: int
    original: str
    replacement: str
    source_layout: str
    target_layout: str
    language: str | None
    confidence: float | None
    applied: bool
    equivalent_layouts: list[str] = field(default_factory=list)
    features: dict[str, float] | None = None

    def to_dict(self, verbose: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "start": self.start,
            "end": self.end,
            "original": self.original,
            "replacement": self.replacement,
            "source_layout": self.source_layout,
            "target_layout": self.target_layout,
            "language": self.language,
            "confidence": self.confidence,
            "applied": self.applied,
        }
        if self.equivalent_layouts:
            data["equivalent_layouts"] = self.equivalent_layouts
        if verbose and self.features is not None:
            data["features"] = {k: round(v, 4) for k, v in self.features.items()}
        return data


@dataclass
class FixResult:
    original: str
    corrected: str
    mode: str
    corrections: list[Correction] = field(default_factory=list)
    suggestions: list[Correction] = field(default_factory=list)
    method: str = METHOD

    @property
    def was_corrected(self) -> bool:
        return self.corrected != self.original

    @property
    def primary(self) -> Correction | None:
        pool = self.corrections or self.suggestions
        return max(pool, key=lambda c: (c.end - c.start, c.confidence or 0)) if pool else None

    @property
    def requires_confirmation(self) -> bool:
        texts = [c.replacement for c in self.corrections + self.suggestions]
        return any(_DESTRUCTIVE.search(t) for t in texts)

    @property
    def suggested_text(self) -> str:
        """The prompt with every correction and suggestion applied."""
        return _apply(self.original, self.corrections + self.suggestions)

    def to_dict(self, verbose: bool = False) -> dict[str, Any]:
        p = self.primary
        conf = min((c.confidence for c in self.corrections if c.confidence is not None), default=None)
        if conf is None and p is not None:
            conf = p.confidence
        data: dict[str, Any] = {
            "original": self.original,
            "corrected": self.corrected,
            "source_layout": p.source_layout if p else None,
            "target_layout": p.target_layout if p else None,
            "target_language": p.language if p else None,
            "confidence": conf,
            "was_corrected": self.was_corrected,
            "method": self.method,
            "mode": self.mode,
            "requires_confirmation": self.requires_confirmation,
            "corrections": [c.to_dict(verbose) for c in self.corrections],
            "suggestions": [c.to_dict(verbose) for c in self.suggestions],
        }
        if self.suggestions:
            data["suggested_text"] = self.suggested_text
        return data


def _apply(text: str, corrections: list[Correction]) -> str:
    out = text
    for c in sorted(corrections, key=lambda c: c.start, reverse=True):
        out = out[: c.start] + c.replacement + out[c.end :]
    return out


class Engine:
    """Keyboard-layout correction engine. Thread-compatible; not thread-safe."""

    def __init__(self, config: Config | None = None, registry: LayoutRegistry | None = None):
        self.config = (config or Config()).validate()
        self.registry = registry or LayoutRegistry.load(self.config.resolved_layouts_dir())
        missing = [lid for lid in self.config.layouts if lid not in self.registry]
        if missing:
            raise KeyError(f"unknown layout(s) in configuration: {', '.join(missing)}")
        self.layout_ids = [self.registry.get(lid).id for lid in self.config.layouts]
        self.protector = Protector(self.config.protection.extra_patterns, self.config.protection.disabled_rules)
        self.detector = Detector(self.registry, self.layout_ids, self.config.layout_languages, self.config.min_letters)

    # -- public API ----------------------------------------------------------------
    def fix(
        self,
        text: str,
        mode: Mode | str | None = None,
        source: str | None = None,
        target: str | None = None,
    ) -> FixResult:
        mode = Mode(mode or self.config.mode)
        if mode is Mode.DISABLED or not text.strip():
            return FixResult(text, text, mode.value)
        if mode is Mode.MANUAL:
            return self._manual(text, source or self.config.manual_source, target or self.config.manual_target)

        proposals = self.proposals(text)
        corrections: list[Correction] = []
        suggestions: list[Correction] = []
        for prop in self._select(proposals):
            conf = prop.confidence
            if conf < self.config.suggest_threshold:
                continue
            apply = (mode is Mode.AUTO and conf >= self.config.auto_threshold and self._long_enough(prop)
                     and self._script_policy_allows(prop))
            item = Correction(prop.start, prop.end, prop.original, prop.replacement, prop.source_layout,
                              prop.target_layout, prop.language, conf, apply, prop.equivalent_layouts,
                              prop.features)
            (corrections if apply else suggestions).append(item)
        corrected = _apply(text, corrections)
        return FixResult(text, corrected, mode.value, corrections, suggestions)

    def detect(self, text: str) -> FixResult:
        """Report candidate corrections without applying any."""
        return self.fix(text, Mode.SUGGEST)

    def convert(self, text: str, source: str, target: str) -> str:
        """Convert all of ``text`` from ``source`` to ``target`` layout, without protection."""
        return convert_text(text, self.registry.get(source), self.registry.get(target)).text

    def proposals(self, text: str) -> list[Proposal]:
        # Offsets refer to the caller's string; chunks are NFC-normalized during conversion.
        tokens = tokenize(text, self.protector)
        props = self.detector.propose(text, tokens)
        for p in props:
            p.confidence = _confidence.score(p.features)
        return props

    # -- internals -------------------------------------------------------------------
    def _select(self, proposals: list[Proposal]) -> list[Proposal]:
        """Greedy non-overlapping selection, highest confidence (then longest) first.

        A proposal that strictly extends an already chosen one and agrees with it
        word for word supersedes it (e.g. a full-sentence correction over a
        partial one produced by a different source layout).
        """
        chosen: list[Proposal] = []
        for p in sorted(proposals, key=lambda p: (-p.confidence, -(p.end - p.start), p.start)):
            overlapping = [c for c in chosen if not (p.end <= c.start or p.start >= c.end)]
            if not overlapping:
                chosen.append(p)
                continue
            if p.confidence >= self.config.suggest_threshold and all(_extends(p, c) for c in overlapping):
                for c in overlapping:
                    chosen.remove(c)
                chosen.append(p)
                continue
            for c in overlapping:
                if p.replacement == c.replacement and p.target_layout not in c.equivalent_layouts \
                        and p.target_layout != c.target_layout:
                    c.equivalent_layouts.append(p.target_layout)
        return sorted(chosen, key=lambda p: p.start)

    def _script_policy_allows(self, prop: Proposal) -> bool:
        if self.config.same_script_auto:
            return True
        return self.registry.get(prop.source_layout).script != self.registry.get(prop.target_layout).script

    def _long_enough(self, prop: Proposal) -> bool:
        """Safety policy: very short spans are only auto-applied with supporting context."""
        letters = round(math.expm1(prop.features["log_letters"]))
        supported = prop.features["has_context"] and prop.features["context_support"] >= 0.5
        return letters >= self.config.min_auto_letters or bool(supported)

    def _manual(self, text: str, source: str | None, target: str | None) -> FixResult:
        if not source or not target:
            raise ValueError("manual mode requires both a source and a target layout")
        src, tgt = self.registry.get(source), self.registry.get(target)
        tokens = tokenize(text, self.protector)
        corrections: list[Correction] = []
        for tok in tokens:
            if tok.kind != CHUNK or not producible(tok.text, src):
                continue
            converted = convert_text(tok.text, src, tgt).text
            if converted != tok.text:
                corrections.append(Correction(tok.start, tok.end, tok.text, converted, src.id, tgt.id,
                                              None, None, True))
        corrections = _merge_adjacent(text, corrections)
        return FixResult(text, _apply(text, corrections), Mode.MANUAL.value, corrections, method=MANUAL_METHOD)


def _extends(p: Proposal, c: Proposal) -> bool:
    """True if ``p`` strictly extends ``c`` and agrees with it word for word."""
    return (p.start, p.end) != (c.start, c.end) and consistent(p, c)


def _merge_adjacent(text: str, corrections: list[Correction]) -> list[Correction]:
    merged: list[Correction] = []
    for c in corrections:
        if merged and text[merged[-1].end : c.start].isspace():
            last = merged[-1]
            gap = text[last.end : c.start]
            merged[-1] = Correction(last.start, c.end, text[last.start : c.end], last.replacement + gap + c.replacement,
                                    last.source_layout, last.target_layout, None, None, True)
        else:
            merged.append(c)
    return merged


@lru_cache(maxsize=1)
def _default_engine() -> Engine:
    return Engine(load_config())


def fix(text: str, mode: Mode | str | None = None, source: str | None = None, target: str | None = None) -> FixResult:
    """Fix ``text`` using the user's configuration."""
    return _default_engine().fix(text, mode, source, target)


def detect(text: str) -> FixResult:
    return _default_engine().detect(text)


def convert(text: str, source: str, target: str) -> str:
    return _default_engine().convert(text, source, target)
