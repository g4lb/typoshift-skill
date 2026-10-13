from __future__ import annotations

import tomllib

import pytest

from typoshift.configuration import Config, ConfigError, dumps_toml, load_config, user_config_path
from typoshift.system_layouts import parse_linux_gsettings, parse_macos, parse_setxkbmap, parse_windows


def write_user(text: str) -> None:
    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_defaults():
    cfg = load_config()
    assert cfg.mode == "auto" and "en-US" in cfg.layouts and cfg.sources == []


def test_layering_user_project_env(tmp_path, monkeypatch):
    write_user('mode = "suggest"\nauto_threshold = 0.95\n[hook]\nshow_message = false\n')
    (tmp_path / "work" / ".typoshift.toml").write_text('layouts = ["en-US", "he"]\n', encoding="utf-8")
    cfg = load_config()
    assert cfg.mode == "suggest" and cfg.auto_threshold == 0.95
    assert cfg.layouts == ["en-US", "he"] and cfg.hook.show_message is False
    assert len(cfg.sources) == 2
    monkeypatch.setenv("TYPOSHIFT_MODE", "disabled")
    assert load_config().mode == "disabled"


@pytest.mark.parametrize("text,match", [
    ('mode = "loud"', "mode must be one of"),
    ("auto_threshold = 2", "between 0 and 1"),
    ("suggest_threshold = 0.95\nauto_threshold = 0.9", "must not exceed"),
    ('layouts = ["en-US"]', "at least two"),
    ("unknown_key = 1", "unknown setting"),
    ("[hook]\nnope = 1", "unknown setting hook.nope"),
    ("this is not toml", "invalid TOML"),
])
def test_invalid_config(text, match):
    write_user(text)
    with pytest.raises(ConfigError, match=match):
        load_config()


def test_toml_roundtrip():
    data = Config().to_dict()
    assert tomllib.loads(dumps_toml(data))["layouts"] == data["layouts"]
    assert tomllib.loads(dumps_toml({"a": 'quote " and \\ backslash'}))["a"] == 'quote " and \\ backslash'


def test_parse_macos():
    out = '''(
        {
        InputSourceKind = "Keyboard Layout";
        "KeyboardLayout ID" = 252;
        "KeyboardLayout Name" = ABC;
    },
        {
        "KeyboardLayout Name" = Hebrew;
    },
        {
        "KeyboardLayout Name" = "Russian - PC";
    },
        {
        "Bundle ID" = "com.apple.CharacterPaletteIM";
    }
)'''
    assert parse_macos(out) == ["en-US", "he", "ru"]


def test_parse_linux():
    assert parse_linux_gsettings("[('xkb', 'us'), ('xkb', 'il'), ('ibus', 'mozc')]") == ["en-US", "he"]
    assert parse_linux_gsettings("@a(ss) []") == []
    assert parse_setxkbmap("rules: evdev\nmodel: pc105\nlayout: us,ru\n") == ["en-US", "ru"]


def test_parse_windows():
    assert parse_windows("0409:00000409\r\n040D:0002040D\r\n0419:00000419\r\n") == ["en-US", "he", "ru"]


@pytest.mark.parametrize("text", [
    '[hook]\nenabled = "false"',
    '[hook]\nmax_prompt_chars = "20k"',
    '[protection]\nextra_patterns = "abc"',
    '[protection]\nextra_patterns = ["(unclosed"]',
    '[layout_languages]\nhe = "he"',
    'layout_languages = "x"',
    'layouts = ["en-US", 5]',
    'min_letters = "2"',
    'same_script_auto = "yes"',
])
def test_wrong_types_rejected(text):
    write_user(text)
    with pytest.raises(ConfigError):
        load_config()
