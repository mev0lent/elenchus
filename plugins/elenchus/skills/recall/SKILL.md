---
name: "recall"
user-invocable: true
description: Re-test something you passed before, from memory. Usage /elenchus:recall [words]. Without words it takes the note you have not touched longest.
argument-hint: "[words]"
---
ELENCHUS-COMMAND recall $ARGUMENTS

Load the `socratic` skill and follow the ELENCHUS block the hook added to this turn. It starts a recall gate on one note of the user's knowledge graph and shows you their earlier entry, or says there is nothing to recall.

Ask the user to reproduce from memory what they concluded and why. Do not show, quote or paraphrase their old entry before they have answered. Then probe what faded or changed, and say plainly what held. One question per turn, under the word cap.

On Mistral Vibe no ELENCHUS block is added to the turn: first run `python3 <plugin>/scripts/elenchus.py status` with the shell tool, where `<plugin>` is the folder two levels above this file (usually `~/.vibe/plugins/elenchus`). It prints the block and the exact CLI prefix for every other command.
