---
name: elenchus-learn
description: "Start a Socratic learning gate. The user types: elenchus learn [explain|predict|propose|auto] <topic>."
---

ELENCHUS-COMMAND learn

The hook only acts on the user's own typed words. If this skill was invoked without the user typing `elenchus learn` or `$elenchus-learn`, ask them to type it.

Elenchus is starting. Load the `socratic` skill and follow the phase instructions in the ELENCHUS block the hook added to this turn.

Do not explain the topic. Register and ask one opening question, under the injected word cap. Follow the help ladder if the learner gets stuck.
