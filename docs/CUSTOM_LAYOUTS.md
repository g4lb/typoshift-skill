# Custom layouts

You can add layouts without modifying TypoShift. There are two ways to install one.

1. **A JSON file in your layouts directory.** This is `~/.config/typoshift/layouts/` by default.
   Change it with `layouts_dir`.
2. **A Python package with a `typoshift.layouts` entry point.** The entry point resolves either to
   a directory path or to a callable that returns layout dictionaries:

   ```toml
   # pyproject.toml of your package
   [project.entry-points."typoshift.layouts"]
   my-layouts = "my_package:layouts_dir"   # returns a path to a folder of *.json files
   ```

Layouts are loaded in this order: built-in, then entry points, then the user directory. A later
layout with the same `id` overrides an earlier one. After adding a layout, enable it with
`typoshift config set layouts en-US,my-layout`.

## Format

```json
{
  "id": "ru-mac",
  "name": "Russian (macOS)",
  "languages": ["ru"],
  "script": "Cyrillic",
  "levels": ["base", "shift"],
  "keys": {
    "AD01": ["й", "Й"],
    "AC01": ["ф", "Ф"]
  },
  "dead_keys": {"AC10": ["0"]},
  "sequences": {"لا": ["AB05", 0]},
  "source": {"database": "...", "symbols": "..."},
  "notes": "free text"
}
```

- **`keys`** maps XKB key codes to `[base, shift]`. Each value is a single character or `null`. The
  key codes are:
  - number row: `TLDE`, `AE01`–`AE12`
  - top row: `AD01`–`AD12`
  - home row: `AC01`–`AC11`
  - backslash key: `BKSL`
  - ISO key left of Z: `LSGT`
  - bottom row: `AB01`–`AB11` (`AB11` is the extra Brazilian key)
- **`dead_keys`** (optional) maps a key to the levels that are dead keys. Use the spacing accent as
  the character, for example `´`.
- **`sequences`** (optional) maps a multi-character string to the key and level that types it at
  once.
- **`languages`** are the languages whose models score candidates for this layout. They must be
  among the bundled languages (`typoshift doctor` lists them). For any other language the layout
  still converts, but it cannot be detected automatically.

## Verifying a layout

Do not type mappings from memory. Generate them from a reliable source (XKB symbols, a Windows
KLC file, or macOS `.keylayout`). Check a few known words with
`typoshift convert --from <id> --to en-US`.

To contribute a layout upstream:

1. Add it to `SPECS` in `tools/generate_layouts.py`, vendor the XKB symbols file into
   `tools/xkb/symbols`, and regenerate.
2. Add row fixtures to `tests/test_layouts.py`.
