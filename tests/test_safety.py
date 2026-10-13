"""False-positive prevention: correctly typed and technical text must never change."""

from __future__ import annotations

import pytest
from conftest import ROOT

from typoshift.protection import RULES, Protector
from typoshift.tokenizer import PROTECTED, tokenize

GARBLE = "ghbdtn"  # "привет" typed on a US layout: corrected when it is plain text


def lines(name: str) -> list[str]:
    path = ROOT / "benchmarks" / "corpus" / "negatives" / f"{name}.txt"
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_garble_is_corrected_as_plain_text(engine):
    assert engine.fix(f"say {GARBLE} to them").corrected != f"say {GARBLE} to them"


@pytest.mark.parametrize("text", [
    "Please update src/components/Header.tsx",
    f"Can you fix the bug in ```\n{GARBLE}\n``` please",
    f"```python\nprint('{GARBLE}')\n```",
    f"see `{GARBLE}` here",
    f"go to https://example.com/{GARBLE} now",
    f"open www.{GARBLE}.com",
    f"mail {GARBLE}@example.com",
    f"edit ./{GARBLE}/config.yaml",
    f"edit ~/{GARBLE}",
    f"C:\\Users\\{GARBLE}\\app.py",
    f"export {GARBLE.upper()}_KEY=1",
    f"echo ${GARBLE}",
    "commit a1b2c3d4e5f6 broke it",
    "use sk-test-abcdefghijklmnop1234 as the key",
    "token ghp_exampleexampleexample0000",
    '{"name": "ghbdtn", "rfr": 1}',
    "name: ghbdtn\nrfr: ltkf",
    "$ ghbdtn --rfr ltkf",
    "git push --force origin main",
    "rm -rf node_modules",
    "npm i",
    "ls -la",
    "cd ..",
    "the ghbdtn_rfr variable",
    "call getUserName() please",
    "rename useState to useReducer",
    "bump to v2.3.1",
    "fix #123 for @ghbdtn",
    "the API, JWT and CORS settings",
    "use ghbdtn.rfr.ltkf module",
    "deploy to example.io",
    "a <div> element",
])
def test_technical_strings_unchanged(engine, text):
    assert engine.fix(text).corrected == text


@pytest.mark.parametrize("name", ["technical", "multilingual", "short_ambiguous"])
def test_negative_corpus_unchanged(engine, name):
    changed = [t for t in lines(name) if engine.fix(t).corrected != t]
    # The full corpus is evaluated by the benchmark; here every line must survive.
    assert changed == []


def test_short_ambiguous_inputs_untouched(engine):
    for text in ("ok", "lgtm", "y", "n", "q", "wip", "כן", "לא", "да", "нет", "?", "..."):
        assert engine.fix(text).corrected == text


def test_destructive_reconstruction_requires_confirmation(engine):
    result = engine.fix("פךקשדק גקךקאק איק ךםע כןךקד")  # "please delete the log files"
    assert result.corrected == "please delete the log files"
    assert result.requires_confirmation


def test_non_destructive_does_not_require_confirmation(engine):
    assert not engine.fix("פךקשדק גקהקךםפ איק מקסא כקשאורק").requires_confirmation


def test_custom_protected_pattern(make_engine):
    eng = make_engine("en-US", "ru", protection={"extra_patterns": [r"ghbdtn\w*"], "disabled_rules": []})
    assert eng.fix("ghbdtn rfr ltkf").corrected.startswith("ghbdtn ")


def test_disabled_rule(make_engine):
    eng = make_engine("en-US", "ru", protection={"disabled_rules": ["inline_code"], "extra_patterns": []})
    assert eng.fix("`ghbdtn rfr ltkf`").corrected != "`ghbdtn rfr ltkf`"


def test_unknown_rule_rejected():
    with pytest.raises(ValueError):
        Protector(disabled=["nope"])


def test_rules_are_listed():
    assert {"url", "email", "code_fence", "inline_code", "path", "secret", "identifier"} <= set(RULES)


def test_tokenizer_roundtrip():
    text = "a  `b c`\n https://x.io/y?z=1 ,d\te"
    tokens = tokenize(text, Protector())
    assert "".join(t.text for t in tokens) == text
    assert any(t.kind == PROTECTED and t.rule == "url" for t in tokens)


def test_arabic_garble_not_mistaken_for_code():
    p = Protector()
    # ذ is on the backtick key, ظ on slash, ج/د on the bracket keys.
    assert not p.find_spans("i`h fi`h")
    assert p.check_chunk("d/iv") is None
    assert p.check_chunk("hg[]d]") is None
    assert p.check_chunk("fHkd") is None
    assert p.check_chunk("getUserName") == "identifier"


def test_protected_span_inside_chunk_protects_whole_chunk(engine, make_engine):
    assert engine.fix("ghbdtn$rfr ltkf ckjdj").corrected.startswith("ghbdtn$rfr ")
    eng = make_engine("en-US", "ru", protection={"extra_patterns": ["b"], "disabled_rules": []})
    out = eng.fix("ghbdtn rfr ltkf").corrected
    assert out.startswith("ghbdtn ") or "ghb" not in out


def test_confirm_destructive_can_be_disabled(make_engine):
    eng = make_engine("en-US", "he", confirm_destructive=False)
    assert not eng.fix("פךקשדק גקךקאק איק ךםע כןךקד").requires_confirmation
