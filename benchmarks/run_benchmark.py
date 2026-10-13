#!/usr/bin/env python3
"""Evaluate TypoShift on the hand-written corpus in ``benchmarks/corpus``.

The corpus is independent of the frequency lists used to train and calibrate
the models. Wrong-layout inputs are produced by replaying each intended
sentence's physical keystrokes on another layout, which is exactly how the
mistake happens in practice.

Outcomes per input (automatic mode):

* positive inputs: ``exact`` (output == intended), ``wrong`` (changed, but not
  to the intended text) or ``missed`` (unchanged);
* negative inputs: ``untouched`` or ``false_positive`` (any change).

Usage::

    python benchmarks/run_benchmark.py [--quick] [--no-write]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from typoshift import __version__  # noqa: E402
from typoshift.configuration import DEFAULT_LAYOUTS, Config  # noqa: E402
from typoshift.conversion import convert_text  # noqa: E402
from typoshift.engine import Engine  # noqa: E402
from typoshift.layouts import builtin_registry  # noqa: E402

CORPUS = ROOT / "benchmarks" / "corpus"
RESULTS = ROOT / "benchmarks" / "results"

NATIVE = {"en": "en-US", "he": "he", "ru": "ru", "uk": "uk", "ar": "ar", "el": "el", "fr": "fr", "de": "de",
          "es": "es", "it": "it", "pt": "pt", "tr": "tr", "pl": "pl", "cs": "cs", "sv": "sv", "no": "no",
          "da": "da", "nl": "nl"}
NON_LATIN = ["he", "ru", "uk", "ar", "el"]
LATIN_OTHER = ["fr", "de", "es", "it", "pt", "tr", "pl", "cs", "sv", "no", "da", "nl"]


def lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def build_cases(quick: bool) -> list[dict]:
    reg = builtin_registry()
    rng = random.Random(2026)
    intended = {lang: lines(CORPUS / "intended" / f"{lang}.txt") for lang in NATIVE}
    if quick:
        intended = {k: v[:15] for k, v in intended.items()}
    cases: list[dict] = []

    def typed(text: str, lang: str, layout: str) -> str:
        return convert_text(text, reg.get(NATIVE[lang]), reg.get(layout)).text

    def add(group: str, config: str, layouts: list[str], wrong: str, intended: str) -> None:
        if wrong != intended:  # identical on both layouts: not a mistake at all
            cases.append({"group": group, "config": config, "layouts": layouts, "input": wrong,
                          "expected": intended})

    default = list(DEFAULT_LAYOUTS)
    # Whole prompt typed on the wrong layout.
    for lay in NON_LATIN:
        for s in intended["en"]:
            for cfg_name, cfg in (("default", default), ("pair", ["en-US", lay])):
                add(f"full en->{lay}", cfg_name, cfg, typed(s, "en", lay), s)
        for s in intended[lay]:
            for cfg_name, cfg in (("default", default), ("pair", [lay, "en-US"])):
                add(f"full {lay}->en-US", cfg_name, cfg, typed(s, lay, "en-US"), s)
    for lang in LATIN_OTHER:
        pair = [NATIVE[lang], "en-US"]
        for s in intended[lang]:
            add("full latin<->latin", "pair", pair, typed(s, lang, "en-US"), s)
        for s in intended["en"][:30 if not quick else 5]:
            add("full latin<->latin", "pair", pair, typed(s, "en", NATIVE[lang]), s)
    # Only a fragment typed on the wrong layout.
    for lang, wrong_layouts in (("en", ["he", "ru", "ar"]), ("he", ["en-US"]), ("ru", ["en-US"])):
        for s in intended[lang]:
            words = s.split(" ")
            if len(words) < 4:
                continue
            lay = rng.choice(wrong_layouts)
            k = rng.randint(1, min(3, len(words) - 2))
            i = rng.randrange(0, len(words) - k + 1)
            frag = " ".join(words[i : i + k])
            wrong = typed(frag, lang, lay)
            if wrong == frag:
                continue
            text = " ".join(words[:i] + [wrong] + words[i + k :])
            layouts = list(dict.fromkeys(default + [NATIVE[lang], lay]))
            cases.append({"group": f"mixed {lang} (fragment on {lay})", "config": "default", "layouts": layouts,
                          "input": text, "expected": s})
    # Negatives: correctly typed text must stay unchanged.
    for name in ("technical", "multilingual", "short_ambiguous"):
        for s in lines(CORPUS / "negatives" / f"{name}.txt")[: 15 if quick else None]:
            cases.append({"group": f"negative {name}", "config": "default", "layouts": default,
                          "input": s, "expected": s})
    for lang, sents in intended.items():
        for s in sents:
            cases.append({"group": "negative native sentences", "config": "default", "layouts": default,
                          "input": s, "expected": s})
            if lang in LATIN_OTHER:
                cases.append({"group": "negative native sentences", "config": "pair",
                              "layouts": [NATIVE[lang], "en-US"], "input": s, "expected": s})
    return cases


def run(cases: list[dict]) -> tuple[dict, list[dict], list[float]]:
    engines: dict[tuple[str, ...], Engine] = {}
    per_group: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    failures: list[dict] = []
    latencies: list[float] = []
    for case in cases:
        key = tuple(case["layouts"])
        if key not in engines:
            engines[key] = Engine(Config(layouts=list(key)), registry=builtin_registry())
            engines[key].fix("warm up")
        engine = engines[key]
        t0 = time.perf_counter()
        result = engine.fix(case["input"], "auto")
        latencies.append((time.perf_counter() - t0) * 1000)
        suggested = result.suggested_text
        positive = case["input"] != case["expected"]
        g = per_group[(case["group"], case["config"])]
        g["n"] += 1
        if positive:
            if result.corrected == case["expected"]:
                outcome = "exact"
            elif result.corrected != case["input"]:
                outcome = "wrong"
            else:
                outcome = "missed"
            g["suggest_exact"] += int(suggested == case["expected"])
        else:
            outcome = "untouched" if result.corrected == case["input"] else "false_positive"
            g["suggestion_noise"] += int(bool(result.suggestions))
        g[outcome] += 1
        if outcome in ("wrong", "false_positive", "missed"):
            failures.append({**{k: case[k] for k in ("group", "config", "input", "expected")},
                             "outcome": outcome, "output": result.corrected,
                             "confidence": result.to_dict()["confidence"]})
    return per_group, failures, latencies


def summarize(per_group) -> dict:
    groups = []
    tot = defaultdict(int)
    for (group, cfg), g in sorted(per_group.items()):
        row = {"group": group, "config": cfg, **g}
        groups.append(row)
        for k, v in g.items():
            tot[k] += v
    pos = tot["exact"] + tot["wrong"] + tot["missed"]
    neg = tot["untouched"] + tot["false_positive"]
    changed = tot["exact"] + tot["wrong"] + tot["false_positive"]
    overall = {
        "positive_inputs": pos,
        "negative_inputs": neg,
        "precision": round(tot["exact"] / changed, 4) if changed else None,
        "recall": round(tot["exact"] / pos, 4) if pos else None,
        "false_positive_rate": round(tot["false_positive"] / neg, 4) if neg else None,
        "exact_correction_accuracy": round(tot["exact"] / (tot["exact"] + tot["wrong"]), 4)
        if tot["exact"] + tot["wrong"] else None,
        "suggest_mode_recall": round(tot["suggest_exact"] / pos, 4) if pos else None,
        "negatives_with_uncertain_suggestion": round(tot["suggestion_noise"] / neg, 4) if neg else None,
        **{k: tot[k] for k in ("exact", "wrong", "missed", "untouched", "false_positive")},
    }
    return {"overall": overall, "groups": groups}


def cold_start_ms(runs: int = 5) -> dict:
    payload = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "פךקשדק גקהקךםפ איק מקסא כקשאורק",
                          "session_id": "bench", "cwd": str(ROOT)})
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        subprocess.run([sys.executable, "-m", "typoshift", "hook", "claude-code"], input=payload.encode(),
                       capture_output=True, check=False, cwd=ROOT,
                       env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "TYPOSHIFT_CONFIG": str(ROOT / "none.toml")})
        times.append((time.perf_counter() - t0) * 1000)
    return {"runs": runs, "median_ms": round(statistics.median(times), 1), "max_ms": round(max(times), 1)}


def to_markdown(report: dict) -> str:
    o = report["overall"]
    out = [
        f"# TypoShift benchmark results ({report['date']})",
        "",
        f"TypoShift {report['version']}, Python {report['python']}, {report['platform']}. "
        "Generated by `python benchmarks/run_benchmark.py`; automatic mode with default thresholds.",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Positive inputs (contain a wrong-layout span) | {o['positive_inputs']} |",
        f"| Negative inputs (correctly typed) | {o['negative_inputs']} |",
        f"| Precision (changes that were exactly right) | {o['precision']:.2%} |",
        f"| Recall (wrong-layout inputs fixed exactly) | {o['recall']:.2%} |",
        f"| False-positive rate (negatives changed) | {o['false_positive_rate']:.2%} |",
        f"| Exact correction accuracy (when a mistake was changed) | {o['exact_correction_accuracy']:.2%} |",
        f"| Suggest-mode recall (intended text among suggestions) | {o['suggest_mode_recall']:.2%} |",
        f"| Negatives that got an uncertain suggestion (hook note, no change) | "
        f"{o['negatives_with_uncertain_suggestion']:.2%} |",
        f"| Warm latency p50 / p95 / max | {report['latency_ms']['p50']} / {report['latency_ms']['p95']} / "
        f"{report['latency_ms']['max']} ms |",
        f"| Hook cold start (new process, median of {report['cold_start']['runs']}) | "
        f"{report['cold_start']['median_ms']} ms |",
        "",
        "## By scenario",
        "",
        "`default` = default layout set (" + ", ".join(DEFAULT_LAYOUTS) + "); `pair` = only the two layouts involved. "
        "Same-script pairs (Latin↔Latin) are suggest-only by default (`same_script_auto = false`).",
        "",
        "Positive rows: *Exact*/*Wrong*/*Missed* in automatic mode, *Suggested* = intended text available "
        "as a suggestion. Negative rows: *Untouched* / *False positives*.",
        "",
        "| Scenario | Config | n | Exact | Wrong | Missed | Suggested | Untouched | False positives |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for g in report["groups"]:
        neg = g["group"].startswith("negative")
        dash = "-"
        out.append(f"| {g['group']} | {g['config']} | {g['n']} | {dash if neg else g.get('exact', 0)} | "
                   f"{dash if neg else g.get('wrong', 0)} | {dash if neg else g.get('missed', 0)} | "
                   f"{dash if neg else g.get('suggest_exact', 0)} | {g.get('untouched', 0) if neg else dash} | "
                   f"{g.get('false_positive', 0) if neg else dash} |")
    out += ["", "Failures are listed in `latest.json` under `failures`.", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="small subset (for CI)")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    cases = build_cases(args.quick)
    per_group, failures, lat = run(cases)
    lat.sort()
    report = {
        "date": date.today().isoformat(),
        "version": __version__,
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        **summarize(per_group),
        "latency_ms": {"p50": round(lat[len(lat) // 2], 2), "p95": round(lat[int(len(lat) * 0.95)], 2),
                       "max": round(lat[-1], 2)},
        "cold_start": cold_start_ms(),
        "failures": failures,
    }
    print(json.dumps(report["overall"], indent=2))
    print(json.dumps({"latency_ms": report["latency_ms"], "cold_start": report["cold_start"]}))
    if not args.no_write and not args.quick:
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                                             encoding="utf-8")
        (RESULTS / "latest.md").write_text(to_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
