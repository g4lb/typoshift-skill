from __future__ import annotations

from pathlib import Path

import pytest

from typoshift.configuration import DEFAULT_LAYOUTS, Config
from typoshift.engine import Engine
from typoshift.layouts import builtin_registry

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Never read or write the developer's real configuration or Claude settings."""
    monkeypatch.setenv("TYPOSHIFT_CONFIG", str(tmp_path / "config" / "config.toml"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    monkeypatch.delenv("TYPOSHIFT_MODE", raising=False)
    monkeypatch.delenv("TYPOSHIFT_DISABLE", raising=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    from typoshift import engine as engine_module

    engine_module._default_engine.cache_clear()
    yield


@pytest.fixture(scope="session")
def registry():
    return builtin_registry()


@pytest.fixture(scope="session")
def engine():
    return Engine(Config(layouts=list(DEFAULT_LAYOUTS)), registry=builtin_registry())


@pytest.fixture(scope="session")
def make_engine():
    cache: dict[tuple, Engine] = {}

    def factory(*layouts: str, **kwargs) -> Engine:
        key = (layouts, repr(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = Engine(Config(layouts=list(layouts), **kwargs), registry=builtin_registry())
        return cache[key]

    return factory
