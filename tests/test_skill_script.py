"""The self-contained skill script (skills/typoshift/scripts/typoshift.py)."""

from __future__ import annotations

import ast
import json
import subprocess
import sys

import pytest
from conftest import ROOT

from typoshift.conversion import convert_text
from typoshift.layouts import builtin_registry

SKILL = ROOT / "skills" / "typoshift"
SCRIPT = SKILL / "scripts" / "typoshift.py"
REG = builtin_registry()


def run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True,
                          encoding="utf-8")


def candidates(text: str, layouts: str = "en-US,he,ru,uk,ar,el") -> list[dict]:
    proc = run("candidates", "--json", "--layouts", layouts, stdin=text)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["candidates"]


def test_python38_compatible_syntax():
    ast.parse(SCRIPT.read_text(encoding="utf-8"), feature_version=(3, 8))


def test_stdlib_only():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                 and node.module}
    assert imported <= {"__future__", "argparse", "json", "os", "re", "sys", "unicodedata"}


def test_skill_is_small():
    size = sum(p.stat().st_size for p in SKILL.rglob("*") if p.is_file())
    assert size < 150_000


@pytest.mark.parametrize("src,dst", [(a, b) for a in sorted(REG.ids()) for b in ("en-US", "he", "ru", "el")
                                     if a != b])
def test_conversion_matches_engine(src, dst):
    import importlib.util

    spec = importlib.util.spec_from_file_location("skill_typoshift", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    layouts = mod.load_layouts()
    lay = REG.get(src)
    text = "".join(v[0] for k, v in lay.keys.items() if v[0] and not lay.is_dead((k, 0))) + " " + \
        "".join(v[1] for k, v in lay.keys.items() if v[1] and not lay.is_dead((k, 1)))
    assert mod.convert(text, layouts[src], layouts[dst]) == convert_text(text, lay, REG.get(dst)).text


@pytest.mark.parametrize("typed,expected", [
    ("פךקשדק גקהקךםפ איק מקסא כקשאורק", "please develop the next feature"),
    ("please implement the login פשעק", "please implement the login page"),
    ("ghbdtn rfr ltkf&", "привет как дела?"),
    ("Руддщ цщкдв", "Hello world"),
    ("akuo", "שלום"),
])
def test_best_candidate(typed, expected):
    assert candidates(typed)[0]["text"] == expected


def test_protected_strings_untouched():
    for cand in candidates("Please update src/components/Header.tsx and https://example.com/ghbdtn"):
        assert "src/components/Header.tsx" in cand["text"] and "https://example.com/ghbdtn" in cand["text"]


def test_common_words_stay():
    assert all(c["text"].startswith("please implement the login") for c in candidates(
        "please implement the login פשעק")[:1])


def test_text_output_and_convert():
    proc = run("candidates", stdin="ghbdtn rfr ltkf&\n")
    assert proc.stdout.splitlines()[0].startswith("1. en-US -> ru: привет как дела?")
    assert run("convert", "--from", "he", "--to", "en-US", stdin="פךקשדק").stdout.strip() == "please"
    assert run("convert", "--from", "xx", "--to", "he", "a").returncode == 2
    assert "he " in run("layouts").stdout


def test_no_mistake():
    assert run("candidates", "--layouts", "en-US,he", stdin="src/app.py").stdout.strip() == \
        "no reconstruction changes any letters"
