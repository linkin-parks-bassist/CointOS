---
status: "unverified"
created_at: "2026-09-16T10:35:57+10:00"
scope: "project local"
source: "ecosystem/telegram.py, control_turns.py, control_agent.py, control_runtime.py and service definition inspected and changed 2026-09-16; 793 source tests and direct managed Qwen3.5 decision probe"
updated_at: "2026-09-16T11:18:41+10:00"
---

Cointelprofessional has a fast routing/contact stage on Qwen3.5 and a deep/action
stage on Qwen3.8 with the canonical 32000-token output allowance. The Qwen3.5 stage
now returns a structured decision with an optional visible response and an explicit
`deep_required` boolean. This supports four outcomes: reply only, reply plus deep
work, intentional silence plus deep work, or intentional silence with no deep work.
The last outcome completes durably without a Telegram send and leaves no turn for a
deep worker to reserve. A malformed or failed front decision retains deep work so a
failure cannot masquerade as intentional silence.

A direct managed Qwen3.5 probe accepted the contract and chose a visible reply with
`deep_required: false` for a celebratory exchange. The exact silent/no-deep lifecycle
is covered by an injected decision check; natural selection of silence remains a
model judgment that may need prompt tuning from live conversations.

Authenticated allowlisted Telegram turns can inspect live status and recent errors,
list roles, queue agent tasks, amend the latest pending task, pause or resume
dispatch, clear conversation history, and publish a follow-up. Queue/amend converts
the already-accepted contact identity into the accepted `contact_requested`
authority profile and a durable task contract. The tool may select an active
workspace by configured id or canonical path, otherwise the first active workspace
is used. Role, model, and agent name are optional hints.

Cancellation/preemption and a broader typed operating surface are still absent.
Status exposes active progress, but there is no dedicated per-task progress query.
Deep failures and dead deep workers retain and requeue the turn without a fixed
attempt ceiling; the former three-attempt terminal gate and ten-minute SIGALRM are
removed.

If the fast lane fails and no initial Telegram response was delivered, deep control
may not choose `finish_silently`; it must publish a visible follow-up. This is
distinct from a successful explicit front decision to remain silent.
