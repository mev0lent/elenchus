# Elenchus

Use AI for speed and stay the master of your work. The ideas, the decisions and the reasons are yours. The code and the configuration may come from the agent.

Every project gets an owner's paper: a Typst document, compiled to PDF, in which each decision is stated formally, as an equation, invariant, definition or algorithm. You own a decision only after you have formalized it yourself and defended that formalization under questioning.

## Commands

| Command | For |
| --- | --- |
| `/elenchus:learn <mode> <topic>` | Learning. You explain, predict or propose first; the agent probes; you pass when your reasoning holds. |
| `/elenchus:paper` | Start a project's paper, or see its state and build the PDF. `/elenchus:paper all` lists every paper you have. |
| `/elenchus:own <decision>` | Own a decision. It must be formalized in the paper; the agent attacks the formalism; pass, and it is marked yours, with your own reasons. |
| `/elenchus:recall [words]` | Remembering. Reproduce from memory something you passed before; without words it takes the note you have not touched longest. |
| `/elenchus:always on` | Every new session, in every project, starts in open work, so decisions come to you without typing a command first. `always off` ends it. |

Also: `/elenchus:status`, `/elenchus:cards` (Anki cards from your last gate), `/elenchus:off`. In Codex, type them without the slash: `elenchus own <decision>`.

## Open work: the agent builds, you decide

A passed gate opens the work and it stays open: no lock and no word cap until the next gate starts. When the work reaches a decision that shapes the result, the agent does not make it. It starts a decide gate: you state your choice and the reason, it attacks once, you answer, and work continues. Two short answers, recorded in your knowledge graph as your decision.

If you really have no opinion, type `delegate: <remark>`. The agent then decides, and the graph records that this one was left to it, alongside what the agent chose and why. `elenchus.py graph delegated` lists what you do not own.

## Fast turns during development

Use a decide gate for a real development trade-off; keep explain/propose for deliberate
learning. Opening questions and ordinary challenges are recorded automatically when
the agent ends its turn, with no bookkeeping tool call. Assessments still check your
reasoning before work opens.

After a verdict, reply with your conclusion and reasons in plain words. You do not
need to repeat it with a `reflect:` prefix; explicit prefixes still work. Cards wait
until you request them. Vibe bootstraps its session once, then receives state through
CLI and tool results instead of fetching status on every turn.

Start a fresh host session after updating, especially Vibe: its plugin code is pinned
per session. These changes remove Elenchus round trips; model/server latency can
still dominate a response. See [the measured comparison](docs/performance.md).

## Your knowledge graph

Every gate you pass becomes a note in one folder shared by all your projects: `~/.config/elenchus/graph` (set `ELENCHUS_GRAPH` to put it elsewhere, for example inside an Obsidian vault). One Markdown note per topic, with your own words, how it works, where else it applies, its limit and what you missed. `[[links]]` connect it to the project and to related notes, so Obsidian, Logseq or Foam show it as a graph without any conversion.

To see it in Obsidian, make that folder a link into your vault before the first note exists: `ln -s ~/path/to/vault/elenchus ~/.config/elenchus/graph`. A link reaches every host; an environment variable only reaches the ones started from a shell that exports it.

The agent reads it too, on every host and in every project. A new session is told the graph exists, and a new gate is shown the related notes. So three months later it does not redo the thinking for you: it reminds you of your own conclusion and asks you to recall it. When notes have gone a month without a visit, it offers `/elenchus:recall`, and passing that adds a new entry to the same note. `python3 plugins/elenchus/scripts/elenchus.py graph <words>` searches it from a terminal.

## Install

You need Python 3.8 or newer and Typst (`pip install typst`, or the Typst CLI). On Windows also Git for Windows. The examples assume the repository is cloned to `~/Documents/elenchus`.

**Claude Code CLI**

```sh
claude plugin marketplace add ~/Documents/elenchus      # Windows: "$env:USERPROFILE\Documents\elenchus"
claude plugin install elenchus@elenchus
claude plugin install elenchus-ui@elenchus              # optional: keeps the question above the input
```

**Claude desktop app** (Windows; Linux beta for Ubuntu and Debian): push the repository, then Customize > Plugins > Add marketplace > `mev0lent/elenchus`, and install `elenchus`. It runs in Cowork, not in the Chat tab. Without pushing: zip the contents of `plugins/elenchus` and upload the zip on the same page. Cowork runs the agent in its own Linux environment; if the PDF build reports that Typst is missing there, ask the agent to run `pip install typst` once.

**Mistral Vibe CLI**

```sh
# Linux, Vibe 3.1 or newer
mkdir -p ~/.vibe/plugins && ln -s ~/Documents/elenchus/plugins/elenchus ~/.vibe/plugins/elenchus
```

```bat
:: Windows, in cmd
mklink /J "%USERPROFILE%\.vibe\plugins\elenchus" "%USERPROFILE%\Documents\elenchus\plugins\elenchus"
```

Restart Vibe: hooks bind when a session starts. It is the same plugin folder as for Claude Code and Codex.

**ChatGPT desktop app and Codex CLI** (Windows; Linux preview for Ubuntu, Debian and Fedora): `codex plugin marketplace add ~/Documents/elenchus` (Windows: `"$env:USERPROFILE\Documents\elenchus"`), restart the app, install `elenchus` from the Plugins Directory, and trust its hooks when asked (`/hooks`). Without trusted hooks, nothing is enforced.

Plugins load in every session. Gates start when you use a command, unless you opt into always-on mode.

**Check:** `/elenchus:learn explain TLS handshakes` should get exactly one question and no explanation.

## The paper

`/elenchus:paper` creates it with five sections. Only the last part of a decision is prose.

| Section | What goes in |
| --- | --- |
| Purpose | Numbered claims, one line each: what must hold for the project to be worth anything. |
| Notation | Every symbol, defined exactly once. |
| Model | Your formal statements, each numbered and labeled. |
| Decisions | One line per decision, pointing to its formal statement. Below it, only why. |
| Limits and open questions | What the model does not cover. |

```typst
= Notation
#symbols(($tau$, [gate threshold on $P("normal" | x)$]), ($A$, [set of anomalous responses]))

= Model
$ "archive"(x) <==> P("normal" | x) >= tau $ <eq-gate>

#invariant("no test leakage")[$tau = f(D_"dev")$, and $f$ never reads $D_"test"$.] <inv-leak>

#algorithm("Triage", input: [$x$], output: [archive or escalate])[
  + $p <- P("normal" | x)$
  + *if* $p >= tau$ *then* archive *else* escalate
] <alg-triage>

= Decisions
#decision("Archive iff P(normal) >= tau", origin: "mine", formal: (<eq-gate>, <alg-triage>), where: "gatelib.mjs:12")
Rejected: a fixed top-k per batch, because the anomaly rate varies between targets.
```

Equations, definitions, invariants and algorithms are numbered, and the PDF cites them ("Formal: Equation 1, Algorithm 1"). Typst refuses to build the PDF if a decision points to a label that does not exist.

| A decision line | Means |
| --- | --- |
| `origin: "inherited"` | In the project, not yours yet. The agent logs these on its own, never formalized. |
| `origin: "mine"`, no `formal:` | Your decision, but not stated formally. It cannot be owned yet. |
| `origin: "mine", formal: <…>` | Formalized and ready for `/elenchus:own`. |
| `gate: "<id>"` | Owned. Only `/elenchus:own` sets this. Your words from the gate are below it, the full record is in `gates/`. |

Keep each `#decision` on one line. Nothing is marked in the code; `where:` points into it.

Cards you want to keep go next to the decision, one line each: `#card("Why >= at tau?", "Equality archives: tau is the lowest confidence I trust.")`. `/elenchus:paper` exports them to Anki, alongside the cards from your gates.

The PDF uses a subtle pastel palette, as colored edges and labels: definitions in sky, invariants in mint, algorithms in lavender, decisions by state (butter: yours, mint: owned, peach: inherited). For your own emphasis: `#mark[...]` highlights in rose, `#highlight[...]` in butter, `#note[...]` adds a remark. The palette sits at the top of each paper; change it there if you like.

## An existing project you want to own completely

1. **`/elenchus:paper`.** The agent asks where the paper lives: `docs/paper` in your own private repository, or a folder of your notes for anything public or not yours. For employer or client work it first asks whether you may keep notes outside their systems.
2. **Write `recall.md` first**, next to the paper, from memory, without the code and without the agent: what the project does, its parts, its main decisions and why, what you know you don't know. Commit it and never edit it.
3. **Let the agent list the decisions** it finds in the code. They enter the paper as `inherited`: what and where, never why, never a formula. Compare with your recall: what you missed or got wrong is where you start.
4. **Formalize one decision.** Define its symbols under Notation, write its statement under Model with a label, and point the decision to it with `formal: <label>`. If you disagree with the decision, formalize the better one and let the agent change the code.
5. **`/elenchus:own <decision>`.** The agent attacks your formalization: undefined symbols, boundary cases, whether the code really does what the statement says. Answer, derive, defend, finish with `reflect: <your conclusion and reasons>`.
6. **Repeat 4 and 5**, foundations first. If one gate covered several closely related decisions, the agent can bind it to each of them (`paper bind`), as long as each is formalized. You are done when `/elenchus:paper` says `OWNED`. When the code changes later, it tells you; own again what the change touched.

## A new project you want to own from the start

1. **`/elenchus:paper` before the first line of code.** Write the purpose as numbered claims.
2. **Formalize before you build.** Each decision you make goes into Notation, Model and Decisions as above. That is the design.
3. **Build with the agent as usual.** Every decision it makes on its own lands in the paper as `inherited`, automatically, in every session. Formalize the ones that matter and take them over, or replace them.
4. **`/elenchus:own` whenever you choose.** Building is never blocked. A good rule: everything owned before you publish the project or rely on it.

## Learning gates

| Mode | For | You start by |
| --- | --- | --- |
| `explain` | concepts, mechanisms | explaining it in your own words |
| `predict` | behavior of code | `predict: <output and why>` before a small example runs once |
| `propose` | designs, decisions | proposing; the agent attacks two assumptions |
| `decide` | one decision inside the work | stating your choice and the reason; one attack, no reflection step |
| `auto` | not sure | letting the agent pick |

You answer in plain words and finish with `reflect: …` (or `agree:` / `disagree:`). You pass when your reflection shows how it works, applies it to a new case and names a limit. Passing opens the work and writes the note into your knowledge graph. Reasoned disagreement passes too. If you are stuck, say so: you get a smaller question, then one hint.

How the gates are enforced on each host, the repository layout and the tests: [docs/internals.md](docs/internals.md).

## Releases

The core plugin uses SemVer across all three hosts; the optional UI is versioned separately. See [release instructions](docs/releases.md) and [changes](CHANGELOG.md).
