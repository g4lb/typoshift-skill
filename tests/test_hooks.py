"""Claude Code UserPromptSubmit hook: output contract and failure safety."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest

from typoshift.integrations.claude_code import hook

SPEC = "פךקשדק גקהקךםפ איק מקסא כקשאורק"


def call(payload) -> tuple[int, str, str]:
    raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    out, err = io.StringIO(), io.StringIO()
    code = hook.main(io.StringIO(raw), out, err)
    return code, out.getvalue(), err.getvalue()


def payload(prompt: str, **extra) -> dict:
    return {"session_id": "s", "transcript_path": "/tmp/t.jsonl", "cwd": os.getcwd(),
            "hook_event_name": "UserPromptSubmit", "prompt": prompt, **extra}


def test_high_confidence_correction_adds_context():
    code, out, _ = call(payload(SPEC))
    assert code == 0
    data = json.loads(out)
    hso = data["hookSpecificOutput"]
    assert hso["hookEventName"] == "UserPromptSubmit"
    ctx = hso["additionalContext"]
    assert "please develop the next feature" in ctx
    assert "High-confidence" in ctx and "unchanged" in ctx
    assert "TypoShift read as" in data["systemMessage"]
    # The hook never claims to replace the prompt and never blocks it.
    assert "decision" not in data
    assert "suppressOriginalPrompt" not in json.dumps(data)


def test_correct_prompt_produces_no_output():
    code, out, err = call(payload("Please update src/components/Header.tsx"))
    assert (code, out, err) == (0, "", "")


def test_uncertain_reconstruction_is_flagged(tmp_path, monkeypatch):
    cfg = tmp_path / "config" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("auto_threshold = 1.0\n", encoding="utf-8")
    code, out, _ = call(payload(SPEC))
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "do NOT act on it without asking" in ctx
    assert "possible reading" in json.loads(out)["systemMessage"]


def test_destructive_reconstruction_requires_confirmation():
    _, out, _ = call(payload("פךקשדק גקךקאק איק ךםע כןךקד"))
    assert "Confirm the exact action" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("raw", ["", "not json", "[]", "null", '{"prompt": 5}', '{"prompt": ""}',
                                 '{"hook_event_name": "PreToolUse", "prompt": "x"}'])
def test_garbage_input_never_fails(raw):
    code, out, _ = call(raw)
    assert code == 0 and out == ""


def test_internal_error_never_blocks(monkeypatch):
    def boom(_):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(hook, "run", boom)
    code, out, err = call(payload(SPEC))
    assert code == 0 and out == "" and "kaboom" in err


def test_disabled_by_config(tmp_path):
    cfg = tmp_path / "config" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    for text in ('mode = "disabled"\n', '[hook]\nenabled = false\n', 'mode = "manual"\n'):
        cfg.write_text(text, encoding="utf-8")
        assert call(payload(SPEC))[1] == ""


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("TYPOSHIFT_DISABLE", "1")
    assert call(payload(SPEC))[1] == ""


def test_project_config_from_payload_cwd(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".typoshift.toml").write_text('mode = "disabled"\n', encoding="utf-8")
    assert call(payload(SPEC, cwd=str(proj)))[1] == ""


def test_long_prompt_skipped(tmp_path):
    cfg = tmp_path / "config" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("[hook]\nmax_prompt_chars = 10\n", encoding="utf-8")
    assert call(payload(SPEC))[1] == ""


def test_skill_invocation_skipped():
    assert call(payload("/typoshift " + SPEC))[1] == ""


def test_system_message_can_be_hidden(tmp_path):
    cfg = tmp_path / "config" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("[hook]\nshow_message = false\n", encoding="utf-8")
    data = json.loads(call(payload(SPEC))[1])
    assert "systemMessage" not in data and "hookSpecificOutput" in data


def test_hook_subprocess_exit_zero_and_valid_json():
    proc = subprocess.run([sys.executable, "-m", "typoshift", "hook", "claude-code"],
                          input=json.dumps(payload(SPEC), ensure_ascii=False), capture_output=True,
                          text=True, encoding="utf-8")
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


def test_hook_subprocess_survives_broken_config(tmp_path):
    cfg = tmp_path / "broken.toml"
    cfg.write_text("this is = = not toml", encoding="utf-8")
    env = {**os.environ, "TYPOSHIFT_CONFIG": str(cfg)}
    proc = subprocess.run([sys.executable, "-m", "typoshift", "hook", "claude-code"],
                          input=json.dumps(payload(SPEC)), capture_output=True, text=True, env=env)
    assert proc.returncode == 0 and proc.stdout == ""
    assert "typoshift hook" in proc.stderr
