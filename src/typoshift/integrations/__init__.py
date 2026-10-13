"""Integrations with AI agents and editors.

Each integration lives in its own subpackage and depends only on the public
engine API (:class:`typoshift.engine.Engine`), never the other way round:

* ``claude_code`` - Claude Code skill, ``UserPromptSubmit`` hook and installer.

Planned integrations (Cursor, VS Code, a local HTTP service, an LSP server)
should follow the same pattern: a thin adapter that converts the host's
input into ``Engine.fix`` calls and the :class:`~typoshift.engine.FixResult`
into the host's output format. See ``docs/ARCHITECTURE.md``.
"""
