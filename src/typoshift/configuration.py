"""TypoShift configuration.

Configuration is layered (later layers win):

1. built-in defaults;
2. the user file: ``$TYPOSHIFT_CONFIG`` if set, otherwise
   ``%APPDATA%\\typoshift\\config.toml`` on Windows or
   ``$XDG_CONFIG_HOME/typoshift/config.toml`` (default ``~/.config``) elsewhere;
3. the nearest ``.typoshift.toml`` in the working directory or its parents;
4. environment variables ``TYPOSHIFT_MODE`` and ``TYPOSHIFT_DISABLE=1``.
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

__all__ = ["Config", "ConfigError", "MODES", "load_config", "user_config_path", "project_config_path", "dumps_toml"]

MODES = ("auto", "suggest", "manual", "disabled")
DEFAULT_LAYOUTS = ["en-US", "he", "ru", "uk", "ar", "el"]
PROJECT_FILE = ".typoshift.toml"


class ConfigError(ValueError):
    """Invalid configuration value or file."""


@dataclass
class ProtectionSettings:
    disabled_rules: list[str] = field(default_factory=list)
    extra_patterns: list[str] = field(default_factory=list)


@dataclass
class HookSettings:
    enabled: bool = True
    max_prompt_chars: int = 20_000
    show_message: bool = True


@dataclass
class Config:
    mode: str = "auto"
    layouts: list[str] = field(default_factory=lambda: list(DEFAULT_LAYOUTS))
    auto_threshold: float = 0.90
    suggest_threshold: float = 0.50
    min_letters: int = 2
    min_auto_letters: int = 4
    manual_source: str | None = None
    manual_target: str | None = None
    confirm_destructive: bool = True
    # Corrections between two layouts of the same script (AZERTY/QWERTY,
    # Russian/Ukrainian) are less reliable; by default they are only suggested.
    same_script_auto: bool = False
    layouts_dir: str | None = None
    layout_languages: dict[str, list[str]] = field(default_factory=dict)
    protection: ProtectionSettings = field(default_factory=ProtectionSettings)
    hook: HookSettings = field(default_factory=HookSettings)
    sources: list[str] = field(default_factory=list, compare=False)

    def __post_init__(self) -> None:
        if isinstance(self.protection, dict):
            self.protection = ProtectionSettings(**self.protection)
        if isinstance(self.hook, dict):
            self.hook = HookSettings(**self.hook)

    def validate(self) -> Config:
        def need(cond: bool, message: str) -> None:
            if not cond:
                raise ConfigError(message)

        def str_list(value: Any) -> bool:
            return isinstance(value, list) and all(isinstance(v, str) for v in value)

        def integer(value: Any) -> bool:
            return isinstance(value, int) and not isinstance(value, bool)

        need(isinstance(self.mode, str), f"mode must be a string; got {self.mode!r}")
        need(str_list(self.layouts), f"layouts must be a list of layout ids; got {self.layouts!r}")
        need(integer(self.min_letters), f"min_letters must be an integer; got {self.min_letters!r}")
        need(integer(self.min_auto_letters), f"min_auto_letters must be an integer; got {self.min_auto_letters!r}")
        for name in ("confirm_destructive", "same_script_auto"):
            need(isinstance(getattr(self, name), bool), f"{name} must be true or false; got {getattr(self, name)!r}")
        need(self.layouts_dir is None or isinstance(self.layouts_dir, str), "layouts_dir must be a string path")
        for name in ("manual_source", "manual_target"):
            need(getattr(self, name) is None or isinstance(getattr(self, name), str), f"{name} must be a layout id")
        need(isinstance(self.layout_languages, dict) and all(
            isinstance(k, str) and str_list(v) for k, v in self.layout_languages.items()),
            "layout_languages must map layout ids to lists of language codes")
        need(str_list(self.protection.extra_patterns), "protection.extra_patterns must be a list of regexes")
        need(str_list(self.protection.disabled_rules), "protection.disabled_rules must be a list of rule names")
        for pattern in self.protection.extra_patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError(f"protection.extra_patterns: invalid regex {pattern!r}: {exc}") from None
        for name in ("enabled", "show_message"):
            need(isinstance(getattr(self.hook, name), bool), f"hook.{name} must be true or false")
        need(integer(self.hook.max_prompt_chars) and self.hook.max_prompt_chars > 0,
             "hook.max_prompt_chars must be a positive integer")
        if self.mode not in MODES:
            raise ConfigError(f"mode must be one of {', '.join(MODES)}; got {self.mode!r}")
        for name in ("auto_threshold", "suggest_threshold"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
                raise ConfigError(f"{name} must be a number between 0 and 1; got {value!r}")
        if self.suggest_threshold > self.auto_threshold:
            raise ConfigError("suggest_threshold must not exceed auto_threshold")
        if not isinstance(self.layouts, list) or len(self.layouts) < 2:
            raise ConfigError("layouts must list at least two layout ids")
        if self.min_letters < 1:
            raise ConfigError("min_letters must be >= 1")
        if self.min_auto_letters < self.min_letters:
            raise ConfigError("min_auto_letters must be >= min_letters")
        return self

    def resolved_layouts_dir(self) -> Path:
        if self.layouts_dir:
            return Path(self.layouts_dir).expanduser()
        return user_config_path().parent / "layouts"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("sources")
        return {k: v for k, v in data.items() if v is not None}


def user_config_path() -> Path:
    explicit = os.environ.get("TYPOSHIFT_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "typoshift" / "config.toml"


def project_config_path(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    home = Path.home().resolve()
    for directory in (current, *current.parents):
        candidate = directory / PROJECT_FILE
        if candidate.is_file():
            return candidate
        if directory == home:
            break
    return None


def _apply(config: Config, data: dict[str, Any], origin: str) -> None:
    known = {f.name: f for f in fields(Config) if f.name != "sources"}
    for key, value in data.items():
        if key not in known:
            raise ConfigError(f"{origin}: unknown setting {key!r}")
        if key == "protection":
            if not isinstance(value, dict):
                raise ConfigError(f"{origin}: [protection] must be a table")
            for k, v in value.items():
                if not hasattr(config.protection, k):
                    raise ConfigError(f"{origin}: unknown setting protection.{k}")
                setattr(config.protection, k, v)
        elif key == "hook":
            if not isinstance(value, dict):
                raise ConfigError(f"{origin}: [hook] must be a table")
            for k, v in value.items():
                if not hasattr(config.hook, k):
                    raise ConfigError(f"{origin}: unknown setting hook.{k}")
                setattr(config.hook, k, v)
        elif key == "layout_languages":
            if not isinstance(value, dict):
                raise ConfigError(f"{origin}: layout_languages must be a table")
            config.layout_languages.update(value)
        else:
            setattr(config, key, value)


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from None


def load_config(*, cwd: Path | None = None, use_files: bool = True, overrides: dict[str, Any] | None = None) -> Config:
    config = Config()
    if use_files:
        user = user_config_path()
        if user.is_file():
            _apply(config, _read(user), str(user))
            config.sources.append(str(user))
        project = project_config_path(cwd)
        if project is not None:
            _apply(config, _read(project), str(project))
            config.sources.append(str(project))
    env_mode = os.environ.get("TYPOSHIFT_MODE")
    if env_mode:
        config.mode = env_mode
        config.sources.append("env:TYPOSHIFT_MODE")
    if os.environ.get("TYPOSHIFT_DISABLE", "").strip().lower() in ("1", "true", "yes", "on"):
        config.mode = "disabled"
        config.sources.append("env:TYPOSHIFT_DISABLE")
    if overrides:
        _apply(config, overrides, "overrides")
    return config.validate()


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"cannot serialize {type(value).__name__} to TOML")


def dumps_toml(data: dict[str, Any]) -> str:
    """Serialize a flat-or-one-level-nested mapping to TOML."""
    lines: list[str] = []
    tables: list[tuple[str, dict[str, Any]]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            tables.append((key, value))
        elif value is not None:
            lines.append(f"{key} = {_toml_value(value)}")
    for name, table in tables:
        lines.append("")
        lines.append(f"[{name}]")
        for key, value in table.items():
            if value is not None:
                k = key if key.replace("-", "").replace("_", "").isalnum() else _toml_value(key)
                lines.append(f"{k} = {_toml_value(value)}")
    return "\n".join(lines).lstrip("\n") + "\n"
