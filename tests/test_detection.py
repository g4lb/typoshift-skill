from __future__ import annotations

import json

import pytest

from typoshift import fix
from typoshift.configuration import Config
from typoshift.engine import Engine, Mode
from typoshift.layouts import builtin_registry

SPEC_INPUT = "פךקשדק גקהקךםפ איק מקסא כקשאורק"


def test_spec_example(engine):
    result = engine.fix(SPEC_INPUT)
    data = result.to_dict()
    assert result.corrected == "please develop the next feature"
    assert data["source_layout"] == "he"
    assert data["target_layout"] == "en-US"
    assert data["target_language"] == "en"
    assert data["was_corrected"] is True
    assert data["method"] == "keyboard_layout_mapping"
    assert 0.9 <= data["confidence"] < 1.0
    assert data["original"] == SPEC_INPUT


def test_schema_is_json_serializable(engine):
    data = engine.fix(SPEC_INPUT).to_dict(verbose=True)
    json.dumps(data, ensure_ascii=False)
    assert set(data) >= {"original", "corrected", "source_layout", "target_layout", "confidence",
                         "was_corrected", "method", "corrections", "suggestions", "requires_confirmation"}
    assert "features" in data["corrections"][0]


@pytest.mark.parametrize("typed,expected", [
    ("ghbdtn rfr ltkf", "привет как дела"),
    ("Руддщ Цщкдв", "Hello World"),
    ("יקךךם 'םרךג", "hello world"),
    ("ыгку", "sure"),
    ("Fix the ЦУИЫЩСЛУЕ handler", "Fix the WEBSOCKET handler"),
    ("hgl ,kfg", "الم ونبل"),
])
def test_corrections(engine, typed, expected):
    assert engine.fix(typed).corrected == expected


def test_greek_with_dead_keys(make_engine):
    assert make_engine("en-US", "el").fix("kalhm;era sas").corrected.startswith("καλημέρα")


def test_ukrainian(make_engine):
    # The Ukrainian comma is Shift+/ (US "?") and "?" is Shift+7 (US "&").
    assert make_engine("en-US", "uk").fix("ghbdsn? zr cghfdb&").corrected == "привіт, як справи?"


def test_confidence_is_not_constant(engine):
    a = engine.fix(SPEC_INPUT).to_dict()["confidence"]
    b = engine.fix("ok פשעק").to_dict()["confidence"]
    assert a != b


def test_identical_layouts_reported_as_equivalent(make_engine):
    result = make_engine("en-US", "pl", "ru").detect("ghbdtn rfr ltkf")
    assert result.suggestions[0].target_layout == "ru"
    result = make_engine("ru", "en-US", "pl").fix("Руддщ цщкдв")
    corr = result.corrections[0]
    assert corr.target_layout == "en-US"
    assert "pl" in corr.equivalent_layouts


def test_modes(engine):
    assert engine.fix(SPEC_INPUT, Mode.DISABLED).corrected == SPEC_INPUT
    suggested = engine.fix(SPEC_INPUT, "suggest")
    assert suggested.corrected == SPEC_INPUT
    assert suggested.suggested_text == "please develop the next feature"
    assert suggested.suggestions and not suggested.corrections
    manual = engine.fix("ghbdtn vbh", "manual", "en-US", "ru")
    assert manual.corrected == "привет мир"
    assert manual.method == "manual_keyboard_layout_mapping"
    with pytest.raises(ValueError):
        engine.fix("x", "manual")


def test_manual_mode_respects_protection(engine):
    out = engine.fix("ghbdtn src/app.py vbh", "manual", "en-US", "ru").corrected
    assert out == "привет src/app.py мир"


def test_empty_and_whitespace(engine):
    for text in ("", "   ", "\n\n"):
        assert engine.fix(text).corrected == text


def test_whitespace_preserved(engine):
    text = "  פךקשדק\n\tגקהקךםפ  איק\n"
    assert engine.fix(text).corrected == "  please\n\tdevelop  the\n"


def test_threshold_one_disables_auto(make_engine):
    eng = make_engine("en-US", "he", auto_threshold=1.0)
    result = eng.fix(SPEC_INPUT)
    assert result.corrected == SPEC_INPUT
    assert result.suggestions


def test_missing_calibration_disables_auto(monkeypatch, engine):
    from typoshift import confidence

    monkeypatch.setattr(confidence, "load_calibration", lambda: None)
    assert engine.fix(SPEC_INPUT).corrected == SPEC_INPUT


def test_module_level_fix_uses_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('mode = "disabled"\n', encoding="utf-8")
    assert fix(SPEC_INPUT).corrected == SPEC_INPUT


def test_unknown_layout_in_config():
    with pytest.raises(KeyError):
        Engine(Config(layouts=["en-US", "xx"]), registry=builtin_registry())
