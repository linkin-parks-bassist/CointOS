---
status: "unverified"
created_at: "2026-09-16T10:35:57+10:00"
scope: "project local"
source: "ecosystem/control_agent.py, control_runtime.py, control_turns.py, control_worker.py and service definition inspected and changed 2026-09-16"
updated_at: "2026-09-16T10:45:44+10:00"
---

Cointelprofessional has two distinct inference stages. The fast Telegram first-contact lane uses Qwen3.5 with a deliberately short response for low prefill latency. The deep/action lane uses Qwen3.8 with the canonical 32000-token output allowance.

Authenticated allowlisted Telegram turns can inspect live status and recent errors, list roles, queue agent tasks, amend the latest pending task, pause or resume dispatch, clear conversation history, and publish a follow-up. Queue/amend converts the already-accepted contact identity into the accepted `contact_requested` authority profile and a durable task contract; it no longer exposes a tool that always refuses. The tool may select an active workspace by configured id or canonical path, otherwise the first active workspace is used. Role, model, and agent name are optional hints.

Cancellation/preemption and a broader typed operating surface are still absent. Status exposes active progress, but there is no dedicated per-task progress query. Deep failures and dead deep workers retain and requeue the turn without a fixed attempt ceiling; the former three-attempt terminal gate and ten-minute SIGALRM are removed.

Live correction: if the fast lane fails and no initial Telegram response was delivered, deep control may not choose `finish_silently`; it must publish a visible follow-up. A retained test turn exposed this after its ghost allocation was reconciled and Qwen3.8 completed without sending text. Source now enforces visible delivery in that branch.
