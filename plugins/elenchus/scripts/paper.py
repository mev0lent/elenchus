"""Owner's paper: one Typst file per project, compiled to PDF. It lists the project's
decisions, each tied to a formal statement (an equation, invariant, definition or
algorithm), and whether each decision is the user's. Shared byte for byte by the
Claude/Codex and Vibe engines (a test keeps the copies equal).

A decision is one line:
  #decision("title", origin: "inherited", where: "file:line", formal: <label>)
    inherited        in the project, not the user's yet (the agent logs these)
    mine             the user's, not tested
    gate: "<id>"     owned: the user passed an Elenchus gate on it (/elenchus:own)
    formal: <label>  the numbered equation, invariant, definition or algorithm that states it;
                     several: formal: (<a>, <b>). A decision without one cannot be owned.

The paper defines its helpers itself, so it compiles with plain Typst and no package.
Reading decisions needs no Typst: they are single lines, read with a regex.
"""
import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

DEFAULT = Path("docs") / "paper" / "main.typ"
POINTER = "paper"  # file inside .elenchus/ holding the paper path, for papers kept elsewhere
LINE = re.compile(r'^[ \t]*#decision\(\s*"((?:[^"\\]|\\.)*)"([^\n]*)\)[ \t]*$', re.M)
ARG = re.compile(r'(origin|where|gate)\s*:\s*"((?:[^"\\]|\\.)*)"')
CARD = re.compile(r'^[ \t]*#card\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*"((?:[^"\\]|\\.)*)"\s*\)[ \t]*$', re.M)
FORMAL = re.compile(r'formal\s*:\s*(<[\w.:-]+>|\([^)]*\))')
LABEL = re.compile(r'<([\w.:-]+)>')

TEMPLATE = r'''// Owner's paper. Formal first: every decision points to a numbered equation,
// invariant, definition or algorithm. Prose only says why.
// Elenchus reads the #decision lines: keep each on one line.

// ---- palette and helpers (edit freely, keep the function names) ----
#let ink = rgb("#2E2B3A")
#let pastel = (
  lavender: (fill: rgb("#EEE8F8"), line: rgb("#A694D6")),
  sky:      (fill: rgb("#E4F0FA"), line: rgb("#86B3DD")),
  mint:     (fill: rgb("#E3F5EC"), line: rgb("#7CC5A1")),
  butter:   (fill: rgb("#FFF6D6"), line: rgb("#DEC062")),
  peach:    (fill: rgb("#FDEADF"), line: rgb("#E9A27C")),
  rose:     (fill: rgb("#FBE6EC"), line: rgb("#DE8EA6")),
)
#set document(title: "{name}")
#set page(margin: 2.2cm, numbering: "1",
  footer: context align(center, text(size: 8pt, fill: pastel.lavender.line)[#counter(page).display()]))
#set text(size: 10.5pt, fill: ink)
#set par(justify: true)
#set heading(numbering: "1.")
#show heading.where(level: 1): it => block(above: 1.8em, below: 0.9em, width: 100%,
  stroke: (bottom: 1.2pt + pastel.lavender.line), inset: (bottom: 5pt), it)
#set math.equation(numbering: n => text(fill: pastel.sky.line.darken(35%))[(#n)])
#show figure: set align(left)
#set highlight(fill: pastel.butter.fill)

#let panel(c) = (width: 100%, stroke: (left: 1.6pt + c.line), inset: (left: 11pt, right: 4pt, y: 5pt))
#let tag(c, body) = box(fill: c.fill, stroke: 0.6pt + c.line, radius: 7pt, inset: (x: 6pt, y: 2pt), text(size: 0.78em, body))
#let stmt(kind, c, name, body) = figure(kind: kind, supplement: kind, numbering: "1",
  block(..panel(c))[#text(fill: c.line.darken(30%), weight: "bold")[#kind #context counter(figure.where(kind: kind)).display()] #text(fill: c.line.darken(30%))[(#name)]. #body])
#let definition(name, body) = stmt("Definition", pastel.sky, name, body)
#let invariant(name, body) = stmt("Invariant", pastel.mint, name, body)
#let algorithm(name, input: none, output: none, body) = figure(kind: "Algorithm", supplement: "Algorithm", numbering: "1",
  block(..panel(pastel.lavender))[
    #text(fill: pastel.lavender.line.darken(30%), weight: "bold")[Algorithm #context counter(figure.where(kind: "Algorithm")).display()] #text(fill: pastel.lavender.line.darken(30%))[(#name)]
    #if input != none [ \ *Input:* #input]
    #if output != none [ \ *Output:* #output]
    #v(2pt) #line(length: 100%, stroke: 0.5pt + pastel.lavender.line) #v(-2pt)
    #body
  ])
#let symbols(..pairs) = table(columns: (auto, 1fr), inset: (x: 8pt, y: 5pt),
  stroke: (_, y) => (bottom: 0.4pt + pastel.sky.fill.darken(4%)),
  ..pairs.pos().map(p => (p.at(0), p.at(1))).flatten())
#let mark(body) = highlight(fill: pastel.rose.fill, body)
#let note(body) = block(..panel(pastel.rose))[#text(size: 0.9em)[#text(fill: pastel.rose.line.darken(25%), weight: "bold")[Note.] #body]]
#let card(q, a) = block(..panel(pastel.butter), above: 0.6em)[#text(size: 0.85em)[#text(fill: pastel.butter.line.darken(30%), weight: "bold")[Card] \ #q \ #emph(a)]]
#let mywords(body) = block(width: 100%, inset: (left: 11pt, y: 4pt), stroke: (left: 1.5pt + pastel.lavender.line))[
  #text(size: 0.8em, fill: pastel.lavender.line.darken(30%))[*In my words, after the gate*] \ #emph(body)]
#let decision(title, origin: "mine", where: none, gate: none, formal: none) = {
  let (c, state) = if gate != none { (pastel.mint, "owned") } else if origin == "inherited" { (pastel.peach, "inherited") } else { (pastel.butter, "mine, not tested") }
  block(..panel(c), above: 1.3em, below: 0.5em)[
    #text(weight: "bold")[#title] #h(1fr) #tag(c, state)
    #if formal != none [ \ #text(size: 0.85em)[Formal: #(if type(formal) == array { formal } else { (formal,) }).map(l => ref(l)).join(", ")]]
    #if where != none [ \ #text(size: 0.8em, raw(where))]
  ]
}

// ---- title ----
#align(center)[
  #text(size: 20pt, weight: "bold")[{name}] \
  #v(2pt) #text(size: 10pt, fill: pastel.lavender.line.darken(20%))[Owner's paper]
]
#grid(columns: (1fr,) * 6, column-gutter: 3pt, ..pastel.values().map(c => rect(width: 100%, height: 3pt, radius: 1.5pt, fill: c.line)))

= Purpose
// Numbered claims, one line each: what must hold for this project to be worth anything.

= Notation
// Every symbol used in this paper, defined exactly once. Example:
//   #symbols(($tau$, [gate threshold on $P("normal" | x)$]), ($D_"dev"$, [development split]))

= Model
// Definitions, invariants and algorithms, each with a label. Examples:
//   $ "archive"(x) <==> P("normal" | x) >= tau $ <eq-gate>
//   #invariant("no test leakage")[$tau = f(D_"dev")$ and $f$ never reads $D_"test"$.] <inv-leak>
//   #algorithm("Triage", input: [$x$], output: [archive or escalate])[
//     + $p <- P("normal" | x)$
//     + *if* $p >= tau$ *then* archive *else* escalate
//   ] <alg-triage>
// Highlights: #mark[...] in rose, #highlight[...] in butter, #note[...] for a remark.

= Decisions
// One line each, pointing to its formal statement:
//   #decision("Archive iff P(normal) >= tau", origin: "mine", formal: <eq-gate>, where: "gatelib.mjs:12")
// Below it, only why: what you rejected and what would change your mind.
// A card worth keeping, on one line: #card("Why is tau chosen on dev?", "Because ...")

= Limits and open questions
'''


def unq(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def find(project: Path, elenchus_dir: Path):
    """The project's paper: the path recorded by init, else docs/paper/main.typ."""
    ptr = elenchus_dir / POINTER
    if ptr.is_file():
        p = Path(ptr.read_text(encoding="utf-8").strip())
        return p if p.is_file() else None
    p = project / DEFAULT
    return p if p.is_file() else None


def init(project: Path, elenchus_dir: Path, path: str, name: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = project / p
    if p.suffix != ".typ":
        p = p / "main.typ"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(TEMPLATE.replace("{name}", name), encoding="utf-8", newline="\n")
    elenchus_dir.mkdir(parents=True, exist_ok=True)
    (elenchus_dir / POINTER).write_text(str(p.resolve()) + "\n", encoding="utf-8")
    remember(p)
    return p


def registry() -> Path:
    """Every paper created on this machine, for the overview. Outside every repository."""
    env = os.environ.get("ELENCHUS_PAPERS")
    return Path(env) if env else Path.home() / ".config" / "elenchus" / "papers.json"


def remember(p: Path) -> None:
    r = registry()
    try:
        known = json.loads(r.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = []
    path = str(p.resolve())
    if path not in known:
        r.parent.mkdir(parents=True, exist_ok=True)
        r.write_text(json.dumps(known + [path], indent=2) + "\n", encoding="utf-8")


def status_all() -> str:
    try:
        known = json.loads(registry().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = []
    rows = []
    for path in known:
        p = Path(path)
        if not p.is_file():
            rows.append(f"  missing   {path}")
            continue
        ds = decisions(p)
        owned = sum(1 for x in ds if gate_ok(p, x["gate"]))
        state = "empty" if not ds else ("OWNED" if owned == len(ds) else "in progress")
        n = drift(p)
        rows.append(f"  {state:11} {owned}/{len(ds)} owned  {p}" + (f"  ({n} commits since the paper)" if n > 0 else ""))
    return "Papers on this machine:\n" + ("\n".join(rows) if rows else "  none yet")


def decisions(paper: Path) -> list:
    out = []
    for m in LINE.finditer(paper.read_text(encoding="utf-8")):
        args = {k: unq(v) for k, v in ARG.findall(m.group(2))}
        f = FORMAL.search(m.group(2))
        out.append({"title": unq(m.group(1)), "origin": args.get("origin", "mine"),
                    "where": args.get("where", ""), "gate": args.get("gate", ""),
                    "formal": LABEL.findall(f.group(1)) if f else []})
    return out


def lookup(paper: Path, title: str):
    want = " ".join(title.lower().split())
    return next((x for x in decisions(paper) if " ".join(x["title"].lower().split()) == want), None)


def formal_source(paper: Path, labels: list):
    """The source of each labeled statement, or None for a label that is not defined.
    A definition is a label right after the closing $ or ] of the statement."""
    src = paper.read_text(encoding="utf-8")
    body = LINE.sub("", src)  # labels inside decision lines are references, not definitions
    out = {}
    for name in labels:
        m = re.search(r"[\$\]\)]\s*<" + re.escape(name) + r">", body)
        if not m:
            out[name] = None
            continue
        lines = body[:m.end()].split("\n")
        stmt = [lines.pop()]
        while not stmt[0].lstrip().startswith(("#", "$")) and lines and lines[-1].strip():
            stmt.insert(0, lines.pop())  # a multi-line statement starts with its #function or $
        out[name] = "\n".join(stmt).strip()[-900:]
    return out


def readiness(paper: Path, title: str):
    """(decision, problem). The problem is None when the decision may be gated."""
    d = lookup(paper, title)
    if not d:
        return None, (f"There is no decision titled {title!r} in the paper. Add it as one line: "
                      f'#decision("{title}", origin: "mine", formal: <label>), with its labeled statement in the Model section.')
    if not d["formal"]:
        return d, ("This decision has no formal statement. State it as a numbered equation, invariant, definition or "
                   "algorithm in the Model section, give it a label, and point to it with formal: <label>.")
    missing = [n for n, s in formal_source(paper, d["formal"]).items() if s is None]
    if missing:
        return d, "These labels are not defined in the paper: " + ", ".join(f"<{n}>" for n in missing) + "."
    return d, None


def gate_ok(paper: Path, gate_id: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{32}", gate_id or ""):
        return False
    try:
        rec = json.loads((paper.parent / "gates" / f"{gate_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    ev = rec.get("evidence") or {}
    return rec.get("id") == gate_id and all(str(ev.get(k, "")).strip() for k in ("mechanism", "transfer", "limit"))


def drift(paper: Path) -> int:
    """Commits outside the paper's folder since the paper was last committed; -1 if unknown."""
    d = paper.resolve().parent
    git = lambda *a: subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True)
    top = git("rev-parse", "--show-toplevel")
    last = git("log", "-1", "--format=%H", "--", ".")
    if top.returncode or last.returncode or not last.stdout.strip():
        return -1
    r = git("log", "--format=%h", last.stdout.strip() + "..HEAD", "--", top.stdout.strip(), ":(exclude)" + str(d))
    return len(r.stdout.split()) if r.returncode == 0 else -1


def status(paper: Path) -> str:
    ds = decisions(paper)
    owned = [x for x in ds if gate_ok(paper, x["gate"])]
    inherited = [x for x in ds if x["origin"] == "inherited" and x not in owned]
    mine = [x for x in ds if x not in owned and x not in inherited]
    state = "empty" if not ds else ("OWNED" if len(owned) == len(ds) else "in progress")
    lines = [f"Paper: {paper}", f"State: {state}. {len(owned)} owned, {len(mine)} mine but untested, {len(inherited)} inherited."]
    for label, group in (("inherited", inherited), ("mine, untested", mine)):
        for x in group:
            flag = "" if x["formal"] else "  [not formalized]"
            lines.append(f"  {label}: {x['title']}{flag}" + (f"  ({x['where']})" if x["where"] else ""))
    broken = [x for x in ds if x["gate"] and x not in owned]
    if broken:
        lines.append(f"  {len(broken)} gate records missing in {paper.parent / 'gates'}")
    n = drift(paper)
    if n > 0:
        lines.append(f"  {n} commits changed the project since the paper was last committed. Re-gate what they touched.")
    return "\n".join(lines)


def build(paper: Path) -> str:
    """Compile the paper to PDF next to it. Typst also checks that every reference resolves."""
    out = paper.with_suffix(".pdf")
    exe = shutil.which("typst")
    if exe:
        r = subprocess.run([exe, "compile", str(paper), str(out)], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr.strip())
        return str(out)
    try:
        import typst  # type: ignore
    except ImportError:
        raise RuntimeError("Typst is not installed. Install the CLI or run `pip install typst`.")
    try:
        typst.compile(str(paper), output=str(out))
    except Exception as e:  # the binding raises its own error types
        raise RuntimeError(str(e))
    return str(out)


def cards(paper: Path, out_dir: Path) -> str:
    """Export the paper's #card lines as an Anki TSV. The paper stays the only source."""
    rows = [(unq(a), unq(b)) for a, b in CARD.findall(paper.read_text(encoding="utf-8"))]
    if not rows:
        return "No #card lines in the paper."
    name = paper.parent.parent.parent.name if paper.parent.name == "paper" and paper.parent.parent.name == "docs" else paper.parent.name
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "paper"
    esc = lambda x: html.escape(x).replace("\t", " ").replace("\n", "<br>")
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f"paper-{slug}.tsv"
    f.write_text(f"#separator:tab\n#html:true\n#notetype:Basic\n#deck:Elenchus::Papers::{name}\n#tags column:3\n"
                 + "".join(f"{esc(a)}\t{esc(b)}\telenchus paper {slug}\n" for a, b in rows), encoding="utf-8", newline="\n")
    return f"{len(rows)} cards -> {f}"


def typst_text(s: str) -> str:
    return re.sub(r"([\\#$*_`<>@\[\]~=/-])", r"\\\1", s)


def bind(paper: Path, title: str, record: dict) -> str:
    """Make a decision owned by a passed gate: copy the gate record next to the paper,
    mark the line, and put the user's own reasoning from the gate below it."""
    gates = paper.parent / "gates"
    gates.mkdir(exist_ok=True)
    (gates / f"{record['id']}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8", newline="\n")
    src = paper.read_text(encoding="utf-8")
    words = (record.get("own_words") or "").strip()
    why = f"#mywords[{typst_text(words)}]\n" if words else ""
    d = lookup(paper, title)
    match = next((m for m in LINE.finditer(src) if d and unq(m.group(1)) == d["title"]), None)
    if match:
        rest = re.sub(r',\s*(origin|gate)\s*:\s*"(?:[^"\\]|\\.)*"', "", match.group(2))
        new = f"#decision({q(d['title'])}{rest}, origin: \"mine\", gate: \"{record['id']}\")"
        src = src[:match.start()] + new + "\n" + why + src[match.end():].lstrip("\n")
        result = "Decision marked owned"
    else:
        entry = f"#decision({q(title)}, origin: \"mine\", gate: \"{record['id']}\")\n{why}\n"
        head = src.find("\n= Limits and open questions")
        head = head + 1 if head >= 0 else -1
        src = src[:head] + entry + src[head:] if head >= 0 else src.rstrip("\n") + "\n\n" + entry
        result = "Decision added as owned, without a formal statement yet"
    paper.write_text(src, encoding="utf-8", newline="\n")
    return f"{result}: {title!r} in {paper}"


def gate_brief(paper: Path, title: str) -> str:
    d, _ = readiness(paper, title)
    if not d:
        return ""
    stmts = "\n".join(f"<{n}>: {s}" for n, s in formal_source(paper, d["formal"]).items() if s)
    where = f" The code is at {d['where']}." if d["where"] else ""
    return (f"OWN GATE on the decision {d['title']!r}. The user's formal statement:\n{stmts}\n{where} "
            "Attack the formalism, one question per turn: is every symbol defined in the Notation section, what happens "
            "at the boundaries (equality, empty input, extremes), does the code do exactly what the statement says, "
            "for an algorithm: termination and cost, and why this formulation instead of the rejected alternative. "
            "Accept only if the user can justify or derive the statement, not just restate it.")


def session_note(paper: Path, cli: str) -> str:
    return (f"OWNER'S PAPER: this project has one at {paper}. Whenever you decide something the user did not "
            "specify and that would matter if it changed (a data model, a threshold, a dependency, an error "
            "policy, a security default), add one line under '= Decisions' in the same turn: "
            '#decision("what you chose", origin: "inherited", where: "file:line"). Mechanical work is not a '
            "decision. Never formalize a decision for the user, never write a reason under it and never edit a "
            "gate value: formal statements and reasons are the user's work. You may typeset math the user dictates. "
            f"Show the state with `{cli} paper status`, build the PDF with `{cli} paper build`.")
