# TypoShift

**Type in the wrong language. Get the right words.**

[![CI](https://github.com/g4lb/typoshift-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/g4lb/typoshift-skill/actions/workflows/ci.yml)
[![skills.sh](https://img.shields.io/badge/skills.sh-g4lb%2Ftyposhift--skill-black)](https://skills.sh/g4lb/typoshift-skill/typoshift)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A Claude Code skill that fixes prompts typed with the wrong keyboard layout.

```text
/typoshift פךקשדק גקהקךםפ איק מקסא כקשאורק
→ Read as: "please develop the next feature" (typed on he, meant en-US)
```

You meant to type English, but the keyboard was on Hebrew. TypoShift finds the physical key behind
each character (`פ` is on the `P` key, `ך` on `L`, ...) and reads those keys in the layout you
intended. It works across 20 layouts, including Hebrew, Russian, Ukrainian, Arabic and Greek.

The skill is light: one standard-library Python script and about 110 KB in total. It needs no install
and no network, and runs in milliseconds.

## Install

**The skill** (from [skills.sh](https://skills.sh/g4lb/typoshift-skill/typoshift)):

```bash
npx skills add g4lb/typoshift-skill -a claude-code          # add -g for all your projects
```

Then use `/typoshift <text>`. Claude also uses the skill on its own when a message looks like a
layout mistake. It needs only `python3` (3.8+), which is already on macOS and Linux; on Windows it
uses `py`.

**The skill plus automatic correction** (Claude Code plugin):

```text
/plugin install typoshift --marketplace g4lb/typoshift-skill
```

On older Claude Code versions: `/plugin marketplace add g4lb/typoshift-skill`, then
`/plugin install typoshift@typoshift`.

The plugin adds a `UserPromptSubmit` hook. It checks every prompt and, when part of it was typed on
the wrong layout, gives Claude the reconstruction. You don't need to type `/typoshift`. The hook
uses the full detection engine bundled in the plugin, so it needs `python3` 3.11+ on PATH but no pip
install.

**Manual:** copy `skills/typoshift/` into `~/.claude/skills/` (all projects) or `.claude/skills/`
(one project).

## What it does (and does not)

| Technique | What it does | Example | TypoShift? |
| --- | --- | --- | --- |
| **Keyboard-layout reconstruction** | Recovers the physical keys pressed and reads them in another layout | `ghbdtn` → `привет` | **Yes** |
| Spell checking | Fixes misspelled words in the right alphabet | `teh` → `the` | No |
| Transliteration | Writes a word's sound in another script | `privet` → `привет` | No |
| Translation | Changes the language and keeps the meaning | `hello` → `привет` | No |

TypoShift never translates or paraphrases. A correction is always a key-for-key replay, so it can
only produce what you would have typed on the other layout.

## Examples

Real `typoshift.py candidates` output, top line. Claude reads it and states the reconstruction.

| You typed | Keyboard was on | Read as |
| --- | --- | --- |
| `פךקשדק גקהקךםפ איק מקסא כקשאורק` | Hebrew | `please develop the next feature` |
| `please implement the login פשעק` | Hebrew (last word only) | `please implement the login page` |
| `ghbdtn rfr ltkf&` | English (meant Russian) | `привет как дела?` |
| `Руддщ цщкдв` | Russian (meant English) | `Hello world` |
| `תעדכן את ה-README ואז ghbdtn` | mixed | `תעדכן את ה-README ואז привет` |
| `Please update src/components/Header.tsx` | correct | "probably no layout mistake" |

`ltkf&` becomes `дела?` because on the Russian layout `?` is Shift+7, the key that types `&` in
English. This is physical reconstruction, not guessing.

## How the skill works

1. `scripts/typoshift.py candidates` lists every reconstruction of the text: one per pair of
   "typed on" and "meant" layouts.
   - Code, URLs, paths, e-mail addresses and identifiers are left alone.
   - Words that are already common in their own language are not converted.
   - Candidates are ranked by how many of their converted words are common words in the
     target language.
2. Claude reads the short list and picks the reading that makes sense. That decision is language
   understanding, which Claude does far better than any word list.
   - **One clear reading:** Claude states it in one line and carries on.
   - **Ambiguous:** Claude asks you first.
   - **Destructive** (delete, force-push, deploy, and similar): Claude always confirms first.

```text
$ python3 skills/typoshift/scripts/typoshift.py candidates <<< "ghbdtn rfr ltkf&"
1. en-US -> ru: привет как дела?  [3/3 common words]  (same as en-US->uk)
2. en-US -> he: עינגאמ רכר ךאלכ&  [0/3 common words]
...
```

## Automatic correction (the hook)

The plugin's hook, and the optional `typoshift install claude` command, run the full TypoShift
engine on every prompt. That engine has its own language models and calibrated confidence. Claude
Code hooks [cannot replace a prompt](https://code.claude.com/docs/en/hooks.md), so the hook adds
context next to your unchanged prompt:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "[TypoShift] Part of this prompt looks like it was typed with the wrong keyboard layout. ... Reconstructed prompt:\nplease develop the next feature ..."
  },
  "systemMessage": "TypoShift read as \"please develop the next feature\" (he→en-US, confidence 0.999)"
}
```

- **High-confidence reconstructions** are given to Claude as your intended prompt.
- **Uncertain ones** are flagged as "do not act without asking".
- **Destructive actions** are always confirmed.
- **Correct prompts** produce no output.

The hook always exits 0 and never blocks a prompt. It was tested in a live Claude Code session.

On a hand-written benchmark in 18 languages, the hook's engine reached 98.9% precision and 87.6%
recall, and changed 0 of 1,720 correctly typed prompts. Details are in
[docs/ENGINE.md](docs/ENGINE.md#accuracy-and-performance-engine--hook).

## Supported layouts

20 layouts, all **generated** from the
[xkeyboard-config](https://gitlab.freedesktop.org/xkeyboard-config/xkeyboard-config) database, never
typed by hand, and tested key by key:

English (US) · Hebrew · Russian · Ukrainian · Arabic · Greek · French (AZERTY) · German (QWERTZ) ·
Spanish · Italian · Portuguese · Portuguese (Brazil, ABNT2) · Turkish Q · Turkish F ·
Polish (Programmers) · Czech · Swedish · Norwegian · Danish · Dutch

By default the skill considers `en-US, he, ru, uk, ar, el`. Ask Claude to use other layouts, or run
the script with `--layouts`. The key tables are in [docs/LAYOUTS.md](docs/LAYOUTS.md).

## Safety

- **Code is never touched:** code blocks, inline code, URLs, e-mail addresses, paths, file names,
  identifiers, flags, hashes, secrets and mixed-script words such as `הAPI` stay as you typed them.
- **Only mistyped words change.** In a mixed prompt, correctly typed words stay as written.
- **Claude decides only when it's clear.** It acts on an unambiguous reconstruction, asks when
  unsure, and always confirms destructive actions (delete, drop, force-push, deploy, and similar).
- **The hook never blocks or replaces a prompt.** It only adds context, and it auto-applies only
  calibrated, high-confidence corrections.
- **Offline and private.** No network, no telemetry, nothing stored. See [SECURITY.md](SECURITY.md).

## Limitations

- **The hook's detection is heuristic.** It relies on word lists and character statistics from
  movie subtitles, so rare words, names, jargon and very short prompts can be scored wrongly. When
  unsure it suggests instead of changing. The skill leaves that judgement to Claude.
- **Only the base and Shift levels are modelled.** AltGr characters (for example Polish `ą` on the
  Programmers layout) are not reconstructed.
- **Platform variants differ.** The layouts follow XKB, which matches standard Windows layouts for
  letters. macOS "Russian" (non-PC), macOS "Arabic" and Hebrew-QWERTY are different layouts and are
  not built in.
- **Letters on the number row** (Czech `ěščřžýáíé`, French `éèçà`) turn into digits when typed on a
  US layout. Words mixing digits and letters are protected as identifiers, so these are often left
  alone.
- **Ambiguous keys.** Arabic `لا` is both the lam-alef key and `g`+`h`, and Greek `Σ` is both
  Shift+`σ` and Shift+`ς`. The skill shows one reading and its instructions tell Claude to consider
  the other. The hook scores both.
- **Russian vs Ukrainian.** The two layouts share most keys, so text without distinguishing letters
  gives the same reconstruction for both.

## Roadmap

1. Word-pair context for ambiguous single words.
2. Built-in macOS layout variants (Russian, Arabic, Hebrew-QWERTY).
3. AltGr (level 3) support.
4. The same skill for other agents that read `SKILL.md` (the skills.sh CLI already installs to
   many agents).

## Contributing

Contributions are welcome, especially new layouts and hard negative examples. See
[CONTRIBUTING.md](CONTRIBUTING.md). Report security issues privately as described in
[SECURITY.md](SECURITY.md).

## License

- **Code:** MIT, © 2026 galb. See [LICENSE](LICENSE).
- **Word lists** (`skills/typoshift/scripts/common_words.json`, `src/typoshift/data/lang`): CC BY-SA
  4.0, derived from FrequencyWords and OpenSubtitles.
- **Keyboard layout source data:** the xkeyboard-config and xorgproto licenses in
  [tools/xkb](tools/xkb).
