# Roadmap: seven improvements after 0.8.0 (shipped as 0.9.0)

Written 2026-11-11 for whoever continues this work, human or agent. Each item says what
to build, where, how to check it, and its state. Update the **State** line when you
finish or stop part-way, and say what is left.

## Read this first

- One engine serves Claude Code, Codex and Mistral Vibe: `plugins/elenchus/scripts/elenchus.py`.
  How each host is wired is in [internals.md](internals.md). Read "Mistral Vibe" there
  before touching hooks: installed Vibe 3.1 has no prompt hook; 0.11.0 uses its post_tool context support.
- The user's words move gates, never the agent. A new way to open or close a gate must be
  triggered by text the user typed (`on_prompt`), not by a CLI call the agent can make.
- Run every suite after each item. All must pass before you start the next one:

  ```sh
  for t in test_gates test_vibe test_codex test_crossos test_launcher test_paper; do
    python3 plugins/elenchus/tests/$t.py || exit 1; done
  python3 plugins/elenchus-ui/tests/test_palette.py || exit 1
  claude plugin validate .
  ```

- `test_codex.py` and `test_vibe.py` inherit every test in `test_gates.py` and replay it
  in that host's environment. A new test in `test_gates.py` is therefore run three times;
  use `self.prompt(...)`, `self.cli(...)`, `self.denied(...)` and it works on all three.
- Tests must never touch the real home directory. `ELENCHUS_DIR` moves state and the
  graph into the temp folder. Any new file under `~/.config/elenchus` needs its own
  environment override, set in `Gates.setUp`.
- A new user command needs four things: the verb in `CTRL_RE`, handling in `on_prompt`,
  a `skills/<verb>/SKILL.md` (quote `name` and `argument-hint`, see `test_vibe.Packaging`),
  and a line in the README command list.
- Live checks without approving anything: `vibe -p "<prompt>"`, `claude -p "<prompt>"`,
  `codex exec --skip-git-repo-check "<prompt>"` in an empty folder, then read
  `.elenchus/sessions/*/state.json`. Do not use auto-approve flags.
- Codex installs a cached copy. After changing the plugin: bump the version in the three
  `plugin.json` files, then `codex plugin remove elenchus@elenchus` and
  `codex plugin add elenchus@elenchus`. Claude Code and Vibe read the repo directly.
- The user requested commits and pushes during the 0.10.0 continuation. See releases.md for the release process.

## 1. Recall gate

**Why.** The graph reminds the agent, not the user. Reproducing an old conclusion from
memory is what keeps it.

**Build.**
- Command `/elenchus:recall [words]`. With words, take the best `graph_find` match;
  without, the note with the oldest modification time. Skip notes whose latest entry is
  a delegation (item 3). No notes: say so, start nothing.
- It starts an ordinary `explain` gate on the note's title with `s["recall"] = True` and
  a brief (reuse `own_brief`) that carries the user's earlier entry and tells the agent:
  ask them to reproduce it from memory, do not show the old words until they answered,
  then compare what held and what faded.
- On accept, `complete()` records `how="recall"` and `graph_add` appends a new dated
  entry to the same note. The new modification time moves the note to the back of the
  queue, so "oldest first" is the whole schedule.
- `graph_note` (SessionStart) adds how many notes are older than 30 days and tells the
  agent to offer `/elenchus:recall` once, at a natural pause.
- `learn`, `own` and `off` clear `s["recall"]`.

**Check.** New test: pass a gate, age the note with `os.utime`, `/elenchus:recall`, the
briefing contains the old words and "RECALL", pass it, the note has two entries.

**State.** Done in 0.9.0 (`test_recall_retests_the_oldest_note`). Live on Claude Code only
the empty-graph answer was checked; a full recall pass in a real session is open.

## 2. Decide gate

**Why.** A propose gate costs five user turns. For a decision raised in the middle of
work that is too heavy, and the user will switch Elenchus off instead.

**Build.**
- New mode `decide`, `MIN_ROUNDS["decide"] = 1`. The user states the choice and the
  reason, the agent attacks once, the user answers, the agent runs
  `assess --result accept --note "<the decision, in the user's words>"`. No `verdict`,
  no `reflect:`, no mechanism/transfer/limit evidence.
- `cmd_assess` accepts in mode `decide` from phase `attempted` when one challenge was
  answered. The record's `own_words` holds the first statement and the answer.
  `assess --result retry` is refused there: challenge again instead.
- `cmd_verdict` refuses `decide`. `on_text` and `cmd_challenge` treat `decide` like
  `propose`. The open-work instruction (`NEXT["open"]`, both places in the Socratic
  skill) names `gate --mode decide` instead of `propose`.
- `/elenchus:own` keeps the full propose gate.

**Check.** New test: from open work, `gate --mode decide`, tools lock, statement, one
challenge, answer, accept with only `--note`, tools open, graph note tagged `decide`.

**State.** Done in 0.9.0 (`test_decide_gate_is_one_round`). Live on Claude Code the gate
started and asked one question; the challenge and accept steps were only run in tests.

## 3. Delegated decisions

**Why.** "You pick" is a legitimate answer, but today it leaves no trace. An honest list
of what the user does not own is worth more than a pretended ownership.

**Build.**
- In a `decide` or `propose` gate that is not an own gate, the user may type
  `delegate: <optional remark>`. That is their word, so it may open the gate.
- `on_prompt` records it: `complete(d, s, "delegated")`, phase `open`. The graph entry
  is headed `delegated` and says the decision was left to the agent, with the remark.
- The briefing then tells the agent to decide, say in one sentence what it chose and
  why, and log it in the owner's paper as `inherited` if there is one.
- The agent tells the user about `delegate:` only when they ask it to choose; it never
  suggests it first.
- `graph delegated` lists these notes (plain word search finds the heading).

**Check.** New test: decide gate, `delegate: no opinion on this`, phase `open`, note
contains `delegated` and the remark, recall skips that note.

**State.** Done in 0.9.0 (`test_delegated_decision_is_recorded_as_such`), and checked
live on Claude Code: `delegate:` opened the work and wrote the note.

Follow-up completed in 0.10.0: `choice --note "<what the agent chose and why>"`
appends a separately labeled agent choice to this session's latest delegated record
and its graph entry. User words remain unchanged. Repeating the same choice repairs a
failed graph update without duplicating it; replacing a choice is refused. Delegations
cannot count as ownership evidence or supply learning cards.

## 4. Always-on mode

**Why.** Gates and the "you decide" rule only apply after the user remembers to type a
command. Ownership of all projects needs a default.

**Build.**
- `/elenchus:always on|off` creates or removes a flag file:
  `$ELENCHUS_ALWAYS`, else `~/.config/elenchus/always-on`.
- With the flag, a session that has no state file starts as `active`, phase `open`:
  no lock, the open-work briefing every turn, decide gates when a real decision comes
  up. `/elenchus:off` writes the state file, so it stays off for that session.
- The briefing in phase `open` is short (no locked-phase reminders).
- `~/.config/elenchus` is protected from the agent's file and shell tools like the rest
  of the machinery.
- Vibe cannot inject the briefing, so always-on does little there until the agent runs
  `status`. Document it, do not work around it.
- The flag is the user's to set. Do not switch it on for them.

**Check.** New test: flag on, a fresh session's prompt hook returns the open briefing
and writes nothing to disk, tools are free, `gate --mode decide` locks, `off` sticks.

**State.** Done in 0.9.0 (`test_always_on_starts_sessions_in_open_work`). The flag is off
on this machine: switching it on is the user's call (`/elenchus:always on`). Not checked
in a live session.

## 5. The graph inside a vault

**Why.** A graph nobody opens does not help.

**Build.** No code. `~/.config/elenchus/graph` may be a symbolic link into an Obsidian
vault; `ELENCHUS_GRAPH` only reaches hosts started from a shell that exports it, a link
reaches all of them. Document the link in the README.

**State.** Done during the 0.10.0 continuation, with the user's explicit choice.
`~/.config/elenchus/graph` links to `~/Documents/prospero/elenchus`. The target folder
and resolved link were verified; no previous graph existed or was moved.

## 6. No `.elenchus/` in folders that never used it

**Why.** Every hook call created `.elenchus/` in the current folder, including
`~/Downloads`.

**Build.**
- `main()` takes the lock only when the project's `.elenchus` already exists. A hook in
  a folder without it runs unlocked and writes nothing unless the user types a command,
  in which case `save()` creates the folder.
- `graph` and `paper status --all` are answered before any lock or state is touched.
- Plain prompts in phase `open` return the briefing without saving, so always-on mode
  does not bring the litter back.
- Existing empty folders are the user's files; list them, do not delete them.

**Check.** New test: prompt, pretool, stop and session hooks plus `graph` in a fresh
folder leave no `.elenchus`; `/elenchus:learn` creates it.

**State.** Done in 0.9.0 (`test_untouched_folders_stay_clean`), and seen live: a command
that started nothing left the folder empty. Old `.elenchus` folders were left in place. During the continuation, this checkout's
folder contained session state and was not empty; nothing was deleted.

## 7. One set of skills

**Why.** Codex 0.167 lists only the shared `skills/` folder (`elenchus:learn`, ...);
`codex/skills/` and the `skills` key in `.codex-plugin/plugin.json` are dead weight
that drifts.

**Build.** Delete `plugins/elenchus/codex/`, drop the `skills` key, make the shared
Socratic skill name the shell tool neutrally, fix the docs that mention
`$elenchus-learn`. `CTRL_RE` keeps accepting `$elenchus-learn` and `elenchus learn`.

**Check.** The Codex cache holds the ten skills from `skills/`. `test_codex.py` passes.

**State.** Done in 0.9.0. Codex was reinstalled at 0.9.0; its hooks still wait for the
user's trust (`/hooks` inside Codex), so nothing is enforced there yet.

## Not planned here

- Approving Elenchus's own CLI calls on Codex and Vibe. No hook output for it was found;
  look again when either host documents one.
- Interactive checks: a full pass in a real session on each host, the predict flow, and
  Windows.

## Continuation: 0.10.0

- Finished delegated choices and added regression tests for session isolation,
  append-only recording, graph-update retries, and preventing false ownership/cards.
- Fixed recall search skipping eligible notes behind five delegated matches.
- Invalid always-on arguments now change nothing; `always off` preserves the current
  session, and `off` clears recall state.
- Tests explicitly override graph, always-on, and paper paths, even when the parent
  environment sets them. Shared graph writes now use one lock, and lock creation
  does not add a `.gitignore` to the user's graph folder.
- Core manifests are 0.10.0. The UI stays at 0.6.0. SemVer, release tags, changelog,
  and the local/CI checks are documented in [releases.md](releases.md).
- No old `.elenchus` folders were deleted. This checkout's folder contains real session
  state, so it is not empty. Always-on remains off; hook trust still needs the user.
- Interactive recall/decide/predict passes on real hosts and native Windows checks
  remain manual. Automated protocol tests are not represented as live host passes.

Validation for the continuation: all six engine suites, both Python UI checks,
Claude marketplace validation, and all nine Claude UI/mod tests passed locally.
Release publication is recorded by the Git history and the `v0.10.0` tag; the
GitHub Checks workflow repeats the Python checks on pushes and tags.

## Performance continuation: 0.11.0

The user requested faster turns on all three hosts, supporting Unix/WSL; native
Windows is outside the requested validation scope.

- Stop records closing questions as challenges without a separate CLI/model round
  trip. Required rounds, subsequent user answers, and assessments stay enforced.
- Gate creation can pin its opening question with `--question`. Openings otherwise
  pin automatically on Stop; ordinary challenges no longer need explicit registration.
- Successful transitions and failed commands return the current phase and next action.
  The prediction run keeps JSON output and adds a `next` field.
- Plain reasoning after verdict enters reflection review. No repeated prefix or new
  verdict is needed; agreement alone is still insufficient, and assessment is mandatory.
- Vibe uses post_tool context once per locked turn; no repeated status polling or stale
  prompt notices after a transition. Bootstrap/recovery can use `status --brief`.
- Shorter shared instructions and briefings; cards are produced only on request.
- [performance.md](performance.md) records measurements and their limits. Existing
  Vibe sessions retain their pinned code: start a fresh session after upgrading.

Validation: all six engine suites and both Python UI checks passed; all nine Claude
UI/mod tests and marketplace validation passed. The installed Vibe 3.1 HookConfig
also accepts all three hook entries. No live model latency bound is claimed.

Live follow-up: a fresh Vibe opening completed in 9.91 seconds with one skill read and
no bookkeeping CLI calls. The next turn caught a premature verdict permission request;
shared phase validation now rejects impossible verdict/assessment calls in pre_tool,
before approval. The live Claude request hit its account usage limit before generation.
See performance.md for the distinction between protocol checks and model timings.

Final Vibe smoke check after the guard fix: opening 11.45 seconds, next probe 9.79
seconds. The probe used one model completion, zero tools, and automatically recorded
round 1 with tools still locked and no violations. These are samples, not time bounds.
