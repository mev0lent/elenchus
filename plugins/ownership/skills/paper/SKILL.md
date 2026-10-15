---
name: paper
description: "Use for any project the user wants to own, new or existing: starting or updating its owner's paper, logging decisions, turning decisions into owned ones through Elenchus gates, checking which projects are owned, or exporting cards. Also use while building in a project that has a paper, to log decisions you made on your own."
user-invocable: true
---

# Owner's paper

`<plugin>` means this plugin's folder, two levels above this SKILL.md. Run its script as `python <plugin>/scripts/ownership.py`.

The ideas, the decisions and the reasons come from the user. Code and configuration may come from you. The paper is where the user's decisions live, so that the project stays theirs however much of it you typed.

## The one idea

The paper is a list of decisions. Each one is in one of three states:

- `inherited`: it is in the project, but the user has not made it theirs.
- `mine`, untested: the user made it or took it over and wrote why.
- owned: the user passed an Elenchus gate on it. Writing a reason is not enough; answering, explaining and defending under questioning is.

A project is owned when every decision is owned. Nothing else is tracked.

## The paper

`docs/paper/main.typ` in the project's repository if the repository is private and the user's. Otherwise, for public repositories or code they do not own, `projects/<name>/main.typ` in the library from `ownership.py config` (ask for the path if none is set; never guess it). Never put a paper into a public repository. For employer or client work, ask first whether the user may keep notes outside those systems.

Create it with `ownership.py install` (once per machine) and `ownership.py init <dir> --name <project>`. It has three sections: Purpose, Decisions, Limits and open questions. A decision is `#decision("title", origin: "mine")` followed by the user's why; `where: "file:line"` points to the code.

## Your part

1. **While building, log what you decide.** Whenever you choose something the user did not specify and that would matter if it changed (a data model, a threshold, a dependency, an error-handling policy, a security-relevant default), add `#decision("what you chose", origin: "inherited", where: "file:line")` in the same turn, with no reason under it. Say in one line that you added it. Mechanical work (naming, formatting, boilerplate) is not a decision.
2. **On an existing project, start by listing.** Add the decisions you find in the code as inherited entries: what was decided and where, never why. If the user wants a recall check first, let them write what they remember before you list anything.
3. **Never write a reason.** The why under a decision, the purpose and the limits are the user's words. You may tidy their wording when asked, and you may point out where their reason contradicts the code. If they ask you to write the why, decline once in one sentence and ask the question that gets them there.

## Making a decision theirs

1. The user writes why the decision is, or should be, that way. If they disagree with it, they write the better decision and you change the code.
2. The user passes an Elenchus gate whose topic is the decision: `propose` for a design choice they must defend, `explain` for a mechanism, `predict` for behavior of code. Elenchus asks, the user answers; only the user's own typed answers can pass it.
3. `ownership.py own <paper> "<decision title>"`, run from the project where the gate ran, binds that gate to the decision: it copies the gate record (the user's words and the assessed evidence) into `gates/` next to the paper, sets `origin: "mine"` and adds the gate id. One gate may cover several closely related decisions: pass `--gate <id>` for the others.

Never run `own` for a gate the user did not pass, and never edit a `gate:` value by hand. Without Elenchus installed, decisions can be `mine` but not owned; say so plainly. Gating is not a hurdle for building: the user decides when to gate, and the ledger shows what is still open.

## Cards and overview

`#card("question", "answer")` next to a decision, in the user's wording. `ownership.py cards <paper>` exports them to Anki. `ownership.py ledger` shows every paper: owned or not, how many decisions are tested and how many inherited (`-v` lists the open ones), missing gate records, and whether code changed after the paper was last updated. Report it as it is.
