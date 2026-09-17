---
scope: project local
status: "unverified"
source: "Git diff, installed services, managed-worker sessions, watchdog state, and live reconciliation evidence 2026-09-17"
review_when: Update after material repository, installation, or live-service changes.
updated_at: "2026-09-17T18:59:13+10:00"
---

Development is on branch `docs/cointos-mvp-bringup`. Commits through `3193d72` are pushed. The current source patch is installed and pending commit.

Requested-model routing now honors an explicit verified task-qualified model before normal largest-model ranking and records a durable fallback reason. Live local jobs selected Qwen3.8 when requested after removing artificial capability labels. Historical terminal-agent facts are filtered from the Cointelprofessional lifecycle prompt.

Inference recovery now closes two additional ghost families: processless worker leases after a verified global client stop/model unload, and final cancellation of a parked session whose physical sequence was already released. Managed executor restart recovery now also recognizes a durably already-closed runner, reconstructs its launch proof from `runner_close_outcome`, and promotes an exact retained OpenCode session to `ready`/`continuing`. The stranded session `ses_f5185dc4fffe35QqWdheR4e2Mi` live-qualified that repair across later scheduler boundaries.

The installed watchdog now runs subsystem-owned reconciliation every tick for native inference, operator sessions, managed jobs, control turns, and inference capacity/proxy credentials. It persists each result plus the eligible control-turn head in `state/watchdog.json`. Persistent deterministic findings no longer hot-spawn a broad Steward every tick; qualitative review jobs obey `steward_review_seconds`. An installed tick recorded all new fields and a second tick left no active watchdog job.

User-session CointOS remains operated as one generation through `scripts/cointos-system {start|stop|restart|status}`. The latest restart returned the models, proxy, resource guard, Telegram, control worker, notifier, ecosystem triggers, and watchdog timer online. Source compilation, focused temporary-root checks, installed reconciliation, exact-session continuation, and `kt prove --local --no-stamp` pass; no regression tests were added.
