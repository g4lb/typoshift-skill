"""Calibrated confidence estimation.

Confidence is the output of a logistic-regression model over the features
computed by :mod:`typoshift.detection`. The weights are *fitted*, never written
by hand: ``tools/calibrate.py`` generates labelled wrong-layout and
correctly-typed samples from held-out vocabulary, runs the detector, and fits
the model. The resulting ``typoshift/data/calibration.json`` records the
training-set size, seed and fit metrics.

If no calibration file is available every confidence is 0.0, so automatic
correction is effectively disabled rather than guessed.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources

from .detection import FEATURES

__all__ = ["Calibration", "load_calibration", "score", "format_confidence"]


def format_confidence(value: float) -> str:
    """Three decimals, truncated (0.9999 shows as 0.999, never as 1.000)."""
    return f"{math.floor(value * 1000) / 1000:.3f}"


@dataclass(frozen=True)
class Calibration:
    weights: dict[str, float]
    bias: float
    means: dict[str, float]
    scales: dict[str, float]
    metadata: dict = field(default_factory=dict)

    def probability(self, features: dict[str, float]) -> float:
        z = self.bias
        for name in FEATURES:
            x = (features.get(name, 0.0) - self.means.get(name, 0.0)) / (self.scales.get(name, 1.0) or 1.0)
            z += self.weights.get(name, 0.0) * x
        if z >= 0:
            return 1.0 / (1.0 + math.exp(-z))
        e = math.exp(z)
        return e / (1.0 + e)

    def to_dict(self) -> dict:
        return {
            "features": list(FEATURES),
            "weights": self.weights,
            "bias": self.bias,
            "means": self.means,
            "scales": self.scales,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Calibration:
        if list(data.get("features", [])) != list(FEATURES):
            raise ValueError("calibration feature set does not match this TypoShift version")
        return cls(
            weights={k: float(v) for k, v in data["weights"].items()},
            bias=float(data["bias"]),
            means={k: float(v) for k, v in data.get("means", {}).items()},
            scales={k: float(v) for k, v in data.get("scales", {}).items()},
            metadata=dict(data.get("metadata", {})),
        )


@lru_cache(maxsize=1)
def load_calibration() -> Calibration | None:
    try:
        raw = (resources.files("typoshift.data") / "calibration.json").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        return Calibration.from_dict(json.loads(raw))
    except (ValueError, KeyError):
        return None


def score(features: dict[str, float], calibration: Calibration | None = None) -> float:
    cal = calibration if calibration is not None else load_calibration()
    if cal is None:
        return 0.0
    # A heuristic model is never certain; never report 1.0.
    return min(0.9999, round(cal.probability(features), 4))
