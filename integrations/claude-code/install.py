#!/usr/bin/env python3
"""Install the TypoShift Claude Code integration from a git checkout.

Equivalent to `typoshift install claude` and accepts the same options:
--scope user|project, --project-dir PATH, --dry-run, --json, --no-hook,
--no-skill, --force.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from typoshift.cli import main  # noqa: E402

raise SystemExit(main(["install", "claude", *sys.argv[1:]]))
