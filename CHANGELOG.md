# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- The skill is now self-contained and light. `skills/typoshift/scripts/typoshift.py` uses only the
  standard library and Python 3.8+, and the skill totals about 70 KB with layouts and common words.
  It lists the reconstructions and Claude picks the one that makes sense. The skill no longer needs
  the Python package.
- Added a Claude Code plugin (`.claude-plugin/`) that bundles the skill and the automatic hook.
- Installable from skills.sh: `npx skills add g4lb/typoshift-skill`.

## [0.1.0] - 2026-10-13

Initial release.

### Added

- Correction engine based on physical-key reconstruction, with automatic, suggest, manual and
  disabled modes.
- 20 keyboard layouts generated from xkeyboard-config:
  - English (US), Hebrew, Russian, Ukrainian, Arabic, Greek;
  - French AZERTY, German QWERTZ, Spanish, Italian, Portuguese, Portuguese (Brazil, ABNT2);
  - Turkish Q and F, Polish (Programmers), Czech, Swedish, Norwegian, Danish, Dutch.

  Supports dead keys, the Arabic lam-alef key and ambiguous keys.
- Offline language models for 18 languages: lexicons and character trigrams derived from
  FrequencyWords (CC BY-SA 4.0).
- Calibrated confidence (logistic model, held-out ECE 0.004) fitted by `tools/calibrate.py`.
- Mixed-language span detection, which rewrites only the mistyped part of a prompt.
- Protection rules for code, paths, URLs, e-mail addresses, identifiers, secrets, JSON/YAML, shell
  commands, regexes and more, plus user-defined patterns.
- Safety policy:
  - confidence thresholds;
  - a minimum span length for automatic changes;
  - suggest-only same-script pairs;
  - a flag for destructive actions.
- `typoshift` CLI: `fix`, `detect`, `convert`, `layouts`, `config`, `doctor`, `install`,
  `uninstall`, `hook`.
- Claude Code integration: the `/typoshift` skill, an automatic `UserPromptSubmit` hook (context
  only, never blocks), and an idempotent installer/uninstaller that preserves existing settings.
- Best-effort detection of OS keyboard layouts (macOS, Windows, GNOME/X11).
- Benchmark on a hand-written 18-language corpus. Default settings give 98.9% precision, 87.6%
  recall and a 0.0% false-positive rate.
- Tests, GitHub Actions CI, and documentation.
