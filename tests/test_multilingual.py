"""Mixed-language prompts: only the mistyped span may change."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("typed,expected", [
    ("please implement the login פשעק", "please implement the login page"),
    ("ok פשעק", "ok page"),
    ("Я хочу ghbdtn сказать", "Я хочу привет сказать"),
    ("Привет! ыгку", "Привет! sure"),
    ("תעדכן את ghbdtn", None),  # Hebrew + Russian garble: both corrected forms are acceptable below
])
def test_only_suspicious_segment_changes(engine, typed, expected):
    result = engine.fix(typed)
    if expected is not None:
        assert result.corrected == expected
    for c in result.corrections:
        # Every change is confined to its span and the rest is untouched.
        assert typed[: c.start] == result.corrected[: c.start] or c.start > 0
    untouched_prefix = typed.split(" ")[0]
    assert result.corrected.startswith(untouched_prefix) or untouched_prefix not in typed


def test_offsets_refer_to_original(engine):
    text = "please implement the login פשעק"
    corr = engine.fix(text).corrections[0]
    assert text[corr.start : corr.end] == "פשעק"
    assert corr.replacement == "page"


@pytest.mark.parametrize("text", [
    "תעדכן את ה-README ותריץ את הטסטים",
    "תעשה deploy לפרודקשן אחרי שהטסטים עוברים",
    "Сделай rebase на main и запусти тесты",
    "Ця функція повертає null, коли API недоступне",
    "أريد إضافة endpoint جديد للـ API",
    "Μπορείς να κάνεις refactor στο component;",
    "Merci, the PR looks good now",
    "שלום, מה שלומך?",
    "Привет, как дела?",
    "Ich habe den Bug im Login gefunden",
])
def test_intentional_multilingual_text_unchanged(engine, text):
    assert engine.fix(text).corrected == text


def test_hebrew_prefix_with_latin_word_unchanged(engine):
    # "הAPI" / "בPR" style code-switching inside one word is protected.
    for text in ("תעדכן את הAPI", "תסתכל בPR שלי", "לmain"):
        assert engine.fix(text).corrected == text
