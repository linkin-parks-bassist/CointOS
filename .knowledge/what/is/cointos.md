---
status: green
revised_at: "2026-09-26T09:15:47+10:00"
---

CointOS is David's personal, local-first, autonomous agent ecosystem, developed in `/home/david/Projects/CointOS` and run from `~/.CointOS`. It is not a tool David "uses" turn by turn. It runs by itself, continuously, and keeps the GPU busy with useful work.

**What it does, in perpetuity:**

- **Agents spawn, look around, act, and recede.** An agent is spawned, is assigned a role, orients itself (expedited by its role and by knowledge trees), decides what needs doing by its own judgement, does a piece of it, and goes back into the void. This repeats indefinitely.
- **Two role classes.** A managerial class builds and maintains priority queues of work (decomposition, ordering, review, audit); a worker class carries those queues out. See `what/is/the/intended/replacement/for/existing/agent/roles.md`.
- **Work sources.** Agents carry out work David has submitted as to-be-done. They also maintain and improve the system itself. They are not limited to either.
- **Where work lands.** Project work happens in ordinary git repositories on disk under `~/Projects/`.
- **Idea pipeline.** David drafts ideas. Without further prompting, agents working through their roles break them into small, elaborated, manageable chunks, then implement, test, review and audit them. The dissolution design is in `what/is/architecture/of/cointos.md`.
- **Remote control.** The system is largely controllable from afar through Cointelprofessional, which must essentially never be unavailable.
- **Deep knowledge-tree integration.** Roles and agents orient, record and hand off through knowledge trees.
- **Harnessed local intelligence.** Local models do the work, in a well-harnessed, curated way: small concrete tasks, bounded context and review.

**Agents vs. GPU jobs (the kernel analogy).** A large-scale analogue of a kernel scheduler doles out GPU time to agents. Agents live at a higher level than active GPU jobs. They have state and persistence that carry them through pre-emption and temporary swap-out, giving long-term parallelism (long relative to process-level scheduling). Agent lifetime is medium-length and transient, but it outlasts any single GPU allocation. Scheduling contracts are in `what/is/intended/agent_scheduling.md`.

**Workstation first.** The machine must remain fully usable as David's workstation at all times. The desktop and his own work outrank autonomous agents: this includes user-driven agent sessions, both hosted (Claude Code, Codex and similar) and local (OpenCode on local models). Priority order: Sole Survivor, then Cointelprofessional, then user-driven sessions, then autonomous background work (`what/is/intended/agent_scheduling.md`). Autonomous work fills capacity David is not using, is pre-empted or suspended when he needs it, and must never make the desktop sluggish.

**Utilisation.** Subject to the above, the GPU should be doing something most of the time, without David having to do much of anything.

**Stability.** The system must be very stable. Safeguards, principally the Sole Survivor, must smartly and quickly take the system down and bring it back up when anything goes wrong.

**Acceptance.** No concrete MVP acceptance test is defined yet; David expects to recognise working behaviour when he sees it. The working hypothesis is that the system can be left alone, keeps the GPU busy, and visibly advances drafted ideas and queued work without falling over.

Implementation status and gaps against this definition are in `what/is/the/state.md` and `what/is/current/project_priority.md`. Do not infer live health from descriptions; use [runtime truth](../../where/is/runtime_truth.md).
