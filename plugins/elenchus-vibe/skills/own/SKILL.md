---
name: own
description: Own a project decision by passing a gate on it. Usage /elenchus:own <decision title>
user-invocable: true
---

ELENCHUS-COMMAND own

Load the `elenchus:socratic` skill and run the CLI `status` command: it shows either why the decision is not ready, or the OWN GATE briefing. This starts a propose gate on one formally stated project decision, or explains why it cannot start yet. Follow the ELENCHUS block. If it says the decision is not ready, tell the user exactly what is missing and stop: never write the formal statement for them. Otherwise attack their formal statement as the socratic skill describes. When you accept, the engine records the decision as owned, with the user's own reasoning.
