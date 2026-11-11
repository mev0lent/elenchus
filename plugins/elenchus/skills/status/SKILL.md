---
name: "status"
user-invocable: true
description: Show the current gate, phase and what happens next.
---
ELENCHUS-COMMAND status

Run the CLI `status` command with the shell tool, using the exact prefix from the ELENCHUS block. Report mode, topic, phase, violations and the next step in two lines.

On Mistral Vibe no ELENCHUS block is added to the turn: first run `python3 <plugin>/scripts/elenchus.py status` with the shell tool, where `<plugin>` is the folder two levels above this file (usually `~/.vibe/plugins/elenchus`). It prints the block and the exact CLI prefix for every other command.
