#!/usr/bin/env python3
"""Ownership tooling for owner's papers written in Typst.

  install                 install the Typst contract package as @local/ownership
  init DIR --name NAME    create DIR/main.typ from the skeleton (never overwrites)
  cards PAPER             export the paper's #card entries as Anki TSV
  own PAPER TITLE         bind the passed Elenchus gate for a decision to it (copies the gate record)
  ledger [PAPER ...]      list papers: decisions tested/untested, and code changed since the paper
  config                  show the resolved configuration

The paper is the source of truth. Cards and the ledger are derived from it with
`typst query`, so nothing here stores state of its own.

Configuration lives outside this repository, in $OWNERSHIP_CONFIG or
~/.config/ownership/config.json:

  {"library": "C:/Users/you/Documents/retention-library",
   "projects": ["C:/Users/you/Documents/my-private-repo"],
   "anki_dir": "C:/Users/you/Documents/retention-library/anki"}
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PACKAGE = HERE / "typst"
SKELETON = HERE / "templates" / "main.typ"
VERSION = re.search(r'version = "([^"]+)"', (PACKAGE / "typst.toml").read_text(encoding="utf-8")).group(1)
PAPER_DIRS = ("docs/paper", "")


def die(msg: str):
    print(f"ownership: {msg}", file=sys.stderr)
    sys.exit(1)


# ------------------------------------------------------------------ config

def config_path() -> Path:
    env = os.environ.get("OWNERSHIP_CONFIG")
    return Path(env) if env else Path.home() / ".config" / "ownership" / "config.json"


def load_config() -> dict:
    cfg = {"library": None, "projects": [], "anki_dir": None}
    p = config_path()
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except ValueError as e:
            die(f"{p} is not valid JSON: {e}")
    return cfg


# ------------------------------------------------------------------ typst

def typst_packages_dir() -> Path:
    if os.environ.get("TYPST_PACKAGE_PATH"):
        return Path(os.environ["TYPST_PACKAGE_PATH"])
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "typst" / "packages"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "typst" / "packages"
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "typst" / "packages"


def query(paper: Path, selector: str) -> list:
    """Run typst query through the CLI, or the typst Python package as a fallback."""
    paper = paper.resolve()
    exe = shutil.which("typst")
    if exe:
        r = subprocess.run([exe, "query", "--package-path", str(typst_packages_dir()),
                            str(paper), selector, "--field", "value"],
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            die(f"typst query failed for {paper}:\n{r.stderr.strip()}")
        return json.loads(r.stdout or "[]")
    try:
        import typst  # type: ignore
    except ImportError:
        die("no Typst found. Install the CLI (https://github.com/typst/typst) or `pip install typst`.")
    try:
        raw = typst.query(str(paper), selector, field="value", package_path=str(typst_packages_dir()))
    except Exception as e:  # the binding raises its own error types
        die(f"typst query failed for {paper}:\n{e}")
    return json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))


# ------------------------------------------------------------------ commands

def cmd_install(a):
    dest = typst_packages_dir() / "local" / "ownership" / VERSION
    dest.mkdir(parents=True, exist_ok=True)
    for f in ("typst.toml", "ownership.typ"):
        shutil.copyfile(PACKAGE / f, dest / f)
    print(f"Installed @local/ownership:{VERSION} to {dest}")


def cmd_init(a):
    target = Path(a.dir) / "main.typ"
    if target.exists():
        die(f"{target} exists. This command never overwrites a paper.")
    target.parent.mkdir(parents=True, exist_ok=True)
    text = SKELETON.read_text(encoding="utf-8").replace("PROJECT", a.name)
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"Created {target}. It contains headings and prompts only; the prose is yours.")


def project_name(paper: Path) -> str:
    d = paper.resolve().parent
    if d.name == "paper" and d.parent.name == "docs":
        return d.parent.parent.name
    return d.name


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "paper"


def cmd_cards(a):
    cfg = load_config()
    paper = Path(a.paper)
    name = a.project or project_name(paper)
    cards = query(paper, "<card>")
    if not cards:
        print(f"No #card entries in {paper}.")
        return
    out = Path(a.out or cfg.get("anki_dir") or paper.resolve().parent / "anki")
    out.mkdir(parents=True, exist_ok=True)
    esc = lambda x: html.escape(str(x)).replace("\t", " ").replace("\r", "").replace("\n", "<br>")
    rows = {"basic": [], "cloze": []}
    seen = set()
    for c in cards:
        front = esc(c["q"])
        if front in seen:
            die(f"duplicate card front in {paper}: {c['q']!r}")
        seen.add(front)
        back = esc(c["a"])
        if c.get("connects"):
            back += f"<div class='el-connects'><b>Connects to:</b> {esc(c['connects'])}</div>"
        rows["cloze" if c.get("cloze") else "basic"].append(f"{front}\t{back}\townership {slug(name)}")
    for kind, lines in rows.items():
        path = out / f"ownership-{slug(name)}-{kind}.tsv"
        if not lines:
            if path.exists():
                path.unlink()
            continue
        head = (f"#separator:tab\n#html:true\n#notetype:{'Cloze' if kind == 'cloze' else 'Basic'}\n"
                f"#deck:Elenchus::Ownership::{name}\n#tags column:3\n")
        path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"{len(lines)} {kind} cards -> {path}")


def find_papers(cfg: dict) -> list:
    found = []
    lib = cfg.get("library")
    if lib:
        found += sorted((Path(lib) / "projects").glob("*/main.typ"))
    for proj in cfg.get("projects", []):
        p = Path(proj) / "docs" / "paper" / "main.typ"
        if p.exists():
            found.append(p)
        else:
            print(f"warning: no docs/paper/main.typ in {proj}", file=sys.stderr)
    return found


def drift(paper: Path) -> int:
    """Commits that changed the repository outside the paper after the paper was last committed.
    -1 when the paper is not inside a git repository with history."""
    d = paper.resolve().parent
    git = lambda *a: subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True)
    top = git("rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return -1
    top = Path(top.stdout.strip())
    try:
        rel = d.relative_to(top).as_posix()
    except ValueError:
        return -1
    last = git("log", "-1", "--format=%H", "--", str(d))
    if last.returncode != 0 or not last.stdout.strip():
        return -1
    args = ["log", "--format=%h", f"{last.stdout.strip()}..HEAD", "--", str(top)]
    if rel != ".":
        args.append(f":(exclude){rel}")
    r = git(*args)
    return len(r.stdout.split()) if r.returncode == 0 else -1


GATES = "gates"


def gate_ok(paper: Path, gate_id) -> bool:
    """A decision counts as tested when its gate record sits next to the paper and carries evidence."""
    if not gate_id or not re.fullmatch(r"[0-9a-f]{32}", gate_id):
        return False
    f = paper.resolve().parent / GATES / f"{gate_id}.json"
    try:
        rec = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    ev = rec.get("evidence") or {}
    return rec.get("id") == gate_id and all(str(ev.get(k, "")).strip() for k in ("mechanism", "transfer", "limit"))


def state(ds: list, tested: int) -> str:
    if not ds:
        return "empty"
    return "owned" if tested == len(ds) else "in progress"


def cmd_ledger(a):
    cfg = load_config()
    papers = [Path(p) for p in a.papers] or find_papers(cfg)
    if not papers:
        die("no papers given and none found. Set library/projects in " + str(config_path()))
    for paper in papers:
        ds = query(paper, "<decision>")
        ok = [gate_ok(paper, x.get("gate")) for x in ds]
        inherited = sum(1 for x in ds if x["origin"] == "inherited")
        broken = sum(1 for x, g in zip(ds, ok) if x.get("gate") and not g)
        line = f"{project_name(paper):28} {state(ds, sum(ok)):12} {sum(ok)}/{len(ds)} tested, {inherited} inherited"
        if broken:
            line += f"; {broken} gate records missing or without evidence"
        n = drift(paper)
        if n > 0:
            line += f"; {n} commits outside the paper since it was last updated"
        print(line)
        if a.verbose:
            for x, g in zip(ds, ok):
                if not g:
                    tag = "inherited" if x["origin"] == "inherited" else "untested"
                    print(f"    {tag}: {x['title']}" + (f"  ({x['where']})" if x.get("where") else ""))


def history_dir(start: Path):
    env = os.environ.get("ELENCHUS_DIR")
    if env:
        return Path(env) / "history"
    for d in (start, *start.parents):
        if (d / ".elenchus" / "history").is_dir():
            return d / ".elenchus" / "history"
    return None


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def cmd_own(a):
    paper = Path(a.paper)
    src = paper.read_text(encoding="utf-8")
    call = re.compile(r'#decision\(\s*"' + re.escape(a.title) + r'"[^\n]*\)')
    hits = call.findall(src)
    if len(hits) != 1:
        die(f"expected exactly one single-line #decision(\"{a.title}\", ...) in {paper}, found {len(hits)}")
    hist = Path(a.elenchus_dir) / "history" if a.elenchus_dir else history_dir(Path.cwd().resolve())
    if not hist or not hist.is_dir():
        die("no Elenchus history found. Pass a gate on this decision first (/elenchus:learn explain|propose <decision>).")
    recs = []
    for f in hist.glob("*.json"):
        try:
            recs.append(json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            continue
    recs.sort(key=lambda r: r.get("created", 0), reverse=True)
    if a.gate:
        rec = next((r for r in recs if r.get("id") == a.gate), None)
        if not rec:
            die(f"gate {a.gate} not found in {hist}")
    else:
        want = norm(a.title)
        def matches(r):
            topic = norm(r.get("topic", ""))
            return bool(topic) and (want in topic or topic in want)
        rec = next((r for r in recs if matches(r)), None)
        if not rec:
            print("No passed gate whose topic matches this decision. Recent gates:", file=sys.stderr)
            for r in recs[:5]:
                print(f"  {r.get('id')}  {r.get('mode')}  {r.get('topic')!r}", file=sys.stderr)
            die("pass a gate on the decision, or choose one with --gate ID")
    ev = rec.get("evidence") or {}
    if not all(str(ev.get(k, "")).strip() for k in ("mechanism", "transfer", "limit")):
        die(f"gate {rec.get('id')} carries no assessed evidence")
    dest = paper.resolve().parent / GATES
    dest.mkdir(exist_ok=True)
    (dest / f"{rec['id']}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    line = hits[0]
    new = re.sub(r',\s*gate:\s*"[^"]*"', "", line)
    new = re.sub(r'origin:\s*"inherited"', 'origin: "mine"', new)
    new = new[:-1] + f', gate: "{rec["id"]}")'
    paper.write_text(src.replace(line, new), encoding="utf-8", newline="\n")
    print(f"Owned: {a.title!r} by the {rec.get('mode')} gate {rec['id'][:8]} on {rec.get('topic')!r}.")
    if rec.get("own_words"):
        print(f"Your words then: {rec['own_words'][:300]}")


def cmd_config(a):
    p = config_path()
    print(f"config file: {p} ({'found' if p.exists() else 'missing, defaults used'})")
    print(json.dumps(load_config(), indent=2))
    print(f"typst package dir: {typst_packages_dir()}")


def main():
    ap = argparse.ArgumentParser(prog="ownership", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("install").set_defaults(fn=cmd_install)
    p = sub.add_parser("init"); p.add_argument("dir"); p.add_argument("--name", required=True); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("cards"); p.add_argument("paper"); p.add_argument("--out"); p.add_argument("--project"); p.set_defaults(fn=cmd_cards)
    p = sub.add_parser("own"); p.add_argument("paper"); p.add_argument("title"); p.add_argument("--gate"); p.add_argument("--elenchus-dir"); p.set_defaults(fn=cmd_own)
    p = sub.add_parser("ledger"); p.add_argument("papers", nargs="*"); p.add_argument("-v", "--verbose", action="store_true"); p.set_defaults(fn=cmd_ledger)
    sub.add_parser("config").set_defaults(fn=cmd_config)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
