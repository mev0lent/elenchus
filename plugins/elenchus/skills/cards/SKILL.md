---
name: "cards"
user-invocable: true
description: Write Anki cards for the last completed gate.
---

ELENCHUS-COMMAND cards

Run `status` using the exact session prefix, then write useful atomic cards for the last assessed gate with `cards add`. Use the user's own words, corrected understanding and actual mistakes. Add a `--connects` card only if status shows a genuinely related earlier topic. The first topic needs no connection. If no gate is completed, say so in one sentence.

On Mistral Vibe no ELENCHUS block is added to the turn: first run `python3 <plugin>/scripts/elenchus.py status` with the shell tool, where `<plugin>` is the folder two levels above this file (usually `~/.vibe/plugins/elenchus`). It prints the block and the exact CLI prefix for every other command.
