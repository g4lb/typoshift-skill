#!/usr/bin/env python3
"""Copy the packaged Claude Code skill to the repository-level locations.

The canonical skill lives in ``src/typoshift/integrations/claude_code/skill``
(it ships inside the wheel so ``typoshift install claude`` works from pip).
This script mirrors it to ``.claude/skills/typoshift`` (so the skill is active
when working on this repository) and ``integrations/claude-code`` (manual
installation). ``tests/test_project_files.py`` fails if the copies drift.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src" / "typoshift" / "integrations" / "claude_code" / "skill"
FILES = ("SKILL.md", "reference.md", "scripts/typoshift.py", "scripts/layouts.json", "scripts/common_words.json",
         "scripts/LICENSE-data.txt")
TARGETS = [
    ROOT / "skills" / "typoshift",  # Claude Code plugin (.claude-plugin/plugin.json) and skills.sh
    ROOT / ".claude" / "skills" / "typoshift",
    ROOT / "integrations" / "claude-code",
]

if __name__ == "__main__":
    for target in TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, target / name)
        print(f"synced {target.relative_to(ROOT)}")
