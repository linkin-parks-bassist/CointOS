---
scope: project local
status: "unverified"
source: "Git, scripts/cointos-system, telegram-999135394 durable/audit evidence, installed services 2026-09-17"
review_when: Update after material repository, installation, or live-service changes.
updated_at: "2026-09-17T16:26:01+10:00"
---

Development is on branch `docs/cointos-mvp-bringup`. Commits through `3193d72` are pushed and installed. Whole-system lifecycle and control-turn retry-backoff changes are installed and pending commit.

User-session CointOS now has one installed lifecycle command: `scripts/cointos-system {start|stop|restart|status}`. It stops triggers, oneshots, and long-running services together; reloads units; starts the whole long-running system plus triggers; and stops everything again if start fails. A live restart returned models, inference proxy, resource guard, Telegram, control worker, notifier, ecosystem triggers, and watchdog trigger as one generation.

This closed a mixed-version incident: Telegram turn `telegram-999135394` hot-retried `invalid inference capacity policy` more than 1,200 times because a 24-hour-old control worker interpreted the newly installed resource-policy schema with stale code. The whole-system restart stopped policy errors and recovered the retained turn into a stable deep attempt. Control-turn failures now use durable exponential retry backoff instead of immediate twice-per-second requeue.

Inference acquisition covers fresh routing, unloaded realization, idle reclamation, priority allocation, tool-boundary park/reacquire, failed-park rollback, ghost reconciliation, context rerouting, retained-session continuation, executor restart, and old-backend termination after Lemonade restart. The qualified GPU allocation capacity is 100 GiB; the 64 GiB sysfs value is informational.

The installed observable wrapper waits for and mirrors server-side assistant completion after CLI-visible tool calls rather than injecting duplicate user continuation prompts. Its live qualification is pending because a requested Qwen3.8 qualifier was silently routed to DeepSeek-Qwen3-8B; `requested_model` is recorded but currently inert.

Latest evidence: shell/source compilation, installed whole-system restart/status, cessation of policy-error audits, retained-turn recovery, direct wrapper stream checks, and 108 earlier focused inference/executor checks. No new regression test was added.