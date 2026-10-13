# The TypoShift engine and CLI (optional)

The skill (`skills/typoshift/`) needs none of this. This document covers the full detection engine,
which powers the automatic hook in the Claude Code plugin and is also available as a CLI and Python
library.

## Install

The engine behind the hook is also a dependency-free Python package (Python 3.11+). It is useful for
scripting, for other editors, or for the hook without the plugin:

```bash
pipx install git+https://github.com/g4lb/typoshift-skill.git
typoshift fix "פךקשדק גקהקךםפ איק מקסא כקשאורק"     # please develop the next feature
typoshift install claude                             # skill + hook, without the plugin system
```

`typoshift install claude` keeps your existing settings and hooks, is idempotent, makes a backup,
and refuses to touch invalid JSON. `typoshift uninstall claude` removes only what it added. Use
either the plugin or `typoshift install claude`, not both, or the hook runs twice.

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
[docs/CONFIGURATION.md](CONFIGURATION.md).

## How the engine works

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
agents and editors can be added the same way. Details are in [docs/ARCHITECTURE.md](ARCHITECTURE.md).

**Data provenance:**

- **Layout mappings** come from xkeyboard-config (vendored with its license in `tools/xkb`) and are
  generated by `tools/generate_layouts.py`.
- **Language models** are word lists and character trigram statistics built from the
  [FrequencyWords](https://github.com/hermitdave/FrequencyWords) OpenSubtitles 2018 lists
  (CC BY-SA 4.0) by `tools/build_language_data.py`.
- **Confidence** is fitted by `tools/calibrate.py` on 24,000 synthetic samples. Its feature weights
  are never set by hand.

## Accuracy and performance (engine / hook)

These are measured numbers, reproducible with `python benchmarks/run_benchmark.py`. Full results,
including every failure, are in [benchmarks/results/latest.md](../benchmarks/results/latest.md).

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

## Safety rules in the engine

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
  See [SECURITY.md](../SECURITY.md).


## Background

Anyone who uses two keyboard layouts makes this mistake many times a day. You start typing, look up,
and see `ghbdtn` instead of `привет`, or `פךקשדק` instead of `please`. With an AI coding agent the
mistake costs more: the agent either fails to understand the prompt or acts on a confused reading of
it. TypoShift fixes the prompt before the agent sees it, and does nothing when nothing is wrong.

