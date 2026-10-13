"""Install and uninstall the TypoShift Claude Code integration.

What gets installed:

* **Skill** - ``SKILL.md`` and ``reference.md`` copied to
  ``<claude dir>/skills/typoshift/`` (user scope: ``~/.claude``; project scope:
  ``<project>/.claude``), plus a ``.typoshift-managed`` marker so uninstall
  never deletes a skill it did not create.
* **Hook** - one ``UserPromptSubmit`` command hook merged into
  ``~/.claude/settings.json`` (user scope) or
  ``<project>/.claude/settings.local.json`` (project scope; the command holds
  an absolute interpreter path, so it belongs in the personal, git-ignored
  file rather than the shared ``settings.json``).

Guarantees: existing settings and hooks are preserved, re-running is a no-op,
invalid JSON is never overwritten, the previous settings file is backed up
before every change, writes are atomic, and ``dry_run`` reports the plan
without touching anything.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from ... import __version__
from . import HOOK_ARGS, HOOK_MARKER

__all__ = ["InstallError", "Report", "install", "uninstall", "status", "hook_command", "paths"]

SKILL_NAME = "typoshift"
SKILL_FILES = ("SKILL.md", "reference.md")
MARKER = ".typoshift-managed"
EVENT = "UserPromptSubmit"
HOOK_TIMEOUT = 10  # seconds


class InstallError(RuntimeError):
    """Installation cannot proceed safely."""


@dataclass
class Report:
    scope: str
    dry_run: bool
    settings_path: Path
    skill_dir: Path
    actions: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(not a.startswith("unchanged") for a in self.actions)

    def to_dict(self) -> dict[str, Any]:
        return {"scope": self.scope, "dry_run": self.dry_run, "settings_path": str(self.settings_path),
                "skill_dir": str(self.skill_dir), "actions": self.actions, "changed": self.changed}


def claude_dir() -> Path:
    custom = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(custom).expanduser() if custom else Path.home() / ".claude"


def paths(scope: str, project_dir: Path | None = None) -> tuple[Path, Path]:
    """Return (settings file, skill directory) for a scope."""
    if scope == "user":
        base = claude_dir()
        return base / "settings.json", base / "skills" / SKILL_NAME
    if scope == "project":
        base = (project_dir or Path.cwd()).resolve() / ".claude"
        return base / "settings.local.json", base / "skills" / SKILL_NAME
    raise InstallError(f"unknown scope {scope!r} (use 'user' or 'project')")


def _quote(arg: str) -> str:
    """Double-quote a path for the hook command (works in POSIX shells and cmd.exe)."""
    if os.name == "nt":
        return f'"{arg}"'
    return '"' + re.sub(r'(["\\$`])', r"\\\1", arg) + '"'


def hook_command(python: str | None = None) -> str:
    exe = python or sys.executable
    return " ".join([_quote(exe), "-m", "typoshift", *HOOK_ARGS])


def _is_ours(handler: Any) -> bool:
    return isinstance(handler, dict) and HOOK_MARKER in str(handler.get("command", "")).replace('"', "")


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InstallError(f"{path} is not valid JSON ({exc}); fix it first, TypoShift will not overwrite it") \
            from None
    if not isinstance(data, dict):
        raise InstallError(f"{path} does not contain a JSON object; refusing to modify it")
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".typoshift.bak"))
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _skill_source() -> resources.abc.Traversable:
    return resources.files("typoshift.integrations.claude_code") / "skill"


def _merge_hook(settings: dict[str, Any], command: str) -> str:
    """Add or update our hook in ``settings``. Returns 'added', 'updated' or 'unchanged'."""
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallError("'hooks' in settings is not an object; refusing to modify it")
    groups = hooks.setdefault(EVENT, [])
    if not isinstance(groups, list):
        raise InstallError(f"'hooks.{EVENT}' in settings is not a list; refusing to modify it")
    found = False
    state = "unchanged"
    for group in groups:
        for handler in group.get("hooks", []) if isinstance(group, dict) else []:
            if _is_ours(handler):
                if found:
                    continue
                found = True
                desired = {"type": "command", "command": command, "timeout": HOOK_TIMEOUT}
                if any(handler.get(k) != v for k, v in desired.items()):
                    handler.update(desired)
                    state = "updated"
    if not found:
        groups.append({"hooks": [{"type": "command", "command": command, "timeout": HOOK_TIMEOUT}]})
        state = "added"
    return state


def _remove_hook(settings: dict[str, Any]) -> int:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict) or not isinstance(hooks.get(EVENT), list):
        return 0
    removed = 0
    kept_groups = []
    for group in hooks[EVENT]:
        if isinstance(group, dict) and isinstance(group.get("hooks"), list):
            kept = [h for h in group["hooks"] if not _is_ours(h)]
            removed += len(group["hooks"]) - len(kept)
            if not kept:
                continue
            group["hooks"] = kept
        kept_groups.append(group)
    if kept_groups:
        hooks[EVENT] = kept_groups
    else:
        del hooks[EVENT]
    if not hooks:
        del settings["hooks"]
    return removed


def install(scope: str = "user", *, project_dir: Path | None = None, hook: bool = True, skill: bool = True,
            dry_run: bool = False, force: bool = False, python: str | None = None) -> Report:
    settings_path, skill_dir = paths(scope, project_dir)
    report = Report(scope, dry_run, settings_path, skill_dir)
    if skill:
        marker = skill_dir / MARKER
        if skill_dir.exists() and not marker.exists() and not force:
            raise InstallError(f"{skill_dir} exists and was not created by TypoShift; use --force to replace it")
        source = _skill_source()
        current = {name: (skill_dir / name).read_text(encoding="utf-8") if (skill_dir / name).exists() else None
                   for name in SKILL_FILES}
        wanted = {name: (source / name).read_text(encoding="utf-8") for name in SKILL_FILES}
        if current == wanted and marker.exists():
            report.actions.append(f"unchanged skill {skill_dir}")
        else:
            report.actions.append(f"{'update' if skill_dir.exists() else 'create'} skill {skill_dir}")
            if not dry_run:
                skill_dir.mkdir(parents=True, exist_ok=True)
                for name, text in wanted.items():
                    (skill_dir / name).write_text(text, encoding="utf-8", newline="\n")
                marker.write_text(f"typoshift {__version__}\n", encoding="utf-8")
    if hook:
        settings = _load(settings_path)
        state = _merge_hook(settings, hook_command(python))
        if state == "unchanged":
            report.actions.append(f"unchanged hook in {settings_path}")
        else:
            report.actions.append(f"{'add' if state == 'added' else 'update'} {EVENT} hook in {settings_path}")
            if not dry_run:
                _write(settings_path, settings)
    return report


def uninstall(scope: str = "user", *, project_dir: Path | None = None, dry_run: bool = False) -> Report:
    settings_path, skill_dir = paths(scope, project_dir)
    report = Report(scope, dry_run, settings_path, skill_dir)
    if settings_path.exists():
        settings = _load(settings_path)
        removed = _remove_hook(settings)
        if removed:
            report.actions.append(f"remove {removed} TypoShift hook(s) from {settings_path}")
            if not dry_run:
                _write(settings_path, settings)
        else:
            report.actions.append(f"unchanged {settings_path} (no TypoShift hook)")
    if (skill_dir / MARKER).exists():
        report.actions.append(f"remove skill {skill_dir}")
        if not dry_run:
            shutil.rmtree(skill_dir)
    elif skill_dir.exists():
        report.actions.append(f"unchanged {skill_dir} (not managed by TypoShift)")
    return report


def status(scope: str = "user", project_dir: Path | None = None) -> dict[str, Any]:
    settings_path, skill_dir = paths(scope, project_dir)
    commands: list[str] = []
    error = None
    try:
        settings = _load(settings_path)
        for group in settings.get("hooks", {}).get(EVENT, []) or []:
            for handler in group.get("hooks", []) if isinstance(group, dict) else []:
                if _is_ours(handler):
                    commands.append(handler.get("command", ""))
    except InstallError as exc:
        error = str(exc)
    return {"scope": scope, "settings_path": str(settings_path), "hook_installed": bool(commands),
            "hook_commands": commands, "skill_installed": (skill_dir / "SKILL.md").exists(),
            "skill_managed": (skill_dir / MARKER).exists(), "skill_dir": str(skill_dir), "error": error}
