---
status: green
revised_at: "2026-10-22T08:10:44+11:00"
---

Acceptance requires independent live behavior, not ledger totals or green fixtures.

- Soak: two hours unattended with at least four live agents sharing the configured lane, checks green throughout and at least three accepted queue-item commits. Integrators signal checked acceptance and the daemon settles dependencies.
- Coin under load: ten Telegram messages during the soak receive visible model replies within fifteen seconds.
- Workstation: normal desktop use remains responsive; the user's local OpenCode work outranks background agents.
- Halt/up: halting during the soak leaves no CointOS process or loaded model; up resumes interrupted tasks.
- Kill: killing a native agent is detected and resumed within thirty seconds, returning checks to green.
- Pipeline: ordinary intake is autonomously decomposed, implemented, integrated and recomposed in bounded stages, meeting its own acceptance without manual decomposition. Test placement and sequencing decisions preserve all requirements and resume through recovery without user approval.
- Escalation: explicit questions survive history trimming and service restart until Telegram acceptance. Ownerless unheld blockage queues a notice after sixty seconds of observation even with the model unavailable; failed delivery retries, active recovery suppresses it, and resolution cancels pending blockage. Telegram acceptance proves transport, not reading or explanation. The brief independent notice must be followed through a durable model explanation. Every accepted outgoing part appears in the agreed rolling history, reply-to references survive rollover, and a clear authorised answer reaches scoped action and checked state rather than an unrelated conversation. Ambiguous sends or crashes before receipt persistence can duplicate delivery.

what/is/the/live/acceptance/evidence/for/cointos.md owns achieved evidence and limits; what/is/the/plan.md owns remaining execution.
