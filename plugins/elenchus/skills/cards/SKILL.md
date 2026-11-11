---
name: "cards"
user-invocable: true
description: Write Anki cards for the last completed gate.
---

ELENCHUS-COMMAND cards

Run `status` using the exact session prefix, then write useful atomic cards for the last assessed gate with `cards add`. Use the user's own words, corrected understanding and actual mistakes. Add a `--connects` card only if status shows a genuinely related earlier topic. The first topic needs no connection. If no gate is completed, say so in one sentence.

On Mistral Vibe, use the phase and session prefix already supplied by a CLI or tool result. If none is available, bootstrap once with `python3 <plugin>/scripts/elenchus.py status --brief`, where `<plugin>` is two directories above this file (usually `~/.vibe/plugins/elenchus`). Do not fetch status again just to verify a successful move.
