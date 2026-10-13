"""Best-effort detection of the keyboard layouts enabled in the operating system.

Used by ``typoshift doctor`` and ``typoshift config init --detect`` so that the
engine only considers layouts the user can actually switch between (fewer
layouts means fewer ambiguous candidates). Detection never runs on the hook
path and failures simply return an empty list.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys

__all__ = ["detect_system_layouts", "parse_macos", "parse_linux_gsettings", "parse_setxkbmap", "parse_windows"]

# macOS "KeyboardLayout Name" values -> TypoShift ids.
_MACOS = {
    "U.S.": "en-US", "ABC": "en-US", "US Extended": "en-US", "British": "en-US", "Hebrew": "he", "Hebrew-PC": "he",
    "Russian": "ru", "Russian - PC": "ru", "RussianWin": "ru", "Arabic": "ar", "Arabic-PC": "ar", "French": "fr",
    "French - PC": "fr", "German": "de", "Spanish": "es", "Spanish - ISO": "es", "Italian": "it",
    "Italian - Pro": "it", "Portuguese": "pt", "Brazilian": "pt-BR", "Brazilian - ABNT2": "pt-BR",
    "Ukrainian": "uk", "Ukrainian-PC": "uk", "Greek": "el", "Turkish-QWERTY": "tr", "Turkish-QWERTY-PC": "tr",
    "Turkish": "tr-F", "Polish Pro": "pl", "Polish": "pl", "Czech": "cs", "Czech-QWERTY": "cs", "Swedish": "sv",
    "Swedish - Pro": "sv", "Norwegian": "no", "Danish": "da", "Dutch": "nl",
}
# XKB layout codes -> TypoShift ids.
_XKB = {
    "us": "en-US", "il": "he", "ru": "ru", "ara": "ar", "fr": "fr", "de": "de", "es": "es", "it": "it",
    "pt": "pt", "br": "pt-BR", "ua": "uk", "gr": "el", "tr": "tr", "pl": "pl", "cz": "cs", "se": "sv",
    "no": "no", "dk": "da", "nl": "nl",
}
# Windows keyboard layout identifiers (KLID) -> TypoShift ids.
_KLID = {
    "00000409": "en-US", "0000040d": "he", "0002040d": "he", "00000419": "ru", "00000401": "ar",
    "0000040c": "fr", "00000407": "de", "0000040a": "es", "00000410": "it", "00000816": "pt",
    "00000416": "pt-BR", "00010416": "pt-BR", "00000422": "uk", "00020422": "uk", "00000408": "el",
    "0000041f": "tr", "0001041f": "tr-F", "00000415": "pl", "00000405": "cs", "0000041d": "sv",
    "00000414": "no", "00000406": "da", "00000413": "nl",
}


def _unique(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in ids if i))


def parse_macos(output: str) -> list[str]:
    names = re.findall(r'"KeyboardLayout Name"\s*=\s*"?([^";\n]+?)"?;', output)
    return _unique([_MACOS.get(n.strip(), "") for n in names])


def parse_linux_gsettings(output: str) -> list[str]:
    try:
        sources = ast.literal_eval(output.strip().removeprefix("@a(ss) "))
    except (ValueError, SyntaxError):
        return []
    return _unique([_XKB.get(code.split("+")[0], "") for kind, code in sources if kind == "xkb"])


def parse_setxkbmap(output: str) -> list[str]:
    m = re.search(r"^layout:\s*(\S+)", output, re.M)
    return _unique([_XKB.get(code, "") for code in m.group(1).split(",")]) if m else []


def parse_windows(output: str) -> list[str]:
    tips = re.findall(r"[0-9A-Fa-f]{4}:([0-9A-Fa-f]{8})", output)
    return _unique([_KLID.get(t.lower(), "") for t in tips])


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def detect_system_layouts() -> list[str]:
    """Return supported layout ids enabled in the OS, in OS order (may be empty)."""
    if sys.platform == "darwin":
        return parse_macos(_run(["defaults", "read", "com.apple.HIToolbox", "AppleEnabledInputSources"]))
    if sys.platform == "win32":
        return parse_windows(_run(["powershell", "-NoProfile", "-Command",
                                   "(Get-WinUserLanguageList).InputMethodTips"]))
    found: list[str] = []
    if shutil.which("gsettings"):
        found = parse_linux_gsettings(_run(["gsettings", "get", "org.gnome.desktop.input-sources", "sources"]))
    if not found and shutil.which("setxkbmap"):
        found = parse_setxkbmap(_run(["setxkbmap", "-query"]))
    return found
