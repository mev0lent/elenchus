---
name: learn
description: Start a Socratic learning gate. Usage /elenchus:learn [explain|predict|propose|auto] <topic>
user-invocable: true
---

ELENCHUS-COMMAND learn

Elenchus is starting. Load the `elenchus:socratic` skill and run the CLI `status` command with the shell tool to see the ELENCHUS briefing and the exact CLI prefix (the engine is `scripts/elenchus.py` inside this plugin; `status` also works without `--session`).

Do not explain the topic. Register and ask one opening question, under the injected word cap. The question stays pinned as the current focus. Follow the help ladder if the learner gets stuck.
