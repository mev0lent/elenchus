---
name: "focus"
user-invocable: true
description: Show the current question. With the optional elenchus-ui plugin, full shows tool details and compact restores the quiet focus view.
argument-hint: "[full|compact]"
---
ELENCHUS-COMMAND focus $ARGUMENTS

The hook handles the display preference. Show only the current pinned question and the next step, in two short lines. This command is housekeeping, not an answer to a challenge. Do not advance the gate, add a challenge, or assess understanding.

On Mistral Vibe no ELENCHUS block is added to the turn: first run `python3 <plugin>/scripts/elenchus.py status` with the shell tool, where `<plugin>` is the folder two levels above this file (usually `~/.vibe/plugins/elenchus`). It prints the block and the exact CLI prefix for every other command.
