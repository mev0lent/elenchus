# Elenchus internals

How the gates are enforced on each host, and how the owner's paper works. For installation and daily use, see the [README](../README.md).

## Repository layout

```
elenchus/
├── .claude-plugin/marketplace.json   marketplace for Claude Code and the Claude desktop app
├── .agents/plugins/marketplace.json  marketplace for Codex and the ChatGPT desktop app
├── docs/internals.md                 this file
└── plugins/
    ├── elenchus/        Claude Code, Cowork, Codex and Mistral Vibe: one engine, paper module, hooks, skills
    └── elenchus-ui/     optional, Claude Code CLI only: focus card above the input, themes
```

| Host | Gates and paper | Focus card |
| --- | --- | --- |
| Claude Code CLI | full | `elenchus-ui` |
| Claude desktop app, Cowork | full | no mods API |
| Claude desktop app, Chat tab | no, hooks do not run in chat | no |
| Mistral Vibe CLI (3.1+) | full, hooks read the session journal | no |
| ChatGPT desktop app and Codex CLI | full, hooks must be trusted | no |


## Keep the question in view (optional `elenchus-ui`, Claude Code CLI)

With `elenchus-ui` installed, the focus card stays directly above the input while tool calls and code scroll past:

```text
╭─────────────────────────────────────────────────────────────╮
│ YOUR TURN  Elenchus · TLS handshakes · round 1/1             │
│ What stops an attacker from impersonating the server?       │
│ answer the challenge                                        │
│ explain · /elenchus:focus full shows tool details            │
╰─────────────────────────────────────────────────────────────╯
```

The question has the strongest visual weight. The next action sits immediately below it. Purple means your turn, crimson means Claude is judging or setting up the next step, and teal means a work turn is open. Status is never communicated by color alone. On narrow terminals the secondary footer and round metadata drop away, keeping the question and next action. Very small terminals use Claude Code's scrollable band.

Successful internal Elenchus tool calls become one short line. Errors, interrupted calls, ordinary project tools, and actual prediction results remain visible. This only changes presentation; Claude still receives the full tool results.

- `/elenchus:focus`: repeat the current question and next step without advancing the gate.
- `/elenchus:focus full`: show full internal tool details.
- `/elenchus:focus compact`: return to the compact view (default).
- `/elenchus:status`: inspect the current gate and recorded violations.

The UI uses Claude Code's [mods API](https://code.claude.com/docs/en/plugins/mods/reference), and requires a build that supports function hooks. It is tested against 2.1.292. The UI is a separate plugin so that the gates run unchanged where the mods API does not exist.

## Predict a specific execution

Prediction gates are deliberately small Python or JavaScript examples:

1. Claude writes the example and calls `prepare --runtime python|node --file relative/path --question "..."`. Additional local imports or data use repeated `--source` arguments.
2. Elenchus records SHA-256 hashes of the registered files. You type your prediction.
3. The CLI `run` verifies the hashes and executes copies of those exact bytes once in a temporary working directory, with a ten-second timeout. Arbitrary Bash and PowerShell commands remain locked.
4. Claude shows the actual output beside your prediction and asks for your reflection. Your reflection is reviewed before the gate is completed or cards can be written.

If a source changes after registration, the prediction expires. Claude must register the new code and ask you to predict again. The run slot is consumed before execution, including on interruption or failure. Full project builds, dependency installation, and general shell work belong to open work, after a passed gate.

The temporary working directory reduces accidental project changes. It is **not an OS sandbox**: example code can still access absolute paths or external services. Use self-contained examples. The enforced boundary is the registered source snapshot and single execution, not isolation from the operating system.

## Sessions, history, and cards

Running gates live in `.elenchus/sessions/s-<hex-session-id>/state.json`. Every hook and CLI call uses the current session ID. Two Claude sessions cannot open or close each other's gates through the allowed CLI calls. OS file locks serialize changes within one session; unique temporary files make state writes atomic. Resuming the same session keeps its gate; a new session starts inactive. Old `.elenchus/state.json` learning records remain available as history, but its running gate is not copied into new sessions.

Completed learning records live in `.elenchus/history/`, shared across sessions. `status` exposes recent topics, your wording, mistakes, and assessment evidence to Claude. Connection cards are added only when a genuinely related earlier topic exists. The first topic needs no invented connection.

Cards land in `.elenchus/anki/basic.tsv` and `cloze.tsv`. In Anki, use File > Import. Headers set deck, note type, and tags; if your Anki version ignores them, pick Basic or Cloze and map the third column to tags. Card writes are serialized across sessions, and duplicate fronts are rejected. The plugin writes `.elenchus/.gitignore` so local learning records are ignored by Git.

## Four enforcement layers (Claude Code)

1. The Socratic skill defines the learning protocol, evidence criteria, help ladder, and concise replies.
2. SessionStart and UserPromptSubmit inject the rules and current phase, including the session-specific CLI prefix.
3. PreToolUse locks edits, arbitrary shell work, subagents, and non-read MCP calls. Predict allows example preparation before the prediction, then only the registered CLI run.
4. Stop detects long locked replies, headings, code fences, missing questions, and missing verdict/assessment moves. Ignored blocks produce a visible violation. It pins valid closing questions and records a valid question after a user attempt as the challenge, without a CLI call. Required rounds and subsequent user answers remain enforced; housekeeping never advances a gate. Explicit `challenge` remains compatible.

Understanding is still a model judgment. Evidence fields make that judgment explicit and reviewable; they cannot prove that a learner's reasoning is correct. Likewise, short answer leakage is a semantic problem that formatting checks cannot fully prevent.

Path checks guard the plugin, `.elenchus`, settings files, and `hooks.json`. Shell text scanning during open work is a speed bump, not protection against an adversarial model constructing a path from pieces. MCP read detection is based on tool names, not a guarantee about third-party behavior. The threat model is a model drifting away from a learning protocol.

## Open work and the knowledge graph

`assess --result accept` sets the phase to `open`, and it stays there: PreToolUse allows everything except the gate machinery, and Stop checks nothing. Only a new gate locks again, started by the user (`/elenchus:learn`, `/elenchus:own`) or by the agent with `gate --mode decide` when the work reaches a decision that is the user's to make. `idle` now only means an unreadable state file, which fails closed.

The same `accept` appends the gate to the note of its topic in the knowledge graph: `$ELENCHUS_GRAPH`, else `$ELENCHUS_DIR/graph`, else `~/.config/elenchus/graph`. The note name is the topic, so `[[topic]]` resolves in Obsidian. Edges are the project name and the notes the agent names in `assess --links "a, b"`. `graph <words>` ranks notes by shared words, title matches first; the briefing of a locked gate carries the three best matches, and SessionStart announces the graph in every project once it has a note. A failed graph write never fails the gate: the record is already in `.elenchus/history/`.

## Decide, delegate, recall, always-on

- `decide` is a fourth mode with one required challenge. `assess --result accept --note ...` is allowed from phase `attempted` once that challenge is answered; there is no verdict, reflection or evidence. The record keeps the first statement and the answer.
- `delegate: <remark>`, typed by the user in a decide or propose gate that is not an own gate, completes the gate with `how = "delegated"` and opens the work. The graph entry is headed `delegated`; recall skips such notes. The agent follows with `choice --note "<what I chose and why>"`: it appends `agent_choice` to this session's latest delegated record and a separately labeled line to that graph entry. It cannot replace a recorded choice or edit the user's words. Retrying the same choice repairs a failed graph update without duplicating the line. Delegations cannot bind ownership or supply learning cards.
- `/elenchus:recall [words]` starts an explain gate on the best match, or on the note with the oldest modification time, with the earlier entry in the briefing. Passing appends an entry headed `recall`, which makes the note the newest. SessionStart mentions notes older than 30 days.
- `/elenchus:always on|off` creates or removes `$ELENCHUS_ALWAYS`, else `~/.config/elenchus/always-on`. With the flag, a session without a state file loads as active and `open`. Open work writes nothing, so a project gets a `.elenchus` folder only when a gate starts there. `/elenchus:off` writes the state and wins for that session. `~/.config/elenchus` is protected like the rest of the machinery. On Vibe the open-work briefing only arrives when the agent runs `status`.
- Hooks and the CLI lock only a project whose `.elenchus` exists; `graph` and `paper status --all` touch no project at all.

## Mistral Vibe

Vibe 3.1 reads `plugins/elenchus` as a native Agent Plugins 1.0 plugin: the root `plugin.json` wins over the Claude and Codex manifests in the same folder, `skills/` holds the commands (shared with Claude Code), and `ai.mistral.vibe/hooks.toml` declares the hooks. Vibe parses Claude-format hooks but does not run them, so `hooks/hooks.json` is ignored there. The engine detects Vibe by `PLUGIN_ROOT` without `CLAUDE_PLUGIN_ROOT`.

1. Vibe has no prompt hook. `pre_tool` (`strict = true`) and `post_agent` read the user's typed words from the session journal (`<transcript_path>/journal/*.jsonl`) and feed every message newer than the last recorded timestamp through the same code as UserPromptSubmit. A message appears as input and as projection; it is recorded once per turn.
2. Vibe 3.1 has no prompt hook, but its `post_tool` hook can append context to a tool result. Elenchus delivers the current briefing on the first ordinary tool result of a locked turn, once; internal CLI calls return their own current state instead. `status --brief` is for bootstrapping or recovering missing context, not every turn. A bare `status` adopts the newest session and prints its exact session prefix; later calls must use that explicit ID. Full `status` still includes history and project notes for intentional inspection.
3. Tool names are qualified (`file_system.bash`, `skill.read`, `vibe.cron`). The policy matches the part after the group, and unknown tools stay locked.
4. Denials are `{"decision": "deny", "reason": ...}`. `post_agent` replaces Stop: the first violation of a turn is denied and handed back as a retry, the second is recorded and shown as a warning.
5. Hooks run from a pinned copy of the plugin, while the agent may call the installed one, so the CLI check accepts a byte-identical copy of the engine.
6. A strict hook denies the tool on any non-zero exit. `run.sh` therefore exits 0 when the engine cannot run and no gate is active, so a broken install never blocks ordinary work. Skill names are quoted: a bare `name: off` is the YAML boolean false and Vibe refuses the skill.

## Colors and themes

The palette remains cream `#FBF5F3`, purple `#7D5BA6`, navy `#000022`, teal `#3BCEAC`, and crimson `#C42847`. Cream is used for questions and teal for the next action on navy. Purple and crimson serve as badge backgrounds and borders, because they are not readable as small text on navy. Palette tests check contrast and the Anki CSS.

The card styling is `plugins/elenchus/anki/elenchus-card.css`. Both light and night modes are supported, with distinct connection and mistake blocks.

The optional **Elenchus** and **Elenchus Light** themes ship with `elenchus-ui` and are available through `/theme` on compatible builds. They change the CLI palette; the focus card handles hierarchy and question visibility. Claude Code does not set the terminal background. For the full dark palette, set your terminal background to `#000022`. After changing `plugins/elenchus-ui/hooks/palette.ts`, run `python plugins/elenchus-ui/scripts/gen_theme.py`; theme tests detect stale generated files.

## Codex

Codex implements the same hook protocol as Claude Code: the same event names, `permissionDecision: "deny"` for PreToolUse, `decision: "block"` on Stop, exit code 2, and it sets `CLAUDE_PLUGIN_ROOT` for compatibility. So one engine and one `hooks/hooks.json` serve both. Codex reads `.codex-plugin/plugin.json` and lists the shared `skills/` folder as `elenchus:learn`, `elenchus:off` and so on. Its hooks run only after the user has trusted them (`/hooks`).

What the engine adapts when `PLUGIN_ROOT` and `CLAUDE_PLUGIN_ROOT` are both set:

1. File edits arrive as `apply_patch`. It counts as a write tool, and the target paths are read from the patch text (`*** Update File:`, `*** Move to:`), so the machinery protection still holds.
2. Shell input may be a string, an argv list (`["bash", "-lc", "..."]`) or `cmd`. All three are normalized before the CLI check.
3. `update_plan` and `view_image` stay available while locked. Hosted tools such as web search are not intercepted by Codex hooks at all.
4. Commands are recognized as `elenchus learn ...`, `$elenchus:learn ...` or `$elenchus-learn ...`, because Codex plugins have no slash commands.
5. Wording names Codex and the shell tool instead of Claude and Bash.

`tests/test_codex.py` replays Codex payloads against the engine, including the full Claude suite under the Codex environment. It does not replace a live Codex session. Codex's own documentation calls hooks "a useful guardrail, not a complete enforcement boundary"; the threat model here is the same as on Claude Code: a model drifting away from a learning protocol, not an adversary. Codex installs a cached copy of the plugin: after a change, bump the version and reinstall.

## The owner's paper

The paper is handled by `scripts/paper.py`. It is Typst and defines its helpers itself (`#symbols`, `#definition`, `#invariant`, `#algorithm`, `#decision`), so it builds with plain Typst and no package. Reading decisions needs no Typst: each `#decision` is one line, read with a regex. Building the PDF (`paper build`) uses the Typst CLI or the `typst` Python package.

- `/elenchus:paper` is housekeeping and never starts a gate. Without a paper, the hook tells the agent to ask where it should live and run `paper init --path <folder> --name <project>`. That writes the template and records the path in `.elenchus/paper`, which stays local and out of Git, so a paper for a public repository leaves no trace in it. With a paper, the agent runs `paper status` and `paper build`.
- Whenever a paper exists, SessionStart tells the agent to log its own decisions as `inherited` lines, never to formalize a decision for the user, and never to write a reason (Claude Code, Cowork, Codex). Vibe has no session hook; it gets the same note, and the knowledge graph note, whenever it runs `status` while Elenchus is active.
- `/elenchus:own <title>` first checks readiness (`paper check --title` shows the same): the decision must exist (title matched case-insensitively), carry `formal:`, and every label must be defined in the paper, meaning it follows the closing `$`, `]` or `)` of a statement. Otherwise the gate does not start and the user is told what is missing.
- A ready decision starts a propose gate (two challenges). Its briefing carries the source of the formal statements and tells the agent to attack the formalism: undefined symbols, boundaries, code versus statement, termination and cost, rejected alternatives.
- On `assess --result accept` the engine binds the gate: it copies the gate record (the user's words, the assessed evidence) to `gates/<id>.json` next to the paper, adds `origin: "mine", gate: "<id>"` to the decision line while keeping `formal:` and `where:`, and puts the user's reflection below it. `/elenchus:learn` or `/elenchus:off` before acceptance cancels the binding.
- `paper status` counts owned, untested and inherited decisions and flags `[not formalized]`. A decision counts as owned only if its gate record exists and carries evidence. If the paper lives in the project's Git repository, status also reports commits since the paper was last committed. `paper bind --title <t> [--gate <id>]` binds a gate passed earlier in this project, in any session, to another formalized decision; without `--gate` it takes the latest.

- `paper init` also records the paper in `~/.config/elenchus/papers.json` (or `$ELENCHUS_PAPERS`), outside every repository; `paper status --all` (`/elenchus:paper all`) reads it for the overview.
- `paper cards` exports single-line `#card("question", "answer")` entries to `.elenchus/anki/paper-<project>.tsv`, deck `Elenchus::Papers::<project>`, regenerated from the paper each time.

This protects against drifting into passive use, not against forgery: a hand-written gate record would pass. Whether a gate is passed is still a model judgment; the evidence makes it reviewable.

## Runtime and tests

Requirements: Python 3.8+, `sh` (Git for Windows provides it), and Node.js only for JavaScript prediction examples. `scripts/run.sh` finds a working Python and skips Microsoft Store stubs. If the engine cannot run, PreToolUse fails closed whenever it finds an active or unreadable state in the project. Without Python it conservatively considers every session here, because it cannot safely parse the session ID. Restore Python before trying to disable a gate.

The reply cap is `ELENCHUS_MAX_WORDS` (default 80); required probe rounds are `MIN_ROUNDS` in `scripts/elenchus.py`. Learner answers have no hard word minimum.

```sh
python plugins/elenchus/tests/test_gates.py
python plugins/elenchus/tests/test_codex.py
python plugins/elenchus/tests/test_crossos.py
python plugins/elenchus/tests/test_launcher.py
python plugins/elenchus-ui/tests/test_palette.py
python plugins/elenchus-ui/tests/test_theme.py
python plugins/elenchus/tests/test_vibe.py
python plugins/elenchus/tests/test_paper.py
claude plugin validate .
claude plugin test plugins/elenchus-ui
```

Integration tests cover short answers, disagreement, mandatory review, evidence, hints, registered executions, source changes, imports, session isolation, concurrent writes, cards, focus commands, open work and the knowledge graph, replayed in the Claude, Codex and Vibe dialects; the Vibe suite adds journal-driven prompt recording, qualified tool names, retry-message filtering, and the post_agent retry and warning flow. Mods tests run against the real UI engine, including narrow layouts and full/compact tool rendering. A headless Claude Code smoke test also verified activation, the first Socratic question, and its persisted focus state. These checks do not replace a live interactive learning session.

For a live check, start a learning gate in a throwaway project, verify the question remains beside the input, ask for a premature file edit, and check that it is denied. Open a second session and confirm its gate is independent. Use `elenchus learn explain <topic>` if slash-command expansion is unavailable; command files also carry an `ELENCHUS-COMMAND` marker.
