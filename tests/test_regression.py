"""Regression cases found during development (see tests/data/regression.jsonl)."""

from __future__ import annotations

import json

import pytest
from conftest import ROOT

from typoshift.configuration import DEFAULT_LAYOUTS, Config
from typoshift.engine import Engine
from typoshift.layouts import builtin_registry

CASES = [json.loads(line) for line in (ROOT / "tests" / "data" / "regression.jsonl").read_text(
    encoding="utf-8").splitlines() if line.strip()]
_ENGINES: dict[tuple[str, ...], Engine] = {}


def _engine(layouts):
    key = tuple(layouts or DEFAULT_LAYOUTS)
    if key not in _ENGINES:
        _ENGINES[key] = Engine(Config(layouts=list(key)), registry=builtin_registry())
    return _ENGINES[key]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_regression(case):
    result = _engine(case.get("layouts")).fix(case["input"])
    assert result.corrected == case["expected"], case.get("why")
