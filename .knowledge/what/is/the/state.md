---
status: green
revised_at: "2026-09-26T09:02:28+10:00"
---

State of CointOS against its definition in `what/is/cointos.md`. For live health, use `cointos-health --json`; this leaf is not a health check.

**Deployment.** Source is on branch `docs/cointos-mvp-bringup`, pushed to `origin`. Installed runtime at `~/.CointOS` matches source, including the knowledge tree; its `where/am/i.md` is rewritten by the installer for the installed location. Rendered unit files under `~/.config/systemd/user` run from `~/.CointOS`. The root-owned survival plane is absent. Do not access Avnet/professional data.

**Runtime data.** Job, conversation, control-turn, inference-run, supervision, incident, verification and log history were deliberately wiped on 2026-09-26 at David's request. Retained: config, secrets, `state/telegram-offset`, backend-profile qualifications, scheduling/resource policy, and the lease ledgers (`inference-capacity.json`, `inference-proxy.json`, `workload-control.json`), which carry fencing generations and hold only released, revoked or quiescent leases.

**What works (the "kernel").** Durable filesystem job records; demand-driven `agent-executor@` lanes; model-neutral backend profiles with fenced reload/rollback; priority pre-emption with parked OpenCode session resume; an admitted inference proxy with per-job leases and credentials; automatic survivor escalation with backoff; read-only `cointos-health` and `cointos-incident` commands. Qwen3.8-27B (the minimum competent worker model) has an evidence-backed two-lane ceiling; Qwen3.5-4B is pinned for control and contact. Automatic 1→2 growth, idle 2→1 shrink and two simultaneous workers have each worked live. Standard `tests/` discovery passes 837 tests.

**What is unproven live.** Stability under sustained autonomous load; Sole Survivor recovery (both attempts in the last incident failed; the rewritten prompt and escalation have not run live); sibling cancellation; pressure priority; multi-model selection; throughput with MTP.

**Cointelprofessional (Coin).** Telegram contact with a fast reply path and a deep control-turn worker. The deep turn has Coin's own tools (status, task progress, cancel, queue, dispatch pause/resume, forget conversation) plus the full `kt_*` knowledge-tree tool set via `ecosystem/knowledge_tools.py`. Tree tools have been verified in the unit's sandbox but not yet exercised by Coin in a live conversation.

**What is missing against the definition.**
- **Roles:** all `roles/*.md` files are empty. The target steward/manager/worker classes are not written (`what/is/the/intended/replacement/for/existing/agent/roles.md`).
- **Knowledge-tree work queues:** no layout or item shape exists yet.
- **Autonomous spawning:** nothing spawns agents when capacity is free. Work comes only from Telegram and the watchdog's periodic `steward-tasks/` deck, so the GPU idles without prompting.
- **Idea pipeline:** no idea intake, and no chunking or state tracking.
