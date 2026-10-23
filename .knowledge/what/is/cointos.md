---
status: green
revised_at: "2026-10-23T19:19:13+11:00"
---

CointOS is a personal, local-first autonomous agent ecosystem developed in `~/Projects/CointOS`. It runs continuously, keeping the GPU busy with useful work rather than requiring turn-by-turn direction.

**Continuous work.** Agents spawn, orient from their role and knowledge trees, judge what needs doing, leave one checkable result and recede. Stewards observe and tend the system; managers decompose, order, review and audit; workers carry out queued stages. Coin is the separate control service. Periodic stewards may garden knowledge while leaving product implementation to project agents; gardeners maintain all CointOS-owned trees. The roles owner defines permissions and budgets.

Agents handle submitted work and discover improvements themselves. Product work lands in ordinary Git repositories under `~/Projects/`. Commands advance through bounded decomposition, implementation, testing, review, integration and audit without further prompting. Every level leaves a checkable artifact and a smaller explicit frontier. Retrospective auditors compare accepted work with its specification and queue managerial correction for semantic gaps.

**Control and knowledge.** Telegram's Cointelprofessional (“Coin”) should remain available. It reads and edits knowledge trees and schedules disk-backed model wakes for deadlines, tasks, logical services and exact process exits. Restart/reboot must not lose definitions or pending delivery, and process interruption must not imply success. Coin checks actual OS state before following up: decisions can settle outside Telegram. Wakes use normal tools and replies. Routine mistakes and recoverable failures stay local. Unsolicited failure updates require exhausted recovery or a concrete CointOS workflow deficiency worth improving; qualifying explanations have durable Telegram delivery. Engineering resolves test placement and sequencing. Agents orient, record and hand off through knowledge trees; only the daemon publishes scheduler queues.

**Local intelligence.** Ordinary agents use local models with concrete tasks, bounded context and independent review. Agents live above individual model requests, like processes above CPU scheduling: many conversations remain alive while only a few GPU lanes execute. They persist through lane waits; ordinary agent lifetimes are transient. The scheduler allocates GPU time without turning a lost process or cache into completed work.

**Workstation first.** The desktop and the user's work outrank autonomous work, including hosted Claude Code/Codex and local OpenCode sessions. Autonomous agents fill unused capacity and must not make the workstation sluggish. Subject to that constraint, the GPU should do useful work most of the time without repeated user intervention.

**Stability.** Simplicity comes first (`how/to/keep/cointos/simple.md`). Mechanical recovery preserves tasks and restores known failures. When it cannot restore progress, the default is a broadly equipped Operator that diagnoses the obstruction, repairs it and returns work to checked ordinary execution. Fatal daemon startup has an independent remote Codex route outside the unavailable local gateway; restoration evidence and current health govern handback. Deployment/acceptance owners distinguish source implementation from installed proof. This focused route does not establish broader autonomous Sole Survivor coverage, which remains off the roadmap.

**Acceptance.** Left alone, the GPU stays usefully busy, commands and queues advance, Coin answers and the workstation stays usable. Green checks and isolated fixtures alone do not establish this behaviour. `what/is/the/spec.md` defines measurable acceptance; architecture, roles and the remaining plan own details.
