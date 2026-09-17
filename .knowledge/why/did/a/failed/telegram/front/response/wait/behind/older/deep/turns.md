---
status: "unverified"
created_at: "2026-09-17T16:29:40+10:00"
scope: "local"
source: "control-turn records telegram-999135396 through 999135399; agent-control-worker unit; live 2026-09-17 state transitions"
---

Telegram turn `telegram-999135398` (`t3st`) failed its fast Qwen3.5 path with `JSONDecodeError: Expecting value` and entered deep_state queued with no visible response. `agent-control-worker.service` was configured with exactly two workers; both were occupied by older recovered deep turns (`telegram-999135396` and `telegram-999135397`). The inference scheduler never saw the newer turn until one controller finished, so control-worker process count became a head-of-line gate in front of the actual priority/resource scheduler.

Live recovery evidence: the later `TEST` turn succeeded through the independent fast path, `sploop` then completed and delivered, and `t3st` moved from queued to running when a controller slot opened. Telegram transport and inference were live; the user-visible silence was fast-path failure plus controller-pool queueing.

Unresolved design fix: controller concurrency should not be the resource-admission policy. Durable deep turns should reach the inference scheduler promptly, or a failed front path should deliver a truthful immediate acknowledgement while its deep result waits. Preserve bounded process behavior without silently serializing high-priority Cointelprofessional turns behind arbitrary worker count.
