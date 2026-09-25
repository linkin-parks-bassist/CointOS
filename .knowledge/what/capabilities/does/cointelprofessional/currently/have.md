---
status: green
revised_at: "2026-09-25T17:32:19+10:00"
---

Cointelprofessional has a fast routing/contact stage on Qwen3.5 and a deep/action
stage on Qwen3.8 with the canonical 32000-token output allowance. The Qwen3.5 stage
now returns a structured decision with an optional visible response and an explicit
`deep_required` boolean. This supports four outcomes: reply only, reply plus deep
work, intentional silence plus deep work, or intentional silence with no deep work.
The last outcome completes durably without a Telegram send and leaves no turn for a
deep worker to reserve. The decision is requested through native tool calling. A visible plain-text answer
is preserved as the fast reply and conservatively requests deep work when the model
does not honor the structured contract; a failed or empty front retains deep work.
Formatting noncompliance therefore cannot suppress a useful response or masquerade
as intentional silence.

Direct managed Qwen3.5 probes accepted the routing contract and chose visible replies
with `deep_required: false` for completed celebratory exchanges. The exact silent/no-deep lifecycle
is covered by an injected decision check; natural selection of silence remains a
model judgment that may need prompt tuning from live conversations.

Authenticated allowlisted Telegram turns can inspect live status and recent errors,
list roles, queue agent tasks, amend the latest pending task, pause or resume
dispatch, clear conversation history, and publish a follow-up. Queue/amend converts
the already-accepted contact identity into the accepted `contact_requested`
authority profile and a durable task contract. The tool may select an active
workspace by configured id or canonical path, otherwise the first active workspace
is used. Role, model, and agent name are optional hints.

Caller-scoped cancellation is available for queued, ready, running, and awaiting-verification agent tasks. Running cancellation safely closes the runner and resources, and now takes precedence over a simultaneous finite-budget continuation. General arbitrary preemption and a broader typed operating surface remain incomplete.
`inspect_task_progress` provides a dedicated caller-scoped durable task-progress query in addition to aggregate status.
Deep failures and dead deep workers retain and requeue the turn without a fixed
attempt ceiling; the former three-attempt terminal gate and ten-minute SIGALRM are
removed.

If the fast lane fails and no initial Telegram response was delivered, deep control
may not choose `finish_silently`; it must publish a visible follow-up. This is
distinct from a successful explicit front decision to remain silent.
