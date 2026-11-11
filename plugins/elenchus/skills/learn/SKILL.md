---
name: "learn"
user-invocable: true
description: Start a Socratic session. Usage /elenchus:learn [explain|predict|propose|decide|auto] <topic>
argument-hint: "[explain|predict|propose|decide|auto] <topic>"
---
ELENCHUS-COMMAND learn $ARGUMENTS

Elenchus is starting. Load the `socratic` skill and follow the phase instructions in the ELENCHUS block the hook added to this turn.

Do not explain the topic. Ask one opening question, under the injected word cap; Stop pins it automatically, so no `question` call is needed. The question stays pinned in the focus card. Follow the help ladder if the learner gets stuck.

On Mistral Vibe, use the phase and session prefix already supplied by a CLI or tool result. If none is available, bootstrap once with `python3 <plugin>/scripts/elenchus.py status --brief`, where `<plugin>` is two directories above this file (usually `~/.vibe/plugins/elenchus`). Do not fetch status again just to verify a successful move.
