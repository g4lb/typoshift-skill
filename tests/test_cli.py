from __future__ import annotations

import io
import json
import subprocess
import sys

import pytest

from typoshift.cli import main

SPEC = "פךקשדק גקהקךםפ איק מקסא כקשאורק"


def run(capsys, *args: str, stdin: str | None = None, monkeypatch=None) -> tuple[int, str, str]:
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


def test_fix(capsys):
    code, out, _ = run(capsys, "fix", SPEC)
    assert code == 0
    assert out == "please develop the next feature\n"


def test_fix_json(capsys):
    code, out, _ = run(capsys, "fix", "--json", SPEC)
    data = json.loads(out)
    assert data["corrected"] == "please develop the next feature"
    assert data["source_layout"] == "he" and data["target_layout"] == "en-US"


def test_fix_verbose_reports_to_stderr(capsys):
    _, out, err = run(capsys, "fix", "--verbose", SPEC)
    assert out.strip() == "please develop the next feature"
    assert "applied" in err and "he → en-US" in err


def test_fix_stdin(capsys, monkeypatch):
    code, out, _ = run(capsys, "fix", "--stdin", stdin=SPEC + "\n", monkeypatch=monkeypatch)
    assert code == 0 and out == "please develop the next feature\n"


def test_fix_suggest_mode(capsys):
    _, out, _ = run(capsys, "fix", "--mode", "suggest", "--json", SPEC)
    data = json.loads(out)
    assert data["corrected"] == SPEC
    assert data["suggested_text"] == "please develop the next feature"


def test_fix_manual(capsys):
    _, out, _ = run(capsys, "fix", "--from", "en-US", "--to", "ru", "ghbdtn")
    assert out.strip() == "привет"
    code, _, err = run(capsys, "fix", "--from", "en-US", "ghbdtn")
    assert code == 2 and "--to" in err


def test_fix_unchanged_text(capsys):
    _, out, _ = run(capsys, "fix", "Please update src/components/Header.tsx")
    assert out.strip() == "Please update src/components/Header.tsx"


def test_detect_exit_codes(capsys):
    code, out, _ = run(capsys, "detect", "פךקשדק")
    assert code == 0 and "he → en-US" in out
    code, out, _ = run(capsys, "detect", "hello world")
    assert code == 1 and "no keyboard-layout mistake" in out
    code, out, _ = run(capsys, "detect", "--json", "ghbdtn rfr ltkf")
    data = json.loads(out)
    assert data["detected"] and data["suggestions"][0]["replacement"] == "привет как дела"


def test_convert(capsys):
    code, out, _ = run(capsys, "convert", "--from", "he", "--to", "en-US", "פךקשדק")
    assert code == 0 and out == "please\n"
    _, out, _ = run(capsys, "convert", "--from", "he", "--to", "en-US", "--json", "פךקשדק")
    assert json.loads(out)["converted"] == "please"


def test_convert_unknown_layout(capsys):
    code, _, err = run(capsys, "convert", "--from", "xx", "--to", "he", "a")
    assert code == 2 and "unknown layout" in err


def test_layouts(capsys):
    code, out, _ = run(capsys, "layouts")
    assert code == 0 and "he" in out and "Hebrew" in out
    _, out, _ = run(capsys, "layouts", "--json")
    rows = json.loads(out)
    assert len(rows) >= 20 and any(r["id"] == "en-US" and r["enabled"] for r in rows)


def test_config_show_path_init_set(capsys, tmp_path):
    code, out, _ = run(capsys, "config", "show")
    assert code == 0 and 'mode = "auto"' in out
    _, out, _ = run(capsys, "config", "path")
    assert "config.toml" in out
    code, out, _ = run(capsys, "config", "init", "--dry-run")
    assert code == 0 and "layouts" in out
    code, out, _ = run(capsys, "config", "init")
    assert code == 0
    code, _, err = run(capsys, "config", "init")
    assert code == 2 and "already exists" in err
    code, out, _ = run(capsys, "config", "set", "mode", "suggest")
    assert code == 0
    _, out, _ = run(capsys, "config", "show", "--json")
    assert json.loads(out)["config"]["mode"] == "suggest"
    code, _, err = run(capsys, "config", "set", "mode", "bogus")
    assert code == 2 and "mode must be one of" in err
    code, _, _ = run(capsys, "config", "set", "hook.enabled", "false")
    assert code == 0
    code, _, _ = run(capsys, "config", "set", "layouts", "en-US,he")
    _, out, _ = run(capsys, "config", "show", "--json")
    cfg = json.loads(out)["config"]
    assert cfg["layouts"] == ["en-US", "he"] and cfg["hook"]["enabled"] is False


def test_config_set_project(capsys):
    code, _, _ = run(capsys, "config", "set", "--project", "mode", "disabled")
    assert code == 0
    _, out, _ = run(capsys, "fix", SPEC)
    assert out.strip() == SPEC


def test_doctor(capsys):
    code, out, _ = run(capsys, "doctor", "--json")
    data = json.loads(out)
    names = {c["check"] for c in data["checks"]}
    assert {"python", "configuration", "layouts", "language models", "calibration", "engine"} <= names
    assert code == 0, data


def test_install_dry_run_and_uninstall(capsys, tmp_path):
    code, out, _ = run(capsys, "install", "claude", "--dry-run")
    assert code == 0 and "would" in out
    code, out, _ = run(capsys, "install", "claude")
    assert code == 0
    code, out, _ = run(capsys, "install", "claude", "--json")
    assert json.loads(out)["changed"] is False
    code, out, _ = run(capsys, "uninstall", "claude")
    assert code == 0 and "remove" in out


def test_install_unknown_integration(capsys):
    code, _, err = run(capsys, "install", "cursor")
    assert code == 2 and "unknown integration" in err


def test_no_command_prints_help(capsys):
    assert main([]) == 2


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_module_entry_point():
    proc = subprocess.run([sys.executable, "-m", "typoshift", "fix", SPEC], capture_output=True, text=True)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "please develop the next feature"


def test_config_set_types(capsys):
    assert run(capsys, "config", "set", "hook.enabled", "no")[0] == 0
    assert run(capsys, "config", "set", "hook.max_prompt_chars", "20k")[0] == 2
    assert run(capsys, "config", "set", "protection.extra_patterns", r"\d{1,3}x")[0] == 0
    assert run(capsys, "config", "set", "layout_languages.he", "he")[0] == 0
    _, out, _ = run(capsys, "config", "show", "--json")
    cfg = json.loads(out)["config"]
    assert cfg["hook"]["enabled"] is False
    assert cfg["protection"]["extra_patterns"] == [r"\d{1,3}x"]
    assert cfg["layout_languages"] == {"he": ["he"]}


def test_detect_agrees_with_fix(capsys):
    # Short span: confident but below min_auto_letters, so neither applies it.
    _, out, _ = run(capsys, "detect", "--json", "--layouts", "en-US,he", "nv")
    data = json.loads(out)
    _, fixed, _ = run(capsys, "fix", "--layouts", "en-US,he", "nv")
    for flag in data.get("would_auto_correct", []):
        assert flag == (fixed.strip() != "nv")
