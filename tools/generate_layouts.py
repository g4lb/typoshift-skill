#!/usr/bin/env python3
"""Generate TypoShift layout data files from xkeyboard-config symbol files.

TypoShift never hand-writes keyboard mappings. Every built-in layout is
derived from the X Keyboard Configuration Database (xkeyboard-config), the
layout database used by Linux/BSD desktops, which is vendored under
``tools/xkb/symbols`` together with its license (``tools/xkb/COPYING``).

Keysym names are resolved to Unicode with ``tools/xkb/keysymdef.h`` from
xorgproto.

Only shift levels 1 and 2 (unmodified and Shift) are extracted. AltGr levels
are intentionally ignored: they are rarely involved in wrong-layout typing and
differ widely between platforms.

Usage::

    python tools/generate_layouts.py            # regenerate data files
    python tools/generate_layouts.py --check    # verify committed data is current
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
XKB_DIR = ROOT / "tools" / "xkb"
SYMBOLS_DIR = XKB_DIR / "symbols"
OUT_DIR = ROOT / "src" / "typoshift" / "layouts" / "data"

XKB_COMMIT = "048b0ca1eb324730e425b8479ad09e404d8a1dbd"
XORGPROTO_COMMIT = "6d3907b6d5dc4aa7d7ee6ee5d7d8714e7466630b"

# Physical alphanumeric keys, named with XKB key codes, in row order.
PHYSICAL_KEYS = (
    ["TLDE"]
    + [f"AE{i:02d}" for i in range(1, 13)]
    + [f"AD{i:02d}" for i in range(1, 13)]
    + [f"AC{i:02d}" for i in range(1, 12)]
    + ["BKSL"]
    + ["LSGT"]
    + [f"AB{i:02d}" for i in range(1, 12)]
)


@dataclass(frozen=True)
class LayoutSpec:
    id: str
    name: str
    xkb_file: str
    xkb_variant: str
    languages: tuple[str, ...]
    script: str
    notes: str = ""


SPECS: list[LayoutSpec] = [
    LayoutSpec("en-US", "English (US, QWERTY)", "us", "basic", ("en",), "Latin"),
    LayoutSpec("he", "Hebrew (Standard, SI-1452)", "il", "basic", ("he",), "Hebrew",
               "Shifted letter keys produce uppercase Latin letters, as on the standard layout."),
    LayoutSpec("ru", "Russian (ЙЦУКЕН)", "ru", "winkeys", ("ru",), "Cyrillic",
               "Windows-style punctuation (the XKB default Russian variant)."),
    LayoutSpec("ar", "Arabic (Standard 101)", "ara", "basic", ("ar",), "Arabic",
               "The B key emits the lam-alef ligature; see 'sequences'."),
    LayoutSpec("fr", "French (AZERTY)", "fr", "basic", ("fr",), "Latin"),
    LayoutSpec("de", "German (QWERTZ)", "de", "basic", ("de",), "Latin"),
    LayoutSpec("es", "Spanish (QWERTY)", "es", "basic", ("es",), "Latin"),
    LayoutSpec("it", "Italian (QWERTY)", "it", "basic", ("it",), "Latin"),
    LayoutSpec("pt", "Portuguese (QWERTY)", "pt", "basic", ("pt",), "Latin"),
    LayoutSpec("pt-BR", "Portuguese (Brazil, ABNT2)", "br", "abnt2", ("pt",), "Latin"),
    LayoutSpec("uk", "Ukrainian (ЙЦУКЕН)", "ua", "unicode", ("uk",), "Cyrillic",
               "The XKB default Ukrainian variant (Windows 'Enhanced' style)."),
    LayoutSpec("el", "Greek", "gr", "basic", ("el",), "Greek"),
    LayoutSpec("tr", "Turkish Q", "tr", "basic", ("tr",), "Latin"),
    LayoutSpec("tr-F", "Turkish F", "tr", "f", ("tr",), "Latin"),
    LayoutSpec("pl", "Polish (Programmers)", "pl", "basic", ("pl",), "Latin",
               "Levels 1-2 are identical to English (US); Polish letters need AltGr."),
    LayoutSpec("cs", "Czech (QWERTZ)", "cz", "basic", ("cs",), "Latin"),
    LayoutSpec("sv", "Swedish", "se", "basic", ("sv",), "Latin"),
    LayoutSpec("no", "Norwegian", "no", "basic", ("no",), "Latin"),
    LayoutSpec("da", "Danish", "dk", "basic", ("da",), "Latin"),
    LayoutSpec("nl", "Dutch", "nl", "basic", ("nl",), "Latin"),
]

# Spacing equivalents of dead keys (what the key yields when followed by Space).
DEAD_KEYS = {
    "dead_grave": "`", "dead_acute": "´", "dead_circumflex": "^", "dead_tilde": "~",
    "dead_macron": "¯", "dead_breve": "˘", "dead_abovedot": "˙", "dead_diaeresis": "¨",
    "dead_abovering": "˚", "dead_doubleacute": "˝", "dead_caron": "ˇ", "dead_cedilla": "¸",
    "dead_ogonek": "˛", "dead_iota": "ͺ", "dead_belowdot": "̣", "dead_hook": "̉",
    "dead_horn": "̛", "dead_stroke": "/", "dead_greek": "µ",
}

# Windows emits the Arabic B key as two code points (lam + alef) rather than the
# presentation-form ligature XKB uses; both spellings are accepted on input.
LIGATURE_DECOMPOSITIONS = {
    "ﻻ": "لا",  # ﻻ LAM WITH ALEF
    "ﻵ": "لآ",  # ﻵ LAM WITH ALEF WITH MADDA ABOVE
    "ﻷ": "لأ",  # ﻷ LAM WITH ALEF WITH HAMZA ABOVE
    "ﻹ": "لإ",  # ﻹ LAM WITH ALEF WITH HAMZA BELOW
}

KEYSYM_RE = re.compile(r"#define XK_(\w+)\s+0x([0-9a-fA-F]+)\s*(?:/\*\s*\(?U\+([0-9A-Fa-f]{4,6}))?")
BLOCK_RE = re.compile(
    r'((?:default\s+)?(?:hidden\s+)?(?:partial\s+)?(?:[\w_]+\s+)*)xkb_symbols\s+"([^"]+)"\s*\{', re.S
)
KEY_RE = re.compile(r"\b(replace\s+|override\s+|augment\s+)?key\s*<(\w+)>\s*\{(.*?)\}\s*;", re.S)
INCLUDE_RE = re.compile(r'\b(include|augment|override|replace)\s+"([^"]+)"')


def load_keysyms() -> dict[str, str]:
    table: dict[str, str] = {}
    for line in (XKB_DIR / "keysymdef.h").read_text(encoding="utf-8").splitlines():
        m = KEYSYM_RE.match(line)
        if not m:
            continue
        name, value, uni = m.group(1), int(m.group(2), 16), m.group(3)
        if uni:
            table[name] = chr(int(uni, 16))
        elif 0x20 <= value <= 0x7E or 0xA0 <= value <= 0xFF:
            table[name] = chr(value)  # Latin-1 keysyms equal their code points
    return table


KEYSYMS = load_keysyms()


def keysym_to_char(sym: str) -> tuple[str | None, bool]:
    """Return (character, is_dead) for an XKB keysym name."""
    sym = sym.strip()
    if sym in ("", "NoSymbol", "VoidSymbol", "any", "none"):
        return None, False
    if sym in DEAD_KEYS:
        return DEAD_KEYS[sym], True
    if re.fullmatch(r"U[0-9A-Fa-f]{4,6}", sym):
        return chr(int(sym[1:], 16)), False
    if re.fullmatch(r"0x[0-9A-Fa-f]+", sym):
        value = int(sym, 16)
        if value >= 0x01000000:
            return chr(value - 0x01000000), False
        return (chr(value), False) if value < 0x100 else (None, False)
    if sym in KEYSYMS:
        return KEYSYMS[sym], False
    if len(sym) == 1:
        return sym, False
    raise KeyError(f"unknown keysym {sym!r}")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def split_blocks(text: str) -> tuple[dict[str, str], str | None]:
    """Return {variant: body} for a symbols file plus the default variant."""
    blocks: dict[str, str] = {}
    default = None
    for m in BLOCK_RE.finditer(text):
        flags, name = m.group(1), m.group(2)
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        blocks[name] = text[m.end(): i - 1]
        if default is None and "default" in flags.split():
            default = name
    if default is None and blocks:
        default = next(iter(blocks))
    return blocks, default


_FILE_CACHE: dict[str, tuple[dict[str, str], str | None]] = {}
MISSING_INCLUDES: set[str] = set()


def resolve(file: str, variant: str | None, keys: dict[str, list], depth: int = 0) -> None:
    if depth > 16:
        raise RecursionError(f"include depth exceeded at {file}({variant})")
    path = SYMBOLS_DIR / file
    if not path.exists():
        MISSING_INCLUDES.add(file)
        return
    if file not in _FILE_CACHE:
        _FILE_CACHE[file] = split_blocks(strip_comments(path.read_text(encoding="utf-8")))
    blocks, default = _FILE_CACHE[file]
    name = variant or default
    if name not in blocks:
        raise KeyError(f"{file}({name}) not found")
    body = blocks[name]
    # Process includes and key statements in document order.
    events = [(m.start(), "inc", m) for m in INCLUDE_RE.finditer(body)]
    events += [(m.start(), "key", m) for m in KEY_RE.finditer(body)]
    for _, kind, m in sorted(events, key=lambda e: e[0]):
        if kind == "inc":
            for part in re.split(r"[+|]", m.group(2)):
                pm = re.fullmatch(r"([\w/]+)(?:\(([\w-]+)\))?(?::\d+)?", part.strip())
                if pm:
                    resolve(pm.group(1), pm.group(2), keys, depth + 1)
            continue
        mode, code, content = (m.group(1) or "").strip(), m.group(2), m.group(3)
        if code not in PHYSICAL_KEYS:
            continue
        content = re.sub(r"\b(?:type|actions|vmods)\s*\[\s*\w+\s*\]\s*=\s*(\"[^\"]*\"|\[[^\]]*\])", "", content)
        sm = re.search(r"symbols\[\s*group1\s*\]\s*=\s*\[(.*?)\]", content, re.S | re.I) or re.search(
            r"\[(.*?)\]", content, re.S
        )
        if not sm:
            continue
        syms = [s.strip() for s in sm.group(1).split(",")][:2]
        levels = [keysym_to_char(s) for s in syms]
        while len(levels) < 2:
            levels.append((None, False))
        while len(syms) < 2:
            syms.append("NoSymbol")
        existing = keys.get(code)
        if existing:
            # 'any'/'NoSymbol' leave the inherited level untouched; augment never overrides.
            levels = [
                existing[i] if syms[i] in ("any", "NoSymbol") or (mode == "augment" and existing[i][0]) else levels[i]
                for i in range(2)
            ]
        keys[code] = levels


def build(spec: LayoutSpec) -> dict:
    raw: dict[str, list] = {}
    resolve(spec.xkb_file, spec.xkb_variant, raw)
    keys: dict[str, list] = {}
    dead: dict[str, list[str]] = {}
    sequences: dict[str, list] = {}
    for code in PHYSICAL_KEYS:
        if code not in raw:
            continue
        values = []
        for level, (char, is_dead) in enumerate(raw[code]):
            values.append(char)
            if is_dead:
                dead.setdefault(code, []).append(str(level))
            if char in LIGATURE_DECOMPOSITIONS:
                sequences[LIGATURE_DECOMPOSITIONS[char]] = [code, level]
        if values[1] is None and values[0] is not None and values[0].upper() != values[0]:
            values[1] = values[0].upper()  # one-level alphabetic key: Shift gives uppercase
        if any(values):
            keys[code] = values
    data = {
        "id": spec.id,
        "name": spec.name,
        "languages": list(spec.languages),
        "script": spec.script,
        "source": {
            "database": "xkeyboard-config",
            "commit": XKB_COMMIT,
            "symbols": f"{spec.xkb_file}({spec.xkb_variant})",
            "keysyms": f"xorgproto {XORGPROTO_COMMIT} include/X11/keysymdef.h",
        },
        "levels": ["base", "shift"],
        "keys": keys,
    }
    if dead:
        data["dead_keys"] = dead
    if sequences:
        data["sequences"] = sequences
    if spec.notes:
        data["notes"] = spec.notes
    return data


def render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if generated data differs")
    args = parser.parse_args()
    stale = []
    for spec in SPECS:
        text = render(build(spec))
        out = OUT_DIR / f"{spec.id}.json"
        if args.check:
            if not out.exists() or out.read_text(encoding="utf-8") != text:
                stale.append(out.name)
        else:
            out.write_text(text, encoding="utf-8")
    if MISSING_INCLUDES:
        print("note: ignored includes without alphanumeric levels 1-2:", ", ".join(sorted(MISSING_INCLUDES)),
              file=sys.stderr)
    if stale:
        print("stale layout data:", ", ".join(stale), file=sys.stderr)
        return 1
    print(f"{'checked' if args.check else 'generated'} {len(SPECS)} layouts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
