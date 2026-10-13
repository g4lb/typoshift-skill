# Configuration

TypoShift reads TOML configuration in this order, with later layers winning:

1. built-in defaults;
2. the user file: `$TYPOSHIFT_CONFIG`, or `%APPDATA%\typoshift\config.toml` on Windows, or
   `$XDG_CONFIG_HOME/typoshift/config.toml` (default `~/.config/typoshift/config.toml`);
3. the nearest `.typoshift.toml` in the working directory or a parent, up to your home directory.
   The Claude Code hook uses the session's `cwd`;
4. environment variables: `TYPOSHIFT_MODE=<mode>` and `TYPOSHIFT_DISABLE=1`.

`typoshift config show` prints the effective configuration and where each setting came from.
`typoshift config init [--detect] [--project]` writes a starter file. `typoshift config set KEY VALUE`
changes one value: lists are comma-separated, and nested keys use dots, for example
`hook.enabled false`.

## Settings

| Key | Default | Meaning |
| --- | --- | --- |
| `mode` | `"auto"` | `auto`: apply confident corrections and suggest the rest. `suggest`: report only. `manual`: convert only with `--from/--to`. `disabled`: off. |
| `layouts` | `["en-US", "he", "ru", "uk", "ar", "el"]` | Layout ids to consider, in preference order. List only the layouts you switch between. |
| `auto_threshold` | `0.9` | Minimum confidence to apply a correction automatically. |
| `suggest_threshold` | `0.5` | Minimum confidence to report a suggestion. |
| `min_letters` | `2` | Spans with fewer letters are ignored. |
| `min_auto_letters` | `4` | Shorter spans are auto-applied only when the rest of the prompt is in the target language. |
| `same_script_auto` | `false` | Allow automatic correction between two layouts of the same script (AZERTY↔QWERTY, Russian↔Ukrainian). These pairs are less reliable, see the benchmark. |
| `confirm_destructive` | `true` | Flag reconstructions with destructive verbs (`requires_confirmation`). |
| `layouts_dir` | config dir + `/layouts` | Directory with custom layout JSON files. |
| `layout_languages` | `{}` | Override the languages a layout's candidates are scored in, for example `{"en-US" = ["en", "fr"]}`. |

### `[protection]`

| Key | Default | Meaning |
| --- | --- | --- |
| `extra_patterns` | `[]` | Regular expressions. Matching text, or chunks that fully match, is never rewritten. |
| `disabled_rules` | `[]` | Built-in rules to turn off. |

Built-in rules:

- **Span rules:** `code_fence`, `inline_code`, `url`, `email`, `windows_path`, `env_var`,
  `shell_prompt`, `code_line`, `shell_command`, `yaml_block`, `json`.
- **Chunk rules:** `path`, `filename`, `dotfile`, `identifier`, `code_operator`, `alnum_mix`,
  `hex_hash`, `version`, `cli_flag`, `mention`, `secret`, `acronym`, `domain`,
  `dotted_identifier`, `symbols`, `high_entropy`, `mixed_script`, `custom`.

Disabling a rule increases recall and risk.

### `[hook]` (Claude Code)

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Turn the automatic hook off without uninstalling it. |
| `show_message` | `true` | Show a one-line `systemMessage` when a reconstruction is added. |
| `max_prompt_chars` | `20000` | Longer prompts are skipped. |

## Example

```toml
mode = "auto"
layouts = ["en-US", "he"]
auto_threshold = 0.92

[protection]
extra_patterns = ['[A-Z]+-\d+', 'acme-\w+']

[hook]
show_message = false
```

Turn TypoShift off temporarily with `TYPOSHIFT_DISABLE=1 claude`, or with `typoshift config set mode
disabled`.
