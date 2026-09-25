---
status: "green"
revised_at: "2026-09-26T09:42:35+10:00"
---

State of CointOS against its definition in `what/is/cointos.md`. For live health, use `cointos-health --json`; this leaf is not a health check.

**Deployment.** Source is on branch `docs/cointos-mvp-bringup`, pushed to `origin`. Installed runtime at `~/.CointOS` matches source, including the knowledge tree; its `where/am/i.md` is rewritten by the installer for the installed location. Rendered unit files under `~/.config/systemd/user` run from `~/.CointOS`. The root-owned survival plane is absent. Do not access Avnet/professional data.

**Runtime data.** Job, conversation, control-turn, inference-run, supervision, incident, verification and log history were deliberately wiped on 2026-09-26 at David's request. Retained: config, secrets, `state/telegram-offset`, backend-profile qualifications, scheduling/resource policy, and the lease ledgers (`inference-capacity.json`, `inference-proxy.json`, `workload-control.json`), which carry fencing generations and hold only released, revoked or quiescent leases.

**What works (the "kernel").** Durable filesystem job records; demand-driven `agent-executor@` lanes; model-neutral backend profiles with fenced reload/rollback; priority pre-emption with parked OpenCode session resume; an admitted inference proxy with per-job leases and credentials; automatic survivor escalation with backoff; read-only `cointos-health` and `cointos-incident` commands. Qwen3.8-27B (the minimum competent worker model) has an evidence-backed two-lane ceiling; Qwen3.5-4B is pinned for control and contact. Automatic 1→2 growth, idle 2→1 shrink and two simultaneous workers have each worked live. Standard `tests/` discovery passes 837 tests.

**What is unproven live.** Stability under sustained autonomous load; Sole Survivor recovery (both attempts in the last incident failed; the rewritten prompt and escalation have not run live); sibling cancellation; pressure priority; multi-model selection; throughput with MTP.

**Cointelprofessional (Coin).** Telegram contact with a fast reply path and a deep control-turn worker. The deep turn has Coin's own tools (status, task progress, cancel, queue, dispatch pause/resume, forget conversation) plus the full `kt_*` knowledge-tree tool set via `ecosystem/knowledge_tools.py`. Coin has used them live over Telegram: a lookup and a leaf write both succeeded. Each call is audited as `control.kt_tool`.

**Autonomy loop (live since 2026-09-26, first rounds unreviewed).**
- **Roles:** `_base`, `_control-plane` (Coin), `sole_survivor`, `steward`, `manager` and `worker` are first drafts; prompts compose base, role and assignment (`what/is/the/intended/replacement/for/existing/agent/roles.md`).
- **Queues:** project knowledge trees, under `what/is/{urgent,queued,drafted}/`.
- **Spawner:** `agent-spawner.timer` is enabled and scans `~/Projects/CointOS` only (`how/does/the/cointos/spawner/choose/work.md`). The first manager survey is running on Qwen3.8-27B at roughly one tool call a minute; a steward waits for the second lane.
- **Lane floor:** `profile_minimum_parallel_sequences: 2` keeps idle work models at two lanes, but no reload to two has been observed yet.
- **Controls:** `cointos stop|go|halt|up` exist (`how/to/operate/cointos.md`); `halt` and `up` have not been exercised live.
- **Mixed generations:** after the 2026-09-26 deployments only Coin's units (Telegram, control worker) were restarted. The proxy, resource guard and notifier still run the previous module generation until a whole-system `cointos-system restart`.
