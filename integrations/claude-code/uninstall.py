#!/usr/bin/env python3
"""Uninstall the TypoShift Claude Code integration from a git checkout.

Equivalent to `typoshift uninstall claude` and accepts the same options:
--scope user|project, --project-dir PATH, --dry-run, --json.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from typoshift.cli import main  # noqa: E402

raise SystemExit(main(["uninstall", "claude", *sys.argv[1:]]))
