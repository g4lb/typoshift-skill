"""Installer and uninstaller must preserve unrelated configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from typoshift.integrations.claude_code.installer import InstallError, hook_command, install, status, uninstall

EXISTING = {
    "model": "opus",
    "permissions": {"allow": ["Bash(npm test)"]},
    "hooks": {
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo other-hook"}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "guard.sh"}]}],
    },
}


def claude_home() -> Path:
    return Path(os.environ["CLAUDE_CONFIG_DIR"])


def settings() -> dict:
    return json.loads((claude_home() / "settings.json").read_text(encoding="utf-8"))


def write_settings(data) -> None:
    claude_home().mkdir(parents=True, exist_ok=True)
    (claude_home() / "settings.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def ours(data: dict) -> list[dict]:
    return [h for g in data.get("hooks", {}).get("UserPromptSubmit", []) for h in g["hooks"]
            if "typoshift hook claude-code" in h["command"].replace('"', "")]


def test_fresh_install_creates_settings_and_skill():
    report = install("user")
    assert report.changed
    data = settings()
    [entry] = ours(data)
    assert entry["type"] == "command" and entry["timeout"] == 10
    skill = claude_home() / "skills" / "typoshift"
    assert (skill / "SKILL.md").read_text(encoding="utf-8").startswith("---\nname: typoshift")
    assert (skill / "reference.md").exists() and (skill / ".typoshift-managed").exists()
    st = status("user")
    assert st["hook_installed"] and st["skill_installed"] and st["skill_managed"]


def test_install_preserves_existing_settings_and_hooks():
    write_settings(EXISTING)
    install("user")
    data = settings()
    assert data["model"] == "opus"
    assert data["permissions"] == EXISTING["permissions"]
    assert data["hooks"]["PreToolUse"] == EXISTING["hooks"]["PreToolUse"]
    commands = [h["command"] for g in data["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
    assert "echo other-hook" in commands and len(ours(data)) == 1
    backup = claude_home() / "settings.json.typoshift.bak"
    assert json.loads(backup.read_text(encoding="utf-8")) == EXISTING


def test_install_is_idempotent():
    write_settings(EXISTING)
    install("user")
    first = (claude_home() / "settings.json").read_text(encoding="utf-8")
    report = install("user")
    assert not report.changed
    assert (claude_home() / "settings.json").read_text(encoding="utf-8") == first
    assert len(ours(settings())) == 1


def test_install_updates_stale_command():
    install("user", python="/old/python")
    report = install("user", python="/new/python")
    assert any(a.startswith("update UserPromptSubmit hook") for a in report.actions)
    [entry] = ours(settings())
    assert "/new/python" in entry["command"]


def test_uninstall_restores_previous_state():
    write_settings(EXISTING)
    install("user")
    uninstall("user")
    assert settings() == EXISTING
    assert not (claude_home() / "skills" / "typoshift").exists()


def test_uninstall_removes_empty_containers():
    install("user")
    uninstall("user")
    assert settings() == {}


def test_uninstall_when_nothing_installed():
    report = uninstall("user")
    assert not report.changed


def test_invalid_json_is_never_overwritten():
    claude_home().mkdir(parents=True)
    path = claude_home() / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(InstallError, match="not valid JSON"):
        install("user")
    assert path.read_text(encoding="utf-8") == "{ not json"


def test_non_object_hooks_rejected():
    write_settings({"hooks": []})
    with pytest.raises(InstallError):
        install("user")


def test_unmanaged_skill_is_not_replaced_or_removed():
    skill = claude_home() / "skills" / "typoshift"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("my own skill", encoding="utf-8")
    with pytest.raises(InstallError, match="--force"):
        install("user")
    uninstall("user")
    assert (skill / "SKILL.md").read_text(encoding="utf-8") == "my own skill"
    install("user", force=True)
    assert (skill / ".typoshift-managed").exists()


def test_dry_run_changes_nothing():
    write_settings(EXISTING)
    report = install("user", dry_run=True)
    assert report.changed and report.dry_run
    assert settings() == EXISTING
    assert not (claude_home() / "skills" / "typoshift").exists()
    install("user")
    before = (claude_home() / "settings.json").read_text(encoding="utf-8")
    uninstall("user", dry_run=True)
    assert (claude_home() / "settings.json").read_text(encoding="utf-8") == before


def test_project_scope_uses_local_settings(tmp_path):
    proj = tmp_path / "my project"
    proj.mkdir()
    install("project", project_dir=proj)
    local = proj / ".claude" / "settings.local.json"
    assert ours(json.loads(local.read_text(encoding="utf-8")))
    assert not (proj / ".claude" / "settings.json").exists()
    assert (proj / ".claude" / "skills" / "typoshift" / "SKILL.md").exists()
    uninstall("project", project_dir=proj)
    assert not ours(json.loads(local.read_text(encoding="utf-8")))


def test_skip_hook_or_skill():
    install("user", hook=False)
    assert not (claude_home() / "settings.json").exists()
    assert (claude_home() / "skills" / "typoshift" / "SKILL.md").exists()


def test_hook_command_quotes_paths_with_spaces():
    cmd = hook_command("/Users/me/My Tools/python3")
    assert cmd.startswith('"/Users/me/My Tools/python3"')
    assert cmd.endswith("-m typoshift hook claude-code")


def test_unknown_scope():
    with pytest.raises(InstallError):
        install("global")
