#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook for a TypoShift git checkout (no pip install).

This is also the hook the Claude Code plugin registers (hooks/hooks.json), so
the plugin works without pip: it runs the engine from the plugin's own copy of
``src/``. Point a hook at this file when you run TypoShift straight from a clone:

    {"type": "command", "command": "python3 \"/path/to/typoshift/integrations/claude-code/hooks/typoshift_hook.py\""}

With TypoShift installed via pip, prefer `typoshift install claude`, which
registers `python -m typoshift hook claude-code` instead.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.version_info < (3, 11):  # noqa: UP036 - the plugin runs whatever python3 is on PATH
    # e.g. an old system python3; stay silent rather than break the prompt
    print("typoshift hook: Python 3.11+ required; hook skipped", file=sys.stderr)
    raise SystemExit(0)

if os.environ.get("TYPOSHIFT_PLUGIN_HOOK", "1") == "0":
    raise SystemExit(0)

SRC = Path(__file__).resolve().parents[3] / "src"
if SRC.is_dir():
    sys.path.insert(0, str(SRC))

try:
    from typoshift.integrations.claude_code.hook import main
except Exception as exc:  # noqa: BLE001 - never block the user's prompt
    print(f"typoshift hook unavailable: {exc}", file=sys.stderr)
    raise SystemExit(0) from None

raise SystemExit(main())
