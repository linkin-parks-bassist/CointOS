---
verified_at: '2026-09-11T17:26:34+10:00'
verified_by: codex /root
scope: project local
source: 'git show 8edeadd^:AGENTS.md; docs/operations/local-worker-view.md; agent_notes/0022-aster-packet-audit-and-timeout.md; local-opencode-capacity-canonical-test JSONL; David briefing correction 2026-09-11'
verification: Checked launch policy and dispatch preference; incorporated the rule
  that worker briefs must not duplicate or prime mandatory knowledge-tree bootstrap
  behavior.
review_when: Recheck when the admission gate, observable launcher, viewer pool, or concurrency policy changes.
---

Launch local Qwen/OpenCode workers through the existing admission gate with
`scripts/opencode_observable.py`; do not use a naked background inference command.
The worker must remain locally attachable with retained JSONL evidence. In an
active driver session, use the canonical tracked viewer pool and publish the exact
session/attach command. Closing or losing a viewer must not stop or restart its
worker. Keep listeners loopback-only and ephemeral.

Dispatch only 1–3 genuinely independent, bounded jobs by default; eight slots are
capacity, not a utilization target. Bound jobs by a small deliverable, exact write
scope, necessary evidence, authority, and task-derived stopping conditions. Never
give local agents elapsed-time limits or arbitrary time budgets; reduce scope
instead. Read `docs/operations/local-worker-view.md`
before dispatch because driver/AFK window handling and the bounded reusable monitor
pool are operational policy, not general desktop-presence inference.

Follow the global `~/.knowledge/how/to/brief/agents.md` procedure. Do not put
knowledge-tree startup instructions or `where/am/i.md` directions in the brief;
the mandatory AGENTS.md/skill chain owns discovery, and prompting the behavior
would invalidate observations of that chain. Include only task-specific knowledge
pointers that are genuinely needed. Do not point a small worker at an entire large
plan or ask it to rediscover field names across the plan corpus. A forbidden broad
glob is still possible under `--auto`; monitor actual tool use and stop on
demonstrated scope expansion. That stopping condition is tied to authority/scope,
not elapsed time.
