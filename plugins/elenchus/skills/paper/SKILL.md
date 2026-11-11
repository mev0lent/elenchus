---
name: "paper"
user-invocable: true
description: Start this project's owner's paper, or show its state and build the PDF. /elenchus:paper all lists every paper.
argument-hint: "[all]"
---
ELENCHUS-COMMAND paper $ARGUMENTS

Follow the ELENCHUS PAPER block the hook added to this turn. This is housekeeping: it does not start a gate.

On Mistral Vibe, use the phase and session prefix already supplied by a CLI or tool result. If none is available, bootstrap once with `python3 <plugin>/scripts/elenchus.py status --brief`, where `<plugin>` is two directories above this file (usually `~/.vibe/plugins/elenchus`). Do not fetch status again just to verify a successful move.
