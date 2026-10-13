"""Repository-level consistency: skill copies, calibration provenance, benchmark sanity."""

from __future__ import annotations

import json
import subprocess
import sys

from conftest import ROOT

from typoshift.confidence import load_calibration
from typoshift.detection import FEATURES

PACKAGE_SKILL = ROOT / "src" / "typoshift" / "integrations" / "claude_code" / "skill"


def test_skill_copies_are_identical():
    for copy in (ROOT / "skills" / "typoshift", ROOT / ".claude" / "skills" / "typoshift",
                 ROOT / "integrations" / "claude-code"):
        for name in ("SKILL.md", "reference.md"):
            assert (copy / name).read_text(encoding="utf-8") == (PACKAGE_SKILL / name).read_text(encoding="utf-8"), \
                f"{copy / name} is out of sync; run tools/sync_skill.py"


def test_skill_frontmatter():
    text = (PACKAGE_SKILL / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---")[1]
    assert "name: typoshift" in head
    assert "description:" in head
    assert "$ARGUMENTS" in text


def test_calibration_is_fitted_and_documented():
    cal = load_calibration()
    assert cal is not None
    assert set(cal.weights) == set(FEATURES)
    meta = cal.metadata
    assert meta["tool"] == "tools/calibrate.py" and meta["samples"] >= 1000
    assert meta["metrics"]["heldout"]["ece"] < 0.05


def test_benchmark_results_published():
    data = json.loads((ROOT / "benchmarks" / "results" / "latest.json").read_text(encoding="utf-8"))
    assert data["overall"]["positive_inputs"] > 1000 and data["overall"]["negative_inputs"] > 1000


def test_quick_benchmark_guards_regressions():
    proc = subprocess.run([sys.executable, str(ROOT / "benchmarks" / "run_benchmark.py"), "--quick"],
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr
    overall = json.loads(proc.stdout[: proc.stdout.index("}\n") + 1])
    assert overall["false_positive_rate"] <= 0.02
    assert overall["precision"] >= 0.9


def test_plugin_manifests():
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    from typoshift import __version__

    assert plugin["name"] == "typoshift" and plugin["version"] == __version__
    assert market["plugins"][0]["version"] == __version__
    [handler] = hooks["hooks"]["UserPromptSubmit"][0]["hooks"]
    assert "${CLAUDE_PLUGIN_ROOT}/integrations/claude-code/hooks/typoshift_hook.py" in handler["command"]


def test_plugin_hook_script_runs_from_checkout():
    hook = ROOT / "integrations" / "claude-code" / "hooks" / "typoshift_hook.py"
    payload = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "פךקשדק גקהקךםפ איק מקסא כקשאורק"})
    proc = subprocess.run([sys.executable, str(hook)], input=payload, capture_output=True, text=True,
                          encoding="utf-8")
    assert proc.returncode == 0
    assert "please develop the next feature" in json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
