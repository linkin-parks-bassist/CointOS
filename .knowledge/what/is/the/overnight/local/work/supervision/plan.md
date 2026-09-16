---
status: "unverified"
created_at: "2026-09-15T00:00:58+10:00"
scope: "local"
source: "David local-worker scope and observable-supervision policy, reconciled 2026-09-17"
updated_at: "2026-09-17T09:56:37+10:00"
---

For unattended or overnight local work, use one observable Qwen3.8 worker at a time through `scripts/opencode_observable.py` with `COINTOS_VIEW_MODE=afk`. Publish a fresh view record and retain the exact OpenCode session. Do not infer progress from a PID or token counter; inspect completed tool calls, artifacts, terminal events, and resource closure.

The coordinator owns architecture, decomposition, policy interpretation, integration, acceptance, installation, commits, and knowledge maintenance. Give Qwen one closed transformation whose files, interface, required branches, forbidden side effects, and stopping condition are already decided. A cohesive slice may span related functions, but it must contain no open design choice. If the worker starts reconstructing the system or describing the task as complex, stop and dissolve the assignment further.

Do not assign arbitrary elapsed-time, attempt, output, or evidence ceilings. OpenCode owns compaction in the retained session; terminal length continues that exact session. Cancellation or preemption must preserve recoverable work and close resources only with evidence. Never use `beep.py` or send external notifications merely to supervise work.

MVP policy remains production-code first: do not write new regression tests unless David explicitly changes that policy. Existing focused checks and bounded direct smoke checks may verify a change. After each worker finishes, inspect the diff, run proportionate checks, update owning KT leaves and `what/is/broken.md`, install reviewed production changes where appropriate, and keep the repository clean.