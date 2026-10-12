# Elenchus

A learning-gate plugin that protects your own thinking. Explain, predict, or propose first. The agent probes your reasoning, and work opens only after your understanding has been assessed. A well-reasoned disagreement counts as success.

The name is the Greek word for Socratic cross-examination.

## Two plugins, one protocol

The repository packages the same learning protocol for two CLIs:

```
elenchus/
├── claude/    Claude Code plugin: commands, hooks, skill, themes, UI module
├── mistral/   Mistral Vibe plugin: skills, pre_tool and post_agent hooks
└── README.md
```

Both carry the same gate engine design, the CLI vocabulary (`gate`, `challenge`, `verdict`, `assess`, `prepare`, `run`, `question`, `status`, `cards`), the session-scoped state under `.elenchus/`, and the Anki card output. Where the platforms differ, each folder carries its own adaptation; the differences are listed under "The Mistral Vibe port" below.

## Start learning

Start Claude Code from your learning project, rather than the plugin's own directory:

```sh
claude --plugin-dir C:/Users/you/Documents/elenchus/claude
```

Then type `/elenchus:learn explain TLS handshakes`. Use `/reload-plugins` after updating the plugin. Commands are `learn`, `off`, `status`, `focus`, and `cards`, all under `/elenchus:`. `/elenchus:off` disables gates for this session.

For Mistral Vibe, put `mistral/` into a plugins directory and start Vibe in your learning project:

```sh
# user scope (every project)
mkdir -p ~/.vibe/plugins && cp -r mistral ~/.vibe/plugins/elenchus
# or project scope, inside a trusted folder
mkdir -p .vibe/plugins && cp -r mistral .vibe/plugins/elenchus
```

On Windows, `mklink /J "%USERPROFILE%\.vibe\plugins\elenchus" "...Documents\elenchus\mistral"` links the folder instead of copying. Then type `/elenchus:learn explain TLS handshakes`; the commands are the same five skills under `/elenchus:`, and `/reload-plugins` picks up updates.

| Mode | Your first move | Claude's job |
| --- | --- | --- |
| `explain` | Explain the mechanism in your own words | Probe a new case, check a limit, then assess your conclusion |
| `predict` | `predict: <output and why>` for registered code | Run that exact example once, compare the output, then assess your reasoning |
| `propose` | Propose your design | Challenge two assumptions; accept a justified defense or revision |
| `auto` | Name the topic | Choose the appropriate mode |

For the final reflection, type `reflect: <your conclusion and reasons>`. `agree:` and `disagree:` also work. They record your reasoning; they do not automatically open a gate. Claude must register evidence of the mechanism, transfer to a new case, and a limitation. If evidence is missing, it asks another question. One accepted reflection opens one turn of work, then the gate locks again.

Concise answers count. Word lengths never determine whether you understood. When stuck, the help ladder is: your attempt, a smaller question, one minimal hint, another attempt. Claude challenges your reasoning respectfully.

## Keep the question in view (Claude Code)

The focus card stays directly above the input while tool calls and code scroll past:

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

The UI uses Claude Code's [mods API](https://code.claude.com/docs/en/plugins/mods/reference), and requires a build that supports function hooks. It is tested against 2.1.292. The command hooks and learning gates also work without the UI module on compatible plugin builds.

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

`mistral/` is a native Agent Plugins 1.0 plugin (`plugin.json` plus an `ai.mistral.vibe` extension) with the same engine, the same CLI, and the same state and cards. Vibe offers fewer hook events than Claude Code, so the enforcement wiring differs:

1. Vibe has no prompt hook. The `pre_tool` hook (`ai.mistral.vibe/hooks.toml`, `strict = true`) reads the user's typed words from the session transcript at the first tool call of a turn, so attempts, predictions, reflections, and `/elenchus:` commands are recorded before the reply is judged. A `post_agent` fallback covers turns without tool calls.
2. There is no injected briefing either. The skill instructs the agent to run `status` at the start of a turn; a bare `status` adopts the newest session and prints the exact CLI prefix, and every locked-tool denial repeats that prefix.
3. The `post_agent` hook replaces the Stop hook: a violating reply is denied and the reason is injected as a retry message, so the agent can fix it within the same user turn. A repeated violation is recorded and shown to the user as a warning.
4. There is no focus-card UI and no theme support; the pinned question lives in the state and surfaces through `status` and `/elenchus:focus`. Commands are user-invocable skills (`learn`, `off`, `status`, `focus`, `cards`), and the Socratic protocol itself is the model-only `socratic` skill.

Tool gating uses Vibe tool names (`bash`, `git_bash`, `powershell`, `write_file`, `edit`, `run_typescript`, subagents, `connector_*` and `mcp__*` tools), and the machinery protection covers `.vibe/` and `hooks.toml` in addition to `.elenchus/` and the plugin tree. Sessions stay isolated by Vibe session ID, exactly as on Claude Code.

## Colors and themes (Claude Code)

The palette remains cream `#FBF5F3`, purple `#7D5BA6`, navy `#000022`, teal `#3BCEAC`, and crimson `#C42847`. Cream is used for questions and teal for the next action on navy. Purple and crimson serve as badge backgrounds and borders, because they are not readable as small text on navy. Palette tests check contrast and the Anki CSS.

For Anki, paste `anki/elenchus-card.css` (identical in `claude/anki/` and `mistral/anki/`) into your note type's Cards > Styling. Both light and night modes are supported, with distinct connection and mistake blocks.

The optional **Elenchus** and **Elenchus Light** themes are available through `/theme` on compatible builds. They change the CLI palette; the focus card handles hierarchy and question visibility. Claude Code does not set the terminal background. For the full dark palette, set your terminal background to `#000022`. After changing `hooks/palette.ts`, run `python scripts/gen_theme.py`; theme tests detect stale generated files.

## Runtime and tests

Requirements: Python 3.8+, `sh` (Git for Windows provides it), and Node.js only for JavaScript prediction examples. `scripts/run.sh` finds a working Python and skips Microsoft Store stubs. If the engine cannot run, PreToolUse fails closed whenever it finds an active or unreadable state in the project. Without Python it conservatively considers every session here, because it cannot safely parse the session ID. Restore Python before trying to disable a gate.

The reply cap is `ELENCHUS_MAX_WORDS` (default 80); required probe rounds are `MIN_ROUNDS` in `scripts/elenchus.py` (identical in both plugins). Learner answers have no hard word minimum.

```sh
python claude/tests/test_gates.py
python claude/tests/test_crossos.py
python claude/tests/test_palette.py
python claude/tests/test_theme.py
python claude/tests/test_launcher.py
python mistral/tests/test_gates.py
claude plugin test claude
claude plugin validate claude
```

Integration tests cover short answers, disagreement, mandatory review, evidence, hints, registered executions, source changes, imports, session isolation, concurrent writes, cards, and focus commands, on both engines; the mistral suite adds transcript-driven prompt recording, retry-message filtering, and the post_agent nudge and warning flow. Mods tests run against the real UI engine, including narrow layouts and full/compact tool rendering. A headless Claude Code smoke test also verified activation, the first Socratic question, and its persisted focus state. These checks do not replace a live interactive learning session.

For a live check, start a learning gate in a throwaway project, verify the question remains beside the input, ask for a premature file edit, and check that it is denied. Open a second session and confirm its gate is independent. Use `elenchus learn explain <topic>` if slash-command expansion is unavailable; command files also carry an `ELENCHUS-COMMAND` marker.
