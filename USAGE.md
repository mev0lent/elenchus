# Usage guide

A one-page reference: what to type, and what it is for. Installation is in the [README](README.md).

## The idea in two lines

**Elenchus** makes you think first: you explain, predict or propose, the agent probes, and work opens only after your understanding is assessed.
**Ownership** keeps each project's decisions in one paper, and a decision only counts as yours once you passed an Elenchus gate on it.

## Elenchus commands

| Claude Code, Cowork, Vibe | Codex | What it does |
| --- | --- | --- |
| `/elenchus:learn <mode> <topic>` | `elenchus learn <mode> <topic>` | Starts a gate for this session. Modes below. |
| `/elenchus:status` | `elenchus status` | Shows mode, topic, phase and what happens next. |
| `/elenchus:focus` | `elenchus focus` | Repeats the current question. `full` / `compact` switch the focus card's tool view (`elenchus-ui` only). |
| `/elenchus:cards` | `elenchus cards` | Writes Anki cards for the last passed gate. |
| `/elenchus:off` | `elenchus off` | Turns gates off for this session. Only you can type it. |

| Mode | Use it for | Your first move |
| --- | --- | --- |
| `explain` | concepts, mechanisms, theory | Explain it from scratch in your own words. |
| `predict` | behavior of code | The agent writes a small example; you type `predict: <output and why>` before it runs once. |
| `propose` | designs and decisions | Propose; the agent attacks two assumptions; you defend or revise. |
| `auto` | not sure | The agent picks the mode. |

## What you type during a gate

| Input | Meaning |
| --- | --- |
| any answer | Your attempt or your answer to a challenge. Short is fine. |
| `predict: ...` | Your prediction in a predict gate. |
| `reflect: ...` | Your conclusion and reasons at the end of a gate. |
| `agree: ...` / `disagree: ...` | Same as reflect, with your stance. Disagreeing with reasons counts as success. |

A gate passes when your reflection shows the mechanism, a transfer to a new case and a limit. The agent then works for one turn and the gate closes again. Stuck? Say so: you get a smaller question first, then one minimal hint.

## Ownership commands

The skill is `/ownership:paper` (Codex: mention `$paper`). The agent uses it on its own in projects that have a paper. The script does the bookkeeping:

```sh
O=<repo>/plugins/ownership/scripts/ownership.py
```

| Command | What it is for |
| --- | --- |
| `python $O install` | Once per machine: installs the Typst package `@local/ownership`. |
| `python $O init docs/paper --name <project>` | Creates a new paper (Purpose, Decisions, Limits). Never overwrites. |
| `python $O own <paper> "<decision title>"` | After you passed a gate on that decision: binds the gate to it. Run it in the project where the gate ran. `--gate <id>` reuses a gate for a related decision. |
| `python $O ledger -v` | Overview of all papers: owned or not, open decisions, code changed since the paper. |
| `python $O cards <paper>` | Exports the paper's cards to Anki. |
| `python $O config` | Shows where your config is expected and what it contains. |

In the paper you only ever write two things:

```typst
#decision("Gate threshold chosen on the dev split", origin: "mine", where: "gatelib.mjs:12")
Your reason: why this, what you rejected, what would change your mind.
#card("Why is the threshold chosen on dev, not test?", "Your answer in your words.")
```

| State | Means | How it changes |
| --- | --- | --- |
| `origin: "inherited"` | In the project, not yours yet. The agent logs these. | Write the why, or replace it with a better decision. |
| `origin: "mine"` | Your decision, with your reason. Not tested. | Pass a gate on it, then run `own`. |
| `gate: "<id>"` | Owned. Set only by `own`. | Stays, unless the gate record in `gates/` goes missing. |

A project is owned when every decision is owned. Keep each `#decision` on one line, because `own` edits it.

## Workflows

**New project.** `init` a paper. Add one line to `CLAUDE.md` (or `AGENTS.md` for Codex and Vibe): *"This project has an owner's paper in docs/paper/main.typ. Use the paper skill and log every decision you make on your own as inherited."* Write your decisions as you make them; let the agent build. Gate decisions whenever you like.

**Existing project.** `init` a paper, then ask the agent to list the decisions it finds in the code as inherited. If you want a recall check, write down what you remember first. Then work through the list.

**Owning a decision.** Write its why, `/elenchus:learn propose <decision title>`, answer and defend, `reflect: ...`, then `own <paper> "<decision title>"`.

**Weekly look.** `ledger -v`. Anything flagged with code changes since the paper is worth a fresh gate.

## Where things live

| Path | Contents | In Git? |
| --- | --- | --- |
| `.elenchus/` in the project | Gate state, history, Elenchus cards (`anki/basic.tsv`, `cloze.tsv`) | No, ignored automatically |
| `docs/paper/main.typ` | The paper of a private repository you own | Yes |
| `docs/paper/gates/` | Copies of passed gates: your words and the evidence | Yes |
| `<library>/projects/<name>/` | Papers for public repositories and code you do not own | In your library |
| `~/.config/ownership/config.json` | Library path, private project list, Anki folder | No, personal |

**Anki:** File > Import the `.tsv` files. For the card styling, paste `plugins/elenchus/anki/elenchus-card.css` into the note type's Styling.
