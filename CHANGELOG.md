# Changelog

## 0.11.0 - 2026-11-11

- Remove opening/question bookkeeping calls on all three hosts: Stop pins opening
  questions and records ordinary challenges. Challenge counts and user answers remain
  required; explicit `challenge` calls still work.
- Add `gate --question` to start a decision and pin its opening question in one call.
- Return the current phase and next action with transitions and CLI errors, avoiding
  status/retry loops. Prediction runs retain JSON output with an added `next` field.
- Treat plain reasoning and objections after verdict as reflections for assessment;
  users no longer need to repeat their answer with a special prefix. No automatic pass.
- Add Vibe 3.1 post_tool context delivery and `status --brief` for one-time bootstrap
  or recovery. Stop requesting full status every turn and discard stale notices.
- Shorten the shared protocol and briefings; search graph notes at gate opening, and
  leave card creation for explicit requests.

Start fresh host sessions after updating. Vibe pins plugin code per session; an old
session may still run 0.10.0. Unix/WSL is the requested support scope; no native Windows
validation was added. Model/server waiting time is outside Elenchus's timing control.

## 0.10.0 - 2026-11-11

- Finish the 0.9.0 handoff with `choice --note`: record the agent's decision and reason
  alongside a user's delegation, without changing the user's words. The command is
  session-scoped, append-only, and safe to retry after a failed graph update.
- Prevent delegated decisions from counting as owned decisions or passed learning
  gates for Anki cards.
- Recall searches past delegated matches instead of stopping after five results.
- Require explicit `on|off` for always-on; invalid arguments leave the setting alone.
  `always off` preserves the current session. Turning Elenchus off clears recall state.
- Isolate test graph, settings, and paper registry paths from the user's environment.
- Document SemVer, separate UI versions, release tags, and release checks; run Python
  checks in GitHub Actions.

Includes the previously uncommitted 0.9.0 work below. No data migration is needed.
Existing delegated records can receive a choice from their originating session in
open work. Refresh Codex's cached plugin and restart open host sessions after updating.
If a Vibe installation still links to `plugins/elenchus-vibe`, recreate that link
using `plugins/elenchus` as described in the README.

## 0.9.0 - 2026-11-11

- Add recall gates, one-round decide gates, explicit delegation, and opt-in always-on.
- Keep work open until another gate starts; store passed gates in a shared Markdown
  knowledge graph with links and reminders for notes older than a month.
- Avoid creating `.elenchus/` in untouched projects.
- Share one engine and ten skills across Claude Code, Codex, and Mistral Vibe;
  remove duplicate Vibe and Codex skill trees.
- Document linking the graph into an Obsidian vault.

Real interactive host checks and Windows checks remain distinct from automated
hook-protocol tests. See `docs/roadmap.md` for the handoff and remaining manual setup.
