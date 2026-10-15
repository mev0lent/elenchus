# Elenchus

A learning-gate plugin that protects your own thinking. Explain, predict, or propose first. The agent probes your reasoning, and work opens only after your understanding has been assessed. A well-reasoned disagreement counts as success.

The name is the Greek word for Socratic cross-examination.

For a one-page reference of every command, see [USAGE.md](USAGE.md).

## One repository, four plugins

The repository is a plugin marketplace. One learning protocol, one gate engine, packaged for three agent hosts, plus an ownership workflow that builds on it:

```
elenchus/
├── .claude-plugin/marketplace.json   marketplace for Claude Code and Claude Cowork
├── .agents/plugins/marketplace.json  marketplace for Codex (CLI and ChatGPT desktop app)
└── plugins/
    ├── elenchus/        the gates: engine, hooks, skill. Claude Code, Cowork and Codex
    ├── elenchus-ui/     optional, Claude Code CLI only: focus card, compact tool view, themes
    ├── elenchus-vibe/   the Mistral Vibe port of the gates
    └── ownership/       one owner's paper per project: your decisions vs inherited ones. All hosts
```

`elenchus` runs without the UI. Hosts without Claude Code's mods API (Cowork, Codex, older CLI builds) simply do not install `elenchus-ui`; the pinned question is then available through `/elenchus:focus`.

| Host | Gates (`elenchus`) | Focus card (`elenchus-ui`) | Ownership |
| --- | --- | --- | --- |
| Claude Code CLI | full: hooks, skill, commands | yes | yes |
| Claude Cowork (desktop app) | full: hooks run in Cowork | no, needs the mods API | yes |
| Claude desktop Chat tab | no: hooks do not run in chat | no | skills only |
| Codex CLI and ChatGPT desktop app (Codex, Work mode) | full: Codex speaks the same hook protocol | no | yes |
| ChatGPT chat | no hooks | no | skills only |
| Mistral Vibe | via `elenchus-vibe` | no | yes |

Without hooks nothing enforces a gate. A skill alone is a polite request to the model, not a learning gate.

## Install

**Claude Code CLI**

```sh
claude plugin marketplace add mev0lent/elenchus      # or a local path to this repository
claude plugin install elenchus@elenchus
claude plugin install ownership@elenchus
claude plugin install elenchus-ui@elenchus           # optional
```

For development, load a working copy directly: `claude --plugin-dir <repo>/plugins/elenchus --plugin-dir <repo>/plugins/ownership`. Start Claude Code from your learning project, not from the plugin directory. Use `/reload-plugins` after updating.

**Claude Cowork (desktop app):** Customize > Plugins > Add marketplace, enter `mev0lent/elenchus` (a private repository needs the GitHub connection), then install `elenchus` and `ownership`. Skip `elenchus-ui`. Click Update on the marketplace after pushing changes.

**Codex:** `codex plugin marketplace add mev0lent/elenchus`, then install `elenchus` and `ownership` from the Plugins Directory of the ChatGPT desktop app. Codex asks you to review and trust plugin hooks before they run; Elenchus does nothing until you do. Codex has no plugin slash commands, so type the commands as text: `elenchus learn explain TLS handshakes`, `elenchus off`, `elenchus status`, `elenchus focus`, `elenchus cards` (or mention the matching `$elenchus-learn` skill). Codex reads files through the shell, and the shell stays locked while a gate is locked, so the agent cannot browse your project during a locked gate.

**Mistral Vibe:** put `plugins/elenchus-vibe/` into a plugins directory and start Vibe in your learning project:

```sh
# user scope (every project)
mkdir -p ~/.vibe/plugins && cp -r plugins/elenchus-vibe ~/.vibe/plugins/elenchus
# or project scope, inside a trusted folder
mkdir -p .vibe/plugins && cp -r plugins/elenchus-vibe .vibe/plugins/elenchus
```

On Windows, `mklink /J "%USERPROFILE%\.vibe\plugins\elenchus" "...Documents\elenchus\plugins\elenchus-vibe"` links the folder instead of copying. `plugins/ownership` installs the same way under `~/.vibe/plugins/ownership`.

## Start learning

Type `/elenchus:learn explain TLS handshakes` (Codex: `elenchus learn explain TLS handshakes`). Commands are `learn`, `off`, `status`, `focus`, and `cards`. `/elenchus:off` disables gates for this session.

| Mode | Your first move | Claude's job |
| --- | --- | --- |
| `explain` | Explain the mechanism in your own words | Probe a new case, check a limit, then assess your conclusion |
| `predict` | `predict: <output and why>` for registered code | Run that exact example once, compare the output, then assess your reasoning |
| `propose` | Propose your design | Challenge two assumptions; accept a justified defense or revision |
| `auto` | Name the topic | Choose the appropriate mode |

For the final reflection, type `reflect: <your conclusion and reasons>`. `agree:` and `disagree:` also work. They record your reasoning; they do not automatically open a gate. Claude must register evidence of the mechanism, transfer to a new case, and a limitation. If evidence is missing, it asks another question. One accepted reflection opens one turn of work, then the gate locks again.

Concise answers count. Word lengths never determine whether you understood. When stuck, the help ladder is: your attempt, a smaller question, one minimal hint, another attempt. Claude challenges your reasoning respectfully.

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

For Anki, paste `anki/elenchus-card.css` (identical in `plugins/elenchus/anki/` and `plugins/elenchus-vibe/anki/`, a test keeps them equal) into your note type's Cards > Styling. Both light and night modes are supported, with distinct connection and mistake blocks.

The optional **Elenchus** and **Elenchus Light** themes ship with `elenchus-ui` and are available through `/theme` on compatible builds. They change the CLI palette; the focus card handles hierarchy and question visibility. Claude Code does not set the terminal background. For the full dark palette, set your terminal background to `#000022`. After changing `plugins/elenchus-ui/hooks/palette.ts`, run `python plugins/elenchus-ui/scripts/gen_theme.py`; theme tests detect stale generated files.

## The Codex port

Codex implements the same hook protocol as Claude Code: the same event names, `permissionDecision: "deny"` for PreToolUse, `decision: "block"` on Stop, exit code 2, and it sets `CLAUDE_PLUGIN_ROOT` for compatibility. So `plugins/elenchus` serves both hosts from one engine and one `hooks/hooks.json`. Codex reads `.codex-plugin/plugin.json`, which points it at `codex/skills/` (the Socratic skill with Codex tool names, plus `elenchus-learn`, `elenchus-off`, `elenchus-status`, `elenchus-focus`, `elenchus-cards`). Claude Code ignores both.

What the engine adapts when `PLUGIN_ROOT` is set (Codex sets it, Claude Code does not):

1. File edits arrive as `apply_patch`. It counts as a write tool, and the target paths are read from the patch text (`*** Update File:`, `*** Move to:`), so the machinery protection still holds.
2. Shell input may be a string, an argv list (`["bash", "-lc", "..."]`) or `cmd`. All three are normalized before the CLI check.
3. `update_plan` and `view_image` stay available while locked. Hosted tools such as web search are not intercepted by Codex hooks at all.
4. Commands are recognized as `elenchus learn ...`, `$elenchus-learn ...` or `$elenchus:learn ...`, because Codex plugins have no slash commands.
5. Wording names Codex and the shell tool instead of Claude and Bash.

`tests/test_codex.py` replays Codex payloads against the engine, including the full Claude suite under the Codex environment. It does not replace a live Codex session. Codex's own documentation calls hooks "a useful guardrail, not a complete enforcement boundary"; the threat model here is the same as on Claude Code: a model drifting away from a learning protocol, not an adversary.

## Ownership: owner's papers

`plugins/ownership` keeps AI-assisted projects yours without slowing development down. The ideas, decisions and reasons come from you; code and configuration may come from the agent. One skill, `paper`, works the same for new and existing projects.

Each project has an owner's paper in Typst with three sections: Purpose, Decisions, Limits and open questions. Every decision is in one of three states:

- `inherited`: it is in the project, but you have not made it yours.
- `mine`, untested: you made it or took it over, and wrote why.
- owned: you passed an Elenchus gate on it. Writing a reason is not enough; you answer, explain and defend under questioning.

On an existing project the agent starts by listing the decisions it finds in the code as inherited (what and where, never why). On a new project you write your decisions as you make them, and the agent logs every decision it makes on its own while building as inherited, in the same turn. Either way a decision becomes owned the same way: you write its why (or replace it with a better one), pass an Elenchus gate whose topic is the decision, and run `own`. That copies the gate record, with your words and the assessed evidence, into `gates/` next to the paper and binds its id to the decision. A project is owned when every decision is. You choose when to gate; building is never blocked by it.

```sh
python plugins/ownership/scripts/ownership.py install          # once: the Typst package @local/ownership
python plugins/ownership/scripts/ownership.py init docs/paper --name my-project
python plugins/ownership/scripts/ownership.py own docs/paper/main.typ "Threshold chosen on dev"   # after passing its gate
python plugins/ownership/scripts/ownership.py ledger -v        # owned or not, tested/inherited, code changed since the paper
python plugins/ownership/scripts/ownership.py cards docs/paper/main.typ   # Anki TSV, deck Elenchus::Ownership::<project>
```

The Typst contract is two functions: `#decision("title", origin: "mine", where: "file:line", gate: "<id>")` and `#card("question", "answer")`. Keep each `#decision` on one line; `own` edits it. Everything else is derived with `typst query`, so the paper is the only source.

Where a paper lives: in `docs/paper/` of a private repository you own; in your retention library under `projects/<name>/` for public repositories and code you do not own. Personal paths stay out of this repository, in `~/.config/ownership/config.json` (or `$OWNERSHIP_CONFIG`):

```json
{"library": "C:/Users/you/Documents/retention-library",
 "projects": ["C:/Users/you/Documents/a-private-repo"],
 "anki_dir": "C:/Users/you/Documents/retention-library/anki"}
```

The tooling needs Python 3.8+ and Typst (the CLI, or `pip install typst`).

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
python plugins/ownership/tests/test_ownership.py
claude plugin validate .
claude plugin test plugins/elenchus
claude plugin validate claude
```

Integration tests cover short answers, disagreement, mandatory review, evidence, hints, registered executions, source changes, imports, session isolation, concurrent writes, cards, and focus commands, on both engines; the mistral suite adds transcript-driven prompt recording, retry-message filtering, and the post_agent nudge and warning flow. Mods tests run against the real UI engine, including narrow layouts and full/compact tool rendering. A headless Claude Code smoke test also verified activation, the first Socratic question, and its persisted focus state. These checks do not replace a live interactive learning session.

For a live check, start a learning gate in a throwaway project, verify the question remains beside the input, ask for a premature file edit, and check that it is denied. Open a second session and confirm its gate is independent. Use `elenchus learn explain <topic>` if slash-command expansion is unavailable; command files also carry an `ELENCHUS-COMMAND` marker.
