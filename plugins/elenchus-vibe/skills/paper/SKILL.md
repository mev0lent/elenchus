---
name: paper
description: "Start this project's owner's paper, show its state, or /elenchus:paper all for every paper. Also use while building in a project that has an owner's paper: log every decision you make on your own as an inherited #decision line."
user-invocable: true
---

ELENCHUS-COMMAND paper

Run the CLI `status` command with the shell tool. If it shows no owner's paper, ask the user once where it should live: inside this repository (docs/paper, only if the repository is private and theirs) or in their own notes folder. Then run `paper init --path <folder> --name <project>` with the exact CLI prefix. Offer a recall check first: the user writes recall.md next to the paper from memory, without the code and without you. Then add every decision you find in the code as one line under '== Decisions': #decision("what was decided", origin: "inherited", where: "file:line"). What and where, never why. If a paper exists, run `paper status` and `paper build` and report both briefly: the state, the PDF path or the Typst error. Decisions marked [not formalized] need a labeled equation, invariant, definition or algorithm, written by the user, before /elenchus:own accepts them. With the argument `all`, run `paper status --all` and report the overview. While building in a project with a paper, run `status` once per session to see the paper rule, and log each decision you make on your own as #decision("what you chose", origin: "inherited", where: "file:line"), never formalized and never with a reason. This does not start a gate.
