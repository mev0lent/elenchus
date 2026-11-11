---
name: "paper"
user-invocable: true
description: Start this project's owner's paper, or show its state and build the PDF. /elenchus:paper all lists every paper.
argument-hint: "[all]"
---
ELENCHUS-COMMAND paper $ARGUMENTS

Follow the ELENCHUS PAPER block the hook added to this turn. This is housekeeping: it does not start a gate.

On Mistral Vibe no ELENCHUS block is added to the turn: first run `python3 <plugin>/scripts/elenchus.py status` with the shell tool, where `<plugin>` is the folder two levels above this file (usually `~/.vibe/plugins/elenchus`). It prints the block and the exact CLI prefix for every other command.
