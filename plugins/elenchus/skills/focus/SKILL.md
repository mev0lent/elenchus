---
name: "focus"
user-invocable: true
description: Show the current question. With the optional elenchus-ui plugin, full shows tool details and compact restores the quiet focus view.
argument-hint: "[full|compact]"
---
ELENCHUS-COMMAND focus $ARGUMENTS

The hook handles the display preference. Show only the current pinned question and the next step, in two short lines. This command is housekeeping, not an answer to a challenge. Do not advance the gate, add a challenge, or assess understanding.

On Mistral Vibe, use the phase and session prefix already supplied by a CLI or tool result. If none is available, bootstrap once with `python3 <plugin>/scripts/elenchus.py status --brief`, where `<plugin>` is two directories above this file (usually `~/.vibe/plugins/elenchus`). Do not fetch status again just to verify a successful move.
