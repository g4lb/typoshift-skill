from __future__ import annotations

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from typoshift.conversion import convert_text, convert_variants, producible
from typoshift.layouts import builtin_registry

REG = builtin_registry()


def conv(text: str, src: str, dst: str) -> str:
    return convert_text(text, REG.get(src), REG.get(dst)).text


@pytest.mark.parametrize("typed,src,dst,expected", [
    ("פךקשדק גקהקךםפ איק מקסא כקשאורק", "he", "en-US", "please develop the next feature"),
    ("please develop the next feature", "en-US", "he", "פךקשדק גקהקךםפ איק מקסא כקשאורק"),
    ("akuo", "en-US", "he", "שלום"),
    ("ghbdtn rfr ltkf?", "en-US", "ru", "привет как дела,"),
    ("Руддщ Цщкдв", "ru", "en-US", "Hello World"),
    ("j,]trn", "en-US", "ru", "объект"),
    ("ghbdsn", "en-US", "uk", "привіт"),
    ("hgl ,kfg", "en-US", "ar", "الم ونبل"),
    ("kalhm;era", "en-US", "el", "καλημέρα"),
    ("καλημέρα", "el", "en-US", "kalhm;era"),
    ("Hallo", "en-US", "de", "Hallo"),
    ("zes", "en-US", "de", "yes"),
    ("qzerty", "fr", "en-US", "awerty"),
    ("ıt", "tr", "en-US", "it"),
])
def test_known_conversions(typed, src, dst, expected):
    assert conv(typed, src, dst) == expected


def test_whitespace_and_newlines_preserved():
    assert conv("פךקשדק\n\n  איק\tמקסא", "he", "en-US") == "please\n\n  the\tnext"


def test_mirrored_parentheses_follow_physical_keys():
    # On the Hebrew layout Shift+9 produces ")" - converting back restores "(".
    assert conv(")פךקשדק(", "he", "en-US") == "(please)"


def test_unproducible_characters_pass_through():
    res = convert_text("פךקשדק 🙂", REG.get("he"), REG.get("en-US"))
    assert res.text == "please 🙂"
    assert res.passthrough == 1


def test_unmapped_iso_key_kept_as_typed():
    # German "<" lives on the ISO key next to left Shift, which a US (ANSI)
    # keyboard does not have: the character is kept and reported as unmapped.
    res = convert_text("<", REG.get("de"), REG.get("en-US"))
    assert res.text == "<"
    assert res.unmapped == 1


def test_arabic_lam_alef_variants():
    texts = {r.text for r in convert_variants("لا", REG.get("ar"), REG.get("en-US"))}
    assert texts == {"b", "gh"}
    assert conv("b", "en-US", "ar") == "لا"
    assert [ord(c) for c in conv("b", "en-US", "ar")] == [0x644, 0x627]


def test_greek_capital_sigma_is_ambiguous():
    texts = {r.text for r in convert_variants("Σ", REG.get("el"), REG.get("en-US"))}
    assert texts == {"S", "W"}


def test_dead_key_followed_by_space_gives_spacing_accent():
    # German: dead circumflex key then space types "^".
    assert conv("` ", "en-US", "de") == "^"
    assert conv("^", "de", "en-US") == "` "


def test_producible():
    assert producible("שלום עולם", REG.get("he"))
    assert not producible("hello", REG.get("he"))  # lowercase Latin needs another layout
    assert producible("HELLO", REG.get("he"))  # Shift on the Hebrew layout gives Latin capitals
    assert producible("καλημέρα", REG.get("el"))  # έ via the dead tonos key
    assert not producible("привет", REG.get("en-US"))


def _unique_strokes(a, b):
    """Strokes whose characters are unambiguous and non-dead on both layouts."""
    out = []
    for code in a.keys:
        if code not in b.keys:
            continue
        for level in (0, 1):
            ca, cb = a.char_at((code, level)), b.char_at((code, level))
            if not ca or not cb or a.is_dead((code, level)) or b.is_dead((code, level)):
                continue
            if len(a.strokes_for(ca)) == 1 and len(b.strokes_for(cb)) == 1 and (code, level) not in \
                    a.sequences.values() and (code, level) not in b.sequences.values():
                out.append((code, level))
    return out


PAIRS = [("en-US", "he"), ("en-US", "ru"), ("en-US", "ar"), ("en-US", "el"), ("en-US", "uk"), ("ru", "uk"),
         ("en-US", "fr"), ("en-US", "de"), ("he", "ru"), ("en-US", "tr-F"), ("en-US", "cs")]


@pytest.mark.parametrize("src,dst", PAIRS)
@settings(max_examples=60, deadline=None)
@given(data=st.data())
def test_roundtrip_property(src, dst, data):
    a, b = REG.get(src), REG.get(dst)
    strokes = _unique_strokes(a, b)
    seq = data.draw(st.lists(st.sampled_from(strokes), min_size=1, max_size=30))
    text = "".join(a.char_at(s) for s in seq)
    there = convert_text(text, a, b).text
    # "لا" is both the lam-alef key and lam followed by alef: inherently ambiguous
    # (handled by convert_variants), so it is excluded from the exact roundtrip.
    assume(not any(seq in there or seq in text for seq in (*a.sequences, *b.sequences)))
    back = convert_text(there, b, a).text
    assert back == text


@pytest.mark.parametrize("layout_id", sorted(REG.ids()))
def test_identity_conversion(layout_id):
    lay = REG.get(layout_id)
    text = "".join(v[0] for k, v in lay.keys.items() if v[0] and not lay.is_dead((k, 0)))
    expected = text.replace("\ufefb", "\u0644\u0627")  # the Arabic B key is emitted as lam + alef
    assert convert_text(text, lay, lay).text == expected


def test_nfd_input_matches_nfc():
    import unicodedata

    word = "άλφα"
    assert conv(unicodedata.normalize("NFD", word), "el", "en-US") == conv(word, "el", "en-US") == ";alfa"
