# Elenchus internals

How the gates are enforced on each host, and how the owner's paper works. For installation and daily use, see the [README](../README.md).

## Repository layout

```
elenchus/
├── .claude-plugin/marketplace.json   marketplace for Claude Code and the Claude desktop app
├── .agents/plugins/marketplace.json  marketplace for Codex and the ChatGPT desktop app
├── docs/internals.md                 this file
└── plugins/
    ├── elenchus/        Claude Code, Cowork and Codex: engine, paper module, hooks, commands, skills
    ├── elenchus-vibe/   Mistral Vibe: same protocol and paper module, Vibe's hook wiring
    └── elenchus-ui/     optional, Claude Code CLI only: focus card above the input, themes
```

| Host | Gates and paper | Focus card |
| --- | --- | --- |
| Claude Code CLI | full | `elenchus-ui` |
| Claude desktop app, Cowork | full | no mods API |
| Claude desktop app, Chat tab | no, hooks do not run in chat | no |
| Mistral Vibe CLI | full, via `elenchus-vibe` | no |
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

If a source changes after registration, the prediction expires. Claude must register the new code and ask you to predict again. The run slot is consumed before execution, including on interruption or failure. Full project builds, dependency installation, and general shell work belong to an assessed open turn.

The temporary working directory reduces accidental project changes. It is **not an OS sandbox**: example code can still access absolute paths or external services. Use self-contained examples. The enforced boundary is the registered source snapshot and single execution, not isolation from the operating system.

## Sessions, history, and cards

Running gates live in `.elenchus/sessions/s-<hex-session-id>/state.json`. Every hook and CLI call uses the current session ID. Two Claude sessions cannot open or close each other's gates through the allowed CLI calls. OS file locks serialize changes within one session; unique temporary files make state writes atomic. Resuming the same session keeps its gate; a new session starts inactive. Old `.elenchus/state.json` learning records remain available as history, but its running gate is not copied into new sessions.

Completed learning records live in `.elenchus/history/`, shared across sessions. `status` exposes recent topics, your wording, mistakes, and assessment evidence to Claude. Connection cards are added only when a genuinely related earlier topic exists. The first topic needs no invented connection.

Cards land in `.elenchus/anki/basic.tsv` and `cloze.tsv`. In Anki, use File > Import. Headers set deck, note type, and tags; if your Anki version ignores them, pick Basic or Cloze and map the third column to tags. Card writes are serialized across sessions, and duplicate fronts are rejected. The plugin writes `.elenchus/.gitignore` so local learning records are ignored by Git.

## Four enforcement layers (Claude Code)

1. The Socratic skill defines the learning protocol, evidence criteria, help ladder, and concise replies.
2. SessionStart and UserPromptSubmit inject the rules and current phase, including the session-specific CLI prefix.
3. PreToolUse locks edits, arbitrary shell work, subagents, and non-read MCP calls. Predict allows example preparation before the prediction, then only the registered CLI run.
4. Stop detects long locked replies, headings, code fences, missing questions, and unregistered moves. Ignored blocks produce a visible violation. It also pins valid learner-facing questions as a fallback if Claude did not register them explicitly.

Understanding is still a model judgment. Evidence fields make that judgment explicit and reviewable; they cannot prove that a learner's reasoning is correct. Likewise, short answer leakage is a semantic problem that formatting checks cannot fully prevent.

Path checks guard the plugin, `.elenchus`, settings files, and `hooks.json`. Shell text scanning during open turns is a speed bump, not protection against an adversarial model constructing a path from pieces. MCP read detection is based on tool names, not a guarantee about third-party behavior. The threat model is a model drifting away from a learning protocol.

## The Mistral Vibe port

`plugins/elenchus-vibe/` is a native Agent Plugins 1.0 plugin (`plugin.json` plus an `ai.mistral.vibe` extension) with the same engine, the same CLI, and the same state and cards. Vibe offers fewer hook events than Claude Code, so the enforcement wiring differs:

1. Vibe has no prompt hook. The `pre_tool` hook (`ai.mistral.vibe/hooks.toml`, `strict = true`) reads the user's typed words from the session transcript at the first tool call of a turn, so attempts, predictions, reflections, and `/elenchus:` commands are recorded before the reply is judged. A `post_agent` fallback covers turns without tool calls.
2. There is no injected briefing either. The skill instructs the agent to run `status` at the start of a turn; a bare `status` adopts the newest session and prints the exact CLI prefix, and every locked-tool denial repeats that prefix.
3. The `post_agent` hook replaces the Stop hook: a violating reply is denied and the reason is injected as a retry message, so the agent can fix it within the same user turn. A repeated violation is recorded and shown to the user as a warning.
4. There is no focus-card UI and no theme support; the pinned question lives in the state and surfaces through `status` and `/elenchus:focus`. Commands are user-invocable skills (`learn`, `off`, `status`, `focus`, `cards`), and the Socratic protocol itself is the model-only `socratic` skill.

Tool gating uses Vibe tool names (`bash`, `git_bash`, `powershell`, `write_file`, `edit`, `run_typescript`, subagents, `connector_*` and `mcp__*` tools), and the machinery protection covers `.vibe/` and `hooks.toml` in addition to `.elenchus/` and the plugin tree. Sessions stay isolated by Vibe session ID, exactly as on Claude Code.

## Colors and themes

The palette remains cream `#FBF5F3`, purple `#7D5BA6`, navy `#000022`, teal `#3BCEAC`, and crimson `#C42847`. Cream is used for questions and teal for the next action on navy. Purple and crimson serve as badge backgrounds and borders, because they are not readable as small text on navy. Palette tests check contrast and the Anki CSS.

The card styling `anki/elenchus-card.css` is identical in `plugins/elenchus/anki/` and `plugins/elenchus-vibe/anki/`; a test keeps them equal. Both light and night modes are supported, with distinct connection and mistake blocks.

The optional **Elenchus** and **Elenchus Light** themes ship with `elenchus-ui` and are available through `/theme` on compatible builds. They change the CLI palette; the focus card handles hierarchy and question visibility. Claude Code does not set the terminal background. For the full dark palette, set your terminal background to `#000022`. After changing `plugins/elenchus-ui/hooks/palette.ts`, run `python plugins/elenchus-ui/scripts/gen_theme.py`; theme tests detect stale generated files.

## The Codex port

Codex implements the same hook protocol as Claude Code: the same event names, `permissionDecision: "deny"` for PreToolUse, `decision: "block"` on Stop, exit code 2, and it sets `CLAUDE_PLUGIN_ROOT` for compatibility. So `plugins/elenchus` serves both hosts from one engine and one `hooks/hooks.json`. Codex reads `.codex-plugin/plugin.json`, which points it at `codex/skills/` (the Socratic skill with Codex tool names, plus `elenchus-learn`, `elenchus-paper`, `elenchus-own`, `elenchus-off`, `elenchus-status`, `elenchus-focus`, `elenchus-cards`). Claude Code ignores both.

What the engine adapts when `PLUGIN_ROOT` is set (Codex sets it, Claude Code does not):

1. File edits arrive as `apply_patch`. It counts as a write tool, and the target paths are read from the patch text (`*** Update File:`, `*** Move to:`), so the machinery protection still holds.
2. Shell input may be a string, an argv list (`["bash", "-lc", "..."]`) or `cmd`. All three are normalized before the CLI check.
3. `update_plan` and `view_image` stay available while locked. Hosted tools such as web search are not intercepted by Codex hooks at all.
4. Commands are recognized as `elenchus learn ...` (likewise `paper`, `own`), `$elenchus-learn ...` or `$elenchus:learn ...`, because Codex plugins have no slash commands.
5. Wording names Codex and the shell tool instead of Claude and Bash.

`tests/test_codex.py` replays Codex payloads against the engine, including the full Claude suite under the Codex environment. It does not replace a live Codex session. Codex's own documentation calls hooks "a useful guardrail, not a complete enforcement boundary"; the threat model here is the same as on Claude Code: a model drifting away from a learning protocol, not an adversary.

## The owner's paper

`scripts/paper.py` is shared byte for byte by both engines (a test keeps the copies equal). The paper is Typst and defines its helpers itself (`#symbols`, `#definition`, `#invariant`, `#algorithm`, `#decision`), so it builds with plain Typst and no package. Reading decisions needs no Typst: each `#decision` is one line, read with a regex. Building the PDF (`paper build`) uses the Typst CLI or the `typst` Python package.

- `/elenchus:paper` is housekeeping and never starts a gate. Without a paper, the hook tells the agent to ask where it should live and run `paper init --path <folder> --name <project>`. That writes the template and records the path in `.elenchus/paper`, which stays local and out of Git, so a paper for a public repository leaves no trace in it. With a paper, the agent runs `paper status` and `paper build`.
- Whenever a paper exists, SessionStart tells the agent to log its own decisions as `inherited` lines, never to formalize a decision for the user, and never to write a reason (Claude Code, Cowork, Codex). Vibe has no session hook; it gets the same note whenever it runs `status`.
- `/elenchus:own <title>` first checks readiness (`paper check --title` shows the same): the decision must exist (title matched case-insensitively), carry `formal:`, and every label must be defined in the paper, meaning it follows the closing `$`, `]` or `)` of a statement. Otherwise the gate does not start and the user is told what is missing.
- A ready decision starts a propose gate (two challenges). Its briefing carries the source of the formal statements and tells the agent to attack the formalism: undefined symbols, boundaries, code versus statement, termination and cost, rejected alternatives.
- On `assess --result accept` the engine binds the gate: it copies the gate record (the user's words, the assessed evidence) to `gates/<id>.json` next to the paper, adds `origin: "mine", gate: "<id>"` to the decision line while keeping `formal:` and `where:`, and puts the user's reflection below it. `/elenchus:learn` or `/elenchus:off` before acceptance cancels the binding.
- `paper status` counts owned, untested and inherited decisions and flags `[not formalized]`. A decision counts as owned only if its gate record exists and carries evidence. If the paper lives in the project's Git repository, status also reports commits since the paper was last committed. `paper bind --title <t> [--gate <id>]` binds a gate passed earlier in this project, in any session, to another formalized decision; without `--gate` it takes the latest.

- `paper init` also records the paper in `~/.config/elenchus/papers.json` (or `$ELENCHUS_PAPERS`), outside every repository; `paper status --all` (`/elenchus:paper all`) reads it for the overview.
- `paper cards` exports single-line `#card("question", "answer")` entries to `.elenchus/anki/paper-<project>.tsv`, deck `Elenchus::Papers::<project>`, regenerated from the paper each time.

This protects against drifting into passive use, not against forgery: a hand-written gate record would pass. Whether a gate is passed is still a model judgment; the evidence makes it reviewable.

## Runtime and tests

Requirements: Python 3.8+, `sh` (Git for Windows provides it), and Node.js only for JavaScript prediction examples. `scripts/run.sh` finds a working Python and skips Microsoft Store stubs. If the engine cannot run, PreToolUse fails closed whenever it finds an active or unreadable state in the project. Without Python it conservatively considers every session here, because it cannot safely parse the session ID. Restore Python before trying to disable a gate.

The reply cap is `ELENCHUS_MAX_WORDS` (default 80); required probe rounds are `MIN_ROUNDS` in `scripts/elenchus.py` (identical in both plugins). Learner answers have no hard word minimum.

```sh
python plugins/elenchus/tests/test_gates.py
python plugins/elenchus/tests/test_codex.py
python plugins/elenchus/tests/test_crossos.py
python plugins/elenchus/tests/test_launcher.py
python plugins/elenchus-ui/tests/test_palette.py
python plugins/elenchus-ui/tests/test_theme.py
python plugins/elenchus-vibe/tests/test_gates.py
python plugins/elenchus/tests/test_paper.py
claude plugin validate .
claude plugin test plugins/elenchus
```

Integration tests cover short answers, disagreement, mandatory review, evidence, hints, registered executions, source changes, imports, session isolation, concurrent writes, cards, and focus commands, on both engines; the mistral suite adds transcript-driven prompt recording, retry-message filtering, and the post_agent nudge and warning flow. Mods tests run against the real UI engine, including narrow layouts and full/compact tool rendering. A headless Claude Code smoke test also verified activation, the first Socratic question, and its persisted focus state. These checks do not replace a live interactive learning session.

For a live check, start a learning gate in a throwaway project, verify the question remains beside the input, ask for a premature file edit, and check that it is denied. Open a second session and confirm its gate is independent. Use `elenchus learn explain <topic>` if slash-command expansion is unavailable; command files also carry an `ELENCHUS-COMMAND` marker.
