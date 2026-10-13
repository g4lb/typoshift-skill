"""Protected-pattern rules.

Anything matched here is never rewritten, whatever the language models say.
Rules run in two passes:

* **span rules** find regions in the full text (code fences, inline code, URLs,
  e-mail addresses, Windows paths, environment variables, JSON documents,
  YAML blocks, shell command lines);
* **chunk rules** inspect each whitespace-delimited chunk outside those regions
  (paths, file names, identifiers, operators, hashes, secrets, flags,
  acronyms, domains, mixed-script words).

Rules are conservative on purpose: a missed correction costs the user one
retype, a wrong correction can silently change an instruction.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

from .scripts import LATIN, char_script, is_letter

__all__ = ["Protector", "Span", "RULES"]


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    rule: str


_EXTENSIONS = (
    "py|pyi|pyc|js|jsx|ts|tsx|mjs|cjs|json|jsonc|md|mdx|rst|txt|yaml|yml|toml|ini|cfg|conf|env|sh|bash|zsh|"
    "fish|ps1|bat|cmd|go|mod|sum|rs|java|kt|kts|swift|m|mm|c|h|cc|cpp|cxx|hpp|cs|fs|rb|php|html|htm|css|scss|"
    "sass|less|vue|svelte|astro|sql|lock|xml|svg|png|jpe?g|gif|webp|ico|pdf|csv|tsv|log|gradle|tf|tfvars|hcl|"
    "proto|graphql|gql|ipynb|r|scala|dart|lua|pl|pm|ex|exs|erl|hs|ml|clj|zig|nim|wasm|zip|tar|gz|tgz|bz2|xz|"
    "dll|so|dylib|exe|bin|whl|jar|war|map|snap|patch|diff|bak|tmp|plist|dockerfile|makefile"
)
_TLDS = (
    "com|org|net|io|dev|ai|app|co|il|ru|ua|de|fr|uk|us|gov|edu|me|sh|xyz|info|biz|cloud|tech|so|gg|tv|ly|to|in|"
    "eu|es|it|nl|se|no|dk|pl|cz|gr|tr|br|pt|ca|au|jp|cn|ch|at|be|fi|ie|nz|site|online|page|run|local|internal|test"
)
_DOTFILES = (
    "gitignore|gitattributes|gitmodules|env|npmrc|nvmrc|yarnrc|bashrc|zshrc|profile|bash_profile|vimrc|"
    "editorconfig|prettierrc|prettierignore|eslintrc|eslintignore|dockerignore|github|gitlab-ci\\.yml|vscode|"
    "idea|claude|cursor|venv|python-version|tool-versions|babelrc|stylelintrc|browserslistrc|husky"
)
_COMMANDS = (
    "git|gh|npm|npx|yarn|pnpm|bun|deno|pip|pip3|pipx|uv|poetry|python|python3|py|node|docker|docker-compose|"
    "kubectl|helm|terraform|aws|gcloud|az|cd|ls|ll|rm|mv|cp|mkdir|rmdir|cat|less|head|tail|grep|rg|find|fd|"
    "curl|wget|ssh|scp|rsync|sudo|brew|apt|apt-get|yum|dnf|pacman|make|cmake|cargo|rustc|go|java|javac|mvn|"
    "gradle|dotnet|chmod|chown|export|echo|touch|vim|vi|nvim|nano|code|open|tar|unzip|zip|jq|sed|awk|xargs|"
    "kill|pkill|ps|top|htop|df|du|which|whereis|source|systemctl|journalctl|tmux|screen|ln|env|set|unset|"
    "pytest|tox|ruff|black|mypy|eslint|prettier|tsc|vite|next|jest|vitest|psql|mysql|redis-cli|mongo|sqlite3|"
    "ffmpeg|openssl|ping|dig|nslookup|traceroute|netstat|lsof|history|alias|claude|typoshift"
)

_SPAN_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("code_fence", re.compile(r"(?s)(```|~~~).*?(?:\1|\Z)")),
    # Backticks must sit at word boundaries: Arabic typed on a US layout puts
    # the letter ذ on the backtick key, inside words.
    ("inline_code", re.compile(r"(?<![\w`])`[^`\n]+`(?![\w`])")),
    ("url", re.compile(r"\b(?:[a-zA-Z][a-zA-Z0-9+.-]{1,15})://[^\s<>\"'`]+|\bwww\.[^\s<>\"'`]+")),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
    ("windows_path", re.compile(r"(?<![\w])[A-Za-z]:\\[^\s\"'<>|]*")),
    ("env_var", re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|%[A-Za-z_][A-Za-z0-9_]*%")),
    ("shell_prompt", re.compile(r"(?m)^[ \t]*\$ [^\n]*$")),
    # ASCII lines with a call and a brace, semicolon or assignment are code.
    ("code_line", re.compile(r"(?m)^(?=[\x20-\x7e]*\w\([\x20-\x7e]*\))(?=[\x20-\x7e]*[{};=])[\x20-\x7e]+$")),
    ("shell_command", re.compile(rf"(?m)^[ \t]*(?:{_COMMANDS})(?:[ \t]+[\x21-\x7e]+)+[ \t]*$")),
    ("yaml_block", re.compile(r"(?m)(?:^[ \t]*-?[ \t]*[A-Za-z_][\w.-]*:(?:[ \t]+[^\n]*)?\n){1,}"
                              r"^[ \t]*-?[ \t]*[A-Za-z_][\w.-]*:(?:[ \t]+[^\n]*)?$")),
]

_CHUNK_RULES: list[tuple[str, re.Pattern[str]]] = [
    # Inner slashes need two path characters on each side: Arabic typed on a US
    # layout puts the letter ظ on the slash key ("d/iv").
    ("path", re.compile(r"^(?:~|\.{1,2})?/[A-Za-z0-9_.@-]|[A-Za-z0-9_.-]{2}/[A-Za-z0-9_.-]{2}|"
                        r"[A-Za-z0-9_.-]\\[A-Za-z0-9_.-]")),
    ("filename", re.compile(rf"^[A-Za-z0-9_.@-]*[A-Za-z0-9_-]\.(?:{_EXTENSIONS})$", re.I)),
    ("filename", re.compile(r"^(?:Dockerfile|Makefile|Procfile|Gemfile|Rakefile|Jenkinsfile|Vagrantfile|"
                            r"README|LICENSE|CHANGELOG|CONTRIBUTING|CODEOWNERS)(?:\.\w+)?$")),
    ("dotfile", re.compile(rf"^\.(?:{_DOTFILES})$|^\.[a-z]+rc$")),
    ("identifier", re.compile(r"[A-Za-z0-9]_[A-Za-z0-9]|^__?[A-Za-z]")),
    # "[]" / "{}" only at a word end: Arabic letters ج and د sit on the bracket keys.
    ("code_operator", re.compile(r"=>|->|::|==|!=|&&|\|\||\+=|-=|\*=|</|/>|\(\)|\[\](?![A-Za-z])|"
                                 r"\{\}(?![A-Za-z])|"
                                 r"^[A-Za-z_][\w.]*\(|^#!|^</?[A-Za-z][^>]*>")),
    ("alnum_mix", re.compile(r"(?=.*[A-Za-z])(?=.*[0-9])^[\x21-\x7e]+$")),
    ("hex_hash", re.compile(r"^[0-9a-fA-F]{7,64}$")),
    ("version", re.compile(r"^[vV]?\d+(?:\.\d+)+(?:[-+][\w.]+)?$")),
    ("cli_flag", re.compile(r"^--?[A-Za-z][\w-]*(?:=.*)?$")),
    ("mention", re.compile(r"^@[\w/-]+$|^#\d+$")),
    ("secret", re.compile(r"^(?:sk|pk|rk)[-_](?:live|test|proj|ant)?[-_]?[\w-]{8,}|^gh[pousr]_[\w]{10,}|"
                          r"^xox[abprs]-[\w-]+|^AKIA[0-9A-Z]{12,}|^AIza[\w-]{20,}|^eyJ[\w-]+\.[\w-]+|"
                          r"^glpat-[\w-]{10,}|^npm_[\w]{20,}")),
    ("acronym", re.compile(r"^[A-Z]{2,6}s?$")),
    ("domain", re.compile(rf"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:{_TLDS})$", re.I)),
    ("dotted_identifier", re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){2,}$")),
]

RULES: tuple[str, ...] = tuple(dict.fromkeys(
    [name for name, _ in _SPAN_RULES] + ["json"] + [name for name, _ in _CHUNK_RULES]
    + ["symbols", "high_entropy", "mixed_script", "custom"]
))

_EDGE_PUNCT = "\"'“”‘’«»()[]{}<>.,;:!?"


def _symbol_heavy(chunk: str) -> bool:
    """Regexes, operators and other strings that are mostly not letters."""
    if len(chunk) < 6:
        return False
    letters = sum(1 for ch in chunk if is_letter(ch))
    return letters < 0.4 * len(chunk)


def _high_entropy(chunk: str) -> bool:
    if len(chunk) < 24 or not chunk.isascii() or any(c.isspace() for c in chunk):
        return False
    classes = sum((any(c.islower() for c in chunk), any(c.isupper() for c in chunk),
                   any(c.isdigit() for c in chunk)))
    return classes >= 3 or (classes == 2 and len(set(chunk)) >= 16)


_CAMEL = re.compile(r"[a-z][A-Z]|^[A-Z][a-z]+[A-Z]")
_CAMEL_PARTS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")


def _camel_case(core: str) -> bool:
    """camelCase / PascalCase identifiers made of English sub-words.

    Shifted keys on some layouts produce look-alikes (Arabic typed on a US
    layout gives strings such as ``fHkd``), so mixed case alone is not enough:
    at least half of the humps must be English words.
    """
    if not core.isascii() or not _CAMEL.search(core):
        return False
    parts = [p.lower() for p in _CAMEL_PARTS.findall(core)]
    if len(parts) < 2:
        return False
    from .langmodel import load_language  # local import: only needed for camelCase chunks

    english = load_language("en")
    words = [p for p in parts if len(p) >= 2]
    known = sum(1 for p in words if english.is_known(p))
    return bool(words) and known * 2 >= len(words)


def _mixed_script(chunk: str) -> bool:
    letters = [(i, ch) for i, ch in enumerate(chunk) if is_letter(ch)]
    scripts = {char_script(ch) for _, ch in letters}
    if len(scripts) < 2:
        return False
    if len(scripts) == 2 and LATIN in scripts:
        latin = [(i, ch) for i, ch in letters if char_script(ch) == LATIN]
        # A single leading capital is what Shift produces on layouts whose
        # shifted letters are Latin (e.g. "Hקךךם" = "Hello" typed on Hebrew).
        if len(latin) == 1 and latin[0][0] == letters[0][0] and latin[0][1].isupper():
            return False
    return True


class Protector:
    """Applies protection rules. ``disabled`` rule names are skipped."""

    def __init__(self, extra_patterns: Iterable[str] = (), disabled: Iterable[str] = ()):
        self.disabled = set(disabled)
        unknown = self.disabled - set(RULES)
        if unknown:
            raise ValueError(f"unknown protection rule(s): {', '.join(sorted(unknown))}")
        self.custom = [re.compile(p) for p in extra_patterns]

    def find_spans(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for name, pattern in _SPAN_RULES:
            if name in self.disabled:
                continue
            for m in pattern.finditer(text):
                end = m.end()
                if name in ("url", "email"):
                    while end > m.start() and text[end - 1] in ".,;:!?)]}'\"":
                        end -= 1
                spans.append(Span(m.start(), end, name))
        if "json" not in self.disabled:
            spans.extend(self._json_spans(text))
        if "custom" not in self.disabled:
            for pattern in self.custom:
                spans.extend(Span(m.start(), m.end(), "custom") for m in pattern.finditer(text) if m.end() > m.start())
        return _merge(spans)

    @staticmethod
    def _json_spans(text: str) -> list[Span]:
        spans = []
        stripped = text.strip()
        if stripped[:1] in "{[" and stripped[-1:] in "}]":
            try:
                json.loads(stripped)
                start = text.index(stripped[0])
                return [Span(start, start + len(stripped), "json")]
            except ValueError:
                pass
        for m in re.finditer(r"(?m)^[ \t]*([{\[].*[}\]])[ \t]*$", text):
            try:
                json.loads(m.group(1))
            except ValueError:
                continue
            spans.append(Span(m.start(1), m.end(1), "json"))
        return spans

    def check_chunk(self, chunk: str) -> str | None:
        """Return the name of the rule protecting ``chunk``, or None."""
        core = chunk.strip(_EDGE_PUNCT) or chunk
        for name, pattern in _CHUNK_RULES:
            if name in self.disabled:
                continue
            target = chunk if name in ("code_operator", "path") else core
            if pattern.search(target):
                return name
        if "identifier" not in self.disabled and _camel_case(core):
            return "identifier"
        if "symbols" not in self.disabled and _symbol_heavy(chunk):
            return "symbols"
        if "high_entropy" not in self.disabled and _high_entropy(core):
            return "high_entropy"
        if "mixed_script" not in self.disabled and _mixed_script(chunk):
            return "mixed_script"
        if "custom" not in self.disabled:
            for pattern in self.custom:
                if pattern.fullmatch(core):
                    return "custom"
        return None


def _merge(spans: list[Span]) -> list[Span]:
    merged: list[Span] = []
    for span in sorted(spans, key=lambda s: (s.start, -s.end)):
        if merged and span.start < merged[-1].end:
            last = merged[-1]
            if span.end > last.end:
                merged[-1] = Span(last.start, span.end, last.rule)
            continue
        merged.append(span)
    return merged
