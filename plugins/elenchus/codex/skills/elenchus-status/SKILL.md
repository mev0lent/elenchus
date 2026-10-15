---
name: elenchus-status
description: "Show the current Elenchus gate, phase and next step. The user types: elenchus status."
---

ELENCHUS-COMMAND status

The hook only acts on the user's own typed words. If this skill was invoked without the user typing `elenchus status` or `$elenchus-status`, ask them to type it.

Run the CLI `status` command with the shell tool, using the exact prefix from the ELENCHUS block. Report mode, topic, phase, violations and the next step in two lines.
