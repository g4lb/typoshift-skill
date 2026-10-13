#!/usr/bin/env python3
"""TypoShift skill helper: rebuild text typed with the wrong keyboard layout.

Self-contained (standard library only, Python 3.8+, no network). It does the
deterministic part - physical-key reconstruction between layouts - and leaves
the judgement of which reading makes sense to Claude.

    python3 typoshift.py candidates [--layouts he,en-US] < text
    python3 typoshift.py convert --from he --to en-US < text
    python3 typoshift.py layouts

Layout data (layouts.json, next to this file) is generated from the
xkeyboard-config database by the TypoShift repository's tools.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ISO_ONLY = ("LSGT", "AB11")
DEAD_TO_COMBINING = {
    "`": "̀", "´": "́", "^": "̂", "~": "̃", "¯": "̄", "˘": "̆", "˙": "̇",
    "¨": "̈", "˚": "̊", "˝": "̋", "ˇ": "̌", "¸": "̧", "˛": "̨", "ͺ": "ͅ",
}
SPACE = ("SPCE", 0)

# Never rewritten: code, URLs, e-mail, paths, flags, identifiers, hashes, secrets.
PROTECTED_SPANS = re.compile(
    r"(```|~~~)[\s\S]*?(?:\1|\Z)"
    r"|(?<![\w`])`[^`\n]+`(?![\w`])"
    r"|\b[a-zA-Z][a-zA-Z0-9+.-]{1,15}://\S+|\bwww\.\S+"
    r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
    r"|(?<![\w])[A-Za-z]:\\\S*"
)
PROTECTED_CHUNK = re.compile(
    r"^(?:~|\.{1,2})?/[A-Za-z0-9_.@-]|[A-Za-z0-9_.-]{2}/[A-Za-z0-9_.-]{2}"  # paths
    r"|^[\w.@-]*\w\.(?:py|js|jsx|ts|tsx|json|md|ya?ml|toml|sh|go|rs|java|c|h|cpp|css|html|sql|txt|lock)$"
    r"|[A-Za-z0-9]_[A-Za-z0-9]|^--?[A-Za-z]"  # snake_case, CLI flags
    r"|(?=.*[A-Za-z])(?=.*\d)^[\x21-\x7e]+$"  # letters mixed with digits (hashes, versions)
    r"|^\$\{?\w+|=>|->|::|==|&&|\|\|"
)


def load_layouts():
    with open(os.path.join(HERE, "layouts.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    layouts = {}
    for lid, data in raw.items():
        keys = {code: tuple(v) for code, v in data["keys"].items()}
        dead = {(code, int(lv)) for code, lvs in data.get("dead_keys", {}).items() for lv in lvs}
        reverse = {}
        for code, values in keys.items():
            for level, ch in enumerate(values):
                if ch:
                    reverse.setdefault(ch, []).append((code, level))
        for ch, strokes in reverse.items():
            strokes.sort(key=lambda s: (s[0] in ISO_ONLY, keys[s[0]][0] != ch.lower() if s[1] else False, s[1]))
        sequences = {seq: (s[0], int(s[1])) for seq, s in data.get("sequences", {}).items()}
        layouts[lid] = {
            "id": lid, "name": data["name"], "script": data["script"], "keys": keys, "dead": dead,
            "languages": data.get("languages", []),
            "reverse": reverse, "sequences": sequences, "seq_out": {v: k for k, v in sequences.items()},
            "dead_chars": {keys[c][lv]: (c, lv) for c, lv in dead},
        }
    return layouts


def load_common_words():
    try:
        with open(os.path.join(HERE, "common_words.json"), encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError:
        return {}
    return {lang: set(words.split()) for lang, words in raw.items() if not lang.startswith("_")}


def word_key(chunk):
    return "".join(c for c in chunk.lower() if unicodedata.category(c)[0] in "LM" or c in "'-")


def dead_stroke_for(layout, mark):
    for spacing, combining in DEAD_TO_COMBINING.items():
        if combining == mark and spacing in layout["dead_chars"]:
            return layout["dead_chars"][spacing]
    return None


def decode(text, layout):
    """Text typed on ``layout`` -> keystrokes. Characters it cannot type pass through as strings."""
    items, i = [], 0
    while i < len(text):
        seq = next((s for s in layout["sequences"] if text.startswith(s, i)), None)
        if seq:
            items.append(layout["sequences"][seq])
            i += len(seq)
            continue
        ch = text[i]
        if i + 1 < len(text) and unicodedata.combining(text[i + 1]):
            dead, base = dead_stroke_for(layout, text[i + 1]), layout["reverse"].get(ch)
            if dead and base:
                items += [dead, base[0]]
                i += 2
                continue
        strokes = layout["reverse"].get(ch)
        if strokes:
            items.append(strokes[0])
            if strokes[0] in layout["dead"]:
                items.append(SPACE)  # a standalone accent was typed as dead key + Space
        else:
            parts = unicodedata.normalize("NFD", ch)
            dead = dead_stroke_for(layout, parts[1]) if len(parts) == 2 else None
            base = layout["reverse"].get(parts[0]) if len(parts) == 2 else None
            items += [dead, base[0]] if dead and base else [ch]
        i += 1
    return items


def encode(items, layout, source):
    out, i = [], 0
    while i < len(items):
        item = items[i]
        if isinstance(item, str) or item == SPACE:
            out.append(" " if item == SPACE else item)
            i += 1
            continue
        values = layout["keys"].get(item[0])
        ch = values[item[1]] if values else None
        if not ch:
            out.append(source["keys"][item[0]][item[1]] or "")  # key missing here: keep as typed
            i += 1
            continue
        if item in layout["dead"] and i + 1 < len(items):
            nxt = items[i + 1]
            if nxt in (SPACE, " "):
                out.append(ch)
                i += 2
                continue
            nxt_ch = nxt if isinstance(nxt, str) else (layout["keys"].get(nxt[0]) or (None, None))[nxt[1]]
            if nxt_ch and ch in DEAD_TO_COMBINING:
                composed = unicodedata.normalize("NFC", nxt_ch + DEAD_TO_COMBINING[ch])
                if len(composed) == 1:
                    out.append(composed)
                    i += 2
                    continue
        out.append(layout["seq_out"].get(item) or ch)
        i += 1
    return "".join(out)


def convert(text, source, target):
    return encode(decode(text, source), target, source)


def producible(text, layout):
    for ch in text:
        if ch.isspace() or ch in layout["reverse"]:
            continue
        if unicodedata.combining(ch):
            continue
        parts = unicodedata.normalize("NFD", ch)
        if not (len(parts) == 2 and parts[0] in layout["reverse"] and dead_stroke_for(layout, parts[1])):
            if not any(ch in seq for seq in layout["sequences"]):
                return False
    return True


def letters(text):
    return [ch for ch in text if unicodedata.category(ch)[0] == "L"]


def script_of(ch):
    name = unicodedata.name(ch, "")
    for prefix in ("LATIN", "HEBREW", "CYRILLIC", "ARABIC", "GREEK"):
        if name.startswith(prefix):
            return prefix.title()
    return "Other"


def chunks(text):
    """Split into (text, protected) pieces; whitespace is kept as unprotected pieces."""
    pieces, pos = [], 0
    for m in PROTECTED_SPANS.finditer(text):
        start, end = m.start(), m.end()
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        while end < len(text) and not text[end].isspace():
            end += 1
        if start < pos:
            continue
        pieces += _split(text[pos:start]) + [(text[start:end], True)]
        pos = end
    return pieces + _split(text[pos:])


def _split(text):
    out = []
    for part in re.split(r"(\s+)", text):
        if part:
            protected = not part.isspace() and bool(
                PROTECTED_CHUNK.search(part.strip("\"'()[]{}.,;:!?")) or mixed_script(part))
            out.append((part, protected))
    return out


def mixed_script(chunk):
    """Words that mix scripts on purpose ("ה-README", "הAPI"). A single leading Latin capital is
    what Shift types on the Hebrew layout, so that alone does not count."""
    found = [(i, script_of(c)) for i, c in enumerate(chunk) if unicodedata.category(c)[0] == "L"]
    scripts = {sc for _, sc in found}
    if len(scripts) < 2:
        return False
    latin = [i for i, sc in found if sc == "Latin"]
    return not (len(scripts) == 2 and latin == [found[0][0]] and chunk[latin[0]].isupper())


def candidates(text, layouts, allowed, common=None):
    """Every distinct reconstruction of the text, one per (typed layout -> intended layout) pair.

    Words that are already common words of their own script are never converted,
    and candidates are ranked by how many converted words become common words of
    the intended layout's language.
    """
    common = common if common is not None else load_common_words()
    by_script = {}
    for lid in allowed:
        for lang in layouts[lid]["languages"]:
            by_script.setdefault(layouts[lid]["script"], set()).update(common.get(lang, ()))
    pieces = chunks(text)
    results = {}
    for src in allowed:
        source = layouts[src]
        native = by_script.get(source["script"], set())
        for dst in allowed:
            target = layouts[dst]
            if dst == src:
                continue
            vocab = set().union(*(common.get(lang, set()) for lang in target["languages"])) if common else set()
            out, changed, hits = [], 0, 0
            for piece, protected in pieces:
                if protected or piece.isspace() or not producible(piece, source) or word_key(piece) in native:
                    out.append(piece)
                    continue
                new = convert(piece, source, target)
                # Only letter changes count; punctuation-only rewrites are not corrections.
                if [c.lower() for c in letters(new)] != [c.lower() for c in letters(piece)]:
                    changed += 1
                    hits += word_key(new) in vocab
                    out.append(new)
                else:
                    out.append(piece)
            if not changed:
                continue
            result = "".join(out)
            ls = letters(result)
            share = sum(1 for c in ls if script_of(c) == target["script"]) / len(ls) if ls else 0
            entry = results.get(result)
            if entry is None:
                results[result] = {"text": result, "typed_on": src, "intended": dst, "equivalent": [],
                                   "changed_words": changed, "common_word_hits": hits,
                                   "target_script_share": round(share, 2)}
            else:
                entry["equivalent"].append(f"{src}->{dst}")
    return sorted(results.values(), key=lambda r: (-r["common_word_hits"] / r["changed_words"],
                                                   -r["common_word_hits"], -r["target_script_share"]))


DEFAULT_LAYOUTS = ["en-US", "he", "ru", "uk", "ar", "el"]


def main(argv=None):
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="typoshift.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates", help="all reconstructions of the text (stdin or args)")
    c.add_argument("text", nargs="*")
    c.add_argument("--layouts", help=f"comma-separated layout ids (default: {','.join(DEFAULT_LAYOUTS)})")
    c.add_argument("--json", action="store_true", help="machine-readable output")
    v = sub.add_parser("convert", help="convert key by key between two layouts")
    v.add_argument("text", nargs="*")
    v.add_argument("--from", dest="source", required=True)
    v.add_argument("--to", dest="target", required=True)
    sub.add_parser("layouts", help="list layout ids")
    args = ap.parse_args(argv)
    layouts = load_layouts()
    if args.cmd == "layouts":
        for lid, lay in layouts.items():
            print(f"{lid:7} {lay['script']:9} {lay['name']}")
        return 0
    text = " ".join(args.text) if args.text else sys.stdin.read().rstrip("\n")
    if args.cmd == "convert":
        for lid in (args.source, args.target):
            if lid not in layouts:
                print(f"unknown layout {lid!r}; run: typoshift.py layouts", file=sys.stderr)
                return 2
        print(convert(text, layouts[args.source], layouts[args.target]))
        return 0
    allowed = [x.strip() for x in (args.layouts or ",".join(DEFAULT_LAYOUTS)).split(",") if x.strip()]
    unknown = [lid for lid in allowed if lid not in layouts]
    if unknown:
        print(f"unknown layout(s): {', '.join(unknown)}; run: typoshift.py layouts", file=sys.stderr)
        return 2
    found = candidates(text, layouts, allowed)
    if args.json:
        print(json.dumps({"original": text, "candidates": found}, ensure_ascii=False))
        return 0
    if not found:
        print("no reconstruction changes any letters")
        return 0
    if not any(c["common_word_hits"] for c in found):
        print("note: no candidate turns any word into a common word; probably no layout mistake")
    for n, cand in enumerate(found, 1):
        same = f"  (same as {', '.join(cand['equivalent'])})" if cand["equivalent"] else ""
        hits = f"  [{cand['common_word_hits']}/{cand['changed_words']} common words]"
        print(f"{n}. {cand['typed_on']} -> {cand['intended']}: {cand['text']}{hits}{same}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
