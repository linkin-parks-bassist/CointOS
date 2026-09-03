# Architecture assessment

Status: functional prototype requiring consolidation before scale.

## Sound foundations

- Local-only inference, durable filesystem state, append-only evidence, systemd
  supervision, role documents, typed job kinds, dependency-aware outbox, explicit
  model decisions, and separate responsive/control versus worker inference.

## Structural debt

- `telegram.py` mixes transport, intent routing, orchestration, queries, memory,
  presentation, and retry behavior.
- `cli.py` owns persistence primitives and unrelated application use cases.
- Job JSON has no versioned schema, repository abstraction, or formal transition table.
- Several state queries scan files ad hoc and return subtly different concepts.
- Presentation is stringly typed and distributed across transport/outbox/model prompts.
- Executors cannot yet checkpoint/resume, enforce all destructive boundaries, or
  provide trustworthy multi-worker resource admission.
- Executor exit status is currently mistaken for semantic task completion. Declared
  artifacts and acceptance checks need validation before success can be reported.
- Tests cover components but not crash consistency and full service-level scenarios.

## Refactor direction

1. Define versioned domain records: Job, AgentIdentity, Message, Approval, ModelLease,
   Trigger, and Event, with validated state transitions.
2. Put persistence behind repositories supporting atomic compare-and-set and indexes.
3. Establish ports for inference, executor, messaging, clock, scheduler, and host facts;
   keep Telegram, Lemonade, OpenCode, filesystem, and systemd as adapters.
4. Route typed Commands to domain Services and emit Events; render user messages from
   typed Views rather than internal records or model output.
5. Add lifecycle/query projections so exact questions use facts, not model memory.
6. Add property/state-machine tests, crash injection, replay tests, and architecture
   dependency checks before increasing worker concurrency or privilege.

An initial `queries` boundary now demonstrates this direction: high-confidence
lifecycle language is resolved to a typed query, authoritative projections answer
it, and the model is limited to ambiguity and presentation rather than factual authority.

No more major feature growth should bypass this consolidation milestone.

## Background ownership

Stewards continuously reconcile system health and choose maintenance assignments.
Auditors investigate architectural and behavioral correctness without casually
implementing their own recommendations. Refactorers consume evidenced, bounded
findings and produce independently reviewable improvements. This separation is a
workflow, not an excuse for role proliferation; all share the binding principles
in `docs/core-engineering-principles.md`, including the total prohibition on OOP.
