"""Layout data: completeness, provenance and per-layout key mappings.

The expected rows below are regression fixtures. They were checked against the
xkeyboard-config symbol files vendored in tools/xkb (the same source the data
is generated from), and test_generated_data_is_current proves the shipped JSON
still matches those sources.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from conftest import ROOT

from typoshift.layouts import LayoutError, LayoutRegistry, layout_from_dict

EXPECTED_IDS = {
    "en-US", "he", "ru", "ar", "fr", "de", "es", "it", "pt", "pt-BR", "uk", "el", "tr", "tr-F", "pl", "cs",
    "sv", "no", "da", "nl",
}

# Base level of the top (AD01-AD12), home (AC01-AC11) and bottom (AB01-AB10) rows.
ROWS = {
    "en-US": ("qwertyuiop[]", "asdfghjkl;'", "zxcvbnm,./"),
    "he": ("/'קראטוןםפ][", "שדגכעיחלךף,", "זסבהנמצתץ."),
    "ru": ("йцукенгшщзхъ", "фывапролджэ", "ячсмитьбю."),
    "uk": ("йцукенгшщзхї", "фівапролджє", "ячсмитьбю."),
    "ar": ("ضصثقفغعهخحجد", "شسيبلاتنمكط", "ئءؤرﻻىةوزظ"),
    "el": (";ςερτυθιοπ[]", "ασδφγηξκλ´'", "ζχψωβνμ,./"),
    "fr": ("azertyuiop^$", "qsdfghjklmù", "wxcvbn,;:!"),
    "de": ("qwertzuiopü+", "asdfghjklöä", "yxcvbnm,.-"),
    "es": ("qwertyuiop`+", "asdfghjklñ´", "zxcvbnm,.-"),
    "it": ("qwertyuiopè+", "asdfghjklòà", "zxcvbnm,.-"),
    "pt": ("qwertyuiop+´", "asdfghjklçº", "zxcvbnm,.-"),
    "pt-BR": ("qwertyuiop´[", "asdfghjklç~", "zxcvbnm,.;"),
    "tr": ("qwertyuıopğü", "asdfghjklşi", "zxcvbnmöç."),
    "tr-F": ("fgğıodrnhpqw", "uieaütkmlyş", "jövcçzsb.,"),
    "pl": ("qwertyuiop[]", "asdfghjkl;'", "zxcvbnm,./"),
    "cs": ("qwertzuiopú)", "asdfghjklů§", "yxcvbnm,.-"),
    "sv": ("qwertyuiopå¨", "asdfghjklöä", "zxcvbnm,.-"),
    "no": ("qwertyuiopå¨", "asdfghjkløæ", "zxcvbnm,.-"),
    "da": ("qwertyuiopå¨", "asdfghjklæø", "zxcvbnm,.-"),
    "nl": ("qwertyuiop¨*", "asdfghjkl+´", "zxcvbnm,.-"),
}

NUMBER_ROW_BASE = {
    "en-US": "`1234567890-=", "he": ";1234567890-=", "ru": "ё1234567890-=", "fr": "²&é\"'(-è_çà)=",
    "de": "^1234567890ß´", "cs": ";+ěščřžýáíé=´", "el": "`1234567890-=", "tr": "\"1234567890*-",
}


def row(layout, prefix: str, n: int, level: int = 0) -> str:
    return "".join(layout.keys.get(f"{prefix}{i:02d}", (None, None))[level] or "·" for i in range(1, n + 1))


def test_all_twenty_layouts_present(registry):
    assert EXPECTED_IDS <= set(registry.ids())
    assert len(EXPECTED_IDS) == 20


@pytest.mark.parametrize("layout_id", sorted(EXPECTED_IDS))
def test_letter_rows(registry, layout_id):
    lay = registry.get(layout_id)
    top, home, bottom = ROWS[layout_id]
    assert row(lay, "AD", 12) == top
    assert row(lay, "AC", 11) == home
    assert row(lay, "AB", 10) == bottom


@pytest.mark.parametrize("layout_id", sorted(NUMBER_ROW_BASE))
def test_number_row(registry, layout_id):
    lay = registry.get(layout_id)
    assert (lay.keys["TLDE"][0] or "·") + row(lay, "AE", 12) == NUMBER_ROW_BASE[layout_id]


@pytest.mark.parametrize("layout_id", sorted(EXPECTED_IDS))
def test_provenance_and_shape(registry, layout_id):
    lay = registry.get(layout_id)
    assert lay.source["database"] == "xkeyboard-config"
    assert lay.source["commit"]
    assert lay.languages and lay.script
    main_keys = [f"AD{i:02d}" for i in range(1, 11)] + [f"AC{i:02d}" for i in range(1, 10)] + \
        [f"AB{i:02d}" for i in range(1, 8)]
    for code in main_keys:
        base, shift = lay.keys[code]
        assert base and shift, f"{layout_id} {code} incomplete"


@pytest.mark.parametrize("layout_id", ["ru", "uk", "el", "de", "fr", "tr", "sv", "cs"])
def test_shift_is_uppercase_for_letters(registry, layout_id):
    lay = registry.get(layout_id)
    special = {("el", "ς"): "Σ", ("tr", "i"): "İ"}
    for code, (base, shift) in lay.keys.items():
        if base and base.isalpha() and shift and shift.isalpha() and code.startswith(("AD", "AC", "AB")):
            assert shift == special.get((layout_id, base), base.upper()), f"{layout_id} {code}: {base!r}/{shift!r}"


def test_hebrew_shift_gives_latin_capitals(registry):
    he = registry.get("he")
    assert he.keys["AD03"] == ("ק", "E")
    assert he.keys["AC01"] == ("ש", "A")


def test_parentheses_are_mirrored_on_hebrew_and_arabic(registry):
    for lid in ("he", "ar"):
        lay = registry.get(lid)
        assert lay.keys["AE09"][1] == ")" and lay.keys["AE10"][1] == "("


def test_polish_programmers_identical_to_us_on_levels_1_2(registry):
    assert registry.get("pl").keys == registry.get("en-US").keys


def test_arabic_lam_alef_sequence(registry):
    ar = registry.get("ar")
    assert ar.sequences["لا"] == ("AB05", 0)
    assert ar.output_at(("AB05", 0)) == "لا"


def test_dead_keys(registry):
    assert registry.get("el").is_dead(("AC10", 0))
    assert registry.get("de").is_dead(("TLDE", 0))
    assert not registry.get("en-US").dead_keys


def test_generated_data_is_current():
    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "generate_layouts.py"), "--check"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_generated_docs_are_current():
    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "generate_docs.py"), "--check"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_custom_layout_from_user_dir(tmp_path, registry):
    data = registry.get("he").to_dict()
    data["id"] = "he-custom"
    data["name"] = "Hebrew (custom)"
    import json

    (tmp_path / "he-custom.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    reg = LayoutRegistry.load(tmp_path, entry_points=False)
    assert "he-custom" in reg
    assert reg.get("he-custom").origin.startswith("user:")
    assert reg.get("HE-CUSTOM").id == "he-custom"


@pytest.mark.parametrize("bad", [
    {"keys": {"AD01": ["a", "A"]}},
    {"id": "x", "keys": {}},
    {"id": "x", "keys": {"AD01": ["ab", "A"]}},
    {"id": "x", "keys": {"AD01": ["a", "A", "b"]}},
    {"id": "x", "keys": {"AD01": ["a", "A"]}, "sequences": {"xy": ["ZZZZ", 0]}},
])
def test_invalid_layouts_rejected(bad):
    with pytest.raises(LayoutError):
        layout_from_dict(bad)


def test_unknown_layout_message(registry):
    with pytest.raises(KeyError, match="typoshift layouts"):
        registry.get("klingon")
