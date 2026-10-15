---
name: elenchus-cards
description: "Write Anki cards for the last completed Elenchus gate. The user types: elenchus cards."
---

ELENCHUS-COMMAND cards

The hook only acts on the user's own typed words. If this skill was invoked without the user typing `elenchus cards` or `$elenchus-cards`, ask them to type it.

Run `status` using the exact session prefix, then write useful atomic cards for the last assessed gate with `cards add`. Use the user's own words, corrected understanding and actual mistakes. Add a `--connects` card only if status shows a genuinely related earlier topic. If no gate is completed, say so in one sentence.
