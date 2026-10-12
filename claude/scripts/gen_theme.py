#!/usr/bin/env python3
"""Generates themes/elenchus.json (dark) and themes/elenchus-light.json from hooks/palette.ts.

The palette stays the single source of truth. A palette color is used as it is wherever it
is readable. Where it is not (purple or crimson as text on a dark ground, teal as text on a
light one), it is lifted toward cream (dark theme) or navy (light theme) by the smallest
amount that reaches the required WCAG contrast. Text tokens must reach 4.5:1, border-like
tokens 3:1, measured against the real worst-case grounds: the navy of the palette AND pure
black (many terminals are black) for the dark theme, cream AND white for the light one.

    python3 scripts/gen_theme.py            write the two files
    python3 scripts/gen_theme.py --check    exit 1 if the files are stale
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_palette():
    ts = (ROOT / "hooks" / "palette.ts").read_text(encoding="utf-8").split("export type Tone")[0]
    p = dict(re.findall(r"^\s+(\w+): '(#[0-9A-Fa-f]{6})',?$", ts, re.M))
    return {k: v.upper() for k, v in p.items()}


def rgb(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def hexc(c):
    return "#" + "".join(f"{max(0, min(255, round(v))):02X}" for v in c)


def mix(a, b, t):
    """t of b into a."""
    return hexc([x + (y - x) * t for x, y in zip(rgb(a), rgb(b))])


def lum(h):
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = [f(v / 255) for v in rgb(h)]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def worst(color, grounds):
    return min(contrast(color, g) for g in grounds)


def ensure(color, toward, grounds, need):
    """The color itself if readable on every ground, else the smallest tint toward `toward`."""
    if worst(color, grounds) >= need:
        return color
    for step in range(1, 101):
        c = mix(color, toward, step / 100)
        if worst(c, grounds) >= need:
            return c
    raise SystemExit(f"cannot make {color} reach {need}:1")


def dark(P):
    cream, purple, navy, teal, crimson = (P[k] for k in ("cream", "purple", "navy", "teal", "crimson"))
    G = [navy, "#000000"]
    txt = lambda c: ensure(c, cream, G, 4.5)
    edge = lambda c: ensure(c, cream, G, 3.0)
    t, pu, cr = txt(teal), txt(purple), txt(crimson)
    o = {
        "claude": t, "claudeShimmer": mix(t, cream, 0.4),
        "text": cream, "inverseText": navy,
        "inactive": txt(mix(navy, cream, 0.5)), "inactiveShimmer": txt(mix(navy, cream, 0.7)),
        "subtle": edge(mix(navy, cream, 0.28)),
        "suggestion": t, "remember": pu,
        "permission": edge(purple), "permissionShimmer": mix(edge(purple), cream, 0.35),
        "success": t, "error": cr, "warning": pu, "warningShimmer": mix(pu, cream, 0.35), "merged": pu,
        "promptBorder": edge(purple), "promptBorderShimmer": mix(edge(purple), cream, 0.35),
        "bashBorder": edge(crimson), "planMode": t, "autoAccept": cr, "ide": t,
        "fastMode": pu, "fastModeShimmer": mix(pu, cream, 0.35),
        "diffAdded": mix(navy, teal, 0.26), "diffRemoved": mix(navy, crimson, 0.38),
        "diffAddedDimmed": mix(navy, teal, 0.14), "diffRemovedDimmed": mix(navy, crimson, 0.2),
        "diffAddedWord": mix(navy, teal, 0.4), "diffRemovedWord": mix(navy, crimson, 0.55),
        "userMessageBackground": mix(navy, purple, 0.22), "userMessageBackgroundHover": mix(navy, purple, 0.32),
        "bashMessageBackgroundColor": mix(navy, teal, 0.14), "memoryBackgroundColor": mix(navy, purple, 0.14),
        "selectionBg": purple,
        "rate_limit_fill": t, "rate_limit_empty": mix(navy, cream, 0.18),
        "briefLabelYou": t, "briefLabelClaude": pu,
        "red_FOR_SUBAGENTS_ONLY": cr, "green_FOR_SUBAGENTS_ONLY": t,
        "purple_FOR_SUBAGENTS_ONLY": pu, "cyan_FOR_SUBAGENTS_ONLY": txt(mix(teal, cream, 0.45)),
    }
    return {"name": "Elenchus", "base": "dark", "overrides": o}


def light(P):
    cream, purple, navy, teal, crimson = (P[k] for k in ("cream", "purple", "navy", "teal", "crimson"))
    G = [cream, "#FFFFFF"]
    txt = lambda c: ensure(c, navy, G, 4.5)
    edge = lambda c: ensure(c, navy, G, 3.0)
    t, pu, cr = txt(teal), txt(purple), txt(crimson)
    o = {
        "claude": pu, "claudeShimmer": mix(pu, cream, 0.4),
        "text": navy, "inverseText": cream,
        "inactive": txt(mix(cream, navy, 0.55)), "inactiveShimmer": txt(mix(cream, navy, 0.4)),
        "subtle": edge(mix(cream, navy, 0.3)),
        "suggestion": pu, "remember": pu,
        "permission": edge(purple), "permissionShimmer": mix(edge(purple), cream, 0.35),
        "success": t, "error": cr, "warning": pu, "warningShimmer": mix(pu, cream, 0.35), "merged": pu,
        "promptBorder": edge(purple), "promptBorderShimmer": mix(edge(purple), cream, 0.35),
        "bashBorder": edge(crimson), "planMode": t, "autoAccept": cr, "ide": t,
        "fastMode": pu, "fastModeShimmer": mix(pu, cream, 0.35),
        "diffAdded": mix(cream, teal, 0.35), "diffRemoved": mix(cream, crimson, 0.22),
        "diffAddedDimmed": mix(cream, teal, 0.18), "diffRemovedDimmed": mix(cream, crimson, 0.12),
        "diffAddedWord": mix(cream, teal, 0.6), "diffRemovedWord": mix(cream, crimson, 0.4),
        "userMessageBackground": mix(cream, purple, 0.12), "userMessageBackgroundHover": mix(cream, purple, 0.2),
        "bashMessageBackgroundColor": mix(cream, teal, 0.18), "memoryBackgroundColor": mix(cream, purple, 0.08),
        "selectionBg": mix(cream, purple, 0.3),
        "rate_limit_fill": pu, "rate_limit_empty": mix(cream, navy, 0.12),
        "briefLabelYou": t, "briefLabelClaude": pu,
        "red_FOR_SUBAGENTS_ONLY": cr, "green_FOR_SUBAGENTS_ONLY": t,
        "purple_FOR_SUBAGENTS_ONLY": pu, "cyan_FOR_SUBAGENTS_ONLY": txt(mix(teal, navy, 0.35)),
    }
    return {"name": "Elenchus Light", "base": "light", "overrides": o}


def build():
    P = load_palette()
    return {"elenchus.json": dark(P), "elenchus-light.json": light(P)}


def render(obj):
    return json.dumps(obj, indent=2) + "\n"


def main():
    out = ROOT / "themes"
    files = build()
    if "--check" in sys.argv:
        stale = [n for n, o in files.items()
                 if not (out / n).exists() or (out / n).read_text(encoding="utf-8") != render(o)]
        if stale:
            print("stale theme files:", ", ".join(stale), "- run python3 scripts/gen_theme.py")
            sys.exit(1)
        print("themes are up to date")
        return
    out.mkdir(exist_ok=True)
    for name, obj in files.items():
        with (out / name).open("w", encoding="utf-8", newline="\n") as f:
            f.write(render(obj))
        print("wrote", out / name)


if __name__ == "__main__":
    main()
