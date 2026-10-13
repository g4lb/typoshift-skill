#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook for a TypoShift git checkout (no pip install).

Point a hook at this file when you run TypoShift straight from a clone:

    {"type": "command", "command": "python3 \"/path/to/typoshift/integrations/claude-code/hooks/typoshift_hook.py\""}

With TypoShift installed via pip, prefer `typoshift install claude`, which
registers `python -m typoshift hook claude-code` instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src"
if SRC.is_dir():
    sys.path.insert(0, str(SRC))

try:
    from typoshift.integrations.claude_code.hook import main
except Exception as exc:  # noqa: BLE001 - never block the user's prompt
    print(f"typoshift hook unavailable: {exc}", file=sys.stderr)
    raise SystemExit(0) from None

raise SystemExit(main())
