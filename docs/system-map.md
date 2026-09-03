# System map

Last reconciled: 2026-09-04 (Australia/Sydney).

This is a factual recovery aid, not a task transcript. Runtime details that change
frequently belong in `state/` and service status, not copied tables here.

## Live topology

- `agent-telegram.service` is the allowlisted remote conversational gateway. It
  durably records each update, asks resident GLM for a bounded generated first
  response, and never runs deep control or result presentation in the polling path.
- `agent-control-worker.service` runs up to two durable Qwen deep-control turns in
  parallel. Typed terminal decisions either publish material new information or
  finish silently after the first response.
- `agent-notifier.service` presents and delivers dependent agent results without
  blocking Telegram update receipt.
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

Telegram -> durable control turn -> GLM first response -> Qwen deep decision/tool
action -> optional follow-up. A dispatched task then flows through role/context
packet -> scheduler -> executor -> provisional output -> independent Verifier ->
accepted/rejected root state -> dependent outbox -> background notifier -> Telegram.

Append-only events live in `logs/runs/*.jsonl`; job and outbox state lives in
`state/jobs/`; control turns live in `state/control-turns/`; private Telegram history
lives in `state/conversations/`. Generated runtime state is not committed.

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
