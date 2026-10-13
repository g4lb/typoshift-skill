---
name: typoshift
description: Fixes text typed with the wrong keyboard layout (for example Hebrew, Russian, Arabic or Greek letters typed while the user meant English, or English letters typed while they meant Hebrew or Russian) by mapping each character back to the physical key that produced it. Use when a message contains gibberish in another script that looks like a keyboard-layout mistake, when a "[TypoShift]" note appears in the context, or when the user runs /typoshift.
argument-hint: "[text typed with the wrong keyboard layout]"
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/typoshift.py *), Bash(python ${CLAUDE_SKILL_DIR}/scripts/typoshift.py *), Bash(py ${CLAUDE_SKILL_DIR}/scripts/typoshift.py *)
---

# TypoShift

Recover what the user meant when their keyboard was on the wrong layout. For
example, `פךקשדק גקהקךםפ איק מקסא כקשאורק` is the Hebrew layout's output for
the keys of `please develop the next feature`.

This is **not translation**. Each character maps back to the physical key that
typed it, and that key is read in another layout. Never translate, paraphrase
or fix meaning. Only undo the layout mistake.

## When to use it

- The user ran `/typoshift <text>`.
- A `[TypoShift]` note is in the context. The optional TypoShift hook adds
  one when it detects a mistake.
- The message contains words in another script that form no real words but
  look like a layout mistake: `ghbdtn` (meant `привет`), `akuo` (meant `שלום`),
  `Руддщ` (meant `Hello`).

Do not use it on text that is meaningful as typed. That includes real Hebrew,
Russian or Arabic, intentionally mixed-language messages, code, paths, URLs,
identifiers, hashes and secrets.

## Procedure

1. List the possible reconstructions with the bundled script. It needs only
   Python 3.8+ (no install, no network) and runs in milliseconds. Pass the text
   in a quoted heredoc so the shell never interprets it:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/typoshift.py candidates <<'TYPOSHIFT_EOF'
   $ARGUMENTS
   TYPOSHIFT_EOF
   ```

   On Windows use `py` instead of `python3`. The script prints one line per
   reconstruction (`typed on -> intended: text`) and leaves code, URLs, paths
   and similar strings untouched. To limit it to the user's layouts, add
   `--layouts en-US,he`. Run `typoshift.py layouts` to list all 20 layouts.

2. Choose a reconstruction. Usually exactly one candidate reads as natural
   text in its language, and the others are gibberish.
   - **One candidate is clearly a sensible message:** state it in one line
     (`Read as: "…" (typed on he, meant en-US)`), then do what it asks. Do not
     ask for confirmation.
   - **Two or more are plausible, or the best one is only partly sensible:**
     show the original and your best reading, and ask the user to confirm
     before acting.
   - **None makes sense:** say no layout mistake was found.
   - **The reconstruction asks for something destructive or irreversible**
     (delete, drop, force-push, deploy, rm, reset): always confirm the exact
     action first, however clear it seems.

3. If Python is unavailable, reconstruct by hand with the key tables in
   [reference.md](reference.md). Say that the reconstruction is manual and
   ask the user to confirm it.

## Notes

- Mixed prompts are converted chunk by chunk. Only the mistyped words change;
  correctly typed words stay as written.
- Some keys are ambiguous. The Arabic `لا` key is also `g`+`h`; the script
  shows the lam-alef reading, so consider `gh` too if the result looks off by
  that key.
- Automatic correction of every prompt (without `/typoshift`) needs the
  TypoShift hook from the Claude Code plugin:
  `/plugin install typoshift --marketplace g4lb/typoshift-skill`.
