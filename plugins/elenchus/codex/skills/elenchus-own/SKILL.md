---
name: elenchus-own
description: "Own a project decision by passing a gate on it. The user types: elenchus own <decision title>."
---

ELENCHUS-COMMAND own

The hook only acts on the user's own typed words. If this skill was invoked without the user typing `elenchus own`, ask them to type it.

This starts a propose gate on one formally stated project decision, or explains why it cannot start yet. Follow the ELENCHUS block. If it says the decision is not ready, tell the user exactly what is missing and stop: never write the formal statement for them. Otherwise attack their formal statement as the socratic skill describes. When you accept, the engine records the decision as owned, with the user's own reasoning.
