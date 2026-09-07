# Telegram task list, reminders, and agent conversations

David's requested use case, recorded by Astra, 2026-09-07.
Status: product requirements / future implementation input, not implemented or
activated. This captures an example of the ecosystem's intended flexibility; it
does not silently expand the currently running MVP implementation packet.

## Capture and maintain tasks through Telegram

David can tell Coin in natural language that he has a new pending task. Coin
records it durably, optionally with a due time, a reminder time, or both. These are
distinct: when something is due need not be when David wants a reminder.
The same Telegram interface supports reviewing, finding, updating, completing,
reordering, reprioritising, and deferring tasks and reminders.

Cointelprofessional must also be able to read and write the same authorized task
list, either directly through its permitted tools or by dispatching an agent with
the needed scoped access. Do not create separate, diverging lists for each role.
It should be able to use reasoning to prioritise, reconsider ordering, identify
related obligations, search semantically across notes, retrieve useful context,
and propose or make authorized changes—not merely match keywords or dates.
Preserve explicit user commitments; an agent's priority judgment is not permission
to silently change a due date or mark unfinished work complete.

## Periodic Reminder role

A Reminder role periodically reviews pending tasks and their notes, due/reminder
times, recent changes, and previous reminders. It can exercise judgment about what
deserves David's attention and dispatch useful contextual reminders through the
shared outbox to Telegram. This is meaningful review, not just a cron message or
a requirement to send filler on every poll. Deterministic due/reminder tracking
must remain dependable alongside model judgment.

Each review is a bounded admitted run; a role need not hold an inference lease
between polls. Poll cadence, timezone/ambiguous-time handling, reminder repetition,
snoozing, and notification preferences need explicit policy during implementation.
No numerical defaults were requested here. Repeated polls and crash replay must
not create duplicate tasks or accidentally resend the same reminder.

## Shared outbox and two-way agent contact

Any running agent can submit an outbound message for David via the shared outbox:
an event update, discovery, result, concern, question, or reminder. It need not be
a reply to an inbound message. Sending remains gateway-owned; agents do not gain
Telegram credentials or independent direct-send paths.

Preserve outbound message identity, originating agent/role, relevant work identity,
and optional task/conversation links. Coin can direct David's Telegram response
back to the agent and work in question. An explicit Telegram reply supplies a
direct relationship; otherwise use authorized context and ask when ambiguous.
An ended agent run need not stay alive: its durable context supports a newly
admitted continuation. Routing a reply does not bypass authority or resource checks.

For example: David adds a task with a Friday deadline; Reminder later points out
that preparation is still needed; David replies “remind me tomorrow morning”;
Coin associates that reply with the correct task/reminder and records the change.
No fake inbound message should be needed to originate the reminder.

## Persistence and boundaries

Use the ecosystem's filesystem source of truth, stable task identities, explicit
state changes, and local-only inference. Runtime history is append-only JSONL;
projections must not rewrite that history. Keep generated task/reminder records
out of Git; version schemas, tests, templates, and operational documentation.

Access is to the appropriately authorized list and context, not all material on
the machine. The agent name Cointelprofessional does not authorize copying Avnet,
AMD, partner, or customer information into this personal system or Telegram.
Task capture and prioritisation do not themselves authorize executing the task,
programming hardware, publishing information, or making external commitments.

## Implementation and acceptance follow-up

The canonical outbound design must cover unsolicited messages and replies without
losing either capability. Define its identity, destination authorization, reply
correlation and replay behavior before assigning implementation. Separately define
the task-list owner and bounded Reminder review contract.

Acceptance must demonstrate Telegram task capture and editing, independent due
and reminder times, shared role access, useful retrieval/prioritisation, reminder
deduplication, completion/snooze handling, and a reply routed back to the correct
task and originating agent context. No deployment or scheduling activation follows
from this documentation request.
