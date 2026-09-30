# Agent Completion Architecture Audit

Read `kt how to approach architecture-design` before changing this system. CointOS is paused. Do not resume autonomy or deploy the pending completion patch until this concern has one owner.

## Finding

Agent completion is not one protocol. The daemon ledger is nominally authoritative, but completion decisions and lifecycle writes are distributed across:

- OpenCode event and session metadata (`stop`, `tool-calls`, process exit, final text);
- `agents.watch` and session-tail reconciliation;
- task-kind branches in `work.settle`;
- `/api/finish`, `/api/land`, `/api/incorporate`, `/api/return`, stop and halt endpoints;
- Git merge/cleanliness checks, `.work-report.md`, tree health and queue records;
- recovery, silence/loop handling, retry limits and resumed-run prompts.

Each role consequently has a different completion mechanism. Workers use a committed report; managers submit a handoff but still await process settlement; integrators mutate worker state through landing or return; gardeners and operators combine transport markers with Git state; stewards and test auditors have no durable completion receipt and are inferred complete from transport markers, retry count or arbitrary outward text.

## Why the steward loop recurred

OpenCode persisted a complete steward summary while the observed finish marker still described the preceding tool-call step. CointOS treated that transport detail as semantic incompletion, requeued the same session and asked it to summarize again.

Successive fixes added session-tail reconciliation, a summary-only recovery prompt, a two-run cap, a second-run text exception, and finally a not-installed first-run text exception. These patches changed different observers without establishing who owns completion. The focused lifecycle tests still pass, demonstrating that branch-level tests do not prove architectural coherence.

The pending `work.py` rule that treats any non-empty steward/auditor text as completion is a quarantined symptom patch, not a solution.

## Required redesign

Create one receipt-driven lifecycle:

1. The runner owns execution facts only: run/session identity, completed messages, process exit, errors and resource accounting.
2. Every bounded assignment submits one typed, idempotent completion receipt tied to task ID and run ID.
3. One daemon lifecycle reducer is the sole writer of task and queue lifecycle state.
4. Per-kind validators check reports, commits, landing receipts, tree state and other artifacts as evidence; none independently transitions lifecycle state.
5. Process exit triggers reconciliation only. Text, exit code and OpenCode `finish_reason` are diagnostic facts, never semantic completion authority.
6. Recovery consumes the reducer's explicit nonterminal result. Prompts and retry counts cannot change completion semantics.
7. Queue publication is a projection of the same accepted receipt, not another lifecycle authority.

Before implementation, inventory every writer of task status, queue status, `settled`, `handoff`, `acceptance`, agent removal and retry state. Define legal transitions and receipt validation for every task kind, then migrate them to the reducer as one concern. Delete superseded special cases rather than layering compatibility indefinitely.

Acceptance must cover every role plus duplicate/lost replies, stale runs, daemon replacement, process exit before and after receipt, directed stop, silence/loop recovery, budget exhaustion, landing/incorporation/return, and a real OpenCode transcript ending after tool calls.

Canonical detailed audit: `kt what is the agent completion model`. Current defect and implementation frontier: `kt what is broken` and `kt what is the plan`.
