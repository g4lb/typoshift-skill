#!/usr/bin/env python3
"""Fit TypoShift's confidence model.

Samples are synthesized from the FrequencyWords vocabularies (never from the
hand-written benchmark corpus, which is reserved for evaluation):

* **positive** inputs: word sequences in language L (frequency-weighted from the
  lexicon, plus out-of-lexicon held-out words), typed on a wrong layout by
  replaying the physical keystrokes; also *mixed* inputs where only a fragment
  of an L sentence was typed on the wrong layout;
* **negative** inputs: correctly typed L sequences, optionally with realistic
  typos or with correctly typed words from another script mixed in.

Every proposal the detector produces is labelled 1 if it reconstructs exactly
the intended text for exactly the mistyped span, else 0. A logistic regression
(L2-regularized, fitted with Newton's method) maps detector features to the
probability that a proposal is correct. 20% of samples are held out to report
calibration error.

Usage::

    python tools/calibrate.py [--samples 24000] [--seed 7]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from build_language_data import LANGUAGES, load_counts  # noqa: E402

from typoshift.confidence import Calibration  # noqa: E402
from typoshift.configuration import DEFAULT_LAYOUTS, Config  # noqa: E402
from typoshift.conversion import convert_text, producible  # noqa: E402
from typoshift.detection import FEATURES  # noqa: E402
from typoshift.engine import Engine  # noqa: E402
from typoshift.layouts import builtin_registry  # noqa: E402

OUT = ROOT / "src" / "typoshift" / "data" / "calibration.json"
HOLDOUT = ROOT / "tools" / "cache" / "holdout"

# language -> its native layout
NATIVE_LAYOUT = {
    "en": "en-US", "he": "he", "ru": "ru", "uk": "uk", "ar": "ar", "el": "el", "fr": "fr", "de": "de",
    "es": "es", "it": "it", "pt": "pt", "tr": "tr", "pl": "pl", "cs": "cs", "sv": "sv", "no": "no",
    "da": "da", "nl": "nl",
}
NON_LATIN = ["he", "ru", "uk", "ar", "el"]
LATIN_OTHER = ["fr", "de", "es", "it", "pt", "tr", "cs", "sv", "no", "da", "nl"]

# (intended language, layout actually active) scenarios and their sampling weight.
SCENARIOS: list[tuple[str, str, float]] = (
    [("en", lay, 3.0) for lay in NON_LATIN]
    + [(lang, "en-US", 3.0) for lang in NON_LATIN]
    + [("ru", "uk", 0.5), ("uk", "ru", 0.5)]
    + [(lang, "en-US", 0.6) for lang in LATIN_OTHER]
    + [("en", NATIVE_LAYOUT[lang], 0.6) for lang in LATIN_OTHER]
)
LENGTHS = [1, 1, 2, 2, 3, 3, 4, 5, 6, 8, 10, 14]


class Vocab:
    def __init__(self, lang: str, rng: random.Random):
        script, codes = LANGUAGES[lang]
        ranked = load_counts(lang, script, codes)[:30_000]
        self.words = [w for w, _ in ranked]
        self.cum: list[float] = []
        total = 0.0
        for _, c in ranked:
            total += c
            self.cum.append(total)
        self.total = total
        lines = (HOLDOUT / f"{lang}.txt").read_text(encoding="utf-8").splitlines()
        self.holdout = [line.split("\t")[0] for line in lines if line.strip()]
        self.rng = rng

    def word(self) -> str:
        if self.rng.random() < 0.15:
            return self.rng.choice(self.holdout)
        x = self.rng.random() * self.total
        lo, hi = 0, len(self.cum) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self.cum[mid] < x:
                lo = mid + 1
            else:
                hi = mid
        return self.words[lo]

    def sentence(self, n: int) -> str:
        words = [self.word() for _ in range(n)]
        if self.rng.random() < 0.5:
            words[0] = words[0][:1].upper() + words[0][1:]
        text = " ".join(words)
        r = self.rng.random()
        if n >= 3 and r < 0.25:
            text += "."
        elif n >= 3 and r < 0.35:
            text += "?"
        if n >= 5 and self.rng.random() < 0.3:
            k = self.rng.randrange(1, n - 1)
            parts = text.split(" ")
            parts[k] += ","
            text = " ".join(parts)
        return text


def typo(word: str, rng: random.Random) -> str:
    if len(word) < 3:
        return word
    i = rng.randrange(len(word) - 1)
    op = rng.random()
    if op < 0.35:
        return word[:i] + word[i + 1] + word[i] + word[i + 2 :]
    if op < 0.6:
        return word[:i] + word[i + 1 :]
    if op < 0.8:
        return word[:i] + word[i] + word[i:]
    return word[:i] + rng.choice(word) + word[i + 1 :]


def make_samples(n: int, rng: random.Random) -> list[dict]:
    registry = builtin_registry()
    vocabs: dict[str, Vocab] = {}

    def vocab(lang: str) -> Vocab:
        if lang not in vocabs:
            vocabs[lang] = Vocab(lang, rng)
        return vocabs[lang]

    weights = [w for _, _, w in SCENARIOS]
    samples = []
    while len(samples) < n:
        lang, typed_layout, _ = rng.choices(SCENARIOS, weights)[0]
        native = registry.get(NATIVE_LAYOUT[lang])
        typed = registry.get(typed_layout)
        # Half the samples use a realistic two-layout setup, half the default set.
        if rng.random() < 0.5:
            layouts = list(dict.fromkeys([native.id, typed.id]))
        else:
            layouts = list(dict.fromkeys(DEFAULT_LAYOUTS + [native.id, typed.id]))
        sentence = vocab(lang).sentence(rng.choice(LENGTHS))
        if not producible(sentence, native):
            continue
        kind = rng.random()
        if kind < 0.4:  # whole input typed on the wrong layout
            wrong = convert_text(sentence, native, typed).text
            if wrong == sentence:
                continue
            samples.append({"text": wrong, "layouts": layouts, "intended": sentence, "kind": "full"})
        elif kind < 0.6:  # only a fragment typed on the wrong layout
            words = sentence.split(" ")
            if len(words) < 3:
                continue
            k = rng.randint(1, min(3, len(words) - 1))
            i = rng.randrange(0, len(words) - k + 1)
            frag = " ".join(words[i : i + k])
            wrong_frag = convert_text(frag, native, typed).text
            if wrong_frag == frag:
                continue
            prefix = " ".join(words[:i]) + (" " if i else "")
            suffix = (" " if i + k < len(words) else "") + " ".join(words[i + k :])
            text = prefix + wrong_frag + suffix
            samples.append({"text": text, "layouts": layouts, "intended": sentence, "kind": "mixed"})
        else:  # correctly typed (negative)
            words = sentence.split(" ")
            r = rng.random()
            if r < 0.35:
                for _ in range(rng.randint(1, 2)):
                    j = rng.randrange(len(words))
                    words[j] = typo(words[j], rng)
            elif r < 0.45 and lang in LATIN_OTHER:
                # Text in a language whose layout is not enabled (e.g. Polish typed
                # on the US layout with the default configuration).
                layouts = list(DEFAULT_LAYOUTS)
            elif r < 0.6:
                other = rng.choice(["en"] if lang != "en" else NON_LATIN)
                for _ in range(rng.randint(1, 2)):
                    words.insert(rng.randrange(len(words) + 1), vocab(other).word())
                layouts = list(dict.fromkeys(layouts + [NATIVE_LAYOUT[other]]))
            text = " ".join(words)
            samples.append({"text": text, "layouts": layouts, "intended": text, "kind": "negative"})
    return samples


def token_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def is_correct(text: str, intended: str, start: int, end: int, replacement: str) -> tuple[bool, set[int]]:
    """Token-aligned check: the proposal rewrites its tokens into exactly the intended tokens."""
    spans = token_spans(text)
    want = intended.split()
    idx = [i for i, (a, b) in enumerate(spans) if a >= start and b <= end]
    if len(spans) != len(want) or not idx:
        return False, set()
    return replacement.split() == want[idx[0] : idx[-1] + 1], set(idx)


def label(samples: list[dict]) -> tuple[list[list[float]], list[int], dict]:
    engines: dict[tuple[str, ...], Engine] = {}
    xs: list[list[float]] = []
    ys: list[int] = []
    stats = {"inputs": len(samples), "proposals": 0, "positive_inputs": 0, "recovered": 0}
    for s in samples:
        key = tuple(s["layouts"])
        if key not in engines:
            engines[key] = Engine(Config(layouts=list(key)), registry=builtin_registry())
        props = engines[key].proposals(s["text"])
        typed, intended = s["text"].split(), s["intended"].split()
        wrong = {i for i, (a, b) in enumerate(zip(typed, intended)) if a != b}
        if wrong:
            stats["positive_inputs"] += 1
        covered: set[int] = set()
        for p in props:
            ok, idx = is_correct(s["text"], s["intended"], p.start, p.end, p.replacement)
            if ok:
                covered |= idx
            xs.append([p.features[f] for f in FEATURES])
            ys.append(int(ok))
        stats["recovered"] += int(bool(wrong) and wrong <= covered)
        stats["proposals"] += len(props)
    return xs, ys, stats


def standardize(xs: list[list[float]]) -> tuple[list[float], list[float]]:
    d = len(xs[0])
    means = [sum(x[j] for x in xs) / len(xs) for j in range(d)]
    scales = [math.sqrt(sum((x[j] - means[j]) ** 2 for x in xs) / len(xs)) or 1.0 for j in range(d)]
    return means, scales


def solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col and m[col][col]:
                f = m[r][col] / m[col][col]
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit(xs: list[list[float]], ys: list[int], l2: float = 1.0, iters: int = 30) -> list[float]:
    """L2-regularized logistic regression via Newton-Raphson. Returns [bias, w1..wd]."""
    rows = [[1.0] + x for x in xs]
    d = len(rows[0])
    w = [0.0] * d
    for _ in range(iters):
        grad = [0.0] * d
        hess = [[0.0] * d for _ in range(d)]
        for x, y in zip(rows, ys):
            z = sum(wi * xi for wi, xi in zip(w, x))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            g = p - y
            s = p * (1 - p)
            for i in range(d):
                grad[i] += g * x[i]
                for j in range(i, d):
                    hess[i][j] += s * x[i] * x[j]
        for i in range(d):
            for j in range(i):
                hess[i][j] = hess[j][i]
            if i:  # do not regularize the bias
                grad[i] += l2 * w[i]
                hess[i][i] += l2
        step = solve(hess, grad)
        w = [wi - si for wi, si in zip(w, step)]
        if max(abs(s) for s in step) < 1e-7:
            break
    return w


def evaluate(cal: Calibration, xs, ys) -> dict:
    probs = [cal.probability(dict(zip(FEATURES, x))) for x in xs]
    eps = 1e-12
    logloss = -sum(y * math.log(p + eps) + (1 - y) * math.log(1 - p + eps) for p, y in zip(probs, ys)) / len(ys)
    bins = [[0, 0.0, 0] for _ in range(10)]
    for p, y in zip(probs, ys):
        b = bins[min(9, int(p * 10))]
        b[0] += 1
        b[1] += p
        b[2] += y
    ece = sum(abs(b[1] - b[2]) for b in bins if b[0]) / len(ys)
    out = {"proposals": len(ys), "positives": sum(ys), "log_loss": round(logloss, 4), "ece": round(ece, 4),
           "reliability": [{"bin": f"{i / 10:.1f}-{(i + 1) / 10:.1f}", "n": b[0],
                            "mean_confidence": round(b[1] / b[0], 3) if b[0] else None,
                            "observed_accuracy": round(b[2] / b[0], 3) if b[0] else None}
                           for i, b in enumerate(bins)]}
    for t in (0.5, 0.8, 0.9, 0.95):
        sel = [(p, y) for p, y in zip(probs, ys) if p >= t]
        out[f"precision@{t}"] = round(sum(y for _, y in sel) / len(sel), 4) if sel else None
        out[f"recall@{t}"] = round(sum(y for _, y in sel) / max(1, sum(ys)), 4)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--samples", type=int, default=24_000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--l2", type=float, default=1.0)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    t0 = time.time()
    samples = make_samples(args.samples, rng)
    rng.shuffle(samples)
    split = int(len(samples) * 0.8)
    train_x, train_y, train_stats = label(samples[:split])
    test_x, test_y, test_stats = label(samples[split:])
    means, scales = standardize(train_x)
    zx = [[(v - m) / s for v, m, s in zip(x, means, scales)] for x in train_x]
    w = fit(zx, train_y, args.l2)
    cal = Calibration(
        weights={f: round(wi, 6) for f, wi in zip(FEATURES, w[1:])},
        bias=round(w[0], 6),
        means={f: round(m, 6) for f, m in zip(FEATURES, means)},
        scales={f: round(s, 6) for f, s in zip(FEATURES, scales)},
    )
    metrics = {"train": evaluate(cal, train_x, train_y), "heldout": evaluate(cal, test_x, test_y)}
    cal = Calibration(cal.weights, cal.bias, cal.means, cal.scales, metadata={
        "generated": date.today().isoformat(),
        "tool": "tools/calibrate.py",
        "seed": args.seed,
        "samples": args.samples,
        "l2": args.l2,
        "train_inputs": train_stats,
        "heldout_inputs": test_stats,
        "metrics": metrics,
        "note": "Confidence = P(proposal is the exact intended text | proposal generated) under the "
                "synthetic calibration mix (about 60% of inputs contain a wrong-layout span).",
    })
    OUT.write_text(json.dumps(cal.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"weights": cal.weights, "bias": cal.bias, "heldout": {
        k: v for k, v in metrics["heldout"].items() if k != "reliability"}, "train_inputs": train_stats,
        "seconds": round(time.time() - t0, 1)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
