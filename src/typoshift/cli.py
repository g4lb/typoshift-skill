"""Command-line interface: ``typoshift``.

Exit codes:

* 0 - success (for ``detect``: a likely layout mistake was found)
* 1 - ``detect`` found no likely mistake; ``doctor`` found a problem
* 2 - usage error (bad arguments, unknown layout, invalid configuration)
* 3 - installation refused or failed (nothing was changed)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__
from ._stdio import utf8_streams

EXIT_OK, EXIT_NEGATIVE, EXIT_USAGE, EXIT_INSTALL = 0, 1, 2, 3


class UsageError(Exception):
    pass


# ---------------------------------------------------------------------------- helpers
def _read_text(args: argparse.Namespace) -> str:
    words = getattr(args, "text", None) or []
    if getattr(args, "stdin", False) or not words or words == ["-"]:
        if sys.stdin is None or (sys.stdin.isatty() and not getattr(args, "stdin", False)):
            raise UsageError("no text given (pass TEXT or pipe it on stdin)")
        text = sys.stdin.read()
        # A trailing newline from heredocs/pipes is not part of the text.
        return text[:-1] if text.endswith("\n") else text
    return " ".join(words)


def _print_json(data: Any) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _engine(args: argparse.Namespace):
    from .configuration import ConfigError, load_config
    from .engine import Engine

    overrides: dict[str, Any] = {}
    if getattr(args, "layouts", None):
        overrides["layouts"] = [x.strip() for x in args.layouts.split(",") if x.strip()]
    if getattr(args, "threshold", None) is not None:
        overrides["auto_threshold"] = args.threshold
        overrides["suggest_threshold"] = min(args.threshold, 0.5)
    try:
        config = load_config(overrides=overrides)
        return Engine(config)
    except (ConfigError, KeyError, ValueError) as exc:
        raise UsageError(str(exc).strip("'\"")) from None


def _describe(c: Any) -> str:
    from .confidence import format_confidence

    conf = format_confidence(c.confidence) if c.confidence is not None else "manual"
    return f"{c.source_layout} → {c.target_layout} [{conf}] {c.original!r} → {c.replacement!r}"


# ---------------------------------------------------------------------------- commands
def cmd_fix(args: argparse.Namespace) -> int:
    text = _read_text(args)
    engine = _engine(args)
    mode = args.mode or None
    if args.source or args.target:
        if not (args.source and args.target):
            raise UsageError("--from and --to must be given together")
        mode = "manual"
    try:
        result = engine.fix(text, mode, args.source, args.target)
    except (KeyError, ValueError) as exc:
        raise UsageError(str(exc).strip("'\"")) from None
    if args.json:
        _print_json(result.to_dict(verbose=args.verbose))
        return EXIT_OK
    out = result.suggested_text if result.mode == "suggest" else result.corrected
    sys.stdout.write(out + ("\n" if not out.endswith("\n") else ""))
    if args.verbose:
        for c in result.corrections:
            print(f"applied:   {_describe(c)}", file=sys.stderr)
        for c in result.suggestions:
            print(f"suggested: {_describe(c)}", file=sys.stderr)
        if not result.corrections and not result.suggestions:
            print("no keyboard-layout mistake detected", file=sys.stderr)
    return EXIT_OK


def cmd_detect(args: argparse.Namespace) -> int:
    text = _read_text(args)
    engine = _engine(args)
    result = engine.detect(text)
    found = bool(result.suggestions)
    if args.json:
        data = result.to_dict(verbose=args.verbose)
        data["detected"] = found
        if found:
            data["would_auto_correct"] = [c.auto_eligible for c in result.suggestions]
        _print_json(data)
    elif found:
        for c in result.suggestions:
            auto = "auto" if c.auto_eligible else "suggest"
            print(f"{_describe(c)} ({auto})")
            if c.equivalent_layouts:
                print(f"  equivalent layouts: {', '.join(c.equivalent_layouts)}")
    else:
        print("no keyboard-layout mistake detected")
    return EXIT_OK if found else EXIT_NEGATIVE


def cmd_convert(args: argparse.Namespace) -> int:
    from .layouts import LayoutRegistry

    text = _read_text(args)
    from .configuration import load_config

    registry = LayoutRegistry.load(load_config().resolved_layouts_dir())
    try:
        src, dst = registry.get(args.source), registry.get(args.target)
    except KeyError as exc:
        raise UsageError(str(exc).strip("'\"")) from None
    from .conversion import convert_text

    res = convert_text(text, src, dst)
    if args.json:
        _print_json({"original": text, "converted": res.text, "source_layout": src.id, "target_layout": dst.id,
                     "unmapped_keys": res.unmapped, "passthrough_chars": res.passthrough,
                     "method": "keyboard_layout_mapping"})
    else:
        sys.stdout.write(res.text + "\n")
    return EXIT_OK


def cmd_layouts(args: argparse.Namespace) -> int:
    from .configuration import load_config
    from .layouts import LayoutRegistry

    config = load_config()
    registry = LayoutRegistry.load(config.resolved_layouts_dir())
    enabled = set(config.layouts)
    rows = []
    for lay in registry:
        rows.append({"id": lay.id, "name": lay.name, "script": lay.script, "languages": list(lay.languages),
                     "enabled": lay.id in enabled, "origin": lay.origin, "keys": len(lay.keys),
                     "source": lay.source.get("symbols", "")})
    if args.json:
        _print_json(rows)
        return EXIT_OK
    print(f"{'':2}{'ID':7} {'LAYOUT':30} {'SCRIPT':9} {'LANG':6} SOURCE")
    for r in rows:
        mark = "* " if r["enabled"] else "  "
        print(f"{mark}{r['id']:7} {r['name']:30} {r['script']:9} {','.join(r['languages']):6} "
              f"{r['source'] or r['origin']}")
    print("\n* = enabled for detection (typoshift config set layouts ...)")
    return EXIT_OK


def cmd_config(args: argparse.Namespace) -> int:
    from .configuration import Config, ConfigError, dumps_toml, load_config, project_config_path, user_config_path

    action = args.config_action or "show"
    if action == "path":
        print(f"user:    {user_config_path()}")
        proj = project_config_path()
        print(f"project: {proj if proj else '(none; create .typoshift.toml)'}")
        return EXIT_OK
    if action == "show":
        try:
            config = load_config()
        except ConfigError as exc:
            raise UsageError(str(exc)) from None
        shown = config.to_dict()
        if args.json:
            _print_json({"config": shown, "sources": config.sources})
        else:
            sys.stdout.write(dumps_toml(shown))
            print(f"# sources: {', '.join(config.sources) or 'built-in defaults'}")
        return EXIT_OK

    target = Path(".typoshift.toml") if args.project else user_config_path()
    if action == "init":
        if target.exists() and not args.force:
            raise UsageError(f"{target} already exists (use --force to overwrite)")
        config = Config()
        if args.detect:
            from .system_layouts import detect_system_layouts

            found = detect_system_layouts()
            if len(found) >= 2:
                config.layouts = found
            elif found:
                config.layouts = list(dict.fromkeys(found + ["en-US"]))
        text = ("# TypoShift configuration - see `typoshift config show` and docs/CONFIGURATION.md\n"
                + dumps_toml(config.to_dict()))
        if args.dry_run:
            sys.stdout.write(text)
            print(f"# (dry run; would write {target})", file=sys.stderr)
            return EXIT_OK
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target}")
        return EXIT_OK
    if action == "set":
        import tomllib

        data: dict[str, Any] = {}
        if target.exists():
            data = tomllib.loads(target.read_text(encoding="utf-8"))
        key, raw = args.key, args.value
        if key is None or raw is None:
            raise UsageError("usage: typoshift config set KEY VALUE")
        value = _parse_setting(key, raw)
        section, _, name = key.rpartition(".")
        if section:
            data.setdefault(section, {})[name] = value
        else:
            data[name] = value
        try:  # validate before writing
            load_config(use_files=False, overrides=data)
        except (ConfigError, TypeError) as exc:
            raise UsageError(str(exc)) from None
        text = dumps_toml(data)
        if args.dry_run:
            sys.stdout.write(text)
            return EXIT_OK
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"set {key} = {value!r} in {target}")
        return EXIT_OK
    raise UsageError(f"unknown config action {action!r}")


_BOOL = {"true": True, "yes": True, "on": True, "1": True, "false": False, "no": False, "off": False, "0": False}
_INT_KEYS = {"min_letters", "min_auto_letters", "hook.max_prompt_chars"}
_FLOAT_KEYS = {"auto_threshold", "suggest_threshold"}
_BOOL_KEYS = {"confirm_destructive", "same_script_auto", "hook.enabled", "hook.show_message"}
_ID_LIST_KEYS = {"layouts", "protection.disabled_rules"}


def _parse_setting(key: str, raw: str) -> Any:
    """Convert a `config set` value to the setting's type."""
    if key in _BOOL_KEYS:
        if raw.lower() not in _BOOL:
            raise UsageError(f"{key} must be true or false")
        return _BOOL[raw.lower()]
    if key in _INT_KEYS:
        try:
            return int(raw)
        except ValueError:
            raise UsageError(f"{key} must be an integer") from None
    if key in _FLOAT_KEYS:
        try:
            return float(raw)
        except ValueError:
            raise UsageError(f"{key} must be a number") from None
    if key in _ID_LIST_KEYS or key.startswith("layout_languages."):
        return [v.strip() for v in raw.split(",") if v.strip()]
    if key == "protection.extra_patterns":
        # Regexes may contain commas, so a list must be given as a JSON array.
        if raw.lstrip().startswith("["):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise UsageError(f"{key}: invalid JSON list: {exc}") from None
            return value
        return [raw]
    return raw


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: list[dict[str, Any]] = []

    def check(name: str, fn) -> Any:
        try:
            detail = fn()
            checks.append({"check": name, "ok": True, "detail": detail})
            return detail
        except Exception as exc:  # noqa: BLE001 - doctor reports every failure
            checks.append({"check": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"})
            return None

    check("python", lambda: f"{sys.version.split()[0]} ({sys.executable})"
          if sys.version_info >= (3, 11) else (_ for _ in ()).throw(RuntimeError("Python 3.11+ required")))
    from .configuration import load_config

    config = check("configuration", lambda: load_config())
    if config is not None:
        checks[-1]["detail"] = f"mode={config.mode}, layouts={','.join(config.layouts)}, " \
                               f"sources={','.join(config.sources) or 'defaults'}"

    def layouts():
        from .layouts import LayoutRegistry

        reg = LayoutRegistry.load(config.resolved_layouts_dir() if config else None)
        return f"{len(reg)} layouts available"

    check("layouts", layouts)

    def languages():
        from .langmodel import available_languages, load_language

        langs = available_languages()
        for lang in langs:
            load_language(lang)
        return f"{len(langs)} language models: {', '.join(langs)}"

    check("language models", languages)

    def calibration():
        from .confidence import load_calibration

        cal = load_calibration()
        if cal is None:
            raise RuntimeError("calibration data missing; automatic correction is disabled")
        return f"calibrated {cal.metadata.get('generated', '?')}, held-out ECE " \
               f"{cal.metadata.get('metrics', {}).get('heldout', {}).get('ece', '?')}"

    check("calibration", calibration)

    def engine_selftest():
        from .configuration import Config
        from .engine import Engine

        engine = Engine(Config(layouts=["en-US", "he"]))
        t0 = time.perf_counter()
        result = engine.fix("פךקשדק גקהקךםפ איק מקסא כקשאורק", "auto")
        ms = (time.perf_counter() - t0) * 1000
        if result.corrected != "please develop the next feature":
            raise RuntimeError(f"self-test produced {result.corrected!r}")
        return f"he→en-US self-test passed in {ms:.1f} ms"

    check("engine", engine_selftest)

    def system():
        from .system_layouts import detect_system_layouts

        found = detect_system_layouts()
        if not found:
            return "could not detect OS keyboard layouts (optional)"
        hint = "" if config is None or set(found) <= set(config.layouts) else \
            f"; consider: typoshift config set layouts {','.join(found)}"
        return f"OS layouts: {', '.join(found)}{hint}"

    check("system layouts", system)

    def claude():
        from .integrations.claude_code.installer import status

        parts = []
        for scope in ("user", "project"):
            st = status(scope)
            if st["error"]:
                raise RuntimeError(st["error"])
            parts.append(f"{scope}: hook={'yes' if st['hook_installed'] else 'no'}, "
                         f"skill={'yes' if st['skill_installed'] else 'no'}")
        return "; ".join(parts)

    check("claude code", claude)
    ok = all(c["ok"] for c in checks)
    if args.json:
        _print_json({"ok": ok, "checks": checks})
    else:
        for c in checks:
            print(f"[{'ok' if c['ok'] else 'FAIL'}] {c['check']}: {c['detail']}")
    return EXIT_OK if ok else EXIT_NEGATIVE


def _integration(args: argparse.Namespace) -> None:
    if args.integration not in ("claude", "claude-code"):
        raise UsageError(f"unknown integration {args.integration!r} (supported: claude)")


def cmd_install(args: argparse.Namespace) -> int:
    from .integrations.claude_code.installer import InstallError, install

    _integration(args)
    try:
        report = install(args.scope, project_dir=Path(args.project_dir) if args.project_dir else None,
                         hook=not args.no_hook, skill=not args.no_skill, dry_run=args.dry_run, force=args.force)
    except InstallError as exc:
        print(f"typoshift: {exc}", file=sys.stderr)
        return EXIT_INSTALL
    if args.json:
        _print_json(report.to_dict())
    else:
        prefix = "would " if args.dry_run else ""
        for action in report.actions:
            print(f"{prefix}{action}")
        if not args.dry_run and report.changed:
            print("Restart Claude Code to load the changes. Try: /typoshift פךקשדק")
    return EXIT_OK


def cmd_uninstall(args: argparse.Namespace) -> int:
    from .integrations.claude_code.installer import InstallError, uninstall

    _integration(args)
    try:
        report = uninstall(args.scope, project_dir=Path(args.project_dir) if args.project_dir else None,
                           dry_run=args.dry_run)
    except InstallError as exc:
        print(f"typoshift: {exc}", file=sys.stderr)
        return EXIT_INSTALL
    if args.json:
        _print_json(report.to_dict())
    else:
        prefix = "would " if args.dry_run else ""
        for action in report.actions or ["nothing to uninstall"]:
            print(f"{prefix}{action}")
    return EXIT_OK


def cmd_hook(args: argparse.Namespace) -> int:
    if args.integration not in ("claude-code", "claude"):
        raise UsageError(f"unknown hook {args.integration!r} (supported: claude-code)")
    from .integrations.claude_code.hook import main as hook_main

    return hook_main()


# ---------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="typoshift", description="Type in the wrong language. Get the right words. "
                                "Detects and reconstructs keyboard-layout mistakes by physical key position.")
    p.add_argument("--version", action="version", version=f"typoshift {__version__}")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    def text_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("text", nargs="*", help="text to process (default: read stdin)")
        sp.add_argument("--stdin", action="store_true", help="read the text from stdin")
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        sp.add_argument("--verbose", "-v", action="store_true", help="explain decisions (features, alternatives)")

    def engine_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--layouts", help="comma-separated layout ids to consider (overrides config)")
        sp.add_argument("--threshold", type=float, help="auto-correction confidence threshold (0-1)")

    sp = sub.add_parser("fix", help="correct wrong-layout text (prints the corrected text)")
    text_args(sp)
    engine_args(sp)
    sp.add_argument("--mode", choices=["auto", "suggest", "disabled"], help="override the configured mode")
    sp.add_argument("--from", dest="source", help="manual mode: layout the text was typed on")
    sp.add_argument("--to", dest="target", help="manual mode: layout the user meant")
    sp.set_defaults(func=cmd_fix)

    sp = sub.add_parser("detect", help="report likely layout mistakes without changing anything")
    text_args(sp)
    engine_args(sp)
    sp.set_defaults(func=cmd_detect)

    sp = sub.add_parser("convert", help="convert text between two layouts (no detection, no protection)")
    sp.add_argument("text", nargs="*")
    sp.add_argument("--stdin", action="store_true")
    sp.add_argument("--from", dest="source", required=True, help="layout the text was typed on")
    sp.add_argument("--to", dest="target", required=True, help="layout the user meant")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_convert)

    sp = sub.add_parser("layouts", help="list available keyboard layouts")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_layouts)

    sp = sub.add_parser("config", help="show or change configuration")
    sp.set_defaults(func=cmd_config, config_action="show", json=False, project=False, detect=False, force=False,
                    dry_run=False, key=None, value=None)
    csub = sp.add_subparsers(dest="config_action", metavar="ACTION")
    c = csub.add_parser("show", help="print the effective configuration (default)")
    c.add_argument("--json", action="store_true")
    csub.add_parser("path", help="print configuration file locations")
    c = csub.add_parser("init", help="write a starter configuration file")
    c.add_argument("--project", action="store_true", help="write ./.typoshift.toml instead of the user file")
    c.add_argument("--detect", action="store_true", help="use the layouts enabled in the OS")
    c.add_argument("--force", action="store_true", help="overwrite an existing file")
    c.add_argument("--dry-run", action="store_true", help="print the file instead of writing it")
    c = csub.add_parser("set", help="change one setting")
    c.add_argument("key", help="setting, e.g. mode, layouts, auto_threshold, hook.enabled")
    c.add_argument("value", help="value (layout lists are comma-separated; regex lists use JSON)")
    c.add_argument("--project", action="store_true", help="write ./.typoshift.toml instead of the user file")
    c.add_argument("--dry-run", action="store_true", help="print the file instead of writing it")

    sp = sub.add_parser("doctor", help="check the installation and environment")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_doctor)

    for name, func, helptext in (("install", cmd_install, "install an integration (claude)"),
                                 ("uninstall", cmd_uninstall, "remove an integration (claude)")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("integration", help="integration name: claude")
        sp.add_argument("--scope", choices=["user", "project"], default="user",
                        help="user: ~/.claude (default); project: ./.claude")
        sp.add_argument("--project-dir", help="project root for --scope project (default: current directory)")
        sp.add_argument("--dry-run", action="store_true", help="show what would change without changing it")
        sp.add_argument("--json", action="store_true")
        if name == "install":
            sp.add_argument("--no-hook", action="store_true", help="install only the skill")
            sp.add_argument("--no-skill", action="store_true", help="install only the hook")
            sp.add_argument("--force", action="store_true", help="replace an existing skill not created by TypoShift")
        sp.set_defaults(func=func)

    sp = sub.add_parser("hook", help="run an integration hook (reads the host's JSON on stdin)")
    sp.add_argument("integration", help="claude-code")
    sp.set_defaults(func=cmd_hook)
    return p


def main(argv: list[str] | None = None) -> int:
    utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        return args.func(args)
    except UsageError as exc:
        print(f"typoshift: error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except BrokenPipeError:  # pragma: no cover - e.g. piping into `head`
        return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
