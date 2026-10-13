# Contributing to TypoShift

Thanks for helping. The most valuable contributions are:

- new keyboard layouts;
- hard negative examples (correct text that TypoShift should leave alone);
- bug reports that include the exact input.

## Development setup

```bash
git clone https://github.com/galb/typoshift.git && cd typoshift
python3 -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
pytest                      # the full test suite
ruff check . && mypy src    # lint and types
python benchmarks/run_benchmark.py --quick
```

## Ground rules

- **Never hand-type keyboard mappings.** Layouts are generated from xkeyboard-config by
  `tools/generate_layouts.py`. For a new layout, vendor its XKB symbols file into
  `tools/xkb/symbols`, add a `LayoutSpec`, regenerate, and add row fixtures to
  `tests/test_layouts.py`. See [docs/CUSTOM_LAYOUTS.md](docs/CUSTOM_LAYOUTS.md).
- **Never hand-tune confidence.** If you change features or the detector, run `tools/calibrate.py`
  and commit the new `calibration.json` together with the code change.
- **Never fabricate benchmark numbers.** Re-run `benchmarks/run_benchmark.py`, commit
  `benchmarks/results/latest.*`, and update the README table from that output.
- **Safety first.** Any change that raises recall must not raise the false-positive rate on the
  negative corpus. Add a regression case to `tests/data/regression.jsonl` for every bug you fix.
- **Keep the engine independent.** `src/typoshift/integrations/` may import the engine, but the
  engine must never import an integration.
- **No runtime dependencies** without a strong reason. The hook runs on every prompt, so startup
  time matters.
- **Corpus independence.** The calibration data (frequency lists) and the evaluation corpus
  (`benchmarks/corpus`) must stay independent. Write new corpus sentences by hand.

## Generated files

After changing layouts, the skill or the data, run the matching tool and commit its output:

| Change | Command |
| --- | --- |
| Layout specs or XKB sources | `python tools/generate_layouts.py && python tools/generate_docs.py` |
| Skill text (`src/typoshift/integrations/claude_code/skill/`) | `python tools/sync_skill.py` |
| Language data | `python tools/build_language_data.py && python tools/calibrate.py` |

## Commits and pull requests

- Keep each pull request focused.
- Describe the user-visible effect.
- Include benchmark output if detection behavior changed.

By contributing you agree that your code is released under the MIT license, and that any data you
add to `src/typoshift/data/lang` is compatible with CC BY-SA 4.0.
