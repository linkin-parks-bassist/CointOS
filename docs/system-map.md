# System map

Last reconciled: 2026-09-03 (Australia/Sydney).

This is a factual recovery aid, not a task transcript. Runtime details that change
frequently belong in `state/` and service status, not copied tables here.

## Live topology

- `agent-telegram.service` is the allowlisted remote conversational gateway. It
  polls Telegram, uses a small local control model for validated intents and prose,
  and records private conversation context outside Git.
- `agent-ecosystem.timer` and `.path` activate the serialized intake/preparation/
  executor pipeline. Agent work is represented by durable JSON job records.
- `agent-watchdog.timer` runs deterministic health checks every three minutes and
  periodically enqueues one deduplicated Steward review.
- Lemonade serves local models on loopback. Model inventory and resource state are
  sampled when work is queued; the recorded choice is retained with the job.
- OpenCode runs prepared role packets as user `david`. A zero process exit currently
  proves only executor termination, not semantic task completion. This is known
  architectural debt and notifications must not overstate it.

## Durable flow

Telegram or local intake -> validated intent -> queued agent task -> role/context
packet -> scheduler -> executor -> durable output -> dependent outbox -> Telegram.

Append-only events live in `logs/runs/*.jsonl`; job and outbox state lives in
`state/jobs/`; private Telegram history lives in `state/conversations/`. Generated
runtime state is not committed.

## Roles and custodianship

Spawnable Markdown roles live in `roles/`. Stewards choose recurring maintenance
cards, Auditors establish evidence and invariants, and Refactorers apply bounded
repairs. Their authority remains limited by each role and `AGENTS.md`. OOP is
forbidden; use functions, plain data, explicit transitions, and composition.

## Safety and operation

The executor runs as `david`, never root. Its OpenCode policy blocks obvious
privileged, package-management, destructive, service-management, push, and web
actions, but shell containment is not a complete security boundary. Telegram is
allowlisted. `./scripts/ecosystem pause` is the dispatch kill switch.

The operational commands and unit installation procedure are maintained in
`docs/operations.md`; current implementation limitations are maintained in
`docs/architecture-assessment.md`. Verify changing facts with `systemctl --user`,
the job records, and the append-only events rather than trusting this summary.
