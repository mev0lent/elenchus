---
name: "own"
user-invocable: true
description: Own a project decision by passing a gate on it. Usage /elenchus:own <decision title>
argument-hint: "<decision title>"
---
ELENCHUS-COMMAND own $ARGUMENTS

Load the `socratic` skill. This starts a propose gate on one formally stated project decision, or explains why it cannot start yet. Follow the ELENCHUS block. If it says the decision is not ready, tell the user exactly what is missing and stop: never write the formal statement for them. Otherwise attack their formal statement as the socratic skill describes. When you accept, the engine records the decision as owned, with the user's own reasoning.

On Mistral Vibe no ELENCHUS block is added to the turn: first run `python3 <plugin>/scripts/elenchus.py status` with the shell tool, where `<plugin>` is the folder two levels above this file (usually `~/.vibe/plugins/elenchus`). It prints the block and the exact CLI prefix for every other command.
