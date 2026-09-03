# 0003: Separate process exit from verified completion

Status: accepted, 2026-09-03.

## Context

Several local agent runs exited with code zero after producing only plans, incomplete
work, or stale claims. The outbox then described those runs as successful. Process
status is mechanical evidence about execution, not a judgment about the requested
outcome.

## Decision

An ordinary agent run that exits cleanly moves to `awaiting_verification`. A linked
Verifier, preferably on a different capable model selected from live inventory,
inspects the original task, full output, artifacts, repository state, tests, and
live facts. It writes a schema-checked evidence record. Only an accepted verdict
moves the root task to `completed`; rejection moves it to `rejected`. Notifications
are gated on those verified terminal states.

Verifier jobs are not recursively verified. Missing or malformed verdicts reject
rather than pass. The watchdog detects orphaned and stale verification handshakes.
Future repair loops must be bounded, deduplicated, approval-aware, and independently
re-verified.

## Consequences

Results take another model turn and may incur model switching. That latency is an
intentional cost of truthful completion. Exit code, output text, agent confidence,
and the existence of a file remain evidence inputs, never self-authenticating proof.
