---
status: green
revised_at: "2026-09-27T17:00:00+10:00"
---

CointOS is David's personal, local-first, autonomous agent ecosystem, developed in `/home/david/Projects/CointOS`. It is not a tool David "uses" turn by turn. It runs by itself, continuously, and keeps the GPU busy with useful work.

**What it does, in perpetuity:**

- **Agents spawn, look around, act, and recede.** An agent is spawned and given a role. It orients itself (expedited by its role and by knowledge trees), decides by its own judgement what needs doing, does a piece of it, and goes back into the void. This repeats indefinitely.
- **Three role classes.** A steward class keeps the system alive: Coin and maintenance stewards. A managerial class proposes work through the daemon API: decomposition, ordering, review and audit. A worker class carries those queues out. See `what/are/the/cointos/roles.md`.
- **Work sources.** Agents carry out work David has submitted as to-be-done, and they maintain and improve the system itself. They are not limited to either.
- **Where work lands.** Project work happens in ordinary git repositories under `~/Projects/`.
- **Idea pipeline.** David submits commands and product requests. Without further prompting, agents advance them through bounded stages of decomposition, implementation, testing, review, integration and audit. Every level, including decomposition and recomposition, leaves a checkable artifact and a smaller explicit frontier for the next stage.
- **Remote control.** The system is largely controllable from afar through Cointelprofessional ("Coin") on Telegram, which must essentially never be unavailable. Coin reads and edits knowledge trees directly.
- **Deep knowledge-tree integration.** Agents orient, record and hand off through knowledge trees; the daemon owns queues in the runtime and publishes them as knowledge-tree answers.
- **Harnessed local intelligence.** Local models do the work in a well-harnessed, curated way: small concrete tasks, bounded context, review.

**Agents vs. GPU time (the kernel analogy).** A scheduler doles out GPU time to agents the way a kernel doles out CPU time to processes. Agents live above individual GPU requests. They persist while waiting for GPU time, which gives long-term parallelism: many agents alive, a few lanes busy at any instant. Agent lifetimes are medium-length and transient.

**Workstation first.** The machine must remain fully usable as David's workstation at all times. The desktop and his own work outrank autonomous agents, including his own agent sessions, both hosted (Claude Code, Codex) and local (OpenCode). Autonomous work fills capacity David is not using and never makes the desktop sluggish.

**Utilisation.** Subject to the above, the GPU should be doing something most of the time, without David having to do much.

**Stability.** The system must be very stable. Mechanical safeguards stop distressed work, preserve tasks and recover known service failures. Catastrophic diagnosis and repair are for David to bring in a stronger agent remotely; an autonomous Sole Survivor agent is not on the current roadmap. Stability comes from simplicity first and safeguards second (`how/to/keep/cointos/simple.md`).

**Acceptance.** David expects to recognise working behaviour when he sees it: left alone, the GPU stays busy, commands and queued work visibly advance, Coin always answers, and nothing falls over. The measurable version is in `what/is/the/spec.md`.
