# TypoShift

**Type in the wrong language. Get the right words.**

[![CI](https://github.com/galb/typoshift/actions/workflows/ci.yml/badge.svg)](https://github.com/galb/typoshift/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

TypoShift detects text typed with the wrong keyboard layout and rebuilds what you meant to type. It
ships as a Python library, a CLI and a Claude Code integration (a skill plus an automatic
`UserPromptSubmit` hook). It runs fully offline, has no runtime dependencies, and never sends your
text anywhere.

```text
$ typoshift fix "פךקשדק גקהקךםפ איק מקסא כקשאורק"
please develop the next feature
```

You meant to type English, but the keyboard was on Hebrew. TypoShift finds the physical key behind
each character (`פ` is on the `P` key, `ך` on `L`, ...) and reads those keys in the layout you
intended.

## Contents

- [Why](#why)
- [What it is (and is not)](#what-it-is-and-is-not)
- [Before and after](#before-and-after)
- [Supported layouts](#supported-layouts)
- [Installation](#installation)
- [Claude Code integration](#claude-code-integration)
- [CLI usage](#cli-usage)
- [Python API](#python-api)
- [Configuration](#configuration)
- [How it works](#how-it-works)
- [Accuracy and performance](#accuracy-and-performance)
- [Safety](#safety)
- [Limitations](#limitations)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

## Why

Anyone who uses two keyboard layouts makes this mistake many times a day. You start typing, look up,
and see `ghbdtn` instead of `привет`, or `פךקשדק` instead of `please`. With an AI coding agent the
mistake costs more: the agent either fails to understand the prompt or acts on a confused reading of
it. TypoShift fixes the prompt before the agent sees it, and does nothing when nothing is wrong.

## What it is (and is not)

| Technique | What it does | Example | TypoShift? |
| --- | --- | --- | --- |
| **Keyboard-layout reconstruction** | Recovers the physical keys pressed and reads them in another layout | `ghbdtn` → `привет` | **Yes** |
| Spell checking | Fixes misspelled words in the right alphabet | `teh` → `the` | No |
| Transliteration | Writes a word's sound in another script | `privet` → `привет` | No |
| Translation | Changes the language and keeps the meaning | `hello` → `привет` | No |

TypoShift never translates or paraphrases. A correction is always a key-for-key replay, so it can
only produce what you would have typed on the other layout.

## Before and after

All examples below are real output of `typoshift fix` with the default configuration.

| You typed | Keyboard was on | TypoShift output |
| --- | --- | --- |
| `פךקשדק גקהקךםפ איק מקסא כקשאורק` | Hebrew | `please develop the next feature` |
| `please implement the login פשעק` | Hebrew (last word only) | `please implement the login page` |
| `ghbdtn rfr ltkf&` | English (meant Russian) | `привет как дела?` |
| `Руддщ цщкдв` | Russian (meant English) | `Hello world` |
| `תעדכן את ה-README ואז ghbdtn` | mixed | `תעדכן את ה-README ואז привет` |
| `Please update src/components/Header.tsx` | correct | unchanged |
| `תעדכן את ה-README ותריץ את הטסטים` | correct (intentionally mixed) | unchanged |

Notice `ltkf&` → `дела?`. On the Russian layout `?` is Shift+7, the key that types `&` in English.
This is physical reconstruction, not guessing.

## Supported layouts

20 layouts are built in. Every mapping is **generated** from the
[xkeyboard-config](https://gitlab.freedesktop.org/xkeyboard-config/xkeyboard-config) database, never
typed by hand, and every layout is covered by tests. The full key tables are in
[docs/LAYOUTS.md](docs/LAYOUTS.md).

| Id | Layout | Script | Default |
| --- | --- | --- | :---: |
| `en-US` | English (US, QWERTY) | Latin | ✓ |
| `he` | Hebrew (Standard, SI-1452) | Hebrew | ✓ |
| `ru` | Russian (ЙЦУКЕН, Windows-style) | Cyrillic | ✓ |
| `uk` | Ukrainian (ЙЦУКЕН) | Cyrillic | ✓ |
| `ar` | Arabic (Standard 101) | Arabic | ✓ |
| `el` | Greek | Greek | ✓ |
| `fr` | French (AZERTY) | Latin | |
| `de` | German (QWERTZ) | Latin | |
| `es` | Spanish (QWERTY) | Latin | |
| `it` | Italian (QWERTY) | Latin | |
| `pt` | Portuguese (QWERTY) | Latin | |
| `pt-BR` | Portuguese (Brazil, ABNT2) | Latin | |
| `tr` | Turkish Q | Latin | |
| `tr-F` | Turkish F | Latin | |
| `pl` | Polish (Programmers) | Latin | |
| `cs` | Czech (QWERTZ) | Latin | |
| `sv` | Swedish | Latin | |
| `no` | Norwegian | Latin | |
| `da` | Danish | Latin | |
| `nl` | Dutch | Latin | |

Language models ship for all 18 languages these layouts cover. You can add layouts without changing
the engine: drop a JSON file in your layouts directory or install a package that exposes the
`typoshift.layouts` entry point (see [docs/CUSTOM_LAYOUTS.md](docs/CUSTOM_LAYOUTS.md)).

**Layouts are not languages.** A layout decides which character each key produces. A language
decides which result makes sense. Polish (Programmers) is identical to US English on the base and
Shift levels, so it produces the same candidates. TypoShift reports one layout and lists the other
under `equivalent_layouts`, and the language models decide whether the text reads as English or
Polish.

**Tip:** enable only the layouts you actually use. Fewer layouts mean fewer competing candidates.
`typoshift config init --detect` reads your OS keyboard settings on macOS, Windows and GNOME/X11.

## Installation

TypoShift needs Python 3.11 or newer and has no runtime dependencies.

**From GitHub (macOS / Linux):**

```bash
pipx install git+https://github.com/galb/typoshift.git     # recommended: isolated CLI
# or
python3 -m pip install --user git+https://github.com/galb/typoshift.git
```

**From GitHub (Windows, PowerShell):**

```powershell
py -m pip install --user git+https://github.com/galb/typoshift.git
```

**From a clone:**

```bash
git clone https://github.com/galb/typoshift.git
cd typoshift
python3 -m pip install .
```

**From PyPI:** not published yet. Once it is, use `pip install typoshift`.

Check the installation:

```bash
typoshift doctor
```

No step needs administrator rights.

## Claude Code integration

```bash
typoshift install claude                    # user level: ~/.claude
typoshift install claude --scope project    # this project: ./.claude
typoshift install claude --dry-run          # show what would change
```

This installs two things.

1. **The `/typoshift` skill** goes to `~/.claude/skills/typoshift/` (or `./.claude/skills/typoshift/`).
   Use it explicitly:

   ```text
   /typoshift פךקשדק גקהקךםפ איק מקסא כקשאורק
   ```

   Claude runs the engine, states the reconstruction, and continues with your request. If the
   result is uncertain, it asks you first. The skill also tells Claude how to recognize layout
   mistakes on its own.

2. **An automatic `UserPromptSubmit` hook** in `~/.claude/settings.json` (user scope) or
   `.claude/settings.local.json` (project scope). Claude Code hooks
   [cannot replace a prompt](https://code.claude.com/docs/en/hooks.md), so the hook does not try to.
   When it finds a mistake it adds context next to your unchanged prompt:

   ```json
   {
     "hookSpecificOutput": {
       "hookEventName": "UserPromptSubmit",
       "additionalContext": "[TypoShift] Part of this prompt looks like it was typed with the wrong keyboard layout. ... Reconstructed prompt:\nplease develop the next feature ..."
     },
     "systemMessage": "TypoShift read as \"please develop the next feature\" (he→en-US, confidence 0.999)"
   }
   ```

   - **High-confidence reconstructions** are given to Claude as your intended prompt, so it doesn't
     ask you to confirm.
   - **Uncertain ones** are flagged as "do not act without asking".
   - **Destructive actions** (delete, drop, force-push, deploy, and similar) are always confirmed
     first.
   - **Correct prompts** produce no output at all.

   The hook always exits 0. If anything goes wrong it prints a note to stderr (visible only in
   Claude Code's verbose mode) and never blocks the prompt.

The installer:

- keeps your existing settings and hooks;
- is idempotent;
- refuses to touch a `settings.json` that isn't valid JSON;
- backs up the previous file to `settings.json.typoshift.bak`;
- writes atomically and handles interpreter paths that contain spaces;
- never replaces a `typoshift` skill it didn't create (unless you pass `--force`).

To remove everything it added:

```bash
typoshift uninstall claude                  # add --scope project / --dry-run as needed
```

**Without pip** (running from a clone), use `python3 integrations/claude-code/install.py`, or point a
hook at `integrations/claude-code/hooks/typoshift_hook.py`. **Manually**, copy
`integrations/claude-code/SKILL.md` and `reference.md` into `~/.claude/skills/typoshift/`.

## CLI usage

```text
typoshift fix TEXT          print the corrected text           (--json, --verbose, --mode, --from/--to)
typoshift detect TEXT       report likely mistakes; exit 0 if found, 1 if not
typoshift convert --from he --to en-US TEXT    raw key-by-key conversion (no detection, no protection)
typoshift layouts           list layouts (* = enabled)
typoshift config show|path|init|set            (--project, --detect, --dry-run)
typoshift doctor            check data, calibration, config and Claude Code status
typoshift install claude    install the skill and hook          (--scope, --dry-run, --no-hook, --no-skill)
typoshift uninstall claude  remove them                         (--scope, --dry-run)
```

Text can come from arguments or stdin (`--stdin`, or a pipe). Exit codes:

| Code | Meaning |
| ---: | --- |
| 0 | Success |
| 1 | `detect` found nothing, or `doctor` found a problem |
| 2 | Usage error, such as an unknown layout or invalid configuration |
| 3 | Install or uninstall refused; nothing was changed |

```text
$ typoshift detect "פךקשדק"
he → en-US [0.999] 'פךקשדק' → 'please' (auto)

$ typoshift fix --verbose "תעדכן את ה-README ואז ghbdtn"
applied:   en-US → ru [0.998] 'ghbdtn' → 'привет'
תעדכן את ה-README ואז привет

$ typoshift convert --from he --to en-US "פךקשדק"
please
```

`typoshift fix --json` returns the full result:

```json
{
  "original": "פךקשדק גקהקךםפ איק מקסא כקשאורק",
  "corrected": "please develop the next feature",
  "source_layout": "he",
  "target_layout": "en-US",
  "target_language": "en",
  "confidence": 0.9998,
  "was_corrected": true,
  "method": "keyboard_layout_mapping",
  "mode": "auto",
  "requires_confirmation": false,
  "corrections": [{"start": 0, "end": 31, "original": "…", "replacement": "please develop the next feature",
                   "source_layout": "he", "target_layout": "en-US", "language": "en",
                   "confidence": 0.9998, "applied": true}],
  "suggestions": []
}
```

`--verbose` adds the feature values behind each confidence score.

## Python API

```python
from typoshift import Engine, fix
from typoshift.configuration import Config

result = fix("פךקשדק גקהקךםפ איק מקסא כקשאורק")   # uses your configuration files
print(result.corrected, result.to_dict()["confidence"])

engine = Engine(Config(layouts=["en-US", "ru"], mode="suggest"))
result = engine.fix("ghbdtn rfr ltkf")
print(result.suggested_text)          # 'привет как дела'
engine.convert("ghbdtn", "en-US", "ru")  # 'привет'
```

## Configuration

Settings are read in this order, with later layers winning:

1. built-in defaults;
2. the user file (`~/.config/typoshift/config.toml`, `%APPDATA%\typoshift\config.toml` on Windows,
   or `$TYPOSHIFT_CONFIG`);
3. the nearest `.typoshift.toml` in the project;
4. the environment variables `TYPOSHIFT_MODE` and `TYPOSHIFT_DISABLE=1`.

```toml
mode = "auto"                 # auto | suggest | manual | disabled
layouts = ["en-US", "he"]     # only the layouts you switch between
auto_threshold = 0.9          # apply a correction automatically at or above this confidence
suggest_threshold = 0.5       # report a suggestion at or above this confidence
min_auto_letters = 4          # shorter spans need supporting context to be auto-applied
same_script_auto = false      # AZERTY<->QWERTY, Russian<->Ukrainian: suggest only

[protection]
extra_patterns = ['JIRA-\d+'] # never touch text matching these regexes
disabled_rules = []           # e.g. ["acronym"]; see docs/CONFIGURATION.md

[hook]
enabled = true
show_message = true
max_prompt_chars = 20000
```

| Mode | Behavior |
| --- | --- |
| `auto` | Applies high-confidence corrections and suggests uncertain ones. |
| `suggest` | Never changes text, only reports. |
| `manual` | Converts only with an explicit `--from`/`--to`. The hook never acts. |
| `disabled` | Turns TypoShift off entirely. |

`typoshift config set mode suggest` changes one setting. Every option is documented in
[docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## How it works

```text
prompt
  │
  ├─ 1. protection     code fences, inline code, URLs, e-mails, paths, identifiers, JSON/YAML,
  │                    shell lines, hashes, secrets, regexes  → never touched
  ├─ 2. tokenization   whitespace chunks (punctuation stays attached: on Hebrew, "," types ת)
  ├─ 3. scripts        Unicode script of each chunk
  ├─ 4. candidates     for each enabled (typed layout → intended layout) pair, the runs of
  │                    chunks the typed layout could have produced
  ├─ 5. reconstruction physical keystrokes → intended layout (dead keys, ligatures, ambiguity)
  ├─ 6. plausibility   word lexicon + character trigram model per language, normalized
  ├─ 7. spans          only chunks that become more plausible change; mixed prompts keep the rest
  ├─ 8. confidence     logistic model over 15 features, fitted on synthetic data
  └─ 9. policy         thresholds, minimum length, same-script rule, destructive-action flag
```

The core engine knows nothing about Claude Code. The integrations are thin adapters, so other
agents and editors can be added the same way. Details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Data provenance:**

- **Layout mappings** come from xkeyboard-config (vendored with its license in `tools/xkb`) and are
  generated by `tools/generate_layouts.py`.
- **Language models** are word lists and character trigram statistics built from the
  [FrequencyWords](https://github.com/hermitdave/FrequencyWords) OpenSubtitles 2018 lists
  (CC BY-SA 4.0) by `tools/build_language_data.py`.
- **Confidence** is fitted by `tools/calibrate.py` on 24,000 synthetic samples. Its feature weights
  are never set by hand.

## Accuracy and performance

These are measured numbers, reproducible with `python benchmarks/run_benchmark.py`. Full results,
including every failure, are in [benchmarks/results/latest.md](benchmarks/results/latest.md).

The evaluation corpus is hand-written:

- 1,360 lines in 18 languages (`benchmarks/corpus`), independent of the word lists used to train
  and calibrate the models;
- wrong-layout inputs produced by replaying each sentence's keystrokes on another layout.

| Metric (automatic mode, default settings) | Result |
| --- | --- |
| Precision: changes that were exactly right | **98.92%** |
| Recall: wrong-layout inputs fixed exactly | **87.55%** |
| False-positive rate: correctly typed inputs changed (1,720 negatives) | **0.00%** |
| Recall with suggestions included (`suggest` mode) | 93.72% |
| Correct inputs that got an "uncertain" hook note (no change) | 0.58% |
| Latency per prompt, warm (p50 / p95) | 0.24 ms / 1.52 ms |
| Hook cold start: new Python process, Hebrew prompt | ~90 ms |

These were measured on an Apple Silicon Mac with Python 3.14, on 2026-10-13.

On a held-out split of its synthetic data, the calibrated confidence has an expected calibration
error of 0.004. At the 0.9 threshold it reaches 98.7% precision at 89.1% recall on those
proposals.

**Read these numbers with care:**

- The benchmark corpus was also used for error analysis during development, so results on new
  text may be somewhat lower.
- Short inputs of one or two words are much harder than sentences. Most misses come from them,
  and the safety policy prefers to suggest rather than change them.
- Latin↔Latin pairs (for example AZERTY vs QWERTY) are suggest-only by default. In testing they
  reached only about 71% precision in automatic mode.

## Safety

False corrections are the main risk, so the defaults favor leaving text alone:

- **Protected patterns** are never rewritten: code fences, inline code, URLs, e-mail addresses,
  Unix and Windows paths, file names, dotfiles, `snake_case` identifiers and English
  camelCase/PascalCase, operators, hashes, versions, CLI flags, @mentions, issue references,
  environment variables, JSON, YAML blocks, shell command lines, code lines, regexes, API-key
  formats, high-entropy strings, acronyms and mixed-script words (`הAPI`). You can add your own
  regexes.
- **Only letters count.** A rewrite that changes punctuation only is never a correction.
- **Spans, not prompts.** In a mixed prompt only the mistyped chunks change, and the offsets are
  reported.
- **Thresholds and policy:**
  - corrections are auto-applied only at confidence ≥ 0.9;
  - spans shorter than 4 letters need supporting context;
  - same-script pairs are suggest-only;
  - with no calibration data, nothing is applied.
- **Destructive reconstructions** (delete, drop, force-push, deploy, and similar) set
  `requires_confirmation`. The Claude Code hook and skill then insist on confirmation.
- **Offline and private.** No network access at runtime, no telemetry, and no prompt is stored.
  See [SECURITY.md](SECURITY.md).

## Limitations

- **Detection is heuristic.** It relies on word lists and character statistics from movie
  subtitles. Rare words, names, jargon and very short inputs can be scored wrongly. When the engine
  is unsure it suggests instead of changing.
- **Only the base and Shift levels are modelled.** AltGr characters (for example Polish `ą` on the
  Programmers layout) are not reconstructed.
- **Platform variants differ.** The built-in layouts follow XKB, which matches standard Windows
  layouts for letters. macOS "Russian" (non-PC), macOS "Arabic" and Hebrew-QWERTY are different
  layouts. You can add them as custom layouts.
- **Letters on the number row** (Czech `ěščřžýáíé`, French `éèçà`) turn into digits when typed on a
  US layout, and digit-letter mixes are protected as identifiers. These words are often left alone.
- **Inherently ambiguous keys.** Arabic `لا` can be either the lam-alef key or `g`+`h`. Greek `Σ`
  can be Shift+`σ` or Shift+`ς`. TypoShift scores both readings, but context beyond one word is not
  modelled.
- **Russian vs Ukrainian.** The two layouts share most keys. When both are enabled and the text has
  no distinguishing letters, the engine may suggest instead of correcting.
- **The destructive-action flag** recognizes common verbs in English, Hebrew, Russian, Ukrainian and
  Arabic only.

## Roadmap

1. Word-bigram context to resolve ambiguous single words.
2. Built-in macOS layout variants (Russian, Arabic, Hebrew-QWERTY).
3. AltGr (level 3) support.
4. A local HTTP service and Language Server Protocol adapter (the engine API is ready, see
   `src/typoshift/integrations/__init__.py`).
5. Integrations for Cursor, VS Code and other agents.
6. Community layout packages through the `typoshift.layouts` entry point.
7. Desktop keyboard correction (an OS-level input hook). This is out of scope until the core is
   proven in agents.

## Contributing

Contributions are welcome, especially new layouts, language data and hard negative examples. See
[CONTRIBUTING.md](CONTRIBUTING.md). Report security issues privately as described in
[SECURITY.md](SECURITY.md).

## License

- **Code:** MIT, © 2026 galb. See [LICENSE](LICENSE).
- **Bundled language data** (`src/typoshift/data/lang`): CC BY-SA 4.0, derived from FrequencyWords
  and OpenSubtitles. See [its LICENSE](src/typoshift/data/lang/LICENSE).
- **Keyboard layout source data** (`tools/xkb`): the xkeyboard-config and xorgproto licenses in
  [tools/xkb/COPYING](tools/xkb/COPYING) and [tools/xkb/COPYING-xorgproto](tools/xkb/COPYING-xorgproto).
