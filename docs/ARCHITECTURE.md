# Architecture

TypoShift is a small, dependency-free Python package. The correction engine does not depend on any
integration. Integrations depend only on the public engine API.

```text
src/typoshift/
├── engine.py          public API: Engine, fix(), detect(), convert(), FixResult, Correction, Mode
├── configuration.py   layered TOML configuration (defaults → user → project → env)
├── tokenizer.py       whitespace chunks + protected regions (lossless: tokens re-join to the input)
├── protection.py      protected-pattern rules (span rules and chunk rules)
├── scripts.py         Unicode script identification
├── conversion.py      physical-key reconstruction between layouts (dead keys, ligatures, ambiguity)
├── langmodel.py       per-language lexicon + character trigram model (Witten-Bell), z-normalized
├── detection.py       candidate generation, span selection, feature extraction
├── confidence.py      calibrated logistic model (weights from data/calibration.json)
├── system_layouts.py  best-effort OS keyboard-layout detection (doctor / config init only)
├── cli.py             `typoshift` command
├── layouts/
│   ├── registry.py    Layout model, JSON loading, user directory + entry-point plugins
│   └── data/*.json    20 generated layouts (+ XKB license notices)
├── data/
│   ├── lang/*.json.gz 18 language models (CC BY-SA 4.0)
│   └── calibration.json
└── integrations/
    └── claude_code/   hook.py (UserPromptSubmit), installer.py, skill/SKILL.md + reference.md
```

## Data model

- **Stroke** = `(key_code, level)`. Key codes are XKB names, for example `AD01` for the key labelled
  Q on a US keyboard. Level 0 is unshifted and level 1 is Shift.
- **Layout** maps each key to its characters at the two levels. It also lists `dead_keys`
  (key → levels) and multi-character `sequences` (for example the Arabic lam-alef key emits `لا`).
  The layout builds a reverse index from characters to strokes. When several keys produce the same
  character, keys present on ANSI keyboards are ranked first.
- **LanguageModel** holds a lexicon (the 30,000 most frequent words), character trigram counts, and
  normalization statistics measured on held-out words.

## Conversion

`decode(text, source)` turns text into slots of keystroke alternatives.

- Characters the source layout cannot type (spaces, emoji, numpad input) pass through unchanged.
- A precomposed letter that needs a dead key (Greek `έ` is dead tonos then `ε`) decodes into two
  strokes.
- A standalone dead-key accent (German `^`) decodes as the dead key followed by Space.
- Ambiguous text produces several alternatives in its slot. Examples are `لا` (lam-alef key, or
  lam then alef) and a letter on two keys (Greek `Σ` is Shift+`σ` or Shift+`ς`).

`encode(strokes, target)` replays the strokes on the target layout. A dead key composes with the
next letter, or with Space it gives the spacing accent. Keys the target lacks (the ISO `<>` key on a
US keyboard) keep the source character and are counted as unmapped.

`convert_variants` enumerates up to 8 alternatives. The detector scores each one and keeps the best.

## Detection pipeline

1. **Protection and tokenization.** Span rules (fences, URLs, JSON, shell lines, and so on) run on
   the whole text. Each remaining whitespace chunk is checked against the chunk rules. Protected
   tokens break runs.
2. **Runs.** For every enabled source layout, a run is a maximal sequence of chunks that layout
   could have produced. Runs with no suspicious chunk are skipped, which keeps correct prompts
   cheap. A chunk is suspicious when most of its letters are unknown in every enabled language of
   its script, or when letters are glued together by punctuation (`pr;ta`).
3. **Candidates.** For every target layout, each chunk in the run is converted. It is scored under
   the target layout's languages and compared with its best native score as typed. The gain is
   `Δz + 3·Δknown − 3·(1 − purity)`. A chunk whose letters do not change counts as neutral.
4. **Spans.**
   - Chunks with positive gain flip.
   - Neutral chunks and weak or suspicious chunks between two flips are bridged.
   - At the edges, a span grows over suspicious chunks, and over words that are valid in both
     languages when the span already has two or more flips.
5. **Features** (computed per span):
   - `delta_z`, `delta_known`, `target_known`, `source_known`
   - `delta_noise`, `purity`, `log_letters`, `short`
   - `context_support`, `has_context`, `context_conflict`, `short_conflict`: does the rest of the
     prompt read as the target language?
   - `unexplained`: suspicious letters in the run that this span leaves unexplained
   - `competitor_gap`, `contested`: how much better this candidate is than inconsistent rivals for
     the same text, compared only on the words where they differ
6. **Confidence.** A logistic model turns the features into P(correct). Its weights come from
   `tools/calibrate.py` and are never set by hand.
7. **Selection.** Proposals are chosen greedily from the highest confidence. A proposal that
   extends a chosen one and agrees with it word for word replaces it. Duplicate replacements from
   other layouts are listed as `equivalent_layouts`.
8. **Policy.** `auto` mode applies a proposal only when all of these hold:
   - confidence ≥ `auto_threshold`;
   - the span has ≥ `min_auto_letters` letters, or the context supports it;
   - the source and target scripts differ, unless `same_script_auto` is set.

   Everything else at or above `suggest_threshold` is reported as a suggestion.
   `requires_confirmation` is set when a reconstruction contains a destructive verb.

## Calibration

`tools/calibrate.py` synthesizes 24,000 inputs from the frequency lists. It samples by frequency,
and 15% of the words come from held-out ranks outside the lexicon.

| Input type | Share | Description |
| --- | --- | --- |
| Full mistakes | 40% | The whole input is typed on the wrong layout. |
| Fragment mistakes | 20% | Only part of the input is typed on the wrong layout. |
| Negatives | 40% | Correct text, some with typos, words from other scripts, or a language whose layout is not enabled. |

Half of the samples use a two-layout setup and half use the default layout set. Each proposal is
labelled by token-aligned exact match. A held-out 20% split is used to report log-loss, ECE and
precision/recall at several thresholds. These are stored in `calibration.json`.

## Integration boundary

An integration converts its host's input into `Engine.fix(text, mode)` and renders the resulting
`FixResult`. The Claude Code hook reads the `UserPromptSubmit` JSON on stdin and writes
`hookSpecificOutput.additionalContext` (plus an optional `systemMessage`). It always exits 0.
Other hosts (Cursor, VS Code, an LSP server, a local HTTP service) need only a similar adapter.
None is implemented yet.

## Regenerating data

```bash
python tools/generate_layouts.py    # layouts from tools/xkb (vendored xkeyboard-config)
python tools/generate_docs.py       # docs/LAYOUTS.md + skill reference.md
python tools/build_language_data.py # language models (downloads pinned FrequencyWords lists)
python tools/calibrate.py           # confidence model
python tools/sync_skill.py          # copy the skill to .claude/ and integrations/
python benchmarks/run_benchmark.py  # results in benchmarks/results/
```

Each step is deterministic for a given input (fixed seeds and pinned upstream commits).
`tools/generate_layouts.py --check` and `tools/generate_docs.py --check` run in the test suite.
