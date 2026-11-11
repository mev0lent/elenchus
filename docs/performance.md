# Turn latency

0.11.0 removes avoidable agent/tool round trips on Claude Code, Codex, and Vibe.
The supported development scope is Unix/WSL. These measurements were taken on Linux;
WSL itself was not timed.

## What the Vibe trace showed

In one local 0.10.0 test, 109.9 seconds elapsed before the first model completion.
The response used about 30,000 input tokens. It attempted an assessment, received a
phase error, fetched status, issued another verdict, and finally asked the user to
repeat a conclusion with a prefix: three CLI calls and four model completions.
Each CLI completion path took about 0.3 to 0.4 seconds. Most of that turn's delay
was outside the engine's bookkeeping, so faster Python alone would not fix it.

Journal parsing measured about 4 ms for that session, and 195 ms for the largest
local journal tested (12.5 MB). Stop now reuses its parsed journal instead of reading
it twice. A daemon or persistent journal cache was not justified by these measurements.

## Fewer calls

An opening question or ordinary probing question is recorded by Stop, without an
agent-issued CLI call. It cannot unlock work: required answered challenges and final
assessment remain enforced. Explicit `challenge` remains supported. A new decide gate
can combine gate creation and question pinning with `gate --question`.

For a normal successful gate with its mode set by the user's command:

| Agent-issued bookkeeping calls | 0.10.0 protocol | 0.11.0 fast path |
| --- | ---: | ---: |
| Explain: opening, one probe, verdict, assessment | 4 | 2 |
| Propose: opening, two probes, verdict, assessment | 5 | 2 |
| Decide: opening, one probe, assessment | 3 | 1 |

These counts exclude optional help, graph searches, cards, and initial skill loading.
Vibe previously also requested status each turn. It now gets state from CLI results
and the first ordinary tool result of a locked turn; a missing prefix can require one
bootstrap `status --brief`. State errors carry their next action in the same result.
No status call is needed merely to verify a successful move.

After verdict, plain user reasoning, including a reasoned objection, enters review.
The user no longer has to repeat it with a reflection prefix. A bare yes still does
not count, and recording a reflection does not accept it.

## Smaller context

Measured as Unicode character counts against the `v0.10.0` sources. The empty-graph
fixture is an explain gate on TLS, session `bench`; the attempted phase has no
completed challenges. Counts are payload sizes, not tokenizer estimates or latency
promises.

| Payload | 0.10.0 | 0.11.0 | Reduction |
| --- | ---: | ---: | ---: |
| Shared Socratic skill | 12,065 | 7,586 | 37% |
| Opening rules plus briefing | 2,576 | 1,963 | 24% |
| Attempt briefing | 1,555 | 806 | 48% |

The regression suites replay the no-CLI challenge path in each host dialect, enforce
prompt-size budgets, test failed-command recovery and natural reflections, and check
Vibe context delivery without stale or repeated notices. They also retain the earlier
lock, evidence, isolation, and prediction tests.

## Practical limits

Model queueing, context prefill, generation, and network waiting can still make a
turn slow; Elenchus cannot set a hard upper bound on them. No model, reasoning setting,
permission policy, or required learning step was changed to obtain these reductions.
Start fresh sessions to load the new instructions and hooks. Vibe pins plugin code
per session, so an old session may keep running the old protocol after installation.

Vibe 3.1's post_tool context contract is documented in the
[Mistral hook reference](https://docs.mistral.ai/vibe/code/cli/hooks). Newer upstream
versions also describe pre_agent context, but that hook is absent from the installed
3.1.0 enum; this release does not require an upgrade or assume that feature exists.
