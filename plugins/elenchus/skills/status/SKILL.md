---
name: "status"
user-invocable: true
description: Show the current gate, phase and what happens next.
---
ELENCHUS-COMMAND status

Run the CLI `status` command with the shell tool, using the exact prefix from the ELENCHUS block. Report mode, topic, phase, violations and the next step in two lines.

On Mistral Vibe, use the phase and session prefix already supplied by a CLI or tool result. If none is available, bootstrap once with `python3 <plugin>/scripts/elenchus.py status --brief`, where `<plugin>` is two directories above this file (usually `~/.vibe/plugins/elenchus`). Do not fetch status again just to verify a successful move.
