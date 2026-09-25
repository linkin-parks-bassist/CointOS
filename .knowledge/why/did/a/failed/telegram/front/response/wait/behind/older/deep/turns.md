---
status: green
revised_at: "2026-09-17T19:53:59+10:00"
---

Telegram turn `telegram-999135398` (`t3st`) failed its fast Qwen3.5 path with `JSONDecodeError: Expecting value` and entered deep_state queued with no visible response. `agent-control-worker.service` was configured with exactly two workers; both were occupied by older recovered deep turns (`telegram-999135396` and `telegram-999135397`). The inference scheduler never saw the newer turn until one controller finished, so control-worker process count became a head-of-line gate in front of the actual priority/resource scheduler.

Live recovery evidence: the later `TEST` turn succeeded through the independent fast path, `sploop` then completed and delivered, and `t3st` moved from queued to running when a controller slot opened. Telegram transport and inference were live; the user-visible silence was fast-path failure plus controller-pool queueing.

The gate is removed in `ecosystem/control_worker.py`. The supervisor no longer reads `AGENT_CONTROL_WORKERS` or stops reservation when `len(active)` reaches an arbitrary maximum. On each loop it reserves and forks every currently eligible durable turn until `reserve_next` returns none; each child then reaches `managed_inference.request`, where the actual priority and resource scheduler may run, queue, or preempt it. Child reaping, reservation rollback on fork failure, signal handling, and idle waiting are unchanged. Source compilation passes and the installed generation contains the repair. A multi-turn Telegram saturation qualification remains useful but is no longer an implementation blocker.
