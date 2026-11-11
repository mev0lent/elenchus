---
name: "learn"
user-invocable: true
description: Start a Socratic session. Usage /elenchus:learn [explain|predict|propose|auto] <topic>
argument-hint: "[explain|predict|propose|auto] <topic>"
---
ELENCHUS-COMMAND learn $ARGUMENTS

Elenchus is starting. Load the `socratic` skill and follow the phase instructions in the ELENCHUS block the hook added to this turn.

Do not explain the topic. Register and ask one opening question, under the injected word cap. The question stays pinned in the focus card. Follow the help ladder if the learner gets stuck.

On Mistral Vibe no ELENCHUS block is added to the turn: first run `python3 <plugin>/scripts/elenchus.py status` with the shell tool, where `<plugin>` is the folder two levels above this file (usually `~/.vibe/plugins/elenchus`). It prints the block and the exact CLI prefix for every other command.
