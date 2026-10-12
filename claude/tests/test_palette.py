#!/usr/bin/env python3
"""Keeps the three places that hold the Elenchus colors in agreement:
hooks/palette.ts (the band), anki/elenchus-card.css (the cards) and the command hooks
that coexist with the UI module in hooks/hooks.json."""
import json
import re
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


def luminance(h):
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


ts = (PLUGIN / "hooks" / "palette.ts").read_text(encoding="utf-8")
css = (PLUGIN / "anki" / "elenchus-card.css").read_text(encoding="utf-8")
palette = dict(re.findall(r"^\s+(\w+): '(#[0-9A-Fa-f]{6})',?$", ts.split("export type Tone")[0], re.M))

check("palette.ts defines the five colors", set(palette) == {"cream", "purple", "navy", "teal", "crimson"})
check("palette is the one the user chose", {k: v.upper() for k, v in palette.items()} ==
      {"cream": "#FBF5F3", "purple": "#7D5BA6", "navy": "#000022", "teal": "#3BCEAC", "crimson": "#C42847"})

allowed = {v.upper() for v in palette.values()}
used = {h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}\b", css)}
check("every hex in the card css is a palette color", used <= allowed)
check("card css uses all five colors", used == allowed)
check("card css has classes for the connects and mistake blocks", ".el-connects" in css and ".el-mistake" in css)
check("card css has a night mode", ".nightMode .card" in css)

# text pairs on the cards must stay readable (WCAG 4.5)
P = {k: v for k, v in palette.items()}
pairs = [("navy", "cream"), ("purple", "cream"), ("crimson", "cream"), ("cream", "navy"), ("teal", "navy")]
for fg, bg in pairs:
    check(f"card text {fg} on {bg} is at least 4.5:1", contrast(P[fg], P[bg]) >= 4.5)

# the pairs that fail must never be used as small text in the css: purple/crimson on navy
night = css.split(".nightMode .card")[1]
check("night mode never sets purple or crimson as text color",
      not re.search(r"(?<!-)color:\s*#(7D5BA6|C42847)", night, re.I))

hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
check("hooks.json names the UI module", hooks.get("modules") == ["./register.tsx"])
check("hooks.json still carries the command hooks", set(hooks.get("hooks", {})) == {"SessionStart", "UserPromptSubmit", "PreToolUse", "Stop"})
check("module files exist", (PLUGIN / "hooks" / "register.tsx").exists() and (PLUGIN / "hooks" / "palette.ts").exists())
check("palette.ts has no em-dashes", chr(0x2014) not in ts)

print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
