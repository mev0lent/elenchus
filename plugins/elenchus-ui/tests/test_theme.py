#!/usr/bin/env python3
"""Checks the two shipped Claude Code themes: valid shape, known tokens, palette fidelity,
readable contrast on the real worst-case grounds, and that they match the generator."""
import json
import re
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / "scripts"))
import gen_theme as g  # noqa: E402

failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


KNOWN = {
    "claude", "claudeShimmer", "text", "inverseText", "inactive", "inactiveShimmer", "subtle", "suggestion",
    "remember", "permission", "permissionShimmer", "success", "error", "warning", "warningShimmer", "merged",
    "promptBorder", "promptBorderShimmer", "bashBorder", "planMode", "autoAccept", "ide", "fastMode",
    "fastModeShimmer", "diffAdded", "diffRemoved", "diffAddedDimmed", "diffRemovedDimmed", "diffAddedWord",
    "diffRemovedWord", "userMessageBackground", "userMessageBackgroundHover", "bashMessageBackgroundColor",
    "memoryBackgroundColor", "selectionBg", "rate_limit_fill", "rate_limit_empty", "briefLabelYou",
    "briefLabelClaude", "red_FOR_SUBAGENTS_ONLY", "green_FOR_SUBAGENTS_ONLY", "purple_FOR_SUBAGENTS_ONLY",
    "cyan_FOR_SUBAGENTS_ONLY",
}
BASES = {"dark", "light", "dark-daltonized", "light-daltonized", "dark-ansi", "light-ansi"}
P = g.load_palette()
TEXT = ["text", "claude", "error", "success", "warning", "suggestion", "remember", "inactive",
        "briefLabelYou", "briefLabelClaude", "planMode", "autoAccept", "ide"]
EDGE = ["promptBorder", "permission", "bashBorder", "subtle"]

for fname, base, bg_pair in (("elenchus.json", "dark", [P["navy"], "#000000"]),
                             ("elenchus-light.json", "light", [P["cream"], "#FFFFFF"])):
    t = json.loads((PLUGIN / "themes" / fname).read_text(encoding="utf-8"))
    o = t["overrides"]
    check(f"{fname}: has name and valid base", bool(t.get("name")) and t.get("base") in BASES and t["base"] == base)
    check(f"{fname}: only documented tokens", set(o) <= KNOWN)
    check(f"{fname}: every value is #rrggbb", all(re.fullmatch(r"#[0-9A-F]{6}", v) for v in o.values()))
    for k in TEXT:
        check(f"{fname}: {k} readable (4.5:1)", g.worst(o[k], bg_pair) >= 4.5)
    for k in EDGE:
        check(f"{fname}: {k} visible (3:1)", g.worst(o[k], bg_pair) >= 3.0)
    ground = P["navy"] if base == "dark" else P["cream"]
    check(f"{fname}: text is the palette's own text color", o["text"] == (P["cream"] if base == "dark" else P["navy"]))
    check(f"{fname}: message backgrounds keep text at 7:1", g.contrast(o["text"], o["userMessageBackground"]) >= 7)
    check(f"{fname}: diff backgrounds keep text at 7:1",
          all(g.contrast(o["text"], o[k]) >= 7 for k in ("diffAdded", "diffRemoved", "diffAddedWord", "diffRemovedWord")))

check("dark theme keeps pure teal and purple where readable",
      json.loads((PLUGIN / "themes" / "elenchus.json").read_text())["overrides"]["success"] == P["teal"]
      and json.loads((PLUGIN / "themes" / "elenchus.json").read_text())["overrides"]["selectionBg"] == P["purple"])
r = subprocess.run([sys.executable, str(PLUGIN / "scripts" / "gen_theme.py"), "--check"], capture_output=True, text=True)
check("generator output matches the shipped files", r.returncode == 0)

print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
