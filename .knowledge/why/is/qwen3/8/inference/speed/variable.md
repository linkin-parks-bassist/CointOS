---
status: "unresolved"
created_at: "2026-09-15T22:19:34+10:00"
scope: "CointOS local inference"
source: "system journal Qwen3.8 Lemonade telemetry and MTP initialization from 2026-09-03 and live llama.cpp /metrics on 2026-09-15"
checked_at: "2026-09-15T22:19:34+10:00"
blocker: "No controlled same-prompt record pairs slow and fast periods with all effective runtime variables."
next_check: "Run repeated same-prompt A/B benchmarks after active work, recording metrics, slots, command, context occupancy, and power state."
---

Qwen3.8's current roughly 20–25 token/s decode rate is not a newly introduced MTP mode. System journal evidence from 2026-09-03 already records `common_speculative_init_result` creating the Qwen3.8 MTP draft context and many completions around 19–27 token/s. The same historical period also contains completions around 3–13 token/s, particularly amid multiple active requests and larger prompt/context states. Current llama.cpp metrics report one busy slot and high draft-token acceptance.

The exact cause of David's previously observed roughly 8 token/s period is not yet isolated. Plausible variables supported by the logs are concurrent active sequences, accumulated context length, backend load, and request shape; `--parallel 1` and MTP presence alone do not explain it.

Blocker: there is no controlled same-prompt benchmark record pairing the slow and fast periods with complete effective backend settings, active-slot count, context occupancy, and power/clock state.

Next check: after active production work finishes, run repeated same-prompt A/B benchmarks while recording `/metrics`, `/slots`, effective llama-server command, context length, and system power/clock state. Change one backend option at a time.
