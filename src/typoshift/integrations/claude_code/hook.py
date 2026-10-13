"""Claude Code ``UserPromptSubmit`` hook.

Claude Code runs this for every submitted prompt, passing a JSON object on
stdin (``prompt``, ``cwd``, ``session_id``, ...). A ``UserPromptSubmit`` hook
cannot replace the prompt; it can only add context. So when TypoShift finds a
wrong-layout span it returns::

    {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                            "additionalContext": "<reconstruction note>"},
     "systemMessage": "<one-line notice for the user>"}

The original prompt is never modified. The hook always exits 0 and prints
nothing when there is nothing to add, so a failure here can never block the
user (unexpected errors are reported on stderr, which Claude Code shows only
in verbose mode).
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import IO, Any

HOOK_EVENT = "UserPromptSubmit"
MAX_SNIPPET = 4000


def _clip(text: str, limit: int = MAX_SNIPPET) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_context(result: Any) -> tuple[str, str] | None:
    """Return (additionalContext, systemMessage) for a FixResult, or None."""
    from ...confidence import format_confidence

    data = result.to_dict()
    applied, suggested = result.corrections, result.suggestions
    if not applied and not suggested:
        return None
    lines = ["[TypoShift] Part of this prompt looks like it was typed with the wrong keyboard layout.",
             "TypoShift rebuilt it by physical key position (no translation). The user's original prompt "
             "above is unchanged."]
    if applied:
        lines.append("")
        lines.append("High-confidence reconstruction:")
        for c in applied:
            lines.append(f"- {c.source_layout} → {c.target_layout} (confidence {format_confidence(c.confidence)}): "
                         f"{json.dumps(_clip(c.original, 500), ensure_ascii=False)} → "
                         f"{json.dumps(_clip(c.replacement, 500), ensure_ascii=False)}")
        lines.append("")
        lines.append("Reconstructed prompt:")
        lines.append(_clip(result.corrected))
        lines.append("")
        lines.append("Treat the reconstructed prompt as what the user meant. Do not ask the user to confirm this; "
                     "mention your interpretation briefly in your reply. If it clearly contradicts the "
                     "conversation, ask instead.")
    if suggested:
        lines.append("")
        lines.append("Uncertain reconstruction (do NOT act on it without asking the user):")
        for c in suggested:
            lines.append(f"- {c.source_layout} → {c.target_layout} (confidence {format_confidence(c.confidence)}): "
                         f"{json.dumps(_clip(c.original, 500), ensure_ascii=False)} → "
                         f"{json.dumps(_clip(c.replacement, 500), ensure_ascii=False)}")
        lines.append("If the original text is meaningful as typed, ignore this note. Otherwise ask the user "
                     "whether the reconstruction is what they meant before doing anything.")
    if data["requires_confirmation"]:
        lines.append("")
        lines.append("The reconstructed text asks for a potentially destructive or irreversible action. "
                     "Confirm the exact action with the user before running any command.")
    primary = result.primary
    shown = _clip(primary.replacement, 80).replace("\n", " ")
    verb = "read as" if applied else "possible reading (unconfirmed):"
    message = (f"TypoShift {verb} {json.dumps(shown, ensure_ascii=False)} "
               f"({primary.source_layout}→{primary.target_layout}, confidence {format_confidence(primary.confidence)})")
    return "\n".join(lines), message


def run(payload: dict[str, Any]) -> dict[str, Any] | None:
    from ...configuration import load_config
    from ...engine import Engine

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    stripped = prompt.lstrip()
    if stripped.startswith("/typoshift"):
        return None  # the skill handles explicit invocations itself
    cwd = payload.get("cwd")
    config = load_config(cwd=Path(cwd) if isinstance(cwd, str) and cwd else None)
    if not config.hook.enabled or config.mode in ("disabled", "manual"):
        return None  # manual mode never runs implicitly
    if len(prompt) > config.hook.max_prompt_chars:
        return None
    mode = "auto" if config.mode == "auto" else "suggest"
    result = Engine(config).fix(prompt, mode)
    built = build_context(result)
    if built is None:
        return None
    context, message = built
    output: dict[str, Any] = {"hookSpecificOutput": {"hookEventName": HOOK_EVENT, "additionalContext": context}}
    if config.hook.show_message:
        output["systemMessage"] = message
    return output


def main(stdin: IO[str] | None = None, stdout: IO[str] | None = None, stderr: IO[str] | None = None) -> int:
    if stdin is None:
        from ..._stdio import utf8_streams

        utf8_streams()  # Claude Code exchanges UTF-8 JSON on every platform
    stdin, stdout, stderr = stdin or sys.stdin, stdout or sys.stdout, stderr or sys.stderr
    try:
        raw = stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            return 0
        event = payload.get("hook_event_name", HOOK_EVENT)
        if event != HOOK_EVENT:
            return 0
        output = run(payload)
        if output is not None:
            stdout.write(json.dumps(output, ensure_ascii=False))
            stdout.write("\n")
    except Exception as exc:  # noqa: BLE001 - a hook must never block the user
        with contextlib.suppress(Exception):
            stderr.write(f"typoshift hook: {type(exc).__name__}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
