---
status: "unverified"
created_at: "2026-09-14T23:57:44+10:00"
scope: "local"
source: "Actual unit inventory, drained core inactive check and successful installer 2026-09-15"
updated_at: "2026-09-15T08:53:19+10:00"
---

On 2026-09-14 David explicitly requested activation. Installed proxy, Telegram gateway, control workers, notifier, resource guard, inbox path and ecosystem/watchdog timers were started. Ecosystem/watchdog are oneshots and legitimately return inactive/dead after success; timers remain active. Activation exposed historical OpenCode sidecar status enumeration and null legacy scheduling authority defects, repaired in cli.status and scheduler.priority, deployed at a drained service boundary. Restarting agent-models loaded the configured pinned small control model while preserving Qwen3.8-27B at one 131072-token slot; small4B runs two 16384-token sequences. A real installed managed request returned READY and durably closed sequence/worker; the default fast control path also returned visible text locally. No test Telegram message was sent. Fresh active states had zero restart counts and no warning-level service journal entries. This verifies startup and basic inference, not saturated priority, end-to-end Telegram, restart recovery or semantic task completion. Next check: real request handling and saturation/recovery qualification.

Exact user service identifiers are agent-inference-proxy.service, agent-telegram.service, agent-control-worker.service, agent-notifier.service and agent-resource-guard.service. A fresh systemctl --user is-active check returned active for all five on 2026-09-15. A failed probe using guessed cointos-prefixed names returned inactive for nonexistent identifiers and did not indicate these services were offline; use the actual agent-prefixed identifiers.

Drained upgrade2026-09-15: all five core units were verified inactive before payload installation completed. The inbox watch is agent-ecosystem.path, not guessed agent-inbox.path; the multi-unit stop returned exit5 for that nonexistent name while correctly stopping the actual named core units. Exact inventory also includes agent-ecosystem.timer and agent-watchdog.timer. Runtime/source spine divergence was explicitly reconciled; installer completed with rollback payload and preserved runtime state/config/knowledge. No model unit restart/reallocation occurred. Next check: restart actual core/watch units and perform installed managed acquisition.
